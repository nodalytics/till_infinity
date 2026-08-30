"""A learned distance over past touches, and a level's own vector.

Two models that share a premise: `reactions.py` compares touches with a
**hand-built** distance - nine features, all weighted the same, Euclidean - and
nobody has ever checked whether that is the right way to decide which past
touches are relevant to this one.

## The learned distance

`Attention` keeps one weight per feature and scores a past touch by

    score = -sum(w_i * (query_i - key_i)^2)

then softmaxes those scores into a weighting over the neighbours and predicts
the weighted average of what they did. With every `w` equal it *is* the kNN's
Euclidean distance with a soft edge instead of a hard cut at k. What it adds is
that the weights move: a feature that separates outcomes gets weight, one that
does not loses it, learned by gradient on the prediction error.

This is the same shape as attention in a transformer - a query scored against
keys, softmaxed, used to average values - which is worth saying plainly because
the resemblance is the reason to expect it to work, not decoration. The thing
being borrowed is the *mechanism*, not the architecture: there is no depth here,
no positions, no tokens, and adding them would be modelling noise with more
parameters.

**The temperature is the k.** A high temperature averages over everything, which
is the base rate; a low one attends to the single nearest touch, which is 1-NN.
It is learned along with the weights, so "how many neighbours" stops being a
constant somebody chose.

## The level vector

`Embedding` gives each level a small vector, nudged toward a direction each time
the level does something and away when it does the opposite. Two levels end up
near each other when they have *behaved* alike, which is a different claim from
being described alike: the hand-built features say what a level looks like, and
this says what it has done.

That is the point and also the limitation, and both should be stated. A level
with two touches has a vector made of two nudges and means very little; the
`seen` count is carried so a caller can tell a learned vector from a rumour, and
`similar` refuses to rank levels below `MIN_SEEN`.

## What neither of these does

Neither decides anything. Both publish a number onto the signal beside the
kNN's, and the outcome machinery is what says whether a learned distance beats
a hand-built one. If it does not, that is the finding - and it is a cheaper
finding than the alternative of assuming either way.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from .state import Restorable

#: Starting weight per feature, so the model begins as the kNN it is being
#: compared against rather than somewhere arbitrary. A comparison that starts
#: from noise measures the training, not the idea.
START_WEIGHT = 1.0

#: How fast the weights and the temperature move.
LEARNING_RATE = 0.01

#: Starting temperature. One is the plain softmax of the negative squared
#: distance, which is the closest thing to "kNN with a soft edge".
START_TEMPERATURE = 1.0

#: Bounds on it. Below the floor this is 1-NN with extra steps; above the
#: ceiling it is the base rate wearing a model.
MIN_TEMPERATURE, MAX_TEMPERATURE = 0.05, 20.0

#: How many touches before a prediction is worth reading.
MIN_NEIGHBOURS = 5


@dataclass(slots=True)
class Attention(Restorable):
    """A weighting over past touches, learned rather than chosen."""

    weights: list[float] = field(default_factory=list)
    temperature: float = START_TEMPERATURE
    rate: float = LEARNING_RATE
    seen: float = 0.0
    error: float = 0.0
    variance: float = 0.0
    mean: float = 0.5

    def _ready(self, width: int) -> None:
        if not self.weights:
            self.weights = [START_WEIGHT] * width

    def _scores(self, query: Sequence[float], keys: Sequence[Sequence[float]]) -> list[float]:
        """Softmax weights over the neighbours. Sums to one."""
        raw: list[float] = []
        for key in keys:
            total = 0.0
            for i, (q, k) in enumerate(zip(query, key, strict=False)):
                total += abs(self.weights[i]) * (q - k) ** 2
            raw.append(-total / max(self.temperature, MIN_TEMPERATURE))
        top = max(raw)
        # Shifted before exp: the raw scores are unbounded below, and without
        # this a distant neighbour set underflows every term to zero and the
        # normaliser is a division by nothing.
        weights = [math.exp(r - top) for r in raw]
        total = sum(weights)
        return [w / total for w in weights] if total > 0 else [1.0 / len(raw)] * len(raw)

    def predict(
        self,
        query: Sequence[float],
        keys: Sequence[Sequence[float]],
        values: Sequence[float],
    ) -> float | None:
        """The attention-weighted average of what the neighbours did.

        None when there is not enough to attend to, rather than a number with
        nothing behind it.
        """
        if len(keys) < MIN_NEIGHBOURS or len(keys) != len(values):
            return None
        self._ready(len(query))
        share = self._scores(query, keys)
        return sum(w * v for w, v in zip(share, values, strict=True))

    def observe(
        self,
        query: Sequence[float],
        keys: Sequence[Sequence[float]],
        values: Sequence[float],
        actual: float,
    ) -> float | None:
        """Predict, score, then learn. Returns what it said beforehand.

        The gradient is the useful part. For weight `i` the prediction moves by
        how much feature `i` separates the neighbours that were right from the
        ones that were wrong - so a feature which is large exactly where the
        neighbours disagree with the outcome loses weight, and one that is
        large where they agree gains it.
        """
        said = self.predict(query, keys, values)
        if said is None:
            return None

        keep = max(0.0, 1.0 - 1.0 / 2_000.0)
        self.seen = self.seen * keep + 1.0
        self.error = self.error * keep + (actual - said) ** 2
        self.variance = self.variance * keep + (actual - self.mean) ** 2
        self.mean += (actual - self.mean) / self.seen

        share = self._scores(query, keys)
        residual = actual - said
        # d(prediction)/d(w_i), through the softmax.
        for i in range(len(self.weights)):
            grad = 0.0
            for n, key in enumerate(keys):
                if i >= len(key):
                    continue
                gap = (query[i] - key[i]) ** 2
                # Each neighbour's share falls as its distance grows, by its
                # own share times the difference from the weighted-average gap.
                mean_gap = sum(
                    share[m] * (query[i] - k[i]) ** 2 for m, k in enumerate(keys) if i < len(k)
                )
                grad += share[n] * (values[n] - said) * -(gap - mean_gap)
            self.weights[i] += self.rate * residual * grad / max(self.temperature, MIN_TEMPERATURE)
            self.weights[i] = max(0.0, self.weights[i])
        return said

    @property
    def r2(self) -> float:
        """Walk-forward, against predicting the running mean."""
        if self.variance <= 1e-12:
            return 0.0
        return 1.0 - self.error / self.variance

    @property
    def warm(self) -> bool:
        return self.seen >= 30.0

    def importance(self, names: Sequence[str]) -> list[tuple[str, float]]:
        """Which features the model decided matter, largest first."""
        if len(names) != len(self.weights):
            return []
        return sorted(zip(names, self.weights, strict=True), key=lambda kv: -kv[1])


#: How wide a level's vector is. Small on purpose: a level has tens of touches,
#: not thousands, and a vector with more dimensions than the level has evidence
#: is a lookup table that has learned each touch separately.
WIDTH = 8

#: How many touches before a level's vector is worth comparing.
MIN_SEEN = 3

#: How far each touch moves the vector.
NUDGE = 0.15


@dataclass(slots=True)
class Vector(Restorable):
    """One level's learned description, and how much is behind it."""

    values: list[float] = field(default_factory=lambda: [0.0] * WIDTH)
    seen: float = 0.0

    @property
    def ready(self) -> bool:
        return self.seen >= MIN_SEEN

    def norm(self) -> float:
        return math.sqrt(sum(v * v for v in self.values))


