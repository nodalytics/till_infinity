"""What the numeric layer emits, and the features it emits it from.

A `Signal` is deliberately not an alert. It says "this reading is unusual, here
is how unusual and here is what it was" and stops there. Deciding whether a
human should be interrupted needs the calendar, and this layer cannot see the
calendar — that is the agent's job, and the reason `structures` publishes
signals rather than conclusions.

The exception is a signal that is unambiguous on its own, which can go straight
to `alerts` without waiting for a model. A venue whose price has stopped moving
while five others carry on does not need an LLM to interpret it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: Bound once at import: a dataclass field called `time` shadows the module
#: inside the class body, so the second default would resolve against a Field.
_now = time.time


class Shape(StrEnum):
    """What kind of unusual. The three have different causes and different fixes."""

    #: One venue's price is far from where the others agree it should be.
    DISLOCATION = "dislocation"
    #: One venue has stopped updating while the others keep moving.
    STALE = "stale"
    #: One venue is consistently late to the same move.
    LAGGING = "lagging"
    #: Liquidity: the spread is unusual for this venue *and* for the group.
    SPREAD = "spread"
    #: The distribution itself moved — a regime change, not a single reading.
    DRIFT = "drift"


@dataclass(frozen=True, slots=True)
class Consensus:
    """Where the venues agree, at one instant, for one instrument.

    The median rather than the mean, because the whole point is to be robust to
    the one venue that has gone wrong — a mean is dragged by the outlier it is
    meant to expose.
    """

    feed: str
    mid: float
    venues: int
    spread_bps: float = 0.0
    time: float = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class Signal:
    """One detection: what, where, how unusual, and the numbers behind it."""

    shape: Shape
    feed: str
    venue: str
    score: float
    detail: str = ""
    features: dict[str, float] = field(default_factory=dict)
    interval: str = "tick"
    time: float = field(default_factory=_now)

    @property
    def key(self) -> tuple[str, str, str]:
        return (str(self.shape), self.feed, self.venue)

    @property
    def title(self) -> str:
        return f"{self.venue} {self.feed}: {self.detail or self.shape}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": str(self.shape),
            "feed": self.feed,
            "venue": self.venue,
            "score": round(self.score, 4),
            "detail": self.detail,
            "features": {k: round(v, 6) for k, v in self.features.items()},
            "interval": self.interval,
            "time": self.time,
        }

    def __str__(self) -> str:
        return f"{self.shape} {self.feed}/{self.venue} score={self.score:.2f} {self.detail}"
