"""FOCuS: the exact CUSUM likelihood-ratio test, over every changepoint at once.

`context/cusum.py` accumulates deviations against a fixed threshold, which asks
"has the running sum drifted far enough". FOCuS asks the sharper question: **of
all the places a change could have started, what is the best evidence for any
of them**, and it answers it exactly rather than by picking a window.

For a Gaussian change in mean with unit variance, the log likelihood ratio for
a change at `tau`, observed at `n`, is

    (S_n - S_tau)^2 / (2 * (n - tau))

with `S` the cumulative sum. The statistic is the maximum over every `tau`, and
computing it naively costs O(n) per observation - which is why nobody does it
and everybody picks a window instead.

## Why this is written here rather than installed

`changepoint-online` publishes the reference implementation and is **GPLv3**.
This repository is public, carries no licence, and publishes a Docker image -
so taking the package would put copyleft over the combined work and settle a
licensing question by accident. The *algorithm* is published in the literature
and implementing it is not a derivative of somebody's implementation, so it is
written out here instead. Nothing is copied from that package.

## The pruning, and what is actually claimed

The candidates that can ever be the maximum lie on the **lower convex hull** of
the points `(tau, S_tau)`: a `tau` whose partial sum sits above the chord
between two others can never beat both, whatever arrives next, so it is dropped
and never reconsidered. Maintaining the hull is amortised O(1) per observation,
and the maximum is then taken over the hull rather than over history.

What is claimed is **exactness**, not a complexity bound: the statistic returned
equals the brute-force maximum over all `tau`, and `test_focus.py` asserts that
against an O(n^2) reference on every step. The literature's O(log n) result
needs a sharper search over the hull than this does; the hull here is small in
practice and the honest description is "pruned", not "logarithmic".

## One-sided on purpose

`up=True` looks only for an increase in the mean. On this desk the quantity fed
to a change detector is usually an absolute return - a *size* - and "moves got
bigger" and "moves got smaller" are different events with different responses,
so collapsing them into one two-sided alarm throws away the half a reader wants.
Run two instances where both matter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...shared.state import Restorable

#: The statistic is a log likelihood ratio, so a threshold is "how many nats of
#: evidence before this is worth saying". Chosen to be conservative rather than
#: fitted: `drift.py` records that a false alarm discounts real evidence.
THRESHOLD = 12.0


@dataclass(slots=True)
class Focus(Restorable):
    """Exact CUSUM likelihood ratio over all changepoints, with pruning.

    Stateful across calls like `Cusum`, so it can be fed a stream one
    observation at a time.
    """

    threshold: float = THRESHOLD
    #: Look for an increase in the mean. See the module docstring.
    up: bool = True
    #: How the stream is scaled. Observations are divided by this before the
    #: Gaussian statistic is applied, so a threshold means the same thing on
    #: gold and on BTC - the same argument volatility units make everywhere.
    scale: float = 1.0
    seen: int = 0
    total: float = 0.0
    #: The pruned candidate set: `(index, cumulative sum)` on the hull.
    hull: list[tuple[int, float]] = field(default_factory=list)
    #: The statistic at the last observation, and where it says the change was.
    statistic: float = 0.0
    at: int = 0

    def reset(self) -> None:
        """Start again from here, after a change has been acted on."""
        self.hull = [(self.seen, self.total)]
        self.statistic = 0.0
        self.at = 0

    def update(self, value: float, scale: float = 0.0) -> bool:
        """Feed one observation. True when the evidence clears the threshold.

        `scale` overrides the stored one for this observation, because
        volatility moves and a detector calibrated to last week's is measuring
        the wrong thing this week - the same argument `Cusum.push` makes.
        """
        unit = scale or self.scale
        if unit <= 0:
            return False
        if not self.hull:
            self.hull = [(self.seen, self.total)]

        self.total += float(value) / unit
        self.seen += 1
        here = (self.seen, self.total)

        # The maximum over the surviving candidates. One-sided: a candidate
        # whose sum is above the current one is evidence of a *fall* and is not
        # what this instance is looking for.
        best, where = 0.0, 0
        for tau, s in self.hull:
            gap = self.seen - tau
            if gap <= 0:
                continue
            diff = self.total - s if self.up else s - self.total
            if diff <= 0:
                continue
            score = diff * diff / (2.0 * gap)
            if score > best:
                best, where = score, tau
        self.statistic, self.at = best, where

        # Prune, then add. A candidate sitting above the chord between its
        # neighbour and the new point can never be the argmax again, whatever
        # arrives next, so it is dropped once rather than re-tested for ever.
        while len(self.hull) >= 2 and _inside(self.hull[-2], self.hull[-1], here, self.up):
            self.hull.pop()
        self.hull.append(here)
        return best >= self.threshold

    def reading(self) -> dict[str, float]:
        """The statistic and what it costs to hold, for a journal entry."""
        return {
            "focus_statistic": round(self.statistic, 4),
            "focus_at": float(self.at),
            "focus_candidates": float(len(self.hull)),
            "focus_seen": float(self.seen),
        }


def _inside(
    left: tuple[int, float], middle: tuple[int, float], right: tuple[int, float], up: bool
) -> bool:
    """Whether `middle` can be dropped: it is never the best candidate again.

    The cross product of the two chords. For an increase the surviving
    candidates are those with the *smallest* partial sums for their index -
    the lower hull - because the statistic rewards a large rise from `tau`.
    """
    (x1, y1), (x2, y2), (x3, y3) = left, middle, right
    cross = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
    return cross <= 0 if up else cross >= 0
