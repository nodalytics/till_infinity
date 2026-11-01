"""What a round trip may cost, measured against the stop rather than the target.

## Why this is its own module and not a number in three places

Because it was a number in three places and only the unmeasured one fired.

The desk had four cost limits. `SurpriseProfile.cost_share` and
`deciding.COST_SHARE`, both 0.10 of the **target**, are the two that run.
`Envelope.max_spread_risk_fraction` at 0.16 of the **risk** and
`Envelope.max_spread_fraction` at 0.25 of the target live inside
`Guard.allows`, which has no production caller, and `DeskConfig
.max_spread_vol` at 0.5 volatility units is read by nothing at all. So the
only limit that ever refused a trade was the one with no measurement behind
it, and `deciding.py` cited `surprise.py` as the place it was measured while
`surprise.py` cited nothing.

**The denominator is the whole point, and the desk measured which one.**
`risk/guard.py` records it: *49 trades passed the reward test while expensive
against the risk, at -0.471R and 53% stopped, for -502.70.* A permitted spread
that scales with the target lets a distant target buy the right to pay more; a
spread that is half the stop distance is half the stop distance wherever the
target sits. So the limit that bites belongs on the risk.

On the geometry both rules use - a 2-volatility stop and a 2R target - 0.16 of
the risk is **0.32 volatility units** and 0.10 of the reward is **0.40**. The
measured limit is the tighter of the two, so adding it refuses trades the
looser one passed. That is the intent: those are the 49.

## What it binds on, measured per venue

A round trip as a share of one volatility unit, on 15m bars, from the recorded
quotes split by venue - pooled they say something different, and
`pooled-medians-invert-subgroups` is why that matters:

| instrument | venue | round trip | refused at 0.32u |
| --- | --- | --- | --- |
| eurusd | FOREXCOM | 0.04 | 0% |
| eurusd | SAXO | 0.09 | 0% |
| eurusd | **DERIV** | **0.26** | **29%** |
| eurusd | OANDA | 0.35 | 60% |
| eurusd | PEPPERSTONE | 0.81 | 99% |
| gold | DERIV | 0.02 | 0% |

Two readings worth keeping. The spread on one instrument varies nineteenfold
across six venues, so **the venue decides whether this gate binds at all** -
the threshold barely participates. And gold on the same venue costs an eighth
of what eurusd costs relative to its own movement, because its volatility unit
is five times larger for a smaller spread; that is a plainer explanation for a
book whose returns concentrate in gold than anything about a signal.

The volatility unit there is an EWMA of true range in basis points, which is
this desk's best measured forecast of the next bar's move and **not** the
statespace fold's `vol_bps` that the gate actually divides by. So the
percentages describe the instrument, not the gate's hit rate: measured on
proposals rather than on all bars, the looser limit refused 40% where this
says 12%, because a surprise is by construction a move large relative to the
scale the gate divides by.
"""

from __future__ import annotations

#: The share of the **risk** a round trip may cost. Measured; see the module
#: docstring and `research/docs/settings.md`.
#:
#: This is the one home for the number. `strategies/config.Settings` defaults
#: its own field from here and `Envelope` projects that, so a deploy still
#: moves it with `TRADING_MAX_SPREAD_RISK_FRACTION` and there is still only one
#: value to change.
MAX_SPREAD_RISK_FRACTION = 0.16


def too_expensive(spread: float, risk: float, limit: float = MAX_SPREAD_RISK_FRACTION) -> str:
    """"" if the round trip is affordable against the stop, else why it is not.

    A reason string rather than a bool, because every caller records one and
    three callers writing the same sentence is three sentences that drift.

    Zero or negative on either input is affordable, not refused. A missing
    quote and a stop at the entry are both real conditions and both have their
    own gates upstream - `Desk._undealable` for the first and the volatility
    check for the second - so refusing them here would attribute a trade to the
    wrong reason in the tally, which is the whole value of a per-gate count.
    """
    if limit <= 0.0 or spread <= 0.0 or risk <= 0.0:
        return ""
    share = spread / risk
    if share <= limit:
        return ""
    return f"the round trip is {share:.0%} of the risk, limit is {limit:.0%}"
