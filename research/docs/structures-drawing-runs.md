# Structures Drawing Runs

Rationale moved out of `till_infinity/structures/drawing/runs.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `points`

    Walks the series once, holding the current run's direction and its extreme.
    When price has come back off that extreme by `threshold` volatility units,
    the run is over: the extreme was a turn, and the bar that completed the
    retracement is when it became knowable.

    Returns points in the order they were *settled*, which is also the order
    they became usable. An unfinished trailing run contributes nothing - its
    extreme may still be exceeded, and emitting it would be the trailing-swing
    look-ahead that `pips.confirmed` exists to prevent.


