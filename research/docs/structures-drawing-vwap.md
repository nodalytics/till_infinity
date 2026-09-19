# Structures Drawing Vwap

Rationale moved out of `till_infinity/structures/drawing/vwap.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `points`

    Emitted on the same `Point` as every other pass, so nothing downstream can
    tell which formation found a level - the record decides which price is
    respected, not an argument here.

    A point is produced at the **end of each anchor**, at that anchor's VWAP,
    and only when price came within `touch_vol` of it during the anchor. The
    confirmation time is the anchor's last bar: a VWAP is knowable only once
    the bars it averages have closed, and dating it from the anchor's start
    would be drawing a level at a price nobody could yet compute.

    Anchors are wall-clock buckets `span` bars wide, so the same calendar moment
    falls in the same anchor however much of the window has aged out. See the
    module note - blocking by array index instead moved every level on every
    bar.


