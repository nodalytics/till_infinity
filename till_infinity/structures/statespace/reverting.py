"""A rate that pulls back instead of running away. Improvement I3, measured.

`linear.Gaussian` is a triple integrator driven by white jerk, and its poles all
sit at the origin: the rate random-walks forever, so a level's drift never
decays and over a long gap its variance grows as `dt^5`. That is what I3 means
by *marginally stable*, and the horizon cap in production is the patch for it.

This is the stable alternative. The rate is an Ornstein-Uhlenbeck process pulled
toward zero at `theta` per hour, and the value is its integral:

    d(value) = rate dt
    d(rate)  = -theta * rate dt + sigma dW

A level still drifts, and the drift dies out. Two states rather than three:
a reverting rate already supplies the curvature that `linear`'s acceleration
state was there to provide, and whether a *third* reverting state earns anything
is I5's question, asked separately.

## Why it exists: it was measured before it was written

On eurusd 4h, 1,073 bars in volatility units with `R = TOUCH_NOISE_VOL^2`,
fitted on the first half and scored on the second - held out, because this model
has one more parameter and in-sample fit would reward it for that alone:

| | white jerk | reverting rate |
| --- | ---: | ---: |
| held-out log-likelihood | -1453.26 | **-941.93** |
| innovation sd (1.0 is honest) | 1.294 | **0.985** |
| Ljung-Box p | 5.96e-27 | **1.22e-04** |
| Jarque-Bera p | 9.18e-89 | 8.83e-183 |

Both arms scored over the same 534 points with none skipped, which had to be
checked rather than assumed: the first version of that comparison reported the
reverting model winning by 1,400, and it was winning by having quietly stopped
scoring when its covariance went non-positive. A likelihood over fewer
observations is not a smaller number, it is a different quantity.

**It fixes the over-confidence completely** - 1.294 to 0.985 - and takes the
innovation autocorrelation down twenty-three orders of magnitude. It does not
fix it: `p = 1.22e-04` is still autocorrelated, so structure remains that a
reverting rate does not capture, which is I8's question rather than another
dynamics tweak.

**And it makes the tails worse, which is a reveal rather than a regression.**
Jarque-Bera goes from 9e-89 to 9e-183: once the dynamics stop absorbing large
moves into a runaway drift, those moves surface as outliers instead. So
`robust.py` - a `PY` change where this is a `PX` change - is the right *next*
step and has a far better case after this than before it.

## What `theta` came out as, and why it is interesting

**0.5 per hour**, a reversion half-life of 1.39 hours. On a 4h series the rate
retains `exp(-0.5 * 4) = 0.135` of itself across one bar, so the drift decays
86% per bar. The best-fitting model of a level's drift is one in which that
drift is very nearly noise - which is where every other result on this desk that
has survived a control has landed: magnitude is predictable and direction is
not.

## Everything here is measured on closes, not touches

A bar close is not a touch. The close moves because price moved; a level is not
supposed to. So the comparison above establishes the *direction* - a stable rate
beats a random-walking one - and sets none of the constants. `theta` for a level
needs the raw touch price the outcomes journal does not record.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .linear import EXISTENCE_HALF_LIFE_HOURS, HOUR

#: Below this `theta * dt`, the exact expression for the value's process
#: variance cancels to nothing and is computed from its series instead.
#:
#: **The cancellation is not subtle.** The exact form carries
#: `dt - 2(1 - e^-u)/theta + (1 - e^-2u)/(2 theta)`, whose first two orders in
#: `u` cancel identically - the answer is `u^3/3` and the terms are `O(u)`. At
#: `u = 1e-4` that is eight significant figures lost before the result begins.
SMALL = 1e-3


def _process(dt: float, sigma2: float, theta: float) -> tuple[float, float, float]:
    """`Q(dt)` for the integrated Ornstein-Uhlenbeck, as `(q00, q01, q11)`.

    Exact, from the integrated-OU covariance, with `expm1` where the expression
    would otherwise subtract two nearly-equal numbers and a series where the
    leading orders cancel outright. As `theta` goes to zero these reduce to the
    white-acceleration terms `sigma2 * dt^3/3`, `dt^2/2` and `dt` - which is the
    check `tests/test_statespace.py` makes, because a discretisation that is
    wrong only in the limit is wrong where it matters most: a long gap.
    """
    if dt <= 0.0 or sigma2 <= 0.0:
        return 0.0, 0.0, 0.0
    if theta <= 0.0:
        # No reversion at all: integrated Brownian motion on the rate.
        return sigma2 * dt**3 / 3.0, sigma2 * dt * dt / 2.0, sigma2 * dt

    u = theta * dt
    one_minus_a = -math.expm1(-u)  # 1 - e^-u, exactly
    q11 = sigma2 / (2.0 * theta) * -math.expm1(-2.0 * u)
    q01 = sigma2 / (2.0 * theta * theta) * one_minus_a * one_minus_a

    if u < SMALL:
        # g(u) = u - 2(1 - e^-u) + (1 - e^-2u)/2 = u^3/3 - u^4/4 + 7u^5/60 - ...
        g = u**3 / 3.0 - u**4 / 4.0 + 7.0 * u**5 / 60.0
    else:
        g = u - 2.0 * one_minus_a + 0.5 * -math.expm1(-2.0 * u)
    q00 = sigma2 / (theta**3) * g
    return q00, q01, q11


@dataclass(slots=True)
class Reverting:
    """`(value, rate)` where the rate reverts to zero. Stable for `theta > 0`.

    The same interface as `linear.Gaussian` - it satisfies `family.Filter` - so
    the two can be scored against each other on identical measurements, which is
    the only reason to write a second member at all.
    """

    value: float = 0.0
    rate: float = 0.0

    #: Covariance of `(value, rate)`, symmetric, held as three floats.
    p00: float = 1.0
    p01: float = 0.0
    p11: float = 0.0

    #: Spectral density of the rate's driving noise, (value units)^2 / hour^3.
    sigma2: float = 1e-3
    #: Reversion rate, per hour. The half-life is `ln 2 / theta`. **Not
    #: measured for any subject**: 0.5 fitted best on eurusd 4h *closes*, and a
    #: close is not a touch.
    theta: float = 0.5

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
        """Advance to `when`, in elapsed time rather than samples."""
        if self.at is None:
            self.at = float(when)
            return
        dt = (float(when) - self.at) / HOUR
        self.at = float(when)
        if dt <= 0.0:
            return

        theta = max(self.theta, 0.0)
        if theta > 0.0:
            decay = math.exp(-theta * dt)
            carry = -math.expm1(-theta * dt) / theta  # (1 - e^-u) / theta
        else:
            decay, carry = 1.0, dt

        # x <- F x
        self.value = self.value + carry * self.rate
        self.rate = decay * self.rate

        # P <- F P F' + Q, with F = [[1, carry], [0, decay]].
        p00, p01, p11 = self.p00, self.p01, self.p11
        new00 = p00 + 2.0 * carry * p01 + carry * carry * p11
        new01 = decay * (p01 + carry * p11)
        new11 = decay * decay * p11

        q00, q01, q11 = _process(dt, max(self.sigma2, 0.0), theta)
        self.p00 = new00 + q00
        self.p01 = new01 + q01
        self.p11 = new11 + q11

        if self.existence > 0.0:
            self.existence *= 0.5 ** (dt / EXISTENCE_HALF_LIFE_HOURS)

    # ------------------------------------------------------------------- update

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in one noisy reading of the value. Returns the innovation."""
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

    # ---------------------------------------------------------------- readings

    @property
    def accel(self) -> float:
        """There is no acceleration state. Reported as the rate's own pull.

        `-theta * rate` is where the rate is heading, which is the nearest
        honest answer and is **not** a third state: a consumer that needs the
        acceleration's own uncertainty needs `linear.Gaussian` or I5's question
        answered first.
        """
        return -max(self.theta, 0.0) * self.rate

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
    def half_life_hours(self) -> float:
        """Hours for the rate to decay by half. Infinite without reversion.

        The number that says what this model is claiming: at 1.39 hours a 4h bar
        retains 13.5% of its drift, which is a model of a level whose drift is
        very nearly noise.
        """
        return math.log(2.0) / self.theta if self.theta > 0 else math.inf

    def at_time(self, when: float) -> float:
        """Where the value is heading, by this model's belief.

        **Bounded, unlike `linear`'s.** A reverting rate contributes at most
        `rate / theta` however far ahead you ask, so the projection converges
        instead of running away - which is the whole point of I3 and is what
        makes a horizon cap unnecessary rather than merely unused.
        """
        if self.at is None:
            return self.value
        dt = (float(when) - self.at) / HOUR
        if dt <= 0.0:
            return self.value
        theta = max(self.theta, 0.0)
        carry = -math.expm1(-theta * dt) / theta if theta > 0 else dt
        return self.value + carry * self.rate

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        """The interval the value is expected in at `when`."""
        var = self.p00
        if self.at is not None:
            dt = (float(when) - self.at) / HOUR
            if dt > 0:
                theta = max(self.theta, 0.0)
                carry = -math.expm1(-theta * dt) / theta if theta > 0 else dt
                q00, _q01, _q11 = _process(dt, max(self.sigma2, 0.0), theta)
                var = self.p00 + 2.0 * carry * self.p01 + carry * carry * self.p11 + q00
        spread = sigmas * math.sqrt(max(var, 0.0))
        middle = self.at_time(when)
        return middle - spread, middle + spread
