# Trading Strategies Strategy

Rationale moved out of `till_infinity/trading/strategies/strategy.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Strategy.horizon`

        The same square root of time the stop floor uses, and for the same
        reason: `vol_bps` and every threshold denominated in it describe **one
        bar**, while the trade is held for many. A number that is right for one
        bar is wrong for thirty by a factor of about 5.5.

        Three settings inherited that mistake and are corrected by this.

        * **the trail**, in volatility units of one bar - a session's pullback
          against a minute's.
        * **the momentum filter**, likewise: 1.5v is a real run on a 3m chart
          and ordinary noise on a 4h one.

        Each was previously a constant per strategy, which meant every new
        strategy had to rediscover the arithmetic and `high-timeframe` carried
        hand-picked doubles of the scalpers' numbers. This derives them.

        **Break-even is deliberately not one of them**, and that was a mistake
        caught by reading the numbers before shipping them. Break-even is in R,
        and R is already measured against the stop, which this same reasoning
        has already widened. Scaling it again counts the horizon twice and puts
        `level-scalp` on a 5.5R break-even, which is a threshold that never
        fires - protection removed by an excess of it.

        Capped at `max_stop_scale`, like the stop floor, because the square
        root of thirty bars is 5.5 and a trail five and a half times its
        stated width is not the same rule any more.

        Returns 1.0 when the hold is not knowable, which restores the constants
        rather than guessing at a scale for them.


## `Strategy.protection`

        A strategy's own values win where it states them, and the trail is then
        stretched by `horizon` so the same declared intent means the same thing
        on a two-minute hold and a two-day one.

        **And then capped against the push, which the first version was not.**
        Scaling 2v by the horizon gives 6v, while the measured push
        distribution has a median of 2.24v and a p90 of 4.93v - so the trail
        sat further from price than the entire move on nine trades in ten,
        could never beat the stop already in place, and was never applied.
        Generalising the horizon idea removed the protection it was meant to
        improve, and silently, which is the worst way for a rule to fail.

        There is a floor downstream: `manage.advance` widens the trail to clear
        the level's own wick spread, so a tight cap here cannot produce a trail
        inside the noise. Between them the trail is bracketed rather than
        merely scaled.

        Break-even is deliberately unscaled - it is in R, and R is measured
        against a stop this same reasoning has already widened, so scaling it
        again counts the horizon twice.


## `Strategy.risk_scale`

        Beside `trend_scale` and `momentum_scale`, which already multiply into
        the risk fraction - these are four more reasons to be smaller and they
        compose the same way. See `scaling.py` for what each measures.

        Each is off unless its setting is set, and **none can enlarge a
        position**. A sizing model that can size up is one that can turn a
        measurement error into a margin call, and every input here rests on a
        few hundred observations.


## `Strategy.resting_price`

        Almost every strategy takes what is on offer: the call is about a level
        and the fill is wherever price happens to be. A strategy whose thesis
        is about *a particular price* - a broken structure being retested, say -
        is not the same trade at a different one, and says so here rather than
        hoping the fill lands nearby.

        The desk already knows how to wait: `_park` turns this into a resting
        order held on this side, re-asking the strategy when price arrives so
        every gate is re-run against the tick that actually fills it.


## `Strategy.observe`

        Called for every matching signal before any of them is considered, and
        called on every strategy rather than only the one that ends up acting.
        A strategy that accumulated state only from the signals it was asked
        about would be learning from a sample it had already filtered - the
        rolling-quantile gate would measure the distribution of what it already
        accepts, and the level book would only know about levels that produced
        a trade.


