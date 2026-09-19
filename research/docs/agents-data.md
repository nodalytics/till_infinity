# Agents Data

Rationale moved out of `till_infinity/agents/data.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `spreads`

    The window **excludes the latest quote**, which is returned beside it as
    `latest_bps`. That is not a detail: the question anyone asks here is "is
    what I am looking at now unusual", and answering it against a window
    containing that same reading is circular. It produced exactly that - an
    alert reporting a venue "at the historical maximum" on a maximum of 8.49
    against a current 8.5, which is the current reading having been folded into
    its own comparison. True by construction and worth nothing.

    `latest_pctile` is the honest version: what share of the *prior* samples
    were at or below the latest one. 100 means genuinely wider than anything
    else in the window, and it can now say so without tautology.


## `arrivals`

    Not a tool - nothing here is meant for a model to read. It exists so the
    headline gate can start knowing how much is normally written about each
    instrument, instead of learning it again from nothing after every restart.

    That matters more than it sounds. The gate needs a handful of arrivals per
    feed before its rate means anything, and the feeds worth hearing about are
    exactly the ones slowest to get there: usdchf runs at five headlines a week,
    so it would spend eleven days deaf, and the service restarts on every
    deploy. Thirty days of history clears the warmup for every tracked feed at
    once.

    Deliberately unbounded by `MAX_ROWS`: this is a startup read of two columns,
    not a query whose result reaches a prompt.


## `levels`

    Each carries where it is, how wide the zone is, how many *effective*
    touches it has from each side, and what price did on arrival - including
    `trap_rate`, the share of breakouts here that were taken back.

    Touch counts are decayed by age, so they are smaller than a raw tally and
    are the number that should be reasoned about: a level tested ten times last
    quarter is weaker evidence than one tested twice this week.


## `next_levels`

    Ordered by *time*, not distance - a level on a fast timeframe can be
    reached long before a nearer one on a slow timeframe, because the clocks
    differ by more than the distances do.

    Each carries a median time and a slow case. There is no average: the
    first-passage distribution has an infinite mean, so any "average time to
    reach" grows with however long you collected data for.


