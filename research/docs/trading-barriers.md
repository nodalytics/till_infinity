# Trading Barriers

Rationale moved out of `till_infinity/trading/barriers.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `shift_for`

    `SHIFT` is 0.5826 of one *monitoring interval's* sigma. Watching `n` times a
    bar makes each interval `1/n` of a bar, whose sigma is `1/sqrt(n)` of the
    bar's, so the shift in bar units falls by the same factor. At thirty ticks a
    bar that is 0.1064.

    One tick a bar returns `SHIFT` unchanged, which is the close-monitored case
    and the one `research/deriving.md` published.


## `duration`

    `(a+B)(b+B)`, the discretely monitored form. The continuous `a*b` understates
    it by 12% at ten sigmas and by **178%** at one, because a near barrier is the
    case the correction exists for.

    This is the number a hold timeout should be set from and is not. `spending.md`
    found the clock firing on 50 of 133 real-market trades at **5% of their
    planned target** - a timeout shorter than the geometry needs converts a trade
    that had not finished into one that is scored as if it had.


## `duration_on_feed`

    `duration` is the driftless-Brownian answer and is exact where that holds -
    on the six Volatility indices every interval covers zero. A real feed is not
    driftless Brownian, and `research/grounding.md` measured the gap on 19 of 19
    feeds: **25% longer at 3:3 and 96% longer at 10:10**. See `SLOWER_ON_FEED`.

    Use this wherever a real instrument's clock is being set - a hold timeout, a
    stale-exit horizon, `hold_covers` - and `duration` wherever the process is
    known to be Brownian or the question is what the theory says. The difference
    between them is the thing that was being got wrong, so calling the right one
    is the whole point of having two.

    Measured, not derived. Five points, an interpolation and a mechanism, on a
    table that stops at 112 bars.


## `overshoot_cost`

    **The whole of it, and it is `P * B`.**

    On a driftless process the barrier odds are exactly fair *once the overshoot
    is counted on both sides*: `P*(a+B) = (1-P)*(b+B)` is an identity, not an
    approximation, and `probability` is that identity rearranged. A trade placed
    the way this desk places one does not collect both sides. A target is a limit
    order and a limit fills **at its price** - there is no overshoot to collect.
    A stop is a stop order and fills **past** its price; that overshoot is
    slippage and it is paid in full.

    So the asymmetry is the foregone overshoot on the wins, `P * B`, and nothing
    else. Two consequences that are not obvious:

    * it is **worse for near targets**, because they win more often and so give
      up the overshoot more often - 0.069R at 0.5:1 against 0.016R at 6:1;
    * it is a **cost of the geometry alone**, present before any spread, any
      commission and any directional call.

    This is the number that was missing. `research/spending.md` found the book
    1.7 points off break-even at the payoff it plans; a geometry quietly paying
    0.03R to 0.07R before the signal is consulted is the size of thing that gap
    is made of.


## `expectancy`

    Negative everywhere and **necessarily so**: `research/deriving.md` proves a
    predictable position on a martingale has expectancy `-(c/2) * turnover` for
    every stop, target, trail and filter, so a function that returned a positive
    number here would be reporting an arithmetic error. Reproducing the theorem
    is the check, not the discovery.

    Which is exactly what makes it useful for **ranking**. The desk's edge is
    supposed to come from the directional call; this says what the geometry
    costs before that call is applied, and the costs are not equal. A geometry
    paying 0.016R needs a far smaller directional edge to clear than one paying
    0.069R, and nothing told the desk which was which - `min_reward_to_risk`
    sees only the ratio and `min_probability` sees only the direction.

    `cost_units` is the spread in the same volatility units, charged once for the
    entry crossing; the exit rests on a barrier that is already placed.


## `ticks_from_slippage`

    `excess` is how far past 1R a stop comes back, as a fraction - 0.027 for the
    -102.7% `research/spending.md` measured across 42 real-market stops. That
    excess **is** the overshoot, so `B = excess * stop_units` and the rate
    follows from `B = SHIFT / sqrt(n)`.

    Worth having because it is measured from this desk's own fills rather than
    assumed, and because it says the assumption is wrong in a specific
    direction: 2.7% on a stop of about 1.3 volatility units implies roughly
    **280 ticks a bar**, not thirty. Real liquid feeds are watched far more
    finely than the two-second synthetics, so the correction on them is smaller
    than `DEFAULT_TICKS_PER_BAR` gives - which is the conservative direction for
    a cost estimate but the wrong one for a probability.

    Returns 0.0 when the excess is non-positive, which is not a reading: a stop
    that comes back better than 1R is a measurement to distrust before it is a
    monitoring rate to believe.


