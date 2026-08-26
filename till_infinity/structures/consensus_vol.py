"""Four estimates of one quantity, put on one scale and scored before combining.

There are now four readings of how much an instrument moves, and they disagree
by construction:

| estimator | reads | measures |
| --- | --- | --- |
| `volatility` | closes | mean absolute deviation |
| `garch` | closes | conditional scale, mean-reverting |
| `ranges` | whole bars | standard deviation |
| `har` | whole bars | a **forecast** of the next bar |

Averaging them as they stand would be wrong in a way that looks right, and the
number that came out would be neither of the things being averaged.

## First: they are not in the same units

`volatility.py` tracks the mean absolute return. The range estimators produce a
standard deviation. For a normal variable those differ by a fixed factor:

    E|X| = sigma * sqrt(2 / pi)     so     sigma = E|X| * sqrt(pi / 2)

about 1.253. Returns are not normal - that is the reason `volatility.py` chose
mean absolute deviation in the first place - so this is a **convention**, not a
correction: it makes the numbers comparable rather than making either of them
right. Everything here is converted to the mean-absolute convention, because
that is the scale every existing threshold in this package was tuned against
and the point is to leave those alone.

## Second: nothing may be combined before it can be scored

An ensemble needs to know which members are any good, and none of these had
ever been checked against an outcome. So each estimate is scored the only way a
volatility estimate can be: against **what the next bar actually did**. The
error is relative rather than absolute, because an instrument moving 40bps and
one moving 0.4bps must contribute comparably, and it is tracked as a decayed
mean so a member that degrades loses its standing rather than keeping it on
history.

## Third: equal weights, until there is a reason for others

The combination is a plain average of the members that are warm. Not because
it is easy - because combining forecasts is one of the better-established
results in the literature *and* the simple average routinely beats optimally
fitted weights out of sample, since the weights are estimated with error and
the error does not vanish.

This repository has its own version of that warning. [edge.md](../../docs/edge.md)
measured a rolling quantile against a matched constant and the constant won
four times out of four; the dynamic rule lost because it was fitting something
that did not need fitting. Inverse-error weighting is available here and is
**off**, so the equal-weight version can be beaten before it is replaced.

## What this does not do

Nothing divides by this yet. It is published beside `vol_bps` like its members
are, and the journal decides whether the combination beat the estimate already
in use. Given that every threshold in this package is denominated in that one
number, switching on the strength of the reasoning above would be exactly the
mistake the paragraph above describes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .state import Restorable

#: Mean absolute deviation to standard deviation, for a normal. Applied in
#: reverse to bring a standard-deviation estimator onto the mean-absolute
#: convention the existing thresholds were tuned against.
MAD_TO_SIGMA = math.sqrt(math.pi / 2.0)

#: Observations before a member's score is trusted enough to weight by.
SCORE_WARMUP = 60

#: Decay on the error history. A member that degrades should lose its standing
#: rather than keep it on the strength of how it behaved last month.
DECAY = 0.999


@dataclass(slots=True)
class Score(Restorable):
    """One member's running relative error against what actually happened."""

    error: float = 0.0
    seen: float = 0.0

    def record(self, predicted: float, actual: float) -> None:
        """Fold in one comparison. Relative, so instruments are comparable."""
        if predicted <= 0 or actual <= 0:
            return
        # Symmetric relative error: |a - b| / (a + b), bounded in [0, 1], and
        # it does not explode when the denominator is small the way a plain
        # percentage error does on a quiet bar.
        rel = abs(predicted - actual) / (predicted + actual)
        self.seen = self.seen * DECAY + 1.0
        weight = 1.0 / min(max(self.seen, 1.0), 200.0)
        self.error = rel if not self.error else self.error * (1 - weight) + rel * weight

    @property
    def warm(self) -> bool:
        return self.seen >= SCORE_WARMUP

    @property
    def accuracy(self) -> float:
        """1 - error, so larger is better. Zero when there is nothing to say.

        `warm` is the only thing that means "nothing to say". An error of zero
        is a member that has been exactly right, which is the best score there
        is - the first version of this treated it as the worst, because the
        same guard was doing duty for "no data" and "no error".
        """
        if not self.warm:
            return 0.0
        return max(0.0, 1.0 - self.error)


@dataclass(slots=True)
class Ensemble(Restorable):
    """Members on one scale, scored against outcomes, combined equally."""

    #: Off by default. See the module note: the equal-weight version has to be
    #: beaten before anything fitted replaces it.
    weighted: bool = False
    _scores: dict[str, Score] = field(default_factory=dict)
    _members: dict[str, float] = field(default_factory=dict)

    def _score(self, name: str) -> Score:
        found = self._scores.get(name)
        if found is None:
            found = self._scores[name] = Score()
        return found

    def observe(
        self, members: dict[str, float], *, sigma_scaled: frozenset[str] = frozenset()
    ) -> None:
        """Take this bar's readings, converting anything on the sigma scale.

        `sigma_scaled` names the members that report a standard deviation - the
        range estimators - so they are brought onto the mean-absolute
        convention rather than being averaged against it directly.
        """
        self._members = {
            name: (value / MAD_TO_SIGMA if name in sigma_scaled else value)
            for name, value in members.items()
            if value > 0
        }

    def settle(self, actual_bps: float) -> None:
        """Say what the bar actually did, and score what each member said."""
        if actual_bps <= 0:
            return
        for name, value in self._members.items():
            self._score(name).record(value, actual_bps)

    @property
    def bps(self) -> float:
        """The combined estimate. Zero when there is nothing to combine."""
        if not self._members:
            return 0.0
        if not self.weighted:
            return sum(self._members.values()) / len(self._members)

        weights = {n: self._score(n).accuracy for n in self._members}
        total = sum(weights.values())
        if total <= 0:
            # Nothing has earned a weight yet, which is not the same as
            # everything having a weight of zero.
            return sum(self._members.values()) / len(self._members)
        return sum(self._members[n] * w for n, w in weights.items()) / total

    def accuracy(self, name: str) -> float:
        """How well one member has been doing, in [0, 1]. Zero until warm."""
        return self._score(name).accuracy

    def standings(self) -> list[tuple[str, float]]:
        """Members by accuracy, best first. What the journal is for."""
        return sorted(
            ((n, s.accuracy) for n, s in self._scores.items() if s.warm),
            key=lambda pair: -pair[1],
        )
