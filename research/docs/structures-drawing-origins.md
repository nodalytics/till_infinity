# Structures Drawing Origins

Rationale moved out of `till_infinity/structures/drawing/origins.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `zone_of`

    `bar` is anything carrying `open`, `high`, `low` and `close` - duck-typed
    rather than imported, so `structures` need not depend on the trading
    package that happens to define a Bar today.

    High to low is the interest placed during that bar. Where the whole range
    reaches `WIDE_BAR` volatility units the bar is mostly wick - price went
    there and did not stay - so the open to the close is used instead: the part
    that traded rather than probed.


## `extremes_in`

    Closes rather than highs and lows, because that is what an origin is made
    of: `Origins.observe` walks a series of closes, so the finer transition has
    to be a close too or the two are measuring different things.

    None unless the finer series reaches **both ends** of the bar. Partial
    cover is not cover - the extreme of whatever fraction happened to be in the
    window is not the extreme of the bar, and a refinement computed from two of
    the fifteen minutes is worse than none.


