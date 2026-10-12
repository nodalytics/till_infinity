"""Direction as a discrete chain: the half of velocity that is a coin.

`family.PENDING["hmm"]` names this member and gives it a specific job rather
than asking for a discrete state for its own sake:

> velocity is two variables and only one of them is learnable. Measured on
> eurusd 4h, **speed is 8.1x as persistent as the signed rate** - the sum of
> the first five autocorrelations is +0.381 against -0.047 - and direction
> agrees with its predecessor 49.5% of the time against 50% +/- 3.1%. So the
> state wants to be `(position, log speed)` with direction as a separate
> discrete process, which is a switching model, and the HMM is the direction
> half of it.

## The prediction, written before the measurement

The same paragraph that motivates the decomposition also says direction agrees
with its predecessor **49.5% of the time against 50% +/- 3.1%**. An HMM on
direction is therefore being asked to model a fair coin, and the expected
result is that its fitted transition matrix comes out at a half, its posterior
sits at a half, and it gains nothing over one fixed coin.

Building it anyway is worth the hour: the item has been open since the package
began, the prediction is sharp enough to be wrong, and a measured null closes
it where an argument would not.

## What it cannot be compared against, and why that is not a defect

`PENDING` says "the comparison has to be on held-out likelihood rather than on
regimes it can draw", which is right and insufficient: **this member's
likelihood is over signs, not over prices.** A density on `{up, down}` cannot
be put in a table next to `linear`'s density on a level - the units differ and
the better number would be whichever quantity is easier to predict, not
whichever model is better.

So the nulls are the two that live in the same space:

* **one fair coin**, `P(up) = 1/2` fixed. The floor.
* **one fitted coin**, a single `P(up)` estimated on the training half. This
  is the null that matters, because a two-state chain that merely discovers
  the unconditional drift has learnt nothing about *sequence*.

A gain over the fitted coin is the only thing that would make a chain worth
carrying.

## The emissions are Bernoulli on the sign, and the states are what differ

Two hidden states, each with its own probability of an up move, and a
transition matrix with a hazard per hour - durations rather than per-bar
probabilities, for the reason every member here uses durations: a per-bar
transition means a different thing at 15m and at 4h.

Zero moves are **dropped rather than assigned**. A flat bar is not a direction
and splitting it evenly would invent observations; on a tick-sparse series
there can be many.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

HOUR = 3600.0

#: How long a direction regime is expected to hold, in hours. Started at a day
#: because the claim being tested is that there is no such thing.
PERSIST_HOURS = 24.0

#: The two states' initial up-probabilities. Deliberately apart, so a fit that
#: brings them together is saying something rather than starting there.
UP_RATES = (0.65, 0.35)


@dataclass(slots=True)
class Direction:
    """A two-state Markov chain over the sign of the move.

    Not a `Filter`: it forecasts a **probability**, not a level, so it carries
    `probability` and `loglike` rather than `value`, `sd` and `band`. Naming
    it a member would invite a comparison that cannot be made.
    """

    persist_hours: float = PERSIST_HOURS
    rates: tuple[float, float] = UP_RATES

    #: Posterior over the two states.
    weights: list[float] = field(default_factory=list)

    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    burn: int = 10

    def __post_init__(self) -> None:
        if not self.weights:
            self.weights = [0.5, 0.5]
        if not 0.0 < self.rates[0] < 1.0 or not 0.0 < self.rates[1] < 1.0:
            raise ValueError("an up-rate is a probability")

    @property
    def probability(self) -> float:
        """P(the next move is up), mixing the states by the posterior."""
        return sum(w * r for w, r in zip(self.weights, self.rates, strict=True))

    @property
    def regime(self) -> str:
        return "up" if self.weights[0] >= self.weights[1] else "down"

    def _switch(self, hours: float) -> float:
        """Probability of leaving a state over `hours`, from a per-hour hazard."""
        if self.persist_hours <= 0 or hours <= 0:
            return 0.0
        return -math.expm1(-hours / self.persist_hours)

    def predict(self, when: float) -> None:
        hours = 0.0
        if self.at is not None:
            hours = max((float(when) - self.at) / HOUR, 0.0)
        leave = self._switch(hours)
        first, second = self.weights
        self.weights = [
            first * (1.0 - leave) + second * leave,
            second * (1.0 - leave) + first * leave,
        ]
        self.at = float(when)

    def update(self, move: float, when: float | None = None) -> float:
        """One signed move. Returns P(up) **before** this move was seen.

        Before, because that is the forecast: a probability read after the
        outcome is folded in is not a forecast of it. The returned value is
        what a caller would have had to bet on.
        """
        if when is not None and self.at is None:
            self.at = float(when)
        if move == 0.0 or not math.isfinite(move):
            # A flat bar is not a direction. Assigning it would invent an
            # observation, and on a sparse series there are many.
            return self.probability

        forecast = self.probability
        up = move > 0
        likes = [r if up else 1.0 - r for r in self.rates]
        evidence = sum(w * k for w, k in zip(self.weights, likes, strict=True))
        if evidence <= 0:
            return forecast

        self.seen += 1
        if self.seen > self.burn:
            self.loglike += math.log(evidence)
        self.weights = [w * k / evidence for w, k in zip(self.weights, likes, strict=True)]
        total = sum(self.weights)
        self.weights = [w / total for w in self.weights] if total > 0 else [0.5, 0.5]
        return forecast


def fit(
    times: Sequence[float],
    moves: Sequence[float],
    *,
    rates=(0.55, 0.45),
    hours=(6.0, 24.0, 96.0, 480.0),
    spreads=(0.02, 0.05, 0.10, 0.20, 0.35),
) -> tuple[Direction, float]:
    """Grid-fit the chain's persistence and how far apart its two states sit.

    A grid rather than Baum-Welch, for the reason `family.PENDING` gives for
    the particle filter: the practical route is a search over the likelihood
    the model already returns. Two parameters do not need EM.

    `spreads` is the half-distance between the two states' up-rates, so a
    spread of zero is two identical states - which is one coin, and is exactly
    the null the fit should collapse to if there is no sequence to find.
    """
    best: tuple[float, Direction] = (-math.inf, Direction())
    for persist in hours:
        for spread in spreads:
            pair = (0.5 + spread, 0.5 - spread)
            member = Direction(persist_hours=persist, rates=pair)
            for when, move in zip(times, moves, strict=True):
                member.predict(when)
                member.update(move, when)
            if math.isfinite(member.loglike) and member.loglike > best[0]:
                best = (member.loglike, member)
    _ = rates
    return best[1], best[0]


def coin(moves: Sequence[float], probability: float) -> float:
    """Log-likelihood of the signs under one coin of a **given** probability.

    `probability` is required rather than defaulted. An earlier version took
    `None` to mean a fair coin and then computed the *fitted* rate in that
    branch - the opposite of what it said - which would have made the fair
    null the fitted one and hidden any gain over it.

    Pass `0.5` for the fair coin, or `up_share(train)` for a coin fitted on a
    training half. The second is the null that matters: a two-state chain
    which merely rediscovers the unconditional drift has learnt nothing about
    sequence.
    """
    signs = [m > 0 for m in moves if m != 0.0 and math.isfinite(m)]
    if not signs:
        return float("-inf")
    rate = min(max(probability, 1e-9), 1.0 - 1e-9)
    ups = sum(signs)
    return ups * math.log(rate) + (len(signs) - ups) * math.log(1.0 - rate)


def up_share(moves: Sequence[float]) -> float:
    """The share of non-zero moves that were up. For fitting the coin null."""
    signs = [1.0 if m > 0 else 0.0 for m in moves if m != 0.0 and math.isfinite(m)]
    return statistics.fmean(signs) if signs else 0.5
