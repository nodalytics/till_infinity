"""Levels where price stopped at the *same* price twice.

`pips` ranks turns by **prominence** - how far price travelled away from them -
which answers "was this a significant turn". It says nothing about whether two
turns happened at the same price, and that is a different claim entirely: a
double top is not two significant highs, it is two highs at one price, and the
second one is evidence about the first.

The desk reading is that resting orders sit there. Whether or not that is why,
the testable version needs no story: **a price reached twice and rejected twice
is a price with a record**, and a price reached once has an anecdote.

## Why this is not what `form` already does

`levels.form` clusters turns within one volatility unit and needs three. That
is a much looser question - three turns anywhere inside a unit-wide band, which
on most instruments is most of a range. This asks whether the extremes are
*equal*, at `EQUAL_VOL` (a quarter unit), which is tight enough that the answer
is about the price rather than about the neighbourhood.

So the two coexist: a cluster `form` would build from three loosely-grouped
turns is one object, and two extremes a quarter of a unit apart is another, and
this pass exists to let the outcome machinery say whether the tight one is
worth more. Every point it emits would also be found by `pips`; what is new is
which of them it emits and how it ranks them.

## Emitted once per member, so the cluster survives

`form` needs three turns to make a level, and an equal-high pair is two by
construction. That is deliberate: on its own this pass draws a level only where
price stopped at one price three times, which is a strong claim and a rare one.
Where it finds only a pair, the points still merge into a level another pass
drew, and `agree` records that this one found it too - which is the whole point
of running several.
"""

from __future__ import annotations

from collections.abc import Sequence

from .pips import Point, Swing
from .volatility import Volatility

#: How close two extremes must be to count as the same price, in volatility
#: units. A quarter, because a whole unit is what `form` already clusters at
#: and this pass exists to ask the tighter question.
EQUAL_VOL = 0.25

#: How many extremes at one price before it is worth reporting. Two is the
#: claim - a double top - and one is a turn `pips` already found.
MIN_EQUAL = 2


def equals(
    points: Sequence[Point],
    vol: Volatility,
    *,
    tolerance_vol: float = EQUAL_VOL,
    minimum: int = MIN_EQUAL,
) -> list[list[Point]]:
    """Groups of turns at the same price and on the same side, largest first.

    Grouped **per side**, because a high and a low at one price are not a
    double top - they are a price that has been both support and resistance,
    which is a different and already-modelled thing (`levels` calls it a
    flip). Mixing them would report a level as twice-rejected when it was
    rejected once from each direction.
    """
    found: list[list[Point]] = []
    for side in (Swing.HIGH, Swing.LOW):
        ordered = sorted((point for point in points if point.swing is side), key=lambda p: p.price)
        if not ordered:
            continue
        run: list[Point] = [ordered[0]]
        for point in ordered[1:]:
            last = run[-1]
            gap_bps = abs(point.price - last.price) / last.price * 10_000 if last.price else 0.0
            if vol.units(gap_bps) <= tolerance_vol:
                run.append(point)
            else:
                if len(run) >= minimum:
                    found.append(run)
                run = [point]
        if len(run) >= minimum:
            found.append(run)
    found.sort(key=lambda group: -len(group))
    return found


def points(
    times: Sequence[float],
    prices: Sequence[float],
    vol: Volatility,
    *,
    count: int = 12,
) -> list[Point]:
    """Equal extremes as turning points, so levels can form at them.

    Built on `pips.points` rather than on the bars directly: the turns are
    already found and already confirmed, and re-deriving them here would be a
    second implementation of the same thing that could drift from the first.

    Every emitted point keeps its own time and price - they are real turns, not
    a synthesised average - so the outcome machinery sees the same objects it
    always has. What this pass changes is *which* it emits: only those with a
    twin, ranked by how many twins they have.
    """
    from . import pips as pp

    if len(prices) < 3 or len(times) != len(prices):
        return []
    turns = pp.points(times, prices, count)
    out: list[Point] = []
    for group in equals(turns, vol):
        # How many times this price has been reached, in basis points, so it
        # ranks the way prominence does for the other formations. A price
        # stopped at four times outranks one stopped at twice.
        weight = float(len(group)) * 10_000
        out.extend(
            Point(
                index=point.index,
                time=point.time,
                price=point.price,
                swing=point.swing,
                prominence_bps=weight,
                confirmed=point.confirmed,
            )
            for point in group
        )
    out.sort(key=lambda point: point.time)
    return out
