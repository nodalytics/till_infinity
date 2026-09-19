# Structures Drawing Level_Range

Rationale moved out of `till_infinity/structures/drawing/level_range.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `between_origins`

    An origin is where a violent move began, so the interest that stopped the
    last advance is still resting there. That is a different object from a
    confluence zone, which is a price several timeframes happen to have drawn
    a level at, and the difference is not academic: measured over 4,117
    published calls on 2026-09-07, at 4h the confluence box is **385bps wide
    against the origin box's 71bps**, and wider on 2,711 of 2,724.

    A box of 3.85% is not a box a trade held for a day moves inside. Its far
    wall is a target price cannot reach, and a position inside it is a reading
    about a range that will never be traversed - the same failure the 15m
    anchor had, arrived at from the other direction.

    The confluence-anchored version of this (`anchored`, with a `PLACED_BY`
    ceiling on which timeframes could place a wall) was removed rather than
    left beside it. It was a careful answer to the wrong question, and leaving
    it would have meant someone finding it and using it.

    Bounds are the origins' **near edges** - `high` for the one below, `low`
    for the one above - because the tradeable room ends where the band starts.
    Either side may be absent, which is open air rather than a distant wall.


## `within`

    **A range with a 1h ceiling and a 5m floor is not a range.** The two bounds
    have to be the same kind of object or the box measures nothing: a 5m zone
    is a place price paused for a few bars, a 1h zone is a place it turned, and
    the distance between one of each is a number with no meaning attached.

    So the span is filtered to the call's own timeframe and coarser. Higher is
    the safe direction - a 4h zone is a real boundary for a 15m trade, while a
    15m zone is noise inside a 4h one - which is the same asymmetry
    `confluence` already relies on when it lets the higher timeframe carry the
    significance and the lower carry the placement.

    A zone with no members has no span and is dropped: it cannot be shown to
    belong.

    `placed_by` is the other end, and it reads the **other** property. A zone
    is not excluded for reaching into the daily or the week - that is what
    makes it significant - it is excluded when *nothing finer agrees with it*,
    because then the only price on offer is one a week of auction produced, and
    a box built from two of those is not a box a day-long trade moves inside.
    Empty means no such requirement, which is what a caller without an opinion
    wants.


## `level_range_of`

    `unit` is one volatility unit as a price distance - the same conversion
    every other reading here uses, passed in rather than recomputed so a
    range cannot disagree with the signal it is attached to.

    `interval` keeps the two bounds comparable: only zones drawn on that
    timeframe or a coarser one are considered, because a ceiling from 1h and a
    floor from 5m are not two ends of one thing. Empty means take them all,
    which is what the tests and any caller without a timeframe want.

    A zone sitting exactly at `price` is treated as **below**, matching
    `Level.side_of`, which resolves the same tie the same way. Consistency
    matters more than the choice: price is at the level either way, and the two
    modules disagreeing would put the same touch on different sides of its own
    range.


