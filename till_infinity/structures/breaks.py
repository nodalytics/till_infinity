"""The moment the market changed its mind, and the line it changed it at.

`pips` finds the swings and labels each one against the previous swing of its
kind - HH, LH, HL, LL. That is a description of where price has been. This
module reads one event out of that description: the point where the sequence
**flips**, which is the first swing that disagrees with the run before it.

A run of higher lows is a market being bought at successively better prices.
The first lower low says that stopped being true, and the line it stopped being
true at is the last higher low - a price that was defended and then was not.
Symmetrically, a run of lower highs ending in a higher high breaks the last
lower high.

## Why the broken line and not the break

The useful number is not where the break was confirmed, it is **the price that
was broken**. Price that has traded through a defended level tends to come back
to it, and the return is the tradeable moment: the level that failed as support
is the level that is now tested as resistance. Whoever was defending it is gone,
and whoever ran the stops beneath it is looking to sell the retest.

That return is what gets called a liquidity sweep when it happens the other way
round - price reaching through the line to take the orders resting past it
before turning. Either way the line is the same price, and it is the one worth
recording.

## What this is not

It is not a trend filter and not a prediction. It says a change of character
happened and names the price it happened at. Whether that price is worth
trading is a question for whatever consumes it, answered against a record -
which is the same discipline `zma` is held to.

**Only the flip, never the continuation.** A second lower low after the first
is the move carrying on, not the market changing its mind, and treating it as
one would report a break on every leg of a trend. The flip is the event; the
rest is the aftermath.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..shared.state import Restorable
from .drawing.pips import Point, Structure, Swing
from .drawing.pips import structure as label_structure

#: Sides, in the convention `zma.agrees` uses: +1 expects a rise, -1 a fall.
UP = 1
DOWN = -1


@dataclass(frozen=True, slots=True)
class Break(Restorable):
    """A change of character, and the price it happened at.

    `Restorable` although nothing persists this - see `Engine._breaks` for why
    it should not be. The mixin is what every dataclass in this package carries
    so that a save predating a field starts cold rather than raising, and the
    guard that enforces it cannot know which classes a future version might
    decide to store. Opting out would be a decision made once and inherited by
    whoever changes that.
    """

    #: **The direction the market turned, not the direction it broke.** A run
    #: of higher lows ending in a lower low is a turn *down*, and what a
    #: consumer wants to know is which way to lean afterwards.
    side: int
    #: The swing that was broken. This is the line to trade - see the module
    #: note on why it is the broken price rather than the breaking one.
    price: float
    #: When the broken swing was made, and when the swing that broke it was.
    #: Both, because the distance between them is how long the level stood, and
    #: a level that held for a day is not the one that held for four bars.
    made: int
    broke: int
    #: How far past the line the breaking swing reached, in price. Kept because
    #: a break by a hair and a break by a mile are different claims, and the
    #: threshold between them belongs to the consumer rather than here.
    past: float

    @property
    def held_for(self) -> int:
        """Seconds the broken line stood before it failed."""
        return max(0, self.broke - self.made)


def last_break(turns: Sequence[Point]) -> Break | None:
    """The most recent change of character in a swing sequence, if there is one.

    Labels the sequence and walks it once, remembering the previous swing of
    each kind and the label it carried. A flip in either series is a break; the
    most recent of the two is returned.

    Returns `None` for a sequence with no flip in it - which is the honest
    answer for a market that has simply been trending, and is why this is not a
    trend filter.
    """
    previous: dict[Swing, tuple[Point, Structure | None]] = {}
    found: Break | None = None

    for point, structure in label_structure(turns):
        if point.swing not in (Swing.HIGH, Swing.LOW):
            continue
        before = previous.get(point.swing)
        previous[point.swing] = (point, structure)
        if before is None:
            continue
        prior, prior_label = before

        # The flip, and only the flip. `prior_label` being the opposite kind is
        # what makes this a change of character rather than the trend carrying
        # on - see the module note.
        if point.swing is Swing.LOW:
            broke = structure is Structure.LOWER_LOW and prior_label is Structure.HIGHER_LOW
            side = DOWN
        else:
            broke = structure is Structure.HIGHER_HIGH and prior_label is Structure.LOWER_HIGH
            side = UP
        if not broke:
            continue

        candidate = Break(
            side=side,
            price=prior.price,
            made=prior.time,
            broke=point.time,
            past=abs(point.price - prior.price),
        )
        if found is None or candidate.broke >= found.broke:
            found = candidate
    return found
