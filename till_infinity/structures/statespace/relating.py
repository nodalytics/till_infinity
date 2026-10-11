"""The hedge ratio as a state: what statistical arbitrage needs and lacked.

`subjects.py` has said since the package began that statistical arbitrage is
not a second system here:

> It is `RELATION`: level becomes relationship, distance becomes deviation,
> zone becomes deviation dispersion, and **the slope becomes a drifting hedge
> ratio**.

Every member in this package observes a **scalar**, so the only way to use one
for a pair was to compute the spread somewhere else, at a hedge ratio chosen
somewhere else, and hand in the residual. That is not the thesis - it is the
thesis with its hardest part done by hand and held fixed, and a hedge ratio
held fixed is the assumption that breaks a pairs trade.

## The trick that makes this fit a scalar-observation family

A pair does not need a vector observation. Write the relationship as

    y_t = alpha_t + beta_t x_t + e_t

and it is **one** scalar observation `y_t` whose observation row carries the
other leg:

    H_t = [1, x_t]

so `alpha` and `beta` are *states*, estimated jointly with their covariance,
and the spread is the innovation. The only thing the existing members cannot do
is let `H` change per reading - `Gaussian` hardcodes `[1, 0, 0]` - and that is
the whole gap. This member is `Gaussian`'s arithmetic with `H` passed in.

The consequences are the ones a pairs desk wants and a precomputed spread
cannot give:

* **The hedge ratio drifts**, with a stated uncertainty, so "the relationship
  is changing" and "the spread is wide" are different readings rather than one
  confounded number.
* **The spread's dispersion is the model's own predictive spread**, so a
  z-score is a z-score rather than a rolling standard deviation of something
  whose definition moved.
* **A relationship that ends** shows up as `beta` wandering with a growing
  band, which is the failure mode `research/docs/idea.md` names: *a
  relationship that can end while still producing a confident deviation*.

## A basket is the same arithmetic, so it is the same member

`H_t = [1, x1, x2, ..., xn]` and an `(n+1)`-square covariance. Nothing about
the recursion changes, so `Relating` takes `legs` and the pair is the `legs=1`
case rather than a separate class. That is what makes the architecture support
multi-leg statistical arbitrage rather than merely not forbid it: one
dependent instrument regressed on a basket, every weight a state with its own
uncertainty and every pair of weights a covariance.

**What this form is and is not.** It is a *regression*: one leg explained by
the others, which is the right shape for a hedge, because a hedge is exactly
"how much of the others do I hold against this one". It is **not** a joint
model of all the legs at once - that needs a genuinely vector observation and
an `n`-square measurement noise, and it is what cross-impact would require
(Lillo, arXiv:2105.00521, where the response of asset `j` to an order on asset
`i` is non-zero and about five times smaller than the self-response). A hedge
does not need it; a cross-impact study does, and that is a different member.

## The stated weight uncertainty is conditional, and the condition bites

`ratio_sds` is honest **only if the observation noise is white and
independent**, which is the Kalman filter's standing assumption and not a
property of a price series. Measured on a collinear basket of three random
walks regressed in **levels**, the filter recovers weights of `0.924, -0.434,
1.338` against a true `0.8, -0.5, 1.3` - good - while reporting standard
deviations near **0.004**, which is thirty times smaller than the errors it
actually made.

That is not a bug in the recursion; it is the recursion correctly propagating
an assumption that the data violates. A levels regression on near-collinear
random walks has heavily autocorrelated residuals, and an autocorrelated
residual fed to a filter that believes it is white produces exactly this: the
right answer with an indefensible confidence interval.

Two remedies, both the caller's:

* **Regress returns rather than levels** where the relationship is a
  co-movement rather than a cointegration. Spurious regression is the textbook
  hazard of the levels form and it is not softened by putting a filter around
  it.
* **Check the innovations are white.** `diagnostics.py` runs Ljung-Box on
  `last_standardised`, and a basket whose innovations fail it has a `ratio_sd`
  that should not be quoted. This is the same rule the package applies to every
  other member and the reason the test exists.

## What it does not do

It does not choose the basket, test for cointegration, or decide the
direction of the regression - `y on x` and `x on y` give different hedge ratios
and the choice matters. Those are the caller's, and `research/ideas/` is where
they get measured.

## Nothing here publishes

The nulls are named and both are the obvious thing a desk does instead: a
**static** hedge ratio fitted once by least squares, and a **rolling-window**
one refitted each bar. This member must beat both on held-out likelihood. And
the desk's own prior is discouraging: the relationship trade has been measured
here at a gross Sharpe of **+0.27** and a net of **-0.97**, so the bar is not
"does the spread revert" but "does it revert past two spreads and a financing
cost".
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

HOUR = 3600.0

#: Process noise on the intercept and on the hedge ratio, per hour. Separate
#: because they are different quantities in different units: `alpha` is in the
#: dependent leg's units and `beta` is dimensionless. **Not fitted** - the
#: harness sweeps them, and `diagnostics` is where a fit would go.
LEVEL_WANDER = 1e-4
RATIO_WANDER = 1e-7


@dataclass(slots=True)
class Relating:
    """`y = w0 + w1 x1 + ... + wn xn + e`, with every weight a drifting state.

    The observation is scalar - the dependent leg - and the independent legs
    arrive in the observation row, which is what lets this carry a basket of
    hedge ratios without the family becoming multivariate.
    """

    #: How many independent legs. One is a pair; the weights are
    #: `[intercept, ratio_1, ..., ratio_legs]`.
    legs: int = 1

    #: The states: intercept first, then one hedge ratio per leg.
    weights: list[float] = field(default_factory=list)
    #: Their covariance, `(legs + 1)` square. The **off-diagonal terms are the
    #: reason this is a filter and not `legs` separate regressions**: a basket
    #: whose weights are jointly uncertain has a wider spread than any weight
    #: alone implies, and that is exactly the case where a pairs book looks
    #: safe and is not.
    covariance: list[list[float]] = field(default_factory=list)

    #: Process noise per hour on the intercept and on each ratio. Separate
    #: because they are different quantities in different units: the intercept
    #: is in the dependent leg's units and a ratio is dimensionless.
    level_wander: float = LEVEL_WANDER
    ratio_wander: float = RATIO_WANDER

    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    burn: int = 10
    existence: float = 1.0
    last_standardised: float = 0.0

    #: The last reading's independent legs, so `value`, `sd` and `band` can be
    #: asked without passing them again.
    _against: list[float] = field(default_factory=list, repr=False)
    #: The last innovation: the realised spread at the current weights.
    spread: float = 0.0

    def __post_init__(self) -> None:
        size = self.legs + 1
        if not self.weights:
            # Intercept at zero and every ratio at one. A ratio of one is a
            # prior that the legs move together, which is why the basket was
            # chosen; zero would be a prior that it does not.
            self.weights = [0.0] + [1.0] * self.legs
        if not self.covariance:
            self.covariance = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
        if not self._against:
            self._against = [0.0] * self.legs

    # ------------------------------------------------------------- the reading

    def _row(self) -> list[float]:
        """`H`, at the last legs seen. **Time-varying, which is the point.**"""
        return [1.0, *self._against]

    @property
    def value(self) -> float:
        """Fair value of the dependent leg, at the last legs seen."""
        return sum(w * h for w, h in zip(self.weights, self._row(), strict=True))

    @property
    def rate(self) -> float:
        """Zero. This member has no time trend, and inventing one is a claim."""
        return 0.0

    @property
    def ratio(self) -> float:
        """The first hedge ratio. For a pair, *the* hedge ratio."""
        return self.weights[1] if len(self.weights) > 1 else 0.0

    @property
    def ratios(self) -> tuple[float, ...]:
        """Every hedge ratio. What a basket desk actually holds."""
        return tuple(self.weights[1:])

    @property
    def ratio_sd(self) -> float:
        """Uncertainty on the first hedge ratio. Widening means it is ending."""
        return math.sqrt(max(self.covariance[1][1], 0.0)) if self.legs else 0.0

    @property
    def ratio_sds(self) -> tuple[float, ...]:
        return tuple(math.sqrt(max(self.covariance[i][i], 0.0)) for i in range(1, self.legs + 1))

    def _quadratic(self, extra: float = 0.0) -> float:
        """`H P H'`, optionally with `extra` hours of wander added first."""
        row = self._row()
        total = 0.0
        for i, hi in enumerate(row):
            for j, hj in enumerate(row):
                value = self.covariance[i][j]
                if i == j and extra > 0.0:
                    value += (self.level_wander if i == 0 else self.ratio_wander) * extra
                total += hi * value * hj
        return total

    @property
    def sd(self) -> float:
        """Predictive spread of the dependent leg at the last legs.

        `H P H'`, which is where the cross terms earn their place: dropping
        them understates the spread whenever the weights are correlated, which
        they always are after a few readings.
        """
        return math.sqrt(max(self._quadratic(), 0.0))

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def state(self) -> tuple[float, ...]:
        return tuple(self.weights)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return (tuple(self._row()),)

    def transition(self, dt_hours: float) -> tuple[tuple[float, ...], ...]:  # noqa: ARG002
        """`F = I`. Every weight random-walks; none drives another."""
        size = len(self.weights)
        return tuple(tuple(1.0 if i == j else 0.0 for j in range(size)) for i in range(size))

    def at_time(self, when: float) -> float:  # noqa: ARG002
        """Fair value, which does not move with time on its own.

        A basket's fair value moves because the *other legs* moved, not because
        the clock did. Returning a time-extrapolated value would be inventing a
        trend this member explicitly does not carry.
        """
        return self.value

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        elapsed = 0.0
        if self.at is not None:
            elapsed = max((float(when) - self.at) / HOUR, 0.0)
        half = sigmas * math.sqrt(max(self._quadratic(elapsed), 0.0))
        return (self.value - half, self.value + half)

    # ------------------------------------------------------------- the filter

    def predict(self, when: float, control: float = 0.0) -> None:  # noqa: ARG002
        """Advance. `F = I`, so only the covariance moves."""
        if self.at is None:
            self.at = float(when)
            return
        dt = (float(when) - self.at) / HOUR
        self.at = float(when)
        if dt <= 0.0:
            return
        self.covariance[0][0] += self.level_wander * dt
        for i in range(1, self.legs + 1):
            self.covariance[i][i] += self.ratio_wander * dt

    def update(
        self,
        measured: float,
        noise: float,
        when: float | None = None,
        *,
        against: float | Sequence[float] = 0.0,
    ) -> float:
        """Fold in one reading. `measured` is `y`, `against` the other legs.

        `against` is keyword-only and defaults to zero so the signature still
        satisfies `Filter` - but a caller who forgets it is regressing on a
        constant, which is why the default is the value that makes that
        obvious rather than one that quietly works.
        """
        legs = [float(against)] if isinstance(against, int | float) else list(against)
        if len(legs) != self.legs:
            raise ValueError(
                f"this member has {self.legs} leg(s) and was given {len(legs)}. "
                "A basket that changes width mid-stream is a different model, "
                "not the same one with a missing column."
            )
        if when is not None and self.at is None:
            self.at = float(when)
        self._against = legs
        row = self._row()

        if self.seen == 0:
            # The first reading sets the intercept and keeps the ratios' prior.
            # Taking a slope from one point would not be an estimate.
            self.weights[0] = measured - sum(
                w * h for w, h in zip(self.weights[1:], legs, strict=True)
            )
            self.covariance[0][0] = max(noise, 1e-12)
            self.seen = 1
            self.existence = 1.0
            return 0.0

        # S = H P H' + R, and `ph` is `P H'`, reused for the gain.
        size = len(row)
        ph = [sum(self.covariance[i][j] * row[j] for j in range(size)) for i in range(size)]
        s = sum(row[i] * ph[i] for i in range(size)) + max(noise, 0.0)
        innovation = measured - self.value
        self.spread = innovation
        if s <= 0.0:
            return innovation

        self.last_standardised = innovation / math.sqrt(s)
        if self.seen >= self.burn:
            self.loglike += -0.5 * (math.log(2.0 * math.pi * s) + innovation * innovation / s)

        gain = [value / s for value in ph]
        for i in range(size):
            self.weights[i] += gain[i] * innovation

        # P <- (I - K H) P, then symmetrised. Symmetry is an invariant rather
        # than an outcome: round-off breaks it, and a covariance that has
        # stopped being symmetric has stopped being a covariance.
        updated = [
            [self.covariance[i][j] - gain[i] * ph[j] for j in range(size)] for i in range(size)
        ]
        self.covariance = [
            [0.5 * (updated[i][j] + updated[j][i]) for j in range(size)] for i in range(size)
        ]

        self.seen += 1
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)
        return innovation

    @property
    def z(self) -> float:
        """The spread in units of its own predictive spread. The stat-arb reading.

        **Not a rolling standard deviation of a precomputed spread**, which is
        the usual construction and which confounds two things: a spread that
        widened because the basket diverged, and a spread that widened because
        the weights are no longer known. This separates them - the second is in
        `ratio_sds`.
        """
        return self.last_standardised
