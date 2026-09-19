# Structures Vol Returns

Rationale moved out of `till_infinity/structures/vol/returns.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Returns`

    One model per series rather than one across the book, which is a real
    choice with a cost: pooling would give every instrument the benefit of
    every other's history, and that is exactly the argument the scale-free
    features exist to support. It is kept separate because the *macro* inputs
    differ per instrument - a euro cross and a dollar index do not share a
    carry gap - so a pooled model would fit one weight that is right for
    neither.


