"""Online learners, and the discipline that makes their scores mean something.

Everything in this package that learns does so from outcomes arriving one at a
time, and the models below are the plainest possible version of that: a linear
regressor and a logistic classifier, both updated by stochastic gradient, both
scoring themselves **predict-then-update**.

That order is the whole point and it is not a detail. A model scored on data it
has already trained on reports how well it memorised; a model that must predict
before it is told the answer reports what it would have said at the time. Every
number this package has ever had to withdraw came from getting that wrong in
one form or another, so it is enforced here rather than left to each caller:
`observe` returns the prediction it made *before* learning, and the running
score is built from those.

## Why linear, when there is already a kNN

Because nothing has ever checked whether the kNN is buying anything. It is the
model behind every level call, it has never been compared with a baseline, and
a kNN that merely matches a linear model on the same features is unjustified
complexity in the most important path in the system.

A linear model also has a property the kNN structurally cannot have: its
weights are readable. "Which of these nine features carries the signal" is a
question the neighbour vote cannot answer at all, and this one answers by
printing a vector.

Two outcomes are worth having and one of them is negative:

* the linear model matches the kNN - then the kNN is complexity with no
  return, and simplifying is a straightforward win;
* both sit at chance - then the features do not carry the signal, which is a
  finding about the *features* and no amount of model will fix it.

## Standardisation, online

Features arrive on different scales - `experience` is log-compressed touches,
`regime` is in [0, 1], `approach_vol` is unbounded. Gradient descent on raw
inputs lets whichever feature happens to be largest dominate the step, so each
input is standardised by a running mean and variance (Welford), which needs no
second pass and no stored history.

The standardiser updates from every observation **including the ones it has not
yet been given an answer for**, which is fine: knowing the distribution of the
inputs is not knowing the outcome, and refusing that would mean standardising
from nothing on the first example.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from .state import Restorable

#: How fast the weights move. Small, because the alternative to converging
#: slowly here is a model whose reported score is mostly its own thrashing.
LEARNING_RATE = 0.03

#: Ridge penalty. Not tuned - present so a feature that appears rarely cannot
#: acquire an enormous weight from the handful of examples that carry it.
DECAY = 1e-4

#: How much of the running score is the recent past. A model that improves
#: should be allowed to show it, and a lifetime average hides that for as long
#: as the lifetime is.
SCORE_MEMORY = 2_000.0


@dataclass(slots=True)
class Scaler(Restorable):
    """Running mean and variance per input, by Welford's method."""

    n: float = 0.0
    mean: list[float] = field(default_factory=list)
    m2: list[float] = field(default_factory=list)

    def observe(self, x: Sequence[float]) -> None:
        if not self.mean:
            self.mean = [0.0] * len(x)
            self.m2 = [0.0] * len(x)
        if len(x) != len(self.mean):
            return
        self.n += 1.0
        for i, value in enumerate(x):
            delta = value - self.mean[i]
            self.mean[i] += delta / self.n
            self.m2[i] += delta * (value - self.mean[i])

    def apply(self, x: Sequence[float]) -> list[float]:
        """Standardised, or the raw values while there is nothing to scale by."""
        if self.n < 2 or len(x) != len(self.mean):
            return list(x)
        out: list[float] = []
        for i, value in enumerate(x):
            sd = math.sqrt(self.m2[i] / (self.n - 1.0))
            out.append((value - self.mean[i]) / sd if sd > 1e-12 else 0.0)
        return out


@dataclass(slots=True)
class Linear(Restorable):
    """Online least squares. `predict` before `learn`, always.

    Used for a *quantity* - a forward return, a push size - as opposed to a
    yes-or-no, which is `Logistic`.
    """

    rate: float = LEARNING_RATE
    decay: float = DECAY
    weights: list[float] = field(default_factory=list)
    bias: float = 0.0
    scaler: Scaler = field(default_factory=Scaler)
    #: Decayed sums for a walk-forward R^2: the model's squared error against
    #: the error of predicting the running mean, which is the honest null.
    seen: float = 0.0
    error: float = 0.0
    variance: float = 0.0
    mean: float = 0.0

    def predict(self, x: Sequence[float]) -> float:
        z = self.scaler.apply(x)
        if not self.weights:
            return self.bias
        if len(z) != len(self.weights):
            return self.bias
        return self.bias + sum(w * v for w, v in zip(self.weights, z, strict=True))

    def observe(self, x: Sequence[float], y: float) -> float:
        """Predict, score, then learn. Returns what it said beforehand."""
        self.scaler.observe(x)
        if not self.weights:
            self.weights = [0.0] * len(x)
        said = self.predict(x)

        # Scored against predicting the running mean, which is what "explains
        # nothing" looks like. Decayed so an improving model can show it.
        keep = max(0.0, 1.0 - 1.0 / SCORE_MEMORY)
        self.seen = self.seen * keep + 1.0
        self.error = self.error * keep + (y - said) ** 2
        self.variance = self.variance * keep + (y - self.mean) ** 2
        self.mean += (y - self.mean) / self.seen

        z = self.scaler.apply(x)
        residual = y - said
        for i, value in enumerate(z):
            self.weights[i] += self.rate * (residual * value - self.decay * self.weights[i])
        self.bias += self.rate * residual
        return said

    @property
    def r2(self) -> float:
        """Walk-forward R^2. Negative means worse than predicting the mean."""
        if self.variance <= 1e-12:
            return 0.0
        return 1.0 - self.error / self.variance

    @property
    def warm(self) -> bool:
        return self.seen >= 30.0


