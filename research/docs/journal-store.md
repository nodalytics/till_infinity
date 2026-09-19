# Journal Store

Rationale moved out of `till_infinity/journal/store.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `read`

    `limit` is honoured as asked. It used to be silently clamped to `MAX_ROWS`,
    which made the argument a suggestion: `facto.dataset` asked for 200,000 rows
    to assemble its training examples, received the most recent 500, and found
    ~167 usable outcomes in a journal holding 9,359 of them. Nothing reported a
    truncation, so the shortfall read as a data problem - outcomes recorded
    without their features - rather than as a window that was never opened.

    `MAX_ROWS` remains what it always was in practice: the ceiling the CLI puts
    on a listing so a long history cannot flood a terminal. That is a display
    concern, and it belongs to the display. A caller that names a number is
    stating what it can hold, and the callers here bound themselves.


