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
from collections.abc import Mapping, Sequence

from till_infinity.utils import effects

from . import exposure as ex

#: **Halving into a likely large bar.** Declared off here and re-declared by the
#: trader with the configured flag, so an enabled switch that never reduces a
#: trade is reported rather than assumed to be working.
effects.declare("trading.spike_switch", enabled=False)

#: Below this a multiplier is not worth applying - the broker's volume step
#: will round it away, and a position sized to nothing is a refusal wearing a
#: number. Callers should refuse instead.
FLOOR = 0.05


def _sign_of(side: object) -> int:
    """+1 for a buy, -1 for a sell, +1 when nothing says.

    Reads `Side.sign` where it exists and falls back to the word, because the
    callers hand this a `Side`, a string and sometimes an int - the same three
    shapes `overshoot_for` accepts.
    """
    found = getattr(side, "sign", None)
    if isinstance(found, int) and found:
        return 1 if found > 0 else -1
    if isinstance(side, int) and side:
        return 1 if side > 0 else -1
    word = str(getattr(side, "value", side) or "").strip().lower()
    return -1 if word.startswith("sell") else 1


def crowding(
    feed: str,
    open_trades: Sequence[tuple[str, int]],
    share: float,
    side: object = None,
) -> float:
    """Reduce for every open position that shares a currency leg, same way round.

    See `trading-scaling.md` in research/docs.

    **`side` is the proposed trade's direction and leaving it out mis-scores a
    sell.** Without it this assumed every proposal was a buy, so it read a
    short of EURUSD as long EUR when it is long **USD** - and therefore found
    no crowding against a book that was long the dollar seven other ways.
    Measured on the live desk on 2026-11-10: `statespace-surprise` opened eight
    positions on one bar close, **every one of them long USD** - two by buying
    USDxxx and six by selling xxxUSD - and this multiplier scored the eighth at
    1.000 against the seven before it. An unsided reading of a currency leg is
    not a reading of it at all.

    `None` keeps the old buy-shaped behaviour rather than raising, because a
    caller that cannot say which way it is going is better served by the
    conservative half of the answer than by an exception in a sizing path.
    """
    if share <= 0 or share >= 1:
        return 1.0
    base, quote = ex.legs(feed)
    if not base and not quote:
        return 1.0
    mine_sign = _sign_of(side)

    crowded = 0
    for other_feed, sign in open_trades:
        other_base, other_quote = ex.legs(other_feed)
        if not other_base and not other_quote:
            continue
        # A shared leg only crowds when both positions are the same way round
        # on it. `Side.sign` is +1 for a buy, so a long of the base is long
        # that currency and short the quote - and a sell is the mirror, which
        # is what `mine_sign` carries.
        for leg, mine in ((base, mine_sign), (quote, -mine_sign)):
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


#: The cosine at which two rules count as making the same bet.
#:
#: **Derived from the live book rather than chosen round.** Measured on the
#: exposure that prompted this - one rule holding eight positions, every one
#: long USD - and on the shapes either side of it:
#:
#: * a one-position rule against a two-position long-dollar rule: **0.577**
#: * two two-position long-dollar rules against each other: **0.667**
#: * a one-position rule against the live seven-position book: **0.661**
#: * a **hedge** - long EUR and GBP, short the dollar - against a long-dollar
#:   rule: **-0.833**
#:
#: So the cases this exists for sit at 0.58 to 0.67 and a genuine hedge sits at
#: -0.83, and 0.5 separates them with wide margin on both sides. A threshold
#: above 0.7 would have missed every one of them: cosine over full leg vectors
#: **dilutes a shared dollar leg**, because each pair contributes its own
#: counter-currency and those read as disagreement even though they are
#: diversification. That dilution is the reason this number is written down
#: with its measurements instead of being left to look obvious.
#:
#: Nobody has scored it against outcomes. It is a risk threshold, not an edge.
AGREE_AT = 0.5


