"""Repeating structures: has this shape happened before, and what followed?

Levels answer "price has been *here* before". This answers a different
question — "price has done *this* before" — and the two are independent. A
double top is the same structure at 4400 and at 95,000, on gold and on BTC, in
January and in June. Nothing about the level machinery can see that, because a
level is a price and a shape is not.

## Shapes are PIP sequences, normalised twice

A shape is the last few perceptually important points, and it has to be made
comparable along both axes before two of them can be compared at all:

- **price** is z-scored, so the same shape at 4400 and at 95,000 is the same
  shape, and a violent version of it is the same shape as a calm one;
- **time** is dropped entirely and only the *order* is kept, because two
  instances of a pattern rarely take the same number of bars — which is
  precisely what dynamic time warping exists to handle.

## Dynamic time warping, not Euclidean distance

Comparing point-by-point would call a three-day double top and a three-hour
double top completely different shapes. DTW finds the alignment minimising
total distance while preserving order, so it matches a stretched instance to a
compressed one — the property that makes it the standard partner to PIP in the
literature this is built from.

The band constraint (Sakoe-Chiba) is not an optimisation detail. Unconstrained
warping will align almost anything to almost anything given enough freedom, so
without a band the "matches" are alignments rather than resemblances.

## What stops it finding patterns in noise

Searching many shapes across many instruments and timeframes **will** turn up
repeats by chance — that is what multiple comparisons do, not a flaw in any one
match. Three things guard against it, and they are the same three the levels
model uses because the failure is the same failure:

- a match needs a **distance below threshold** *and* enough instances;
- every outcome is reported next to the **base rate**, so a shape whose
  P(up) equals the unconditional rate is visibly worth nothing;
- outcomes are measured in **volatility units**, so a "reliable" pattern worth
  a tenth of a typical move is visibly not worth acting on.
"""

from __future__ import annotations

import math
import statistics
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..logging import get_logger
from .pips import Point

log = get_logger(__name__)

#: Points in a shape. Five captures a double top or a head and shoulders
#: without becoming a description of one particular episode.
SHAPE_POINTS = 5

#: Sakoe-Chiba band, as a fraction of the sequence length. Beyond this the
#: warp is free enough to align unrelated shapes.
BAND = 0.4

#: Normalised DTW distance below which two shapes are the same shape. Tuned so
#: that visually similar sequences match and merely monotonic ones do not.
MATCH_DISTANCE = 0.35

#: Shapes kept. Bounded because this runs forever and the oldest shapes
#: describe a market that no longer exists.
MEMORY = 2_000

#: Instances needed before a shape's record is worth reporting at all.
MIN_INSTANCES = 5


def normalise(prices: Sequence[float]) -> list[float]:
    """Z-score a price sequence so shape survives and level and scale do not.

    A flat sequence has no shape, so it returns zeros rather than dividing by
    zero — and a zero vector matches nothing interesting, which is correct.
    """
    if len(prices) < 2:
        return [0.0] * len(prices)
    mean = statistics.fmean(prices)
    spread = statistics.pstdev(prices)
    if spread < 1e-12:
        return [0.0] * len(prices)
    return [(price - mean) / spread for price in prices]


def dtw(left: Sequence[float], right: Sequence[float], band: float = BAND) -> float:
    """Band-constrained DTW distance, normalised by path length.

    Normalising by length is what makes distances comparable between shapes of
    different sizes; without it a longer sequence is penalised for being long.
    """
    n, m = len(left), len(right)
    if not n or not m:
        return math.inf
    width = max(int(band * max(n, m)), abs(n - m)) + 1

    previous = [math.inf] * (m + 1)
    previous[0] = 0.0
    for i in range(1, n + 1):
        current = [math.inf] * (m + 1)
        low = max(1, i - width)
        high = min(m, i + width)
        for j in range(low, high + 1):
            cost = abs(left[i - 1] - right[j - 1])
            current[j] = cost + min(previous[j], current[j - 1], previous[j - 1])
        previous = current
    total = previous[m]
    return total / (n + m) if math.isfinite(total) else math.inf


@dataclass(frozen=True, slots=True)
class Shape:
    """One normalised sequence, with where it came from."""

    values: tuple[float, ...]
    feed: str = ""
    interval: str = ""
    time: float = field(default_factory=time.time)

    @classmethod
    def of(cls, points: Sequence[Point], feed: str = "", interval: str = "") -> Shape | None:
        """Build from PIPs. None when there are too few to have a shape."""
        if len(points) < 3:
            return None
        return cls(
            values=tuple(normalise([point.price for point in points])),
            feed=feed,
            interval=interval,
            time=max(point.confirmed for point in points),
        )

    def distance(self, other: Shape) -> float:
        return dtw(self.values, other.values)

    @property
    def flat(self) -> bool:
        return all(abs(value) < 1e-9 for value in self.values)

    def __len__(self) -> int:
        return len(self.values)


