"""Regime change: has the market itself changed, not just this reading?

The anomaly detector answers "is this tick unusual". This answers a different
question that no per-tick score can: "has what counts as usual moved?" They
need separating because the responses are opposite. An anomaly is something to
look at. Drift is a reason to distrust every threshold that was learned before
it — and, more importantly, a reason to say so out loud rather than quietly
carrying on with stale expectations.

`ADWIN` is the right tool because it needs no window length chosen in advance.
It maintains a window and cuts it wherever the two halves stop looking like the
same distribution, so the answer to "over what horizon" is discovered rather
than configured — which matters when the horizon is exactly what changed.

What is watched is the **consensus** return, not one venue's. A single venue's
series mixes market moves with that venue's own quirks, and the point of having
six is that the median cancels them.
"""

from __future__ import annotations

import time

from river import drift as river_drift

from ..logging import get_logger
from .models import Shape, Signal

log = get_logger(__name__)

#: Returns below this are rounding, and feeding them to ADWIN teaches it that
#: the market is a flat line punctuated by noise.
MIN_RETURN_BPS = 1e-6


class Drift:
    """One drift detector per instrument, over cross-venue consensus returns."""

    def __init__(self, *, delta: float = 0.002) -> None:
        self.delta = delta
        self._detectors: dict[str, river_drift.ADWIN] = {}
        self._last: dict[str, float] = {}
        self._seen: dict[str, int] = {}

    def _detector(self, feed: str) -> river_drift.ADWIN:
        found = self._detectors.get(feed)
        if found is None:
            found = self._detectors[feed] = river_drift.ADWIN(delta=self.delta)
        return found

    def observe(self, feed: str, mid: float, when: float | None = None) -> Signal | None:
        """Feed one consensus mid. Returns a signal only when the regime breaks."""
        when = time.time() if when is None else when
        previous = self._last.get(feed)
        self._last[feed] = mid
        if previous is None or not previous:
            return None

        # Absolute return: ADWIN watches the *size* of moves, so a market that
        # starts trending and one that starts chopping both register. Signed
        # returns average to zero either way and would hide both.
        change = abs(mid - previous) / previous * 10_000
        if change < MIN_RETURN_BPS:
            return None

        detector = self._detector(feed)
        detector.update(change)
        self._seen[feed] = self._seen.get(feed, 0) + 1
        if not detector.drift_detected:
            return None

        log.info("drift: %s regime changed, mean move now %.3fbps", feed, detector.estimation)
        return Signal(
            shape=Shape.DRIFT,
            feed=feed,
            venue="consensus",
            score=1.0,
            detail=(
                f"volatility regime changed — typical move is now "
                f"{detector.estimation:.3f}bps across {detector.width} readings"
            ),
            features={"mean_move_bps": float(detector.estimation), "window": float(detector.width)},
            time=when,
        )

    def seen(self) -> dict[str, int]:
        return dict(self._seen)
