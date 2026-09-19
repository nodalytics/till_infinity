# Trading Strategies Swing

Rationale moved out of `till_infinity/trading/strategies/swing.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `SwingLevel.at_the_right_place`

        The design in one condition. A range trade is a bet that a wall holds,
        so there has to *be* a wall: buying belongs at the floor and selling at
        the ceiling, and anywhere in between is a directional trade wearing a
        range trade's stop.

        Silent when there is no 4h range - one side open air, or an older
        signal that carries no `swing_*` readings at all. A missing structure
        is not evidence against the trade, and refusing on it would make this
        strategy quietly dependent on a feature that is often absent.


## `OriginSwing._anchored_stop`

        The level is not what this trade is about. Anchoring there put the stop
        on the wrong side of the fill outright - a long entered at the lower
        origin, 2v under the level, got a stop *above* its own entry and was
        refused as already through.

        The far edge of the zone plus a volatility unit of clearance. Inside
        the zone is where the wicks are, and a stop placed there is taken out
        by the rejection the trade exists to trade.


