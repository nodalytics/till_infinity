"""What a stop-and-target geometry is actually worth, before anything is traded.

Every position this desk opens is a bet between two barriers: a stop below and a
target above, or the mirror. The question "how often does this geometry reach
its target first" has a closed form, and **nothing in this package computed it**
until this module. The desk gated on `min_probability`, which is the kNN's
*directional* call - P(price goes up) - and on `min_reward_to_risk`, which is
geometry with no probability attached at all. Between them they never asked the
one question that decides whether a trade is worth taking:

    P(target before stop | the stop and target I just chose)

`research/spending.md` measured the consequence. Across 133 real-market closes
the entries are **1.7 points** off break-even at the payoff they plan, and the
geometry around them gives away half of it: wins come in at 54% of their risk
where losses come in at 78%, and **50 of 133 trades exit on the clock at 5% of
their planned target**. That is not a signal problem. It is a book placing
barriers without knowing what they are worth.

## The forms, and the constant that is most of the answer

For driftless Brownian motion with barriers `a` above and `b` below, measured in
the standard deviation of one observation interval:

    P(up first) = (b + B) / (a + b + 2B)
    E[time]     = (a + B) * (b + B)   intervals

where `B = -zeta(1/2)/sqrt(2*pi) = 0.5826` is the Broadie-Glasserman-Kou
continuity correction - the limiting expected overshoot of a Gaussian random
walk past a level. The textbook forms are these with `B = 0`, and at the
distances this desk trades the correction is not a refinement but most of the
answer: a 3:1 geometry is a 25.0% shot continuously and **30.7%** when monitored
on one-minute closes.

## Monitoring frequency, which is the part that was got wrong

`B` is `0.5826` **of one monitoring interval's sigma**, so it shrinks as the
price is watched more finely: the shift scales as `sigma * sqrt(dt)`, and at
`n` ticks a bar it falls by `sqrt(n)`.

**A real stop is hit on a tick, not on a close.** `research/deriving.md` section
one walks non-overlapping windows on one-minute closes, so its whole published
table - including the 30.7% - is the *close-monitored* answer, and the desk does
not trade on closes. At thirty ticks a bar the shift falls from 0.5826 to
**0.1064** of a one-minute sigma, and the 3:1 geometry becomes:

| monitoring | P(target first) |
| --- | --- |
| continuous | 0.2500 |
| one-minute closes | 0.3064 |
| **ticks, 30 a bar** | **0.2626** |

Measured on the tick table over about 2,100 and 2,600 non-overlapping trades,
the feed agrees with the tick-monitored prediction to within **0.61 standard
errors** on all six pooled cells and disagrees with the published close-monitored
figure by up to **5.7**. So the number the desk should size on is four points
below the one the research page gives - a seventh of the hit rate.

## Where this is validated and where it is a prior

**Derived and confirmed on the Volatility indices**, which `research/generators.md`
and `research/twins.md` establish as geometric Brownian motion with a published
sigma, H = 0.50 and kurtosis 3.00. There the assumption is not an assumption.

**On real markets it is a better prior than the continuous form and was not
validated when this module was written.** It has been since - see below - and the
prior was right about its own limits.

## Measured, 2026-09-12, four arms on 19 feeds out of sample

`research/grounding.md` tested the law against the closed form, an exact
propagation of the same Gaussian law, the feed's own return histogram, and a
learned volatility-regime operator. Then again at **tick** resolution on
`feed.py`'s millisecond stamps, which is the scale this module's headline
correction is actually about and which a bar replay cannot reach.

* **Where the assumption holds, the law is exact.** On the six Volatility
  indices every interval covers zero; on Volatility 75 and Step Index at tick
  resolution every `z` is under 0.5 and durations land at **0.99 to 1.08**.
* **Where it does not, it fails loudly and correctly.** Boom 500 is off by
  **-32 standard errors** at tick resolution and 55 on bars. That is a compound
  Poisson refusing to be a diffusion, which is the right answer.
* **On real feeds the probability is nearly right and the duration is not.**
  A 3:1 target measures **0.3147** against the form's 0.3064 - understating by
  **0.83 points, [0.52, 1.13]** - and it is mirror-antisymmetric, so symmetric
  geometries are unbiased. Trades resolve **1.18x to 1.49x slower** than
  `duration` says.

**The mechanism is measured and its sign flips**, which is what makes it a cause
rather than a correlation: real feeds carry tick autocorrelation of **-0.28 to
-0.05** where the synthetics carry -0.001, the variance ratio explains **29% to
59%** of the duration excess, and BTCUSD - the one feed with *positive*
autocorrelation - is the one feed that resolves **faster** than the law.

So on a real feed, read `duration` as a floor: mean reversion at tick scale makes
a barrier take longer to reach than a driftless walk would. That matters most for
`hold_covers`, which compares the clock against exactly this number - a geometry
reading 87% covered is closer to 60% once the excess is applied.

Treat a figure from here on a real feed as a sharp prior journalled against
outcomes, which is why `expectancy` is published on the intent rather than wired
into a refusal. The journal is what turned the paragraph above from a caveat into
a measurement.
"""

