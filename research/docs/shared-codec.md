# Shared Codec

Rationale moved out of `till_infinity/shared/codec.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `registry`

    Walked rather than listed, for the reason `store._schema` gives about the
    hand-written list it replaced: a list is a thing somebody has to remember
    to update, and the person who adds a class is exactly the person who does
    not know it exists.

    Recurses into subpackages, so this keeps working when `structures` is
    eventually organised into folders - which is the entire point of the
    exercise.

    `package` walks somewhere else instead, which is what lets `trading` keep
    its own state in the same format. **Each package gets its own registry
    rather than one shared across both**: keys are `basename.ClassName`, and
    `config.Settings` exists in each - a shared map would silently resolve one
    package's state into the other's class.


## `pack_into`

    **The same bytes `msgpack.packb(pack(value))` produces, at a fraction of the
    memory.** `pack` builds a complete parallel tree of plain dicts and lists
    mirroring the entire state, and `packb` then renders that tree into one
    contiguous `bytes`. Both exist in full, alongside the live state, at the
    moment of the write.

    Measured on production's own 206MB state: holding it costs 1.33GB resident
    and a save adds **+0.58GB** on top - against a 2.6GB container limit and a
    1.45GB baseline. That transient is what OOM-killed the desk 23 times
    between 1 and 10 September, and hourly sampling never saw it because it
    lives entirely between samples. See `research/starving.md`.

    This walks the same structure and emits each node as it is reached, so the
    extra memory is one `CHUNK` plus whatever a single leaf costs, rather than
    two copies of everything.

    Returns the number of bytes written, because a save that silently wrote
    nothing is the failure this replaces a single `write_bytes` with.

    **It must stay a mirror of `pack`.** Every branch below is the same branch
    in the same order, and a tag written here that `unpack` does not know is a
    file nobody can read. `test_streaming_a_save_writes_what_packing_it_would`
    is what holds the two together.


## `_spill`

    `msgpack` needs the length before the body, which is the only reason the
    temp file exists: pickling twice to measure it would cost the time instead
    of the memory, and pickling into a list of chunks costs the memory again
    under a different name.

    The header is written by hand because `msgpack.Packer` exposes
    `pack_map_header` and `pack_array_header` but nothing for `bin`.

    **The width has to match what `packb` would have chosen**, which is the
    narrowest that fits: `bin8` under 256 bytes, `bin16` under 65536, `bin32`
    above. Always writing `bin32` is valid msgpack and reads back identically -
    and it is not the same bytes, so
    `test_streaming_a_save_writes_what_packing_it_would` failed on a one-byte
    difference at offset 339. That test exists for exactly this: a difference
    that changes nothing about meaning and everything about whether the two
    writers can be swapped under a live 206MB file.


## `_homes`

    Built the same way `registry` is built, and cached for the same reason:
    walking the package on every raw blob would be paid thousands of times
    reading one state file.

    **`structures` by name, and not by accident.** This map exists for one
    historical event - the day `structures` was organised into folders and
    every raw pickle blob in a 58MB state file went on pointing at
    `till_infinity.structures.anomaly`, which no longer existed. It repairs
    that one package's history. Walking whatever package this module happens
    to live in would have quietly become `shared` the moment this file moved,
    and the symptom would have been the same cold start it was written to
    prevent.

    Imported inside the function rather than at the top, because `structures`
    imports this module and the cycle would be real at import time and is not
    at call time.


## `_Relocating`

    The gap in this codec's own reasoning, found the hard way. The docstring
    above says raw blobs pickle *river's* classes and this project does not
    move those - so a reorganisation was safe. It is not quite true: at least
    one blob referenced `till_infinity.structures.anomaly`, and after that
    module moved into `learning/` the whole 59MB file failed to read with
    `No module named 'till_infinity.structures.anomaly'` and structures
    started cold.

    So the basename rule that protects the *named* classes has to protect the
    pickled ones too. `find_class` maps any `till_infinity.structures.X` to
    wherever X lives now, which is the `find_class` override
    `research/handoff.md` listed as the only migration that ends clean.


