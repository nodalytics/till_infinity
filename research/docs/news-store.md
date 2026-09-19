# News Store

Rationale moved out of `till_infinity/news/store.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `SqliteStore.series`

        `observations` takes the newest rows across all series, which is the
        right shape for a status page and the wrong one for a model: thirty
        series interleaved into a limit of fifty gives one or two points each,
        and a change over ninety days cannot be computed from two points.

        Oldest first because a consumer folding these into a time-ordered
        window should not have to reverse them, and ninety days of thirty
        daily-at-fastest series is a few thousand rows - small enough to read
        whole rather than paged.