from __future__ import annotations

import math
import re
from itertools import pairwise

#: The Broadie-Glasserman-Kou continuity correction, `-zeta(1/2)/sqrt(2*pi)`.
#: Also the limiting expected overshoot of a Gaussian random walk past a level,
#: which is the reading that makes it a property of discrete monitoring rather
#: than a fitted constant.
SHIFT = 0.5826

#: Ticks per bar to assume when the real rate is not known. Thirty is the
#: two-second synthetic family's published rate and the figure every number in
#: the module docstring was measured at. It is deliberately **not** 1: assuming
#: close monitoring overstates a 3:1 geometry by four points, which is the error
#: this module exists to remove.
DEFAULT_TICKS_PER_BAR = 30.0

#: Below this many volatility units a barrier is inside the noise the estimate
#: itself carries, and the forms return a number with more confidence than the
#: inputs deserve. Reported rather than refused - see `reachable`.
MIN_UNITS = 0.10


def shift_for(ticks_per_bar: float = DEFAULT_TICKS_PER_BAR) -> float:
    """`B` in units of one **bar's** sigma, for a price watched `n` times a bar.

    `SHIFT` is 0.5826 of one *monitoring interval's* sigma. Watching `n` times a
    bar makes each interval `1/n` of a bar, whose sigma is `1/sqrt(n)` of the
    bar's, so the shift in bar units falls by the same factor. At thirty ticks a
    bar that is 0.1064.

    One tick a bar returns `SHIFT` unchanged, which is the close-monitored case
    and the one `research/deriving.md` published.
    """
    rate = max(1.0, float(ticks_per_bar))
    return SHIFT / math.sqrt(rate)


def probability(
    target_units: float,
    stop_units: float,
    *,
    ticks_per_bar: float = DEFAULT_TICKS_PER_BAR,
) -> float:
    """P(target before stop), both distances in volatility units of one bar.

    The symmetric case is the sanity check: equal barriers give 0.5 whatever the
    shift, because the correction pushes both walls out by the same amount.
    """
    up, down = abs(float(target_units)), abs(float(stop_units))
    shift = shift_for(ticks_per_bar)
    span = up + down + 2.0 * shift
    if span <= 0:
        return 0.5
    return (down + shift) / span


def duration(
    target_units: float,
    stop_units: float,
    *,
    ticks_per_bar: float = DEFAULT_TICKS_PER_BAR,
) -> float:
    """Expected bars until one barrier or the other is touched.

    `(a+B)(b+B)`, the discretely monitored form. The continuous `a*b` understates
    it by 12% at ten sigmas and by **178%** at one, because a near barrier is the
    case the correction exists for.

    This is the number a hold timeout should be set from and is not. `spending.md`
    found the clock firing on 50 of 133 real-market trades at **5% of their
    planned target** - a timeout shorter than the geometry needs converts a trade
    that had not finished into one that is scored as if it had.
    """
    up, down = abs(float(target_units)), abs(float(stop_units))
    shift = shift_for(ticks_per_bar)
    return (up + shift) * (down + shift)


#: How much longer a real trade takes than `duration` says, measured as
#: `(predicted bars, multiple)` on 19 real feeds by `research/grounding.md`.
#:
#: **Not an approximation error, and the control is what proves it.** The same
#: table on feeds `research/deriving.md` proves Brownian reads 1.111, 1.047,
#: 1.047, 1.053, 1.091 - **flat in geometry**, which is what the closed form's
#: own known error looks like. The real-feed column is not flat: it grows
#: monotonically and reaches **1.958 at ten sigmas, on 19 feeds out of 19**.
#:
#: The mechanism is mean reversion in volatility, and it predicts the growth.
#: Barriers are fixed at entry in units of the *entry* volatility; a real feed's
#: volatility half-life is 30 to 79 bars; a geometry needing 112 bars is held at
#: a volatility that has had one and a half half-lives to revert. Expected
#: first-passage time is **convex in 1/sigma**, so periods where volatility falls
#: lengthen the trade by more than periods where it rises shorten it, and the
#: mean moves up. Longer geometries have more time to revert, which is exactly
#: the ordering measured.
#:
#: Keyed on **predicted bars** rather than on the geometry ratio, because the
#: mechanism is about how long the trade is held against the half-life - so it
#: generalises to the asymmetric geometries the table does not contain.
SLOWER_ON_FEED: tuple[tuple[float, float], ...] = (
    (2.505, 1.251),
    (6.672, 1.209),
    (12.839, 1.271),
    (31.166, 1.417),
    (111.991, 1.958),
)


