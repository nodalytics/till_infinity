"""Regime change: has the market itself changed, not just this reading?

The anomaly detector answers "is this tick unusual". This answers a different
question no per-tick score can: "has what counts as usual moved?" They need
separating because the responses are opposite. An anomaly is something to look
at. Drift invalidates every threshold learned before it.

`ADWIN` is the right tool because it needs no window length chosen in advance.
It maintains a window and cuts it wherever the two halves stop looking like the
same distribution, so the horizon is discovered rather than configured - which
matters when the horizon is exactly what changed.

## One timeframe is not enough

A single detector on 5m bars fires on a busy hour. That was tolerable when
drift was only reported; it is not now, because a regime change **discounts
every level's accumulated history** for that instrument. A spurious drift throws
away real evidence, so the cost of a false positive went up sharply and the
detector had to get more conservative to match.

So a detector runs per timeframe and a change is only declared when they
**agree**: either a slow timeframe fires - a 4h regime change is a regime
change, it is not noise - or two fast ones fire close together. One fast
timeframe on its own is a busy hour and is deliberately ignored.

## How much, not just whether

ADWIN answers *whether*. On its own that is not enough, because a confirmed
change discounts every level's accumulated history - and a marginal change and
a violent one would get the same flat discount, from a constant somebody picked.

So the magnitude is measured and **calibrated against past magnitudes**, the
same trick that rescued the anomaly detector from HalfSpaceTrees' uncalibrated
scores. Severity is the log-ratio of the mean move before and after the cut:

    severity = |log(after / before)|

which is scale-free, so a doubling counts the same on gold and on BTC. Its
running quantile turns it into a number in [0, 1] that means "bigger than this
fraction of the changes we have seen", and that grades the decay:

    decay = 1 - p * (1 - REGIME_DECAY)

A 99th-percentile change nearly resets a level's history; a 55th-percentile one
barely touches it. Nobody picks a constant, and the scale adapts as the market
does.

## A second detector, watching and deciding nothing

`ADWIN` tests for a change in the **mean**, via a Hoeffding bound on two halves
of its window. That is the right test for "moves got bigger" and it is blind to
a change that leaves the mean where it was - a distribution that widens
symmetrically, which on this desk is not an exotic case but the ordinary one.

`KSWIN` applies a Kolmogorov-Smirnov test to a recent window against an older
one and asks whether they came from the same distribution **at all**, assuming
nothing about its shape. Where ADWIN cannot see a change with no mean shift,
this can.

It is deliberately wired to **decide nothing**. The paragraph above says why: a
spurious drift discounts every level's accumulated history, so the cost of a
false positive here is real evidence thrown away, and that is what made ADWIN
conservative once its output was consumed. A second detector inherits that cost
in full. So KSWIN counts - how often it fires, how often ADWIN fires, and how
often they agree - and the record decides whether it is worth listening to
before anything listens.

What is watched is the **consensus** price, not one venue's. A single venue's
series mixes market moves with that venue's own quirks, which is what having
six venues exists to cancel.
"""

from __future__ import annotations

import math
import time

from river import drift as river_drift

from ...logging import get_logger
from ..drawing.confluence import rank
from ..models import Shape, Signal

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

#: Past change magnitudes kept for calibration. A change is only "big" relative
#: to other changes, so this is the sample that makes the word mean anything.
SEVERITY_WINDOW = 200

#: Severities below this many observations are not calibrated yet, so a change
#: is treated as middling rather than assigned a percentile from three samples.
SEVERITY_WARMUP = 8

#: KSWIN's significance. River's default is 0.005; this is stricter because the
#: stream is one reading per quote and a test run that often at 0.005 fires on
#: its own error rate several times an hour.
KS_ALPHA = 0.0005

#: The recent sample KSWIN tests against its window. Both are River's defaults,
#: named here because a window is the one thing ADWIN does not need chosen and
#: this detector does - which is itself a cost worth seeing.
KS_WINDOW = 100
KS_STAT = 30


