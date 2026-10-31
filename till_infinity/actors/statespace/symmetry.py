"""Symmetry in the displacement sequence, as a switching model over it.

Two in-house papers make the same claim from different directions. One says
price can be predicted by finding symmetry in the sequence of moves between
reversals:

> `dN(t+k) = S(dN(t))`, where `S` is a symmetry transformation and `k` the
> periodicity of the cyclic pattern

and offers a **Nodal Symmetry Index** to measure how well it holds - the mean
distance between a displacement and the transform of the one `k` back - with
the reading that low NSI means structure and high NSI means noise. The other
asserts the same thing about ratios between swings persisting within a regime
and breaking at its boundary.

Neither paper reports a number. The first one's results section says
"significant improvements" and "superior performance" without a table, so
there is nothing here to replicate - only a shape to test, which is why this
module exists and a backtest of their strategy does not.

## What the transformation can actually be

A displacement has a size, a duration and a direction, and `displacements.py`
already drops the case where two same-direction swings follow each other, so
**the sequence alternates by construction**. That kills reflection as a
candidate: direction flipping is not a finding when the detector enforces it.

What is left is **scaling** - the size ratio between consecutive moves - and
that is the only free quantity in the claim. So `S` is a scaling, the
observation is `log(size(t) / size(t-1))`, and the three symmetry classes are
the three things that ratio can do:

* **mirror** - the ratio sits at one, swings repeat at the same scale. This
  is the symmetric case the papers are named after, and in auction terms it
  is rotation around a value.
* **expanding** - each swing larger than the last. A trend taking hold.
* **contracting** - each swing smaller. The papers' reversal signal, on the
  reading that shrinking displacements mean a dying move.

Three Gaussians over one scalar, mixed each step: the same interacting
multiple model `switching.py` runs, on a different observation.

## The hazard is per hour, which is the whole reason this is portable

The sequence's own clock is the turn, not the hour, and it would be natural to
let the regime persist for a number of *displacements*. That is the bar count
in disguise: a market that turns ten times in a day and one that turns twice
would get regimes of the same length in events and wildly different lengths
in time, and the member would stop meaning the same thing at 15m and 1d.

So the transition hazard is per hour and it is applied over the displacement's
**own duration**. A regime that lasts twenty hours lasts twenty hours whether
the market turned twice inside it or ten times.

## Its likelihood is not comparable to a price member's

This member observes a ratio, not a price. Its `loglike` is a density over a
different quantity and putting it in a table next to `linear` would be
meaningless. **Its nulls are the same model on a shuffled sequence** - same
displacements, order destroyed, which removes symmetry and keeps the size
distribution - and on the displacement sequence of a random walk, which has
turns but no structure between them.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

from .displacements import Relation

HOUR = 3600.0
TAU = 2.0 * math.pi

#: The three classes, in the order the arrays hold them.
CLASSES = ("mirror", "expanding", "contracting")

#: Where each class sits in log-ratio. Mirror at zero by definition; the other
#: two at plus and minus the logarithm of a golden-ish step, which is not a
#: mystical choice - it is one scale of swing per regime, and the fit moves
#: them anyway.
CENTRES = (0.0, 0.48, -0.48)

#: How long a symmetry regime is expected to hold, in hours. Started at a day
#: because a swing structure that resolves inside an hour is not a regime.
PERSIST_HOURS = 24.0

#: Spread of the log ratio within a class: the emission width, shared.
SPREAD = 0.55

#: Kept so a caller can widen the emissions over a long gap, which is the one
#: sense in which a class is less certain after a silence.
CENTRE_WANDER = 1e-3

#: **The class centres are fixed, and that is the design rather than a
#: simplification.**
#:
#: The first version made them states. All three then walked to wherever the
#: data was - same starting variance, same gain, same destination - so the
#: means collapsed, the three densities became one, and the posterior sat at
#: a third forever. A test caught it reporting exactly that, and anchoring
#: them with a reversion only slowed it down: the measurement update still
#: dragged every centre toward the observation and 0.48 arrived at 0.095.
#:
#: The deeper reason is that a class here is a **definition**, not a level to
#: be estimated. Mirror *means* the ratio is one. A mirror class whose centre
#: has drifted to 1.4 is not a better-fitted mirror, it is a mislabelled
#: expansion - and then every reading of `contracting` is a reading of where
#: the centres happen to have drifted.
#:
#: So this is a hidden Markov model with known emissions: three fixed
#: hypotheses about what the ratio is doing, scored by likelihood, mixed by a
#: hazard per hour. Letting the centres move is a separate and later
#: question, and it belongs in a fit over a whole series rather than in a
#: per-reading update.


@dataclass(slots=True)
class Symmetry:
    """Three symmetry classes over the displacement ratios, mixed each step."""

    persist_hours: float = PERSIST_HOURS
    spread: float = SPREAD
    centre_wander: float = CENTRE_WANDER

    #: One Gaussian per class, over the log ratio.
    means: list[float] = field(default_factory=list)
    variances: list[float] = field(default_factory=list)
    #: Posterior over classes, in `CLASSES` order.
    weights: list[float] = field(default_factory=list)

    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    burn: int = 6
    existence: float = 1.0
    last_standardised: float = 0.0

    def __post_init__(self) -> None:
        if not self.means:
            self.means = list(CENTRES)
        if not self.variances:
            self.variances = [self.spread * self.spread] * len(CLASSES)
        if not self.weights:
            share = 1.0 / len(CLASSES)
            self.weights = [share] * len(CLASSES)

    # ------------------------------------------------------------- the reading

    @property
    def mirror(self) -> float:
        """Posterior probability the swings are repeating at one scale."""
        return self.weights[0]

    @property
    def expanding(self) -> float:
        return self.weights[1]

    @property
    def contracting(self) -> float:
        """The papers' reversal reading: displacements shrinking."""
        return self.weights[2]

    @property
    def regime(self) -> str:
        """The most likely class, for reporting. Never for gating."""
        best = max(range(len(CLASSES)), key=lambda i: self.weights[i])
        return CLASSES[best]

    @property
    def value(self) -> float:
        """Expected log ratio of the next displacement to the last."""
        return sum(w * m for w, m in zip(self.weights, self.means, strict=True))

    @property
    def rate(self) -> float:
        return 0.0

    @property
    def sd(self) -> float:
        """Spread of the mixture, carrying the disagreement between classes."""
        middle = self.value
        total = sum(
            w * (v + (m - middle) ** 2)
            for w, m, v in zip(self.weights, self.means, self.variances, strict=True)
        )
        return math.sqrt(max(total, 0.0))

    @property
    def expected_ratio(self) -> float:
        """The next size as a multiple of the last.

        Exponentiated with the half-variance correction, because the mean of a
        lognormal is not the exponential of the mean and dropping the term
        would bias every forecast low.
        """
        return math.exp(self.value + 0.5 * self.sd * self.sd)

    def state(self) -> tuple[float, ...]:
        return (self.value, self.weights[0])

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return ((1.0, 0.0),)

    def at_time(self, when: float) -> float:  # noqa: ARG002
        """The expected log ratio.

        It does not depend on `when`, and that is not an oversight. The next
        ratio is a property of the next *turn*, which has not happened; there
        is no sense in which it is further away in an hour than it is now.
        Projecting it forward in clock time would invent a decay the sequence
        does not have.
        """
        return self.value

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        middle = self.at_time(when)
        width = sigmas * self.sd
        return (middle - width, middle + width)

    # ------------------------------------------------------------ the machinery

    def _switch(self, hours: float) -> list[list[float]]:
        """Transition matrix over `hours`, from a per-hour hazard.

        One hazard, shared: there is no evidence for an asymmetric one between
        symmetry classes, and three free durations on a sequence this sparse
        would be fitted to noise.
        """
        if self.persist_hours <= 0 or hours <= 0:
            width = len(CLASSES)
            return [[1.0 if i == j else 0.0 for j in range(width)] for i in range(width)]
        leave = -math.expm1(-hours / self.persist_hours)
        width = len(CLASSES)
        spread = leave / (width - 1)
        return [[1.0 - leave if i == j else spread for j in range(width)] for i in range(width)]

    def predict(self, when: float, control: float = 0.0) -> None:  # noqa: ARG002
        """Mix the class posterior through the transition.

        `when` is the time of the displacement being predicted, and the
        elapsed hours come from the previous one - which is the duration of
        the move itself, so the hazard sees real time rather than turns.

        Only the weights move. The centres are the classes' definitions and
        the spreads are the emission widths, and neither is a state.
        """
        hours = 0.0
        if self.at is not None:
            hours = max((float(when) - self.at) / HOUR, 0.0)
        matrix = self._switch(hours)
        width = len(CLASSES)

        mixed = [sum(matrix[i][j] * self.weights[i] for i in range(width)) for j in range(width)]
        total = sum(mixed)
        if total <= 0:
            share = 1.0 / width
            self.weights = [share] * width
        else:
            self.weights = [w / total for w in mixed]
        self.at = float(when)

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """One log ratio, scored against each class, and the classes reweighted.

        `measured` is `log(size(t) / size(t-1))` and `noise` the **variance**
        of a single ratio around its class centre - a measurement variance
        rather than an instrument's, because a displacement is not read off a
        quote, but a variance all the same so that this member can be scored
        beside the others.
        """
        if when is not None and self.at is None:
            self.at = float(when)
        if not math.isfinite(measured):
            return 0.0

        # The measurement **variance**, per the `Filter` contract. Squared
        # here once, which made every comparison against another member wrong
        # by a square.
        extra = max(noise, 1e-18)
        width = len(CLASSES)

        densities: list[float] = []
        for j in range(width):
            spread = self.variances[j] + extra
            residual = measured - self.means[j]
            densities.append(
                math.exp(-0.5 * residual * residual / spread) / math.sqrt(TAU * spread)
            )

        evidence = sum(w * d for w, d in zip(self.weights, densities, strict=True))
        if evidence <= 0:
            return 0.0

        self.seen += 1
        if self.seen > self.burn:
            self.loglike += math.log(evidence)

        # Standardise against the **predictive** spread of the mixture, which
        # carries the spread between the classes, within them, and the
        # measurement variance. `self.sd` alone omits `R`, so a residual built
        # on it is not comparable with another member's - the defect
        # `switching` had in a sharper form.
        predictive = math.sqrt(self.sd * self.sd + extra)
        self.last_standardised = (measured - self.value) / max(predictive, 1e-12)

        self.weights = [w * d / evidence for w, d in zip(self.weights, densities, strict=True)]
        total = sum(self.weights)
        if total <= 0:
            share = 1.0 / width
            self.weights = [share] * width
        else:
            self.weights = [w / total for w in self.weights]
        return self.last_standardised

    def absorb(self, relation: Relation, noise: float | None = None) -> float:
        """Take one `Relation` straight from `displacements.relations`.

        Uses `confirmed` as the clock, not the time the move ended, so the
        member never sees a ratio before the market had confirmed the pivot
        that closed it.
        """
        self.predict(relation.confirmed)
        # `self.spread` is a standard deviation and `update` takes a
        # variance, so it is squared here rather than at every call site.
        return self.update(
            relation.log_ratio,
            self.spread * self.spread if noise is None else noise,
            relation.confirmed,
        )


def nodal_symmetry(sizes: Sequence[float], lag: int) -> float:
    """The papers' NSI at one lag, for a scaling transformation.

    `NSI = (1/n) sum |dN(i) - S(dN(i-lag))|` with `S` a scaling reduces to the
    mean absolute log ratio across the lag: how far, in multiplicative terms,
    a swing is from the one `lag` back. Low means sizes repeat at that lag.

    **It is only a reading next to its null.** The mean absolute log ratio of
    a shuffled sequence is the same statistic with the order destroyed, and a
    sequence with no symmetry gives the same number for both.
    """
    if lag < 1 or len(sizes) <= lag:
        return float("nan")
    gaps = [
        abs(math.log(sizes[i] / sizes[i - lag]))
        for i in range(lag, len(sizes))
        if sizes[i] > 0 and sizes[i - lag] > 0
    ]
    return statistics.fmean(gaps) if gaps else float("nan")
