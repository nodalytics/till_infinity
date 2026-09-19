# Structures Learning Decay

Rationale moved out of `till_infinity/structures/learning/decay.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Decay`

    Keyed by a name the caller chooses, so several models can be watched by one
    instance and the log line says which.

    `Restorable` because it is in `structures` and therefore persisted, and a
    watcher whose alarm history resets on every restart would report a model as
    healthy because the process is young - which is the failure the daily loss
    limit already made once. The detectors themselves are River objects rebuilt
    on first use; what survives is the count and the rate, which is what a
    reader wants.


