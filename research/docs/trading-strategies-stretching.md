# Trading Strategies Stretching

Rationale moved out of `till_infinity/trading/strategies/stretching.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `CycleTurnScalp`

    ## The shape

    **Entry on 1m to 15m**, stopped and targeted on the entry bar's own scale.
    No horizon stretching: this is a scalp, and a scalp that aims at a slower
    horizon is a position trade with a scalp's stop.

    **The 1h is the mother cycle.** Without its agreement there is no agreement
    at all - a 15m and a 30m agreeing with each other while the hour does not
    are two timeframes agreeing about something the cycle they sit inside has
    already turned away from. And it may not agree alone: one reading is not an
    agreement however senior, so at least one of the 15m and 30m has to agree
    with it. The call's own interval never counts, so a 15m entry is anchored
    on the 30m and the 1h.

    **A break has to have happened first**, pointing the same way, with price
    still near enough to the line for the line to be an entry. The order is the
    claim: structure fails, and *then* the reading stretches.

    **Licensed by the entry bar's own record**, because a scalp's horizon is
    the entry bar. See the module note.


## `CycleTurnScalp.conviction_scale`

        The agreement flag is the stricter reading of the same reading: the
        displacement is there *and* momentum has already started to unwind it.
        That is a better-supported version of this trade rather than a
        different one, so it sizes rather than gates.

        Shrinking only. `1.0` is the ceiling and `UNCONFIRMED_RISK` the floor,
        because a multiplier that enlarges would be a way past `max_risk_money`
        and every other cap downstream.


## `CycleTurnScalp._unconfirmed`

        Two different failures of different sizes: the mother missing is the
        whole agreement gone, and the mother alone is one reading rather than
        an agreement. The caller turns each into its own refusal, because a
        counter that merged them would not say which.

        The call's own interval is excluded throughout - a timeframe cannot
        confirm itself - so a 15m entry is anchored on the 30m and the 1h.