#: Feeds the venue generates rather than quotes.
#:
#: The distinction decides which duration to use, and it is not cosmetic: the
#: Brownian form is *exact* on the generated side - every interval covers zero on
#: the six Volatility indices - and understates the real side by 25% to 96%. The
#: same names drive `research/spending.md`'s split of the book.
#:
#: A wider pattern than `structures/vol/stated.NAMED`, which matches only the
#: families that publish a volatility in their name. This one has to catch every
#: feed whose process is the venue's rather than a market's.
GENERATED = re.compile(r"^(volatility|jump|boom|crash|step|range_break)_", re.I)


def generated(feed: object) -> bool:
    """Whether this feed's process is the venue's own."""
    return bool(GENERATED.match(str(feed or "").strip().lower()))


def slowdown(bars: float) -> float:
    """The measured multiple for a geometry predicted to take `bars`.

    Log-linear between the measured points and **clamped at both ends**, because
    this is five points and an interpolation, not a law. Extrapolating a
    monotone empirical curve past 112 bars would invent a number; holding it at
    1.958 says "at least this much, and the table stops here".
    """
    want = max(float(bars), 1e-9)
    points = SLOWER_ON_FEED
    if want <= points[0][0]:
        return points[0][1]
    if want >= points[-1][0]:
        return points[-1][1]
    for (low, at_low), (high, at_high) in pairwise(points):
        if low <= want <= high:
            span = math.log(high) - math.log(low)
            share = (math.log(want) - math.log(low)) / span if span else 0.0
            return at_low + share * (at_high - at_low)
    return points[-1][1]


def duration_on_feed(
    target_units: float,
    stop_units: float,
    *,
    ticks_per_bar: float = DEFAULT_TICKS_PER_BAR,
) -> float:
    """Expected bars on a **real** feed, which is not what `duration` returns.

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
    """
    bars = duration(target_units, stop_units, ticks_per_bar=ticks_per_bar)
    return bars * slowdown(bars)


def overshoot_cost(
    target_units: float,
    stop_units: float,
    *,
    ticks_per_bar: float = DEFAULT_TICKS_PER_BAR,
) -> float:
    """What discrete monitoring costs this geometry, in units of planned risk.

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
    """
    up, down = abs(float(target_units)), abs(float(stop_units))
    if down <= 0:
        return 0.0
    hit = probability(up, down, ticks_per_bar=ticks_per_bar)
    return hit * shift_for(ticks_per_bar) / down


def expectancy(
    target_units: float,
    stop_units: float,
    *,
    ticks_per_bar: float = DEFAULT_TICKS_PER_BAR,
    cost_units: float = 0.0,
) -> float:
    """Expected return of the geometry alone, in units of its planned risk.

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
    """
    down = abs(float(stop_units))
    if down <= 0:
        return 0.0
    cost = abs(float(cost_units)) / down
    return -overshoot_cost(target_units, down, ticks_per_bar=ticks_per_bar) - cost


def ticks_from_slippage(excess: float, stop_units: float) -> float:
    """Infer the effective monitoring rate from what stops actually cost.

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
    """
    down = abs(float(stop_units))
    if excess <= 0 or down <= 0:
        return 0.0
    shift = float(excess) * down
    return (SHIFT / shift) ** 2 if shift > 0 else 0.0


def reachable(target_units: float, stop_units: float) -> bool:
    """Whether both barriers are far enough out for the forms to mean anything.

    Under `MIN_UNITS` the answer is dominated by the volatility estimate's own
    error rather than by the geometry, and a confident-looking number there is
    the failure this repository keeps cataloguing in `research/inert.md`.
    """
    return min(abs(float(target_units)), abs(float(stop_units))) >= MIN_UNITS


def units_for(distance: float, price: float, vol_bps: float) -> float:
    """A price distance as volatility units, or 0.0 when it cannot be formed.

    Every caller has a distance in price and a volatility in basis points, and
    doing this conversion at each call site is how one of them ends up dividing
    by the wrong thing.
    """
    if price <= 0 or vol_bps <= 0:
        return 0.0
    unit = price * vol_bps / 10_000.0
    return abs(float(distance)) / unit if unit > 0 else 0.0
