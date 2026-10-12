"""Error feedback on the filter's own noise. Online learning, where it is missing.

**A Kalman filter already is online learning with error feedback.** The
innovation `z - C x` is an error signal, the gain `K = P C' (C P C' + R)^-1` is
a learning rate, and that rate is *optimal by construction* given the model -
it is derived from the uncertainty rather than tuned. So "add online learning"
to a member in this package is mostly a category error, and asking for it is
really asking the sharper question: **what is the filter not learning?**

It is not learning its own parameters. The gain is optimal *given* `(Q, R)`,
and those are set by hand or fitted offline on a grid over a whole series. That
is the gap this module fills - for the scalar process-noise lever only, which
is the one `driven.py` already treats as a lever.

`family.MISSING["sequential parameter learning"]` describes the full version -
IBIS or SMC^2, a posterior over parameters updated as measurements arrive - and
that stays missing, because it needs a particle filter which is itself unbuilt.
This is the cheap part of it: a point estimate of one parameter, driven by the
residual.

## The three schemes, and why two of them are the same scheme

`mode` picks the rule. All three act multiplicatively on the lever and are
clamped, because a process noise of zero is a state that cannot move and a
process noise of infinity is a state that is pure noise.

* **`matching`** - covariance matching, the control-theory answer. Track an
  exponentially weighted mean of the **squared standardised innovation**,
  `z^2 = i^2 / s`. An honest filter has `E[z^2] = 1`; above one it is
  over-confident, so inflate the lever. The update is `lever *= m ** rate`.

* **`gradient`** - stochastic gradient ascent on the one-step log-likelihood
  with respect to `log Q`, the machine-learning answer. And it is **the same
  direction**:

      d/d(log Q) [-0.5 (log s + i^2/s)] = 0.5 (z^2 - 1) * (dQ s)/s

  which is positive exactly when `z^2 > 1`. So covariance matching *is*
  gradient ascent on the likelihood, up to the step size - the control answer
  and the learning answer coincide here, and the only real difference is that
  the gradient's step shrinks as `s` grows while matching's does not. Both are
  kept because that difference is measurable; neither is kept because they are
  different ideas.

* **`forgetting`** - exponential forgetting, the recursive-least-squares
  answer. It does **not touch `Q` at all**: it inflates `P` by `1/lambda` on
  every step, which bounds how much information the filter can accumulate and
  so bounds how confident it can become. A genuinely different mechanism, with
  one parameter and no error signal, which makes it the cheap control on
  whether the error feedback is doing anything.

## What this is, honestly

Covariance matching on `Q` from an exponentially weighted mean of squared
innovations **is a volatility model.** Not a disguised one - that is what it
is. This desk already knows volatility clustering is real and large, so a win
here is expected rather than interesting, and the measurement that matters is
not "does it beat a fixed `Q`" but:

* does it beat `Q` **fitted offline**, which is what the desk does now;
* does it beat the **clock** in `seasonal.Profile`, which models the same
  quantity deterministically and cannot react to a shock;
* and do the two **compose**, since one is a time-of-day pattern and the other
  is a reaction to what just happened.

`research/ideas/online_learning.py` runs those, with a planted
changing-`Q` series to prove the loop can track at all and the Deriv
volatility indices - constant `Q` by construction - as the control where it
must buy nothing.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

#: Default step for `matching` and `gradient`. 0.02 is deliberately slow: the
#: quantity being tracked is a second moment estimated from one observation at
#: a time, so a fast rate chases single innovations.
RATE = 0.02

#: Memory for the squared-innovation mean, in effective observations. The
#: decay is `1 - 1/MEMORY` per step.
MEMORY = 64.0

#: Forgetting factor for `forgetting`. `P` is inflated by `1/lambda` per step,
#: so 0.999 at hourly bars forgets on a scale of about a thousand bars.
LAMBDA = 0.999

#: Clamps on the lever, as multiples of the member's own starting value. A
#: process noise of zero is a state that cannot move; one of infinity is a
#: state that is pure noise. Both are reachable by a loop chasing an outlier.
LEAST = 1e-3
MOST = 1e3


@dataclass(slots=True)
class Adapting:
    """A member whose process-noise lever is learnt online from its residual.

    Satisfies `Filter` by delegating, in the same shape as `driven.Driven`, so
    the two can wrap the same member and be scored against each other - which
    is the whole point, since they model the same quantity by opposite routes.
    """

    build: Callable[[], object]
    lever: str = "jerk"
    #: `"matching"`, `"gradient"`, `"forgetting"`, or `"none"` for the bare
    #: delegate. `"none"` exists so a harness can use one code path for the
    #: null arm and cannot accidentally compare two different wrappers.
    mode: str = "matching"
    #: Step size. **Called `step` and not `rate` on purpose**: `family.Filter`
    #: requires `rate`, and there it means the *state's* drift. A wrapper that
    #: used the name for a learning rate would hand every consumer a step size
    #: where it expected a velocity, and the two are both floats, so nothing
    #: would complain.
    step: float = RATE
    memory: float = MEMORY
    forgetting: float = LAMBDA
    least: float = LEAST
    most: float = MOST

    _member: object = field(default=None, repr=False)
    _base: float = 0.0
    #: Exponentially weighted mean of the squared standardised innovation.
    #: **1.0 is an honest filter**; this is the error signal itself, exposed
    #: rather than hidden, because a loop whose signal cannot be read is a
    #: loop whose failure cannot be diagnosed.
    excess: float = 1.0
    #: The lever's current multiple of its starting value, and the extremes it
    #: has reached - a loop that never moves is not adapting, and one that
    #: sits on a clamp is not either.
    factor: float = 1.0
    lowest: float = 1.0
    highest: float = 1.0
    #: How many readings this wrapper has folded in. Counted here rather than
    #: delegated because the member's own `seen` skips a first reading that
    #: initialises the state, and the loop's memory is in wrapper steps.
    steps: int = 0

    def __post_init__(self) -> None:
        if self._member is None:
            self._member = self.build()
        if not hasattr(self._member, self.lever):
            raise ValueError(
                f"{type(self._member).__name__} has no '{self.lever}' to adapt. "
                "The lever has to name a real field, or this silently does nothing."
            )
        if self.mode not in ("matching", "gradient", "forgetting", "none"):
            raise ValueError(f"unknown mode {self.mode!r}")
        self._base = float(getattr(self._member, self.lever))

    # ----------------------------------------------------------- delegation

    @property
    def value(self) -> float:
        return float(getattr(self._member, "value", 0.0))

    @property
    def rate(self) -> float:
        """The **state's** drift, as `family.Filter` means it."""
        return float(getattr(self._member, "rate", 0.0))

    @property
    def existence(self) -> float:
        return float(getattr(self._member, "existence", 1.0))

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
        self._member.loglike = float(value)

    @property
    def burn(self) -> int:
        return int(getattr(self._member, "burn", 0))

    @burn.setter
    def burn(self, value: int) -> None:
        self._member.burn = int(value)

    @property
    def last_standardised(self) -> float:
        return float(getattr(self._member, "last_standardised", 0.0))

    def state(self) -> tuple[float, ...]:
        return self._member.state()

    def covariance(self) -> tuple[tuple[float, ...], ...]:
        return self._member.covariance()

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return self._member.observation()

    def output(self) -> tuple[float, ...]:
        return self._member.output()

    def transition(self, dt: float) -> tuple[tuple[float, ...], ...]:
        return self._member.transition(dt)

    def at_time(self, when: float) -> float:
        return self._member.at_time(when)

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        return self._member.band(when, sigmas)

    # --------------------------------------------------------------- predict

    def predict(self, when: float) -> None:
        self._member.predict(when)
        if self.mode == "forgetting" and 0.0 < self.forgetting < 1.0:
            # Inflate P. Only the diagonal is scaled here, because the
            # off-diagonal carries the *correlation* between states and
            # scaling it by the same factor would leave the correlation
            # unchanged while the variances grew - which is what forgetting
            # is supposed to do, so the full scaling is the right one.
            lift = 1.0 / self.forgetting
            for name in ("p00", "p01", "p11"):
                if hasattr(self._member, name):
                    setattr(self._member, name, getattr(self._member, name) * lift)

    # ---------------------------------------------------------------- update

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in one reading, then correct the lever from the residual.

        **The order matters and is the whole design.** The lever is updated
        *after* the measurement is scored, so the likelihood at every step was
        produced by a parameter chosen before that measurement was seen. A loop
        that adapted first would be scoring a parameter fitted to the point it
        is predicting, and would win by cheating.
        """
        if when is not None:
            self.predict(when)
        innovation = float(self._member.update(measured, noise))
        self.steps += 1

        # **The error signal is tracked in every mode, including `none`.** It
        # is a diagnostic - `E[z^2] = 1` says whether the filter's confidence
        # is honest - and a harness wants to read it on the null arm too. Only
        # the *lever* is mode-dependent. The first version returned early for
        # `none`, so the null arm always reported a perfect 1.0 and the
        # comparison it was there to provide was unavailable.
        standardised = float(getattr(self._member, "last_standardised", 0.0))
        if math.isfinite(standardised):
            decay = 1.0 - 1.0 / max(self.memory, 2.0)
            self.excess = decay * self.excess + (1.0 - decay) * standardised * standardised
        if self.mode in ("none", "forgetting") or not math.isfinite(standardised):
            return innovation

        if self.mode == "matching":
            # lever *= m ** rate: a damped multiplicative step toward E[z^2]=1.
            move = self.excess**self.step if self.excess > 0.0 else 1.0
        else:
            # The gradient's step shrinks with the predictive spread, which
            # matching's does not. Written as an exponential so it cannot
            # take the lever negative however large one innovation is.
            spread = self.sd * self.sd + max(noise, 0.0)
            scale = 1.0 / (1.0 + spread) if spread > 0.0 else 1.0
            move = math.exp(self.step * (self.excess - 1.0) * scale)

        self.factor = min(max(self.factor * move, self.least), self.most)
        self.lowest = min(self.lowest, self.factor)
        self.highest = max(self.highest, self.factor)
        setattr(self._member, self.lever, self._base * self.factor)
        return innovation

    # -------------------------------------------------------------- readings

    @property
    def honest(self) -> bool:
        """Is the filter's own confidence currently calibrated?

        `E[z^2] = 1` within a tolerance that scales as `sqrt(2/memory)` - the
        standard error of a mean of squared normals. **Not a diagnostic
        afterthought**: this is the quantity the loop exists to drive to one,
        so whether it got there is the result.
        """
        if self.steps < self.memory:
            return False
        return abs(self.excess - 1.0) <= 2.0 * math.sqrt(2.0 / max(self.memory, 2.0))

    @property
    def clamped(self) -> bool:
        """Has the lever hit a clamp? Then the loop is not learning, it is stuck."""
        return self.factor <= self.least * 1.001 or self.factor >= self.most * 0.999

    @property
    def moved(self) -> float:
        """Ratio of the highest to the lowest lever reached. 1.0 is not adapting."""
        return self.highest / self.lowest if self.lowest > 0 else math.inf
