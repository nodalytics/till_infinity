# Structures Store

Rationale moved out of `till_infinity/structures/store.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `_schema`

    **A map rather than one hash over the lot, and that is the whole point.**
    A single fingerprint changes when *anything* changes, so adding a new model
    - `learning/racing.Races`, say - discarded every level, the break model and
    weeks of touches, for a class that was not in the old file at all and could
    not conflict with anything in it. That happened twice in one day.

    Compared key by key on load: a class in both the file and the build with
    different fields is the danger this exists for, and a class in only one of
    them is not. `Restorable.__setstate__` already defaults a field the state
    predates, and `codec.unpack` already warns about a class the build has
    dropped.

    Found by walking the package, because the hand-written list this replaces
    *was* the bug. It named seven classes and `Volatility` was not among them,
    so adding `_tick`, `_steps` and `_grid` to it left the hash unchanged. The
    old state was therefore accepted as compatible, and the service then
    crashed reading a field the save predated - `AttributeError` on a
    `slots=True` dataclass, which has no `__dict__` to fall back on, so an
    absent field is missing rather than defaulted.

    The throw landed inside the structures consumer, so nothing crashed
    outright: the container stayed healthy at 11% CPU and simply stopped
    producing for four hours, across twelve deploys, each one restoring the
    same stale state and dying the same way.

    A list is the wrong shape for this. Anyone adding a field to a persisted
    class would have to know the list exists, and the person who added those
    three did not. Walking means the guard covers classes nobody thought to
    register - including ones added later.

    The cost of a change here is a cold start, which is the policy `load`
    already states: slow but correct. That is the trade this hash exists to
    make, and it is a far better one than a silent stop.

    Imported lazily: `store` is imported by the modules these classes live in,
    and asking for them at module scope would be a cycle.


## `_reshaped`

    Only classes present in **both** can conflict. One that exists solely in
    the build is new and has no state to be wrong about; one that exists solely
    in the file has been dropped, and `codec.unpack` says so at the point of
    use rather than costing the whole file here.

    A `saved` that is not a map came from a format that stored a single hash.
    There is nothing to compare key by key, so it is accepted - the alternative
    is discarding exactly the state this change exists to stop discarding.


## `save`

    **Streamed, because the save was the thing killing the container.** The
    obvious form - `write_bytes(msgpack.packb(pack(state)))` - holds three
    copies of everything at once: the live state, the parallel tree `pack`
    builds, and the contiguous `bytes` msgpack renders it into. On production's
    206MB state that measured **+0.58GB** on top of a 1.45GB baseline against a
    2.6GB limit, and it is why the desk was OOM-killed 23 times in ten days.

    Writing through `pack_into` costs one 4MB buffer instead. The bytes are
    identical, so a file written either way reads back the same - which is what
    made this safe to change under a live state rather than a migration.

    The temp-file-then-rename is unchanged and is now doing more work: a
    streamed write is only atomic because of it. A crash halfway through leaves
    a partial `.tmp` and the last good file still in place.


