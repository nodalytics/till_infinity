# Agents Analyst

Rationale moved out of `till_infinity/agents/analyst.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `build_model`

    A monitor that goes quiet because one model returned a 529 is a monitor
    that failed at the only moment it mattered, so a degraded answer from the
    next model down beats no answer. Fallbacks may cross providers - a Claude
    primary with a GPT spare survives an outage at either.

    A fallback whose client is not installed, or whose key is not set, is
    dropped with a warning rather than taking the run down. It is a spare;
    refusing to start because a spare is missing defeats the point.


## `budget`

    A constant here has now failed twice, and both times for the same reason:
    the model investigates what it is handed, so the calls it makes scale with
    the number of instruments in the window, and that number keeps growing.
    Twelve died at fourteen calls when the sixth instrument was added; thirty-two
    died at **thirty-seven** on 2026-08-17 with fourteen instruments tracked.

    The comment beside the constant already said what was wrong with the fix
    applied to it - *"raising the limit each time is chasing rather than
    fixing"* - and then it was raised, and the chase continued. So the budget
    is a function of the work now: a fixed overhead for orienting and answering,
    plus an allowance per subject.

    `settings.tool_calls` stays as the **ceiling**, so `AGENTS_TOOL_CALLS` still
    caps cost absolutely and a question about nothing in particular is bounded
    the way it always was.


