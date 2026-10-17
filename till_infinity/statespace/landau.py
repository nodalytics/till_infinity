"""A rate whose reversion stiffens with its own size. The Landau cubic.

`reverting.py` pulls the rate toward zero at a constant `theta` per hour, so
the restoring force is linear in the rate and the rate's stationary
distribution is a single bell centred on no drift. This member replaces that
force with the next odd term:

    d(value) = rate dt
    d(rate)  = -(theta * rate + kappa * rate^3) dt + sigma dW

`kappa > 0` makes the pull *stiffen* with the trend - a big drift is dragged
back harder than linearly - and `theta < 0` with `kappa > 0` makes the origin
**unstable** and plants two stable drifts at `+/- sqrt(-theta/kappa)`. One
member covers both, and which one the data wants is a fitted sign rather than
a modelling choice.

## Where the shape comes from, and the number it has to beat

Schmidhuber's lattice-gas renormalisation-group model of a market gives the
trend a Landau free energy, whose derivative is the drift on returns:

    V(phi) = b~ phi^2 / 2 - c~ phi^4 / 4 + ...    =>    R = a + b phi + c phi^3

That is this member's rate equation with `b = -theta` and `c = -kappa`, which
is the reason to write it: the regression has been run on real markets and
**reported with error bars** - `b = 1.29% +/- 0.43%`, `c = -0.62% +/- 0.23%`
daily, and `b = +0.132% +/- 0.046%`, `c = -0.039% +/- 0.014%` intraday. Almost
nothing else in the reading pile quotes an uncertainty, so this is the one
claim that can be *replicated* rather than merely re-found.

The published signs say `b > 0` and `c < 0`: the origin repels and the cubic
stabilises. In this member's parameters that is `theta < 0, kappa > 0` - the
double well - and it predicts something a linear member cannot produce,
**a bimodal trend**, with modes at `+/- sqrt(-theta/kappa)`. From the daily
coefficients that is `+/- sqrt(1.29/0.62) = +/- 1.44` in whatever units `phi`
was rescaled to.

`research/ideas/landau_cubic.py` runs both tests - the regression as published
and this member against `Reverting`, which is the same model with `kappa = 0`
and therefore a one-parameter likelihood-ratio test rather than a fight
between two collinear regressors. `research/docs/statespace-landau.md` has
what came back.

## Why the mean is exact and only the covariance is linearised

The usual objection to a non-linear member is that the filter becomes
approximate everywhere. Here it does not have to: `dr/dt = -theta r - kappa
r^3` has a closed-form solution. Substituting `u = r^2` gives

    du/dt = -2 theta u - 2 kappa u^2

which is logistic, so with `a = 2 theta` and `b = 2 kappa`,

    u(t) = u0 / (e^{a t} + b u0 (e^{a t} - 1) / a)

and `r(t) = sign(r0) sqrt(u(t))`. The rate's mean is propagated through that
expression, not through a tangent, so no linearisation error enters it at any
step size - including the long gaps where an extended filter is usually worst.
The `(e^{at} - 1)/a` factor is `expm1(a t) / a`, which tends to `t`, so the
same line covers `theta = 0` (pure cubic decay, `u0 / (1 + 2 kappa u0 t)`) and
`theta < 0` (growth toward the well) without a branch.

The **covariance** is linearised, because that is unavoidable: the Jacobian of
the flow is

    d(dr)/dr = -(theta + 3 kappa r^2)

so the covariance is advanced with `reverting`'s exact integrated-OU terms at
the *local* reversion rate `theta + 3 kappa r^2`, evaluated at the midpoint of
the step. That is the honest description of this member: an exact mean and a
first-order covariance, which is what makes `kappa = 0` reduce to `Reverting`
bit-for-bit and is the test that guards it.

The value's integral `int r dt` is **also** closed - substituting `w = e^{a t}`
reduces it to `int dw / (w sqrt(A w + B))`, a logarithm in the double well and
an arctangent outside it. So the whole mean propagation is exact and there is
no quadrature anywhere in this member. The first version of it substepped
Simpson's rule, which cost nine transcendentals a step to land 2e-3 from the
answer; the closed form costs four and lands 4e-12 from it.

## What it is not

Not a two-regime model. `switching.py` already mixes two linear members and
would fit a trending and a reverting state as separate hypotheses; this is one
member whose single rate equation produces both behaviours depending on how
large the rate currently is. The difference is testable and the harness tests
it: a double well predicts the *transition* through zero to be fast and the
time spent near a mode to be long, where a switching model predicts dwell
times set by its transition matrix and nothing about the rate's magnitude.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .linear import EXISTENCE_HALF_LIFE_HOURS, HOUR
from .reverting import _process

#: Below this `|a t|`, `expm1(a t) / a` is taken as `t`. The ratio is well
#: conditioned - `expm1` is exact for small arguments - but `a` itself can be
#: zero, and a branch on `a == 0` alone would leave a discontinuity nearby.
SMALL = 1e-8

#: Below this `|A|`, the rate is sitting in a well to within floating point and
#: the travel integral is `rate * dt`. `A = 1 + kappa r^2 / theta` vanishes
#: exactly when `theta = -kappa r^2`, which *is* the well condition - so this
#: is not a numerical fudge, it is the stationary case appearing as a zero.
FLAT = 1e-14

#: `|a t|` above which `e^{a t}` overflows a float. Both branches have a limit
#: there - the rate is zero, and the travel integral has converged.
HUGE = 700.0


def _flow(rate: float, dt: float, theta: float, kappa: float) -> float:
    """The rate after `dt` hours of `dr/dt = -(theta r + kappa r^3)`. Exact.

    Closed form via `u = r^2`, which turns the cubic into a logistic equation.
    Handles `theta` of either sign and zero on the same line, because the only
    `theta`-dependent factor is `expm1(a t) / a`.
    """
    if dt <= 0.0 or rate == 0.0:
        return rate
    if kappa == 0.0:
        return rate * math.exp(-theta * dt)

    a = 2.0 * theta
    u0 = rate * rate
    at = a * dt
    if at > HUGE:  # e^{at} overflows and u is zero to every bit anyway
        return 0.0
    ratio = dt if abs(at) < SMALL else math.expm1(at) / a
    denominator = math.exp(at) + 2.0 * kappa * u0 * ratio
    if denominator <= 0.0:
        # Only reachable with kappa < 0, where the cubic drives the rate to
        # infinity in finite time. Report the blow-up rather than a sign flip.
        return math.inf if rate > 0.0 else -math.inf
    u = u0 / denominator
    return math.copysign(math.sqrt(u), rate)


def _travel(rate: float, dt: float, theta: float, kappa: float) -> float:
    """`int_0^dt r(s) ds` for the cubic flow. Exact, in closed form.

    The rate's own solution is `r = sign(r0) sqrt(u0 / D(t))` with
    `D(t) = A e^{a t} + B`, `a = 2 theta`, `c = 2 kappa r0^2`, `A = 1 + c/a`
    and `B = -c/a` - so `A + B = 1`, which is `D(0) = 1`. Substituting
    `w = e^{a t}` turns the integral into

        int dw / (w sqrt(A w + B)) / a

    a standard form with a logarithm for `B > 0` and an arctangent for `B < 0`.

    **The logarithm is rearranged before it is evaluated.** Written as
    `ln|(y - sqrt B)/(y + sqrt B)|` it subtracts two nearly-equal numbers
    exactly where the answer matters most - `B > 0` is the double well, where
    `y -> sqrt B` as the rate settles into a mode. Multiplying through by the
    conjugate gives `ln|A w| - 2 ln(y + sqrt B)`, and the `w` cancels against
    the other limit, leaving

        (a t + 2 ln((1 + sqrt B) / (y + sqrt B))) / (a sqrt B)

    whose first term carries the linear growth and whose second is bounded. The
    divergence is real - a rate held at a well travels forever - and this form
    expresses it without ever cancelling a float against itself.

    Verified against Simpson's rule at 400,000 panels to 4e-12 relative or
    better on eleven cases: both signs of `theta`, `theta` at zero and at
    1e-12, either sign of the rate, a rate placed exactly in a well, and `dt`
    from 0.001 to 200 hours.
    """
    if dt <= 0.0 or rate == 0.0:
        return 0.0
    if kappa == 0.0:
        if theta == 0.0:
            return rate * dt
        # Parenthesised to divide before multiplying, which is the order
        # `Reverting.predict` uses. Without the brackets this rounds
        # differently in the last bit and the two members stop being
        # bit-identical at `kappa = 0` - which is a test, not a nicety.
        return rate * (-math.expm1(-theta * dt) / theta)

    sign = math.copysign(1.0, rate)
    u0 = rate * rate
    c = 2.0 * kappa * u0
    a = 2.0 * theta
    at = a * dt

    if abs(at) < SMALL:
        # theta is zero to floating point: D(t) = 1 + c t, elementary.
        inner = 1.0 + c * dt
        if inner <= 0.0:
            return math.copysign(math.inf, rate)
        return sign * math.sqrt(u0) * 2.0 * (math.sqrt(inner) - 1.0) / c

    big_a = 1.0 + c / a
    big_b = -c / a
    if abs(big_a) < FLAT:
        # theta = -kappa r^2 exactly: the rate is stationary, so is the travel.
        return rate * dt

    if at > HUGE:
        edge = math.inf
    else:
        denominator = big_a * math.exp(at) + big_b
        if denominator <= 0.0:
            # kappa < 0 drives the rate to infinity in finite time.
            return math.copysign(math.inf, rate)
        edge = math.sqrt(denominator)

    if big_b > 0.0:
        root = math.sqrt(big_b)
        integral = (at + 2.0 * math.log((1.0 + root) / (edge + root))) / (a * root)
    else:
        root = math.sqrt(-big_b)
        far = math.pi / 2.0 if edge == math.inf else math.atan(edge / root)
        integral = 2.0 * (far - math.atan(1.0 / root)) / (a * root)
    return sign * math.sqrt(u0) * integral


@dataclass(slots=True)
class Landau:
    """`(value, rate)` with a cubic restoring force on the rate.

    Satisfies `family.Filter`, so it scores against `linear.Gaussian` and
    `reverting.Reverting` on identical measurements. With `kappa = 0` it *is*
    `Reverting` - the same state, the same covariance, the same likelihood -
    which is what makes the comparison a nested one-parameter test.
    """

    value: float = 0.0
    rate: float = 0.0

    #: Covariance of `(value, rate)`, symmetric, held as three floats.
    p00: float = 1.0
    p01: float = 0.0
    p11: float = 0.0

    #: Spectral density of the rate's driving noise, (value units)^2 / hour^3.
    sigma2: float = 1e-3
    #: Linear part of the restoring force, per hour. **Positive reverts toward
    #: zero; negative makes zero unstable** and the two wells appear. Not
    #: measured for any subject - `reverting`'s 0.5 is a starting point and was
    #: fitted on closes.
    theta: float = 0.5
    #: Cubic part, per hour per (value units / hour)^2. Zero is `Reverting`.
    kappa: float = 0.0

    at: float | None = None
    existence: float = 1.0
    prev_rate: float = 0.0
    earned_rate: bool = False
    seen: int = 0

    loglike: float = 0.0
    burn: int = 2
    last_standardised: float = 0.0

    # ------------------------------------------------------------------ predict

    def predict(self, when: float) -> None:
        """Advance to `when`. Exact mean, linearised covariance."""
        if self.at is None:
            self.at = float(when)
            return
        dt = (float(when) - self.at) / HOUR
        self.at = float(when)
        if dt <= 0.0:
            return

        theta, kappa = self.theta, self.kappa
        travelled = _travel(self.rate, dt, theta, kappa)
        moved = _flow(self.rate, dt, theta, kappa)
        if not math.isfinite(moved) or not math.isfinite(travelled):
            # A blown-up cubic. Freeze the mean and let the covariance grow;
            # the likelihood will say what it thinks of the parameters.
            moved, travelled = self.rate, self.rate * dt

        # The local reversion rate, at the step's midpoint rather than its
        # start: the flow is non-linear, and taking the Jacobian where the
        # state begins overstates the stiffness of a step that decays.
        middle = _flow(self.rate, dt * 0.5, theta, kappa)
        if not math.isfinite(middle):
            middle = self.rate
        local = theta + 3.0 * kappa * middle * middle

        # One branch for either sign: `exp` and `expm1` are both correct for a
        # negative `local`, where the tangent *grows* - which is the right
        # covariance for a rate currently being pushed away from zero. Only
        # `local == 0` needs the limit, because the carry term divides by it.
        if local != 0.0:
            decay = math.exp(-local * dt)
            carry = -math.expm1(-local * dt) / local
        else:
            decay, carry = 1.0, dt

        self.value = self.value + travelled
        self.rate = moved

        p00, p01, p11 = self.p00, self.p01, self.p11
        new00 = p00 + 2.0 * carry * p01 + carry * carry * p11
        new01 = decay * (p01 + carry * p11)
        new11 = decay * decay * p11

        q00, q01, q11 = _process(dt, max(self.sigma2, 0.0), max(local, 0.0))
        self.p00 = new00 + q00
        self.p01 = new01 + q01
        self.p11 = new11 + q11

        if self.existence > 0.0:
            self.existence *= 0.5 ** (dt / EXISTENCE_HALF_LIFE_HOURS)

    # ------------------------------------------------------------------- update

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in one noisy reading of the value. Returns the innovation.

        `noise` is the measurement **variance**, as everywhere else in this
        package - the convention that `seasonal` and `symmetry` broke by
        squaring it, which reversed a published result before it was caught.
        """
        if not math.isfinite(measured) or not math.isfinite(noise) or noise < 0.0:
            return 0.0
        if when is not None:
            self.predict(when)

        if not self.seen and self.p00 >= 1.0:
            self.value = measured
            self.p00 = noise
            self.seen = 1
            self.existence = 1.0
            return 0.0

        innovation = measured - self.value
        s = self.p00 + noise
        if s <= 0.0:
            return innovation

        self.last_standardised = innovation / math.sqrt(s)
        if self.seen >= self.burn:
            self.loglike += -0.5 * (math.log(2.0 * math.pi * s) + innovation * innovation / s)

        k0 = self.p00 / s
        k1 = self.p01 / s
        self.prev_rate = self.rate
        self.value += k0 * innovation
        self.rate += k1 * innovation

        p00, p01 = self.p00, self.p01
        self.p00 = p00 - k0 * p00
        self.p01 = p01 - k0 * p01
        self.p11 = self.p11 - k1 * p01

        self.seen += 1
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)
        if self.rate_confident:
            self.earned_rate = True
        return innovation

    # ------------------------------------------------- what a smoother needs

    NAMES: tuple[str, ...] = ("value", "rate")
    OUTPUTS: tuple[str, ...] = ("value",)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return ((1.0, 0.0),)

    def output(self) -> tuple[float, ...]:
        state = self.state()
        return tuple(
            sum(c * x for c, x in zip(row, state, strict=True)) for row in self.observation()
        )

    def state(self) -> tuple[float, ...]:
        return (self.value, self.rate)

    def covariance(self) -> tuple[tuple[float, ...], ...]:
        return ((self.p00, self.p01), (self.p01, self.p11))

    def transition(self, dt: float) -> tuple[tuple[float, ...], ...]:
        """`F(dt)`, the Jacobian of the flow at the current rate.

        **This is a linearisation and the rest of the member is not.** A
        smoother needs a matrix, so it gets the tangent; `predict` does not use
        this, it uses the closed form. The two agree exactly when `kappa` is
        zero, and a smoother run over a strongly non-linear fit is reading an
        approximation that `predict` never made.
        """
        local = self.theta + 3.0 * self.kappa * self.rate * self.rate
        if local != 0.0:
            decay = math.exp(-local * dt)
            carry = -math.expm1(-local * dt) / local
        else:
            decay, carry = 1.0, dt
        return ((1.0, carry), (0.0, decay))

    # ---------------------------------------------------------------- readings

    @property
    def accel(self) -> float:
        """The rate's own pull, `-(theta r + kappa r^3)`. Not a third state."""
        return -(self.theta * self.rate + self.kappa * self.rate**3)

    @property
    def sd(self) -> float:
        return math.sqrt(max(self.p00, 0.0))

    @property
    def sd_rate(self) -> float:
        return math.sqrt(max(self.p11, 0.0))

    @property
    def rate_confident(self) -> bool:
        return self.p11 > 0.0 and abs(self.rate) > 2.0 * self.sd_rate

    @property
    def turning(self) -> bool:
        return self.earned_rate and (self.prev_rate * self.rate) < 0.0

    @property
    def wells(self) -> tuple[float, float] | None:
        """The two stable drifts, or `None` when the origin is the only one.

        `+/- sqrt(-theta/kappa)` exists only for `theta < 0 < kappa`, which is
        the sign pattern the renormalisation-group regression reports. **This
        property is the member's falsifiable claim**: if it returns a pair, the
        rate's unconditional distribution should have two modes there, and that
        is checkable without reference to any likelihood.
        """
        if self.theta >= 0.0 or self.kappa <= 0.0:
            return None
        edge = math.sqrt(-self.theta / self.kappa)
        return -edge, edge

    @property
    def stiffness(self) -> float:
        """The local reversion rate, `theta + 3 kappa r^2`, per hour.

        What `reverting.theta` is a constant version of. Negative means the
        rate is currently being pushed away from zero.
        """
        return self.theta + 3.0 * self.kappa * self.rate * self.rate

    @property
    def half_life_hours(self) -> float:
        """Hours for the *current* rate to halve, from the local stiffness.

        Unlike `Reverting.half_life_hours` this is a function of the state, not
        of the parameters alone - which is the whole content of the cubic term.
        """
        local = self.stiffness
        return math.log(2.0) / local if local > 0.0 else math.inf

    def at_time(self, when: float) -> float:
        """Where the value is heading. Bounded for `theta >= 0 <= kappa`."""
        if self.at is None:
            return self.value
        dt = (float(when) - self.at) / HOUR
        if dt <= 0.0:
            return self.value
        travelled = _travel(self.rate, dt, self.theta, self.kappa)
        return self.value + travelled if math.isfinite(travelled) else self.value

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        """The interval the value is expected in at `when`."""
        var = self.p00
        if self.at is not None:
            dt = (float(when) - self.at) / HOUR
            if dt > 0:
                middle = _flow(self.rate, dt * 0.5, self.theta, self.kappa)
                if not math.isfinite(middle):
                    middle = self.rate
                local = self.theta + 3.0 * self.kappa * middle * middle
                carry = -math.expm1(-local * dt) / local if local != 0.0 else dt
                q00, _q01, _q11 = _process(dt, max(self.sigma2, 0.0), max(local, 0.0))
                var = self.p00 + 2.0 * carry * self.p01 + carry * carry * self.p11 + q00
        spread = sigmas * math.sqrt(max(var, 0.0))
        middle_value = self.at_time(when)
        return middle_value - spread, middle_value + spread
