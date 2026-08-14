"""The level engine: bars in, levels and directional calls out.

Ties the pieces together. Bars arrive from the bus; the engine keeps a rolling
window per instrument, re-forms levels from the perceptually important points
in it, tracks price against those levels, and produces a call whenever price
comes into one.

Two things it is careful about, because both are easy to get wrong in ways that
do not show up until the results are being trusted:

**Levels are formed only from confirmed swings.** A turning point is not
knowable as one until the bars after it have printed, so `pips.as_of` filters
to what was visible. Without that the engine would draw levels through swings
nobody could have seen and then congratulate itself for respecting them.

**Levels persist across re-forming.** Re-deriving from a window would discard
the touch history that makes a level worth anything, so new candidates are
merged into the existing set rather than replacing it. A level rediscovered is
evidence about an old level, not a new one.
"""

from __future__ import annotations

import sqlite3
import statistics
import time
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from ..logging import get_logger
from . import confluence, patterns, pips, pivots, reactions
from . import levels as lv
from .models import Shape, Signal
from .volatility import Book as VolBook
from .volatility import Volatility

log = get_logger(__name__)

#: Bars kept per instrument. Enough to hold the swings that matter on a 5m
#: chart without the window itself becoming the thing being modelled.
WINDOW = 500

#: Perceptually important points pulled from the window. Roughly one per ten
#: bars: fewer and real swings are missed, more and noise becomes a level.
PIP_COUNT = 50

#: Re-form levels this often, in bars. Every bar would be wasted work — the
#: swings barely change — and never would let the set go stale.
REFORM_EVERY = 20

#: Bars after a shape completes before its outcome is counted. Long enough for
#: the move to develop, short enough that it is still attributable to the shape.
SHAPE_HORIZON = 12

#: The timeframes levels are built on. Defined in `confluence` and used here so
#: there is one list rather than two that drift — which they did: confluence
#: spanned 4h while the engine never built it, so combining across timeframes
#: was quietly looking for something that never existed.
LEVEL_INTERVALS: tuple[str, ...] = confluence.TIMEFRAMES

#: Venues that must report a bar before its consensus close is usable. Below
#: this the "median" is one venue's opinion wearing a median's clothes.
MIN_VENUES = 3

#: Quotes kept per instrument for the spread median.
SPREAD_WINDOW = 128

#: Bars read per (instrument, interval) when warming from the store. One window
#: is all the engine can hold; more would be read and immediately discarded.
SEED_BARS = WINDOW

#: An untouched level this far from price, in volatility units, is not going to
#: be tested soon and is only crowding the set. Touched levels are kept
#: regardless of distance — a level price has reacted at is worth remembering
#: precisely because price left it.
KEEP_VOL = 8.0

#: Resolutions held for a consumer that may not be draining them.
MAX_RESOLVED = 500

#: Ceiling per (instrument, interval), strongest kept. Without one a long
#: history accrues a level every few basis points, and at that density every
#: price is "at a level" and the model predicts nothing. Fifteen is roughly
#: what a person marks on one chart, which is the right order of magnitude —
#: the constraint is attention, not storage.
MAX_LEVELS = 15


@dataclass(slots=True)
class Consensus:
    """Median bar across venues, per instrument and interval.

    Bars arrive one venue at a time and several venues report the same bar.
    Without this the series took whichever venue published last, and the winner
    changed from bar to bar — so the swing detection was reading a series
    stitched together from different venues, injecting exactly the cross-venue
    disagreement this project exists to *measure* rather than suffer.

    The median is taken across whichever venues have reported that bar so far
    and recomputed as more arrive, so the estimate improves within the sweep
    rather than waiting for a venue that may never report.
    """

    #: (feed, interval) -> ts -> venue -> (high, low, close)
    _bars: dict[tuple[str, str], dict[int, dict[str, tuple[float, float, float]]]] = field(
        default_factory=dict
    )

    def observe(
        self, feed: str, interval: str, venue: str, when: int, high: float, low: float, close: float
    ) -> tuple[float, float, float] | None:
        """Fold one venue's bar in. Returns the consensus once enough agree."""
        key = (feed, interval)
        bars = self._bars.setdefault(key, {})
        at = bars.setdefault(when, {})
        at[venue] = (high, low, close)
        # Only the bars still being filled are worth keeping.
        if len(bars) > 4:
            for stale in sorted(bars)[:-4]:
                del bars[stale]
        if len(at) < MIN_VENUES:
            return None
        return (
            statistics.median([h for h, _, _ in at.values()]),
            statistics.median([low for _, low, _ in at.values()]),
            statistics.median([c for _, _, c in at.values()]),
        )


