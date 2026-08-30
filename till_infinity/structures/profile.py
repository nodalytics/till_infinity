"""Levels where a lot of supply changed hands.

Glassnode's long-term-holder cost basis reports how much bitcoin last moved in
each price band - 1.05m BTC between $83k and $86k while spot is near $79k. The
claim is that a band holding a great deal of supply is a price the market has
to get through, because everyone who bought there is watching it.

That is the same object this package already models. A price where supply
changed hands is a price with unfilled interest at it, which is what an origin
is and what a level's touch record measures. The difference is only how it is
found: an origin is found by what price *did* next, and this is found by how
much happened *at* the price.

## No vendor, and none needed

There is no on-chain feed here and a cost basis is bitcoin-specific anyway. The
market-data equivalent is the distribution of activity over price, which every
instrument has and which needs nothing bought: bin the window by price, add up
what happened in each bin, and the peaks are the bands.

## Weight by volume where it is real, and by time where it is not

Volume would be the right weight and is not always available: 43% of stored
eurusd bars carry none, and on an FX CFD what is reported is tick count rather
than contracts, so it measures *activity* rather than size. Bitcoin is the one
instrument here whose volume means what the word usually means.

So weights are optional. Given none, each bar counts once - **time at price**,
which is the older idea and asks a defensible question of its own: where has
this market been willing to trade. Given volume, that is used instead. The two
answer slightly different questions and the code says which it used rather than
pretending they are the same.

## What a node is

A bin is a **node** when it holds several times its fair share of everything in
the window and is a local maximum among its neighbours. Both conditions matter:
the share alone would return a plateau's worth of adjacent bins, and the local
maximum alone would return the tallest bin of a flat profile, which is noise
with a rank.

The share is relative rather than absolute, and that is not a detail: as a
fixed 5% this drew **no nodes at all, on any instrument**. Bins are half a
volatility unit wide, a 500-bar window spans far more than twenty of them, and
no bin can hold a twentieth of everything unless price barely moves.

Bins are `BIN_VOL` volatility units wide, because a fixed price width would give
btc four bins and eurusd four thousand.
"""

from __future__ import annotations

from collections.abc import Sequence

from .pips import Point, Swing
from .volatility import Volatility

#: Bin width, in volatility units.
BIN_VOL = 0.5

#: How many times its fair share a bin must hold to be a node.
#:
#: **Relative, because an absolute share cannot be calibrated.** This was a
#: fixed 5% and drew nothing anywhere: bins are half a volatility unit wide, a
#: 500-bar window spans far more than twenty of them, and no bin can hold a
#: twentieth of everything unless price sits almost still. The threshold was an
#: absolute number where the quantity it judges depends on how many bins there
#: are.
#:
#: Fair share is `1 / bins`, so this asks for a bin holding `NODE_CONCENTRATION`
#: times what it would hold if activity were spread evenly. That self-calibrates
#: to any window length and to any instrument's spread of prices - the same
#: argument that makes the bins volatility-scaled rather than fixed in price.
NODE_CONCENTRATION = 3.0

#: The most a bin can be asked to hold, whatever the bin count implies. Half a
#: window in one half-unit band is concentrated by any reading.
MOST_OF_IT = 0.5

#: How many bins either side must be smaller for a bin to be a local maximum.
NODE_SPAN = 2


def nodes(
    prices: Sequence[float],
    vol: Volatility,
    *,
    weights: Sequence[float] | None = None,
    bin_vol: float = BIN_VOL,
    concentration: float = NODE_CONCENTRATION,
    span: int = NODE_SPAN,
) -> list[tuple[float, float]]:
    """`(price, share of the window)` for each high-activity band, richest first.

    `weights` is volume where it is real. Without it every bar counts once,
    which is time at price - see the module docstring on why that is a
    different question rather than a worse answer.
    """
    if len(prices) < 2:
        return []
    unit = vol.price_units(prices[-1], bin_vol)
    if unit <= 0:
        return []
    if weights is not None and len(weights) != len(prices):
        weights = None

    floor = min(prices)
    buckets: dict[int, float] = {}
    for index, price in enumerate(prices):
        weight = 1.0
        if weights is not None:
            raw = weights[index]
            # A missing or zero volume is not evidence of no activity, it is an
            # absent measurement - counting it as zero would erase the bar.
            weight = float(raw) if raw and raw > 0 else 1.0
        at = int((price - floor) / unit)
        buckets[at] = buckets.get(at, 0.0) + weight

    total = sum(buckets.values())
    if total <= 0 or not buckets:
        return []

    # What a bin would hold if activity were spread evenly across the bins that
    # actually saw any. Empty bins are not counted: a window that ranges widely
    # and trades in two places has two bins, not two hundred, and dividing by
    # the span would make every node look concentrated.
    fair = 1.0 / len(buckets)
    # Capped, or the threshold becomes unsatisfiable exactly where it should be
    # easiest: with three bins a fair share is a third and three times that is
    # everything, so a window that traded in two places would return nothing.
    # A bin holding half of a window is a node whatever the bin count says.
    # Named `least` rather than `floor`, which is already the window's lowest
    # price a few lines up. Shadowing it put every node at 8.5 instead of 100.
    least = min(fair * concentration, MOST_OF_IT)

    found: list[tuple[float, float]] = []
    for at, weight in buckets.items():
        if weight / total < least:
            continue
        neighbours = [buckets.get(at + step, 0.0) for step in range(-span, span + 1) if step != 0]
        if any(other > weight for other in neighbours):
            continue
        # The middle of the bin: the band is the claim, not a single price.
        found.append((floor + (at + 0.5) * unit, weight / total))
    found.sort(key=lambda pair: -pair[1])
    return found


def points(
    times: Sequence[float],
    prices: Sequence[float],
    vol: Volatility,
    *,
    weights: Sequence[float] | None = None,
) -> list[Point]:
    """High-activity bands as turning points, so levels can form at them.

    A fourth formation beside `pips`, `runs` and `origin_points`, on the same
    terms - the same `Point`, so nothing downstream can tell which pass found a
    level.

    **A node has no side**, which is the honest difference from the other three.
    A swing high is a place price turned down and a swing low is where it turned
    up; a band where a lot of supply changed hands is neither, and price can
    arrive at it from either direction. `Swing.HIGH` and `Swing.LOW` are the
    only turns `form` accepts, so a node is emitted as whichever it is *not*
    currently on - a band above the last price behaves like resistance and one
    below like support, which is the same reading a cost-basis shelf gets.

    `confirmed` is the last time in the window. A profile is a statement about
    a window and is not knowable before the window ends, so anything asking
    when this became usable must not be given an earlier answer.
    """
    if len(prices) < 2 or len(times) != len(prices):
        return []
    spot = prices[-1]
    settled = float(times[-1])
    found: list[Point] = []
    for price, held in nodes(prices, vol, weights=weights):
        found.append(
            Point(
                index=len(prices) - 1,
                time=int(settled),
                price=price,
                swing=Swing.HIGH if price > spot else Swing.LOW,
                # The share of the window's activity, in basis points, so it
                # ranks the same way prominence does for the other formations.
                prominence_bps=held * 10_000,
                confirmed=settled,
            )
        )
    return found
