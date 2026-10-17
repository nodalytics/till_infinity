"""The changepoint detector `paired.py` runs, vendored so the package stands alone.

**This package must not import from anywhere outside itself.** It is built to be
extractable - and deletable - in one move, so a reach up into
`structures.learning` or `shared` makes that a code change rather than a copy.
`bounding.py` restates the Broadie-Glasserman-Kou constant for the same reason.

`paired.py` previously imported `Focus` from `structures/learning/focus.py`, and
its docstring records *why* it imported rather than duplicated: the persistence
registry keys classes by **module basename and class name**, so a second module
called `focus` holding a second class called `Focus` resolved to the same
`focus.Focus`, one silently shadowed the other, and a restore built the wrong
class. Two tests caught it in CI.

So this is not named `focus.Focus`, and it is not named `cusum` either.

**The first attempt at this file was `statespace/cusum.py`, and it broke the
schema test.** The class name was changed and the *module* name was not:
`codec.py` also keys a basename-to-location map by walking `structures`, there
is already a `context/cusum.py`, and two modules called `cusum` made that map
ambiguous - so a new field on `context.cusum.Cusum` stopped invalidating saved
state. The incident this module's caller documented has **two** halves and
avoiding one of them is not enough.

`accruing` is a basename that exists nowhere else under `structures`, and
`OneSided` a class name that exists nowhere else.

The package being outside the registry would have covered it anyway -
`CODEC_UNPERSISTED` is checked up the parent packages, so a walk of `structures`
registers 120 classes and **none is from `statespace`** - but a flag is one line
and this hazard has now cost three CI failures to find, so the names are
distinct as well.

The implementation is copied unchanged apart from dropping the `Restorable`
base, which this package deliberately does not use - nothing here is saved.
`tests/test_statespace.py` asserts this copy and the original agree observation
by observation, so the duplication cannot drift silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The evidence threshold in nats. Calibrated in
#: `research/docs/statespace-paired-threshold.md`: on a stationary standard
#: normal stream this gives an average run length to a false alarm of about
#: **216,000** observations and detects a one-sigma shift in 22, but **on a real
#: series it alarms every 1,389 instead** - a factor of 156, from volatility
#: clustering, measured on EURUSD, XAUUSD and BTCUSD. The number to quote beside
#: it is 1,389.
THRESHOLD = 12.0


@dataclass(slots=True)
class OneSided:
    """Exact CUSUM likelihood ratio over all changepoints, with pruning.

    Stateful across calls, so it can be fed a stream one observation at a time.
    One-sided on purpose: "moves got bigger" and "moves got smaller" are
    different events, which is why `paired.py` runs two of these.
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
