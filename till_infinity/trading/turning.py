"""The turn model's exit, ridden alongside the real one and scored against it.

`structures/cycles.py` publishes `turn_price` on every call: where its
turn-depth head expects the current leg to end. That is an **exit** rather than
an entry - it says how far this move has left to run - and it is the one part of
that work `research/delivering.md` measured as carrying anything, with a skill
of +0.19 against the running mean on constructed spreads and the four feature
families taking it from 0.045 to 0.189.

**It acts on nothing.** This records what the suggested exit would have made,
beside what the trade actually made, and settles both from the same path. The
journal then answers the question rather than an argument doing it - which is
how `Shadow` settled the stop-width question that reasoning had been going round
in circles on.

## Why a counterfactual here is honest, and usually is not

Most "what if we had exited there" claims are unfalsifiable because the exit
level is chosen after the fact. This one is not, for two reasons:

* **The level is fixed before the trade opens.** `turn_price` is on the signal,
  and the signal is what opened the position. Nothing about it can move
  afterwards.
* **The path is already tracked.** `_best` and `_worst` follow every open trade
  from the quote stream, because `Shadow` and `best_r` already need them. So
  whether a level *was reached* is a fact this service already holds, not a
  reconstruction from bars that may have missed the touch.

What it still cannot know is the **fill**. A limit at the suggested level would
have been filled at that level or not at all, so the comparison is fair for a
take-profit and optimistic for anything that would have required chasing. The
scored figure is therefore an upper bound on what the suggestion was worth, and
`optimistic` says so on every row rather than leaving somebody to discover it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Side

#: How far past the entry a suggestion has to sit before it is worth scoring.
#: A turn predicted behind the entry is not an exit, it is the model saying the
#: move is already over - which is a different claim and is counted separately.
MIN_AHEAD = 0.1

#: Suggestions further out than this multiple of the trade's own risk are
#: recorded and not scored. The head is a linear model on bounded features and
#: it can extrapolate; a target at forty times the risk is a fault rather than a
#: forecast, and averaging it in would let one row own the comparison.
MAX_R = 20.0


@dataclass(frozen=True, slots=True)
class TurnExit:
    """One trade, and the exit the turn model would have taken instead.

    Not `Ride`, which `strategies.exits` already uses for a shipped exit
    policy. Two objects called the same thing in one package is how a reader
    ends up sure they know what an import means - the same collision
    `Affordability` was renamed out of.
    """

    feed: str
    side: Side
    entry: float
    stop: float
    target: float
    #: Where the turn model expected this leg to end, from the opening signal.
    suggested: float
    ticket: int = 0
    by: str = ""

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def ahead(self) -> float:
        """How far the suggestion sits in front of the entry, in R.

        Negative means behind it - the model expecting the move to be over
        before the trade even starts, which is information about the model and
        not an exit.
        """
        if self.risk <= 0:
            return 0.0
        return (self.suggested - self.entry) * self.side.sign / self.risk

    @property
    def scorable(self) -> bool:
        return self.risk > 0 and MIN_AHEAD <= self.ahead <= MAX_R


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """What each exit made on the same path, in units of the trade's own risk."""

    ticket: int
    feed: str
    took: float
    suggested_r: float
    reached: bool
    ahead: float
    optimistic: bool = True
    reason: str = ""

    @property
    def gained(self) -> float:
        """What riding the suggestion instead would have added. Can be negative."""
        return self.suggested_r - self.took

    def to_dict(self) -> dict:
        return {
            "shape": "turn-exit",
            "feed": self.feed,
            "ticket": self.ticket,
            "took_r": round(self.took, 3),
            "suggested_r": round(self.suggested_r, 3),
            "gained_r": round(self.gained, 3),
            "reached": self.reached,
            "ahead_r": round(self.ahead, 3),
            "optimistic": self.optimistic,
            "reason": self.reason,
        }


def suggestion_from(features: dict, side: Side) -> float:
    """The suggested exit price off a signal's own features, or 0.0 if absent.

    Absent is the common case and is not a fault: the head stays silent until it
    has settled two hundred turns on that feed, and a silent model must not be
    given a default - a made-up exit scored against a real one is worse than no
    comparison at all.
    """
    price = features.get("turn_price")
    if not isinstance(price, int | float) or not math.isfinite(price) or price <= 0:
        return 0.0
    # The model names a side too. A suggestion pointing the other way is the
    # model disagreeing with the trade, which is worth recording as a refusal
    # to suggest rather than as an exit behind the entry.
    stated = features.get("turn_side")
    if isinstance(stated, int | float) and stated:
        wants_up = stated > 0
        if wants_up != (side is Side.BUY):
            return 0.0
    return float(price)


def score(ride: TurnExit, *, best: float, took_r: float) -> TurnOutcome:
    """What the suggested exit would have made on the path the trade actually saw.

    `best` is the most favourable price the trade reached - the high for a long,
    the low for a short - which the service already tracks for `best_r`. If the
    suggestion sat inside that, a resting order there would have filled and the
    trade would have banked `ahead` R; if it did not, the suggestion never
    triggered and the trade would have ended however it actually ended.
    """
    if not ride.scorable:
        why = "no risk" if ride.risk <= 0 else f"suggestion {ride.ahead:+.2f}R from entry"
        return TurnOutcome(
            ticket=ride.ticket,
            feed=ride.feed,
            took=took_r,
            suggested_r=took_r,
            reached=False,
            ahead=ride.ahead,
            reason=why,
        )
    reached = (best - ride.suggested) * ride.side.sign >= 0
    return TurnOutcome(
        ticket=ride.ticket,
        feed=ride.feed,
        took=took_r,
        # Not reached means the suggestion changed nothing: the trade ran to
        # whatever ended it, and that is exactly what it actually made.
        suggested_r=ride.ahead if reached else took_r,
        reached=reached,
        ahead=ride.ahead,
    )


@dataclass(slots=True)
class TurnTally:
    """The running comparison, so the answer is a number rather than an argument."""

    rides: int = 0
    scored: int = 0
    reached: int = 0
    took_total: float = 0.0
    suggested_total: float = 0.0

    def add(self, outcome: TurnOutcome) -> None:
        self.rides += 1
        if outcome.reason:
            return
        self.scored += 1
        self.reached += int(outcome.reached)
        self.took_total += outcome.took
        self.suggested_total += outcome.suggested_r

    @property
    def gained_per_trade(self) -> float:
        """R a trade the suggestion would have added. **The whole question.**"""
        if not self.scored:
            return float("nan")
        return (self.suggested_total - self.took_total) / self.scored

    def to_dict(self) -> dict:
        return {
            "rides": self.rides,
            "scored": self.scored,
            "reached": self.reached,
            "took_r_per_trade": round(self.took_total / self.scored, 4) if self.scored else None,
            "suggested_r_per_trade": (
                round(self.suggested_total / self.scored, 4) if self.scored else None
            ),
            "gained_r_per_trade": (round(self.gained_per_trade, 4) if self.scored else None),
        }
