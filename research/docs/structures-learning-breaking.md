# Structures Learning Breaking

Rationale moved out of `till_infinity/structures/learning/breaking.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Breaks.inputs`

        Takes the object rather than importing `reactions.Features`, so this
        module stays cheap to import and to test - and so a caller can pass the
        plain feature dictionary a signal carries.

        `ABSOLUTE` names are taken as magnitudes. A signed slope would ask a
        linear fit to learn that steep up and steep down both break, which is
        exactly the shape a linear fit cannot represent.


## `Breaks._fresh_start_if_the_recipe_changed`

        Adding an input is handled already: `Logistic` and `Scaler` rebuild on
        a length change. **Re-meaning one is not**, and that is the case this
        catches. `slowing` was an unbounded ratio whose running mean in the
        standardiser had reached 141,380,329; capping it at 10.0 fixed every
        future value and could never fix the statistics, because `Scaler` is
        plain Welford with no decay - at n=5,256 a clamped observation moves
        the mean by (10 - 141M)/5256, and recovery would take on the order of
        1e11 samples. The cap read as done and changed nothing.

        Checked here rather than in `__setstate__`, which was tried and is a
        trap: a `slots=True` dataclass is a new class object built after the
        method bodies compile, so bare `super()` raises at unpickling time
        only, and `Breaks.recipe` is the slot *descriptor* rather than the
        default, so the comparison never matches.


