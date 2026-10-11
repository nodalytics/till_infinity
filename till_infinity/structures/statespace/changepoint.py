"""Bayesian online change-point detection: a posterior over *how long this has held*.

Adams and MacKay's BOCPD, with the Normal-Inverse-Gamma conjugate model that
makes the one-step predictive a Student-t. Added 2026-10-11 after reading
Tsaknaki, Lillo and Mazzarisi (arXiv:2307.02375), whose application - order flow
and market impact - needs signed trades and a book that this desk does not have,
and whose *method* transfers directly.

## Why this and not `hmm`

`family.PENDING` records the objection to a hidden Markov member: "a discrete
state is a different claim about the world, not a better fit", and it needs the
number of states chosen before it can be fitted. BOCPD keeps a posterior over
the **run length** - how many observations since the last change - which

* **does not require a regime count.** It is the change-point formulation of the
  unbounded-mixture idea `dpm` is listed for, and cheaper: a distribution over
  one integer rather than a mixture over partitions.
* **is online by construction.** `hmm` as usually fitted needs the series. This
  updates per observation, which is the only form a desk can run - the same
  constraint that made `smooth` unusable live and `lagged` necessary.

## The two outputs nothing else here has

Every other member answers *where is it* and *how sure*. This one also answers:

* **`changepoint`** - the posterior probability that the run length is zero,
  which is "the thing I am tracking just changed". A level that has stopped
  being the level is the event the desk's `existence` decays toward and never
  detects; this names it on the observation it happens.
* **`run_length`** - the expected number of observations since that change, so
  "how established is this" is a number rather than a feeling.

## It infers its measurement variance, which no other member does

`noise` on the `Filter` contract is the measurement **variance**, and every
other member is *told* it. This one is told a prior and **learns it**: the
Normal-Inverse-Gamma posterior carries the variance as well as the mean, so
`noise` here sets `beta0/alpha0` and is then updated by the data.

That is a real difference and it cuts both ways. It is the honest answer to
`README.md`'s improvements 1 and 2 - a time-varying `R` without either an
external forecaster or a score-driven rule, because the variance is simply part
of the posterior. And it means this member cannot be handed a volatility
forecast, so the comparison against one is a comparison of two mechanisms.

## What it does not claim

**There is no rate here, and `rate` returns zero.** A change-point model asserts
the quantity is *piecewise constant*: the claim is that it holds, then changes,
not that it drifts. A rate read off this member would be inventing a trend the
model does not have, which is the pattern `reverting.accel` already refuses - it
reports `-theta * rate` because that is where the rate is heading, and a
consumer wanting the acceleration's own uncertainty is sent to `linear`.

So on a trending series this member is **wrong on purpose**, and `linear` or
`reverting` is the one to use. Its claim is about a level that sits still until
it does not.

## Cost

`O(R)` an observation, where `R` is the truncated run-length support. The
posterior is capped at `MAX_RUN` and renormalised, which is standard practice
and bounds both time and memory - without it the support grows with the series
and this would be `O(n)` per step.

## Nothing here publishes

Same rule as the rest of the package: reachable from tests and research
harnesses only, until a named null has been beaten on held-out data. **The null
is `linear` and `reverting` on held-out one-step likelihood**, and the paper's
own claim is the bar: regime information improved its online predictions over
models without it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .linear import EXISTENCE_HALF_LIFE_HOURS

HOUR = 3600.0

#: Hard ceiling on the run-length posterior, as a **compute budget**. Each
#: component carries six floats and is touched every reading, so this is the
#: cost of the member rather than a statement about the model.
#:
#: **It used to be 300 and the reason given for it was wrong.** The claim was
#: that 300 is where the geometric prior's tail is negligible - which is a
#: claim about *time* dressed as a count. At 1d a hazard of one change per ten
#: days makes 300 components 300 days and the tail genuinely negligible; at 15m
#: the same 300 components are **three days**, less than a third of one
#: expected regime, so the posterior was pressed against the cap permanently
#: and `run_hours` reported a lower bound while looking like an estimate.
MAX_RUN = 1000

#: How many expected regime lengths the posterior should reach before it is
#: truncated, which is the duration the cap is really about. Three gives a tail
#: of `exp(-3)`, about 5%, and the tail is folded into the last kept component
#: rather than dropped - so nothing leaks either way, and what truncation costs
#: is the ability to say a regime is *older* than this.
LIVES = 3.0

#: How recent a run counts as "just changed", in **hours**. A duration, because
#: "two readings ago" is half an hour at 15m and two days at 1d, and the
#: question `changepoint` answers - did the thing I track just change - is about
#: the market rather than about the sampling.
#:
#: Six hours is not fitted. It is short relative to the ten-day regime the
#: hazard expects, which is the only property it needs.
FRESH_HOURS = 6.0

#: Components always included in `changepoint`, whatever the clock says. Two
#: rather than zero because `P(run length = 0)` is approximately the hazard rate
#: whatever the data does - see `changepoint` for why, and for the measurement
#: that showed it - so on a series whose bars are longer than `FRESH_HOURS` the
#: statistical floor is what applies.
FRESH_LEAST = 2

#: Hazard **per hour**, not per observation. `1/HAZARD` is the mean time
#: between changes, so this says "expect a regime to last about ten days" -
#: chosen to be long relative to the horizons this desk trades and **not**
#: fitted.
#:
#: **Per hour is the whole point.** The first version was per observation, at
#: `1/250`, which means "a change every 250 readings" - **12.5 hours at 3m and
#: 250 days at 1d**. The same member would then assert wildly different beliefs
#: about how often the world changes depending on which series it was handed,
#: which is the same portability bug `inputs.py` has in its windows and the
#: reason those are in hours too. It also makes the member correct under
#: irregular sampling, which is this package's actual situation: touches arrive
#: when they arrive.
HAZARD = 1.0 / (10 * 24.0)


def _log_student_t(x: float, mu: float, kappa: float, alpha: float, beta: float) -> float:
    """Log predictive density under a Normal-Inverse-Gamma posterior.

    The marginal is a Student-t with `2*alpha` degrees of freedom, location `mu`
    and scale squared `beta*(kappa + 1)/(alpha*kappa)`. Written out rather than
    taken from scipy, for the same reason the rest of the package is.
    """
    if kappa <= 0 or alpha <= 0 or beta <= 0:
        return -math.inf
    df = 2.0 * alpha
    scale2 = beta * (kappa + 1.0) / (alpha * kappa)
    if scale2 <= 0:
        return -math.inf
    z2 = (x - mu) ** 2 / scale2
    return (
        math.lgamma(0.5 * (df + 1.0))
        - math.lgamma(0.5 * df)
        - 0.5 * math.log(math.pi * df * scale2)
        - 0.5 * (df + 1.0) * math.log1p(z2 / df)
    )


@dataclass(slots=True)
class Changepoint:
    """BOCPD over a piecewise-constant quantity, with a Student-t predictive.

    The state is a posterior over run lengths; `value` and `sd` are that
    posterior marginalised, and `changepoint` is its mass at zero.
    """

    #: Hazard **per hour**. Converted to a per-observation probability from the
    #: elapsed time at each reading, so a gap of a day carries a day's worth of
    #: change risk and a gap of a minute carries a minute's.
    hazard: float = HAZARD
    #: Prior pseudo-count on the mean. One says "the first reading is worth as
    #: much as the prior", which is the diffuse-ish choice `linear` makes when
    #: it takes the first reading as its state.
    kappa0: float = 1.0
    #: Prior shape on the variance. Above one so the predictive has finite
    #: variance from the first observation.
    alpha0: float = 1.5
    #: Prior scale on the variance, set from `noise` on the first update.
    beta0: float = 1.0

    at: float | None = None
    #: Unix seconds of the last *reading*, which is not `at`: `predict` moves
    #: `at` without one, and the hazard has to be driven by the gap between
    #: readings rather than by the gap since any clock advance.
    _read_at: float | None = field(default=None, repr=False)
    seen: int = 0
    loglike: float = 0.0
    #: One reading is skipped: the first sets the prior's location.
    burn: int = 1
    last_standardised: float = 0.0
    existence: float = 1.0

    #: `log P(run length = r, data)` for `r = 0 .. len-1`, unnormalised.
    _logp: list[float] = field(default_factory=list)
    #: Elapsed **hours** covered by each run-length component, parallel to
    #: `_logp`. What makes `run_hours` portable where `run_length` is not.
    _hours: list[float] = field(default_factory=list)
    #: Running mean of the gaps between readings, in hours. What turns the
    #: truncation's duration into a component count without being told the
    #: timeframe.
    _spacing: float = 0.0
    #: Sufficient statistics per run length, parallel to `_logp`.
    _mu: list[float] = field(default_factory=list)
    _kappa: list[float] = field(default_factory=list)
    _alpha: list[float] = field(default_factory=list)
    _beta: list[float] = field(default_factory=list)

    NAMES: tuple[str, ...] = ("value",)
    OUTPUTS: tuple[str, ...] = ("value",)

    # ------------------------------------------------------------- posterior

    def _weights(self) -> list[float]:
        """The run-length posterior, normalised."""
        if not self._logp:
            return []
        top = max(self._logp)
        raw = [math.exp(v - top) for v in self._logp]
        total = sum(raw)
        return [v / total for v in raw] if total > 0 else [1.0 / len(raw)] * len(raw)

    @property
    def value(self) -> float:
        """The posterior mean, averaged over run lengths.

        A reading taken after a change should move this sharply, because the
        mass has moved to a run length of zero whose mean is the new reading.
        """
        weights = self._weights()
        if not weights:
            return 0.0
        return sum(w * m for w, m in zip(weights, self._mu, strict=True))

    @property
    def rate(self) -> float:
        """**Zero, always.** See the module docstring: a change-point model
        claims the quantity is piecewise constant, so a rate is not part of
        what it asserts and inventing one would be reporting a trend the model
        does not have."""
        return 0.0

    @property
    def changepoint(self) -> float:
        """Posterior mass on a run no older than `FRESH_HOURS`.

        **The output this member exists for**: "the thing I am tracking just
        changed", on the observation it happens rather than after a decay.

        **Not `P(run length = 0)`, and that is the subtlety worth recording.**
        The obvious definition does not work, and it fails in the way that is
        hardest to notice: it returns roughly the hazard rate forever. In the
        recursion both arms multiply by the *same* predictive `pi_r(x_t)`, so
        the ratio of the change arm to the growth arm is
        `hazard / (1 - hazard)` whatever the data does - a reading that
        obliterates every existing run scales both arms down together. Measured
        on a clean step from 100 to 107, `P(r = 0)` read **0.004 before, during
        and after**, while the expected run length fell from 57.7 to 1.1.

        So the detection is in the posterior's mass moving to *small* run
        lengths, not in its mass at exactly zero. This reports that, and
        `run_length` is the same event as a single number.

        **"Small" is a duration, not a count.** The first version summed the
        first three components, which is ninety minutes at 30m and three days at
        1d - so the same number meant different questions on different feeds,
        and this class had already decided that was wrong when it added
        `run_hours`. The components now included are those whose elapsed time is
        within `FRESH_HOURS`, with `FRESH_LEAST` always included so the
        statistical floor above still holds on a series whose bars are longer
        than that.
        """
        weights = self._weights()
        if not weights:
            return 0.0
        total = 0.0
        for i, weight in enumerate(weights):
            within = i < len(self._hours) and self._hours[i] <= FRESH_HOURS
            if i <= FRESH_LEAST or within:
                total += weight
        return total

    @property
    def run_length(self) -> float:
        """Expected **observations** since the last change.

        The BOCPD quantity, kept because it is what the recursion is over -
        but it is in bars, so it is not comparable across timeframes. Use
        `run_hours` for anything that crosses one.
        """
        weights = self._weights()
        if not weights:
            return 0.0
        return sum(w * r for r, w in enumerate(weights))

    @property
    def run_hours(self) -> float:
        """Expected **hours** since the last change. The portable one.

        "This level has held for two days" means the same thing on every series;
        "this level has held for forty bars" does not. Accumulated from the
        actual elapsed time between readings, so an irregular series - which is
        what a touch series is - is handled rather than assumed away.
        """
        weights = self._weights()
        if not weights or not self._hours:
            return 0.0
        return sum(w * h for w, h in zip(weights, self._hours, strict=True))

    @property
    def sd(self) -> float:
        """Predictive standard deviation, marginalised over run lengths.

        The law of total variance across the mixture: the mean of each
        component's variance plus the variance of their means. Dropping the
        second term would understate the spread exactly when the posterior is
        split between "it held" and "it changed", which is when a caller most
        needs it.
        """
        weights = self._weights()
        if not weights:
            return math.sqrt(max(self.beta0 / max(self.alpha0 - 1.0, 1e-9), 0.0))
        middle = self.value
        total = 0.0
        for w, mu, kappa, alpha, beta in zip(
            weights, self._mu, self._kappa, self._alpha, self._beta, strict=True
        ):
            if alpha > 1.0:
                var = beta * (kappa + 1.0) / (kappa * (alpha - 1.0))
            else:
                var = beta * (kappa + 1.0) / kappa
            total += w * (var + (mu - middle) ** 2)
        return math.sqrt(max(total, 0.0))

    # ----------------------------------------------------------- the contract

    def predict(self, when: float) -> None:
        """Advance the clock. The posterior does not move without a reading.

        A piecewise-constant quantity does not drift between observations -
        that is the claim - so unlike `linear` there is nothing to propagate
        here. `existence` still decays, because an absence of evidence is
        caused by time passing whatever the model of the quantity is.
        """
        if self.at is None:
            self.at = when
            return
        hours = (when - self.at) / HOUR
        if hours <= 0.0:
            return
        if self.existence > 0.0:
            self.existence *= 0.5 ** (hours / EXISTENCE_HALF_LIFE_HOURS)
        self.at = when

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in one reading, growing and resetting the run-length posterior.

        `noise` is a **variance** per the contract, and here it sets the prior
        scale on the first reading rather than being used directly - this is
        the one member that *learns* its measurement variance.
        """
        if not math.isfinite(measured) or not math.isfinite(noise) or noise < 0.0:
            return 0.0
        if when is not None:
            self.predict(when)
        if self.at is None:
            self.at = when if when is not None else 0.0

        if not self._logp:
            # First reading: it becomes the prior's location, and `noise` its
            # scale. Returning a zero innovation matches `linear`, which takes
            # the first reading as its state rather than averaging it with a
            # prior nobody chose.
            self.beta0 = max(noise, 1e-12) * max(self.alpha0 - 1.0, 1e-9)
            self._logp = [0.0]
            self._hours = [0.0]
            self._mu = [measured]
            self._kappa = [self.kappa0]
            self._alpha = [self.alpha0]
            self._beta = [self.beta0]
            self.seen = 1
            self.existence = 1.0
            self._read_at = when if when is not None else self.at
            return 0.0

        innovation = measured - self.value
        spread = self.sd
        self.last_standardised = innovation / spread if spread > 0 else 0.0

        # The one-step predictive, before anything moves: the evidence, which
        # is what `loglike` must accumulate for this to be comparable with the
        # other members.
        weights = self._weights()
        densities = [
            _log_student_t(measured, mu, kappa, alpha, beta)
            for mu, kappa, alpha, beta in zip(
                self._mu, self._kappa, self._alpha, self._beta, strict=True
            )
        ]
        top = max(densities)
        mixed = sum(w * math.exp(d - top) for w, d in zip(weights, densities, strict=True))
        if self.seen >= self.burn and mixed > 0:
            self.loglike += math.log(mixed) + top

        # The hazard over the gap actually elapsed, rather than a fixed
        # per-reading probability: `1 - exp(-hazard * dt)` is the chance of at
        # least one change in `dt` hours under a constant-rate prior.
        elapsed = 0.0
        if when is not None and self._read_at is not None:
            elapsed = max((when - self._read_at) / HOUR, 0.0)
        risk = -math.expm1(-self.hazard * elapsed) if elapsed > 0 else 0.0
        risk = min(max(risk, 1e-12), 1.0 - 1e-12)

        if elapsed > 0:
            count = max(self.seen - 1, 1)
            self._spacing += (elapsed - self._spacing) / count
        self._advance(measured, densities, risk, elapsed)
        self.seen += 1
        self._read_at = when if when is not None else self._read_at
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)
        return innovation

    def _keep(self) -> int:
        """How many components to hold: `LIVES` regimes of **time**, capped.

        The cap is a compute budget and this is the duration it is meant to
        cover, so the conversion happens here rather than being assumed. The
        spacing comes from the readings themselves - a running mean of the gaps
        actually seen - because a member is handed one reading at a time and
        never told its timeframe.
        """
        want = LIVES / max(self.hazard, 1e-12)
        if self._spacing <= 0:
            return MAX_RUN
        return max(min(round(want / self._spacing), MAX_RUN), FRESH_LEAST + 1)

    @property
    def saturated(self) -> bool:
        """Whether the posterior is pressed against the truncation.

        When it is, `run_hours` and `run_length` are **lower bounds** rather
        than estimates: the mass that would have sat at longer runs has been
        folded into the last kept component. Published rather than assumed
        away, because the previous version of this cap was wrong on every fast
        series and nothing said so.

        **Both conditions are needed and the first version had only the
        second.** On a quiet series the posterior concentrates on the *longest*
        run length it holds, so mass at the last component is the normal state
        of affairs and means nothing on its own. It is evidence of truncation
        only once the list has actually reached the cap.
        """
        weights = self._weights()
        if not weights or len(weights) < self._keep():
            return False
        return weights[-1] > 0.01

    def _advance(
        self,
        measured: float,
        densities: list[float],
        risk: float,
        elapsed: float,
    ) -> None:
        """The run-length recursion: grow every component, collapse the rest.

        Split out of `update` because that method was doing three things - the
        evidence, the recursion and the truncation - and only the first two are
        about the model.
        """
        # Growth: every run length extends by one, with its statistics updated.
        grown_logp: list[float] = []
        grown_mu: list[float] = []
        grown_kappa: list[float] = []
        grown_alpha: list[float] = []
        grown_beta: list[float] = []
        grown_hours: list[float] = []
        survive = math.log(1.0 - risk)
        for i, logp in enumerate(self._logp):
            kappa, mu = self._kappa[i], self._mu[i]
            grown_logp.append(logp + densities[i] + survive)
            grown_kappa.append(kappa + 1.0)
            grown_mu.append((kappa * mu + measured) / (kappa + 1.0))
            grown_alpha.append(self._alpha[i] + 0.5)
            grown_beta.append(self._beta[i] + kappa * (measured - mu) ** 2 / (2.0 * (kappa + 1.0)))
            grown_hours.append(self._hours[i] + elapsed)

        # A change: all the mass that did not survive, collapsed onto run
        # length zero with the prior's statistics and this reading.
        change = math.log(risk)
        parts = [logp + d + change for logp, d in zip(self._logp, densities, strict=True)]
        best = max(parts)
        fresh_logp = best + math.log(sum(math.exp(p - best) for p in parts))

        self._logp = [fresh_logp, *grown_logp]
        self._hours = [0.0, *grown_hours]
        self._mu = [measured, *grown_mu]
        self._kappa = [self.kappa0, *grown_kappa]
        self._alpha = [self.alpha0, *grown_alpha]
        self._beta = [self.beta0, *grown_beta]

        keep = self._keep()
        if len(self._logp) > keep:
            # Truncate the tail. The mass there is folded into the last kept
            # run length rather than discarded, so nothing leaks - a posterior
            # that quietly sums to less than one is the kind of error that
            # looks like a model result.
            tail = self._logp[keep:]
            if tail:
                edge = max(tail)
                folded = edge + math.log(sum(math.exp(v - edge) for v in tail))
                last = self._logp[keep - 1]
                pair = max(last, folded)
                self._logp[keep - 1] = pair + math.log(
                    math.exp(last - pair) + math.exp(folded - pair)
                )
            self._logp = self._logp[:keep]
            self._hours = self._hours[:keep]
            self._mu = self._mu[:keep]
            self._kappa = self._kappa[:keep]
            self._alpha = self._alpha[:keep]
            self._beta = self._beta[:keep]

    def at_time(self, when: float) -> float:  # noqa: ARG002 - contract, see below
        """The posterior mean, at any horizon. **Flat, and that is the claim.**

        `when` is unused on purpose and is part of the `Filter` contract: a
        piecewise-constant quantity's best forecast is its current level at
        every horizon.

        A piecewise-constant quantity's best forecast is its current level,
        whatever the horizon - this member has no view about where it goes next,
        only about whether it has just moved. The random-walk null in the
        harnesses is flat for the same reason and beats every member here on the
        point forecast, which is worth remembering before reading this as a
        weakness.
        """
        return self.value

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:  # noqa: ARG002
        """The predictive interval. It does **not** widen with the horizon.

        Also the claim rather than an oversight: nothing drifts between
        observations in a piecewise-constant model, so there is no accumulating
        uncertainty to report. A caller needing a band that grows with elapsed
        time wants `swarm`, whose anchor wanders, or `linear`, whose covariance
        propagates.
        """
        middle = self.value
        half = sigmas * self.sd
        return (middle - half, middle + half)

    def state(self) -> tuple[float, ...]:
        return (self.value,)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return ((1.0,),)

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def covariance(self) -> tuple[tuple[float, ...], ...]:
        return ((self.sd**2,),)

    def transition(self, dt: float) -> tuple[tuple[float, ...], ...]:  # noqa: ARG002
        """Identity. The mean does not move between observations, by assumption."""
        return ((1.0,),)
