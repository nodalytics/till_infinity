# Structures Learning Attention

Rationale moved out of `till_infinity/structures/learning/attention.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Embedding`

    The features in `reactions.Features` say what a level *looks like* -
    touches, strength, whether it is a pivot. This says what it has *done*, and
    two levels can look alike and behave nothing alike.

    The update is deliberately the simplest thing that could work: project the
    touch's own description into the vector's width and nudge toward it when
    the level held, away when it broke. There is no objective being minimised
    here and it should not be described as if there were - it is a running
    summary of behaviour, and its value is whether levels that end up near each
    other go on to do the same thing.


