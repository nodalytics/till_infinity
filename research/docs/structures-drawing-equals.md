# Structures Drawing Equals

Rationale moved out of `till_infinity/structures/drawing/equals.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `points`

    Built on `pips.points` rather than on the bars directly: the turns are
    already found and already confirmed, and re-deriving them here would be a
    second implementation of the same thing that could drift from the first.

    Every emitted point keeps its own time and price - they are real turns, not
    a synthesised average - so the outcome machinery sees the same objects it
    always has. What this pass changes is *which* it emits: only those with a
    twin, ranked by how many twins they have.


