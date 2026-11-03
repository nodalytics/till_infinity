"""Stop asserting continuity where the evidence says there isn't any.

Two independent fluid-dynamics papers arrived at the same prescription, and it
is one this package can act on directly.

Fluids 11:251 (parametric PINN against a tensorial reduced-order model for the
shallow-water dam break) finds that at a shock **the differential form of the
equation is not valid**, so enforcing it there degrades the fit - and the repair
is *shock-aware collocation* plus **PDE gating**: stop asserting the physics
where the physics does not hold. Processes 14:3253 arrives at the same place
from the interface-capturing side, where the whole reason the phase-field branch
exists is that a **diffuse** interface is numerically better behaved than a
sharp one.

A Kalman filter's process model is a smoothness prior: the state moves by a
bounded amount per unit time. At a regime change that prior is **false**, and
the filter fights the data - which is the same failure, in a different field.

## Why this rather than a reset

`Paired` already resets a member on detection, and a reset is the *sharp*
interface: it throws the state away at a point. The diffuse version keeps the
state and **widens the process noise in proportion to the evidence**, which

* degrades gracefully when the detector is wrong, where a reset does not;
* needs no threshold, because the posterior probability is already a number
  between zero and one;
* and loses nothing when there is no change, because the probability is then
  near zero and the member is its unmodified self.

`Changepoint` already publishes exactly the number required - `changepoint`, the
posterior mass on a run no older than `FRESH_HOURS` - and **nothing consumed
it**. That is bug shape #4 in the `finding-bugs` skill, computed and read by
nothing, and this is the thing it was computed for.

## The lever, and why it is named rather than general

Process noise enters each member through its own parameter: `jerk` on `linear`,
and whatever the member calls it elsewhere. There is no general way to scale a
process noise through the `Filter` protocol, and the two general-looking
alternatives are both wrong - inflating the elapsed time passed to `predict`
would advance the **drift** as well as the variance, and reaching into a
covariance would assume a state layout.

So `Yielding` scales a **named attribute**, and a member that does not have one
declines to be softened. That is the same contract `smooth` uses: a member that
cannot state its own transition declines to be smoothed, which is a true
statement about the member rather than a limitation here.

## Nothing here publishes

The null is two-sided and both halves matter: `Yielding` must beat **the member
alone** - or the detector is firing on noise - and must beat **`Paired`**, the
reset, or the diffuse treatment bought nothing over the sharp one. Both are the
same member on the same series, scored on held-out likelihood.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

HOUR = 3600.0

#: How far the process noise may be inflated when the detector is certain a
#: change just happened. Ten, because the prior being softened is a *smoothness*
#: prior and an order of magnitude is the difference between "the state barely
#: moves" and "the state may go anywhere" - not fitted, and the harness sweeps
#: it rather than trusting it.
REACH = 10.0

#: The attribute each member exposes as its process-noise scale.
LEVER = "jerk"


@dataclass(slots=True)
class Yielding:
    """A member whose process noise widens with the probability of a change.

    Satisfies `Filter` by delegating, so it is scored against the member alone
    and against `Paired` on the same readings. Adds `softness`, the factor
    currently applied, so what it is doing is observable rather than inferred.
    """

    build: Callable[[], object]
    #: How far the noise may be inflated at certainty. `1.0` disables the whole
    #: mechanism, which is the arm the harness needs.
    reach: float = REACH
    lever: str = LEVER

    _member: object = field(default=None, repr=False)
    _detector: object = field(default=None, repr=False)
    #: The member's own process noise, before anything was done to it.
    _base: float = 0.0
    #: The factor applied at the last reading. 1.0 means untouched.
    softness: float = 1.0
    #: Peak softness **after the warm-up**, and the running mean. A plain
    #: maximum over the whole run is useless: `Changepoint` necessarily reads
    #: near one before it has any history, because all its mass sits at short
    #: run lengths, so every run would report a peak of `reach` whether or not
    #: anything happened. Measured from `settled` readings onward.
    widest: float = 1.0
    average: float = 1.0
    _total: float = field(default=0.0, repr=False)
    _counted: int = field(default=0, repr=False)
    #: Readings before the softness is counted, for the reason above.
    settled: int = 30

    def __post_init__(self) -> None:
        if self._member is None:
            self._member = self.build()
        if not hasattr(self._member, self.lever):
            raise AttributeError(
                f"{type(self._member).__name__} has no '{self.lever}' to soften. "
                "A member that cannot name its process noise declines to be "
                "softened, which is a statement about the member."
            )
        self._base = float(getattr(self._member, self.lever))
        if self._detector is None:
            from .changepoint import Changepoint

            self._detector = Changepoint()

    # ----------------------------------------------------- the member's view

    @property
    def value(self) -> float:
        return float(getattr(self._member, "value", 0.0))

    @property
    def rate(self) -> float:
        return float(getattr(self._member, "rate", 0.0))

    @property
    def sd(self) -> float:
        return float(getattr(self._member, "sd", 0.0))

    @property
    def at(self) -> float | None:
        return getattr(self._member, "at", None)

    @property
    def seen(self) -> int:
        return int(getattr(self._member, "seen", 0))

    @property
    def loglike(self) -> float:
        return float(getattr(self._member, "loglike", 0.0))

    @loglike.setter
    def loglike(self, value: float) -> None:
        """Forwarded to the member, so a harness can zero it at a boundary."""
        self._member.loglike = float(value)  # type: ignore[union-attr]

    @property
    def last_standardised(self) -> float:
        return float(getattr(self._member, "last_standardised", 0.0))

    @property
    def existence(self) -> float:
        return float(getattr(self._member, "existence", 1.0))

    def at_time(self, when: float) -> float:
        return float(self._member.at_time(when))  # type: ignore[union-attr]

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        return self._member.band(when, sigmas)  # type: ignore[union-attr]

    def state(self) -> tuple[float, ...]:
        return tuple(self._member.state())  # type: ignore[union-attr]

    def output(self) -> tuple[float, ...]:
        return self._member.output()  # type: ignore[union-attr]

    # --------------------------------------------------------------- the pair

    @property
    def changepoint(self) -> float:
        """The detector's current posterior mass on a fresh run."""
        return float(getattr(self._detector, "changepoint", 0.0))

    def predict(self, when: float) -> None:
        """Soften **before** advancing, which is the only correct order.

        The process noise is applied over the interval being advanced, so the
        factor has to be in place before `predict` runs. Softening afterwards
        would widen the *next* step on the evidence of this one - a one-step
        lag that would look like it worked, because a change takes more than one
        reading to be detected anyway.
        """
        self.softness = 1.0 + (self.reach - 1.0) * self.changepoint
        if self.seen >= self.settled:
            self.widest = max(self.widest, self.softness)
            self._total += self.softness
            self._counted += 1
            self.average = self._total / self._counted
        setattr(self._member, self.lever, self._base * self.softness)
        self._member.predict(when)  # type: ignore[union-attr]

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold the reading into both, member first.

        The detector sees the same reading as the member rather than the
        member's innovation, because what it is asked is whether the *level*
        changed - `Paired` asks the other question, whether the model stopped
        describing the series, and the two are different events.
        """
        innovation = self._member.update(measured, noise, when)  # type: ignore[union-attr]
        self._detector.predict(when if when is not None else 0.0)  # type: ignore[union-attr]
        self._detector.update(measured, noise, when)  # type: ignore[union-attr]
        return innovation

    @property
    def hours_since_change(self) -> float:
        """How long the detector thinks the current regime has stood."""
        return float(getattr(self._detector, "run_hours", 0.0))
