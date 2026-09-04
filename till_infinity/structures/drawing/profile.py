"""Levels where a lot of supply changed hands, found as modes rather than bins.

Glassnode's long-term-holder cost basis reports how much bitcoin last moved in
each price band - 1.05m BTC between $83k and $86k while spot is near $79k. The
claim is that a band holding a great deal of supply is a price the market has
to get through, because everyone who bought there is watching it.

That is the same object this package already models. A price where supply
changed hands is a price with unfilled interest at it, which is what an origin
is and what a level's touch record measures. The difference is only how it is
found: an origin is found by what price *did* next, and this is found by how
much happened *at* the price.

There is no on-chain feed here and a cost basis is bitcoin-specific anyway. The
market-data equivalent is the distribution of activity over price, which every
instrument has and which needs nothing bought.

## Why this is not a histogram any more

It was, and the histogram could not do the job. A bin qualified by holding
several times its **fair share** of the window, where fair is one over the
number of occupied bins - and that test can only ever fire when *one* band
dominates:

    bands   bins each   fair    floor   a peak holds   node?
      1         2       0.500   0.500      0.500        yes
      2         2       0.250   0.500      0.250        no
      3         2       0.167   0.500      0.167        no
      5         3       0.067   0.200      0.067        no

When the bands are equally busy a peak holds *exactly* its fair share, for any
number of bands and any spread - never three times it. A range, which is the
one situation a volume-at-price formation exists for, produced nothing by
construction. In production it drew 3 levels out of 1,808.

So the threshold is now **relative to the busiest mode rather than to a fair
share**. Several equally busy bands all sit at the peak, so they all pass,
which is the whole point.

## And why it is not a histogram in the other sense either

Bins have edges, and a band that straddles one is split between two bins that
each look ordinary. A kernel puts a smooth bump at every observation and adds
them up, so a band is a peak wherever it happens to fall. The kernel is
Epanechnikov - finite support, so the density at a price only sums the prices
within one bandwidth of it, which with the series sorted is two moving pointers
rather than a pass over everything.

Bandwidth is in volatility units, for the reason the bins were: a fixed price
width gives btc four bands and eurusd four thousand.

## A mode is emitted once per visit, not once

`levels.form` clusters **turns** and needs three of them within a volatility
unit. A formation that emits one point per band, all stamped with the end of
the window, can never make a cluster - which was the second, independent reason
this drew almost nothing.

A band price came back to four times is four visits, and each visit is a bar
where price was actually there. That is three turns for `form` to cluster when
the band has been revisited three times, and nothing when it has not, which is
the correct answer rather than a workaround: a price visited once is not a
level, whatever the density says.

## The width is a volatility estimate

A mode has a spread, and that spread is how far price wanders while it is at
this band - a **local** volatility, measured at the price rather than across
the window. It is reported as `width_vol` and carried on the point, because a
level that price hugs within a quarter of a unit and one it swings a unit
either side of are different objects, and everything downstream currently sizes
their zones from one global estimate.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from typing import NamedTuple

from ..vol.volatility import Volatility
from .pips import Point, Swing

#: Kernel half-width, in volatility units. Every observation within this of a
#: price contributes to the density there.
BANDWIDTH_VOL = 0.75

#: How far apart two modes must be to be two modes, in volatility units.
#: Anything closer is the same band seen twice and the busier one wins.
SEPARATION_VOL = 1.5

#: How dense a mode must be against the **busiest** one in the window, rather
#: than against a fair share. This is the correction: n equally busy bands all
#: sit at the peak, so a test relative to the peak admits all of them, and a
#: test relative to a fair share admits none. See the module docstring.
MODE_OF_PEAK = 0.5

#: How much busier than **uniform** the busiest band must be before this
#: formation says anything at all.
#:
#: A threshold relative to the peak admits equally busy bands, which is the
#: whole fix - and on its own it also admits a perfectly flat series, where
#: every price ties the peak and thirteen modes come back from a sawtooth. So
#: the peak is judged against a null first: how dense the busiest band would be
#: if the same observations were spread evenly over the same range. A band is a
#: place with more activity than an even spread would put there, and a window
#: with no such place has no bands rather than a ranking of noise.
MIN_CONTRAST = 2.0

#: A visit ends when price has been outside the band for this many bars. One
#: bar of noise stepping out of the band does not end a visit and start a new
#: one, which would turn a single camp into a dozen turns and manufacture a
#: level out of one occasion.
VISIT_GAP = 3


class Mode(NamedTuple):
    """One busy band: where it is, how much is there, how wide it is."""

    price: float
    #: Share of the window's observations lying within one bandwidth.
    share: float
    #: Spread of those observations, in volatility units. See the docstring -
    #: this is a local volatility, measured at the price.
    width_vol: float
    #: Density at the peak, relative to the busiest mode in the window.
    strength: float


def _density(ordered: Sequence[float], band: float) -> list[float]:
    """Epanechnikov density at each observation, from a sorted series.

    Finite support is what makes this cheap: the sum at a price only runs over
    the prices within one bandwidth, so with the series sorted it is two
    pointers walking forward rather than a pass over everything for every
    point.
    """
    out = [0.0] * len(ordered)
    low = high = 0
    for index, price in enumerate(ordered):
        while ordered[low] < price - band:
            low += 1
        while high < len(ordered) and ordered[high] <= price + band:
            high += 1
        total = 0.0
        for other in range(low, high):
            gap = (ordered[other] - price) / band
            total += 1.0 - gap * gap  # Epanechnikov, up to a constant
        out[index] = total
    return out


def modes(
    prices: Sequence[float],
    vol: Volatility,
    *,
    weights: Sequence[float] | None = None,
    bandwidth_vol: float = BANDWIDTH_VOL,
    separation_vol: float = SEPARATION_VOL,
    of_peak: float = MODE_OF_PEAK,
    contrast: float = MIN_CONTRAST,
) -> list[Mode]:
    """The busy bands in this window, densest first.

    `weights` is volume where it is real. Volume would be the right weight and
    is not always available - 43% of stored eurusd bars carry none, and on an
    FX CFD what is reported is tick count rather than contracts. Without it
    each bar counts once, which is **time at price**: the older idea, and a
    defensible question of its own rather than a worse answer.
    """
    if len(prices) < 3:
        return []
    band = vol.price_units(prices[-1], bandwidth_vol)
    if band <= 0:
        return []
    if weights is not None and len(weights) != len(prices):
        weights = None

    order = sorted(range(len(prices)), key=lambda i: prices[i])
    ordered = [float(prices[i]) for i in order]
    density = _density(ordered, band)
    if weights is not None:
        # A missing or zero volume is not evidence of no activity, it is an
        # absent measurement - counting it as zero would erase the bar.
        scale = [float(weights[i]) if weights[i] and weights[i] > 0 else 1.0 for i in order]
        density = [d * w for d, w in zip(density, scale, strict=True)]

    peak = max(density)
    if peak <= 0:
        return []

    # The null: what the density would be if these observations were spread
    # evenly over the range they cover. `2 * band / span` is the share of the
    # range a kernel reaches, and 2/3 is the average Epanechnikov weight across
    # it, so this is the count the kernel would see under a flat distribution.
    span = ordered[-1] - ordered[0]
    if span <= 0:
        return []
    flat = len(ordered) * (2.0 * band / span) * (2.0 / 3.0)
    if flat > 0 and peak < flat * contrast:
        return []

    gap = vol.price_units(prices[-1], separation_vol)
    # Non-maximum suppression: take the densest point, claim everything within
    # `gap` of it, repeat. In continuous space this is what "is a local
    # maximum" means, and unlike a bin comparison it cannot be fooled by a band
    # that straddles an edge.
    taken: list[int] = []
    for index in sorted(range(len(ordered)), key=lambda i: -density[i]):
        if density[index] < peak * of_peak:
            break
        if any(abs(ordered[index] - ordered[other]) < gap for other in taken):
            continue
        taken.append(index)

    found: list[Mode] = []
    for index in taken:
        at = ordered[index]
        low, high = bisect_left(ordered, at - band), bisect_right(ordered, at + band)
        near = ordered[low:high]
        if not near:
            continue
        share = len(near) / len(ordered)
        mean = sum(near) / len(near)
        spread = math.sqrt(sum((p - mean) ** 2 for p in near) / len(near)) if len(near) > 1 else 0.0
        width = vol.units(spread / at * 10_000) if at else 0.0
        found.append(Mode(at, share, width, density[index] / peak))
    found.sort(key=lambda mode: -mode.strength)
    return found


def nodes(
    prices: Sequence[float],
    vol: Volatility,
    *,
    weights: Sequence[float] | None = None,
    **over: float,
) -> list[tuple[float, float]]:
    """`(price, share of the window)` per band, densest first.

    The shape the reachability harness reads. `modes` is the fuller answer and
    is what everything else here uses.
    """
    return [(mode.price, mode.share) for mode in modes(prices, vol, weights=weights, **over)]


def _visits(
    prices: Sequence[float],
    at: float,
    band: float,
    gap: int = VISIT_GAP,
) -> list[int]:
    """Bar indices, one per occasion price was at this band.

    The bar of each occasion that came closest to the band's centre, so a turn
    is stamped at the price the band actually claims rather than at whichever
    end of the visit happened to be last.

    An occasion ends only after `gap` bars away. One bar of noise stepping out
    does not end a visit and start another - that would turn a single camp into
    a dozen turns and manufacture a level out of one occasion.
    """
    out: list[int] = []
    best: int | None = None
    away = 0
    for index in range(len(prices)):
        if abs(prices[index] - at) <= band:
            away = 0
            if best is None or abs(prices[index] - at) < abs(prices[best] - at):
                best = index
            continue
        away += 1
        if best is not None and away >= gap:
            out.append(best)
            best = None
    if best is not None:
        out.append(best)
    return out


def points(
    times: Sequence[float],
    prices: Sequence[float],
    vol: Volatility,
    *,
    weights: Sequence[float] | None = None,
) -> list[Point]:
    """Busy bands as turning points, so levels can form at them.

    A fourth formation beside `pips`, `runs` and `origin_points`, on the same
    terms - the same `Point`, so nothing downstream can tell which pass found a
    level.

    **A band has no side**, which is the honest difference from the other
    three. A swing high is where price turned down and a swing low is where it
    turned up; a band where a lot of supply changed hands is neither, and price
    can arrive from either direction. `Swing.HIGH` and `Swing.LOW` are the only
    turns `form` accepts, so a band is emitted as whichever it is *not*
    currently on - one above the last price behaves like resistance and one
    below like support, which is the reading a cost-basis shelf gets.

    One point per **visit**, not one per band. `form` needs three turns within
    a volatility unit, so a formation emitting one point per band could never
    make a cluster; and a band price came to once is not a level whatever its
    density says, so this is the right test rather than a way around one.
    """
    if len(prices) < 3 or len(times) != len(prices):
        return []
    band = vol.price_units(prices[-1], BANDWIDTH_VOL)
    if band <= 0:
        return []
    spot = prices[-1]
    found: list[Point] = []
    for mode in modes(prices, vol, weights=weights):
        found.extend(
            Point(
                index=index,
                time=int(times[index]),
                price=prices[index],
                swing=Swing.HIGH if mode.price > spot else Swing.LOW,
                # How dense this band is against the busiest, in basis points,
                # so it ranks the way prominence does elsewhere.
                prominence_bps=mode.strength * 10_000,
                # A visit is over when price has left the band, which the bar
                # itself establishes - there is no confirmation delay to
                # choose, the same argument `runs` makes.
                confirmed=float(times[index]),
            )
            for index in _visits(prices, mode.price, band)
        )
    found.sort(key=lambda point: point.time)
    return found
