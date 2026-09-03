"""Four ways to size a trade by something other than a fixed fraction.

`lots()` risks a constant share of equity per trade. That is the right default
and it is blind to four things this book measurably has:

* **shared legs.** `exposure.py` decomposes a pair into its currencies, so long
  EURUSD, GBPUSD and AUDUSD is *one* dollar trade in three tickets. The
  currency cap refuses the fourth. Nothing sizes the second and third **down**,
  and capping a leg is a different thing from sizing for it.
* **volatility.** Constant money at risk is not constant risk when an
  instrument's own volatility doubles. The stop widens with volatility, so lots
  fall - but the *portfolio's* exposure to a violent regime does not.
* **measured edge.** research/paying.md gives a net edge per instrument in
  volatility units: gold +0.919v against usdcnh -4.663v. They currently carry
  the same risk fraction.
* **drawdown.** There is a daily loss halt, which is a cliff. A book that has
  given back a third of its month should be trading smaller *before* it hits
  the halt, not the same size until it does.

Each returns a **multiplier in [0, 1]**, and they compose by multiplication.
Every one can only reduce, which is deliberate: a sizing model that can enlarge
a position is a sizing model that can turn a measurement error into a margin
call, and every input here is measured on a few hundred observations.

## They decide nothing until they are turned on

All four are off by default and each has its own setting. That is not caution
for its own sake - the account is -688 over 128 trades and research/horizon.md
finds no demonstrated directional edge at the horizon the desk trades, so
better sizing of a signal with no edge scales the loss rather than fixing it.
These are built so they are ready when that question resolves, and so the
arithmetic is written down where it can be argued with.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from . import exposure as ex

#: Below this a multiplier is not worth applying - the broker's volume step
#: will round it away, and a position sized to nothing is a refusal wearing a
#: number. Callers should refuse instead.
FLOOR = 0.05


def crowding(feed: str, open_trades: Sequence[tuple[str, int]], share: float) -> float:
    """Reduce for every open position that shares a currency leg.

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
    """
    if share <= 0 or share >= 1:
        return 1.0
    base, quote = ex.legs(feed)
    if not base and not quote:
        return 1.0

    crowded = 0
    for other_feed, sign in open_trades:
        other_base, other_quote = ex.legs(other_feed)
        if not other_base and not other_quote:
            continue
        # A shared leg only crowds when both positions are the same way round
        # on it. `Side.sign` is +1 for a buy, so a long of the base is long
        # that currency and short the quote.
        for leg, mine in ((base, 1), (quote, -1)):
            if not leg:
                continue
            theirs = 0
            if leg == other_base:
                theirs = sign
            elif leg == other_quote:
                theirs = -sign
            if theirs and (mine > 0) == (theirs > 0):
                crowded += 1
                break
    return share**crowded if crowded else 1.0


def by_volatility(vol_bps: float, target_bps: float) -> float:
    """Reduce when the instrument is more volatile than the target.

    `target_bps` is the volatility this book is sized for. Above it the trade
    is scaled by the ratio, so a doubling of volatility halves the position.

    **Only ever reduces.** A quiet instrument does *not* get a larger position:
    the ratio is capped at one. Sizing up into calm is how a book discovers
    that calm was the beginning of something, and the stop already widens with
    volatility so the money at risk is constant either way. What this adds is a
    cap on how much of the *portfolio* one violent instrument can represent.
    """
    if target_bps <= 0 or vol_bps <= 0:
        return 1.0
    return min(1.0, target_bps / vol_bps)


def by_edge(edge_vol: float | None, full_at: float) -> float:
    """Scale by measured net edge, fractionally.

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
    """
    if full_at <= 0:
        return 1.0
    if edge_vol is None:
        return 1.0
    if edge_vol <= 0:
        return FLOOR
    return max(FLOOR, min(1.0, edge_vol / full_at))


def by_drawdown(peak: float, equity: float, halt_at: float) -> float:
    """Taper as the book gives back its high-water mark.

    `halt_at` is the drawdown fraction at which size reaches the floor - a
    smooth approach to the daily loss halt rather than trading full size until
    it fires.

    Square-root rather than linear, so the first losses barely register and the
    reduction bites as the drawdown deepens. A book that taper hard on a 2%
    dip cannot recover, because it is trading a quarter size exactly when the
    edge it was sized for is still there.
    """
    if halt_at <= 0 or peak <= 0 or equity >= peak:
        return 1.0
    fallen = (peak - equity) / peak
    if fallen >= halt_at:
        return FLOOR
    return max(FLOOR, math.sqrt(1.0 - fallen / halt_at))


def by_interval(interval: str, weights: Sequence[tuple[str, float]]) -> float:
    """Size by the timeframe the signal was triggered on.

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
    """
    if not weights:
        return 1.0
    want = (interval or "").strip().lower()
    for name, weight in weights:
        if name == want:
            return max(FLOOR, min(1.0, weight))
    return 1.0


def by_slippage(overshoot: float) -> float:
    """Give back the size an instrument's stops overshoot by.

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

    Never enlarges. An instrument whose stops come back *better* than 1R is not
    a reason to trade it bigger; it is a reason to distrust the measurement.
    """
    if overshoot <= 1.0:
        return 1.0
    return max(FLOOR, 1.0 / overshoot)


def combined(*multipliers: float) -> float:
    """Every reduction at once, bounded to [FLOOR, 1].

    Multiplicative because each is an independent reason to be smaller, and
    because it makes the order they are applied in irrelevant - which matters
    when four of them can fire on one trade and no reader should have to know
    which ran first.
    """
    total = 1.0
    for value in multipliers:
        total *= max(0.0, min(1.0, value))
    return max(FLOOR, min(1.0, total))