@dataclass(slots=True)
class Series:
    """A rolling window of one instrument at one interval."""

    feed: str
    interval: str
    times: deque[int] = field(default_factory=lambda: deque(maxlen=WINDOW))
    closes: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    highs: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    lows: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    since_reform: int = 0

    def add(self, when: int, high: float, low: float, close: float) -> None:
        # A bar arriving for a time already held is a correction, not a new bar.
        if self.times and when == self.times[-1]:
            self.highs[-1], self.lows[-1], self.closes[-1] = high, low, close
            return
        self.times.append(when)
        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)
        self.since_reform += 1

    @property
    def ready(self) -> bool:
        return len(self.closes) >= pips.MIN_POINTS * 4

    @property
    def due(self) -> bool:
        return self.since_reform >= REFORM_EVERY


@dataclass(slots=True)
class Call:
    """A directional call at a level, with everything behind it."""

    feed: str
    interval: str
    level: lv.Level
    inference: reactions.Inference
    price: float
    time: float

    def to_signal(self, vol) -> Signal:
        # `probability`, not `probability_up`: quoting P(up) beside a *down*
        # call reads as the confidence in down when it is the confidence
        # against it. The base rate flips with it or the pair is not a
        # comparison. See reactions.Inference.probability.
        detail = (
            f"{self.inference.direction} from {self.inference.side} at "
            f"{self.level.price:.5g} — p={self.inference.probability:.0%} "
            f"vs {self.inference.base_rate:.0%} base, "
            f"push {self.inference.expected_push:+.2f}v"
        )
        return Signal(
            shape=Shape.LEVEL,
            feed=self.feed,
            venue="consensus",
            score=abs(self.inference.edge),
            detail=detail,
            features={
                "level": self.level.price,
                "probability_up": self.inference.probability_up,
                "probability": self.inference.probability,
                "expected_push_vol": self.inference.expected_push,
                "base_rate_up": self.inference.base_rate_up,
                "edge": self.inference.edge,
                "own_touches": float(self.inference.own_touches),
                "neighbours": float(self.inference.neighbours),
                "strength": self.level.strength(self.time, vol),
                "risk_vol": self.inference.risk_vol,
            },
            direction=self.inference.direction,
            interval=self.interval,
            time=self.time,
        )


def _read_bars(
    database: Path | str,
    feeds: Sequence[str],
    intervals: Sequence[str],
    bars: int,
) -> list[dict]:
    """Stored bars as bus-shaped payloads, oldest first.

    Shaped like a `prices.bars` message so the replay goes through exactly the
    same code the live path does. A separate warm-up path would be a second
    implementation of level formation, and the two would drift.
    """
    path = Path(database)
    if not path.exists():
        return []
    if not intervals:
        return []

    marks = ",".join("?" * len(intervals))
    where = f"interval IN ({marks})"
    params: list[object] = list(intervals)
    if feeds:
        where += f" AND feed IN ({','.join('?' * len(feeds))})"
        params.extend(feeds)

    rows: list[dict] = []
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)) as conn:
            conn.row_factory = sqlite3.Row
            for feed, interval in conn.execute(
                f"SELECT DISTINCT feed, interval FROM bars WHERE {where}",
                tuple(params),
            ).fetchall():
                found = conn.execute(
                    "SELECT feed, venue, interval, ts, high, low, close FROM bars"
                    " WHERE feed = ? AND interval = ? ORDER BY ts DESC LIMIT ?",
                    (feed, interval, bars * 8),  # several venues per bar
                ).fetchall()
                rows.extend(dict(row) for row in found)
    except sqlite3.Error as exc:
        log.warning("levels: could not warm from %s: %s", path, exc)
        return []

    # Oldest first, and grouped so every venue on one bar arrives together —
    # the consensus needs them adjacent to reach a quorum on that timestamp.
    rows.sort(key=lambda row: (row["ts"], row["feed"], row["interval"]))
    return [{**row, "time": row["ts"]} for row in rows]


