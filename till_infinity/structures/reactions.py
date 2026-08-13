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

from .levels import CONFIDENT_TOUCHES, TRAP_VOL, TRAP_WINDOW, Level, Outcome, Side
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
    #: 1.0 for a pivot, 0.0 for a swing level. A dimension rather than a hard
    #: split: pivots do behave differently, but a pivot with no history should
    #: still be able to borrow from swing levels rather than from nothing.
    pivot: float = 0.0
    #: 1.0 when this touch is a retest of a recent break. Also a dimension: a
    #: back check is a different setup from a first touch, and the neighbours
    #: worth learning from are the other back checks.
    backcheck: float = 0.0
    #: Where volatility sat in its own recent range when this happened, in
    #: [0, 1]. Everything else here is *scaled* by volatility, which makes
    #: sizes comparable but deliberately erases the regime — and a level held
    #: in a dead session is weaker evidence about a violent one than the
    #: normalised numbers suggest. This puts that back as a dimension, so a
    #: touch is compared with touches from a market that felt the same.
    regime: float = 0.5

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
            + (self.pivot - other.pivot) ** 2
            + (self.backcheck - other.backcheck) ** 2
            + (self.regime - other.regime) ** 2
        )

    def to_dict(self) -> dict[str, float | str]:
        return {
            "side": str(self.side),
            "approach_vol": round(self.approach_vol, 4),
            "depth_vol": round(self.depth_vol, 4),
            "strength": round(self.strength, 4),
            "run_vol": round(self.run_vol, 4),
            "experience": round(self.experience, 4),
            "pivot": self.pivot,
            "backcheck": self.backcheck,
            "regime": round(self.regime, 4),
        }


