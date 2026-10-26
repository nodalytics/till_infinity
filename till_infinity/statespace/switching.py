"""Balance and imbalance as two regimes, with the transition fitted not drawn.

Auction market theory says the market alternates between **balance** - price
rotating around a fair value - and **imbalance** - one side aggressive, price
leaving to find a new value. The vendor write-up in
`research/docs/statespace-from-papers.md` states two numbers without a source:
that price stays in balance about 70% of the time and reverses from balance
about 70% of the time.

Stated that way they are untestable, because "balance" is drawn on a chart
afterwards. Stated as a **switching state-space model** they are measurable:
balance is a mean-reverting state, imbalance is an integrated one, and the
transition between them is a hazard per hour that the data fits rather than an
eye picks.

This is also **I9**, the switching model `family.PENDING` has named since the
beginning, and the member `research/docs/statespace-measured.md` argues for
from the other direction: speed is 8.1x as persistent as the signed rate, so
the implied state is a continuous magnitude plus a discrete mode.

## How two regimes are filtered at once

Exactly, the posterior over regime histories doubles every reading, so after
forty bars there are a trillion of them. The standard remedy is the
**interacting multiple model**: keep one Gaussian per regime, mix them through
the transition matrix before each step, run both filters, reweight by how well
each predicted, and collapse. The approximation is in the collapse - a mixture
of two Gaussians is not a Gaussian - and it is the one every tracking system
makes.

The regimes:

* **balance** - an Ornstein-Uhlenbeck reverting to an anchor that itself moves
  slowly. This is `reverting`'s dynamics with the level as the reverting
  quantity rather than the rate. In variance-ratio terms, **VR < 1**.
* **imbalance** - a random walk. No reversion, so a move is kept. **VR = 1**,
  and it is pinned there by theory rather than estimated, which is what gives
  the other two regimes anchors - `definitions-cannot-be-states` records a
  free mixture centre collapsing onto the data.
* **trending** - a random walk plus a drift that is extrapolated. **VR > 1**.

Those are the three things the variance ratio can say, and they are the three
things a price can do. Before this regime existed, a trend was represented as
*imbalance*, which is wrong: an integrated state has VR = 1 by construction and
a trend does not. A companion measurement put the traded variance ratio at
0.980 falling to 0.924 across horizons against 1.000 on an i.i.d. control, so
all three states are things the data actually distinguishes.

## The hazards are per hour, because everything here is

`balance_hours` and `imbalance_hours` are the **expected duration** of each
regime. A probability per bar would be a different model on every timeframe -
the mistake this package audits for - so the per-step transition probability
is `1 - exp(-dt / duration)` and a 15m bar and a 1h bar agree.

## What it is for, and the claim it can settle

`balance` is the posterior probability that the market is rotating rather than
seeking. That is the testable form of the 70% claim, and it comes with the
control this desk insists on: the same reading on the Deriv synthetics, which
are generated and have no auction.

## What it does, measured - and the asymmetry in it

On a fixture that alternates 400 bars of rotation around a level with 120 bars
of trend:

| regime | during rotation | during trend |
|---|---:|---:|
| **balance** | **0.459** | **0.009** |
| imbalance | 0.296 | 0.279 |
| **trending** | 0.245 | **0.712** |

**Read every cell against 1/3, not against 1/2.** Three regimes move the
chance level, and that is what changed the original finding rather than the
model getting worse. With two regimes balance read 0.528 during rotation
against a coin - **1.06x chance**. With three it reads 0.459 against 0.333 -
**1.38x chance**. Balance detection improved; only the raw number fell.

The old asymmetry had a cause, and naming the third regime removed most of it.
A random walk fits a noisy rotation acceptably well, so the imbalance regime
kept winning likelihood that belonged to balance - but it was also the only
component that could represent a trend, so it was being paid twice. Given a
regime that actually extrapolates, balance's rejection of a trend sharpened
from 0.015 to **0.009** while trending took the trend outright at 0.712.

`imbalance` now sits flat at 0.296 against 0.279 - almost identical in both
phases - which is the internal check: this fixture contains no genuine
random-walk segment, so the walk regime *should* be indifferent between them,
and before the third state existed it was not.

Two consequences still worth stating. The 70% claim remains unsettled by this
member as parameterised, and closing that gap means fitting `theta` and the
wanders rather than asserting them. And **the trending regime still gains
+66.9 loglike over the two-regime null on 2,000 bars of driftless walk**, so
part of its advantage is flexibility rather than signal - the quotable figure
is the excess over that walk, +509.8 on pure trend, not the raw gain.

## Nothing here publishes

The null is **`reverting` alone** and **`linear` alone** on held-out
likelihood - a switching model carries more parameters and has to earn them -
and the 70% claims are scored against a matched arbitrary-price control
before either is quoted, which is what already killed "price is a magnet".

For the third regime the null is **this member with `regimes=2`**, which is
constructible for exactly that reason: a nested null that cannot be built
cannot be scored, and three of the parameters here exist only to serve a state
that has to earn them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

HOUR = 3600.0

#: Balance, imbalance, trending. An instance can be built with `regimes=2` to
#: drop the trending state, which is **the null this member is scored against**
#: - the docstring's requirement that a switching model earn its parameters is
#: not testable unless the smaller model is constructible.
STATES = 3

#: Expected duration of each regime, in **hours**. Not fitted; the harness
#: sweeps them and `diagnostics.fit_both` is the pattern for fitting.
BALANCE_HOURS = 24.0
IMBALANCE_HOURS = 4.0

#: Reversion rate of the balance regime, per hour. `ln 2 / theta` is how long
#: a dislocation inside balance takes to halve.
THETA = 0.5

#: Process noise per hour, per regime. Imbalance is noisier by construction -
#: that is what "seeking a new value" means. Trending sits between the two: it
#: explains a move through its drift rather than through noise - so the first
#: guess was that it needs *less* wander than imbalance, and that was wrong.
#:
#: **It is selected on the control, not on the fit.** With a small wander the
#: trending state degenerates, when its drift is near zero, into a
#: better-tuned random walk than imbalance itself, and then wins likelihood
#: for the wrong reason. Mean loglike gain over the two-regime null, five seeds
#: of 2,000 bars each:
#:
#: | wander | on a walk | on pure OU | on pure trend | trending: rot / trend |
#: | --- | ---: | ---: | ---: | --- |
#: | 3e-2 | **+310.8** | +44.8 | +973.5 | 0.442 / 0.806 |
#: | 1e-1 | +246.1 | +9.5 | +912.4 | 0.397 / 0.825 |
#: | **3e-1** | **+66.9** | **-53.1** | +576.7 | 0.245 / 0.712 |
#:
#: At 3e-1 the gain on a **driftless walk** falls from +311 to +67, the gain on
#: pure OU turns correctly *negative* - a trending state must lose where there
#: is no trend - and the regime separates 2.9x on the fixture against 1.8x.
#: The looser settings show a larger raw gain on real trend, but a third of it
#: is reproducible on noise, so the number to quote is the **excess over the
#: walk** and the parameter is set where that excess is cleanest.
#:
#: +66.9 is still positive, and that is stated rather than tuned away: part of
#: this state's advantage is flexibility, not signal.
BALANCE_WANDER = 1e-3
IMBALANCE_WANDER = 1e-1
TREND_WANDER = 3e-1

#: Expected duration of a trend, in hours. Between the other two, and stated
#: rather than fitted for the same reason they are.
TREND_HOURS = 8.0

#: How fast `drift` follows the realised rate. The trending regime's
#: counterpart to `anchor`: balance reverts to a slow **level**, trending
#: extrapolates a slow **rate**, and both are nuisance quantities that follow
#: the mixed estimate rather than free states - `definitions-cannot-be-states`
#: records a free mixture centre collapsing onto the data.
DRIFT_FOLLOW = 0.05


@dataclass(slots=True)
class Switching:
    """Two regimes, mixed each step. Balance reverts, imbalance walks."""

    balance_hours: float = BALANCE_HOURS
    imbalance_hours: float = IMBALANCE_HOURS
    trend_hours: float = TREND_HOURS
    #: How many regimes. `2` is the balance/imbalance model this member was
    #: before, kept constructible so it can serve as the null.
    regimes: int = STATES
    theta: float = THETA
    balance_wander: float = BALANCE_WANDER
    imbalance_wander: float = IMBALANCE_WANDER
    trend_wander: float = TREND_WANDER
    drift_follow: float = DRIFT_FOLLOW

    #: One Gaussian per regime: value and variance.
    means: list[float] = field(default_factory=list)
    variances: list[float] = field(default_factory=list)
    #: Posterior over regimes. `weights[0]` balance, `[1]` imbalance,
    #: `[2]` trending.
    weights: list[float] = field(default_factory=list)
    #: What balance reverts to, which itself drifts with the mixed estimate.
    anchor: float = 0.0
    #: What trending extrapolates, per hour. An EWMA of the realised rate of
    #: the mixed estimate, so it is a nuisance quantity like `anchor`.
    drift: float = 0.0
    #: Previous mixed estimate and its time, for measuring that rate.
    before: float = 0.0
    before_at: float | None = None

    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    burn: int = 10
    existence: float = 1.0
    last_standardised: float = 0.0

    def __post_init__(self) -> None:
        if not self.means:
            self.means = [0.0] * self.regimes
        if not self.variances:
            self.variances = [1.0] * self.regimes
        if not self.weights:
            self.weights = [1.0 / self.regimes] * self.regimes
        # A longer restored state wins over the field, so a three-regime save
        # loaded into a default instance keeps all three.
        self.regimes = max(self.regimes, len(self.weights))
        # **A restored two-regime state is padded rather than rejected.** This
        # member was two regimes before it was three, so saved state in the
        # wild is short. Padding copies the imbalance component and renormalises,
        # which starts the new regime from a live estimate instead of a stale
        # zero, and `seen` keeps its history.
        while len(self.means) < self.regimes:
            self.means.append(self.means[-1])
        while len(self.variances) < self.regimes:
            self.variances.append(self.variances[-1])
        while len(self.weights) < self.regimes:
            self.weights.append(0.0)
        total = sum(self.weights)
        if total > 0:
            self.weights = [w / total for w in self.weights]
        else:
            self.weights = [1.0 / self.regimes] * self.regimes

    # ------------------------------------------------------------- the reading

    @property
    def balance(self) -> float:
        """Posterior probability the market is rotating rather than seeking.

        **The testable form of the 70% claim.** Averaged over a series this is
        the share of time in balance, and it comes with a control: the Deriv
        synthetics are generated and have no auction, so a reading that is the
        same there is a reading of the model rather than of the market.
        """
        return self.weights[0]

    @property
    def seeking(self) -> float:
        """Posterior probability of imbalance - a **random walk**, VR = 1.

        Named for what it is rather than for "not balance". Before the trending
        regime existed this component absorbed trends too, because a walk fits
        a trend better than an Ornstein-Uhlenbeck does, and that is why
        `balance` was sharp about imbalance and weak about balance.
        """
        return self.weights[1]

    @property
    def trending(self) -> float:
        """Posterior probability of a **drift**, which is VR > 1.

        The state that had no representation here. `regime-granularity.md`'s
        companion measurement put the variance ratio at 0.980 to 0.924 on
        traded closes and 1.000 on an i.i.d. control, and the three regimes are
        exactly the three things that statistic can say: below one is balance,
        **one is imbalance**, above one is trending. The middle state is
        therefore pinned by theory rather than estimated, which is what gives
        the other two anchors - `definitions-cannot-be-states`.

        This is a reading, not a direction: it says a drift exists, and
        `direction-is-closed-not-just-null` priced the sign of one at 2% of a
        spread.
        """
        return self.weights[2] if self.regimes > 2 else 0.0

    @property
    def value(self) -> float:
        return sum(w * m for w, m in zip(self.weights, self.means, strict=True))

    @property
    def rate(self) -> float:
        return 0.0

    @property
    def sd(self) -> float:
        """Spread of the **mixture**, not of either regime.

        A mixture's variance carries the spread *between* the components as
        well as within them, and dropping that term is how a switching model
        reports confidence it does not have: two regimes disagreeing about
        where the value is *is* uncertainty.
        """
        middle = self.value
        total = sum(
            w * (v + (m - middle) ** 2)
            for w, m, v in zip(self.weights, self.means, self.variances, strict=True)
        )
        return math.sqrt(max(total, 0.0))

    def state(self) -> tuple[float, ...]:
        return (self.value, *self.weights[1:])

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return ((1.0, *(0.0 for _ in self.weights[1:])),)

    def at_time(self, when: float) -> float:
        """Each regime projected forward, then mixed by the regime posterior.

        Balance decays toward its anchor and imbalance holds, so a market the
        model thinks is balanced forecasts back to value and one it thinks is
        imbalanced forecasts flat. That difference is the whole point of
        carrying two regimes rather than one averaged set of dynamics.
        """
        elapsed = 0.0
        if self.at is not None:
            elapsed = max((float(when) - self.at) / HOUR, 0.0)
        keep = math.exp(-self.theta * elapsed)
        ahead = [self.anchor + keep * (self.means[0] - self.anchor), self.means[1]]
        if self.regimes > 2:
            ahead.append(self.means[2] + self.drift * elapsed)
        return sum(w * m for w, m in zip(self.weights, ahead, strict=True))

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        elapsed = 0.0
        if self.at is not None:
            elapsed = max((float(when) - self.at) / HOUR, 0.0)
        grown = [
            self.variances[0] + self.balance_wander * elapsed,
            self.variances[1] + self.imbalance_wander * elapsed,
        ]
        if self.regimes > 2:
            grown.append(self.variances[2] + self.trend_wander * elapsed)
        middle = self.at_time(when)
        total = sum(
            w * (v + (m - middle) ** 2)
            for w, m, v in zip(self.weights, self.means, grown, strict=True)
        )
        half = sigmas * math.sqrt(max(total, 0.0))
        return (middle - half, middle + half)

    # ------------------------------------------------------------- the filter

    def _switch(self, dt: float) -> list[list[float]]:
        """Transition matrix over `dt` hours. **Durations, not per-bar odds.**

        Leaving a regime is `1 - exp(-dt / duration)` as before, and with three
        regimes that mass is split **uniformly over the other two**. That is
        one stated assumption and no new parameters: a destination prior would
        be three more numbers to fit, and nothing here has measured them. So
        `row[i][i]` is still the staying probability and the off-diagonal of a
        row still sums to the leaving probability - which is the invariant to
        assert, rather than any single off-diagonal entry.
        """
        hours = (self.balance_hours, self.imbalance_hours, self.trend_hours)
        rows = []
        for i in range(self.regimes):
            leave = -math.expm1(-dt / max(hours[i], 1e-9))
            share = leave / max(self.regimes - 1, 1)
            rows.append([1.0 - leave if j == i else share for j in range(self.regimes)])
        return rows

    def predict(self, when: float, control: float = 0.0) -> None:  # noqa: ARG002
        if self.at is None:
            self.at = float(when)
            return
        dt = (float(when) - self.at) / HOUR
        self.at = float(when)
        if dt <= 0.0:
            return

        switch = self._switch(dt)
        # **Mixing, which is what makes this an IMM rather than two filters.**
        # Each regime's prior is the transition-weighted mixture of both
        # posteriors, so a regime that has just become likely inherits the
        # other's estimate instead of starting from its own stale one.
        mixed_weights = [
            sum(self.weights[i] * switch[i][j] for i in range(self.regimes))
            for j in range(self.regimes)
        ]
        means, variances = [], []
        for j in range(self.regimes):
            if mixed_weights[j] <= 0:
                means.append(self.means[j])
                variances.append(self.variances[j])
                continue
            share = [self.weights[i] * switch[i][j] / mixed_weights[j] for i in range(self.regimes)]
            middle = sum(share[i] * self.means[i] for i in range(self.regimes))
            spread = sum(
                share[i] * (self.variances[i] + (self.means[i] - middle) ** 2)
                for i in range(self.regimes)
            )
            means.append(middle)
            variances.append(spread)
        self.weights = mixed_weights

        # Then each regime's own dynamics: balance reverts to its anchor,
        # imbalance holds, trending extrapolates its drift. Those are the three
        # things a price can do, and the middle one is pinned at a walk.
        keep = math.exp(-self.theta * dt)
        ahead = [self.anchor + keep * (means[0] - self.anchor), means[1]]
        spreads = [
            keep * keep * variances[0] + self.balance_wander * dt,
            variances[1] + self.imbalance_wander * dt,
        ]
        if self.regimes > 2:
            ahead.append(means[2] + self.drift * dt)
            spreads.append(variances[2] + self.trend_wander * dt)
        self.means, self.variances = ahead[: self.regimes], spreads[: self.regimes]

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        if when is not None and self.at is None:
            self.at = float(when)
        if self.seen == 0:
            self.means = [measured] * self.regimes
            self.variances = [max(noise, 1e-12)] * self.regimes
            self.anchor = measured
            self.drift = 0.0
            self.before = measured
            self.before_at = self.at
            self.seen = 1
            self.existence = 1.0
            return 0.0

        innovation = measured - self.value

        # **The predictive spread, taken before anything is updated.** A
        # residual is a pre-update quantity: it asks how surprising the
        # reading was given what the member believed *beforehand*. This
        # divided by `self.sd` read after the component updates and the
        # reweighting, which is the **posterior** spread and excludes `R`
        # entirely - so the standardised residual shrank as the measurement
        # noise grew, which is backwards, and it was not comparable with any
        # other member's.
        #
        # For a mixture the predictive variance carries the spread *between*
        # the components as well as within them, plus `R`.
        middle = self.value
        predictive = sum(
            w * (v + max(noise, 0.0) + (m - middle) ** 2)
            for w, m, v in zip(self.weights, self.means, self.variances, strict=True)
        )

        likes = []
        for j in range(self.regimes):
            s = self.variances[j] + max(noise, 0.0)
            if s <= 0:
                likes.append(0.0)
                continue
            gap = measured - self.means[j]
            likes.append(math.exp(-0.5 * gap * gap / s) / math.sqrt(2.0 * math.pi * s))
            gain = self.variances[j] / s
            self.means[j] += gain * gap
            self.variances[j] = (1.0 - gain) * self.variances[j]

        # Reweight by how well each regime predicted. This is the only place
        # the data chooses the regime, and it is why the transition durations
        # are a prior rather than a decision.
        total = sum(w * k for w, k in zip(self.weights, likes, strict=True))
        if total > 0:
            self.weights = [w * k / total for w, k in zip(self.weights, likes, strict=True)]
            if self.seen >= self.burn:
                self.loglike += math.log(total)

        spread = math.sqrt(max(predictive, 0.0))
        self.last_standardised = innovation / spread if spread > 0 else 0.0
        # The anchor follows the mixed estimate slowly: fair value moves, but
        # not as fast as price, or balance would have nothing to revert to.
        self.anchor += 0.01 * (self.value - self.anchor)
        # **The drift is measured from the mixed estimate, not from price.**
        # Price carries the measurement noise; the mixture has had it filtered
        # out, so a drift read off price would chase `R` and make the trending
        # regime win on noise. Per hour, so a 15m and a 1h bar agree - the same
        # reason the durations are hours.
        if self.before_at is not None and self.at is not None:
            span = (self.at - self.before_at) / HOUR
            if span > 0:
                rate = (self.value - self.before) / span
                self.drift += self.drift_follow * (rate - self.drift)
        self.before = self.value
        self.before_at = self.at
        self.seen += 1
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)
        return innovation
