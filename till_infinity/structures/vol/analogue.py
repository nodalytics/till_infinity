"""Volatility from the past rows that most resemble this one.

Every estimator in this package weights the past by **recency**. An EWMA
half-life is precisely "how fast to forget"; GARCH adds a level to revert
toward but still decays what it saw; the range estimators average a window.
None of them can say *that bar three weeks ago looked like this one, and here
is what followed it* - the one thing a chart reader does without effort.

Weighting by **relevance** rather than by recency is what an attention layer
buys, and it is the only part of that architecture worth having here. A
transformer is batch-trained and this is an online system on two cores with
about a gigabyte spare - a Mondrian forest was already rejected at 46MB per
model, and attention over four hundred series would be orders of magnitude
worse. The mechanism survives the constraint; the implementation does not.

## What this is

A k-nearest-neighbour regression over the learner's own feature row: find the
`K` past rows closest to this one, average what actually followed them, and
report it. That is a kernel-weighted estimator, and it is the same idea
`reactions` already uses over past touches at a level - see
`research/similarity.md`, which is the standing work on it.

Three things make it affordable where attention is not:

* **One shared memory, not one per series.** The features are dimensionless
  for exactly this reason - see `learned.py` - so eurusd at 5m and gold at 4h
  are rows in one table rather than two tables.
* **A bounded reservoir.** `MEMORY` rows are kept and the oldest is displaced,
  so the cost is fixed rather than growing with the run.
* **No matrix anywhere.** A distance over twenty floats, `MEMORY` times.

## What it is not

It is not a replacement for anything and nothing divides by it. Like `garch`,
`ranges`, `har` and `learned` before it, it is published beside `vol_bps` and
scored by the same head-to-head, and `research/forecasting.md` records what
happened the last three times a replacement looked justified - two of the
three were defects that made the data look clean.

**The honest prior is that it loses.** Persistence beat every model in that
study, and this one has a specific extra way to fail: with twenty features and
a few thousand rows, the "nearest" neighbours in a twenty-dimensional space are
not necessarily near. That is the curse of dimensionality and it is a real
objection, not a ritual one - which is why `WEIGHTS` exists to restrict the
distance to the features that carry scale, rather than pretending all twenty
are equally informative.
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

from ..state import Restorable

#: Rows kept. Bounded so the cost is fixed: a scan is `MEMORY` distances, and
#: at 4,000 that is about a millisecond, against roughly 1.3 bar closes a
#: second across the whole book.
MEMORY = 4_000

#: Neighbours averaged. Small enough that "similar" still means something,
#: large enough that one row cannot decide the answer.
K = 24

#: Rows before the estimate is offered at all. A nearest neighbour drawn from
#: fifty is the nearest of fifty, which is not the same claim.
WARMUP = 1_000

#: The features the distance is computed over, and **not all of them**.
#:
#: Twenty dimensions is where nearest-neighbour methods stop working: distances
#: concentrate, every point becomes roughly equidistant from every other, and
#: "nearest" degenerates into "arbitrary". The defence is to measure distance
#: only over the features that carry the quantity being predicted.
#:
#: These six are the scale and shape of the bar and where the estimators
#: disagree. `hour_sin`/`hour_cos`, `log_bar`, `weekday` and the rest are
#: deliberately absent: they identify *which* series and *when*, which is
#: useful to a tree that can split on them and harmful in a distance, where
#: they would make a 5m bar and a 4h bar far apart by construction and defeat
#: the pooling the whole design rests on.
WEIGHTS: dict[str, float] = {
    "span_rel": 2.0,
    "r1": 1.5,
    "r5": 1.0,
    "accel": 1.0,
    "body": 0.75,
    "garch_rel": 0.75,
}


@dataclass(slots=True)
class Analogue(Restorable):
    """A k-NN over past feature rows, answering with what followed them."""

    memory: int = MEMORY
    k: int = K
    warmup: int = WARMUP
    #: (vector, log-correction that followed). The vector is pre-extracted so
    #: the scan is arithmetic rather than dictionary lookups.
    _rows: deque[tuple[tuple[float, ...], float]] = field(
        default_factory=lambda: deque(maxlen=MEMORY)
    )
    _seen: int = 0

    def __post_init__(self) -> None:
        """Honour `memory`, which the default factory cannot see.

        A `default_factory` runs before the instance exists, so it can only
        close over the module constant - and the field was therefore inert:
        `Analogue(memory=50)` kept four thousand rows and reported the fifty it
        had been asked for nowhere. A test caught it.

        That is worth more than a line of code. An unbounded accumulator that
        *looks* bounded is the exact shape behind four of this repository's
        outages, and it is the shape this module's own docstring claims to have
        avoided.
        """
        if self._rows.maxlen != self.memory:
            self._rows = deque(self._rows, maxlen=self.memory)

    @property
    def warm(self) -> bool:
        return self._seen >= self.warmup

    @staticmethod
    def _vector(row: dict[str, float]) -> tuple[float, ...]:
        """The row as a weighted point, in a fixed order."""
        return tuple(float(row.get(name, 0.0) or 0.0) * weight for name, weight in WEIGHTS.items())

    def observe(self, row: dict[str, float] | None, correction: float) -> None:
        """Remember one row and the log correction that actually followed it."""
        if not row or not math.isfinite(correction):
            return
        self._rows.append((self._vector(row), float(correction)))
        self._seen += 1

    def predict(self, row: dict[str, float] | None) -> float | None:
        """The mean correction that followed the `k` most similar past rows.

        `None` rather than a number when there is nothing to say, which is the
        rule the rest of this package follows: a missing reading is missing,
        and zero here would be the confident claim that the standing estimate
        is exactly right.

        Distance-weighted rather than a plain mean over the k. The nearest of
        four thousand rows and the twenty-fourth nearest are not equally
        informative, and averaging them flat throws away the ordering that is
        the entire content of the method.
        """
        if not row or not self.warm or len(self._rows) < self.k:
            return None
        here = self._vector(row)
        # A partial selection would be faster; a full sort of 4,000 is about a
        # millisecond and this runs on bar closes, not on quotes. Measured
        # before optimised, in that order.
        scored = sorted(
            (
                (sum((a - b) ** 2 for a, b in zip(here, past, strict=True)), value)
                for past, value in self._rows
            ),
            key=lambda pair: pair[0],
        )[: self.k]
        total = weight_sum = 0.0
        for distance, value in scored:
            # Inverse distance, floored so an exact match does not divide by
            # zero and take the whole answer with it.
            weight = 1.0 / max(math.sqrt(distance), 1e-6)
            total += weight * value
            weight_sum += weight
        if weight_sum <= 0:
            return None
        return total / weight_sum

    def sample(self, rate: float = 1.0, rng: random.Random | None = None) -> bool:
        """Whether to remember this row, for a caller thinning the stream.

        Kept here rather than at the call site so the reservoir's shape is
        decided by the thing that owns it.
        """
        if rate >= 1.0:
            return True
        return (rng or random).random() < rate
