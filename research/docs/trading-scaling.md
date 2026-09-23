# Trading Scaling

Rationale moved out of `till_infinity/trading/scaling.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `crowding`

    `open_trades` is `(feed, side sign)` per open position - taken as feeds
    rather than `Position` objects because a `Position` is slotted and carries
    the broker's symbol, not the feed name. Asking the caller for the pair it
    already knows is cheaper than reverse-mapping a symbol here, and it makes
    the direction explicit rather than inferred.

    `share` is how much of the size a *fully* crowded leg keeps. At 0.5 the
    second position on a leg is halved, the third quartered.

    Geometric rather than linear, because the risk of a shared leg compounds:
    three positions all short the dollar are not three-halves of one trade,
    they are closer to three of it. Linear reduction would still leave the book
    net long the same idea by a wide margin.

    Counts **legs**, not instruments. Long EURUSD and short GBPUSD share the
    dollar and point opposite ways on it, which is not crowding - so the sign
    of the position matters and a hedge is not penalised.


## `by_volatility`

    `target_bps` is the volatility this book is sized for. Above it the trade
    is scaled by the ratio, so a doubling of volatility halves the position.

    **Only ever reduces.** A quiet instrument does *not* get a larger position:
    the ratio is capped at one. Sizing up into calm is how a book discovers
    that calm was the beginning of something, and the stop already widens with
    volatility so the money at risk is constant either way. What this adds is a
    cap on how much of the *portfolio* one violent instrument can represent.


## `by_regime`

    `ratio` is `forecast_ratio` off the call, and it is **not** a reading of
    the regime level. It is `har.ratio`: the next-bar forecast over the last
    realised value - *where volatility is going*, not where it is. One means
    the next bar is expected to look like the last one, whatever size that was.

    The distinction is load-bearing and was got wrong here for a while. The
    reading of *where we are* is `vol_stretch` (`garch.stretch`, current scale
    over its own long-run level), it is published on the same call, and it
    predicts **nothing**: 84.6 / 83.4 / 83.6 / 83.4 / 84.0 across its quintiles
    over 32,362 touches, flat to within 1.2 points. The two are near
    independent - log correlation **+0.033** - so they are separate questions
    and only one has an answer.

    **The shape is an inverted U and that is the whole point.** Measured over
    32,362 decisive touches on 14 days, a level held **86.4%** of the time with
    the ratio between 1.0 and 1.21, and **81.3%** below 0.75 and **81.4%**
    above 2.06 - worse at *both* ends, by about five points. Levels hold when
    the scale is about to stay put and break when it is about to change, in
    either direction: a fivefold expansion runs a level over, and a collapse in
    scale is what a level was holding price against being released.

    An earlier 7-day read of this gave 85.7% against 78.9 / 78.8 - the same
    shape, a wider spread. The peak is stable and the tails have come in, which
    is the direction a period effect usually moves when the period lengthens.

    Nothing linear can express that, which is why this is a distance from one
    rather than a multiple of it - `by_volatility` above is the multiple, and
    it is a different statement about a different quantity.

    `width` is how far from one the ratio may drift before size starts falling,
    in log space so that half and double are equally far away. Zero is off.
    `floor` bounds the reduction: the reading is worth seven points of held
    rate, not a veto, and a scaler that can go to zero is a gate wearing a
    multiplier's clothes.

    **Only ever reduces**, like everything else here. The middle of the band
    gets full size; it never gets more than full.


## `by_spike`

    `percentile` is `tr_percentile` off the call: where the 14-bar true-range
    average (`ewma_tr_bps`, the figure `by_volatility` sizes on) sits within this
    instrument's own last 1,500 bars. `above` is `TRADING_SPIKE_ABOVE` and
    `floor` is `TRADING_SPIKE_FLOOR`.

    **A different question from `by_volatility` and `by_regime`.** Those size by
    how big volatility is and where it is heading. This one asks how likely a
    *large bar* is inside the hold, because that is what takes a stop out past its
    level and what makes up the tail of a position's outcomes. Measured in
    `research/docs/crash-timing.md` on 14 real instruments at 15m and 1h and 9 at
    1d: in the top fifth of this percentile a bar beyond 4x the trailing mean
    |return| is **2.2-2.5 times as likely** (22.0% against 10.1% at 15m, 19.3%
    against 7.9% at 1h, 12.6% against 5.6% on daily). Halving size there, on two
    positions that knew nothing about the reading:

    | | 1% tail flat -> switched | worst | return per unit of risk |
    | --- | --- | --- | --- |
    | 15m long | -4.05 -> -3.47 | -38.3 -> -19.2 | 0.020 -> 0.023 |
    | 1h long | -4.20 -> -3.77 | -28.3 -> **-14.1** | 0.011 -> 0.012 |
    | 1d long | -3.69 -> -3.21 | -11.0 -> -11.0 | 0.050 -> 0.047 |

    A gradient-boosted big-move model does somewhat better at 15m (-2.96) and has
    to be fit and kept fit; this is a percentile of a number already published,
    with nothing to train. The 60-bar version of the same percentile (`regime`)
    managed 4-9% on the tail and never moved the worst outcome, which is why this
    reads the 14-bar average.

    **It cannot be a signal.** The same state predicts melt-ups as well as crashes
    - a crash model built on it scored AUC 0.78 on melt-ups against 0.81 on
    crashes at 15m - and shorting it lost on daily bars. So it sizes down and
    never picks a side.

    **Every sizing path reads it.** `risk_scale` covers the level strategies;
    FadeToValue and Council, which size without `risk_scale`, apply it directly;
    and the trader's own re-sizing in the consensus path, in parallel mode and
    onto follower accounts - all of which size at the flat fraction and discard
    every other multiplier - apply it too, through one function
    (`strategy.spike_scale`) so the paths cannot disagree. It is about the
    instrument's state, not a strategy's view, and it would be inert in exactly
    the modes that take the most trades if it lived only in `risk_scale`.

    Off at 0; 0.8 is the measured setting. Before 20 bars of history the
    percentile reads 0.5, which no sensible threshold treats as high.


## `by_edge`

    `edge_vol` is the instrument's net edge per touch in volatility units, from
    research/paying.md - accuracy times expected push, less the cost to cross.
    `full_at` is the edge that earns full size.

    **Fractional and capped, not Kelly.** Full Kelly on an edge estimated from
    fifty touches is a way to be wiped out by an estimation error rather than by
    a market. This is linear in the edge up to a cap, which is the conservative
    end of the same family.

    A negative or absent edge returns the floor rather than zero, because a
    refusal is `paying.md`'s job and not a sizing model's - and an instrument
    with no measurement is not an instrument with a measured loss.


## `by_drawdown`

    `halt_at` is the drawdown fraction at which size reaches the floor - a
    smooth approach to the daily loss halt rather than trading full size until
    it fires.

    Square-root rather than linear, so the first losses barely register and the
    reduction bites as the drawdown deepens. A book that taper hard on a 2%
    dip cannot recover, because it is trading a quarter size exactly when the
    edge it was sized for is still there.


## `by_interval`

    The book's own record, 2026-09-03, per closed trade:

    | interval | closes | per close | t |
    | --- | ---: | ---: | ---: |
    | 1m | 47 | -7.75 | -2.29 |
    | 3m | 34 | -4.80 | -1.53 |
    | 5m | 48 | -6.13 | -2.55 |
    | 15m | 15 | -2.46 | -0.49 |
    | 30m | 2 | +3.71 | |
    | 1h | 3 | +18.67 | +1.83 |

    Sub-15m is **-821.75 over 129 closes**; 15m and above is **+35.03 over
    21**. The ordering is monotone and the three fastest are each individually
    negative, two of them past two standard errors.

    **Sizing is only half of what this timeframe problem needs, and the smaller
    half.** 1m and 3m signals also produced 547 of the book's 1,270 capacity
    refusals - `max_positions`, `already_open`, `waiting` - so the fast trades
    are not merely losing money, they are occupying the slots a slow signal
    needs when it finally arrives. A gold 4h level appeared *once* in 48 hours
    against ninety-six 1m calls, and was refused for want of room. Making the
    fast trade smaller does not give that slot back; only not taking it does.
    See research/timeframes.md.

    So this is the reversible half, shipped first because it cannot stop the
    desk trading. Unlisted intervals size at full.


## `by_slippage`

    `overshoot` is what a stop on this instrument actually costs, in R, where
    it was placed at 1R. A book that sizes every trade to risk one unit and
    then loses 1.25 on that instrument is risking a quarter more than it
    authorised, and no other model here notices: `by_volatility` reads the
    instrument's volatility, which is the *planned* stop distance, and the plan
    is not what went wrong.

    So the correction is the reciprocal - 1.25 realised means 0.8 size, and the
    trade risks what it said it would. Measured 2026-09-02 on till_infinity:
    Boom 500 Index stops came back at a median -1.25R and a worst -1.79R, 60%
    of them past 1.1R, where every other instrument on the book delivered
    between -1.00R and -1.09R with none past 1.1R. Five stops, so the number is
    thin - which the reciprocal handles gracefully, since a wrong estimate near
    1.0 barely moves the size.

    **Revised 2026-09-11, and the old number was thin by its own admission.**
    The 1.25 above rests on five stops. A mechanical replay over 84,701 ticks
    puts the *spike side* of Boom and Crash at **+9.9R to +19.1R**, with 93-98%
    of stopped trades past 0.5R, against +0.02R on the grind side and +0.061R on
    a symmetric control. Widening narrows it and never closes it: boom_500 still
    overshoots 1.02R at a fifty-spread stop.

    So sizing off stop distance understates tail risk by **15x at five spreads
    and 2x at fifty** on those sides - which is the shape that ends an account
    rather than the shape that costs it a quarter. See
    `research/generators.md`, and `overshoot_for` for why this is keyed by side.

    Never enlarges. An instrument whose stops come back *better* than 1R is not
    a reason to trade it bigger; it is a reason to distrust the measurement.


