# Structures Learning Drift

Rationale moved out of `till_infinity/structures/learning/drift.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Drift._counts`

        **`Drift` is persisted and is not a `Restorable` dataclass**, so nothing
        fills in a field a save was written before. `_agreement` was added with
        the KSWIN work; every instance restored from an older save came back
        without it, and the first time ADWIN actually fired the attribute
        access threw.

        That threw inside the structures consumer, which had no per-message
        guard, so the service stopped and the container stayed `healthy` -
        eleven hours of it on 2026-09-08, with 132,807 bus warnings burying the
        one line that named the fault. Both of those are fixed too; this is the
        fault itself.

        Asked for rather than assumed, which is the same guard `_remember_origins`
        needed for `_origins` and `_note_change` for `_changes`.


