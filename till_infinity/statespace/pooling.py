"""Several members on one subject, combined by precision to a power.

`family.py` frames the thesis as a measurement between two imports - "which
filter does this state need" is asked per state - and until now nothing
combined them, so every comparison had one winner and the losers were
discarded. `statespace-pooling-exponent.md` measured what that cost:

| arm | loglike/bar | PIT | CRPS |
| --- | ---: | ---: | ---: |
| the best single member | 4.9225 | 168.14 | 0.009007 |
| **this, at the defaults below** | **5.0862** | **56.18** | **0.001601** |

**CRPS improves 5.6-fold**, which makes this the largest measured gain in the
package that was not in it.

## Every default here is the measured one, and two of them are surprises

`alpha` is the power the precision is raised to in the weight. **`1.0`**, the
Bayesian rule for independent estimates, which was *not* the expected answer:
the arm this study was built to test was `0.5`, quadratic voting's square root,
on the theory that weighting by precision rewards whichever member has
understated its own uncertainty. CRPS falls monotonically in `alpha` and 0.5
loses to 1.0 on both metrics, so the over-confidence this desk has measured
elsewhere is not caused by the weights.

`rule` is how the pooled spread is formed, and it is where the over-confidence
actually lives. **`shrinking`**, `1 / sum(precision)`, which sits *below every
member's own spread* and is strictly correct only if the members are
independent - they are not, since they read the same series. The conservative
alternative, `mixture`, is the law of total variance and cannot fall below the
members' own disagreement; it **loses by up to threefold on CRPS**. That is
informative rather than merely negative: the members disagree far more than
their individual uncertainties justify, so the between-member term carries one
member being wrong rather than genuine uncertainty.

`argmax` is the third rule and it is worth having. Winner takes all, every
step, carrying the chosen member's own spread - which is `alpha` at infinity,
and is what *A Thousand Brains* describes the cortex's columns doing. It
reaches **0.001688 against the best blend's 0.001601**, within 5%, with no
weights to compute and no spread rule to choose. It also beats a member chosen
at random each step by **4.7-fold**, which is the null that makes "selecting"
mean anything, and beats one good member held throughout by **5.3-fold** - so
the value is in **switching** rather than in model choice.

## Where the gain comes from, and where it does not apply

On **generated** feeds, whose processes are specified, pooling **loses** and a
higher `alpha` makes it worse - the exact reverse of the table above. A
correctly specified model has nothing to gain from company. So the 5.6x is
**model uncertainty**, not noise averaging, and a caller who knows the
generating process should use one member.

`argmax` on those feeds reproduces the best single member's three scores
*exactly*, which is the behaviour winner-take-all should have when a correct
member exists.

## What this does not do

**It does not make a calibrated band.** The best PIT flatness in the study is
56 against the 1.0 of a calibrated forecast, and a shape-free conformal band
reaches **1.5** at one bar. This is a **sharpness** win and not a calibration
fix. The two are not in competition - a pooled point forecast inside a
conformal band uses each for what it measurably does.

Not `Restorable` and not persisted: see `CODEC_UNPERSISTED`. It is also
deliberately **absent from `family.members()`**, which is the registry of
filter *kinds*; a pool is a combination of them rather than another one.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

#: The power the precision is raised to. Measured: CRPS falls monotonically in
#: this and 1.0 beats 0.5, the quadratic-voting value this was built to test.
ALPHA = 1.0

#: How the pooled spread is formed. `shrinking` is `1 / sum(precision)`,
#: `mixture` the law of total variance, `argmax` winner-take-all.
RULE = "shrinking"

#: The members pooled when a caller names none. Three distinct behaviours.
#:
#: **`landau` is deliberately not here.** At its default `kappa = 0` it *is*
#: `reverting` - the same state, the same covariance, the same likelihood,
#: which its own docstring gives as the thing that makes it a nested
#: one-parameter test. A pool containing both puts twice the weight on
#: reverting behaviour and calls itself a four-member pool, which is how the
#: first version of the study ran before its single-member arm exposed two
#: members scoring identically to four decimal places.
DEFAULT = ("kalman", "reverting", "robust")

#: Smallest spread a member is allowed to claim, so one that has convinced
#: itself it is certain cannot take the whole weight and divide by zero.
FLOOR = 1e-12

#: The process-noise lever each member names, for `adapt`. `Adapting` defaults
#: to `jerk`, which `reverting` does not have - it calls the same quantity
#: `sigma2` - so a pool that adapted every member through one name would raise
#: on the second one.
#: `s4d` names `noise`, which is the only thing that sets a deterministic map's
#: predictive spread - there is no `Q` in it to inflate. **It is a standard
#: deviation where every other lever here is a variance**, and that is stated
#: rather than hidden: a multiplicative step of `f` on an sd is `f**2` on the
#: variance, so the loop's damping is doubled. The *fixed point* is unchanged -
#: `matching` solves `E[z**2] = 1` either way - so this changes how fast the
#: lever converges and not where it converges to.
LEVERS = {
    "kalman": "jerk",
    "robust": "jerk",
    "reverting": "sigma2",
    "landau": "sigma2",
    "s4d": "noise",
    # `sigma2` is the process variance per hour, so this is a variance lever
    # like `kalman`'s and `reverting`'s - no units caveat needed.
    "ornstein": "sigma2",
}

#: Whether each member learns its own process noise from its own standardised
#: innovation, through `adapting.Adapting` in `matching` mode.
#:
#: **Default true, and it is the largest correction in this module.**
#: `statespace-river-against-members.md` set a River Hoeffding tree against this
#: pool and lost by **3.6x on CRPS** - and then found that most of the gap was
#: not learning at all. On the generated feeds, which are validated driftless
#: Brownian motion with **nothing to learn**, the learner still won and sat at a
#: PIT flatness of 1.24 where this pool read **43.05**. A gain that survives
#: where there is nothing to learn is a statement about the pool, and what it
#: says is that its members' `Q` is mis-set.
#:
#: Wrapping them in `Adapting` - which drives the exponentially weighted square
#: of the standardised innovation toward 1.0, what its own docstring calls "an
#: honest filter" - recovers most of it:
#:
#: | arm | PIT | CRPS |
#: | --- | ---: | ---: |
#: | plain members | 37.77 | 0.001598 |
#: | **adapting members** | **7.89** | **0.000588** |
#: | the River tree | 8.81 | 0.000441 |
#:
#: So `Adapting` is worth **2.7x on CRPS** here and takes the pool from badly
#: over-confident to better calibrated than the learner that exposed it. It was
#: written, measured at +848 nats median in `family.py`, and until this was
#: used by nothing.
ADAPT = True


def _factories(names: Sequence[str]) -> tuple[Callable[[], object], ...]:
    from .family import members

    built = members()
    return tuple(built[name] for name in names if name in built)


@dataclass(slots=True)
class Pooled:
    """A pool of members that is itself a `family.Filter`.

    Satisfies the contract by delegating: `predict` advances every member and
    forms the combined `(value, sd)`, `update` scores the combined predictive
    against the reading and then folds it into each member.
    """

    names: tuple[str, ...] = DEFAULT
    alpha: float = ALPHA
    rule: str = RULE
    #: See `ADAPT`. `False` is the un-adapting pool, kept because it is the arm
    #: every `alpha` and `rule` figure was originally measured on.
    adapt: bool = ADAPT
    #: Upper clamp on each member's process-noise lever, as a multiple of its
    #: starting value. `None` takes `adapting.MOST`.
    #:
    #: **Reachable because it was measured binding.** `adapting-strata.md`
    #: found every member on every traded instrument finishing at
    #: `factor = 1000.000` - `MOST` exactly - with the loop's own `excess`
    #: reading what the sample reads: it knew how wrong it was and was not
    #: allowed to move. Released to 1e7 the loop converges at a factor of 1.3
    #: to 4.2 **million**, which is the scale between a price and a log
    #: variance rather than a tuning error.
    #:
    #: The default does not move. Six orders of magnitude is a unit problem,
    #: and whether the answer is a wider clamp or an input on the scale the
    #: priors expect is being measured; a clamp exists to stop a loop chasing
    #: an outlier and widening it by default would weaken that for every
    #: member. What ships here is the knob and `saturated`, so the condition is
    #: observable instead of silent.
    most: float | None = None

    #: Combined state, formed in `predict`.
    value: float = 0.0
    rate: float = 0.0
    variance: float = 1.0
    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    last_standardised: float = 0.0
    existence: float = 1.0

    #: The weight each member carried at the last reading, so what the pool
    #: actually did is observable rather than assumed. `argmax` makes this a
    #: one-hot vector and the harness reads which member won from it.
    weights: tuple[float, ...] = ()

    _pool: list = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if not self._pool:
            built = _factories(self.names)
            if len(built) < 2:
                raise ValueError(
                    f"a pool needs at least two members, got {len(built)} from "
                    f"{self.names!r}. One member is not a pool and should be "
                    "used directly."
                )
            if self.adapt:
                from .adapting import MOST, Adapting

                self._pool = [
                    Adapting(
                        build=make,
                        lever=LEVERS.get(name, "jerk"),
                        mode="matching",
                        most=MOST if self.most is None else float(self.most),
                    )
                    for name, make in zip(self.names, built, strict=False)
                ]
            else:
                self._pool = [make() for make in built]
        if self.rule not in ("shrinking", "mixture", "argmax"):
            raise ValueError(f"unknown rule {self.rule!r}")

    @property
    def members(self) -> tuple:
        """The pooled members, for a caller that wants to inspect them."""
        return tuple(self._pool)

    @property
    def saturated(self) -> tuple[str, ...]:
        """Members whose process-noise lever has run out of room, by name.

        **A loop on its clamp is not adapting**, which `adapting.py` says in so
        many words - and until this existed there was no way to see it from
        outside. `adapting-strata.md` measured every traded member pinned at
        `MOST` while publishing a one-step spread three times too small, and
        the service logged nothing unusual for the whole run, because nothing
        looked.

        Both ends count. The constant-sigma family pins at `LEAST` instead -
        its lever runs to 0.028 and then to the floor - which is the same
        failure wearing the opposite sign: a lever against a stop cannot
        answer the next bar.
        """
        out = []
        for name, one in zip(self.names, self._pool, strict=False):
            factor = getattr(one, "factor", None)
            if factor is None:
                continue
            most = float(getattr(one, "most", math.inf))
            least = float(getattr(one, "least", 0.0))
            if float(factor) >= most * (1.0 - 1e-9) or float(factor) <= least * (1.0 + 1e-9):
                out.append(name)
        return tuple(out)

    @property
    def sd(self) -> float:
        return math.sqrt(max(self.variance, 0.0))

    def _combine(self) -> None:
        mus = [float(one.value) for one in self._pool]
        sds = [max(float(one.sd), FLOOR) for one in self._pool]
        precision = [1.0 / (s * s) for s in sds]
        if self.rule == "argmax":
            best = max(range(len(precision)), key=lambda i: precision[i])
            weights = [1.0 if i == best else 0.0 for i in range(len(precision))]
            self.value = mus[best]
            self.variance = sds[best] ** 2
        else:
            raised = [p**self.alpha for p in precision]
            total = sum(raised)
            if total > 0:
                weights = [r / total for r in raised]
            else:
                weights = [1.0 / len(raised)] * len(raised)
            self.value = sum(w * m for w, m in zip(weights, mus, strict=True))
            if self.rule == "shrinking":
                self.variance = 1.0 / sum(precision)
            else:
                within = sum(w * s * s for w, s in zip(weights, sds, strict=True))
                between = sum(w * (m - self.value) ** 2 for w, m in zip(weights, mus, strict=True))
                self.variance = within + between
        self.weights = tuple(weights)
        self.rate = sum(
            w * float(getattr(one, "rate", 0.0)) for w, one in zip(weights, self._pool, strict=True)
        )

    def predict(self, when: float, control: float = 0.0) -> None:
        """Advance every member, then form the combined state."""
        for one in self._pool:
            try:
                one.predict(float(when), control)  # type: ignore[call-arg]
            except TypeError:
                one.predict(float(when))
        self._combine()
        self.at = float(when)

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Score the combined predictive, then fold the reading into each member.

        **In that order.** Scoring after the members have absorbed the reading
        would be scoring a posterior against its own observation, which is the
        one thing a held-out likelihood must not do.
        """
        if when is not None:
            self.predict(float(when))
        spread = self.variance + max(float(noise), 0.0)
        if spread > 0:
            residual = float(measured) - self.value
            self.last_standardised = residual / math.sqrt(spread)
            self.loglike += -0.5 * (residual * residual / spread + math.log(2.0 * math.pi * spread))
        for one in self._pool:
            one.update(float(measured), float(noise), when)
        self.seen += 1
        self._combine()
        return self.last_standardised

    def at_time(self, when: float) -> float:  # noqa: ARG002
        """The pool does not extrapolate between members. Returns `value`."""
        return self.value

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:  # noqa: ARG002
        spread = sigmas * self.sd
        return self.value - spread, self.value + spread

    def state(self) -> tuple[float, ...]:
        return (self.value, self.rate)

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        """`C`, the observation matrix. The pool's state is `(value, rate)`.

        Written down rather than implied, for the reason `linear.py` gives: the
        measured quantity being the first state slot is a convention that is
        true of these members and not true in general. For a pool it is true by
        construction, because `state()` is built from the combined `value` and
        `rate` rather than from any member's own basis - which is what lets a
        pool hold `selective`, whose state is coefficients.
        """
        return ((1.0, 0.0),)

    def quantiles(self, levels: Sequence[float]) -> list[tuple[float, float]]:
        """`(level, value)` pairs for `diagnostics.crps`, Gaussian in shape.

        The pool's predictive is a weighted mean and a variance, so it is
        normal by construction rather than by assumption - which is also its
        limitation, and why `statespace-conformal-band.md` remains the
        calibrated forecast and this one the sharp one.
        """
        from .distance import _normal_quantile

        return [(level, self.value + self.sd * _normal_quantile(level)) for level in levels]