def by_agreement(
    mine: Sequence[tuple[str, int]],
    others: Mapping[str, Sequence[tuple[str, int]]],
    share: float,
    at_least: float = AGREE_AT,
) -> float:
    """Reduce for every **other rule** whose book points the same way as this one.

    **Different granularity from `crowding`, and that is the point.**
    `crowding` prices how many *positions* sit on a shared currency leg;
    this prices how many *rules* are making the same bet. A book of five rules
    that all agree is closer to one rule's risk than to five, and nothing in
    this desk's pipeline noticed that until now: `ideas.md` logs it as E6,
    "collapse look-alike strategies before counting trials", and
    `agenda.md` item 13 asks it as "when do independent strategies become
    dangerously synchronised".

    The desk already has the answer for *counting*: `node/selection.
    effective_trials` deflates a Sharpe by `N / (1 + (N-1) * mean pairwise
    correlation)`. It had never reached a sizing decision.

    `mine` is the exposure this rule would hold **including** the proposed
    trade, so a rule's first position is compared on what it is about to be
    rather than on what it was. `others` is each other rule's current book.

    Geometric, like `crowding`, and for the same reason: the risk of a shared
    direction compounds, so three rules all long the dollar are closer to three
    of one trade than to one and a half.

    `at_least` is a cosine, and `AGREE_AT` is derived from the case rather than
    picked - see its own comment for the four numbers.
    """
    if share <= 0 or share >= 1 or not others:
        return 1.0
    ours = ex.leg_vector(mine)
    if not ours:
        return 1.0
    agreeing = sum(
        1
        for book in others.values()
        if book and ex.agreement(ours, ex.leg_vector(book)) >= at_least
    )
    return share**agreeing if agreeing else 1.0


def by_volatility(vol_bps: float, target_bps: float) -> float:
    """Reduce when the instrument is more volatile than the target.

    See `trading-scaling.md` in research/docs.
    """
    if target_bps <= 0 or vol_bps <= 0:
        return 1.0
    return min(1.0, target_bps / vol_bps)


def by_regime(ratio: float | None, width: float, floor: float = 0.5) -> float:
    """Reduce when the volatility scale is expected to change sharply.

    See `trading-scaling.md` in research/docs.
    """
    if width <= 0 or ratio is None or ratio <= 0:
        return 1.0
    # Log distance, so 0.5 and 2.0 are the same distance from 1.0. A ratio is a
    # multiplicative quantity and treating it additively would make the quiet
    # tail - which is bounded below by zero - look far closer than the loud one.
    drift = abs(math.log(float(ratio)))
    if drift <= width:
        return 1.0
    over = (drift - width) / width
    return max(floor, min(1.0, 1.0 - over * (1.0 - floor)))


def by_spike(percentile: float | None, above: float, floor: float = 0.5) -> float:
    """Halve into the windows where a large bar is likely.

    See `trading-scaling.md` in research/docs.
    """
    if above <= 0 or percentile is None:
        return 1.0
    if float(percentile) < above:
        return 1.0
    effects.fired("trading.spike_switch")
    return max(FLOOR, min(1.0, floor))


def by_edge(edge_vol: float | None, full_at: float) -> float:
    """Scale by measured net edge, fractionally.

    See `trading-scaling.md` in research/docs.
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

    See `trading-scaling.md` in research/docs.
    """
    if halt_at <= 0 or peak <= 0 or equity >= peak:
        return 1.0
    fallen = (peak - equity) / peak
    if fallen >= halt_at:
        return FLOOR
    return max(FLOOR, math.sqrt(1.0 - fallen / halt_at))


def by_interval(interval: str, weights: Sequence[tuple[str, float]]) -> float:
    """Size by the timeframe the signal was triggered on.

    See `trading-scaling.md` in research/docs.
    """
    if not weights:
        return 1.0
    want = (interval or "").strip().lower()
    for name, weight in weights:
        if name == want:
            return max(FLOOR, min(1.0, weight))
    return 1.0


def overshoot_for(book: Sequence[tuple[str, float]], feed: str, side: object = None) -> float:
    """This feed's stop overshoot, preferring a side-specific entry.

    `boom_500_index.sell` beats `boom_500_index`, because on a jump instrument
    the two sides are not the same trade: a stop on the spike side can only be
    gapped over. See `config._overshoot`.
    """
    held = dict(book)
    name = feed.strip().lower()
    word = str(getattr(side, "value", side) or "").strip().lower()
    if word and f"{name}.{word}" in held:
        return held[f"{name}.{word}"]
    return held.get(name, 1.0)


def by_slippage(overshoot: float) -> float:
    """Give back the size an instrument's stops overshoot by.

    See `trading-scaling.md` in research/docs.
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
