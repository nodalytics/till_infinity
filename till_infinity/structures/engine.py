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
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from ..logging import get_logger
from . import (
    confluence,
    origin_points,
    origins,
    patterns,
    pips,
    pivots,
    profile,
    reactions,
    regimes,
    runs,
    sessions,
    sweeps,
)
from . import levels as lv
from .models import Shape, Signal
from .state import Restorable
from .volatility import Book as VolBook
from .volatility import Volatility


@dataclass(frozen=True, slots=True)
class _OriginBar(Restorable):
    """The four prices `origins.zone_of` reads, and nothing else.

    Restorable although it is never persisted - it lives for one call and is
    discarded. The walk that enforces that invariant does not know the
    difference, and satisfying a guard that exists for a real reason is
    cheaper than teaching it about exceptions.
    """

    open: float
    high: float
    low: float
    close: float


log = get_logger(__name__)

#: Sigmas of wick spread a stop has to clear beyond the level's own average.
#:
#: One would be roughly the depth 84% of sweeps stay inside if the depths were
#: normal, which they are not - they are bounded below at zero with a long
#: right tail, so real coverage at one sigma is higher than that. Two produces
#: stops wide enough that the size the risk budget then allows is uninteresting
#: on the tighter instruments. This is the setting most worth measuring against
#: outcomes rather than reasoning about.
SWEEP_SIGMAS = 1.0


#: Bars kept per instrument. Enough to hold the swings that matter on a 5m
#: chart without the window itself becoming the thing being modelled.
WINDOW = 500

#: Perceptually important points pulled from the window. Roughly one per ten
#: bars: fewer and real swings are missed, more and noise becomes a level.
PIP_COUNT = 50

#: Re-form levels this often, in bars. Every bar would be wasted work - the
#: swings barely change - and never would let the set go stale.
REFORM_EVERY = 20

#: Bars after a shape completes before its outcome is counted. Long enough for
#: the move to develop, short enough that it is still attributable to the shape.
SHAPE_HORIZON = 12

#: The timeframes levels are built on. Defined in `confluence` and used here so
#: there is one list rather than two that drift - which they did: confluence
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
#: regardless of distance - a level price has reacted at is worth remembering
#: precisely because price left it.
KEEP_VOL = 8.0

#: Resolutions held for a consumer that may not be draining them.
MAX_RESOLVED = 500

#: Bars of its own timeframe an instrument may go without printing before it is
#: treated as closed rather than quiet. Four, matching `GAP_FACTOR`, which makes
#: the same judgement about a touch that spans a closure: long enough that an
#: ordinary thin session still counts as trading, short enough that a weekend
#: does not. Quotes are no use for this - venues keep answering polls with
#: Friday's price all weekend, which is what let a shut market alert.
STALE_BARS = 4.0

#: The fewest price steps that must fit inside a level's zone before the pair
#: is modelled at all.
#:
#: A level is a band price is meant to **enter**, react inside, and leave. That
#: only means something if price can be *inside* it. When the venue's tick is a
#: large fraction of a typical move, price cannot enter - it jumps across - and
#: every crossing becomes a touch. Measured on the instance: `sol 3m` fits 2.5
#: ticks in a zone and `audusd 1m` fits 2.7, against `btc 5m`'s 170. It is not
#: a crypto problem; coarse pip quoting does the same thing a cheap coin does.
#:
#: Four, because `depth_vol` - how far into the zone price pushed - is a
#: feature, and a feature with two distinguishable values is not one. Four
#: steps is the least that gives it any resolution, and it is also where the
#: measurement separates: 2.5, 2.7, 2.7 and 3.5 on one side, 4.1 and up on the
#: other.
#:
#: Judged on the **floor** zone rather than the observed one, which is the
#: conservative direction and deliberate. Wicks widen a real zone as touches
#: accumulate, so an established level is roomier than this - but a *new* level
#: gets the floor, and the question here is whether to form one at all.
#:
#: It declines eight of fifteen sampled pairs, which is more than the observed
#: widths alone would suggest: sol at 1m, 3m and 5m, and audusd, nzdusd,
#: eurusd, usdcad and usdchf at 1m. sol keeps 15m and coarser. The FX ones were
#: assessed over a weekend, when those markets are shut and their measured
#: behaviour says nothing, so they want re-checking on a weekday - see todo.md.
#:
#: Erring toward declining is the right direction here even so. Losing a good
#: pair costs some alerts, visibly. Keeping a bad one poisons the sample: sol
#: alone was half of every outcome in the journal, which is what gates `fit`.
#:
#: Both ends of this are bad and only one is fixed by `GRID_ZONE_VOL`. That
#: bounds a zone from becoming absurdly *wide* on a coarse grid, which was
#: making everything a touch. What remains is a zone two or three ticks
#: *across*, which is the failure `MIN_ZONE_TICKS` was added for. There is no
#: width that works, so the pair is declined instead - the same shape as
#: `trading()`: refuse rather than produce something meaningless.
MIN_TICKS_PER_ZONE = 4.0

#: Ceiling per (instrument, interval), strongest kept. Without one a long
#: history accrues a level every few basis points, and at that density every
#: price is "at a level" and the model predicts nothing. Fifteen is roughly
#: what a person marks on one chart, which is the right order of magnitude -
#: the constraint is attention, not storage.
MAX_LEVELS = 15


def _widen_to_origin(low: float, high: float, origin: dict) -> tuple[float, float]:
    """Extend a level's zone to cover the origin it sits in.

    **Only when the level is inside one.** `in_origin` is the condition: a
    level that happens to have an origin somewhere nearby is an ordinary level,
    and stretching its zone towards an unrelated one would put stops where
    nothing has ever been defended.

    The zone is the band a stop has to clear, built from how far wicks have run
    past the level. When the level coincides with an origin - the last opposing
    bar before an impulse that broke structure - the interest left stranded
    there is the thing price reacts to, and its far edge is further out than
    the wick average knows. A stop inside it is stopped by the rejection the
    trade is trading.

    The level price itself does not move. Every statistic the level owns is
    recorded against that price, and shifting it would silently re-key history
    that was measured somewhere else.

    Union, never contraction: an origin narrower than the observed wicks does
    not make the wicks smaller. The zone can only widen.
    """
    if not origin or not origin.get("in_origin"):
        return low, high
    edge_low = origin.get("origin_low")
    edge_high = origin.get("origin_high")
    if not isinstance(edge_low, int | float) or not isinstance(edge_high, int | float):
        return low, high
    if not edge_low or not edge_high or edge_low > edge_high:
        return low, high
    return min(low, float(edge_low)), max(high, float(edge_high))