def experience_of(touches: float) -> float:
    return math.log1p(max(0.0, touches)) / math.log1p(50)


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
    #: When price first got beyond the level. A break is provisional until it
    #: survives `TRAP_WINDOW`, so this is set long before the outcome is.
    broke_at: float = 0.0
    #: Furthest it reached beyond the level, in volatility units. What a
    #: breakout entry would have been offered before it was taken back.
    excursion_vol: float = 0.0

    @property
    def open(self) -> bool:
        return self.outcome is Outcome.OPEN

    @property
    def breaking(self) -> bool:
        """Through the level, but not yet proven to have stayed through."""
        return bool(self.broke_at) and self.open

    def to_dict(self) -> dict:
        return {
            "feed": self.feed,
            "level_price": round(self.level_price, 8),
            "started": self.started,
            "entry": round(self.entry, 8),
            "extreme": round(self.extreme, 8),
            "outcome": str(self.outcome),
            "push_vol": round(self.push_vol, 4),
            "excursion_vol": round(self.excursion_vol, 4),
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
    own_touches: float
    neighbours: int
    detail: str = ""
    #: A retest of a recent break, arriving from the side it broke to.
    backcheck: bool = False
    #: Distance to a stop beyond the flipped level, in volatility units. What
    #: being wrong costs, which an expected push means nothing without.
    risk_vol: float = 0.0

    @property
    def direction(self) -> str:
        """Which way to lean — taken from the expected push, not the win rate.

        The two can disagree, and when they do the expected value is what a
        consumer acts on: a level that drifts down four times in five and jumps
        hard on the fifth has a losing win rate and a positive expectation.
        Reporting "down" there while the expected move is upward would be
        incoherent to anyone reading it.
        """
        if self.expected_push > 0:
            return "up"
        if self.expected_push < 0:
            return "down"
        return "up" if self.probability_up >= 0.5 else "down"

    @property
    def mixed(self) -> bool:
        """True when the win rate and the expected move point opposite ways.

        Not an error — it is a skewed distribution, usually many small moves one
        way and a few large ones the other. Worth surfacing rather than hiding,
        because it is exactly the shape where a win rate alone misleads.
        """
        leans_up = self.probability_up >= 0.5
        return leans_up != (self.expected_push > 0) and self.expected_push != 0

    @property
    def edge(self) -> float:
        """How far the conditional sits from the unconditional. The real number."""
        return self.probability_up - self.base_rate_up

    @property
    def reward_to_risk(self) -> float:
        """Expected push against what being wrong costs, both in volatility units.

        The number that decides whether an edge is worth taking. A 70% call
        worth half what it risks is a losing trade; a 55% call worth three
        times it is not.
        """
        return abs(self.expected_push) / self.risk_vol if self.risk_vol else 0.0

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
            # A win rate and an expected move pointing opposite ways is a real
            # shape, but it is not a call — whichever one you act on, the other
            # says you are wrong.
            and not self.mixed
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
            "own_touches": round(self.own_touches, 2),
            "backcheck": self.backcheck,
            "risk_vol": round(self.risk_vol, 3),
            "reward_to_risk": round(self.reward_to_risk, 3),
            "neighbours": self.neighbours,
            "actionable": self.actionable,
            "mixed": self.mixed,
            "detail": self.detail,
        }

    def __str__(self) -> str:
        note = " mixed" if self.mixed else ""
        return (
            f"{self.direction} p={self.probability_up:.0%} "
            f"(base {self.base_rate_up:.0%}) push={self.expected_push:+.2f}v "
            f"n={self.own_touches:.1f}+{self.neighbours}{note}"
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
        """The unconditional rate. Without it no conditional means anything.

        Jeffreys-smoothed — `(ups + 0.5) / (n + 1)` — so it never reaches 0 or
        1. Twenty observations that all went up make the base rate 0.98, not
        1.0, and the difference matters because everything else is shrunk
        *toward* this number: an unsmoothed 1.0 would propagate certainty into
        every conditional built on it, and no finite sample earns that.
        """
        if not self._touches:
            return 0.5
        return (self._ups + 0.5) / (len(self._touches) + 1.0)

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

        The result is then **shrunk toward the base rate**, which matters more
        than it sounds: twelve neighbours that all went the same way would
        otherwise return exactly 0.0 or 1.0, and a level with no history of its
        own would inherit that certainty and report it. Twelve agreeing
        observations are evidence; they are not proof, and a system that prints
        "0%" from them will eventually print it about something it is wrong
        about.
        """
        found = self.neighbours(features)
        if not found:
            return self.base_rate_up, 0.0, 0
        weights = [1.0 / (1.0 + distance) for distance, _ in found]
        total = sum(weights)
        ups = sum(w for w, (_, touch) in zip(weights, found, strict=True) if touch.push_vol > 0)
        push = sum(w * touch.push_vol for w, (_, touch) in zip(weights, found, strict=True))

        base = self.base_rate_up
        weight = len(found) / (len(found) + PRIOR_WEIGHT)
        smoothed = weight * (ups / total) + (1.0 - weight) * base
        return smoothed, push / total, len(found)

    def __len__(self) -> int:
        return len(self._touches)


def infer(
    level: Level,
    side: Side,
    features: Features,
    memory: Memory,
    vol: Volatility | None = None,
    price: float = 0.0,
) -> Inference:
    """Combine the level's own record with its neighbours' into one answer.

    With `vol` and `price` the risk geometry is filled in too — where a stop
    would sit beyond the flipped level, and what the expected push is worth
    against it. An expected move without the cost of being wrong is only half
    a decision.
    """
    own = level.stats(side)
    prior_up, prior_push, neighbours = memory.prior(features)

    # Shrinkage: the level's own history takes over as it accumulates. With no
    # touches this is entirely the neighbours' answer; past CONFIDENT_TOUCHES it
    # is mostly the level's own.
    weight = own.touches / (own.touches + PRIOR_WEIGHT) if own.touches else 0.0
    probability = weight * own.probability_up(prior_up, PRIOR_WEIGHT) + (1 - weight) * prior_up
    push = weight * own.mean_push + (1 - weight) * prior_push

    if own.touches >= CONFIDENT_TOUCHES:
        detail = f"{own.touches:.1f} prior touches from {side}"
    elif neighbours:
        detail = f"{own.touches:.1f} own touches, {neighbours} similar elsewhere"
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
        backcheck=bool(features.backcheck),
        risk_vol=level.risk_vol(side, price or level.price, vol) if vol is not None else 0.0,
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
    #: How far back through the level counts as the break being taken back.
    trap_vol: float = TRAP_VOL
    #: How long a break stays provisional before it counts as having held.
    trap_window: float = TRAP_WINDOW
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

        if touch.breaking:
            # A break is provisional. Coming back through the level means the
            # breakout was a trap, and the trade it invited has lost — which is
            # a different fact from the level holding in the first place, and
            # the one worth knowing before trading the next break here.
            touch.excursion_vol = max(touch.excursion_vol, beyond)
            if away >= self.trap_vol:
                return self._close(level, touch, Outcome.TRAP, travelled, side, when)
            if when - touch.broke_at >= self.trap_window:
                return self._close(level, touch, Outcome.BREAK, travelled, side, when)
            return None

        if away >= self.resolve_vol:
            # A retest of a recent break that holds is a back check, not a
            # plain rejection: the direction is already established, so this is
            # a continuation entry rather than a reversal one.
            held = Outcome.BACKCHECK if level.is_backcheck(side, touch.started) else Outcome.REJECT
            return self._close(level, touch, held, travelled, side, when)
        if beyond >= self.resolve_vol:
            # Through it — but not resolved yet. A break is not a break until
            # it survives, which is how anyone trading one treats it.
            touch.broke_at = when
            touch.excursion_vol = beyond
            return None
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
        level.record(side, outcome, touch.push_vol, when)
        if outcome is Outcome.BREAK and touch.broke_at:
            # The retest clock starts when price *got through*, not when the
            # break was confirmed. Confirmation waits out the trap window, so
            # dating it from there spends most of the window before a retest
            # could possibly happen — which is why almost none were detected.
            level.broke_at = touch.broke_at
        self.memory.add(touch)
        return touch

    def open_touch(self, level: Level) -> Touch | None:
        return self._open.get(self.key(level))

    @property
    def open_count(self) -> int:
        return len(self._open)

    def expire(self, when: float) -> list[Touch]:
        """Close out anything that has sat open too long.

        A touch that broke and then went quiet counts as a break: it got
        through and nothing took it back. One that never got anywhere is chop.
        """
        stale = [
            key
            for key, touch in self._open.items()
            if when - touch.started >= self.horizon * 2
            or (touch.breaking and when - touch.broke_at >= self.trap_window)
        ]
        dropped = []
        for key in stale:
            touch = self._open.pop(key)
            touch.outcome = Outcome.BREAK if touch.breaking else Outcome.CHOP
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
        pivot=1.0 if level.origin.startswith("pivot") else 0.0,
        backcheck=1.0 if level.is_backcheck(side, when) else 0.0,
        regime=vol.regime,
    )


def rank(inferences: Sequence[Inference]) -> list[Inference]:
    """Strongest first: real edge, then size, then evidence."""
    return sorted(
        inferences,
        key=lambda i: (i.actionable, abs(i.edge), abs(i.expected_push)),
        reverse=True,
    )
