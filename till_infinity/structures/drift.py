"""Regime change: has the market itself changed, not just this reading?

The anomaly detector answers "is this tick unusual". This answers a different
question no per-tick score can: "has what counts as usual moved?" They need
separating because the responses are opposite. An anomaly is something to look
at. Drift invalidates every threshold learned before it.

`ADWIN` is the right tool because it needs no window length chosen in advance.
It maintains a window and cuts it wherever the two halves stop looking like the
same distribution, so the horizon is discovered rather than configured — which
matters when the horizon is exactly what changed.

## One timeframe is not enough

A single detector on 5m bars fires on a busy hour. That was tolerable when
drift was only reported; it is not now, because a regime change **discounts
every level's accumulated history** for that instrument. A spurious drift throws
away real evidence, so the cost of a false positive went up sharply and the
detector had to get more conservative to match.

So a detector runs per timeframe and a change is only declared when they
**agree**: either a slow timeframe fires — a 4h regime change is a regime
change, it is not noise — or two fast ones fire close together. One fast
timeframe on its own is a busy hour and is deliberately ignored.

What is watched is the **consensus** price, not one venue's. A single venue's
series mixes market moves with that venue's own quirks, which is what having
six venues exists to cancel.
"""

from __future__ import annotations

import time

from river import drift as river_drift

from ..logging import get_logger
from .confluence import rank
from .models import Shape, Signal

log = get_logger(__name__)

#: Returns below this are rounding, and feeding them to ADWIN teaches it that
#: the market is a flat line punctuated by noise.
MIN_RETURN_BPS = 1e-6

#: A timeframe at or above this rank is slow enough to be believed alone.
SLOW_ENOUGH = "1h"

#: Fast timeframes firing within this long of each other count as agreeing.
AGREEMENT_WINDOW = 3_600.0

#: How many fast timeframes must agree when no slow one has fired.
FAST_QUORUM = 2


class Drift:
    """Regime detection per (instrument, timeframe), reported on agreement."""

    def __init__(self, *, delta: float = 0.002, quorum: int = FAST_QUORUM) -> None:
        self.delta = delta
        self.quorum = quorum
        self._detectors: dict[tuple[str, str], river_drift.ADWIN] = {}
        self._last: dict[tuple[str, str], float] = {}
        self._fired: dict[tuple[str, str], float] = {}
        self._announced: dict[str, float] = {}
        self._seen: dict[tuple[str, str], int] = {}

    def _detector(self, key: tuple[str, str]) -> river_drift.ADWIN:
        found = self._detectors.get(key)
        if found is None:
            found = self._detectors[key] = river_drift.ADWIN(delta=self.delta)
        return found

    def observe(
        self, feed: str, mid: float, when: float | None = None, interval: str = "5m"
    ) -> Signal | None:
        """Feed one consensus price. Returns a signal only on a *confirmed* change."""
        when = time.time() if when is None else when
        key = (feed, interval)
        previous = self._last.get(key)
        self._last[key] = mid
        if previous is None or not previous:
            return None

        # Absolute return: ADWIN watches the *size* of moves, so a market that
        # starts trending and one that starts chopping both register. Signed
        # returns average to zero either way and would hide both.
        change = abs(mid - previous) / previous * 10_000
        if change < MIN_RETURN_BPS:
            return None

        detector = self._detector(key)
        detector.update(change)
        self._seen[key] = self._seen.get(key, 0) + 1
        if not detector.drift_detected:
            return None

        self._fired[key] = when
        agreed = self.agreement(feed, when)
        if not agreed:
            log.debug("drift: %s %s fired alone, waiting for agreement", feed, interval)
            return None

        # One change per instrument per window, however many timeframes agree.
        if when - self._announced.get(feed, 0.0) < AGREEMENT_WINDOW:
            return None
        self._announced[feed] = when

        log.info("drift: %s regime changed, confirmed by %s", feed, "+".join(agreed))
        return Signal(
            shape=Shape.DRIFT,
            feed=feed,
            venue="consensus",
            score=1.0,
            detail=(
                f"volatility regime changed on {'+'.join(agreed)} — typical move now "
                f"{detector.estimation:.3f}bps across {detector.width} readings"
            ),
            features={
                "mean_move_bps": float(detector.estimation),
                "window": float(detector.width),
                "timeframes": float(len(agreed)),
            },
            interval=interval,
            time=when,
        )

    def agreement(self, feed: str, when: float) -> list[str]:
        """Timeframes that have fired recently enough to count, or [].

        A slow timeframe alone is enough. Fast ones need a quorum, because one
        fast timeframe firing is a busy hour rather than a new market.
        """
        recent = [
            interval
            for (this_feed, interval), fired in self._fired.items()
            if this_feed == feed and when - fired <= AGREEMENT_WINDOW
        ]
        if not recent:
            return []
        ordered = sorted(recent, key=rank, reverse=True)
        if any(rank(interval) >= rank(SLOW_ENOUGH) for interval in ordered):
            return ordered
        return ordered if len(ordered) >= self.quorum else []

    def seen(self) -> dict[str, int]:
        """Readings per instrument, summed across timeframes."""
        totals: dict[str, int] = {}
        for (feed, _), count in self._seen.items():
            totals[feed] = totals.get(feed, 0) + count
        return totals

    def pending(self, feed: str, when: float | None = None) -> list[str]:
        """Timeframes that have fired but not yet reached agreement."""
        when = time.time() if when is None else when
        return [
            interval
            for (this_feed, interval), fired in self._fired.items()
            if this_feed == feed and when - fired <= AGREEMENT_WINDOW
        ]
