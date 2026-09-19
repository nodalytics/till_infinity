# Structures Vol Analogue

Rationale moved out of `till_infinity/structures/vol/analogue.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Analogue.__post_init__`

        A `default_factory` runs before the instance exists, so it can only
        close over the module constant - and the field was therefore inert:
        `Analogue(memory=50)` kept four thousand rows and reported the fifty it
        had been asked for nowhere. A test caught it.

        That is worth more than a line of code. An unbounded accumulator that
        *looks* bounded is the exact shape behind four of this repository's
        outages, and it is the shape this module's own docstring claims to have
        avoided.


## `Analogue.predict`

        `None` rather than a number when there is nothing to say, which is the
        rule the rest of this package follows: a missing reading is missing,
        and zero here would be the confident claim that the standing estimate
        is exactly right.

        Distance-weighted rather than a plain mean over the k. The nearest of
        four thousand rows and the twenty-fourth nearest are not equally
        informative, and averaging them flat throws away the ordering that is
        the entire content of the method.


