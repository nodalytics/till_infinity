# Trading Strategies Scalper

Rationale moved out of `till_infinity/trading/strategies/scalper.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `LevelStrategy.momentum_scale`

        Full size when the accumulated run is with the trade, reduced when it
        is merely not against it. The two gates either side of this are
        yes-or-no - `max_against_vol` refuses a run still going the wrong way,
        `require_turn_vol` asks for the turn after a pullback - and between
        them sits a case neither covers: momentum flat or unreadable, which is
        weaker evidence than momentum turning and stronger than momentum
        opposing.

        Returns 1.0 when the setting is off, when there is no reading, or when
        momentum is with the trade. It can only reduce.


## `LevelStrategy.conviction_scale`

        `1.0` for every strategy that does not override it. A strategy with a
        stricter reading of its own signal - one that would have gated on it and
        chose to size on it instead - says so here.

        **It may only shrink.** Applied to `risk_fraction` beside the others, so
        every cap downstream still binds; a multiplier that enlarged would be a
        way past `max_risk_money` through a setting nobody reads as a risk
        setting. See `scaling.py` for the rule and `cycle-turn-scalp` for the
        one caller.


## `LevelStrategy.quality`

        Extracted because one of them was not clearing them. `FadeToValue`
        overrides `consider` entirely and therefore ran none of this - so the
        probability floor, the per-direction percentile, the edge floor and the
        base-rate floor applied to three strategies and not to the fourth. The
        exemption was invisible from the configuration, which read as though
        every gate protected every strategy, and the exempt one was first in
        the running order taking most of the trades.

        A shared method rather than a copied block, so the two paths cannot
        drift apart again.


## `LevelStrategy.distances`

        `features` and `side` are passed for the benefit of anything that aims
        at a price the market drew rather than at a multiple of the push -
        `SwingLevel` uses them to target the far side of the level range. Both
        optional, so every other strategy is unchanged.

        The stop is floored at `min_stop_vol`. A stop inside one volatility
        unit is inside the width of the estimate it is protecting, and is taken
        by ordinary movement rather than by the thesis failing - see
        `Settings.min_stop_vol` for the two live trades that made the case.


## `LevelStrategy._chasing`

        Entry is a market order, so it lands wherever price is when the call
        arrives, and nothing used to look at that. The call was measured *at*
        the level and the push it predicts runs from there, so a fill well past
        it has already spent part of the move - and the stop, being anchored to
        the level, ends up sitting close underneath the fill. Both halves of
        "stopped out before the move came" meet at this number.

        Only counted when the fill is past the level in the trade's own
        direction. Arriving before it is the setup behaving as advertised.


## `LevelStrategy._floored_stop`

        Applied only after the `through` check has passed, and the order is not
        a detail. A fill already on the far side of the level-anchored stop is
        an invalidated trade, not a trade to re-stop; running this first would
        quietly rebase the stop below such a fill and turn a refusal into a
        position. An existing test says so, and caught exactly that.

        Past that point this can only push the stop further from the fill,
        which only ever reduces size for the same money at risk.