@dataclass(slots=True)
class Instance:
    """One occurrence of a shape, and what followed it."""

    shape: Shape
    #: Signed move over the horizon after the shape completed, volatility units.
    outcome_vol: float = 0.0
    resolved: bool = False

    @property
    def up(self) -> bool:
        return self.outcome_vol > 0


@dataclass(frozen=True, slots=True)
class Match:
    """What the library says about a shape that has just formed."""

    instances: int
    probability_up: float
    expected_move: float
    move_sigma: float
    base_rate_up: float
    nearest: float

    @property
    def edge(self) -> float:
        return self.probability_up - self.base_rate_up

    @property
    def direction(self) -> str:
        return "up" if self.probability_up >= 0.5 else "down"

    @property
    def actionable(self) -> bool:
        """The same three guards the levels model uses, for the same reason."""
        return (
            self.instances >= MIN_INSTANCES
            and abs(self.edge) >= 0.10
            and abs(self.expected_move) >= 0.5
        )

    def to_dict(self) -> dict:
        return {
            "instances": self.instances,
            "probability_up": round(self.probability_up, 4),
            "expected_move_vol": round(self.expected_move, 4),
            "move_sigma_vol": round(self.move_sigma, 4),
            "base_rate_up": round(self.base_rate_up, 4),
            "edge": round(self.edge, 4),
            "nearest": round(self.nearest, 4),
            "actionable": self.actionable,
        }

    def __str__(self) -> str:
        return (
            f"{self.direction} p={self.probability_up:.0%} "
            f"(base {self.base_rate_up:.0%}) move={self.expected_move:+.2f}v "
            f"n={self.instances} d={self.nearest:.3f}"
        )


class Library:
    """Shapes seen before, and what followed each.

    A plain scan rather than an index. DTW is not a metric — it violates the
    triangle inequality — so the usual spatial structures do not apply to it,
    and the honest options are a linear scan or a lower-bound filter. At a few
    thousand short sequences the scan is fast enough that the filter would be
    complexity bought with nothing.
    """

    def __init__(self, capacity: int = MEMORY, threshold: float = MATCH_DISTANCE) -> None:
        self.capacity = capacity
        self.threshold = threshold
        self._instances: OrderedDict[int, Instance] = OrderedDict()
        self._next = 0
        self._ups = 0
        self._resolved = 0

    def add(self, shape: Shape) -> int:
        """Record a shape as it forms. Returns a handle for reporting its outcome."""
        if shape.flat:
            return -1
        key = self._next
        self._next += 1
        self._instances[key] = Instance(shape=shape)
        while len(self._instances) > self.capacity:
            _, dropped = self._instances.popitem(last=False)
            if dropped.resolved:
                self._resolved -= 1
                self._ups -= dropped.up
        return key

    def resolve(self, key: int, outcome_vol: float) -> bool:
        """Say what followed. Only resolved instances count as evidence."""
        instance = self._instances.get(key)
        if instance is None or instance.resolved:
            return False
        instance.outcome_vol = outcome_vol
        instance.resolved = True
        self._resolved += 1
        self._ups += instance.up
        return True

    @property
    def base_rate_up(self) -> float:
        return self._ups / self._resolved if self._resolved else 0.5

    def similar(self, shape: Shape) -> list[tuple[float, Instance]]:
        """Resolved instances close enough to be the same shape, nearest first."""
        found = []
        for instance in self._instances.values():
            if not instance.resolved:
                continue
            distance = shape.distance(instance.shape)
            if distance <= self.threshold:
                found.append((distance, instance))
        found.sort(key=lambda pair: pair[0])
        return found

    def match(self, shape: Shape) -> Match | None:
        """What happened the other times this shape appeared.

        Distance-weighted, so a close instance counts for more than a marginal
        one — with a hard threshold alone, the estimate is dominated by whatever
        sits just inside it.
        """
        if shape.flat:
            return None
        found = self.similar(shape)
        if not found:
            return None

        weights = [1.0 / (1.0 + distance) for distance, _ in found]
        total = sum(weights)
        ups = sum(w for w, (_, inst) in zip(weights, found, strict=True) if inst.up)
        move = sum(w * inst.outcome_vol for w, (_, inst) in zip(weights, found, strict=True))
        moves = [inst.outcome_vol for _, inst in found]
        return Match(
            instances=len(found),
            probability_up=ups / total,
            expected_move=move / total,
            move_sigma=statistics.pstdev(moves) if len(moves) > 1 else 0.0,
            base_rate_up=self.base_rate_up,
            nearest=found[0][0],
        )

    @property
    def resolved(self) -> int:
        return self._resolved

    def __len__(self) -> int:
        return len(self._instances)
