"""A damped harmonic oscillator: the member that can actually cycle.

From a set of field-equation market models reviewed on 2026-10-11, the most
directly usable of which maps price deviation onto a Klein-Gordon scalar
field and lands on

    phi'' + gamma phi' + omega^2 phi = noise

a **damped harmonic oscillator driven by noise**. That is a second-order
stochastic differential equation, which is to say a two-state state-space
model, and it is genuinely different from everything already in this family:

* `reverting` is **first order** - an Ornstein-Uhlenbeck process pulls back to
  a level and cannot overshoot it, so it cannot oscillate;
* `linear` is an **integrator chain** with no restoring force at all, so it
  cannot return to anything;
* this has both a restoring force and inertia, so it can overshoot, and
  overshoot is what a cycle is.

The difference is visible in the spectrum rather than argued about:
**underdamped, its eigenvalues are complex**, and a complex eigenvalue is an
oscillation. No other member here has one, so `spectrum.py` reads a period
from this and from nothing else.

## The damping ratio is the readout, and it is a regime label derived rather
## than asserted

    zeta = gamma / (2 omega)

* `zeta < 1` - **underdamped**: deviations oscillate about the level. The
  state a range-trader wants.
* `zeta = 1` - critically damped: the fastest return to the level with no
  overshoot.
* `zeta > 1` - **overdamped**: deviations decay slowly without crossing. The
  state that looks like a trend.

`switching.py` labels balance, imbalance and trending with three regimes and a
transition prior. This gets a *continuous* version of the same distinction out
of two fitted parameters, which is worth having beside it - and the two disagreeing
would be informative rather than embarrassing.

## The discretisation is exact, not Euler

The continuous model has a closed-form transition over any step, and using it
rather than a first-order approximation matters here more than usual: an
Euler step of an oscillator **gains energy** at each step - the discrete
system is less damped than the continuous one it approximates - so a
long-horizon forecast from an Euler oscillator grows when the real one
decays. The matrix exponential of a 2x2 companion matrix has three closed
forms by discriminant and all three are written out.

## Nothing here publishes

The null is `reverting` - the first-order version of the same idea, so the
comparison isolates exactly the inertia term - and the fitted random walk,
which has beaten everything. And the honest prior from this desk's own
record: an Ising susceptibility, a three-state HMM and a fifty-neighbour
analogue have all been tried against volatility and lost, and "the market
oscillates at a natural frequency" is a claim of the same family.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

HOUR = 3600.0

#: Natural frequency in radians per hour. `2 pi / omega` is the period, so
#: this default is a cycle of about 63 hours. **Not fitted.**
OMEGA = 0.1

#: Damping, per hour. With the default `omega` this is `zeta = 0.5`:
#: underdamped, which is the regime the member exists to represent.
GAMMA = 0.1

#: Spectral density of the forcing noise, per hour.
FORCING = 1e-3


@dataclass(slots=True)
class Oscillator:
    """`phi'' + gamma phi' + omega^2 phi = noise`, as a two-state filter.

    The state is `(deviation, its rate)` and the observation is the deviation,
    which the caller supplies already detrended - this member models the
    *deviation from* a level, not the level, and handing it a price would be
    asking a bounded process to track an unbounded one.
    """

    omega: float = OMEGA
    gamma: float = GAMMA
    forcing: float = FORCING

    deviation: float = 0.0
    speed: float = 0.0

    p00: float = 1.0
    p01: float = 0.0
    p11: float = 1.0

    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    burn: int = 10
    existence: float = 1.0
    last_standardised: float = 0.0

    NAMES = ("deviation", "speed")
    OUTPUTS = ("deviation",)

    # ------------------------------------------------------------- the reading

    @property
    def value(self) -> float:
        return self.deviation

    @property
    def rate(self) -> float:
        return self.speed

    @property
    def zeta(self) -> float:
        """The damping ratio. Below one the market oscillates; above, it drifts."""
        return self.gamma / (2.0 * self.omega) if self.omega > 0 else math.inf

    @property
    def period(self) -> float:
        """The **damped** period in hours, or `inf` when not oscillating.

        The damped frequency is `omega sqrt(1 - zeta^2)`, not `omega`.
        Quoting the undamped period for a damped system overstates the
        frequency, and for `zeta` near one it overstates it by a lot.
        """
        ratio = self.zeta
        if ratio >= 1.0 or self.omega <= 0:
            return math.inf
        return 2.0 * math.pi / (self.omega * math.sqrt(1.0 - ratio * ratio))

    @property
    def sd(self) -> float:
        return math.sqrt(max(self.p00, 0.0))

    def state(self) -> tuple[float, ...]:
        return (self.deviation, self.speed)

    def output(self) -> tuple[float, ...]:
        return (self.deviation,)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return ((1.0, 0.0),)

    def transition(self, dt_hours: float) -> tuple[tuple[float, ...], ...]:
        """`exp(A dt)` for the companion matrix, in closed form.

        Three cases by discriminant, and all three are written because an
        Euler step of an oscillator **gains energy**: the discrete system is
        less damped than the continuous one, so a long forecast grows where
        the real process decays.
        """
        dt = max(float(dt_hours), 0.0)
        if dt <= 0.0:
            return ((1.0, 0.0), (0.0, 1.0))
        half = self.gamma / 2.0
        decay = math.exp(-half * dt)
        discriminant = half * half - self.omega * self.omega
        if abs(discriminant) < 1e-12:
            # Critically damped: the repeated-root form.
            return (
                (decay * (1.0 + half * dt), decay * dt),
                (-decay * self.omega * self.omega * dt, decay * (1.0 - half * dt)),
            )
        if discriminant < 0.0:
            # Underdamped: a genuine oscillation.
            w = math.sqrt(-discriminant)
            cos, sin = math.cos(w * dt), math.sin(w * dt)
            return (
                (decay * (cos + half * sin / w), decay * sin / w),
                (
                    -decay * self.omega * self.omega * sin / w,
                    decay * (cos - half * sin / w),
                ),
            )
        # Overdamped: two real roots.
        r = math.sqrt(discriminant)
        cosh, sinh = math.cosh(r * dt), math.sinh(r * dt)
        return (
            (decay * (cosh + half * sinh / r), decay * sinh / r),
            (
                -decay * self.omega * self.omega * sinh / r,
                decay * (cosh - half * sinh / r),
            ),
        )

    def covariance(self) -> tuple[tuple[float, ...], ...]:
        return ((self.p00, self.p01), (self.p01, self.p11))

    def at_time(self, when: float) -> float:
        """The deviation carried forward by the oscillator's own dynamics.

        **This is where it differs from every other member.** Underdamped, the
        forecast *crosses zero and comes back* - it does not decay
        monotonically, because the state has inertia. A first-order member
        cannot produce that shape at any parameters.
        """
        elapsed = 0.0
        if self.at is not None:
            elapsed = max((float(when) - self.at) / HOUR, 0.0)
        f = self.transition(elapsed)
        return f[0][0] * self.deviation + f[0][1] * self.speed

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        elapsed = 0.0
        if self.at is not None:
            elapsed = max((float(when) - self.at) / HOUR, 0.0)
        f = self.transition(elapsed)
        variance = (
            f[0][0] * f[0][0] * self.p00
            + 2.0 * f[0][0] * f[0][1] * self.p01
            + f[0][1] * f[0][1] * self.p11
            + self.forcing * elapsed
        )
        middle = self.at_time(when)
        half = sigmas * math.sqrt(max(variance, 0.0))
        return (middle - half, middle + half)

    # ------------------------------------------------------------- the filter

    def predict(self, when: float, control: float = 0.0) -> None:  # noqa: ARG002
        if self.at is None:
            self.at = float(when)
            return
        dt = (float(when) - self.at) / HOUR
        self.at = float(when)
        if dt <= 0.0:
            return
        f = self.transition(dt)
        deviation = f[0][0] * self.deviation + f[0][1] * self.speed
        speed = f[1][0] * self.deviation + f[1][1] * self.speed
        p00, p01, p11 = self.p00, self.p01, self.p11
        # P <- F P F' + Q, with Q driving the *rate* only: the forcing enters
        # the second-order equation, so it accelerates rather than displaces.
        self.p00 = f[0][0] * f[0][0] * p00 + 2.0 * f[0][0] * f[0][1] * p01 + f[0][1] * f[0][1] * p11
        self.p01 = (
            f[0][0] * f[1][0] * p00
            + (f[0][0] * f[1][1] + f[0][1] * f[1][0]) * p01
            + f[0][1] * f[1][1] * p11
        )
        self.p11 = (
            f[1][0] * f[1][0] * p00
            + 2.0 * f[1][0] * f[1][1] * p01
            + f[1][1] * f[1][1] * p11
            + self.forcing * dt
        )
        self.deviation, self.speed = deviation, speed

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        if when is not None and self.at is None:
            self.at = float(when)
        if self.seen == 0:
            self.deviation = measured
            self.p00 = max(noise, 1e-12)
            self.seen = 1
            self.existence = 1.0
            return 0.0

        innovation = measured - self.deviation
        s = self.p00 + max(noise, 0.0)
        if s <= 0.0:
            return innovation
        self.last_standardised = innovation / math.sqrt(s)
        if self.seen >= self.burn:
            self.loglike += -0.5 * (math.log(2.0 * math.pi * s) + innovation * innovation / s)
        k0 = self.p00 / s
        k1 = self.p01 / s
        self.deviation += k0 * innovation
        self.speed += k1 * innovation
        p00, p01 = self.p00, self.p01
        self.p00 = p00 - k0 * p00
        self.p01 = p01 - k0 * p01
        self.p11 = self.p11 - k1 * p01
        self.seen += 1
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)
        return innovation
