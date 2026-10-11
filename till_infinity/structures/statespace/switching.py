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
  quantity rather than the rate.
* **imbalance** - a random walk. No reversion, so a move is kept.

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

| | P(balance) |
|---|---|
| during rotation | **0.528** |
| during trend | **0.015** |

**It detects imbalance almost perfectly and balance only weakly.** During a
trend it is 98.5% sure, which is as crisp as this kind of model gets. During
rotation it is barely past a coin.

The asymmetry is not a bug and it is the same finding this desk keeps
producing from other directions: **a random walk is hard to beat**. The
imbalance regime *is* a random walk, and a random walk fits a noisy rotation
acceptably well - so it keeps winning likelihood that belongs to balance.
Trending, by contrast, is something a reverting model genuinely cannot do, so
the evidence against balance is decisive.

Two consequences worth stating. The `balance` reading should be used as
**evidence of imbalance** rather than evidence of balance, because only one
direction is sharp. And the 70% claim cannot be settled by this member as
parameterised: it reports 0.461 where the fixture is 0.870, and closing that
gap means fitting `theta` and the wanders rather than asserting them.

## Nothing here publishes

The null is **`reverting` alone** and **`linear` alone** on held-out
likelihood - a switching model carries more parameters and has to earn them -
and the 70% claims are scored against a matched arbitrary-price control
before either is quoted, which is what already killed "price is a magnet".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

HOUR = 3600.0

#: Expected duration of each regime, in **hours**. Not fitted; the harness
#: sweeps them and `diagnostics.fit_both` is the pattern for fitting.
BALANCE_HOURS = 24.0
IMBALANCE_HOURS = 4.0

#: Reversion rate of the balance regime, per hour. `ln 2 / theta` is how long
#: a dislocation inside balance takes to halve.
THETA = 0.5

#: Process noise per hour, per regime. Imbalance is noisier by construction -
#: that is what "seeking a new value" means.
BALANCE_WANDER = 1e-3
IMBALANCE_WANDER = 1e-1


@dataclass(slots=True)
class Switching:
    """Two regimes, mixed each step. Balance reverts, imbalance walks."""

    balance_hours: float = BALANCE_HOURS
    imbalance_hours: float = IMBALANCE_HOURS
    theta: float = THETA
    balance_wander: float = BALANCE_WANDER
    imbalance_wander: float = IMBALANCE_WANDER

    #: One Gaussian per regime: value and variance.
    means: list[float] = field(default_factory=list)
    variances: list[float] = field(default_factory=list)
    #: Posterior over regimes. `weights[0]` is balance.
    weights: list[float] = field(default_factory=list)
    #: What balance reverts to, which itself drifts with the mixed estimate.
    anchor: float = 0.0

    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    burn: int = 10
    existence: float = 1.0
    last_standardised: float = 0.0

    def __post_init__(self) -> None:
        if not self.means:
            self.means = [0.0, 0.0]
        if not self.variances:
            self.variances = [1.0, 1.0]
        if not self.weights:
            self.weights = [0.5, 0.5]

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
        return (self.value, self.weights[0])

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return ((1.0, 0.0),)

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
        reverted = self.anchor + keep * (self.means[0] - self.anchor)
        return self.weights[0] * reverted + self.weights[1] * self.means[1]

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        elapsed = 0.0
        if self.at is not None:
            elapsed = max((float(when) - self.at) / HOUR, 0.0)
        grown = [
            self.variances[0] + self.balance_wander * elapsed,
            self.variances[1] + self.imbalance_wander * elapsed,
        ]
        middle = self.at_time(when)
        total = sum(
            w * (v + (m - middle) ** 2)
            for w, m, v in zip(self.weights, self.means, grown, strict=True)
        )
        half = sigmas * math.sqrt(max(total, 0.0))
        return (middle - half, middle + half)

    # ------------------------------------------------------------- the filter

    def _switch(self, dt: float) -> list[list[float]]:
        """Transition matrix over `dt` hours. **Durations, not per-bar odds.**"""
        leave_balance = -math.expm1(-dt / max(self.balance_hours, 1e-9))
        leave_imbalance = -math.expm1(-dt / max(self.imbalance_hours, 1e-9))
        return [
            [1.0 - leave_balance, leave_balance],
            [leave_imbalance, 1.0 - leave_imbalance],
        ]

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
        mixed_weights = [sum(self.weights[i] * switch[i][j] for i in range(2)) for j in range(2)]
        means, variances = [], []
        for j in range(2):
            if mixed_weights[j] <= 0:
                means.append(self.means[j])
                variances.append(self.variances[j])
                continue
            share = [self.weights[i] * switch[i][j] / mixed_weights[j] for i in range(2)]
            middle = sum(share[i] * self.means[i] for i in range(2))
            spread = sum(
                share[i] * (self.variances[i] + (self.means[i] - middle) ** 2) for i in range(2)
            )
            means.append(middle)
            variances.append(spread)
        self.weights = mixed_weights

        # Then each regime's own dynamics.
        keep = math.exp(-self.theta * dt)
        self.means = [
            self.anchor + keep * (means[0] - self.anchor),
            means[1],
        ]
        self.variances = [
            keep * keep * variances[0] + self.balance_wander * dt,
            variances[1] + self.imbalance_wander * dt,
        ]

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        if when is not None and self.at is None:
            self.at = float(when)
        if self.seen == 0:
            self.means = [measured, measured]
            self.variances = [max(noise, 1e-12)] * 2
            self.anchor = measured
            self.seen = 1
            self.existence = 1.0
            return 0.0

        innovation = measured - self.value
        likes = []
        for j in range(2):
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

        spread = self.sd
        self.last_standardised = innovation / spread if spread > 0 else 0.0
        # The anchor follows the mixed estimate slowly: fair value moves, but
        # not as fast as price, or balance would have nothing to revert to.
        self.anchor += 0.01 * (self.value - self.anchor)
        self.seen += 1
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)
        return innovation
