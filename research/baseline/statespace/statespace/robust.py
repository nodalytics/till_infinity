"""The same model, with an update that does not believe every measurement.

A Kalman update is optimal when the measurement noise is Gaussian, and it is
*maximally wrong* when it is not: the gain is linear in the innovation, so one
reading ten standard deviations out moves the state ten times as far as one that
is one out. On this desk that is not hypothetical. A touch resolving against a
stale venue quote, a synthetic jumping, a rounded-to-zero FX bar - the tails are
real, and `vol/vol-particle.md` found the non-Gaussianity in volatility large
enough that a particle filter beat the linearisation on three of four series.

**This is the cheap arm for that.** Not a different model - the same linear
state, the same `Q(dt)`, the same readings - with the gain rolled off once the
innovation is large against what the filter expected. If a robust update earns
nothing over `linear.Gaussian`, the heavy tails are not where the error is, and
that answer costs one module instead of a particle filter.

## What it does, precisely

The innovation `y = measured - value` has predicted variance `S = P00 + R`. In
Gaussian country `|y|/sqrt(S)` is a standard normal, so values past about two are
rare and values past four are not supposed to happen. Rather than reject those -
a rejected measurement is information thrown away, and on a level it is often the
*interesting* one - the measurement's variance is **inflated** by how surprising
it is:

    R' = R * (|y| / (k * sqrt(S)))    when |y| > k * sqrt(S)

which is Huber's idea applied to the gain. Inside the gate nothing changes at
all. Outside it the gain falls as `1/sigma` while the innovation grows as
`sigma`, so the **movement is bounded**: a reading sixteen sigma out moves the
state about as far as one four sigma out, instead of four times as far.

**The exponent is one, and it was two until it was tested.** Squaring the ratio
makes the gain fall as `1/sigma^2` and the movement as `1/sigma` - so a sixteen
sigma reading moved the state *less* than a four sigma one, measured at 0.0071
against 0.0266. That is a **redescending** estimator, Tukey's shape rather than
Huber's, and it is the wrong one here: the more a reading disagrees, the less a
redescending filter listens, which is exactly backwards for a level that has
genuinely broken. A real break arrives as a run of large innovations and the
filter has to be able to follow them. Bounded influence follows; vanishing
influence does not.

**It is not a filter that ignores outliers.** A series that genuinely re-levels
will keep producing large innovations, each one widening its own `R'` less than
the last as the state follows - so the filter is slow to be convinced and not
incapable of it. That is the behaviour a level wants: a single bad print should
not move it, and a real break should.

## The parameter

`gate`, in standard deviations of the innovation. 2.5 as a starting point and
**not measured**: it is the point past which a touch is treated as surprising,
and the honest way to set it is the distribution of realised innovations over
real touches. That is measurable now: the episode record carries `entry` - the
touch price - at eight decimal places, with `r_price` for the scale. This
docstring used to call it a missing field, which was my error; the resolutions
write lacks it and the episode write has it. The same measurement settles `jerk`
alongside it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .linear import Gaussian

#: Innovation standard deviations before the gain is rolled off. Inside this the
#: filter is exactly `linear.Gaussian`, which is what makes it a fair arm: the
#: comparison is of the tails alone, not of two different models.
GATE_SIGMAS = 2.5


@dataclass(slots=True)
class Robust(Gaussian):
    """`linear.Gaussian` with a Huber-gated gain. Identical inside the gate.

    **Calls `Gaussian.update(self, ...)` rather than `super().update(...)`**, and
    that is required rather than stylistic: `@dataclass(slots=True)` builds a new
    class object and the zero-argument `super()` closes over the original, so it
    raises `TypeError: obj must be an instance or subtype of type`. Every slotted
    dataclass in this repository has the same constraint.
    """

    #: Innovation standard deviations before the measurement's variance starts
    #: being inflated. Not measured - see the module note.
    gate: float = GATE_SIGMAS

    #: Measurements that fell outside the gate, and the largest surprise seen in
    #: standard deviations. Both are here to be read rather than acted on: a
    #: filter whose gate never fires is `linear.Gaussian` with extra arithmetic,
    #: and one whose gate always fires has the wrong `R`.
    gated: int = 0
    worst_sigma: float = 0.0

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in one reading, discounting it in proportion to its surprise."""
        if not math.isfinite(measured) or not math.isfinite(noise) or noise < 0.0:
            return 0.0
        if when is not None:
            self.predict(when)

        # The first reading has no state to be surprised by, so there is nothing
        # to gate and the base class takes it as-is.
        if not self.seen and self.p00 >= 1.0:
            return Gaussian.update(self, measured, noise)

        s = self.p00 + noise
        if s <= 0.0:
            return Gaussian.update(self, measured, noise)
        innovation = measured - self.value
        sigma = abs(innovation) / math.sqrt(s)
        self.worst_sigma = max(self.worst_sigma, sigma)

        gate = max(self.gate, 1e-9)
        if sigma > gate:
            self.gated += 1
            # Inflate the measurement's variance by how far past the gate it is.
            # **Linear in the ratio, not squared.** The gain then falls as
            # `1/sigma` while the innovation grows as `sigma`, so the movement is
            # bounded - Huber. Squaring it makes the movement *fall* with the
            # surprise, which is redescending and ignores a real break.
            noise = noise * (sigma / gate)

        return Gaussian.update(self, measured, noise)

    @property
    def gated_share(self) -> float:
        """Share of measurements that fell outside the gate.

        **The number that says whether this is worth having.** Under a true
        Gaussian at a 2.5-sigma gate this is about 1.2%. Far above that and the
        tails are real, which is the case this module exists for. At or below it
        the gate is doing nothing and `linear.Gaussian` is the honest choice.
        """
        return self.gated / self.seen if self.seen else 0.0