@dataclass(slots=True)
class Consensus(Restorable):
    """Median bar across venues, per instrument and interval.

    Bars arrive one venue at a time and several venues report the same bar.
    Without this the series took whichever venue published last, and the winner
    changed from bar to bar - so the swing detection was reading a series
    stitched together from different venues, injecting exactly the cross-venue
    disagreement this project exists to *measure* rather than suffer.

    The median is taken across whichever venues have reported that bar so far
    and recomputed as more arrive, so the estimate improves within the sweep
    rather than waiting for a venue that may never report.
    """

    #: Feeds carried by a single source, which need no agreement because there
    #: is none to be had.
    #:
    #: `MIN_VENUES` exists because a median of two is one venue's opinion
    #: wearing a median's clothes. That argument does not reach an instrument
    #: only one place quotes: a synthetic has no underlying, so the broker is
    #: not *a* source for it, it is the *only* source, and the price it gives
    #: is the instrument by definition.
    #:
    #: Without this the block was total and silent - nine synthetics quoted,
    #: were selected in the terminal, published onto the bus, and produced not
    #: one level between them, because a lone venue never reached three.
    single_source: frozenset[str] = frozenset()

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
        if len(at) < (1 if feed in self.single_source else MIN_VENUES):
            return None
        return (
            statistics.median([h for h, _, _ in at.values()]),
            statistics.median([low for _, low, _ in at.values()]),
            statistics.median([c for _, _, c in at.values()]),
        )


#: A venue that has not quoted for this long is no longer part of the picture.
#: Without it a venue that stops publishing holds its last mid in the median
#: for ever, and on a fast move the consensus lags behind every live venue.
QUOTE_STALE = 30.0


@dataclass(slots=True)
class Quotes(Restorable):
    """Median mid across venues, per instrument.

    The same argument as `Consensus`, for the stream that needed it more. Bars
    got a median across venues and quotes did not, so `check` was called with
    whichever venue published last - and venues do not agree on the price.
    Measured across a five second window: 6.12bps between venues on US500 and
    5.74 on BTCUSD, which in each instrument's own volatility units is **3.46**
    and **1.09**. `resolve_vol` is 1.5, so on spx500 two consecutive quotes
    from different venues looked like a three-and-a-half unit move and opened
    and closed a touch between them, having observed nothing but a change of
    publisher.

    That is why spx500 and btc led the instant-resolution table at 41% and 39%
    while gold and the FX majors, whose venues agree to within a twentieth of a
    unit, sat near zero.

    Held per feed rather than per (feed, interval): a quote has no interval, and
    the mid is the instrument's price whatever chart is being tested against it.
    """

    #: feed -> venue -> (when, mid)
    _mids: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)

    def observe(self, feed: str, venue: str, when: float, mid: float) -> float:
        """Fold one venue's quote in and answer with what the venues agree on."""
        seen = self._mids.setdefault(feed, {})
        seen[venue] = (when, mid)
        fresh = [value for last, value in seen.values() if when - last <= QUOTE_STALE]
        # One venue quoting is not a disagreement, and a median of nothing is an
        # error - either way its own mid is the best answer available.
        return statistics.median(fresh) if fresh else mid


@dataclass(slots=True)
class Series(Restorable):
    """A rolling window of one instrument at one interval."""

    feed: str
    interval: str
    times: deque[int] = field(default_factory=lambda: deque(maxlen=WINDOW))
    closes: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    highs: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    lows: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    #: Kept for `origins`, which needs a body to fall back on when a bar is
    #: mostly wick. Everything else here works from closes and extremes.
    opens: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    since_reform: int = 0

    def add(
        self, when: int, high: float, low: float, close: float, open_: float | None = None
    ) -> bool:
        """Fold a bar in. True if it is a new one rather than a correction.

        The answer matters to anything *accumulating* rather than storing: see
        the volatility update in `observe_bar`.
        """
        # A bar arriving for a time already held is a correction, not a new bar.
        opening = close if open_ is None else float(open_)
        if self.times and when == self.times[-1]:
            self.highs[-1], self.lows[-1], self.closes[-1] = high, low, close
            if self.opens:
                self.opens[-1] = opening
            return False
        self.times.append(when)
        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)
        # Guarded: a Series restored from before this field existed has an
        # empty deque while the others are full, and appending blindly would
        # misalign every bar against its own open from then on.
        if len(self.opens) == len(self.closes) - 1:
            self.opens.append(opening)
        self.since_reform += 1
        return True

    @property
    def ready(self) -> bool:
        return len(self.closes) >= pips.MIN_POINTS * 4

    @property
    def due(self) -> bool:
        return self.since_reform >= REFORM_EVERY


