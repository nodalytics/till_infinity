# Structures Vol Implied

Rationale moved out of `till_infinity/structures/vol/implied.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Fit`

    **The coefficient is the member.** A raw VIX quote scores worse than
    predicting the mean on four of the eight series measured - R-squared of
    -0.484 on spx500 daily - because VIX systematically exceeds realised
    volatility. That gap is the variance risk premium, it is a bias rather than
    noise, and one number removes it.

    Least squares by accumulated sums rather than by keeping the rows: it is
    exact, it is O(1) per bar, and it persists as six floats instead of a
    history. Strictly causal - `predict` uses only what `observe` has already
    been given, so a bar never informs its own forecast.

    One fit per `(feed, interval)` and not one pooled fit, because the premium
    differs by index: raw VIX scores second on us100 and last on spx500, which
    is what a per-index bias looks like.


## `latest`

    Synchronous and blocking - yfinance does its own HTTP - so callers push it
    onto a thread, the way `prices/yahoo.py` does for the same reason.

    Never raises, and **never blocks for long**. A source that is unreachable
    must leave the last good reading in place and let `MAX_AGE` retire it,
    because an exception here would take down a service whose actual job is
    levels - and a hang would do worse, since this runs inside the message loop.


## `seeds`

    **Why a file rather than a warm-up.** `MIN_FIT` is 250 observations and
    production gets one daily bar a day, so a member with no seed is about a
    *year* from voting, and `SCORE_WARMUP` at 60 daily bars is three months
    before its weight means anything. A design that does nothing until next year
    is not a design - see `research/specs/2026-09-11-vix-ensemble-member-design.md`.

    Never raises. A missing or malformed seed means the member warms the slow
    way, which is correct and slow rather than absent and silent.