class Drift:
    """Regime detection per (instrument, timeframe), reported on agreement."""

    def __init__(self, *, delta: float = 0.002, quorum: int = FAST_QUORUM) -> None:
        self.delta = delta
        self.quorum = quorum
        self._detectors: dict[tuple[str, str], river_drift.ADWIN] = {}
        #: The second opinion, which decides nothing. See the module docstring.
        self._shape: dict[tuple[str, str], river_drift.KSWIN] = {}
        #: How the two compare, so the record can say whether the second one
        #: is worth listening to before anything listens.
        self._agreement: dict[str, int] = {
            "adwin": 0,
            "kswin": 0,
            "both": 0,
            "kswin_alone": 0,
        }
        self._last: dict[tuple[str, str], float] = {}
        self._fired: dict[tuple[str, str], float] = {}
        self._announced: dict[str, float] = {}
        self._seen: dict[tuple[str, str], int] = {}
        self._before: dict[tuple[str, str], float] = {}
        #: Past severities, so "how big" can be answered relative to something.
        self._severities: list[float] = []

    def _detector(self, key: tuple[str, str]) -> river_drift.ADWIN:
        found = self._detectors.get(key)
        if found is None:
            found = self._detectors[key] = river_drift.ADWIN(delta=self.delta)
        return found

    def _shaped(self, key: tuple[str, str]) -> river_drift.KSWIN:
        found = self._shape.get(key)
        if found is None:
            found = self._shape[key] = river_drift.KSWIN(
                alpha=KS_ALPHA, window_size=KS_WINDOW, stat_size=KS_STAT
            )
        return found

    def _counts(self) -> dict[str, int]:
        """The agreement counters, created if this instance predates them.

        **`Drift` is persisted and is not a `Restorable` dataclass**, so nothing
        fills in a field a save was written before. `_agreement` was added with
        the KSWIN work; every instance restored from an older save came back
        without it, and the first time ADWIN actually fired the attribute
        access threw.

        That threw inside the structures consumer, which had no per-message
        guard, so the service stopped and the container stayed `healthy` -
        eleven hours of it on 2026-09-08, with 132,807 bus warnings burying the
        one line that named the fault. Both of those are fixed too; this is the
        fault itself.

        Asked for rather than assumed, which is the same guard `_remember_origins`
        needed for `_origins` and `_note_change` for `_changes`.
        """
        found = getattr(self, "_agreement", None)
        if not isinstance(found, dict):
            found = self._agreement = {}
        for name in ("adwin", "kswin", "both", "kswin_alone"):
            found.setdefault(name, 0)
        return found

    def watching(self) -> dict[str, int]:
        """How the two detectors have compared so far.

        Read rather than acted on. `kswin_alone` is the number that decides
        whether the second detector is worth having: if it is near zero, KSWIN
        never sees anything ADWIN missed and costs a window size for nothing.
        """
        return dict(self._counts())

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
        before = float(detector.estimation)
        detector.update(change)
        self._seen[key] = self._seen.get(key, 0) + 1

        # The second opinion, scored and otherwise ignored. Wrapped because a
        # detector that decides nothing must not be able to stop one that does.
        shaped = False
        try:
            shape = self._shaped(key)
            shape.update(change)
            shaped = bool(shape.drift_detected)
        except Exception as exc:  # a second opinion is not worth an outage
            log.debug("drift: KSWIN failed on %s %s: %s", feed, interval, exc)
        counts = self._counts()
        if shaped:
            counts["kswin"] += 1
        if detector.drift_detected:
            counts["adwin"] += 1
        if shaped and detector.drift_detected:
            counts["both"] += 1
        elif shaped:
            counts["kswin_alone"] += 1

        if not detector.drift_detected:
            self._before[key] = before
            return None

        self._fired[key] = when
        severity = self.severity(self._before.get(key, before), float(detector.estimation))
        self._before[key] = float(detector.estimation)
        agreed = self.agreement(feed, when)
        if not agreed:
            log.debug("drift: %s %s fired alone, waiting for agreement", feed, interval)
            return None

        # One change per instrument per window, however many timeframes agree.
        if when - self._announced.get(feed, 0.0) < AGREEMENT_WINDOW:
            return None
        self._announced[feed] = when

        graded = self.percentile(severity)
        self._remember(severity)
        log.info(
            "drift: %s regime changed, confirmed by %s, severity %.0f%%",
            feed,
            "+".join(agreed),
            graded * 100,
        )
        return Signal(
            shape=Shape.DRIFT,
            feed=feed,
            venue="consensus",
            score=1.0,
            detail=(
                f"volatility regime changed on {'+'.join(agreed)} - typical move now "
                f"{detector.estimation:.3f}bps across {detector.width} readings"
            ),
            features={
                "mean_move_bps": float(detector.estimation),
                "window": float(detector.width),
                "timeframes": float(len(agreed)),
                "severity": severity,
                # In [0, 1]: how big this change is against past changes. The
                # consumer grades its response by this rather than by a flag.
                "severity_pct": graded,
            },
            interval=interval,
            time=when,
        )

    @staticmethod
    def severity(before: float, after: float) -> float:
        """How big the change was, scale-free.

        The log-ratio of the mean move either side of the cut, so a doubling
        counts the same on gold as on BTC - and a halving counts the same as a
        doubling, because a market going quiet is as much a regime change as one
        going wild.
        """
        if before <= 0 or after <= 0:
            return 0.0
        return abs(math.log(after / before))

    def percentile(self, severity: float) -> float:
        """Where this severity sits among past ones, in [0, 1].

        Middling until there are enough past changes to place it. Assigning a
        percentile from three samples would be a confident number derived from
        nothing, which is worse than admitting there is no calibration yet.
        """
        if len(self._severities) < SEVERITY_WARMUP:
            return 0.5
        below = sum(1 for value in self._severities if value < severity)
        return below / len(self._severities)

    def _remember(self, severity: float) -> None:
        self._severities.append(severity)
        if len(self._severities) > SEVERITY_WINDOW:
            del self._severities[: len(self._severities) - SEVERITY_WINDOW]

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