class Engine:
    """Levels and directional calls for every instrument at once."""

    def __init__(
        self,
        *,
        window: int = WINDOW,
        pip_count: int = PIP_COUNT,
        intervals: tuple[str, ...] = LEVEL_INTERVALS,
        horizon: float = 3600.0,
        shape_horizon: int = SHAPE_HORIZON,
        charge_spread: bool = True,
    ) -> None:
        #: Whether the quoted spread is charged against every level call. On by
        #: default, because an uncharged edge is a gross number and acting on
        #: one is the mistake the cost exists to prevent.
        #:
        #: Off is for answering "what would this have said without the cost" —
        #: the two runs are directly comparable, since nothing else changes. It
        #: is deliberately not a threshold to tune: the cost is measured, and
        #: something measured is either charged or it is not.
        self.charge_spread = charge_spread
        self.shape_horizon = shape_horizon
        self.window = window
        self.pip_count = pip_count
        self.intervals = intervals
        self.vol = VolBook()
        self.tracker = reactions.Tracker(horizon=horizon)
        #: Pivots come from completed sessions, so they need no confirmation
        #: delay and exist before price has ever turned there.
        self.sessions = pivots.Sessions()
        #: Bars are per venue; levels are not. This makes them one series.
        self.consensus = Consensus()
        #: Shapes seen before and what followed. Independent of levels: a level
        #: is a price, a shape is not, so a double top repeats across
        #: instruments and prices where a level cannot.
        self.shapes = patterns.Library()
        #: Open shape instances, waiting for the horizon to say what followed.
        self._pending: dict[tuple[str, str], tuple[int, float, int]] = {}
        self._series: dict[tuple[str, str], Series] = {}
        self._levels: dict[tuple[str, str], list[lv.Level]] = {}
        #: The timestamp of the bar being processed. Held so that "what was
        #: knowable" is answerable at any point, including from a test.
        self._now: float = 0.0
        #: Touches that have resolved since anyone last looked, with the level
        #: they resolved at. Queued rather than pushed because the engine has
        #: no journal and should not grow one — a resolution is a fact about
        #: price, and who wants to record it is not the engine's business.
        self._resolved: list[tuple[lv.Level, reactions.Touch]] = []
        #: Recent quoted spreads per instrument, in basis points — the cost of
        #: taking any edge found here, measured all along and never charged.
        #: A window rather than a running value, so the cost can be a *median*.
        self._spread: dict[str, deque[float]] = {}
        #: Which interval carries the touch check, as history advances. Set
        #: only while replaying: `[(from_time, interval), ...]`, oldest first.
        #: Empty means "the finest series seen so far", which is right live.
        self._touch_eras: list[tuple[float, str]] = []
        self.calls = 0
        if not charge_spread:
            # Said out loud, once, because a disabled charge and an unarmed one
            # both record `cost_vol` of 0.0 and are indistinguishable in the
            # journal afterwards. A zero that was configured should not be
            # readable as a zero that went wrong.
            log.warning(
                "structures: spread costs disabled — every level call will be "
                "judged on its gross push, and cost_vol will read 0.0 for that "
                "reason rather than for want of quotes"
            )

    # --------------------------------------------------------------- levels

    def series(self, feed: str, interval: str) -> Series:
        key = (feed, interval)
        found = self._series.get(key)
        if found is None:
            found = self._series[key] = Series(feed, interval)
        return found

    def levels(self, feed: str, interval: str = "") -> list[lv.Level]:
        if interval:
            return list(self._levels.get((feed, interval), []))
        return [
            level
            for (this_feed, _), found in self._levels.items()
            if this_feed == feed
            for level in found
        ]

    def reform(self, series: Series, when: float) -> list[lv.Level]:
        """Re-derive levels from the confirmed swings in the window."""
        vol = self.vol.of(series.feed, series.interval)
        found = pips.points(list(series.times), list(series.closes), self.pip_count)
        visible = pips.as_of(found, when)
        candidates = lv.form(series.feed, series.interval, pips.turns(visible), vol)
        key = (series.feed, series.interval)
        merged = lv.merge(self._levels.get(key, []), candidates, vol)
        self._levels[key] = self.prune(merged, series.closes[-1], vol, when)
        series.since_reform = 0
        self._record_shape(series, visible)
        return self._levels[key]

    def prune(self, levels: list[lv.Level], price: float, vol, when: float) -> list[lv.Level]:
        """Drop levels that are not earning their place.

        A swing price never returned to is not a level, it is a swing. On real
        history most of them are exactly that — warming from a fortnight of
        gold produced 148 levels of which 135 had never been touched — and
        keeping them means every price is near something.

        Two rules, in this order. **Anything with a touch stays**, however far
        away it now is: a level price reacted at is worth remembering precisely
        because price left it. Everything else must be close enough to be
        tested soon, and then only the strongest survive the cap.
        """
        touched = [level for level in levels if level.touches >= 1.0]
        fresh = [
            level
            for level in levels
            if level.touches < 1.0 and abs(level.distance_vol(price, vol)) <= KEEP_VOL
        ]
        fresh.sort(key=lambda level: level.strength(when, vol), reverse=True)
        room = max(0, MAX_LEVELS - len(touched))
        kept = touched + fresh[:room]
        dropped = len(levels) - len(kept)
        if dropped:
            log.debug("levels: dropped %d untested levels", dropped)
        return kept

    # -------------------------------------------------------------- shapes

    def _record_shape(self, series: Series, visible: list[pips.Point]) -> None:
        """Note the shape the last few confirmed swings make.

        Only confirmed swings, for the same reason levels use only confirmed
        swings: a shape whose last point has not settled is a shape nobody
        could have recognised yet.
        """
        turns = pips.turns(visible)
        if len(turns) < patterns.SHAPE_POINTS:
            return
        shape = patterns.Shape.of(turns[-patterns.SHAPE_POINTS :], series.feed, series.interval)
        if shape is None or shape.flat:
            return
        key = (series.feed, series.interval)
        if key in self._pending:
            return  # one open shape per series; overlapping ones are the same episode
        handle = self.shapes.add(shape)
        if handle >= 0:
            self._pending[key] = (handle, series.closes[-1], len(series.closes))

    def match_shape(self, feed: str, interval: str) -> patterns.Match | None:
        """What the library says about the shape currently forming here."""
        series = self._series.get((feed, interval))
        if series is None or not series.ready:
            return None
        found = pips.points(list(series.times), list(series.closes), self.pip_count)
        turns = pips.turns(pips.as_of(found, self._now))
        if len(turns) < patterns.SHAPE_POINTS:
            return None
        shape = patterns.Shape.of(turns[-patterns.SHAPE_POINTS :], feed, interval)
        return self.shapes.match(shape) if shape else None

    def _resolve_shapes(self, series: Series, vol) -> None:
        """Close out any shape whose horizon has passed.

        The move is measured in volatility units from where the shape completed,
        so a pattern that "works" in a violent week and one that works in a calm
        one are the same observation.
        """
        key = (series.feed, series.interval)
        pending = self._pending.get(key)
        if pending is None:
            return
        handle, price, at_bar = pending
        if len(series.closes) - at_bar < self.shape_horizon:
            return
        moved = (series.closes[-1] - price) / price * 10_000 if price else 0.0
        self.shapes.resolve(handle, moved / vol.bps)
        self._pending.pop(key, None)

    # -------------------------------------------------------------- feeding

    def __setstate__(self, state: dict) -> None:
        """Restore a pickled engine, including one written by an older build.

        Unpickling rebuilds `__dict__` directly and **never calls `__init__`**,
        so every attribute added since a state file was written is simply
        absent from the restored object. That is not theoretical: adding
        `_touch_eras` took the whole structures service down on the next
        deploy — restored models, then `AttributeError` on the first bar, five
        seconds after start. Nothing consumed the bus afterwards, so the
        symptom was dropped quotes and a silent journal rather than anything
        naming the cause.

        Filling the gaps from a default-constructed engine rather than from a
        hand-written list of names, because the hand-written list is the part
        that goes stale — it would need editing every time a field is added,
        which is precisely the thing nobody remembers to do. Anything the state
        carries wins; anything it lacks arrives at its default.
        """
        self.__dict__.update({**Engine().__dict__, **state})

    def touch_interval(self, feed: str = "", when: float | None = None) -> str:
        """Which interval's bars carry the touch check for all the others.

        The finest one available *at that moment*, which is not the same as the
        finest one overall and is the whole subtlety here. Venues keep far less
        fine history than coarse — Yahoo serves seven days of 1m against
        decades of 1w — so a replay of a few hundred bars per interval covers
        hours at 1m and years at 1w. Pinning the touch check to the globally
        finest series therefore leaves every earlier era untouched: on gold,
        1w and 4h opened *zero* touches across 20,159 replayed bars, and their
        levels were then pruned for never having been visited. Twenty-one
        levels became four.

        So the touch source changes as history advances. Before 1m data begins,
        the finest thing that exists carries the check; once it begins, it takes
        over. Each era is touched at the best resolution that era actually has,
        which is what "from the finest bars available" was always meant to say.
        """
        if self._touch_eras:
            at = self._now if when is None else when
            found = self._touch_eras[0][1]
            for start, interval in self._touch_eras:
                if start > at:
                    break
                found = interval
            return found
        seen = {interval for (this, interval) in self._series if not feed or this == feed}
        candidates = seen or set(self.intervals)
        return min(candidates, key=confluence.rank, default="")

    @staticmethod
    def _eras(rows: Sequence[dict]) -> list[tuple[float, str]]:
        """When each finer series starts, so a replay can hand the check over.

        The finest interval available only ever gets finer as time runs
        forward, so this is one pass over the earliest timestamp per interval,
        keeping the improvements.
        """
        first: dict[str, float] = {}
        for row in rows:
            interval = str(row.get("interval") or "")
            when = float(row.get("time") or 0.0)
            if interval and (interval not in first or when < first[interval]):
                first[interval] = when

        eras: list[tuple[float, str]] = []
        best = ""
        for interval, start in sorted(first.items(), key=lambda kv: kv[1]):
            if not best or confluence.rank(interval) < confluence.rank(best):
                best = interval
                eras.append((start, best))
        return eras

    def observe_bar(self, payload: dict) -> list[Call]:
        """One `prices.bars` message. Returns any calls it produced.

        **Forming and touching are separate jobs**, and this used to do both at
        one resolution. A daily level warmed from daily bars had its origins
        quantised to the day — and since a cold start replays six-figure bar
        counts, that was most of what any level knew about itself.

        So: every bar forms levels for its own interval, and only the *finest*
        interval's bars run the touch check, against every interval at once.
        That is the replay equivalent of `observe_quote`, which has always
        checked every interval on every quote and is why the live path never
        had this problem.

        The trap the doc warns about is running both — keeping the per-interval
        check and adding a fine-grained pass on top, which would count every
        interaction twice. The `return []` below is what avoids it: a coarse
        bar forms and then stops, rather than also touching.
        """
        feed = str(payload.get("feed") or "")
        interval = str(payload.get("interval") or "")
        if not feed or interval not in self.intervals:
            return []
        close = payload.get("close")
        if not isinstance(close, int | float) or not close:
            return []
        when = int(payload.get("time") or time.time())
        high = float(payload.get("high") or close)
        low = float(payload.get("low") or close)
        venue = str(payload.get("venue") or "")

        agreed = self.consensus.observe(feed, interval, venue, when, high, low, float(close))
        if agreed is None:
            return []  # not enough venues on this bar yet
        high, low, close = agreed

        self._now = max(self._now, when)
        series = self.series(feed, interval)
        series.add(when, high, low, float(close))
        # This timeframe's own volatility: a typical 4h move is not a typical
        # 5m move, and one estimate for both makes every threshold expressed in
        # volatility units wrong for all but whichever series updates most.
        vol = self.vol.of(feed, interval)
        vol.update(float(close))
        # Pivots are session structures priced at today's scale, so they use the
        # reference estimate rather than the bar interval that happened to
        # deliver them — a 4h bar completing a day does not make it a 4h level.
        self._roll_sessions(feed, when, high, low, float(close), self.reference(feed))
        self._resolve_shapes(series, vol)
        if not series.ready:
            return []
        if series.due or not self._levels.get((feed, interval)):
            self.reform(series, when)

        # Formed. Whether this bar also *touches* is a separate question, and
        # the answer is no unless it is the finest series this instrument has —
        # otherwise the same interaction would be counted once here and again
        # when the fine bars arrive.
        if interval != self.touch_interval(feed, when):
            return []
        calls: list[Call] = []
        for other in self.intervals_for(feed):
            calls += self.check(feed, other, float(close), when, low, high)
        return calls

    def observe_quote(self, payload: dict) -> list[Call]:
        """A quote moves price against existing levels without re-forming them.

        Quotes are what make a touch detectable in time to matter — waiting for
        a 5m bar to close means reporting the interaction after it happened.
        """
        feed = str(payload.get("feed") or "")
        mid = payload.get("mid")
        if not feed or not isinstance(mid, int | float) or not mid:
            return []
        when = float(payload.get("time") or time.time())
        spread = payload.get("spread_bps")
        if isinstance(spread, int | float) and spread > 0:
            self._spread.setdefault(feed, deque(maxlen=SPREAD_WINDOW)).append(float(spread))
        # Quotes feed the tick-level estimate, which is the common denominator
        # every timeframe's levels are ranked against.
        vol = self.vol.of(feed)
        vol.update(float(mid))
        calls: list[Call] = []
        # Pivot levels live under their session name, so quotes must check
        # every interval this instrument has levels at, not just the bar ones.
        for interval in self.intervals_for(feed):
            calls += self.check(feed, interval, float(mid), when)
        return calls

    # ------------------------------------------------------------- touching

    def cost_of(self, feed: str, vol: Volatility | None = None) -> float:
        """What crossing the spread costs here, in volatility units.

        The same quantity on every instrument and timeframe, which is the only
        way it can be compared against an expected push measured the same way.
        A spread of 3bps is nothing on a violent daily chart and most of the
        move on a quiet 3m one — in units, that difference is the answer rather
        than something a reader has to hold in their head.

        A **median** over a recent window, for the reason the consensus is also
        a median: a mean is dragged by the outlier it exists to ignore. The cost
        that matters is what this instrument normally costs to trade, not
        whatever the spread happened to be in the microsecond a level was
        touched — one wide print during a release must not disqualify an edge
        that is ordinarily takeable. An exponential average was tried first and
        is not good enough here: at a 0.1 weight a single hundred-fold print
        moved the charged cost tenfold, which would silence a whole instrument
        for as long as it took to decay.
        """
        if not self.charge_spread:
            return 0.0
        seen = self._spread.get(feed)
        if not seen or vol is None or not vol.bps:
            return 0.0
        return statistics.median(seen) / vol.bps

    def intervals_for(self, feed: str) -> list[str]:
        """Every interval this instrument has levels at, pivots included."""
        return sorted({interval for (this, interval) in self._levels if this == feed})

    def check(
        self,
        feed: str,
        interval: str,
        price: float,
        when: float,
        low: float | None = None,
        high: float | None = None,
    ) -> list[Call]:
        """Advance every open interaction, and open one where price has arrived.

        `low` and `high` are how far the bar reached beyond its close. Both are
        offered and each touch takes the end that faces the side it arrived
        from. Without them the extreme and the origin are the same number, and
        the distinction between where liquidity was taken and where the level
        is drawn disappears.
        """
        vol = self.vol.of(feed, interval)
        if not vol.warm:
            return []
        calls: list[Call] = []
        for level in self._levels.get((feed, interval), []):
            open_touch = self.tracker.open_touch(level)
            if open_touch is not None:
                done = self.tracker.update(level, price, vol, when, low, high)
                if done is not None:
                    # The origin, not the extreme. The extreme is a wick —
                    # liquidity taken a fraction beyond the level at a price
                    # nobody traded around — while the origin is where the leg
                    # in ended and the leg out began, which is the price the
                    # level is actually drawn at.
                    level.observe_touch(done.origin or done.extreme, vol, when)
                    # The wick is the zone's far edge, not noise to discard.
                    level.observe_wick(
                        done.features.side, done.origin or done.extreme, done.extreme, vol
                    )
                    log.debug("level %s %.5g resolved %s", feed, level.price, done.outcome)
                    self._resolved.append((level, done))
                    # Bounded: a consumer that stops draining must not become a
                    # slow memory leak in a service designed to run for months.
                    if len(self._resolved) > MAX_RESOLVED:
                        del self._resolved[: len(self._resolved) - MAX_RESOLVED]
                    # Only hold the level back if price is *still* in the zone.
                    # An interaction that resolved by price leaving has already
                    # done the leaving, and making it wait for a second exit
                    # would drop the next genuine approach.
                    level.waiting = level.contains(price, vol)
                continue

            if not level.contains(price, vol):
                # Out of the zone is not the same as away from the level. Price
                # sitting on the edge crosses it constantly, and re-arming on
                # each crossing counts a consolidation as dozens of turns — the
                # residue of the same bug the `waiting` flag was added for,
                # which the flag alone did not reach.
                if abs(level.distance_vol(price, vol)) >= lv.REARM_VOL:
                    level.waiting = False
                continue

            # Inside the zone, but this is the same visit that just resolved.
            if level.waiting:
                continue
            side = self._approach(level, price)
            features = reactions.features_for(
                level, side, price, vol, approach_vol=self._speed(feed, interval, vol), when=when
            )
            self.tracker.begin(level, price, features, when)
            inference = reactions.infer(
                level, side, features, self.tracker.memory, cost_vol=self.cost_of(feed, vol)
            )
            calls.append(
                Call(
                    feed=feed,
                    interval=interval,
                    level=level,
                    inference=inference,
                    price=price,
                    time=when,
                )
            )
            self.calls += 1
        self.tracker.expire(when)
        return calls

    def _roll_sessions(
        self, feed: str, when: int, high: float, low: float, close: float, vol
    ) -> None:
        """Turn completed sessions into pivot levels for the next one.

        Pruned like any other level, and that is not optional: a session adds
        ten pivots and sessions keep completing, so without it a fortnight of
        history accrues a hundred and forty of them and nothing ever removes
        one. Yesterday's pivots are watched; the ones from twelve days ago are
        not, unless price actually reacted at them.
        """
        for session in self.sessions.observe(feed, when, high, low, close):
            key = (feed, session.period)
            built = pivots.build(feed, session, vol)
            merged = lv.merge(self._levels.get(key, []), built, vol)
            self._levels[key] = self.prune(merged, close, vol, float(when))

    def regime_changed(self, feed: str, severity: float = 0.5) -> int:
        """Discount every level's history for this instrument.

        The drift detector saying the volatility regime changed means these
        levels learned their behaviour in a market that no longer exists. They
        are still levels; their statistics are just much weaker evidence now.

        `severity` is the change's percentile among past changes, so a marginal
        change costs a level little and a violent one costs it most of its
        history. A flat discount would treat both the same.
        """
        touched = 0
        for (this_feed, _), found in self._levels.items():
            if this_feed != feed:
                continue
            for level in found:
                level.regime_changed(severity)
                touched += 1
        if touched:
            log.info(
                "levels: discounted %d %s levels, severity %.0f%%", touched, feed, severity * 100
            )
        return touched

    def _approach(self, level: lv.Level, price: float) -> lv.Side:
        """Which side price came from — the previous bar, not the current one.

        Using the current price would be circular: inside the zone, price is by
        definition next to the level, and the question is where it came *from*.
        """
        series = self._series.get((level.feed, level.interval))
        if series is not None and len(series.closes) >= 2:
            return level.side_of(series.closes[-2])
        return level.side_of(price)

    def reference(self, feed: str) -> Volatility:
        """The estimate levels from every timeframe are compared against.

        Cross-timeframe questions — which level is nearest, is this one worth
        acting on — need one denominator, or "three volatility units away" means
        something different for each level and they cannot be ranked.
        """
        tick = self.vol.of(feed)
        if tick.warm:
            return tick
        # Before any quotes have arrived, the finest timeframe with data is the
        # closest thing to a tick estimate.
        for interval in self.intervals:
            found = self.vol.of(feed, interval)
            if found.warm:
                return found
        return tick

    def _speed(self, feed: str, interval: str, vol) -> float:
        """How fast price is moving, in volatility units per bar."""
        series = self._series.get((feed, interval))
        if series is None or len(series.closes) < 2:
            return 0.0
        previous, latest = series.closes[-2], series.closes[-1]
        if not previous:
            return 0.0
        return abs((latest - previous) / previous * 10_000) / vol.bps

    # ---------------------------------------------------------------- state

    # ------------------------------------------------------------- warming

    def seed(
        self,
        database: Path | str,
        *,
        feeds: Sequence[str] = (),
        intervals: Sequence[str] = (),
        bars: int = SEED_BARS,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Warm the windows from stored history. Returns bars replayed.

        Without this the engine can only learn from the bus, which carries a
        *notice* per sweep rather than a series — roughly one bar per venue per
        minute. Levels need hundreds, so bootstrapping from the bus alone would
        take days while a backfilled store already holds the history.

        The store is opened **read-only**: the numeric layer reads prices, it
        does not own them, and enforcing that at the driver is cheaper than
        remembering it.

        Bars are replayed in time order through the ordinary path, so levels
        form from confirmed swings exactly as they would live, and the touch
        statistics that make the directional inference work exist from the
        first minute. Calls produced during the replay are discarded — they
        describe touches that happened days ago, and publishing them would
        alert on history.
        """
        wanted = tuple(intervals) or self.intervals
        rows = _read_bars(database, feeds, wanted, bars)
        if not rows:
            return 0

        # Worked out from the whole replay before it starts, so the first bar is
        # judged by the same rule as the last rather than by whichever series
        # happened to have arrived.
        eras = self._eras(rows)
        replayed = 0
        total = len(rows)
        # A cold start replays six-figure bar counts and says nothing until it
        # finishes, which is minutes of a service that looks hung — and the one
        # thing this project keeps relearning is that silence has to say which
        # kind it is. `on_progress` lets a terminal draw a bar; without one the
        # log carries it, because that is where a running service is read from.
        beat = max(1, total // 100)
        spoken = max(1, total // 10)
        self._touch_eras = eras
        try:
            for row in rows:
                self.observe_bar(row)  # calls discarded on purpose
                replayed += 1
                if on_progress is not None:
                    if replayed % beat == 0 or replayed == total:
                        on_progress(replayed, total)
                elif replayed % spoken == 0 and replayed != total:
                    log.info(
                        "levels: warming, %d%% (%s of %s bars)",
                        round(100 * replayed / total),
                        f"{replayed:,}",
                        f"{total:,}",
                    )
        finally:
            self._touch_eras = []
        log.info(
            "levels: warmed from %d stored bars across %s, touching from %s",
            replayed,
            ", ".join(sorted({row["feed"] for row in rows})) or "nothing",
            " then ".join(interval for _start, interval in eras) or "nothing",
        )
        return replayed

    def drain_resolved(self) -> list[tuple[lv.Level, reactions.Touch]]:
        """Take the touches that have resolved since the last call.

        Draining rather than reading, because each resolution should be
        recorded once: a consumer that read without clearing would journal the
        same outcome on every message.
        """
        found, self._resolved = self._resolved, []
        return found

    def summary(self) -> list[dict]:
        """What the engine knows, for `structures levels`."""
        rows = []
        for (feed, interval), found in sorted(self._levels.items()):
            vol = self.vol.of(feed, interval)
            for level in sorted(found, key=lambda level: level.price):
                rows.append(level.to_dict(vol))
                rows[-1]["interval"] = interval
        return rows
