"""Predict the order, then map the order to the value.

Kretschmer, Harrieder, Witting and Böcker, *Times are changing but order
matters*, Nature Methods (2026). Reviewed on 2026-10-11 and built the same day,
because the pre-test it suggested came back saying the premise holds here.

## The argument

Predicting chromatographic retention times across laboratories fails because the
*times* do not transfer between instruments - but the *order* does. So the paper
splits one task into two: a model learns a scale-free **order index** from
pairwise comparisons, with the laboratory's conditions as input features; then a
low-degree polynomial maps that index onto absolute times, fitted on a handful
of **anchors** measured in the target system. The result transfers to systems
with no training data at all, beating models that *were* trained on them.

This desk already had the result in miniature and did not generalise it: over
293,252 live resolutions a level's raw record scores **AUC 0.5005** while
`|record - 0.5|` scores **0.6006**. A monotone transformation of the same
number carried everything the number itself did not.

## Why it is built here, and what it is allowed to predict

`research/docs/informatory-pairs.md` ran the paper's own pre-test before any of
this was written, and it settled three design questions that would otherwise
have been guesses:

* **The target is magnitude, not direction.** Across six window and horizon
  combinations, at most **6 of 45** bin pairs could be ordered by their mean
  *signed* outcome at two standard errors, and in two of them not one could.
  There is no ordering of direction to learn. Magnitude orders fine, 15 to 34
  of 45.
* **One model spans every instrument and resolution.** Instrument reads 5.1%
  informatory and timeframe 0.0%, so orderings transfer and per-instrument
  models buy almost nothing - which is the paper's transferability claim,
  measured here before relying on it.
* **Volatility regime and session are conditions, not separate models.** They
  read 47.1% and 23.4% informatory, so they *do* change the ordering and belong
  as **input features** - exactly how the paper treats column and pH.

## The two pieces

`Ranker` is a linear RankNet. It has **no intercept**, because a constant
cancels in every pairwise difference and fitting one would be fitting a
parameter the loss cannot see. It learns from pairs, and a pair closer together
than `margin` is **not compared at all** - the paper's ten-second rule, which
exists so the model is not taught estimation error. Here the natural margin is
one spread, which puts the cost model inside the loss rather than beside it.

`Mapping` turns a score into a quantity, fitted on anchors from the target
series by median regression and then least squares on the inliers. Degree two,
because the paper measured degree two against generalised additive models,
shape-constrained additive models and constrained B-splines, and the simplest
one won.

## What this is not

**Not a member of the filter family.** It answers a point estimate, not a
predictive distribution, so it cannot be scored on held-out likelihood against
`linear` and it is not in `members()`. It is a model over features, like
`structures/learning`, and it is here because the features and the portability
rules are here.

**Not published.** The null is `research/ideas/rank_then_map.py`: a trailing
standard deviation, which has beaten every volatility model tried on this desk,
plus the two the paper itself implies - per-instrument models, and predicting
the value in one step.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

#: Default learning rate for the pairwise updates. Small, because the loss is
#: over pairs and a pass sees `O(n)` of them.
RATE = 0.01

#: Pairs whose outcomes differ by less than this are not compared. Zero means
#: compare everything, which is what teaching a model estimation error looks
#: like - the caller is expected to pass a cost or a noise floor.
MARGIN = 0.0

#: Iterations of the robust fit in `Mapping`.
ROUNDS = 12


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-min(value, 700.0)))
    got = math.exp(max(value, -700.0))
    return got / (1.0 + got)


@dataclass(slots=True)
class Ranker:
    """A scale-free score whose **ordering** is what is learned.

    `score(x)` is meaningless on its own - only differences between scores mean
    anything, which is the point: an index that transfers cannot carry a scale,
    because the scale is the thing that does not transfer.
    """

    #: One weight per feature. No intercept: a constant cancels in every
    #: pairwise difference, so the loss cannot see it and fitting one is
    #: fitting noise.
    weights: list[float] = field(default_factory=list)
    rate: float = RATE
    #: Outcomes closer than this are not compared. See the module docstring.
    margin: float = MARGIN
    #: Pairs used and pairs skipped as too close, so the margin's effect is
    #: observable rather than assumed.
    used: int = 0
    skipped: int = 0

    def score(self, features: Sequence[float]) -> float:
        if not self.weights:
            self.weights = [0.0] * len(features)
        return sum(w * x for w, x in zip(self.weights, features, strict=True))

    def learn(
        self,
        left: Sequence[float],
        left_value: float,
        right: Sequence[float],
        right_value: float,
    ) -> bool:
        """One pairwise update. `True` when the pair was close enough to use.

        The RankNet loss: with `d = score(left) - score(right)` and the true
        order `t` in `{+1, -1}`, the gradient of `log(1 + exp(-t d))` with
        respect to `d` is `-t * sigmoid(-t d)`, so a pair the model already
        orders confidently contributes almost nothing and a pair it gets wrong
        contributes almost all of it.

        **Weighted by how far apart the outcomes are**, through a `tanh` of the
        gap over the margin. The hard threshold removes pairs that are noise;
        this stops a pair just past the threshold counting as much as one at the
        other end of the distribution.
        """
        gap = left_value - right_value
        if abs(gap) <= self.margin:
            self.skipped += 1
            return False
        if not self.weights:
            self.weights = [0.0] * len(left)

        target = 1.0 if gap > 0 else -1.0
        difference = self.score(left) - self.score(right)
        push = target * _sigmoid(-target * difference)
        weight = math.tanh(abs(gap) / self.margin) if self.margin > 0 else 1.0
        step = self.rate * push * weight
        for i, (a, b) in enumerate(zip(left, right, strict=True)):
            self.weights[i] += step * (a - b)
        self.used += 1
        return True

    def fit(
        self,
        rows: Sequence[tuple[Sequence[float], float]],
        epochs: int = 3,
        pairs: int = 20_000,
        seed: int = 0,
    ) -> None:
        """Sample random pairs and learn from them.

        Random pairs rather than all of them: the full set is `O(n^2)` and the
        paper's own training samples too. Pairs are drawn **within** whatever
        the caller passed, so a caller wanting comparisons only inside a
        condition should pass one condition at a time.
        """
        if len(rows) < 2:
            return
        rng = random.Random(seed)
        for _ in range(epochs):
            for _ in range(pairs):
                left = rng.randrange(len(rows))
                right = rng.randrange(len(rows))
                if left == right:
                    continue
                self.learn(rows[left][0], rows[left][1], rows[right][0], rows[right][1])


def _polynomial(coefficients: Sequence[float], value: float) -> float:
    return sum(c * value**k for k, c in enumerate(coefficients))


def _least_squares(
    xs: Sequence[float], ys: Sequence[float], degree: int, weights: Sequence[float]
) -> list[float]:
    """Weighted least squares on a polynomial basis, by normal equations.

    Degree two means a 3x3 system, which is small enough that Gaussian
    elimination here is clearer than a dependency.
    """
    size = degree + 1
    matrix = [[0.0] * (size + 1) for _ in range(size)]
    for x, y, w in zip(xs, ys, weights, strict=True):
        powers = [x**k for k in range(size)]
        for i in range(size):
            for j in range(size):
                matrix[i][j] += w * powers[i] * powers[j]
            matrix[i][size] += w * powers[i] * y
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(matrix[r][col]))
        if abs(matrix[pivot][col]) < 1e-12:
            return [0.0] * size
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        for row in range(size):
            if row == col:
                continue
            factor = matrix[row][col] / matrix[col][col]
            for k in range(col, size + 1):
                matrix[row][k] -= factor * matrix[col][k]
    return [matrix[i][size] / matrix[i][i] for i in range(size)]


@dataclass(slots=True)
class Mapping:
    """Score to quantity, fitted on anchors, robustly.

    Median regression first, then least squares on the inliers. The paper
    measured this against generalised additive models, shape-constrained
    additive models and constrained B-splines, and the degree-two polynomial
    won - which is the usual result here too and the reason it is not a spline.
    """

    coefficients: list[float] = field(default_factory=list)
    degree: int = 2
    #: Whether the fit had to fall back to a straight line. See `fit`.
    straightened: bool = False
    #: The anchor range the fit was made over, so a caller can see when it is
    #: extrapolating rather than interpolating.
    low: float = 0.0
    high: float = 0.0

    def fit(self, scores: Sequence[float], values: Sequence[float]) -> None:
        """Fit on anchors. Needs `degree + 2` of them; a handful is enough."""
        if len(scores) < self.degree + 2:
            return
        self.low, self.high = min(scores), max(scores)
        weights = [1.0] * len(scores)
        coefficients = _least_squares(scores, values, self.degree, weights)
        # Median regression, as iteratively reweighted least squares with
        # weights `1/|residual|`. A mis-annotated anchor is the failure the
        # paper names, and squared error hands it the fit.
        for _ in range(ROUNDS):
            residuals = [
                abs(y - _polynomial(coefficients, x)) for x, y in zip(scores, values, strict=True)
            ]
            scale = max(sorted(residuals)[len(residuals) // 2], 1e-9)
            weights = [1.0 / max(r, 0.1 * scale) for r in residuals]
            coefficients = _least_squares(scores, values, self.degree, weights)

        # Then least squares on the inliers, which is the paper's combination:
        # the robust fit decides who is an outlier, the efficient fit uses the
        # rest.
        residuals = [
            abs(y - _polynomial(coefficients, x)) for x, y in zip(scores, values, strict=True)
        ]
        cut = 3.0 * max(sorted(residuals)[len(residuals) // 2], 1e-9)
        keep = [r <= cut for r in residuals]
        if sum(keep) >= self.degree + 2:
            inliers = [1.0 if k else 0.0 for k in keep]
            coefficients = _least_squares(scores, values, self.degree, inliers)

        self.coefficients = coefficients
        self.straightened = False
        if self.degree >= 2 and not self._monotone():
            # **A quantity that rises with rank must not fall again.** A
            # degree-two polynomial has a turning point, and with anchors
            # clustered at one end it can land inside the range - which would
            # make the map say a higher rank means a smaller move. The paper
            # does not enforce this; here the fallback is a straight line, and
            # the flag says it happened rather than hiding it.
            self.coefficients = _least_squares(scores, values, 1, [1.0] * len(scores))
            self.straightened = True

    def _monotone(self) -> bool:
        """Does the fit rise all the way across the anchors' own range?"""
        if len(self.coefficients) < 3 or abs(self.coefficients[2]) < 1e-15:
            return True
        turning = -self.coefficients[1] / (2.0 * self.coefficients[2])
        return not (self.low < turning < self.high)

    def __call__(self, score: float) -> float:
        if not self.coefficients:
            return 0.0
        return _polynomial(self.coefficients, score)


@dataclass(slots=True)
class RankThenMap:
    """The two steps together: a global ranker and a per-series mapping."""

    ranker: Ranker = field(default_factory=Ranker)
    mapping: Mapping = field(default_factory=Mapping)

    def anchor(self, rows: Sequence[tuple[Sequence[float], float]]) -> None:
        """Calibrate on anchors from the target series. The ranker is untouched.

        This is the whole transferability claim in one method: the expensive
        model is fitted once, somewhere else, and arriving at a new instrument
        costs a handful of observations and a 3x3 solve.
        """
        scores = [self.ranker.score(features) for features, _ in rows]
        self.mapping.fit(scores, [value for _, value in rows])

    def predict(self, features: Sequence[float]) -> float:
        return self.mapping(self.ranker.score(features))

    def rank(self, features: Sequence[float]) -> float:
        """The index itself, for when the ordering is all that is wanted."""
        return self.ranker.score(features)
