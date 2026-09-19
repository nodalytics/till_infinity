# Trading Affordable

Rationale moved out of `till_infinity/trading/affordable.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `judge`

    Sized through `sizing.lots` rather than by arithmetic repeated here, so the
    verdict is the same decision the desk makes at the moment of the trade. A
    report that disagrees with the thing it reports on is worse than none.

    The stop tested is the wider of what the strategy asks for and what the
    broker will accept: a strategy stop inside `stops_level` is not the stop
    that gets placed, and pricing the instrument on it would call something
    affordable that is not.