@dataclass(slots=True)
class Logistic(Restorable):
    """Online logistic regression - the baseline the kNN has never been given.

    Scores itself on **log loss** and on accuracy, both walk-forward. Log loss
    rather than accuracy alone because a model that is right 55% of the time
    while being certain about the 45% is worse than one that is right 55% of
    the time and says so, and accuracy cannot tell them apart.
    """

    rate: float = LEARNING_RATE
    decay: float = DECAY
    weights: list[float] = field(default_factory=list)
    bias: float = 0.0
    scaler: Scaler = field(default_factory=Scaler)
    seen: float = 0.0
    loss: float = 0.0
    right: float = 0.0
    #: The base rate, so accuracy can be read against always guessing it.
    positives: float = 0.0

    def predict(self, x: Sequence[float]) -> float:
        """Probability of the positive class, in (0, 1)."""
        z = self.scaler.apply(x)
        if not self.weights or len(z) != len(self.weights):
            return 0.5
        raw = self.bias + sum(w * v for w, v in zip(self.weights, z, strict=True))
        # Clamped before exp, or a confident model on a surprising example
        # overflows and the whole learner dies on one row.
        raw = max(-30.0, min(30.0, raw))
        return 1.0 / (1.0 + math.exp(-raw))

    def observe(self, x: Sequence[float], y: bool) -> float:
        """Predict, score, then learn. Returns the probability it said."""
        self.scaler.observe(x)
        if not self.weights:
            self.weights = [0.0] * len(x)
        said = self.predict(x)
        target = 1.0 if y else 0.0

        keep = max(0.0, 1.0 - 1.0 / SCORE_MEMORY)
        self.seen = self.seen * keep + 1.0
        safe = min(max(said, 1e-9), 1.0 - 1e-9)
        self.loss = self.loss * keep + -(
            target * math.log(safe) + (1 - target) * math.log(1 - safe)
        )
        self.right = self.right * keep + (1.0 if (said >= 0.5) == y else 0.0)
        self.positives = self.positives * keep + target

        z = self.scaler.apply(x)
        residual = target - said
        for i, value in enumerate(z):
            self.weights[i] += self.rate * (residual * value - self.decay * self.weights[i])
        self.bias += self.rate * residual
        return said

    @property
    def accuracy(self) -> float:
        return self.right / self.seen if self.seen else 0.0

    @property
    def base_rate(self) -> float:
        """What always guessing the commoner class would score."""
        if not self.seen:
            return 0.5
        share = self.positives / self.seen
        return max(share, 1.0 - share)

    @property
    def log_loss(self) -> float:
        return self.loss / self.seen if self.seen else 0.0

    @property
    def edge(self) -> float:
        """Accuracy above the base rate. Zero means it has learned nothing.

        The number that matters, and the one an accuracy alone hides: 63%
        accuracy on a problem whose base rate is 63% is a model that has
        discovered which answer is commoner.
        """
        return self.accuracy - self.base_rate

    @property
    def warm(self) -> bool:
        return self.seen >= 30.0

    def importance(self, names: Sequence[str]) -> list[tuple[str, float]]:
        """Which features carry the signal, largest first.

        The thing the neighbour vote structurally cannot report. Weights are on
        standardised inputs, so they are directly comparable to each other -
        which is the only reason this is meaningful rather than a list of
        numbers on nine different scales.
        """
        if len(names) != len(self.weights):
            return []
        return sorted(zip(names, self.weights, strict=True), key=lambda kv: -abs(kv[1]))
