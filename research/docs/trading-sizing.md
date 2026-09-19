# Trading Sizing

Rationale moved out of `till_infinity/trading/sizing.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `stop_for`

    Beyond the *level*, not beyond the entry. The level is the thing being
    traded - the price at which this instrument has repeatedly turned - so the
    trade is wrong when price is through it, whatever the fill happened to be.
    Anchoring the stop to the fill instead would move the invalidation point
    every time the spread widened.

    **And beyond the zone, not beyond the origin.** A level is a range, not a
    line: the origin is where the leg in met the leg out, and the band extends
    by however far the wick ran past it on that side. A stop placed at
    `origin - distance` can therefore sit *inside* the band where wicks
    routinely reach, which is not a stop at all - it is a standing offer to be
    swept and then watch the trade work without you. `zone_edge` is that
    band's far edge and the stop is pushed outside it, plus `clearance` so it
    is not resting exactly where the last wick stopped.

    Being wrong and being swept look identical in the account and are not the
    same event. This is the difference.


## `lots`

    `slippage` is how much further than the placed stop a stopped trade
    actually costs, as a fraction of the stop distance. It inflates the
    distance sized against, so a stop that fills 9% past still loses the
    budgeted money rather than 9% more of it.

    Measured at 0.087 across the stopped trades in the journal, of which
    two-thirds is the exit rather than the entry: a broker stop is a market
    order once triggered and fills through the spread. Sizing against the stop
    we *place* rather than the one we *get* breaches the risk budget on every
    loss, quietly and by a constant.