@dataclass(slots=True)
class Call(Restorable):
    """A directional call at a level, with everything behind it."""

    feed: str
    interval: str
    level: lv.Level
    inference: reactions.Inference
    price: float
    time: float
    #: What the origin model says about this level, or an empty dict. Computed
    #: at construction because the engine has the series and the Call does not,
    #: and merged into the published features below.
    origin: dict = field(default_factory=dict)

    def to_signal(self, vol, clock=None, peers=None, busy: float = 1.0, market: str = "") -> Signal:
        # `probability`, not `probability_up`: quoting P(up) beside a *down*
        # call reads as the confidence in down when it is the confidence
        # against it. The base rate flips with it or the pair is not a
        # comparison. See reactions.Inference.probability.
        swept, swept_n = sweeps.sweep_rate(self.level, self.inference.side)
        beyond_vol, beyond_n = (
            sweeps.liquidity_beyond(self.level, peers, self.inference.side, vol)
            if peers
            else (0.0, 0)
        )

        zone_low, zone_high = self.level.zone(vol)
        zone_low, zone_high = _widen_to_origin(zone_low, zone_high, self.origin)
        # The wider band a stop has to clear. See `Level.sweep_zone`: the touch
        # zone is built from the average wick, and a stop at the average sweep
        # depth is exceeded by about half of all sweeps by construction.
        sweep_low, sweep_high = self.level.sweep_zone(vol, SWEEP_SIGMAS)
        sweep_low, sweep_high = _widen_to_origin(sweep_low, sweep_high, self.origin)
        unit = vol.price_units(self.level.price, 1.0) or 1.0
        wick_below = (self.level.price - zone_low) / unit
        wick_above = (zone_high - self.level.price) / unit
        # How *spread out* the wicks are, not only how deep on average.
        #
        # `SideStats` has tracked this since the sweep zone was built and it
        # has never left the object: only the mean reached a consumer, so
        # anything asking "how far does this level get pushed" got a number
        # that half of pushes exceed. A consumer waiting for a retracement
        # needs the spread to know whether the mean means anything.
        below = self.level.sides.get(lv.Side.ABOVE)
        above = self.level.sides.get(lv.Side.BELOW)
        wick_below_sd = below.wick_sd_vol if below else 0.0
        wick_above_sd = above.wick_sd_vol if above else 0.0

        if clock is not None:
            hour_hold, hour_n = clock.hold_rate(self.feed, self.time)
            _, hour_vol_share = clock.volatility(self.feed, self.time)
        else:
            hour_hold, hour_n, hour_vol_share = 0.0, 0.0, 1.0

        detail = (
            f"{self.inference.direction} from {self.inference.side} at "
            f"{self.level.price:.5g} - p={self.inference.probability:.0%} "
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
                # Where a violent move began, and whether this level sits in
                # one. A level that coincides with unfilled interest is better
                # evidenced than the same level in open space - see
                # `structures/origins.py`. Recorded for now: nothing gates or
                # sizes on it, and the journal is what will say whether it
                # separates.
                **self.origin,
                # The volatility unit itself, in basis points. Everything else
                # here is measured in multiples of it, so a consumer that only
                # sees the published signal - `trading` reads them off the bus
                # and never touches this engine - cannot turn `risk_vol` or
                # `expected_push_vol` into a price without it. Carrying the
                # multiples without the unit made those two fields unusable
                # outside this process.
                "vol_bps": vol.bps,
                # The same quantity read by a mean-reverting model, and how far
                # the current scale sits above its own long-run level. Recorded
                # rather than used: nothing divides by these yet, and the point
                # of carrying them is that the journal can say whether they
                # would have been the better number. See `garch.py`.
                "garch_bps": vol.garch_bps,
                "vol_stretch": vol.stretch,
                # Read from whole bars rather than closes, and a forecast of
                # the next bar rather than a reading of the last ones. Both
                # recorded and used by nothing - see `ranges.py` and `har.py`.
                "range_bps": vol.range_bps,
                "forecast_bps": vol.forecast_bps,
                "forecast_ratio": vol.forecast_ratio,
                # All four on one scale, combined equally. Recorded so the
                # journal can say whether the combination beat the estimate
                # already in use - see `consensus_vol.py`.
                "ensemble_bps": vol.ensemble_bps,
                # The level's own hold rate on the side price arrived from,
                # and the decisive interactions behind it. The strongest
                # single signal a level carries - strength.md puts it at AUC
                # 0.648 where the `strength` composite reaches 0.548 - and it
                # was computed on every touch and published nowhere.
                #
                # Unshrunk, with its count beside it, so a consumer can apply
                # its own prior. A rate with two interactions behind it and one
                # with ninety are not the same number and must not arrive
                # looking like it.
                "record_hold": self.inference.record_hold,
                "record_n": self.inference.record_n,
                # When, which nothing in this package has ever conditioned on.
                # The hour is stamped unconditionally so the journal can pair
                # it with outcomes; `hour_hold` and `hour_n` are what the clock
                # has learned about it so far, shrunk, and are near the
                # instrument's base rate until an hour has earned otherwise.
                "hour": float(sessions.hour_of(self.time)),
                "hour_hold": hour_hold,
                "hour_n": hour_n,
                "hour_vol_share": hour_vol_share,
                # The level is a **range**, and an asymmetric one: the origin
                # is where the leg in met the leg out, and each edge extends by
                # how far the wick ran past it on that side. Published because
                # a consumer that only sees `level` will place a stop inside
                # the band where wicks routinely reach - which is the difference
                # between being wrong and being swept.
                "zone_low": zone_low,
                "zone_high": zone_high,
                "wick_below_vol": wick_below,
                "wick_above_vol": wick_above,
                "wick_below_sd": wick_below_sd,
                "wick_above_sd": wick_above_sd,
                # How many wicks are behind those two numbers. A mean and a
                # spread from one observation are not a mean and a spread, and
                # a consumer cannot tell without being told.
                "wick_n": float(below.wick_n if below else 0.0),
                # And the wider band a **stop** has to clear. The two are not
                # the same question: the touch zone is built from the average
                # wick, which is the right centre for "is price at this level"
                # and the wrong edge for "how far past it does price go" - a
                # stop there is exceeded by about half of all sweeps by
                # construction. See `Level.sweep_zone`.
                "sweep_low": sweep_low,
                "sweep_high": sweep_high,
                # Whether this level has a history of being run rather than
                # respected, and what is resting beyond it for price to run it
                # toward. Neither gates anything here: they go to the journal
                # beside the outcome so the question can be answered from our
                # own resolutions. See `sweeps`.
                "sweep_rate": swept,
                "sweep_n": swept_n,
                "liquidity_beyond_vol": beyond_vol,
                "liquidity_beyond_n": float(beyond_n),
                # How busy the market was, as a share of this instrument's own
                # typical bar on this timeframe. A ratio because the underlying
                # count is tick volume on most feeds and absent on some, so
                # only "relative to normal" means the same thing everywhere.
                "activity": busy,
            },
            direction=self.inference.direction,
            market=market,
            interval=self.interval,
            time=self.time,
        )


def _bar_query(feeds: Sequence[str], intervals: Sequence[str]) -> tuple[str, list[object]]:
    """The window-function query both readers share, and its parameters."""
    marks = ",".join("?" * len(intervals))
    where = f"interval IN ({marks})"
    params: list[object] = list(intervals)
    if feeds:
        where += f" AND feed IN ({','.join('?' * len(feeds))})"
        params.extend(feeds)
    return where, params


def _bar_span(
    database: Path | str,
    feeds: Sequence[str],
    intervals: Sequence[str],
    bars: int,
) -> tuple[int, dict[str, float]]:
    """How many bars the warm will replay, and the earliest time per interval.

    Both are aggregates, so they come from SQLite rather than from a list of
    rows in this process. `_eras` only ever needed the earliest timestamp per
    interval - reading three hundred thousand rows to find six numbers was the
    expensive half of a cold start.
    """
    where, params = _bar_query(feeds, intervals)
    with closing(sqlite3.connect(f"file:{Path(database)}?mode=ro", uri=True, timeout=10.0)) as conn:
        rows = conn.execute(
            "SELECT interval, COUNT(*), MIN(ts) FROM ("
            "  SELECT interval, ts,"
            "         ROW_NUMBER() OVER (PARTITION BY feed, interval ORDER BY ts DESC) AS rn"
            f"  FROM bars WHERE {where}"
            ") WHERE rn <= ? GROUP BY interval",
            (*params, bars * 8),
        ).fetchall()
    total = sum(int(n) for _, n, _ in rows)
    first = {str(interval): float(start) for interval, _, start in rows if interval}
    return total, first


