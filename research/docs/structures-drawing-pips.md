# Structures Drawing Pips

Rationale moved out of `till_infinity/structures/drawing/pips.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `extremes`

    **Two passes, not one**, and `points` above says why: mixing highs and lows
    in a single series compares points that never coexisted - a "swing" from a
    bar's high to the next bar's low is a move nothing traded. So the highs are
    run for peaks, the lows for troughs, and each keeps only the swing type it
    is entitled to produce.

    Why bother, when the close series has drawn every level here so far: a
    swing high *is* a high. A close series cannot see the price a rejection
    actually reached, so a level drawn from it sits wherever the bar happened
    to settle after being turned away - which is a price nobody defended, some
    distance inside the one they did. The engine has warned about this from the
    other direction for months, on every feed that arrives without extremes:
    "levels on this series are forming from closes alone".

    Whether it draws *better* levels is a question for the outcome machinery
    rather than for this docstring, which is why it is a separate pass rather
    than a change to `pip`. Both can run, and the record can say which price
    gets respected.


