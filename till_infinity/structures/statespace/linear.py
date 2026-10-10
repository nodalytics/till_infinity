"""The linear-Gaussian model, written in continuous time and subject-agnostic.

One latent quantity that drifts and accelerates, observed noisily. That is the
whole thesis in one object, and the three subjects in `subjects.py` are this
model with different meanings attached to the same three numbers.

## How this differs from `levels.Kalman`, which keeps running the desk

Not in what it computes - the state, the gains and the `trending` / `turning`
readings are the same arithmetic. In how the process noise is **parameterised**:

* `levels.Kalman` grows its covariance from `DRIFT_VOL_PER_HOUR`, applied to the
  price row, with the slope and acceleration rows carrying their own separately
  chosen terms.
* Here there is **one** parameter, `jerk`, with explicit units, and the whole
  `Q(dt)` follows from it by integrating the continuous model. The three rows
  cannot drift out of step with each other because there is nothing to set
  independently.

That is the difference the spec's I2 and I10 are about, and it is why this is
written beside the incumbent rather than as an edit to it: one parameter against
three means the two models make different predictions about how a level's
uncertainty grows between touches, and **that is measurable on touch pairs** -
`var(touch2 - touch1) = q*dt + 2R`, slope the process variance, intercept twice
the measurement noise.

## The parameter nobody has measured

`jerk` is the spectral density of the third derivative, in value units squared
per hour to the fifth. Its counterpart in production is
`DRIFT_VOL_PER_HOUR = 0.02`, which was chosen per hour and applied at every
timeframe, and which the structures outcomes journal cannot currently be used to
fit because it records `feed`, `interval`, `interval_log` and `level` but not the
raw touch price. Until that field exists, any value here is a placeholder and
this module says so rather than implying otherwise.

## What the coefficients may depend on, which is I4

`state_space` (michaelnowotny) states the constraint cleanly: the coefficients
may depend on **exogenous data and on unknown parameters, but not on the state**.
That is the line between this model and a different one, and it settles what I4
is asking for.

I4 says `A` should change with the operating point and this one never does. If
"operating point" means something exogenous - the hour, the regime, the
instrument's own volatility - then `A(t)` is still a linear state-space model and
the change is admissible here. If it means the state itself, so that the rate's
coefficient depends on where the value currently is, the model stops being linear
and the Kalman stops being the right filter: that is the nonlinear Gaussian case,
and it belongs beside this module rather than inside it.

The distinction is worth holding onto because the two look identical when
written informally and have different filters.

## Existence probability

Carried here as a third number beside the mean and the variance, exactly as the
spec says - not a different kind of object. It decays with elapsed time and is
reinforced by a measurement, and **nothing reads it yet**. It is here because the
set layer in Phase 2 needs it and because `State.BROKEN` is the boolean it would
replace.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

HOUR = 3_600.0

#: Half-life of existence belief, in hours, with no measurements at all. Seven
#: days, matching `engine.FORGET_FEED_SECONDS`, because a quantity the desk has
#: stopped seeing evidence for and a feed it has stopped seeing bars from are the
#: same kind of absence and should not decay on two different clocks.
EXISTENCE_HALF_LIFE_HOURS = 7 * 24.0


@dataclass(slots=True)
class Gaussian:
    """One latent `(value, rate, accel)` with its covariance, in continuous time.

    State, in order: the quantity itself, its rate per hour, and the rate's own
    rate per hour per hour. `P` is the full 3x3 covariance held as nine floats -
    written out rather than nested, so a restore cannot reshape it and so the
    arithmetic below is readable as the matrix algebra it is.
    """

    #: The state, in whatever units the subject declares.
    value: float = 0.0
    rate: float = 0.0
    accel: float = 0.0

    #: Covariance, row-major and symmetric: p01 == p10 is kept once.
    p00: float = 1.0
    p01: float = 0.0
    p02: float = 0.0
    p11: float = 0.0
    p12: float = 0.0
    p22: float = 0.0

    #: Spectral density of the jerk, (value units)^2 / hour^5. See the module
    #: note: this has not been measured for any subject yet.
    jerk: float = 1e-6

    #: When the state was last advanced, unix seconds, or None before the first
    #: time it was. **None rather than 0.0**, because the sentinel for "never
    #: advanced" must not be a valid value of the field: the first version used
    #: `if self.at` and therefore read a state at unix time zero as one that had
    #: never been advanced, so `predict` returned early forever and the
    #: covariance never grew. Real timestamps are never zero, which is exactly
    #: what makes that kind of bug survive to production.
    at: float | None = None

    #: Probability the quantity exists at all, in [0, 1]. Nothing reads it yet.
    existence: float = 1.0

    #: The rate as it stood before the last measurement, and whether the rate has
    #: ever cleared two of its own standard deviations. Both are a record of what
    #: the filter did rather than inputs to it, which is what lets `turning` be
    #: asked without changing the filter by a bit.
    prev_rate: float = 0.0
    earned_rate: bool = False

    #: Measurements folded in. Not a warm-up gate - the covariance is the gate -
    #: but the number any score has to be read against.
    seen: int = field(default=0)

    #: **Accumulated Gaussian log-likelihood of the measurements seen.**
    #:
    #: This is the single most useful thing the filter produces and it was
    #: missing. Statsmodels' state-space machinery is built on the observation
    #: that *the likelihood comes as a byproduct of the Kalman filter* - each
    #: step already computes the innovation `y` and its variance `S`, and
    #: `-0.5 * (log(2*pi*S) + y^2/S)` is that step's contribution. Accumulate it
    #: and every parameter in this package stops being a placeholder and becomes
    #: a one-dimensional fit; `diagnostics.fit_jerk` is that fit.
    #:
    #: It is why `update` returns the innovation rather than nothing.
    loglike: float = 0.0

    #: Steps excluded from `loglike`, for a diffuse initialisation.
    #:
    #: The prior here is not knowledge - `p00 = 1.0` is a stand-in for "no idea"
    #: and the first measurement is taken as the state. That is an approximate
    #: diffuse initialisation, and the standard treatment is to **discard the
    #: first few likelihood terms** rather than let a prior nobody chose dominate
    #: the fit. Statsmodels calls the same thing `loglikelihood_burn` and uses 2
    #: for a local linear trend, which is one per diffuse state; this has three
    #: states and two of them are only ever observed through the first.
    burn: int = 3

    #: The most recent standardised innovation, `y / sqrt(S)`. Under a correctly
    #: specified filter this is a standard normal, which is the whole basis of
    #: the residual diagnostics in `diagnostics.py`.
    last_standardised: float = 0.0

    # ------------------------------------------------------------------ predict

    def predict(self, when: float) -> None:
        """Advance to `when`. Elapsed **time**, never a number of samples."""
        if self.at is None:
            self.at = float(when)
            return
        dt = (float(when) - self.at) / HOUR
        self.at = float(when)
        if dt <= 0.0:
            # A measurement at or before the last one is not a step backwards in
            # belief; it is the same instant. Going backwards would shrink the
            # covariance, which is the one direction a prediction may never move
            # it.
            return

        # x <- F x, with F the integrator for a constant-jerk model.
        half = 0.5 * dt * dt
        self.value = self.value + self.rate * dt + self.accel * half
        self.rate = self.rate + self.accel * dt

        # P <- F P F' + Q(dt). Written out because the symmetry is the invariant
        # worth being able to read, and three nested loops hide it.
        p00, p01, p02 = self.p00, self.p01, self.p02
        p11, p12, p22 = self.p11, self.p12, self.p22
        # F P
        a00 = p00 + dt * p01 + half * p02
        a01 = p01 + dt * p11 + half * p12
        a02 = p02 + dt * p12 + half * p22
        a11 = p11 + dt * p12
        a12 = p12 + dt * p22
        # (F P) F'
        self.p00 = a00 + dt * a01 + half * a02
        self.p01 = a01 + dt * a02
        self.p02 = a02
        self.p11 = a11 + dt * a12
        self.p12 = a12
        self.p22 = p22

        # Q(dt) for continuous white-noise jerk, integrated exactly. One
        # parameter, three rows, no freedom to set them inconsistently.
        q = max(self.jerk, 0.0)
        dt2 = dt * dt
        dt3 = dt2 * dt
        self.p00 += q * dt3 * dt2 / 20.0
        self.p01 += q * dt2 * dt2 / 8.0
        self.p02 += q * dt3 / 6.0
        self.p11 += q * dt3 / 3.0
        self.p12 += q * dt2 / 2.0
        self.p22 += q * dt

        # Belief that the quantity is still there decays with time alone.
        if self.existence > 0.0:
            self.existence *= 0.5 ** (dt / EXISTENCE_HALF_LIFE_HOURS)

    # ------------------------------------------------------------------- update

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in one noisy reading of the value. Returns the innovation.

        `noise` is the measurement variance `R`, in value units squared. The
        innovation is returned because it is the residual every scoring question
        here needs - including whether `jerk` is right, which is what
        `var(touch2 - touch1) = q*dt + 2R` fits.
        """
        if not math.isfinite(measured) or not math.isfinite(noise) or noise < 0.0:
            return 0.0
        if when is not None:
            self.predict(when)

        if not self.seen and self.p00 >= 1.0:
            # First reading: take it as the state rather than averaging it with a
            # prior nobody chose. The covariance becomes the measurement's.
            self.value = measured
            self.p00 = noise
            self.seen = 1
            self.existence = 1.0
            return 0.0

        innovation = measured - self.value
        s = self.p00 + noise
        if s <= 0.0:
            return innovation

        # The likelihood, before the state moves. Free, and it is what makes
        # `jerk` fittable rather than chosen - see `loglike`.
        self.last_standardised = innovation / math.sqrt(s)
        if self.seen >= self.burn:
            self.loglike += -0.5 * (math.log(2.0 * math.pi * s) + innovation * innovation / s)
        # Gain for H = [1, 0, 0]: K = P H' / S, one column.
        k0 = self.p00 / s
        k1 = self.p01 / s
        k2 = self.p02 / s

        self.prev_rate = self.rate
        self.value += k0 * innovation
        self.rate += k1 * innovation
        self.accel += k2 * innovation

        # P <- (I - K H) P, which touches only the first column's contribution.
        p00, p01, p02 = self.p00, self.p01, self.p02
        self.p00 = p00 - k0 * p00
        self.p01 = p01 - k0 * p01
        self.p02 = p02 - k0 * p02
        self.p11 = self.p11 - k1 * p01
        self.p12 = self.p12 - k1 * p02
        self.p22 = self.p22 - k2 * p02

        self.seen += 1
        # A measurement is evidence the quantity is there. Bounded at one; an
        # existence probability above one is not a stronger belief, it is a bug.
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)
        if self.rate_confident:
            self.earned_rate = True
        return innovation

    # ------------------------------------------------- what a smoother needs

    #: Components, in the order `state` and `covariance` report them.
    NAMES: tuple[str, ...] = ("value", "rate", "accel")

    def state(self) -> tuple[float, ...]:
        """The state vector, in `NAMES` order."""
        return (self.value, self.rate, self.accel)

    def covariance(self) -> tuple[tuple[float, ...], ...]:
        """The full covariance, dense and symmetric.

        Dense rather than the six floats it is stored as, because a smoother
        should not have to know how a member packs its upper triangle - and the
        cost is nine floats on a structure that already holds a market.
        """
        return (
            (self.p00, self.p01, self.p02),
            (self.p01, self.p11, self.p12),
            (self.p02, self.p12, self.p22),
        )

    def transition(self, dt: float) -> tuple[tuple[float, ...], ...]:
        """`F(dt)`, the integrator for a constant-jerk model.

        **The reason a factory alone cannot smooth a member.** The
        Rauch-Tung-Striebel gain is `P_t F' P_{t+1|t}^-1`, so a smoother needs
        the transition and not only the ability to run the filter. A member that
        cannot state its own `F` cannot be smoothed, which is a true thing to
        say about it rather than a limitation of the smoother.
        """
        half = 0.5 * dt * dt
        return (
            (1.0, dt, half),
            (0.0, 1.0, dt),
            (0.0, 0.0, 1.0),
        )

    # ---------------------------------------------------------------- readings

    @property
    def sd(self) -> float:
        return math.sqrt(max(self.p00, 0.0))

    @property
    def sd_rate(self) -> float:
        return math.sqrt(max(self.p11, 0.0))

    @property
    def sd_accel(self) -> float:
        return math.sqrt(max(self.p22, 0.0))

    @property
    def rate_confident(self) -> bool:
        """The rate is more than two of its own standard deviations from zero.

        Zero variance reads as *no information*, not as certainty - the mistake
        `Kalman.var_slope` documents and the reason this is not `abs(rate) > 0`.
        """
        return self.p11 > 0.0 and abs(self.rate) > 2.0 * self.sd_rate

    @property
    def turning(self) -> bool:
        """The rate has changed sign since the last measurement, having earned one.

        Both halves matter: a quantity that never earned a rate has not turned,
        it has never been going anywhere.
        """
        return self.earned_rate and (self.prev_rate * self.rate) < 0.0

    @property
    def accel_confident(self) -> bool:
        return self.p22 > 0.0 and abs(self.accel) > 2.0 * self.sd_accel

    def at_time(self, when: float) -> float:
        """Where the value will be at `when`, by this model's own belief.

        The projection the chart draws. It is the current state carried forward,
        not a record of where the quantity was - and the further `when` is from
        `at`, the more of the answer is `jerk`, which is unmeasured.
        """
        dt = 0.0 if self.at is None else (float(when) - self.at) / HOUR
        return self.value + self.rate * dt + 0.5 * self.accel * dt * dt

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        """The interval the value is expected in at `when`, as `(low, high)`.

        Unlike the published zone this **does** widen with elapsed time, because
        the covariance it reads from has been advanced. That makes it the honest
        version and the untrustworthy one at the same time, for the same reason:
        the widening rate is `jerk`.
        """
        dt = 0.0 if self.at is None else (float(when) - self.at) / HOUR
        var = self.p00
        if dt > 0:
            half = 0.5 * dt * dt
            var = (
                self.p00
                + 2.0 * dt * self.p01
                + 2.0 * half * self.p02
                + dt * dt * self.p11
                + 2.0 * dt * half * self.p12
                + half * half * self.p22
                + max(self.jerk, 0.0) * (dt**5) / 20.0
            )
        spread = sigmas * math.sqrt(max(var, 0.0))
        middle = self.at_time(when)
        return middle - spread, middle + spread
