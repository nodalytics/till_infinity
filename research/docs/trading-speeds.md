# Trading Speeds

Rationale moved out of `till_infinity/trading/speeds.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Speeds.ready`

        See `warmup` for why this is not the slowest half-life any more, and
        what is given up by lowering it.

        **The fallback is here rather than in a constructor because no restore
        path can bypass a comparison.** `restore_number` passes `None` through
        deliberately - "a value that will not convert is left exactly as it was,
        so the fault stays visible at the point of use rather than being turned
        into a plausible zero" - and it stayed visible by raising `'>=' not
        supported between 'int' and 'NoneType'` here, which the per-message
        guard turned into six skipped signals in twenty-seven minutes on
        2026-09-11.

        A `__post_init__` would not have caught it: the codec builds through
        `cls.__new__` and a generated `__setstate__`, which is exactly how the
        `None` arrived. Same family as `Seen.price` the same morning.