@dataclass(slots=True)
class Embedding(Restorable):
    """A vector per level, learned from what the level has done.

    The features in `reactions.Features` say what a level *looks like* -
    touches, strength, whether it is a pivot. This says what it has *done*, and
    two levels can look alike and behave nothing alike.

    The update is deliberately the simplest thing that could work: project the
    touch's own description into the vector's width and nudge toward it when
    the level held, away when it broke. There is no objective being minimised
    here and it should not be described as if there were - it is a running
    summary of behaviour, and its value is whether levels that end up near each
    other go on to do the same thing.
    """

    vectors: dict[str, Vector] = field(default_factory=dict)
    nudge: float = NUDGE

    def of(self, level_id: str) -> Vector:
        found = self.vectors.get(level_id)
        if found is None:
            found = self.vectors[level_id] = Vector()
        return found

    def observe(self, level_id: str, features: Sequence[float], held: bool) -> None:
        """Move this level's vector by what just happened at it."""
        if not level_id:
            return
        vector = self.of(level_id)
        direction = 1.0 if held else -1.0
        for i in range(WIDTH):
            # Folded rather than truncated, so a feature past the width still
            # reaches the vector instead of being silently dropped.
            value = sum(features[j] for j in range(i, len(features), WIDTH))
            vector.values[i] += self.nudge * direction * value
        vector.seen += 1.0
        # Kept on the unit sphere, so `similar` compares shape rather than how
        # many touches a level happens to have had.
        size = vector.norm()
        if size > 1e-9:
            vector.values = [v / size for v in vector.values]

    def similar(self, level_id: str, limit: int = 5) -> list[tuple[str, float]]:
        """Levels that have behaved most like this one, by cosine.

        Refuses to rank anything below `MIN_SEEN`: a vector made of two nudges
        is a rumour, and returning it alongside one made of forty would make
        them look like the same kind of claim.
        """
        mine = self.vectors.get(level_id)
        if mine is None or not mine.ready:
            return []
        found = [
            (name, sum(a * b for a, b in zip(mine.values, other.values, strict=True)))
            for name, other in self.vectors.items()
            if name != level_id and other.ready
        ]
        found.sort(key=lambda kv: -kv[1])
        return found[:limit]

    def prune(self, keep: int = 5_000) -> int:
        """Drop the least-evidenced vectors. Levels die and this must not grow."""
        if len(self.vectors) <= keep:
            return 0
        ordered = sorted(self.vectors.items(), key=lambda kv: -kv[1].seen)
        dropped = len(self.vectors) - keep
        self.vectors = dict(ordered[:keep])
        return dropped
