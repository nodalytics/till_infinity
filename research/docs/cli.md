# Cli

Rationale moved out of `till_infinity/cli.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `_load_env`

    Every setting here comes from an environment variable, which is right for
    deployment and tedious for development - a dozen exports before a run, and
    one forgotten export produces a service that starts and silently does less.
    A `.env` file makes the whole configuration one reviewable thing.

    Real environment variables win over the file, so a deployment that sets
    them properly is never overridden by a stray `.env` that got committed.


## `prices_spreads`

    Two kinds. **`cross`** is two USD pairs at one broker, which is an implied
    FX cross exactly - `ln(EURUSD) - ln(GBPUSD)` is `ln(EURGBP)` with no
    residual and no fitted ratio - and it is **tradeable**, as two orders on one
    account. **`venue`** is the same asset at two venues, which reverts by
    arbitrage and is the kind `research/zma.md` measured AUC 0.67 to 0.73 on;
    this desk cannot hold it, because that means a position at each venue.

        till-infinity prices spreads
        till-infinity prices spreads --kind venue --build 1m --build 15m


## `structures_levels`

    Touch counts are *effective* counts: evidence decays with age, so a level
    tested ten times last quarter reads lower than one tested ten times this
    week. That is the point - a level is only as good as its recent behaviour.

    With `--at`, the nearest levels are judged from that price: which way the
    history says it goes, against the base rate, and whether that clears the
    bar for being worth acting on.


## `structures_fit`

    Reads the journal for resolved level calls - the features a call was made
    from, and the push that followed - and fits progressively: every example is
    predicted before it is learned, so the evaluation is walk-forward by
    construction rather than by an arrangement that can be got wrong.

    The score is reported next to two baselines, because alone it means
    nothing: predicting the average, and what the levels model already said at
    the time. An FM that does not beat the model it was meant to improve on is
    not an improvement.


## `structures_gaps`

    The check after a market close. A touch open at the Friday close used to
    resolve on the Sunday reopen, and the recorded push was the *gap* - written
    into the level's own statistics and into `facto`'s targets as that level's
    reaction. `GAP_FACTOR` discards those now, so the expected answer here is
    **none**, and anything listed is the guard having failed.

    Split by whether the instrument trades through the weekend, because that is
    the control: crypto never closes, so a gap there means the collector
    stopped rather than the market. Same guard, different cause, and the
    difference is only visible side by side.