def _read_bars(
    database: Path | str,
    feeds: Sequence[str],
    intervals: Sequence[str],
    bars: int,
) -> Iterator[dict]:
    """Stored bars as bus-shaped payloads, oldest first, **streamed**.

    Shaped like a `prices.bars` message so the replay goes through exactly the
    same code the live path does. A separate warm-up path would be a second
    implementation of level formation, and the two would drift.

    A generator rather than a list, and the ordering is SQLite's rather than
    Python's. Materialising the whole warm cost over 330,000 dicts on fourteen
    instruments - 410MB resident against a host with 908MB and no swap - and
    OOM-killed the container on every cold start it attempted. Sixteen kills,
    never finishing. SQLite sorts in its own temp space and hands rows over one
    at a time; the engine only ever needed one at a time.
    """
    path = Path(database)
    if not path.exists() or not intervals:
        return

    where, params = _bar_query(feeds, intervals)
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)) as conn:
            conn.row_factory = sqlite3.Row
            # Oldest first, and grouped so every venue on one bar arrives
            # together - the consensus needs them adjacent to reach a quorum on
            # that timestamp. `bars * 8` because several venues report each one.
            found = conn.execute(
                "SELECT feed, venue, interval, ts, high, low, close FROM ("
                "  SELECT feed, venue, interval, ts, high, low, close,"
                "         ROW_NUMBER() OVER (PARTITION BY feed, interval ORDER BY ts DESC) AS rn"
                f"  FROM bars WHERE {where}"
                ") WHERE rn <= ? ORDER BY ts, feed, interval",
                (*params, bars * 8),
            )
            for row in found:
                yield {**row, "time": row["ts"]}
    except sqlite3.Error as exc:
        log.warning("levels: could not warm from %s: %s", path, exc)
        return


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
        formation: str = "pip,run,origin",
        run_threshold: float = runs.RUN_SWING_VOL,
        single_source: frozenset[str] = frozenset(),
    ) -> None:
        #: How swings are found: `pip` selects bar extremes, `run` takes the
        #: boundaries between runs of volatility. An experiment, not a setting
        #: to tune in production - the point is to run both over one history
        #: and let the outcome machinery say which price respects more.
        #: The passes to run, merged. Composing them is the point rather than a
        #: fallback: a formation that draws nothing is not a neutral choice, it
        #: is silence. `origin` alone draws no levels at all on gold at 1m, 5m
        #: or 15m - the timeframes carrying nearly every signal - so selecting
        #: it on its own would stop that instrument trading, quietly.
        self.passes: tuple[str, ...] = ()
        self.formation = ""
        self.draw_with(formation)
        self.run_threshold = run_threshold
        #: Whether the quoted spread is charged against every level call. On by
        #: default, because an uncharged edge is a gross number and acting on
        #: one is the mistake the cost exists to prevent.
        #:
        #: Off is for answering "what would this have said without the cost" -
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
        self.consensus = Consensus(single_source=single_source)
        #: (feed, interval, venue) already reported as arriving with no
        #: high/low. Warned once each rather than per bar - the condition is a
        #: property of the producer, so it either happens always or never, and
        #: per-bar it would be thousands of identical lines a day.
        self._flat_bars: set[tuple[str, str, str]] = set()
        #: What kind of market this is, learned online. Labels only - it
        #: records and does not decide. See `regimes.py`.
        self.regimes = regimes.Regimes()
        #: And quotes are per venue for exactly the same reason, which they were
        #: not given until the bar fix made the omission visible.
        self.quotes = Quotes()
        #: Shapes seen before and what followed. Independent of levels: a level
        #: is a price, a shape is not, so a double top repeats across
        #: instruments and prices where a level cannot.
        self.shapes = patterns.Library()
        #: Open shape instances, waiting for the horizon to say what followed.
        self._pending: dict[tuple[str, str], tuple[int, float, int]] = {}
        self._series: dict[tuple[str, str], Series] = {}
        #: Pairs already told about, so `supports` says so once rather than on
        #: every reform. Not persisted: it is a log-noise guard, and saying it
        #: again after a restart is correct.
        self._declined: set[tuple[str, str]] = set()
        self._levels: dict[tuple[str, str], list[lv.Level]] = {}
        #: The timestamp of the bar being processed. Held so that "what was
        #: knowable" is answerable at any point, including from a test.
        self._now: float = 0.0
        #: Touches that have resolved since anyone last looked, with the level
        #: they resolved at. Queued rather than pushed because the engine has
        #: no journal and should not grow one - a resolution is a fact about
        #: price, and who wants to record it is not the engine's business.
        self._resolved: list[tuple[lv.Level, reactions.Touch]] = []
        #: Recent quoted spreads per instrument, in basis points - the cost of
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
                "structures: spread costs disabled - every level call will be "
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

    def _origin_at(self, feed: str, interval: str, price: float, vol: Volatility) -> dict:
        """What the origin model says about a level, as published features.

        An origin is where a violent move began - the last price in the
        previous direction before the new one took over - and the zone is the
        last bar of that opposing leg. A level that coincides with one is
        sitting on interest that was placed and not filled; the same level in
        open space is not. See `structures/origins.py`.

        **Recorded, not acted on.** Nothing gates or sizes on these yet. They
        go on the call so the journal can say whether a level inside an origin
        behaves differently from one outside it, which is the only thing that
        would justify acting on it. That is the same order this repository got
        wrong with `reward_to_risk` and right with `strength`.

        Wrapped, and deliberately. Two production outages this month were a
        fault in this engine stopping the whole structures service, and an
        annotation nobody reads yet is not worth a third. A failure here costs
        the features on one call.
        """
        try:
            unit = price * vol.bps / 10_000.0 if vol.bps else 0.0
            if unit <= 0:
                return {}
            series = self.series(feed, interval)
            closes = list(series.closes)
            if len(closes) < 12:
                return {}
            bars = None
            if len(series.opens) == len(closes):
                bars = [
                    _OriginBar(o, h, lo, c)
                    for o, h, lo, c in zip(
                        series.opens, series.highs, series.lows, closes, strict=False
                    )
                ]
            found = origins.Origins().observe(list(series.times), closes, unit, bars_at=bars)
            if not found:
                return {}
            nearest = min(found, key=lambda o: abs(o.price - price))
            inside = any(o.holds(price) for o in found)
            # The pair that brackets the current price. A swing that runs from
            # one origin to the other needs both ends: the near one is where it
            # enters and the far one is what it aims at, and "nearest" alone
            # cannot say which side of price it sits on.
            above = [o for o in found if o.low > price]
            below = [o for o in found if o.high < price]
            bracket: dict[str, float] = {}
            if above:
                near = min(above, key=lambda o: o.low - price)
                bracket["origin_above_low"] = near.low
                bracket["origin_above_high"] = near.high
                bracket["origin_above_vol"] = (near.low - price) / unit
                bracket["origin_above_revisits"] = float(near.revisits)
            if below:
                near = max(below, key=lambda o: o.high - price)
                bracket["origin_below_low"] = near.low
                bracket["origin_below_high"] = near.high
                bracket["origin_below_vol"] = (price - near.high) / unit
                bracket["origin_below_revisits"] = float(near.revisits)
            return {
                **bracket,
                "origin_distance_vol": abs(nearest.price - price) / unit,
                "origin_size_vol": nearest.size_vol,
                # How decisively the impulse cleared the extremum it broke.
                # Both this and the size have a floor below which the origin
                # holds *worse* than a generated process - see origins.py - so
                # a consumer that wants to be stricter than the detector can.
                "origin_extremum_vol": nearest.extremum_vol,
                "origin_revisits": float(nearest.revisits),
                "in_origin": 1.0 if inside else 0.0,
                # The zone itself, in prices. The four fields above describe an
                # origin without saying where it is, which is enough to score a
                # level and not enough to enter at one: a consumer that wants
                # to rest an order at the edge of the zone needs the edge.
                # `origin_distance_vol` is an absolute distance and cannot be
                # turned back into a price - it has lost the direction.
                "origin_price": nearest.price,
                "origin_low": nearest.low,
                "origin_high": nearest.high,
            }
        except Exception as exc:
            log.debug("structures: no origin reading for %s %s: %s", feed, interval, exc)
            return {}

    FORMATIONS: ClassVar[tuple[str, ...]] = ("pip", "run", "origin", "profile")

    def draw_with(self, formation: str) -> tuple[str, ...]:
        """Set which passes draw levels, validating the name. Returns the passes.

        A method rather than two lines in `__init__` because it has to be
        callable **after a restore**, and that is not a refinement - it is the
        correction of a setting that was inert for its whole life. `Watcher.load`
        replaces the freshly configured engine with the pickled one, so a
        deployment that asked for three passes got whichever one the state file
        was first saved with and kept it across every restart. Production ran
        `pip` alone while `STRUCTURES_FORMATION` said `pip,run,origin`, and the
        only visible symptom was that `run` and `origin` never drew anything -
        which reads exactly like two formations that do not work.

        Levels already formed are not redrawn. They are evidence gathered under
        the old geometry and throwing them away would cost the touch history
        that makes them worth holding; what changes is how the next reform
        draws, which is where the agreement between passes comes from.
        """
        wanted = (
            ("pip", "run")
            if formation == "both"
            else tuple(n.strip() for n in formation.split(",") if n.strip())
        )
        if not wanted or [n for n in wanted if n not in self.FORMATIONS]:
            raise ValueError(
                f"unknown formation {formation!r} - use {', '.join(self.FORMATIONS)}, "
                "'both', or a comma list of them"
            )
        self.passes = wanted
        self.formation = formation
        return wanted

    def feeds(self) -> set[str]:
        """Every instrument this engine has bars for, whatever the interval.

        From the series rather than from the levels: an instrument that has
        printed bars but not yet formed a level is one this engine is watching,
        and a consumer asking "what am I following" wants it in the answer.
        """
        return {feed for feed, _ in self._series}

    def levels(self, feed: str, interval: str = "") -> list[lv.Level]:
        if interval:
            return list(self._levels.get((feed, interval), []))
        return [
            level
            for (this_feed, _), found in self._levels.items()
            if this_feed == feed
            for level in found
        ]

    def swings(self, series: Series, vol: Volatility) -> list[pips.Point]:
        """The turning points levels are drawn at - by whichever formation.

        Pluggable so the two can be *compared* rather than argued about. Both
        return the same `Point`, carrying `confirmed`, so everything downstream
        - `as_of`, `form`, the whole outcome machinery - is indifferent to
        which produced them. See [levels.md], "A level spans periods too".
        """
        return self._points(self.passes[0], series, vol)

    def _form(self, series: Series, visible: Sequence[pips.Point], vol: Volatility):
        """Cluster the visible swings into candidate levels.

        Under `both` the two formations are run as separate passes and merged,
        rather than pooled into one clustering. Pooling would let a bar extreme
        and a run boundary a hair apart form a level *between* them and lose
        which pass found it; merging keeps each pass's own clusters and folds
        them only where one falls inside the other's zone - the same test a
        rediscovered level already passes. `agree` then records that both found
        it, which is the whole reason for doing this rather than choosing.
        """
        if len(self.passes) == 1:
            return lv.form(
                series.feed, series.interval, pips.turns(visible), vol, origin=self.passes[0]
            )
        made: list = []
        for name in self.passes:
            found = lv.form(
                series.feed,
                series.interval,
                pips.turns(pips.as_of(self._points(name, series, vol), self._now)),
                vol,
                origin=name,
            )
            made = found if not made else lv.merge(made, found, vol)
        return made

    def _points(self, name: str, series: Series, vol: Volatility) -> list[pips.Point]:
        """One pass's turning points."""
        times, closes = list(series.times), list(series.closes)
        if name == "run":
            return runs.points(times, closes, vol, threshold=self.run_threshold)
        if name == "origin":
            return origin_points.points([float(t) for t in times], closes, vol)
        if name == "profile":
            return profile.points([float(t) for t in times], closes, vol)
        return pips.points(times, closes, self.pip_count)

    def supports(self, feed: str, interval: str) -> bool:
        """Can this instrument carry a level at this resolution?

        Judged on how many ticks fit inside a zone - see `MIN_TICKS_PER_ZONE`.
        Silent about what it cannot judge: an estimate that is not warm, or an
        instrument that has not yet printed a single-step move, is missing
        evidence rather than evidence of a problem, and suppressing on that
        would decline every instrument for its first hour.
        """
        vol = self.vol.of(feed, interval)
        series = self._series.get((feed, interval))
        if not vol.warm or series is None or not series.closes or not vol.tick:
            return True
        price = series.closes[-1]
        if not price or not vol.bps:
            return True
        tick_vol = (vol.tick / price * 10_000) / vol.bps
        if tick_vol <= 0:
            return True
        # The zone this pair would actually get, by the same rule `Level.zone`
        # uses, so the answer tracks the geometry rather than a second copy of
        # it. Wicks can widen a real zone further, which only helps.
        zone_vol = max(lv.MIN_ZONE_VOL, min(tick_vol * lv.MIN_ZONE_TICKS, lv.GRID_ZONE_VOL))
        return zone_vol / tick_vol >= MIN_TICKS_PER_ZONE

    def drop_unsupported(self) -> int:
        """Decline every pair whose grid is too coarse, now rather than later.

        `reform` applies the same rule, but only when a series comes due -
        `REFORM_EVERY` is twenty bars, so a 15m series carries levels it should
        not have for five hours after a restart, producing touches and calls
        from them the whole time. The gate was correct and slow, and a restart
        is exactly when it needs to be fast: state restored from disk was
        formed under whatever geometry was current when it was saved.

        Returns how many pairs were dropped, so a caller can say so.
        """
        dropped = 0
        for feed, interval in sorted(self._levels):
            if self.supports(feed, interval):
                continue
            self._levels.pop((feed, interval), None)
            self._declined.add((feed, interval))
            dropped += 1
            log.info(
                "levels: %s %s declines a level - the grid is too coarse for a "
                "zone to be entered rather than crossed",
                feed,
                interval,
            )
        return dropped

    def reform(self, series: Series, when: float) -> list[lv.Level]:
        """Re-derive levels from the confirmed swings in the window."""
        key = (series.feed, series.interval)
        if not self.supports(series.feed, series.interval):
            # Said once per pair, because it is a property of the instrument
            # and the venue rather than an event, and repeating it every reform
            # would bury everything else.
            if key not in self._declined:
                self._declined.add(key)
                log.info(
                    "levels: %s %s declines a level - the grid is too coarse "
                    "for a zone to be entered rather than crossed",
                    series.feed,
                    series.interval,
                )
            # Anything already formed here was formed on the same bad geometry.
            self._levels.pop(key, None)
            series.since_reform = 0
            return []
        self._declined.discard(key)
        vol = self.vol.of(series.feed, series.interval)
        found = self.swings(series, vol)
        visible = pips.as_of(found, when)
        candidates = self._form(series, visible, vol)
        merged = lv.merge(self._levels.get(key, []), candidates, vol)
        self._levels[key] = self.prune(merged, series.closes[-1], vol, when)
        series.since_reform = 0
        self._record_shape(series, visible)
        return self._levels[key]

    def prune(self, levels: list[lv.Level], price: float, vol, when: float) -> list[lv.Level]:
        """Drop levels that are not earning their place.

        A swing price never returned to is not a level, it is a swing. On real
        history most of them are exactly that - warming from a fortnight of
        gold produced 148 levels of which 135 had never been touched - and
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
        deploy - restored models, then `AttributeError` on the first bar, five
        seconds after start. Nothing consumed the bus afterwards, so the
        symptom was dropped quotes and a silent journal rather than anything
        naming the cause.

        Filling the gaps from a default-constructed engine rather than from a
        hand-written list of names, because the hand-written list is the part
        that goes stale - it would need editing every time a field is added,
        which is precisely the thing nobody remembers to do. Anything the state
        carries wins; anything it lacks arrives at its default.
        """
        self.__dict__.update({**Engine().__dict__, **state})

    def touch_interval(self, feed: str = "", when: float | None = None) -> str:
        """Which interval's bars carry the touch check for all the others.

        The finest one available *at that moment*, which is not the same as the
        finest one overall and is the whole subtlety here. Venues keep far less
        fine history than coarse - Yahoo serves seven days of 1m against
        decades of 1w - so a replay of a few hundred bars per interval covers
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
    def _eras_from(first: dict[str, float]) -> list[tuple[float, str]]:
        """Era boundaries from the earliest time per interval.

        The half of `_eras` that does the work. Split out because the other
        half - finding those earliest times - was reading three hundred
        thousand rows to produce six numbers, and SQLite can answer it with a
        GROUP BY.
        """
        eras: list[tuple[float, str]] = []
        best = ""
        for interval, start in sorted(first.items(), key=lambda kv: kv[1]):
            if not best or confluence.rank(interval) < confluence.rank(best):
                best = interval
                eras.append((start, best))
        return eras

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

        return Engine._eras_from(first)

    def observe_bar(self, payload: dict) -> list[Call]:
        """One `prices.bars` message. Returns any calls it produced.

        **Forming and touching are separate jobs**, and this used to do both at
        one resolution. A daily level warmed from daily bars had its origins
        quantised to the day - and since a cold start replays six-figure bar
        counts, that was most of what any level knew about itself.

        So: every bar forms levels for its own interval, and only the *finest*
        interval's bars run the touch check, against every interval at once.
        That is the replay equivalent of `observe_quote`, which has always
        checked every interval on every quote and is why the live path never
        had this problem.

        The trap the doc warns about is running both - keeping the per-interval
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
        # A bar with no extremes is a doji as far as everything below is
        # concerned, and a doji has no leg in and no leg out - which is what an
        # origin is made of. The fallback above is deliberate, because a notice
        # from an older producer is better folded in flat than dropped, but it
        # must not be quiet: `prices.announce_bars` shipped for a while sending
        # close alone, every live bar arrived flat, and levels on the live path
        # were built from closing prices while the leg extremes existed only in
        # replayed history. Nothing said so. This is what would have said so.
        if high == low == close:
            key = (feed, interval, venue)
            if key not in self._flat_bars:
                self._flat_bars.add(key)
                log.warning(
                    "structures: %s %s from %s carries no high/low - levels on "
                    "this series are forming from closes alone",
                    feed,
                    interval,
                    venue or "an unnamed venue",
                )

        # The open was on the payload and read by nothing. Range estimators
        # need all four prices, and Yang-Zhang needs the open specifically -
        # it is the only one of them unbiased across an opening gap, and the
        # gap is exactly what the open measures.
        opened = float(payload.get("open") or close)

        agreed = self.consensus.observe(feed, interval, venue, when, high, low, float(close))
        if agreed is None:
            return []  # not enough venues on this bar yet
        high, low, close = agreed

        self._now = max(self._now, when)
        series = self.series(feed, interval)
        fresh = series.add(when, high, low, float(close), opened)
        # This timeframe's own volatility: a typical 4h move is not a typical
        # 5m move, and one estimate for both makes every threshold expressed in
        # volatility units wrong for all but whichever series updates most.
        vol = self.vol.of(feed, interval)
        # Once per *bar*, not once per venue row. `Consensus.observe`
        # deliberately answers again on every venue that reports a bar, so the
        # median improves within a sweep rather than waiting; `Series.add`
        # handles the repeat by overwriting. A volatility estimate has no such
        # handling - folding the same close in once per venue fed it a run of
        # zero returns and dragged the estimate down by however many venues
        # report past quorum. Measured on the live feeds: six venues on EURUSD
        # and GBPUSD divided it by four, five on XAUUSD by three, four on
        # BTCUSD by two, and US500 at exactly quorum was the only one correct.
        #
        # Everything this project expresses in volatility units divides by that
        # number, so distances read two to four times larger than they were:
        # zone width, resolve distance, KEEP_VOL, the edge gate. The cost of
        # taking the first quorum's median rather than the last venue's is a
        # rounding error beside it.
        if fresh:
            vol.update(float(close))
            # Whole-bar estimates, once per bar rather than once per venue -
            # same reasoning as the line above.
            vol.observe_bar(opened, high, low, float(close))
        # Pivots are session structures priced at today's scale, so they use the
        # reference estimate rather than the bar interval that happened to
        # deliver them - a 4h bar completing a day does not make it a 4h level.
        self._roll_sessions(feed, when, high, low, float(close), self.reference(feed))
        self._resolve_shapes(series, vol)
        if not series.ready:
            return []
        if series.due or not self._levels.get((feed, interval)):
            self.reform(series, when)

        # Formed. Whether this bar also *touches* is a separate question, and
        # the answer is no unless it is the finest series this instrument has -
        # otherwise the same interaction would be counted once here and again
        # when the fine bars arrive.
        if interval != self.touch_interval(feed, when):
            return []
        if not fresh:
            # ...and once per bar, for the same reason the volatility estimate
            # is. `Consensus.observe` answers again on every venue row, and the
            # median *moves* as venues arrive - on spx500, whose venues quote
            # genuinely different absolute prices, it moves by more than four
            # volatility units within a single bar. Checking touches on each
            # row fed that jitter to the tracker as though it were price: a
            # touch opened on one venue's row and resolved on the next one's,
            # at the same timestamp, having observed nothing but the median
            # rearranging itself. That is 45% of resolutions in this replay and
            # 46% in the production journal, and it is why two runs of the same
            # replay disagree - venue arrival order is not stable.
            return []
        calls: list[Call] = []
        # A bar is stamped with its **open** time, but it is not knowable until
        # it closes - and quotes carry wall clock. Feeding both to one tracker
        # mixed two clocks a bar apart: a touch opened by a quote and resolved
        # by the bar that closed after it recorded a *negative* duration, which
        # is 10% of resolved touches in the journal, every one of them 5m and
        # every one about 300 seconds. The number itself is the small harm. The
        # large one is that `horizon`, `trap_window` and the GAP_FACTOR weekend
        # guard all test `when - touch.started`, and a negative elapsed trips
        # none of them.
        # ...but never later than now, because the bar being delivered is
        # usually the one still forming. Stamping that one at its close puts it
        # up to a whole interval in the *future*, and a quote arriving in the
        # meantime then resolves a touch before it started - the same negative
        # duration this line was written to remove, in the other direction.
        # Measured on production: it took negatives from 1.7% of outcomes to
        # 5.7%, at -98, -98, -98, -7 and -1 seconds rather than the clean one
        # bar of before, which is the shape of a partly-formed bar rather than
        # a closed one.
        #
        # `min` is right for both cases without knowing which this is. A bar
        # that has closed was knowable at its close and that is earlier than
        # now; one still forming is knowable now. During a seed every bar is
        # long closed, so this leaves the replay alone.
        observed = min(when + lv.SECONDS.get(interval, 0.0), time.time())
        for other in self.intervals_for(feed):
            # `when` is the bar's *open*, which is what says whether a touch
            # lived through the range this bar is about to hand over.
            calls += self.check(feed, other, float(close), observed, low, high, since=when)
        return calls

    def observe_quote(self, payload: dict) -> list[Call]:
        """A quote moves price against existing levels without re-forming them.

        Quotes are what make a touch detectable in time to matter - waiting for
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
        # What the venues agree on, not whichever one published last. See
        # `Quotes`: the raw mid made a change of publisher look like a move of
        # three and a half volatility units on spx500, which is past the
        # distance that resolves a touch.
        agreed = self.quotes.observe(feed, str(payload.get("venue") or ""), when, float(mid))
        # Quotes feed the tick-level estimate, which is the common denominator
        # every timeframe's levels are ranked against - so it takes the agreed
        # price too, or the disagreement between venues is counted as movement
        # and inflates the very denominator everything else is divided by.
        vol = self.vol.of(feed)
        vol.update(agreed)
        calls: list[Call] = []
        # Pivot levels live under their session name, so quotes must check
        # every interval this instrument has levels at, not just the bar ones.
        for interval in self.intervals_for(feed):
            calls += self.check(feed, interval, agreed, when)
        return calls

    # ------------------------------------------------------------- touching

    def cost_of(self, feed: str, vol: Volatility | None = None) -> float:
        """What crossing the spread costs here, in volatility units.

        The same quantity on every instrument and timeframe, which is the only
        way it can be compared against an expected push measured the same way.
        A spread of 3bps is nothing on a violent daily chart and most of the
        move on a quiet 3m one - in units, that difference is the answer rather
        than something a reader has to hold in their head.

        A **median** over a recent window, for the reason the consensus is also
        a median: a mean is dragged by the outlier it exists to ignore. The cost
        that matters is what this instrument normally costs to trade, not
        whatever the spread happened to be in the microsecond a level was
        touched - one wide print during a release must not disqualify an edge
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

    def _deliver(
        self, level: lv.Level, done: reactions.Touch, vol: Volatility, when: float
    ) -> None:
        """Everything downstream of a resolved touch, wherever it resolved.

        Both ways a touch can end have to arrive here. `update` closing one on
        a price and `expire` closing one on the clock are the same event to a
        level, to the journal and to `facto`, and only the first was being
        delivered.
        """
        # The origin, not the extreme. The extreme is a wick - liquidity taken
        # a fraction beyond the level at a price nobody traded around - while
        # the origin is where the leg in ended and the leg out began, which is
        # the price the level is actually drawn at.
        level.observe_touch(done.origin or done.extreme, vol, when)
        # The wick is the zone's far edge, not noise to discard.
        level.observe_wick(done.features.side, done.origin or done.extreme, done.extreme, vol)
        log.debug("level %s %.5g resolved %s", level.feed, level.price, done.outcome)
        self._resolved.append((level, done))
        # Bounded: a consumer that stops draining must not become a slow memory
        # leak in a service designed to run for months.
        if len(self._resolved) > MAX_RESOLVED:
            del self._resolved[: len(self._resolved) - MAX_RESOLVED]

    def trading(self, feed: str, when: float) -> bool:
        """Is this instrument's market open, or have its bars simply stopped?

        Judged on **bars**, because quotes keep arriving after a market shuts.
        On a Saturday morning the FX venues were still answering every poll -
        quotes sixteen minutes old - while the last 3m bar was nine hours old.
        Those quotes carry Friday's closing price, and price that cannot move
        is not price arriving at a level.

        Without this, an instrument that had closed still opened touches on its
        frozen price and published directional calls for them: USDCNH and
        AUDUSD both alerted on a Saturday, with a `down 97%` on a market where
        nothing could go anywhere.

        `GAP_FACTOR` is the same judgement applied at the other end - it throws
        away a touch that *spans* a closure, because the reopening gap is not a
        reaction. This stops one being opened inside a closure at all.

        Silent about instruments it cannot judge: no series, or none yet, means
        no evidence of a closure rather than evidence of one, and crypto - which
        genuinely trades all weekend - keeps printing bars and passes.
        """
        interval = self.touch_interval(feed, when)
        series = self._series.get((feed, interval))
        if series is None or not series.times:
            return True
        return (when - series.times[-1]) <= lv.SECONDS.get(interval, 60.0) * STALE_BARS

    def _drain_expired(self, when: float) -> None:
        """Deliver the touches `expire` closed on the clock rather than a price.

        `Tracker.expire` closes them, sets an outcome and folds them into the
        kNN memory - and its return value was discarded, so that memory was the
        only place they reached. No `level.record`, no Kalman update, nothing in
        `_resolved`, so nothing in the journal and nothing in `facto`. Measured
        on a replay of the stored bars: 26.7% of all resolutions, and because
        it is where a break that got through and went quiet resolves, 97.5% of
        breaks. The break rate downstream read 0.3% against a real 8.2%.

        Touches are keyed by (feed, price) and `expire` hands back only the
        touch, but a `Touch` carries its feed, interval and level price, so the
        level can be found again without the tracker holding a reference to it
        - which matters, because the engine is pickled and a new field would
        have to be migrated.
        """
        expired = self.tracker.expire(when)
        if not expired:
            return
        known = {
            (level.feed, level.interval, round(level.price, 8)): level
            for levels in self._levels.values()
            for level in levels
        }
        for touch in expired:
            level = known.get((touch.feed, touch.interval, round(touch.level_price, 8)))
            if level is None:
                # The level was re-formed or pruned while the touch was open.
                # Nothing to credit it to; the kNN memory already has it.
                continue
            # `expire` cannot do this itself - it has the touch, not the level.
            level.record(touch.features.side, touch.outcome, touch.push_vol, when)
            if touch.outcome is lv.Outcome.BREAK and touch.broke_at:
                level.broke_at = touch.broke_at
            # Held back, which the resolving path does and this one did not.
            # A touch that expired did so because price sat at the level and
            # never went anywhere, so price is still there - and leaving the
            # level re-armed opened another touch against the same visit on the
            # very next observation, which produced another call and another
            # alert. On a market that has closed, where the price is frozen and
            # nothing can ever resolve, that is a loop: it fired repeatedly on
            # USDCNH and AUDUSD at the same levels on a Saturday morning.
            #
            # `True` rather than `contains(price)` because there is no current
            # price here - expiry is a clock event. It is also the right answer:
            # the visit is not over, only this observation of it. `check`
            # re-arms it once price is REARM_VOL away, which is what "over"
            # means.
            level.waiting = True
            self._deliver(level, touch, self.vol.of(touch.feed, touch.interval), when)

    def check(
        self,
        feed: str,
        interval: str,
        price: float,
        when: float,
        low: float | None = None,
        high: float | None = None,
        since: float | None = None,
    ) -> list[Call]:
        """Advance every open interaction, and open one where price has arrived.

        `low` and `high` are how far the bar reached beyond its close. Both are
        offered and each touch takes the end that faces the side it arrived
        from. Without them the extreme and the origin are the same number, and
        the distinction between where liquidity was taken and where the level
        is drawn disappears.

        `since` is when the bar supplying them **opened**, and it exists to stop
        a range being applied to a touch that did not live through it. A quote
        opens a touch part way through a bar; the bar then arrives carrying a
        low and a high that describe the *whole* period, including the minutes
        before that touch existed. Applied to it, the touch resolves instantly
        on movement that predates it - recording a large push, a duration of
        zero, and `run_vol` of exactly 0.00 because no leg in was ever seen.

        That was **33.6% of production outcomes**, and 41.9% of 3m ones. See
        todo 0g. A touch that began inside this bar therefore sees only the
        close, and picks the wick up on the next bar it genuinely lives through.
        """
        vol = self.vol.of(feed, interval)
        if not vol.warm:
            return []
        calls: list[Call] = []
        for level in self._levels.get((feed, interval), []):
            open_touch = self.tracker.open_touch(level)
            if open_touch is not None:
                # The wick belongs to this touch only if the touch was already
                # open when the bar carrying it opened.
                within = since is not None and open_touch.started >= since
                done = self.tracker.update(
                    level,
                    price,
                    vol,
                    when,
                    None if within else low,
                    None if within else high,
                )
                if done is not None:
                    # The origin, not the extreme. The extreme is a wick -
                    # liquidity taken a fraction beyond the level at a price
                    # nobody traded around - while the origin is where the leg
                    # in ended and the leg out began, which is the price the
                    # level is actually drawn at.
                    self._deliver(level, done, vol, when)
                    # Only hold the level back if price is *still* in the zone.
                    # An interaction that resolved by price leaving has already
                    # done the leaving, and making it wait for a second exit
                    # would drop the next genuine approach.
                    level.waiting = level.contains(price, vol)
                continue

            if not level.contains(price, vol):
                # Out of the zone is not the same as away from the level. Price
                # sitting on the edge crosses it constantly, and re-arming on
                # each crossing counts a consolidation as dozens of turns - the
                # residue of the same bug the `waiting` flag was added for,
                # which the flag alone did not reach.
                if abs(level.distance_vol(price, vol)) >= lv.REARM_VOL:
                    level.waiting = False
                continue

            # Inside the zone, but this is the same visit that just resolved.
            if level.waiting:
                continue
            # ...or the market is shut and this is Friday's price, still being
            # answered to every poll. Checked here rather than at the top of
            # `check` on purpose: an open touch must still be advanced, so that
            # GAP_FACTOR can discard it, and levels must still be formed. It is
            # only *opening* one that a closed market makes meaningless.
            if not self.trading(feed, when):
                continue
            side = self._approach(level, price)
            features = reactions.features_for(
                level, side, price, vol, approach_vol=self._speed(feed, interval, vol), when=when
            )
            touch = self.tracker.begin(level, price, features, when)
            inference = reactions.infer(
                level,
                side,
                features,
                self.tracker.memory,
                vol,
                price=price,
                cost_vol=self.cost_of(feed, vol),
            )
            # Kept on the touch so the resolution can be scored against what
            # was believed at the time - including the touches that were never
            # published, which is the half of the distribution nothing has ever
            # been able to look at. See `Touch.edge`.
            touch.edge = inference.edge
            touch.probability_up = inference.probability_up
            touch.base_rate_up = inference.base_rate_up
            touch.actionable = inference.actionable
            # A call is priced entirely in volatility units, so an estimate
            # that has not warmed makes every number on it meaningless rather
            # than merely uncertain. See `Volatility.warm`: the guard existed
            # and nothing asked it, and a brent call went out claiming a push
            # of 10,229 volatility units.
            if not vol.warm:
                continue
            calls.append(
                Call(
                    feed=feed,
                    interval=interval,
                    level=level,
                    inference=inference,
                    price=price,
                    time=when,
                    origin=self._origin_at(feed, interval, level.price, vol),
                )
            )
            self.calls += 1
        self._drain_expired(when)
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
        """Which side price came from - the previous bar, not the current one.

        Using the current price would be circular: inside the zone, price is by
        definition next to the level, and the question is where it came *from*.
        """
        series = self._series.get((level.feed, level.interval))
        if series is not None and len(series.closes) >= 2:
            return level.side_of(series.closes[-2])
        return level.side_of(price)

    def reference(self, feed: str) -> Volatility:
        """The estimate levels from every timeframe are compared against.

        Cross-timeframe questions - which level is nearest, is this one worth
        acting on - need one denominator, or "three volatility units away" means
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
        *notice* per sweep rather than a series - roughly one bar per venue per
        minute. Levels need hundreds, so bootstrapping from the bus alone would
        take days while a backfilled store already holds the history.

        The store is opened **read-only**: the numeric layer reads prices, it
        does not own them, and enforcing that at the driver is cheaper than
        remembering it.

        Bars are replayed in time order through the ordinary path, so levels
        form from confirmed swings exactly as they would live, and the touch
        statistics that make the directional inference work exist from the
        first minute. Calls produced during the replay are discarded - they
        describe touches that happened days ago, and publishing them would
        alert on history.
        """
        wanted = tuple(intervals) or self.intervals
        if not Path(database).exists():
            return 0
        # Both are aggregates, so the count and the era boundaries come from
        # SQLite rather than from a list of rows held in this process. The rows
        # themselves are then streamed: materialising them cost 410MB on a
        # 908MB host and OOM-killed every cold start it attempted.
        total, first_seen = _bar_span(database, feeds, wanted, bars)
        if not total:
            return 0

        # Worked out before the replay starts, so the first bar is judged by the
        # same rule as the last rather than by whichever series happened to have
        # arrived.
        eras = self._eras_from(first_seen)
        replayed = 0
        feeds_seen: set[str] = set()
        # A cold start replays six-figure bar counts and says nothing until it
        # finishes, which is minutes of a service that looks hung - and the one
        # thing this project keeps relearning is that silence has to say which
        # kind it is. `on_progress` lets a terminal draw a bar; without one the
        # log carries it, because that is where a running service is read from.
        beat = max(1, total // 100)
        spoken = max(1, total // 10)
        self._touch_eras = eras
        try:
            for row in _read_bars(database, feeds, wanted, bars):
                self.observe_bar(row)  # calls discarded on purpose
                replayed += 1
                feeds_seen.add(str(row["feed"]))
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
            ", ".join(sorted(feeds_seen)) or "nothing",
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
