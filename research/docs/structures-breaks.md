# Structures Breaks

Rationale moved out of `till_infinity/structures/breaks.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `last_break`

    Labels the sequence and walks it once, remembering the previous swing of
    each kind and the label it carried. A flip in either series is a break; the
    most recent of the two is returned.

    Returns `None` for a sequence with no flip in it - which is the honest
    answer for a market that has simply been trending, and is why this is not a
    trend filter.


