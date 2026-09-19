# Structures Drawing Rounds

Rationale moved out of `till_infinity/structures/drawing/rounds.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `points`

    **These are not turns and the code should not pretend otherwise.** Every
    other formation emits a price where something happened; this emits a price
    because of how it is written. It is given `Swing.HIGH` above the last price
    and `Swing.LOW` below for the same reason a mode is - those are the only
    two `form` accepts - and the `index` and `time` are the last bar's, because
    a round number has no moment of its own.

    That is a real weakness and it is the reason this is worth measuring rather
    than assuming: a formation with no history behind it either works or is
    superstition, and the touch record is what separates those.


