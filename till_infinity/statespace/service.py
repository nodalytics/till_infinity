"""The always-on loop: bars in, dispersion out.

    prices ──▶ statespace ──▶ statespace.dispersion ──▶ trading, structures

One topic out, and it carries no side. The payload says how wide the next bars
are and how sure of that it is, because that is the half this desk has measured
forecastable - and a consumer that wants a direction has to get it somewhere
else, which is the point rather than a limitation.

## It is plugged in by subscribing, not by being imported

Nothing in production imported this package before it became a service, and
nothing imports it now. A service that other services reach into is the shape
`shared/` exists to end - `structures/codec.py` records `trading` having
imported its persistence layer - so the seam here is the bus: this reads
`prices.bars` and publishes `statespace.dispersion`, and a consumer subscribes.
That is what makes it pluggable: it can be run, not run, or run on its own box,
and the only thing that changes for anyone else is whether the topic has
traffic.

## The bus arrives as an argument, and the topics are named here

`TestVendoredCusum` asserts that this package imports nothing from outside
itself but `shared`, because "isolation is the point: this package is meant to
lift out in one move". `from ..bus import Bus` would break that, and the first
version of this file did.

So `Carrier` is a protocol rather than an import: anything with `publish` and
`subscribe` drives this loop, which is what lets the package be tested without
a bus and run under a different one. The topic names are duplicated here as
constants rather than imported, and the duplication is checked - a test outside
the package asserts `TOPIC == bus.DISPERSION` and `CONSUMES == bus.BARS`, so a
rename in either place fails loudly instead of leaving a service subscribed to
a topic nobody publishes.

## Warm by replay, which is why `armed` lags `tracking`

`Engine.restore` reads counters, not members, so a freshly started service
reports `tracking=0` with a restored bar count. It publishes nothing for a
feed until `warm_bars` bars have arrived, because `Desk._quantiles` returns an
empty band below `facade.LEAST` residuals and a readout whose interval is
missing is worse than no readout. `armed=0` right after a deploy is the normal
reading here for the same reason it is in `structures`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .config import Settings
from .engine import Engine
from .facade import Readout

log = logging.getLogger(__name__)

__all__ = [
    "CONSUMES",
    "NOTICES",
    "TOPIC",
    "Carrier",
    "Watcher",
    "notice_for",
    "payload_for",
    "watch",
]

#: The topic this service reads. Must equal `bus.BARS`; a test asserts it.
CONSUMES = "prices.bars"

#: The topic it publishes. Must equal `bus.DISPERSION`; a test asserts it.
TOPIC = "statespace.dispersion"

#: The transition topic. Must equal `bus.STATESPACE_SIGNALS`; a test asserts it.
#:
#: **Separate from `TOPIC` because of the arithmetic.** Production runs 207
#: armed feed-intervals at 1m, so a reading per bar is twelve thousand messages
#: an hour - fine for a consumer that wants the latest value per feed, useless
#: for one deciding what to look at. This fires on a change of state and then
#: stays quiet for `signal_quiet_hours`.
NOTICES = "statespace.signals"


@runtime_checkable
class Carrier(Protocol):
    """What this loop needs of a bus, and nothing more."""

    async def publish(self, topic: str, payload: dict[str, Any], *, source: str = "") -> int: ...

    def subscribe(self, topic: str, group: str = ...) -> Any: ...


#: Seconds between the log line that says what the service is doing. Quiet by
#: default: one line every ten minutes names the bars folded and the feeds
#: armed, which is enough to tell a stalled service from an idle bus.
REPORT_SECONDS = 600.0


def payload_for(readout: Readout) -> dict[str, object]:
    """What goes on the bus. JSON-safe, and deliberately without a direction.

    `band` is the interval the readout is prepared to state at its measured
    coverage, which is the t-anchored one where it has the residuals for it
    and the assumed one otherwise - `Readout.covering` chooses and says which
    in `source`, so a consumer can refuse an assumed band without having to
    know how the choice is made.
    """
    interval = readout.covering(0.90)
    out: dict[str, object] = {
        "feed": readout.feed,
        "interval": readout.interval,
        "time": float(readout.at),
        # Log variance, which is the space the members were fitted in.
        "log_variance": float(readout.value),
        "spread": float(readout.spread),
        "surprise": float(readout.surprise),
        "family": readout.family,
        "paced": bool(readout.paced),
        "pace_factor": float(readout.pace_factor),
        "seen": int(readout.seen),
        # How `spread` was combined, and whether the loop that scaled it had
        # run out of room. A recorded spread is not comparable across either.
        "spread_rule": str(readout.spread_rule),
        "spread_saturated": bool(readout.spread_saturated),
    }
    if readout.fair_variance:
        # **A fair *volatility*, not a fair price** - this service folds log
        # variance. `stretch` is in half-band units, so 1.0 is the band's own
        # edge and the number is comparable across feeds because that band's
        # coverage is measured. See `anchored.py` for why the weights are
        # precisions rather than volume.
        out["fair_variance"] = round(float(readout.fair_variance), 6)
        out["fair_sd"] = round(float(readout.fair_sd), 6)
        out["stretch"] = round(float(readout.stretch), 4)
    if interval is not None:
        out["band"] = {
            "low": float(interval.low),
            "high": float(interval.high),
            "coverage": float(interval.coverage),
            "source": str(interval.source),
        }
    return out


def notice_for(readout: Readout, kind: str, score: float) -> dict[str, object]:
    """What a transition puts on the bus.

    A superset of `payload_for`, plus the three things a notice needs that a
    reading does not: `kind`, a `score` comparable across feeds, and a `detail`
    line, because `agents._signal` builds its alert text from `detail` and
    keeps the loudest `score` per feed.

    **The side ships with its own significance or not at all.** `side_z` is
    omitted when the drift's standard deviation is unknown rather than
    defaulted, because a zero there would read as certainty. Direction at the
    level is measured closed on this desk - 0.50 across 112,429 rows, 16 of 17
    bias kinds null, 0 of 28 cells profitable after costs - so a consumer that
    reads `side` without `side_z` is acting on a measured nothing.
    """
    out = dict(payload_for(readout))
    out["kind"] = kind
    out["score"] = round(float(score), 4)
    out["detail"] = f"{kind} at {score:+.2f}"
    # Two structural drifts that disagree by construction, and the slope's own
    # realised volatility beside its estimation uncertainty.
    out["drift_free"] = round(float(readout.drift_free), 8)
    out["drift_revert"] = round(float(readout.drift_revert), 8)
    out["rate"] = round(float(readout.rate), 8)
    out["rate_vol"] = round(float(readout.rate_vol), 8)
    if readout.rate_sd > 0:
        out["rate_sd"] = round(float(readout.rate_sd), 8)
        # **`variance_side`, not `side`.** This service folds log variance, so
        # the sign is whether *dispersion* is drifting up - not whether price
        # is. A field called `side` in an alert would be read as the second
        # thing within a day.
        out["variance_side"] = 1 if readout.rate > 0 else -1 if readout.rate < 0 else 0
        out["variance_side_z"] = round(float(readout.rate / readout.rate_sd), 4)
    if readout.variance_up:
        # The discrete chain's independent reading of the same sign. Built to
        # be shown wrong - direction agrees with its predecessor 49.5% of the
        # time against 50% +/- 3.1% - so two methods disagreeing is the
        # expected case and a consumer should see both.
        out["variance_up"] = round(float(readout.variance_up), 4)
    return out


@dataclass(slots=True)
class Watcher:
    """One bus message in, zero or one publish out."""

    engine: Engine
    published: int = 0
    noticed: int = 0
    _last_report: float = field(default=0.0, repr=False)
    #: key -> exponentially weighted mean of the log band width, so a widening
    #: is judged against this feed-interval's own history rather than a
    #: constant that would mean something different on every instrument.
    _widths: dict[tuple[str, str], float] = field(default_factory=dict, repr=False)
    #: (key, kind) -> when it was last announced, for the quiet period.
    _said: dict[tuple[tuple[str, str], str], float] = field(default_factory=dict, repr=False)

    def transition(self, readout: Readout) -> tuple[str, float] | None:
        """The kind of change this bar represents, and how big, or None.

        Ordered by what a consumer should act on first: a spread that cannot
        be trusted beats a break, and a break beats a change of width.
        """
        settings = self.engine.settings
        key = (readout.feed, readout.interval)

        interval = readout.covering(0.90)
        width = None
        if interval is not None and interval.high > interval.low:
            width = math.log(interval.high - interval.low)
        was = self._widths.get(key)
        if width is not None:
            decay = 0.0 if was is None else 1.0 - 1.0 / 64.0
            self._widths[key] = width if was is None else decay * was + (1.0 - decay) * width

        if readout.spread_saturated:
            return ("saturated", 0.0)
        if abs(readout.surprise) >= settings.signal_surprise:
            return ("break", readout.surprise)
        if width is not None and was is not None:
            moved = width - was
            if moved >= settings.signal_width:
                return ("widening", moved)
            if moved <= -settings.signal_width:
                return ("quieting", moved)
        return None

    def quiet(self, readout: Readout, kind: str, *, at: float | None = None) -> bool:
        """Whether this kind is still inside its quiet period for this feed."""
        now = time.time() if at is None else float(at)
        key = ((readout.feed, readout.interval), kind)
        last = self._said.get(key)
        if last is not None and now - last < self.engine.settings.signal_quiet_hours * 3600.0:
            return True
        self._said[key] = now
        return False

    async def handle(self, message: Any, bus: Carrier) -> Readout | None:
        """Fold a bar and publish what came back.

        `message` is anything with `topic` and `payload`, for the reason
        `Carrier` is a protocol: the package does not import our bus.
        """
        if getattr(message, "topic", "") != CONSUMES:
            return None
        readout = self.engine.observe_bar(message.payload)
        if readout is None:
            return None
        if self.engine.settings.publish:
            await bus.publish(TOPIC, payload_for(readout), source="statespace")
            self.published += 1
        if self.engine.settings.signals:
            change = self.transition(readout)
            if change is not None and not self.quiet(readout, change[0], at=readout.at):
                await bus.publish(NOTICES, notice_for(readout, *change), source="statespace")
                self.noticed += 1
        return readout

    def report(self, *, at: float | None = None) -> str:
        """A line, at most every `REPORT_SECONDS`. Empty when it is too soon."""
        now = time.time() if at is None else float(at)
        if now - self._last_report < REPORT_SECONDS:
            return ""
        self._last_report = now
        saturated = self.engine.saturated
        line = (
            f"statespace: {self.engine.progress.folded} bars folded, "
            f"{self.engine.tracking} tracking, {self.engine.armed} armed, "
            f"{self.published} published, {self.noticed} announced"
        )
        if saturated:
            # **The condition that was silent.** A matching loop against its
            # clamp keeps returning numbers, so every member can run out of
            # process noise without one line being out of the ordinary.
            # `adapting-strata.md` found it by looking, measured a spread
            # three times too small at `R = 0.265`, and then found the shipped
            # `R = 0.670` does not reach the clamp - so this line is expected
            # to stay absent, which is the point of having it.
            line += (
                f", {saturated} feed-interval(s) with a member on its lever's stop "
                "- its spread cannot be trusted, see adapting-strata.md"
            )
        return line


async def watch(
    bus: Carrier, settings: Settings | None = None, *, engine: Engine | None = None
) -> None:
    """Consume `prices.bars` until cancelled, saving progress as it goes.

    Cancellation saves. A service that is stopped cleanly and comes back having
    forgotten the last five minutes is a service whose counters cannot be
    trusted to say whether it was running.
    """
    settings = Settings.from_env() if settings is None else settings
    engine = Engine(settings=settings) if engine is None else engine
    engine.restore()
    watcher = Watcher(engine=engine)
    subscription = bus.subscribe(CONSUMES, group="statespace")
    log.info(
        "statespace: watching %s for %s on %s",
        CONSUMES,
        ", ".join(settings.intervals),
        ", ".join(settings.feeds) if settings.feeds else "every feed",
    )
    try:
        async for message in subscription:
            await watcher.handle(message, bus)
            engine.save()
            line = watcher.report()
            if line:
                log.info("%s", line)
    except asyncio.CancelledError:
        raise
    finally:
        with contextlib.suppress(Exception):
            engine.save(force=True)
        log.info(
            "statespace: stopped after %d bars, %d published",
            engine.progress.folded,
            watcher.published,
        )
