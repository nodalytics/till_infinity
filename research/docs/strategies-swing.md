# Strategies Swing

Rationale moved out of `till_infinity/trading/strategies/swing.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `ApproachScalp`

    The setup, in the desk's words: a level below price is something to sell
    down to, a level above is something to buy up to, once something confirms
    the direction. The confirmation here is the ordinary level call - a
    measured, directional reading at the level price is standing on - and the
    target is the next level the book knows about in that direction.

    So the geometry is inverted from the other strategies. They enter at a
    level and take the expected push; this one enters *on* a call and exits at
    a level. The stop is unchanged, still anchored beyond the confirming level,
    because that is still what makes the read wrong.

    **What the repository already knows about this, stated up front.**
    [magnet.md](../../docs/magnet.md) tested whether levels pull price and
    found they do not: across 22,219 evaluation bars a level was reached within
    twenty bars 44.9% of the time against 49.5% for an arbitrary price the same
    distance away, and with the day held fixed the gap is nine-tenths of a
    point and indistinguishable from zero. So this strategy is **not** an
    attraction bet, and it is built so as not to become one by accident:

    * the target stops `approach_buffer_vol` **short** of the level, because
      the last quarter unit into the zone is exactly the part the measurement
      says nothing supports;
    * the distance is checked against `structures.timing`, the same
      first-passage model magnet.md used as its baseline, and refused when
      diffusion alone says the move is unlikely inside the hold. A level is
      therefore chosen as a target because it is a price the model has
      statistics at and a plausible place to be taken out, not because being a
      level makes it more likely to be reached.

    What is left after that is a rule for choosing a *target distance*, which
    the null does not touch, on an entry that is separately measured.

    **It is given longer to work.** The desk's observation is that this takes
    twenty to thirty minutes to deliver; the module's default hold is thirty,
    which would close a good trade at the moment it started paying. So this
    strategy asks for forty-five and that is why.


## `Runner`

    Every other strategy here closes at the push the level model predicted.
    That number is a *median* estimate of where price goes, and closing there
    keeps the half of the distribution below it while giving away the half
    above. Measured over 54,529 resolutions the tail is where the money is:

    | push reached | volatility units |
    | --- | ---: |
    | median | 2.24v |
    | p75 | 3.37v |
    | p90 | 4.93v |
    | p99 | 9.55v |

    Replayed against those resolutions at a 0.5v stop, letting the move run and
    exiting on a trail returned **+8.4R against +1.7R** for the same entries
    closed at a fixed target - roughly five times as much from identical calls,
    entirely in how they were exited.

    **`trail_vol` already half-does this and cannot finish the job.** The trail
    protects a runner once it is running, but the *target* still closes the
    trade at the modelled push, so on most trades the target is hit first and
    the trail never gets the chance to do anything. Raising the target is what
    lets the mechanism that already exists actually operate.

    So the target here sits at `target_multiple` times the modelled push rather
    than at it. It is deliberately not removed: `lots` and the reward-to-risk
    gate both need a target to exist, and a trade with no defined objective
    cannot be sized or refused. Placed near the ninetieth percentile of the
    push distribution, it stops being the thing that ends the trade in the
    ordinary case and becomes what `thesis-only` did for the stop - an outer
    bound rather than a decision.

    **What ends the trade instead** is the trail, tightened here because it now
    carries the exit rather than assisting it, and the clock. The risk this
    takes is the obvious one and it should be stated: a trail that has not been
    reached gives back everything between the peak and the stop, so this will
    show more round trips through profit than the fixed target does. That is
    the trade being made - a worse win rate for a longer right tail - and it is
    exactly what running it beside the others will measure.

    **One difference from `level-scalp`**, like `snap` and `thesis-only` before
    it: same entries, same anchors, same gates, same stop. Only the exit moves.


## `SwingLevel`

    Everything else here is a scalp. This is the same machinery pointed at a
    longer horizon, and it exists mainly to show that the entry/anchor split is
    a real structure rather than a scalping detail.

    **The anchor and the entry are not the same timeframe, and the gap is the
    point.** The bias comes from 4h, 1d and 1w - where a level has enough
    history to mean something and enough distance to be worth crossing. The
    *trigger* is allowed as low as 15m, because the entry is what fixes the
    stop, and a stop measured on 15m is a fraction of one measured on 1d for
    the identical idea. That is risk reduction, not a different trade: same
    thesis, smaller distance to being wrong, so the same money buys more of it.

    It requires its anchor. A 1h call with nothing above it agreeing is a fast
    trade wearing a swing's hold, which is the worst combination available -
    the patience of the one and the evidence of the other.

    Given six hours rather than the scalpers' thirty minutes, because a daily
    level's push is measured in sessions. The hold is the setting most likely
    to be wrong here and it has never been measured; `max_hold` closing a
    winner early would look exactly like the strategy not working.


## `SwingLevel.distances`

        Every other strategy here aims at a multiple of the modelled push,
        which is a distance the position sizer chose. This aims at the far
        bound of the level range - a price the market drew, where the next
        agreed level actually sits - because a swing that is going anywhere is
        going there, and a target short of it is leaving the move for someone
        else while a target past it is asking price through a level on the
        first attempt.

        The range is built on this call's timeframe or coarser
        (`structures/drawing/level_range.py`), so the bound is a 4h object for
        a 4h thesis rather than whichever 5m zone happened to be nearest.

        **It is a floor, not a replacement.** Three cases fall back to the push
        multiple, and all three are real:

        * no range - one side is open air, and there is no far bound to aim at.
        * a far bound *nearer* than the modelled push, which would cut a trade
          short at a level the model already expects it to pass.
        * anything that would put the target inside the stop, which is not a
          trade.

        The trail does the rest. `trail_vol` is 4.0 here, so a move that runs
        past the bound is not closed by this target - it is followed, and the
        target only ends the trade when price stops making new ground. That is
        the combination asked for: aim at the next level, and trail past it.


## `OriginSwing`

    An origin is where volatility turned - the last opposing bar before an
    impulse, kept as a zone rather than a price because the zone is what price
    reacts to. See `structures/origins.py`.

    **The trade is the space between two of them.** When price sits between an
    origin above and an origin below there are two places worth trading and one
    question: which does price reach first. It arrives, it is confirmed there,
    and the trade runs to the opposite origin. Long from the one below, short
    from the one above; the far edge is the target either way.

    That makes the target a **structure** rather than a multiple of the
    modelled push. `expected_push_vol` is a forecast about the next few bars,
    and over a swing horizon the honest answer to "how far does this go" is "to
    the next place that stopped it last time".

    **Two confirmations at the origin, and they are different questions.** The
    4h rejection candle says the auction failed there; the momentum ensemble
    below 1h says it is failing *now*. The candle is slower, stronger, and has
    to wait for a close; the accumulator reads the same event tick by tick.
    Both are required here rather than the disjunction the scalps use - a swing
    can afford to wait, and an origin price merely touched is not an origin
    that rejected it.

    **The stop sits beyond the rejection, by an amount the instrument sets.**
    Past the far edge of the origin zone plus a volatility buffer: inside the
    zone is where the wicks are, and a stop placed there is stopped by the very
    rejection it is trading.

    **What is claimed and what is not.** Origin *freshness* separates - never
    revisited returned 1.136R against 0.822R twice revisited. Origin
    *proximity* did not: it read +0.299 on the first live sample and -0.166
    over 49,619. So nothing here scores on distance. The bracket is used as
    geometry - where to enter, where to aim, where the stop clears - which is a
    placement decision this repository has not measured either way.


## `FadeToValue`

    The thesis in its plainest form. Every other strategy here reacts *at* a
    level: price arrives, the level's record says what usually happens, the
    trade is taken there. This one asks the question the README opens with -
    what is this worth, and where is it trading - and takes the difference.

    **Fair value is the best-evidenced level within reach**, not the nearest
    one. A price the instrument has turned at forty times is a claim about
    value; one it clipped twice is barely a claim at all, and taking the
    closest level regardless would make the estimate a function of where price
    happens to be standing. The book is scanned and the level with the most
    decisive history wins, provided it has enough to speak.

    **The stance is arithmetic.** Fair value above the market is a long, below
    it is a short. Nothing is forecast: the side falls out of the valuation,
    which is the property the whole design exists to protect.

    **The distance has to clear the noise before it is a mispricing.** Fair
    value is a distribution and volatility is its width, so a price one unit
    away is inside the estimate and says nothing. `fade_min_distance_vol` is
    where a distance starts being a statement.

    **And it stops short of the target**, for the reason `approach-scalp` does:
    price is not drawn to a level. The distance is an opportunity because the
    level is a place with statistics attached, not because anything pulls price
    to it, and the last stretch into the zone is exactly the part that was
    measured and did not survive.

    The stop goes beyond the level price is *at* - the one that triggered the
    signal - because that is where this reading of value is wrong. If price
    settles through the level it just arrived at, the estimate that said it was
    cheap here was the thing that failed.

## Inline notes

Passages that stood inside the functions named, moved out on 2026-09-19.
Each keeps its first sentence at the call site.

### `FadeToValue.consider`

running order, it was taking most of the trades through the only
ungated path in the system while the other three were refused by
floors it never saw.

The chase gate is deliberately *not* applied here and the difference
is real rather than an oversight: chasing means filling far from the
level the call was measured at, and this strategy's whole premise is
being far from fair value. That gate would refuse every trade it ever
wanted, by construction.

