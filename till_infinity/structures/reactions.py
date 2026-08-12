"""What happened last time price came here, and what that says about now.

A level with a history is only useful if the history is turned into an answer.
This module does two things: it watches an interaction from first contact to
resolution, and it turns the record of past interactions into a direction with
a probability and an expected size.

## The answer is a direction, not a verdict

"Will it hold" is the wrong question, because a level does different things
depending on which side price arrives from, and because "held" says nothing
about how far the push carried. What is produced instead is:

    given price arrived from *this* side, P(pushed up), and how far, in
    volatility units

Both halves matter. A 55% chance of a push worth 0.1 volatility units is not
worth acting on; a 55% chance of two volatility units might be.

## Two sources of evidence, and the honest weighting between them

A level that has been touched twenty times knows its own behaviour. A level
formed yesterday knows nothing — but it *resembles* levels that have been
touched hundreds of times, and that resemblance is real evidence.

So the estimate is a shrinkage between:

- **this level's own per-side record**, which is specific but often sparse;
- **kNN over historical touches at similar levels**, which is plentiful but
  only as relevant as the similarity is real.

The weight moves with the level's own touch count, so a level's own history
takes over as it earns one. That is the whole reason both exist: neither alone
is right at both ends.

## What stops it fooling itself

Every conditional probability here is reported next to the **base rate** — the
unconditional chance price went up over the same horizon. A level where
P(up | touched from below) equals the base rate has told you nothing, however
confident the number looks, and a system that does not show both will find
signal in noise every time.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from .levels import CONFIDENT_TOUCHES, Level, Outcome, Side
from .volatility import Volatility

#: Neighbours consulted for the cold-start prior.
DEFAULT_K = 12

#: Historical touches kept for kNN. Bounded because this runs forever, and the
#: oldest touches describe a market that no longer exists anyway.
MEMORY = 4_000

#: How strongly a kNN prior counts, in pseudo-touches. Roughly: borrowed
#: evidence is worth this much of the level's own.
PRIOR_WEIGHT = 4.0


@dataclass(frozen=True, slots=True)
class Features:
    """What makes two touches comparable.

    Deliberately small, and every entry scale-free. A feature in price units or
    basis points would make gold and EURUSD incomparable, which would defeat
    the point of borrowing evidence across them.
    """

    side: Side
    #: How fast price was travelling into the level, in volatility units per bar.
    approach_vol: float
    #: How far into the zone it pushed, in volatility units.
    depth_vol: float
    #: The level's own quality at the time, in [0, 1].
    strength: float
    #: How many volatility units price had already travelled in this leg.
    run_vol: float
    #: Touch count, log-compressed: the difference between 1 and 5 touches
    #: matters far more than between 50 and 54.
    experience: float

    def distance(self, other: Features) -> float:
        """Similarity for kNN. Side is a hard constraint, not a dimension.

        Mixing sides would let a floor's history vote on a ceiling's future,
        which is precisely the asymmetry the whole design exists to respect.
        """
        if self.side is not other.side:
            return math.inf
        return math.sqrt(
            (self.approach_vol - other.approach_vol) ** 2
            + (self.depth_vol - other.depth_vol) ** 2
            + (self.strength - other.strength) ** 2
            + (self.run_vol - other.run_vol) ** 2
            + (self.experience - other.experience) ** 2
        )

    def to_dict(self) -> dict[str, float | str]:
        return {
            "side": str(self.side),
            "approach_vol": round(self.approach_vol, 4),
            "depth_vol": round(self.depth_vol, 4),
            "strength": round(self.strength, 4),
            "run_vol": round(self.run_vol, 4),
            "experience": round(self.experience, 4),
        }


def experience_of(touches: int) -> float:
    return math.log1p(max(0, touches)) / math.log1p(50)


@dataclass(slots=True)
class Touch:
    """One interaction, from first contact to resolution."""

    feed: str
    level_price: float
    features: Features
    started: float
    entry: float
    #: The furthest price reached while inside the zone — the Kalman filter's
    #: observation of where the level actually is.
    extreme: float
    outcome: Outcome = Outcome.OPEN
    push_vol: float = 0.0
    resolved: float = 0.0

    @property
    def open(self) -> bool:
        return self.outcome is Outcome.OPEN

    def to_dict(self) -> dict:
        return {
            "feed": self.feed,
            "level_price": round(self.level_price, 8),
            "started": self.started,
            "entry": round(self.entry, 8),
            "extreme": round(self.extreme, 8),
            "outcome": str(self.outcome),
            "push_vol": round(self.push_vol, 4),
            "resolved": self.resolved,
            **self.features.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Inference:
    """What the history says about the direction from here."""

    side: Side
    probability_up: float
    #: Expected push in volatility units, signed. Positive is upward.
    expected_push: float
    #: Dispersion of that push. A large mean with a larger sigma is not a call.
    push_sigma: float
    #: The unconditional rate, for comparison. If these match, there is no edge.
    base_rate_up: float
    own_touches: int
    neighbours: int
    detail: str = ""

    @property
    def direction(self) -> str:
        if self.probability_up >= 0.5:
            return "up"
        return "down"

    @property
    def edge(self) -> float:
        """How far the conditional sits from the unconditional. The real number."""
        return self.probability_up - self.base_rate_up

    @property
    def actionable(self) -> bool:
        """Enough evidence, enough separation from the base rate, enough size.

        All three, because any one alone is how a backtest lies: a big edge on
        four touches is noise, a large sample at the base rate is nothing, and
        a confident call worth 0.1 volatility units does not pay for itself.
        """
        return (
            self.own_touches + self.neighbours >= 8
            and abs(self.edge) >= 0.08
            and abs(self.expected_push) >= 0.5
        )

    def to_dict(self) -> dict:
        return {
            "side": str(self.side),
            "direction": self.direction,
            "probability_up": round(self.probability_up, 4),
            "expected_push_vol": round(self.expected_push, 4),
            "push_sigma_vol": round(self.push_sigma, 4),
            "base_rate_up": round(self.base_rate_up, 4),
            "edge": round(self.edge, 4),
            "own_touches": self.own_touches,
            "neighbours": self.neighbours,
            "actionable": self.actionable,
            "detail": self.detail,
        }

    def __str__(self) -> str:
        return (
            f"{self.direction} p={self.probability_up:.0%} "
            f"(base {self.base_rate_up:.0%}) push={self.expected_push:+.2f}v "
            f"n={self.own_touches}+{self.neighbours}"
        )


class Memory:
    """Resolved touches, and the kNN over them.

    A plain scan rather than a spatial index. The bound is a few thousand rows
    of five floats, which is microseconds — an index here would be complexity
    bought with nothing, and it would have to be rebuilt as touches age out.
    """

    def __init__(self, capacity: int = MEMORY, k: int = DEFAULT_K) -> None:
        self.capacity = capacity
        self.k = k
        self._touches: list[Touch] = []
        self._ups = 0

    def add(self, touch: Touch) -> None:
        if touch.open:
            return
        self._touches.append(touch)
        if touch.push_vol > 0:
            self._ups += 1
        while len(self._touches) > self.capacity:
            dropped = self._touches.pop(0)
            if dropped.push_vol > 0:
                self._ups -= 1

    @property
    def base_rate_up(self) -> float:
        """The unconditional rate. Without it no conditional means anything."""
        return self._ups / len(self._touches) if self._touches else 0.5

    def neighbours(self, features: Features) -> list[tuple[float, Touch]]:
        """The k most similar resolved touches, nearest first."""
        scored = [
            (features.distance(touch.features), touch)
            for touch in self._touches
            if touch.features.side is features.side
        ]
        scored = [pair for pair in scored if math.isfinite(pair[0])]
        scored.sort(key=lambda pair: pair[0])
        return scored[: self.k]

    def prior(self, features: Features) -> tuple[float, float, int]:
        """(P(up), mean push, count) from similar touches at *other* levels.

        Distance-weighted, so a close neighbour counts for more than a distant
        one. Without the weighting, k neighbours of wildly different similarity
        vote equally and the estimate is dominated by whichever level happened
        to be touched most.
        """
        found = self.neighbours(features)
        if not found:
            return self.base_rate_up, 0.0, 0
        weights = [1.0 / (1.0 + distance) for distance, _ in found]
        total = sum(weights)
        ups = sum(w for w, (_, touch) in zip(weights, found, strict=True) if touch.push_vol > 0)
        push = sum(w * touch.push_vol for w, (_, touch) in zip(weights, found, strict=True))
        return ups / total, push / total, len(found)

    def __len__(self) -> int:
        return len(self._touches)


def infer(level: Level, side: Side, features: Features, memory: Memory) -> Inference:
    """Combine the level's own record with its neighbours' into one answer."""
    own = level.stats(side)
    prior_up, prior_push, neighbours = memory.prior(features)

    # Shrinkage: the level's own history takes over as it accumulates. With no
    # touches this is entirely the neighbours' answer; past CONFIDENT_TOUCHES it
    # is mostly the level's own.
    weight = own.touches / (own.touches + PRIOR_WEIGHT) if own.touches else 0.0
    probability = weight * own.probability_up(prior_up, PRIOR_WEIGHT) + (1 - weight) * prior_up
    push = weight * own.mean_push + (1 - weight) * prior_push

    if own.touches >= CONFIDENT_TOUCHES:
        detail = f"{own.touches} prior touches from {side}"
    elif neighbours:
        detail = f"{own.touches} own touches, {neighbours} similar elsewhere"
    else:
        detail = "no comparable history"

    return Inference(
        side=side,
        probability_up=probability,
        expected_push=push,
        push_sigma=own.push_sigma,
        base_rate_up=memory.base_rate_up,
        own_touches=own.touches,
        neighbours=neighbours,
        detail=detail,
    )


# ------------------------------------------------------------------ tracking


@dataclass(slots=True)
class Tracker:
    """Follows interactions from first contact to resolution.

    Resolution is what makes the record a training example rather than an
    observation, so it is the part that has to be right: a touch is resolved
    when price has travelled `resolve_vol` volatility units away from the
    level, in either direction, and is chopped if it has not done so within
    `horizon` seconds.
    """

    resolve_vol: float = 1.5
    break_vol: float = 0.75
    horizon: float = 3600.0
    memory: Memory = field(default_factory=Memory)
    _open: dict[tuple[str, float], Touch] = field(default_factory=dict)

    def key(self, level: Level) -> tuple[str, float]:
        return (level.feed, round(level.price, 8))

    def begin(self, level: Level, price: float, features: Features, when: float) -> Touch:
        """Record first contact. The side comes from `features`, not separately —
        two sources for one fact is two things that can disagree."""
        touch = Touch(
            feed=level.feed,
            level_price=level.price,
            features=features,
            started=when,
            entry=price,
            extreme=price,
        )
        self._open[self.key(level)] = touch
        return touch

    def update(self, level: Level, price: float, vol: Volatility, when: float) -> Touch | None:
        """Advance an open interaction. Returns it once resolved.

        The extreme is tracked throughout, because where price actually turned
        is a better observation of the level than where it first arrived — and
        it is what the Kalman filter should be fed.
        """
        touch = self._open.get(self.key(level))
        if touch is None:
            return None

        side = touch.features.side
        if side is Side.ABOVE:
            touch.extreme = min(touch.extreme, price)
        else:
            touch.extreme = max(touch.extreme, price)

        travelled = level.distance_vol(price, vol)
        away = travelled if side is Side.ABOVE else -travelled
        beyond = -away

        if away >= self.resolve_vol:
            return self._close(level, touch, Outcome.REJECT, travelled, side, when)
        if beyond >= self.resolve_vol:
            return self._close(level, touch, Outcome.BREAK, travelled, side, when)
        if when - touch.started >= self.horizon:
            return self._close(level, touch, Outcome.CHOP, travelled, side, when)
        return None

    def _close(
        self,
        level: Level,
        touch: Touch,
        outcome: Outcome,
        travelled: float,
        side: Side,
        when: float,
    ) -> Touch:
        touch.outcome = outcome
        # Signed in absolute terms — positive is up — rather than relative to
        # the approach. A consumer wants to know which way to lean, not whether
        # the level "won".
        touch.push_vol = travelled
        touch.resolved = when
        self._open.pop(self.key(level), None)
        level.record(side, outcome, touch.push_vol)
        self.memory.add(touch)
        return touch

    def open_touch(self, level: Level) -> Touch | None:
        return self._open.get(self.key(level))

    @property
    def open_count(self) -> int:
        return len(self._open)

    def expire(self, when: float) -> list[Touch]:
        """Chop out anything that has sat open past the horizon."""
        stale = [
            key for key, touch in self._open.items() if when - touch.started >= self.horizon * 2
        ]
        dropped = []
        for key in stale:
            touch = self._open.pop(key)
            touch.outcome = Outcome.CHOP
            touch.resolved = when
            self.memory.add(touch)
            dropped.append(touch)
        return dropped


def features_for(
    level: Level,
    side: Side,
    price: float,
    vol: Volatility,
    *,
    approach_vol: float = 0.0,
    run_vol: float = 0.0,
    when: float | None = None,
) -> Features:
    """Describe one touch in the scale-free terms kNN compares."""
    when = time.time() if when is None else when
    return Features(
        side=side,
        approach_vol=approach_vol,
        depth_vol=abs(level.distance_vol(price, vol)),
        strength=level.strength(when, vol),
        run_vol=run_vol,
        experience=experience_of(level.touches),
    )


def rank(inferences: Sequence[Inference]) -> list[Inference]:
    """Strongest first: real edge, then size, then evidence."""
    return sorted(
        inferences,
        key=lambda i: (i.actionable, abs(i.edge), abs(i.expected_push)),
        reverse=True,
    )
