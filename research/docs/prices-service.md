# Prices Service

Rationale moved out of `till_infinity/prices/service.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `notices`

    **This used to be one notice carrying only the newest bar**, whatever the
    sweep had written. Everything else went to the store and never reached the
    bus, so on any sweep that wrote more than one bar the live path formed
    levels from a subset of the series and counted touches on a subset of the
    interactions - silently, and differently from a replay of the same data.
    That is the same shape as the close-only bug: the live path seeing less
    than the store, with nothing saying so.

    Republishing is safe where it overlaps. `Series.add` treats a bar it
    already holds as a correction rather than a new one, and the touch check is
    gated on the bar being new, so a bar delivered twice cannot count its
    interaction twice.


## `derive`

    **Runs after the sweep, not beside it.** These are made *out of* the bars
    the sweep just wrote, so a pass that overlapped it would build the spread
    from one leg's new bar and the other's old one - which is the forward-fill
    this module refuses everywhere else, arriving by timing instead of by code.

    Written through `store.write` and announced through `notices` exactly as a
    fetched series is, so nothing downstream can tell the difference: that is
    the whole point of constructing them here rather than in a harness.


