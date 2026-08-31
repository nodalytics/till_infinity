"""Watching the bus, learning continuously, saying something when it matters.

This is the always-on layer. It consumes `prices.quotes` and `prices.bars`,
updates its models on every message, and publishes what it finds:

    prices ──▶ structures ──┬──▶ structures.signals ──▶ agents
                            └──▶ alerts (unambiguous only)

Two outputs because two kinds of finding. Most signals are *evidence*: a venue
looks odd, and whether that matters depends on the calendar, which this layer
cannot see. Those go to `structures.signals` for an agent to weigh against the
fundamentals.

A few are unambiguous. A venue that has not moved in five minutes while five
others have does not need a language model to interpret it and does not need a
release to explain it, so it goes straight to `alerts`. Making everything wait
for an agent would put an LLM in the path of the one message that most needs to
arrive during an outage.

Nothing here needs an API key.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import statistics
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from ..bus import ALERTS, BARS, MACRO, QUOTES, RESOLUTIONS, SIGNALS, Bus, Message
from ..journal import Journal, decide, observe, outcome
from ..logging import get_logger
from . import confluence as cf
from . import store
from .activity import Book as ActivityBook
from .anomaly import Detector
from .baseline import Bench
from .baseline import vector as bench_vector
from .breaking import Breaks
from .config import DRIFT_INTERVALS, Settings
from .drift import Drift
from .engine import Engine
from .macro import Macro, since_default, stored
from .models import Shape, Signal
from .sessions import Clock

log = get_logger(__name__)

#: `MACRO` is a notice with a count in it, not the data - see `bus.py`. The
#: series are read from the store when it arrives, which is the contract the
#: bus was written to and the reason a poll of thousands of historic rows does
#: not become thousands of messages.
TOPICS: tuple[str, ...] = (QUOTES, BARS, MACRO)

#: How many bars a feed's deepest window must hold before it counts as warm.
#:
#: A fifth of the engine's window. Not "has any series at all", which is what
#: this asked first and which reported eleven instruments as warm on about
#: twenty live bars each while the store held 2,700 apiece.
WARM_MIN_BARS = 100

#: Shapes that never need a model or a calendar to be worth sending.
UNAMBIGUOUS: frozenset[Shape] = frozenset({Shape.STALE})

#: Venues needed before a median close means anything, matching the quote side.
MIN_VENUES = 3

#: How far from the group's median a venue may be before it is treated as
#: quoting a different **unit** rather than a different price.
#:
#: `FOREXCOM:USOIL` ran 8047-8397 against 80-85 everywhere else, and
#: `FOREXCOM:UKOIL` 8516-8891 against 85-92 - oil quoted in cents, a clean
#: factor of 100, across 70,402 stored wti quotes and 61,924 brent ones. That
#: is not a dislocation: it drags the median, makes every spread comparison
#: meaningless, and reads as one venue permanently disagreeing with five.
#:
#: A real disagreement between venues is basis points. Two times is already far
#: beyond anything a live market produces, and far below the hundred-fold a
#: unit error produces, so there is no band where this has to guess.
SCALE_LIMIT = 2.0


def _passes(level: object) -> list[str]:
    """The formations that drew a level, from its "+"-joined origin.

    Pivots are named `pivot:PP` and are one formation however many of them
    merged, so the split is on "+" and the count is of distinct passes.
    """
    drawn = getattr(level, "origin", "")
    if not isinstance(drawn, str) or not drawn:
        return []
    return sorted({part.partition(":")[0] for part in drawn.split("+") if part})


def single_source_feeds() -> frozenset[str]:
    """Feeds only one venue carries, so `MIN_VENUES` must not apply to them.

    Read from the price catalogue rather than guessed: a feed whose symbol map
    has exactly one source is one nobody else quotes. Synthetics are the case
    that matters - they have no underlying, so the broker is not one opinion
    among several, it is the instrument.

    Import kept local because `structures` does not otherwise depend on
    `prices`, and a missing catalogue must not stop the engine starting.
    """
    try:
        from ..prices.config import FEEDS
    except Exception:  # pragma: no cover - prices is always present in practice
        return frozenset()
    return frozenset(name for name, feed in FEEDS.items() if len(feed.symbols) <= 1)


class BarConsensus:
    """Median close per (instrument, interval), for the drift detector.

    Kept per interval rather than collapsed, because drift is now judged across
    timeframes and needs to know which one each price came from.

    Bars arrive one venue at a time. Feeding drift a single venue's series
    would mix market moves with that venue's own quirks, which is the thing
    having six venues exists to cancel.
    """

    def __init__(self) -> None:
        self._closes: dict[tuple[str, str], dict[str, tuple[int, float]]] = {}

    def observe(self, payload: dict) -> tuple[str, float, str] | None:
        feed = str(payload.get("feed") or "")
        venue = str(payload.get("venue") or "")
        interval = str(payload.get("interval") or "")
        close = payload.get("close")
        when = payload.get("time")
        if interval not in DRIFT_INTERVALS or not feed or not venue:
            return None
        if not isinstance(close, int | float) or not close:
            return None

        group = self._closes.setdefault((feed, interval), {})
        group[venue] = (int(when or 0), float(close))
        # Only the venues that reported this same bar, so the median is a
        # snapshot rather than a blend of different minutes.
        latest = max(ts for ts, _ in group.values())
        aligned = [price for ts, price in group.values() if ts == latest]
        if len(aligned) < MIN_VENUES:
            return None
        aligned = _same_unit(aligned)
        if len(aligned) < MIN_VENUES:
            return None
        return feed, statistics.median(aligned), interval


def _same_unit(prices: list[float]) -> list[float]:
    """Drop venues quoting a different unit from the group.

    The median is the reference because it is what the group agrees on and it
    survives one venue being wrong - which is the whole case this exists for.
    A venue outside `SCALE_LIMIT` either way is not disagreeing about price, it
    is counting in something else.
    """
    if not prices:
        return prices
    middle = statistics.median(prices)
    if middle <= 0:
        return prices
    return [p for p in prices if 1 / SCALE_LIMIT <= p / middle <= SCALE_LIMIT]


def alert_payload(signal: Signal) -> dict[str, object]:
    """The message a person actually reads, as opposed to the record.

    `Signal.title` is built for a log line - venue, feed, then the whole detail
    string - which arrives on a phone as one long sentence with the numbers
    buried in it. What a reader wants first is the instrument, the timeframe and
    the direction; the evidence belongs underneath, one claim per line.

    Routing fields (`shape`, `instrument`, `venue`, `direction`) are set for the
    notification filter and are deliberately not rendered again - the title
    already carries them.
    """
    fields = {
        "instrument": signal.feed,
        "venue": signal.venue,
        "shape": str(signal.shape),
        "direction": signal.direction,
    }
    if signal.shape is not Shape.LEVEL:
        return {
            "title": signal.title,
            "body": "",
            "level": "warning",
            "fields": {**fields, "score": f"{signal.score:.3f}"},
            "source": "structures",
        }

    got = signal.features
    price = got.get("level", 0.0)
    up = signal.direction == "up"
    probability = got.get("probability") or (
        got.get("probability_up", 0.5) if up else 1.0 - got.get("probability_up", 0.5)
    )
    base = got.get("base_rate_up", 0.5) if up else 1.0 - got.get("base_rate_up", 0.5)
    touches, similar = got.get("own_touches", 0.0), int(got.get("neighbours", 0))
    risk = got.get("risk_vol", 0.0)
    push = got.get("expected_push_vol", 0.0)

    story = (
        f"confirmed by {', '.join(t for t in signal.confluence if t != signal.interval)}"
        if len(signal.confluence) > 1
        else "this timeframe only"
    )
    body = [
        f"level {price:.5g} · {story}",
        "",
        f"{signal.direction} {probability:.0%} - against a {base:.0%} base rate",
        f"expected push {push:+.2f}v" + (f" · risk {risk:.2f}v" if risk else ""),
        f"{touches:.0f} touches here + {similar} similar · strength {got.get('strength', 0.0):.2f}",
    ]
    return {
        "title": f"{signal.feed.upper()} {signal.interval} - {signal.direction}",
        "body": "\n".join(body),
        "level": "warning",
        "fields": fields,
        "source": "structures",
    }


class Watcher:
    """The online layer as a running service."""

    def __init__(
        self,
        bus: Bus,
        *,
        settings: Settings | None = None,
        group: str = "structures",
        journal: Journal | None = None,
        memory: int = 500,
    ) -> None:
        self.bus = bus
        self.settings = settings or Settings.from_env()
        self.group = group
        self.journal = journal
        self.memory = memory
        self.detector = Detector(
            warmup=self.settings.warmup,
            quantile=self.settings.quantile,
            sigma=self.settings.sigma,
        )
        self.drift = Drift()
        self.bars = BarConsensus()
        #: Key levels and what they do when price arrives. Fed by both bars
        #: (which form the levels) and quotes (which detect the touch in time
        #: to matter - waiting for a 5m close reports it after the fact).
        self.engine = Engine(
            charge_spread=self.settings.charge_spread,
            single_source=single_source_feeds(),
            formation=self.settings.formation,
        )
        #: What the hour of the day has been worth, per instrument. Learns
        #: from resolutions and from the volatility it sees; asserts
        #: nothing until an hour has earned it.
        self.clock = Clock()
        #: Monetary policy per currency, folded onto every level call and
        #: emitted as its own shape when a stance turns. Empty until the news
        #: service has collected something, and silent while empty - a level
        #: call is correct without it.
        self.macro = Macro()
        #: Every model that could replace the kNN, scored beside it on the same
        #: touches. Decides nothing - the whole point is that "the kNN works"
        #: has never been distinguished from "the features work and any model
        #: would do", and two separate runs would compare two samples rather
        #: than two models.
        self.bench = Bench()
        #: Will this level give way? A different question from which way price
        #: goes, and the first one anything here has separated: `up_rate` is
        #: the strongest direction feature there is and predicts a break at
        #: AUC 0.4892, while `approach_vol` and `depth_vol` together reach
        #: 0.658. See research/force.md. Publishes a number and decides
        #: nothing.
        self.breaks = Breaks()
        #: The newest observation time already taken, so a re-read after a
        #: poll asks for the tail rather than for four hundred days again.
        self._macro_since = 0.0
        #: How busy each instrument's bars usually are, so a touch can be
        #: stamped with whether this one was unusual. Decides nothing.
        self.activity = ActivityBook()
        #: The most recent activity share per series, so a call can be
        #: stamped without threading the bar's volume down three layers.
        self._busy: dict[tuple[str, str], float] = {}
        self._sent: OrderedDict[tuple[str, str, str], float] = OrderedDict()
        #: Level -> the journal entry recording why we called it. Kept so the
        #: result can be attached to the decision that predicted it, which is
        #: the whole difference between a log and a training example.
        self._awaiting: OrderedDict[tuple[str, float], str] = OrderedDict()
        #: Feeds already replayed in this process, whether or not the replay
        #: left a series behind. See `warm_new`.
        self._seeded: set[str] = set()
        self.outcomes = 0
        self._saved = 0.0
        self.published = 0
        self.alerted = 0

    # ---------------------------------------------------------- persistence

    @property
    def cold(self) -> bool:
        """True when the engine holds no levels, however it was started.

        The condition that matters is "do I have levels", not "did state
        load". A state file saved before any history existed restores an empty
        engine perfectly happily, and keying the warm-up off the load meant
        that emptiness became permanent: every restart restored nothing and
        skipped warming because the restore had *succeeded*.
        """
        return not any(self.engine._levels.values())

    def unwarmed(self) -> tuple[str, ...]:
        """Feeds the store has bars for and the engine has never seen.

        An instrument added to a running deployment lands here: it collects
        bars immediately and forms levels only from the live stream, one bar at
        a time, while every feed that was present at the last cold start got a
        several-hundred-thousand-bar replay. Eleven synthetics added this way
        had 2,700 stored bars each and seven levels between them.

        The engine's own series are the test rather than its levels: a feed
        that has been replayed and legitimately formed no level is warm, and
        seeding it again would count every one of its bars twice.

        **Thin counts as unwarmed, and "has a series" did not.** The first
        version of this asked only whether the engine had ever seen the feed,
        and the eleven new synthetics had - about twenty bars each, collected
        live since they were added. So it reported nothing to warm while they
        sat on 2,700 stored bars apiece. A window holding less than
        `WARM_MIN_BARS` is not a warm feed, it is a feed at the start of a very
        slow one.

        The overlap that costs is real and small: replaying a feed with twenty
        live bars re-counts those twenty. Against five hundred replayed bars
        that is noise, and the alternative is leaving the instrument thin for
        hours.
        """
        path = Path(self.settings.prices_db)
        if not path.exists():
            return ()
        deepest: dict[str, int] = {}
        for (feed, _interval), series in self.engine._series.items():
            deepest[feed] = max(deepest.get(feed, 0), len(series.closes))
        seen = {f for f, n in deepest.items() if n >= WARM_MIN_BARS} | self._seeded
        try:
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
                stored = {row[0] for row in conn.execute("SELECT DISTINCT feed FROM bars")}
        except sqlite3.Error as exc:
            log.warning("structures: could not list stored feeds: %s", exc)
            return ()
        return tuple(sorted(stored - seen))

    def warm_new(self, on_progress: Callable[[int, int], None] | None = None) -> int:
        """Replay the store for feeds the engine has no history of.

        Called after every restore, not only a cold one. `cold` asks whether
        the engine holds *any* levels, which was the right question when the
        instrument set never changed and is the wrong one now: with 2,018
        levels restored the engine is not cold, so the warm-up was skipped
        entirely and eleven new feeds were left to learn from the bus at
        roughly one bar a minute.

        Safe to call every start because it seeds only what has no series, and
        a feed with no series has no bars to double count.
        """
        if not self.settings.warm:
            return 0
        feeds = self.unwarmed()
        if not feeds:
            return 0
        log.info("structures: warming %d feed(s) with no history: %s", len(feeds), ", ".join(feeds))
        # Remembered whether or not a series results. A feed whose bars cannot
        # form one - too few venues, and not marked single-source - would
        # otherwise read as unwarmed and be replayed on every call, announcing
        # work it has already done.
        self._seeded.update(feeds)
        try:
            replayed = self.engine.seed(
                self.settings.prices_db, feeds=feeds, on_progress=on_progress
            )
            self._decline_unsupported()
            return replayed
        except Exception as exc:  # warming is an optimisation, not a requirement
            log.warning("structures: could not warm %s: %s", ", ".join(feeds), exc)
            return 0

    def warm(self, on_progress: Callable[[int, int], None] | None = None) -> int:
        """Fill the level windows from stored price history.

        The bus carries a notice per sweep, not a series - roughly one bar per
        venue per minute - so an engine that only learned from it would take
        days to see enough bars to place a level. The store already holds the
        history, read-only.

        `on_progress(done, total)` is for a caller with a terminal to draw into.
        Without one the replay reports itself to the log instead, which is the
        only place a running service can be watched from.
        """
        if not self.settings.warm:
            return 0
        try:
            replayed = self.engine.seed(self.settings.prices_db, on_progress=on_progress)
            # Warming forms levels for every pair it has bars for, including
            # the ones whose grid cannot carry one. Decline them here rather
            # than waiting for each series to come due for a reform.
            self._decline_unsupported()
            return replayed
        except Exception as exc:  # warming is an optimisation, not a requirement
            log.warning("structures: could not warm from %s: %s", self.settings.prices_db, exc)
            return 0

    def load(self) -> bool:
        """Restore what was learned last run. False means starting cold."""
        state = store.load(self.settings.state_dir)
        if not state:
            return False
        self.detector = state.get("detector", self.detector)
        self.drift = state.get("drift", self.drift)
        self.engine = state.get("engine", self.engine)
        self.clock = state.get("clock", self.clock)
        self.activity = state.get("activity", self.activity)
        self.bench = state.get("bench", self.bench)
        self.breaks = state.get("breaks", self.breaks)
        # Configuration re-applied over the restore, and this is not tidying.
        # The pickled engine carries the settings it was **first** built with,
        # so every one of these was inert from the moment a state file existed:
        # production drew levels with `pip` alone for the whole life of a
        # `STRUCTURES_FORMATION` that asked for three passes, and the only
        # symptom was `run` and `origin` never drawing anything.
        #
        # What is learned is kept - the levels, their touch history, the
        # filters. What was *chosen* comes from this deployment.
        self.engine.draw_with(self.settings.formation)
        self.engine.charge_spread = self.settings.charge_spread
        self.engine.consensus.single_source = single_source_feeds()
        log.info(
            "structures: restored models (%s), drawing with %s",
            self.detector.seen(),
            "+".join(self.engine.passes),
        )
        # Restored levels were formed under whatever geometry was current when
        # the state was saved, which is not necessarily this one.
        self._decline_unsupported()
        return True

    def _decline_unsupported(self) -> None:
        """Drop pairs whose grid is too coarse to carry a level, and say so."""
        dropped = self.engine.drop_unsupported()
        if dropped:
            log.info("structures: %d instrument/timeframe pair(s) declined", dropped)

    def save(self) -> None:
        if self.bench.scores:
            # Logged rather than only stored, because a comparison nobody reads
            # settles nothing - and this one exists to settle whether the model
            # behind every level call is earning its complexity.
            log.info("structures: model bench\n%s", self.bench.report())
        try:
            store.save(
                {
                    "detector": self.detector,
                    "drift": self.drift,
                    "engine": self.engine,
                    "bench": self.bench,
                    "breaks": self.breaks,
                    "clock": self.clock,
                    "activity": self.activity,
                },
                self.settings.state_dir,
            )
        except Exception as exc:  # losing a save must not stop the watch
            log.warning("structures: could not save state: %s", exc)
        self._saved = time.monotonic()

    # -------------------------------------------------------------- sending

    def fresh(self, signal: Signal) -> bool:
        """True unless this exact finding was sent inside the cooldown."""
        now = time.time()
        last = self._sent.get(signal.key)
        if last is not None and now - last < self.settings.cooldown:
            return False
        self._sent[signal.key] = now
        self._sent.move_to_end(signal.key)
        while len(self._sent) > self.memory:
            self._sent.popitem(last=False)
        return True

    def direct(self, signal: Signal) -> bool:
        """Whether this goes to a human without an agent in between.

        Deliberately *not* keyed on score. Score measures statistical rarity,
        and rarity is not unambiguity - an unusually wide spread is rare and is
        exactly the case that needs the calendar before anyone is woken. What
        qualifies is a reading that no fundamental could explain: a feed that
        has stopped, or a price so far from every other venue that it is a
        broken quote rather than a market opinion.
        """
        if not self.settings.alert_direct:
            return False
        if signal.shape in UNAMBIGUOUS:
            return True
        # A level call is the exception to the paragraph above, and on purpose.
        # It is not unambiguous in that sense - a fundamental absolutely can
        # explain why a level gave way - but it is the only shape here that is
        # a *finding* rather than a fault, and the one the channel exists for.
        # Every call that reaches this point is already `actionable`
        # (`_level_calls` drops the rest), which is a stricter gate than any
        # score: enough evidence, enough separation from the base rate, enough
        # size. Routing it through agents that are switched off means publishing
        # it to a topic nobody is subscribed to.
        if signal.shape is Shape.LEVEL:
            return self.settings.alert_levels
        return (
            signal.shape is Shape.DISLOCATION
            and signal.features.get("abs_dev_bps", 0.0) >= self.settings.direct_dev_bps
        )

    async def emit(self, signals: Sequence[Signal]) -> int:
        """Publish signals, alerting directly on the unambiguous ones."""
        sent = 0
        for signal in signals:
            if not self.fresh(signal):
                continue
            await self.bus.publish(SIGNALS, signal.to_dict(), source="structures")
            self.published += 1
            sent += 1

            if self.direct(signal):
                await self.bus.publish(ALERTS, alert_payload(signal), source="structures")
                self.alerted += 1

            # Journalled with the features it was found from, because those are
            # the inputs a later model would need and they cannot be recovered
            # from the stores - the consensus at that instant is not written
            # down anywhere else.
            ref = await decide(
                self.journal,
                signal.title,
                rationale=signal.detail,
                actor="structures",
                context={
                    "shape": str(signal.shape),
                    "score": signal.score,
                    # The three that identify *what* this is about. They were
                    # on the Signal all along and simply were not written down,
                    # so every recorded call was anonymous as to instrument and
                    # timeframe - which made "how does volatility scale across
                    # intervals" unanswerable from our own record, and it is a
                    # question we went looking for an answer to.
                    #
                    # `feed` was recoverable from the first tag and `interval`
                    # was nowhere at all. Both are here now, because a tag is
                    # for filtering and a context is for measuring.
                    "feed": signal.feed,
                    "interval": signal.interval,
                    "venue": signal.venue,
                    "direction": signal.direction,
                    "market": signal.market,
                    "confluence": "+".join(signal.confluence),
                    # The level's name rather than its price. Without it a
                    # record cannot be added up: the filter moves the price
                    # whenever the level learns, so two trades on one level are
                    # journalled at two prices and group as two levels.
                    "level_id": signal.level_id,
                    **signal.features,
                },
                tags=(signal.feed, signal.venue, str(signal.shape), signal.interval),
                confidence=min(1.0, signal.score),
            )
            if ref and signal.shape is Shape.LEVEL:
                # Level calls only. A touch resolving is unambiguous ground
                # truth about what followed; a wide spread has no comparable
                # moment of being proven right or wrong, and pretending it does
                # would fill the record with labels nobody could check.
                self._remember(signal.feed, signal.features.get("level"), ref)
        return sent

    # ------------------------------------------------------------- outcomes

    def _remember(self, feed: str, level_price: float | None, ref: str) -> None:
        """Note which decision predicted what would happen at this level."""
        if level_price is None:
            return
        key = (feed, round(float(level_price), 8))
        self._awaiting[key] = ref
        self._awaiting.move_to_end(key)
        while len(self._awaiting) > self.memory:
            self._awaiting.popitem(last=False)

    def _benchmark(self, level: object, touch: object) -> None:
        """Put one resolved touch through every model, the kNN included.

        **Direction**, not hold-versus-break, because direction is what the kNN
        actually predicts and a comparison has to be on the incumbent's own
        quantity. `Memory.prior` returns P(up); so does everything here.

        **The same neighbour set for all of them**, derived once. That is what
        makes this like-for-like rather than two numbers from two runs: the
        fixed distance and the learned one are handed identical evidence, and
        the only difference is how they weight it.

        **The touch itself is excluded.** It is added to memory during
        resolution, so it can appear among its own neighbours at distance zero
        and hand every model the answer - which would report a perfect score
        for whichever model trusted its nearest neighbour most.

        Wrapped, because this is measurement and not machinery: a model that
        raises must not stop the service recording what happened, which is the
        one thing here that cannot be recomputed later.
        """
        try:
            went_up = float(touch.push_vol) > 0
            found = [
                (distance, other)
                for distance, other in self.engine.tracker.memory.neighbours(touch.features)
                if other is not touch
            ]
            if not found:
                return
            keys = [bench_vector(other.features) for _d, other in found]
            values = [1.0 if other.push_vol > 0 else 0.0 for _d, other in found]
            # The kNN's own answer over exactly this evidence: distance
            # weighted, the way `Memory.prior` weights it.
            weights = [1.0 / (1.0 + d) for d, _o in found]
            total = sum(weights)
            said = (
                sum(w * v for w, v in zip(weights, values, strict=True)) / total
                if total > 0
                else 0.5
            )
            self.bench.observe(
                touch.features,
                went_up,
                neighbours=list(zip(keys, values, strict=True)),
                level_id=getattr(level, "id", ""),
                knn_said=said,
                # The band this touch belongs to. Without it every model is
                # fitted and scored on a stream that is 46% sub-minute touches
                # whose direction is definitional.
                interval=getattr(level, "interval", ""),
                # And how long it actually took, which is what the scores are
                # cut by. Known only now, which is why it cannot band training.
                seconds=float(touch.resolved) - float(touch.started),
            )
        except Exception as exc:  # measurement must not stop the record
            log.debug("structures: bench skipped a touch: %s", exc)

    async def record_outcomes(self) -> int:
        """Attach what happened to the decision that predicted it.

        A decision without its result is half a training example, and until
        this ran the journal held only halves - decisions with no outcomes and
        no parent links at all. The touch resolving *is* the label: which way
        price went from the level, how far, and whether a break it made was
        taken back.

        Every resolution is also published to `structures.resolutions`, which
        is the only ground truth on the bus. Anything acting on `signals` - the
        trader, in particular - is otherwise blind to whether the calls it
        acted on were right, and a threshold that should move with outcomes
        cannot move without seeing them.
        """
        written = 0
        for level, touch in self.engine.drain_resolved():
            # Announced before the journal lookup, and unconditionally. A
            # resolution is a fact about the market, not a label on one of our
            # decisions - most touches were never predicted by anything, and
            # those are exactly the ones a consumer learning what levels do
            # needs. Gating this on `ref` would publish only the outcomes we
            # had already called, which is the sample that teaches least.
            await self.bus.publish(
                RESOLUTIONS,
                {
                    "feed": level.feed,
                    "interval": level.interval,
                    "level": round(touch.level_price, 8),
                    "outcome": str(touch.outcome),
                    "direction": "up" if touch.push_vol > 0 else "down",
                    "push_vol": round(touch.push_vol, 6),
                    "excursion_vol": round(touch.excursion_vol, 6),
                    "seconds": round(touch.resolved - touch.started),
                    "started": touch.started,
                    "time": touch.resolved,
                    **{
                        k: round(v, 6)
                        for k, v in touch.features.to_dict().items()
                        if isinstance(v, int | float)
                    },
                },
                source="structures",
            )

            # Keyed on the price recorded *with the touch*, not the level's
            # current one. The Kalman mean moves when the touch is folded in,
            # and it is folded in before this runs - so looking up by
            # `level.price` searches for a key that no longer exists.
            # Every resolution, not only the predicted ones - and before the
            # journal lookup for the same reason the announcement is: most
            # touches were never called by anything, and those are the sample
            # a model learns most from.
            self._benchmark(level, touch)
            # Predict-then-learn, like everything else here: `observe` returns
            # what it said before it was told.
            self.breaks.observe(touch.features, str(touch.outcome))

            ref = self._awaiting.pop((level.feed, round(touch.level_price, 8)), None)
            if ref is None:
                continue  # nothing predicted this; the result is a fact, not a label
            # The hour learns from the same event the journal does. `reject`
            # and `backcheck` are the level holding; `break` and `trap` are
            # price getting through. Chop is neither and is not counted, which
            # is the discipline the rest of the package applies to it.
            # Named `resolved_as`, not `outcome`: `outcome` is the journal
            # function imported at the top of this module, and shadowing it
            # here made the very next call to it a TypeError. Caught by two
            # existing tests within a minute, which is the argument for having
            # them.
            resolved_as = str(touch.outcome)
            if resolved_as in ("reject", "backcheck", "break", "trap"):
                self.clock.record(
                    level.feed, touch.resolved, held=resolved_as in ("reject", "backcheck")
                )

            went = "up" if touch.push_vol > 0 else "down"
            recorded = await outcome(
                self.journal,
                ref,
                f"{level.feed} {level.price:.5g}: {touch.outcome}, {went} "
                f"{abs(touch.push_vol):.2f}v",
                rationale=(
                    f"Resolved {touch.outcome} {touch.resolved - touch.started:.0f}s after "
                    f"first contact, pushing {touch.push_vol:+.2f} volatility units"
                ),
                actor="structures",
                context={
                    "outcome": str(touch.outcome),
                    "push_vol": round(touch.push_vol, 4),
                    "excursion_vol": round(touch.excursion_vol, 4),
                    # Not the same quantity, and the difference cost a day.
                    # `excursion_vol` is only assigned once price is a full
                    # unit past the level, so it holds zeros and values above
                    # one with nothing between, and every replay that stopped
                    # a trade on it modelled a 1.0v stop whatever width it was
                    # asked for. `adverse_vol` has no threshold.
                    "adverse_vol": round(touch.adverse_vol, 4),
                    "seconds": round(touch.resolved - touch.started),
                    "level": round(level.price, 8),
                    "interval": level.interval,
                    # Which formation drew this level. Running pip, run and
                    # origin together is pointless without it: the argument for
                    # merging them is that the journal says which price gets
                    # respected, and it cannot say that if the record does not
                    # carry which pass found it.
                    #
                    # On the **outcome**, not the signal's features. Features
                    # are `dict[str, float]` and `Signal.to_dict` rounds every
                    # value, so a string there raises `TypeError: type str
                    # doesn't define __round__` - which stopped the structures
                    # service in production for four minutes.
                    #
                    # `drawn_by` rather than `origin`, which in this namespace
                    # already means the impulse origin.
                    "drawn_by": level.origin,
                    # Which instrument this happened on. The resolution had the
                    # timeframe and not the instrument, so a scoring pass could
                    # group by one and not the other - and pooling gold with
                    # EURUSD describes neither.
                    "feed": level.feed,
                    # What was believed when the touch opened, carried so the
                    # belief and the outcome can be joined. Only published
                    # calls ever recorded an edge, and publication requires
                    # passing the threshold, so the below-threshold half of the
                    # distribution has never been observable. See `Touch.edge`.
                    "edge": round(touch.edge, 4),
                    "probability_up": round(touch.probability_up, 4),
                    "base_rate_up": round(touch.base_rate_up, 4),
                    "actionable": touch.actionable,
                    **touch.features.to_dict(),
                },
            )
            written += bool(recorded)
        self.outcomes += written
        return written

    # -------------------------------------------------------------- running

    async def handle(self, message: Message) -> list[Signal]:
        """One bus message in, zero or more findings out."""
        if message.topic == QUOTES:
            signals = self.detector.observe(message.payload)
            calls = self.engine.observe_quote(message.payload)
            await self._watch_calls(calls)
            return signals + self._level_calls(calls)
        if message.topic == BARS:
            calls = self.engine.observe_bar(message.payload)
            await self._watch_calls(calls)
            signals = self._level_calls(calls)
            feed = str(message.payload.get("feed") or "")
            interval = str(message.payload.get("interval") or "")
            if feed and interval:
                # The one time-of-day effect the literature actually supports.
                # Taken from the volatility estimate rather than recomputed, so
                # the hour is described in the same units as everything else.
                unit = self.engine.vol.of(feed, interval)
                when = message.payload.get("time")
                if unit.warm and isinstance(when, int | float) and when:
                    self.clock.observe_vol(feed, float(when), unit.bps)

                volume = message.payload.get("volume")
                if isinstance(volume, int | float) and volume > 0:
                    self._busy[(feed, interval)] = self.activity.update(
                        feed, interval, float(volume)
                    )

            seen = self.bars.observe(message.payload)
            if seen is not None:
                feed, mid, interval = seen
                found = self.drift.observe(feed, mid, message.time, interval)
                if found is not None:
                    # The tide changed: every level for this instrument learned
                    # its behaviour in the old regime, so discount it - by how
                    # big this change was against past ones, not by a constant.
                    self.engine.regime_changed(feed, found.features.get("severity_pct", 0.5))
                    signals.append(found)
            return signals
        if message.topic == MACRO:
            return await self._read_macro()
        return []

    async def _read_macro(self) -> list[Signal]:
        """Re-read the policy series, and speak if a stance turned.

        Both halves of the consumption at once, deliberately. The features and
        the model read the same state, so splitting them would mean two reads
        of the same file and two chances for them to disagree about what the
        rate differential is.
        """
        if not self.settings.macro:
            return []
        since = self._macro_since or since_default()
        rows = await asyncio.to_thread(stored, self.settings.news_db, since=since)
        if not rows:
            return []
        taken = self.macro.take(rows)
        # From the rows rather than from the clock: a series two months behind
        # would otherwise push the watermark past its own newest observation
        # and the next read would ask for a window it has nothing in.
        self._macro_since = max(row.time for row in rows)
        found = self.macro.calls(sorted(self.engine.feeds()))
        if taken or found:
            log.info(
                "structures: policy - %d new readings, %d stance changes",
                taken,
                len(found),
            )
        return found

    def _level_calls(self, calls: Sequence[object]) -> list[Signal]:
        """Turn level calls into signals, dropping the ones with no edge.

        `actionable` is the filter, and it is strict on purpose: it wants
        enough evidence, enough separation from the base rate, and enough size.
        A call that merely restates the base rate is not information, however
        confident the number looks.
        """
        worth = [call for call in calls if call.inference.actionable]
        if not worth:
            return []

        best: dict[object, tuple[float, Signal]] = {}
        loners: list[Signal] = []
        # Grouped once per instrument per batch, not once per call: a busy
        # instrument produces dozens of calls in one batch and regrouping for
        # each was doing the same work dozens of times over the same levels.
        grouped: dict[str, list] = {}
        for call in worth:
            vol = self.engine.vol.of(call.feed, call.interval)
            busy = self._busy.get((call.feed, call.interval), 1.0)
            # Fold the reading in and take the label back. Done here rather
            # than inside `to_signal` because the classifier is one model
            # across the whole book - a Call has no business holding it, and
            # per-call state would make the partition per-instrument, which is
            # the opposite of what the scale-free features are for.
            market = self.engine.regimes.observe(
                {
                    "vol_stretch": vol.stretch,
                    "regime": vol.regime,
                    "activity": busy,
                    "hour_vol_share": (
                        self.clock.volatility(call.feed, call.time)[1] if self.clock else 1.0
                    ),
                    "forecast_ratio": vol.forecast_ratio,
                    "sweep_rate": 0.0,
                }
            )
            signal = call.to_signal(
                vol,
                self.clock,
                self.engine.levels(call.feed, call.interval),
                busy,
                market,
            )
            # How many formations agree on this price, as a number.
            #
            # `Level.origin` has always carried the passes that drew it -
            # "pip+run+origin" - and `agree()` has always maintained it through
            # a merge. Nothing ever counted it, so "does a level two methods
            # found behave better than a level one method found" could not be
            # asked, of 969 recorded outcomes or of any others.
            #
            # A feature and not a gate, deliberately and in that order: it
            # lands in the journal beside the outcome, and the outcome
            # machinery gets to say whether agreement is worth anything before
            # anything is refused for lacking it.
            extra = {"drawn_by_n": float(len(_passes(call.level)))}
            # P(this level gives way), from the arrival force and the depth of
            # the touch. Silent until it has 200 resolutions behind it, and
            # `None` rather than 0.5 while cold - "no opinion" and "an even
            # chance" are different claims.
            extra.update(self.breaks.reading(getattr(call, "features", None) or {}))
            # Policy folded on here rather than inside `to_signal`, for the
            # same reason the regime label is: it is one model across the whole
            # book and a Call has no business holding it. Empty until the news
            # service has collected something, so this is a no-op on a
            # deployment without one rather than a missing key downstream.
            extra.update(self.macro.features(call.feed))
            signal = replace(signal, features={**signal.features, **extra})
            if call.feed not in grouped:
                grouped[call.feed] = self._zones(call.feed)
            zone = self._zone_for(grouped[call.feed], call.level)
            if zone is None:
                loners.append(signal)
                continue
            signal = replace(signal, confluence=zone.timeframes)
            # And onto the touch, so the resolution carries it too. It was on
            # the signal and not on the outcome, so "does agreement across
            # timeframes predict what happens" could only be asked of the two
            # dozen touches that were traded - where it is noise.
            self.engine.tracker.note_confluence(call.feed, call.level.price, zone.timeframes)
            # One zone, one message. Three timeframes agreeing on a price is one
            # structure seen three times, and sending it three times says the
            # opposite of what it means - it reads as three findings when it is
            # really one with more behind it. The strongest call speaks for the
            # zone, and the timeframes it beat are named in the message.
            key = id(zone)
            if key not in best or abs(signal.score) > best[key][0]:
                best[key] = (abs(signal.score), signal)
        return loners + [signal for _score, signal in best.values()]

    def _zones(self, feed: str) -> list[object]:
        """Confluence zones for one instrument, rebuilt once per batch.

        Not cached *across* batches, and that is the deliberate half. Levels
        move under the Kalman filter and are pruned between batches, so a zone
        held longer than a batch would name timeframes that had since stopped
        agreeing - staleness that reads as confidence, which is the worst kind.
        Within a batch nothing moves, so grouping once is both correct and
        cheap: a few dozen levels through one pass of overlap grouping.
        """
        return cf.combine(
            self.engine.levels(feed),
            self.engine.reference(feed),
            volatility=lambda level: self.engine.vol.of(feed, level.interval),
        )

    def _zone_for(self, zones: Sequence[object], level: object) -> object | None:
        """The zone this level belongs to, if any timeframe agrees with it."""
        for zone in zones:
            if len(zone.members) > 1 and any(member is level for member in zone.members):
                return zone
        return None

    async def _watch_calls(self, calls: Sequence[object]) -> None:
        """Record every level call, acted on or not, so the result can be paired.

        Only `actionable` calls become signals - but a dataset containing only
        the calls we acted on is the worst possible sample to learn from. It
        cannot say when holding off was right, because holding off is never in
        it. Non-actionable calls are journalled as observations instead: same
        features, same outcome attached later, no alert.
        """
        for call in calls:
            if call.inference.actionable:
                continue  # `emit` records these, with the alert
            ref = await observe(
                self.journal,
                f"{call.feed} at {call.level.price:.5g}: not worth acting on",
                rationale=str(call.inference),
                actor="structures",
                context={
                    "shape": "level",
                    "level": call.level.price,
                    "interval": call.interval,
                    **call.inference.to_dict(),
                },
                tags=(call.feed, call.interval, "level"),
            )
            if ref:
                self._remember(call.feed, call.level.price, ref)

    async def run(
        self,
        *,
        messages: int | None = None,
        on_signal: Callable[[Signal], None] | None = None,
    ) -> int:
        """Consume until the bus closes, or for `messages` messages."""
        seen = 0
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=10_000)

        # Read once before consuming anything, rather than waiting for the
        # first `MACRO` notice. FRED is a slow source and its series move once
        # a day at fastest, so a restart would otherwise publish level calls
        # with no policy on them for however long the next poll is away - with
        # four hundred days of it already sitting in the store.
        #
        # **And emit what it finds.** This discarded the return value, which
        # was worse than not calling it: `calls` records the stance it just
        # announced, so seven stance changes were computed, marked as already
        # published, and dropped - and the feeds they were about then stayed
        # silent until they flipped again. Nothing reached the journal, so the
        # expensive half of the FRED work looked like a model that never fires.
        opening = await self._read_macro()
        if opening:
            await self.emit(opening)

        async def read(topic: str) -> None:
            with contextlib.suppress(asyncio.CancelledError):
                async for message in self.bus.subscribe(topic, group=self.group):
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(message)

        async with asyncio.TaskGroup() as tasks:
            readers = [tasks.create_task(read(topic)) for topic in TOPICS]
            try:
                while messages is None or seen < messages:
                    message = await queue.get()
                    seen += 1
                    signals = await self.handle(message)
                    if signals:
                        await self.emit(signals)
                        for signal in signals:
                            log.info("structures: %s", signal)
                            if on_signal is not None:
                                on_signal(signal)
                    # Every message, because a resolution that is not drained
                    # promptly is one the engine is holding for no reason.
                    await self.record_outcomes()
                    if time.monotonic() - self._saved >= self.settings.save_seconds:
                        self.save()
            finally:
                self.save()
                for reader in readers:
                    reader.cancel()
        return seen


async def watch(
    bus: Bus,
    *,
    settings: Settings | None = None,
    group: str = "structures",
    journal: Journal | None = None,
    messages: int | None = None,
    on_signal: Callable[[Signal], None] | None = None,
) -> int:
    """Run the online layer over the bus. The everyday entry point."""
    watcher = Watcher(bus, settings=settings, group=group, journal=journal)
    # Restore first, then warm only if the restore left us with no levels.
    # Warming over a populated engine would count every stored bar twice;
    # skipping it because a restore succeeded leaves an empty engine empty.
    watcher.load()
    if watcher.cold:
        watcher.warm()
    else:
        # And the feeds added since the last cold start, which `cold` cannot
        # see: it asks whether the engine holds *any* levels, so eleven new
        # instruments with 2,700 stored bars each were left to learn from the
        # bus one bar at a time.
        watcher.warm_new()
    return await watcher.run(messages=messages, on_signal=on_signal)
