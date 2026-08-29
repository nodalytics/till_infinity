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
import statistics
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import replace

from ..bus import ALERTS, BARS, QUOTES, RESOLUTIONS, SIGNALS, Bus, Message
from ..journal import Journal, decide, observe, outcome
from ..logging import get_logger
from . import confluence as cf
from . import store
from .activity import Book as ActivityBook
from .anomaly import Detector
from .config import DRIFT_INTERVALS, Settings
from .drift import Drift
from .engine import Engine
from .models import Shape, Signal
from .sessions import Clock

log = get_logger(__name__)

TOPICS: tuple[str, ...] = (QUOTES, BARS)

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
        log.info("structures: restored models (%s)", self.detector.seen())
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
        try:
            store.save(
                {
                    "detector": self.detector,
                    "drift": self.drift,
                    "engine": self.engine,
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
        return []

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
    return await watcher.run(messages=messages, on_signal=on_signal)
