"""Transitions on the dispersion reading, and the line that explains one.

**Why a second topic and not a field on the reading.** Production runs 207
armed feed-intervals at 1m, so a reading per bar is twelve thousand messages an
hour - fine for a consumer that wants the latest value per feed, useless for
one deciding what to look at. This fires on a *change* of state and then stays
quiet for `signal_quiet_hours`.

**This did not survive the Nautilus port, and nothing said so.** The mechanism
lived on `service.Watcher`, which retired with the bus; `STATESPACE_SIGNALS`,
`STATESPACE_SIGNAL_SURPRISE`, `STATESPACE_SIGNAL_WIDTH` and
`STATESPACE_SIGNAL_QUIET_HOURS` stayed live in `config.Settings`, read by
nothing - four settings an operator could set to no effect. The state and the
wording moved here, where `StatespaceActor` can own them, rather than moving
with the retired file.

Pure, and not an `Actor` method, for the reason `actor.alert_for` is pure:
`Actor.log` and `Actor.msgbus` are read-only on the Cython base, so a method
that both decides and publishes can only be tested with a bus.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Notices", "notice_for"]


@dataclass(slots=True)
class Notices:
    """Which bars are a change of state, and which have been said recently."""

    #: key -> exponentially weighted mean of the log band width, so a widening
    #: is judged against this feed-interval's own history rather than a
    #: constant that would mean something different on every instrument.
    _widths: dict[tuple[str, str], float] = field(default_factory=dict, repr=False)
    #: (key, kind) -> when it was last announced, for the quiet period.
    _said: dict[tuple[tuple[str, str], str], float] = field(default_factory=dict, repr=False)
    #: How many were published, since the engine cannot see them.
    sent: int = 0

    def of(self, readout: Any, settings: Any) -> tuple[str, float] | None:
        """The kind of change this bar represents, and how big, or None.

        Ordered by what a consumer should act on first: a spread that cannot
        be trusted beats a surprise, and a surprise beats a change of width.
        """
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
            # **`surprise`, not `break`.** "Break" is a level word to anybody
            # who trades, and this is a standardised innovation on log
            # variance - the quantity's own field name says what it is.
            return ("surprise", readout.surprise)
        if width is not None and was is not None:
            moved = width - was
            if moved >= settings.signal_width:
                return ("widening", moved)
            if moved <= -settings.signal_width:
                return ("quieting", moved)
        return None

    def quiet(self, readout: Any, kind: str, settings: Any, *, at: float | None = None) -> bool:
        """Whether this kind is still inside its quiet period for this feed."""
        now = time.time() if at is None else float(at)
        key = ((readout.feed, readout.interval), kind)
        last = self._said.get(key)
        if last is not None and now - last < settings.signal_quiet_hours * 3600.0:
            return True
        self._said[key] = now
        return False


def notice_for(payload: dict[str, Any], readout: Any, kind: str, score: float) -> dict[str, Any]:
    """What a transition puts on the bus.

    A superset of `actor.payload_for`, plus the three things a notice needs
    that a
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
    # The reading's own payload, passed in rather than rebuilt: a notice that
    # disagreed with the reading published on the same bar would be two
    # answers to one question.
    out = dict(payload)
    out["kind"] = kind
    out["score"] = round(float(score), 4)
    out["detail"] = _detail(readout, kind, score)
    # **`shape` is what the notification filter routes on**, and a payload
    # without one is keyed by its *source* instead - so a channel narrowed with
    # `NOTIFY_SHAPES=level,drift` would drop every notice from this service
    # silently, which `agents.publish` calls the worst way for an analysis to
    # fail. The kind is the shape, so a channel can ask for breaks and not
    # quietings.
    out["shape"] = kind
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


def _detail(readout: Any, kind: str, score: float) -> str:
    """One line in plain words, for a reader who does not know what a sigma is.

    **The payload keeps every technical field; this does not.** `agents`
    composes the alert body with a model, and `notifications` sends it to a
    phone - so this is the line that survives if the analysis says nothing
    useful, and it is read by whoever happens to be holding the phone. Numbers
    appear as multiples and percentages because those are read correctly
    without training; sigmas, z-scores, log widths and "half-bands" are not.

    Two namings earlier this evening would have been read as price claims by
    anyone sensible - a field called `side` and a kind called `break`. The same
    care applies here, so every line says **move size** or **swings** and never
    implies a direction for the price.
    """
    size = abs(score)
    if kind == "surprise":
        if size >= 6.0:
            how = "an extreme move"
        elif size >= 4.0:
            how = "a far bigger move than usual"
        else:
            how = "a much bigger move than usual"
        if score < 0:
            how = "a far quieter bar than usual" if size >= 4.0 else "a much quieter bar than usual"
        parts = [f"{how} just printed"]
    elif kind in ("widening", "quieting"):
        times = math.exp(abs(score))
        if kind == "widening":
            parts = [f"swings are about {times:.1f}x wider than they have been"]
        else:
            parts = [
                f"swings are about {100.0 * (1.0 - 1.0 / times):.0f}% narrower than they have been"
            ]
    elif kind == "saturated":
        # **And nothing else.** Quoting a probability in the same breath as
        # "these readings are unreliable" invites the reader to use the
        # probability, which is the one thing this line exists to prevent.
        return "these readings are unreliable right now - treat the range as a guess"
    else:  # pragma: no cover - a kind without a line is still readable
        parts = [f"{kind} {score:+.2f}"]

    if readout.stretch:
        stretch = readout.stretch
        if abs(stretch) < 0.5:
            parts.append("about average for the session so far")
        elif stretch > 0:
            parts.append("busier than the rest of the session")
        else:
            parts.append("calmer than the rest of the session")
    if readout.variance_up:
        parts.append(f"{100.0 * readout.variance_up:.0f}% chance the next bar is bigger again")
    return "; ".join(parts)
