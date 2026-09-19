# Trading Candles

Rationale moved out of `till_infinity/trading/candles.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `hammer`

    Not required to be a bullish bar. A hammer's message is in the tail - the
    auction went down, found no takers and came back - and whether the close
    finished a tick above or below the open is a detail of where the bar
    happened to open, not of what happened inside it.

    A body of almost nothing is accepted rather than refused. That shape is a
    dragonfly doji, and at a level it is the *strongest* version of this
    pattern, not a degenerate one: price left and came all the way back.


## `rejection_wick`

    The side that matters is the one price was pushed back *from*: a long is
    rejected at the low, so its evidence is the lower wick. Zero on a bar with
    no range, which is a bar nothing happened in.

    Read by the entry rule rather than by the pattern check - a long tail is
    not what makes a hammer a hammer, it is what makes waiting for a pullback
    worth doing.


## `confirms`

    Three conditions, and a pattern satisfying two of them is not a weaker
    signal - it is a different event:

    1. the pattern is present on the **last closed bar**,
    2. that bar **reached the level**, and
    3. it **closed on the side the trade wants**, which is what separates a
       rejection from a breakout that has not finished yet.

    The third is the one most easily left out and the most important. A hammer
    whose tail pierces support and whose close is still below it is not support
    holding; it is support breaking, drawn in a shape that looks reassuring.


