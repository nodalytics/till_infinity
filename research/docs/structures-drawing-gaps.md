# Structures Drawing Gaps

Rationale moved out of `till_infinity/structures/drawing/gaps.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `points`

    **A gap has no side**, like a mode and unlike a swing: price can arrive at
    it from either direction, and which side it is on depends only on where
    price is now. `Swing.HIGH` and `Swing.LOW` are the only turns `form`
    accepts, so a gap above the last price is emitted as resistance and one
    below as support.

    `confirmed` is the time of the **third** bar, not the middle one. The gap
    does not exist until the third bar has printed - that is what makes it a
    gap - so anything asking when this became usable must not be told the
    middle bar's time, which is a bar earlier than the evidence.


