"""Levels at the volume-weighted average price - fair value by the other definition.

[idea.md](../../../docs/idea.md) defines fair value as the price a demand or
supply spree began from: where agreement broke. VWAP is a different answer to
the same question - the price at which the business actually got done - and two
definitions that disagree is information. A price both arrive at is a stronger
claim than either alone, which is the argument `confluence` already makes
across timeframes.

It is also the one anchor large institutions are measured against, which gives
price a mechanical reason to return to it that has nothing to do with the level
being respected. That is a *different kind* of reason from anything else drawn
here, and different kinds are what a confluence is worth having.

## The honest state of the volume

`context/activity.py` sets this out at length and it applies with full force
here: on most feeds `volume` is **tick count**, not size; it is not comparable
between venues; and spot FX has no consolidated volume at all. Of the
instruments this desk carries, the crypto venues report real traded size, the
futures stand-ins report exchange volume, and the seven majors, gold and silver
report ticks or nothing.

Two consequences, both taken deliberately:

* **A weight need not be comparable to be useful.** Within one series, tick
  count still says which bars carried more business than their neighbours, and
  that is all a weighted mean asks of it. What would be indefensible is
  comparing one instrument's VWAP *distance* to another's in raw units, and
  nothing here does - everything leaves in volatility units like every other
  reading.
* **No volume means no level, not an unweighted one.** Falling back to a simple
  mean would produce a "VWAP" on every FX pair that is not a VWAP at all, and
  it would be indistinguishable downstream from one computed on real size. A
  pass that draws nothing on half the book is honest; one that draws something
  wrong everywhere is the failure `research/inert.md` catalogues, wearing a
  better disguise.

## Anchored, not rolling - and anchored to the clock, not to the buffer

VWAP is cumulative from an anchor - conventionally the session open. A rolling
window would be a moving average with volume weights, which is a different and
much weaker object: the whole claim is *the average price everyone who traded
since the anchor got*, and that only means something if the anchor is a moment
people agree on.

**The first version of this said that and then did the other thing.** It cut
anchors into blocks of `SPAN` bars counted from the start of the array - and the
array is a rolling window, so every bar that aged out shifted every anchor
boundary by one bar and moved every VWAP with it. Measured 2026-09-11 on 500
bars of 5m: rolling the window forward a single bar moved the oldest anchor's
price by about half a point and its time by exactly one bar, on every roll.
A level at a different price on every reform is not a level.

So the anchor is a **wall-clock bucket**: `span` times the bar interval, counted
from the epoch, which puts the boundary at the same instant for every window,
every restart and every instrument. At 5m and the default span that is 00:00,
08:00 and 16:00 UTC - within an hour of the three session opens without needing
a calendar, which is the compromise this package can actually defend. The bar
interval is inferred from the stamps rather than passed, because a pass that has
to be told what it is looking at is a pass that will one day be told wrong.

An anchor is emitted only once it holds a full `span` bars, so the one still
filling never publishes a price that is going to change.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from ..vol.volatility import Volatility
from .pips import Point, Swing

#: Bars per anchor. Reset this often and the VWAP is a short moving average;
#: never, and it is a number from before anybody currently trading arrived.
#:
#: Read with the bar interval it lands on: 96 five-minute bars is eight hours,
#: so anchors begin at 00:00, 08:00 and 16:00 UTC.
SPAN = 96

#: How near price must come, in volatility units, for the VWAP to count as a
#: level worth drawing rather than a line it happened to cross. Levels are made
#: of interactions, and a VWAP price never visited is a statistic.
TOUCH_VOL = 0.25

#: How many bars must carry real volume before the weighted mean is one. Below
#: this the anchor is a handful of bars and the average is theirs.
MIN_WEIGHTED = 12


def step_of(times: Sequence[float]) -> float:
    """The bar interval these stamps are on, in seconds. 0 when it cannot tell.

    The median gap rather than the first or the mean: a feed with a weekend in
    it, a gap, or one duplicated stamp should not change what interval it is on.
    """
    gaps = sorted(float(b) - float(a) for a, b in pairwise(times) if float(b) > float(a))
    return gaps[len(gaps) // 2] if gaps else 0.0


def typical(high: float, low: float, close: float) -> float:
    """The price a bar's volume is attributed to.

    High, low and close in thirds - the convention, and the reason it is not
    just the close is the same reason `wick` exists: business was done across
    the bar's range, not at the price it happened to finish on.
    """
    return (float(high) + float(low) + float(close)) / 3.0


def points(
    times: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    vol: Volatility,
    *,
    span: int = SPAN,
    touch_vol: float = TOUCH_VOL,
) -> list[Point]:
    """VWAP prices that price came back to, as turning points.

    Emitted on the same `Point` as every other pass, so nothing downstream can
    tell which formation found a level - the record decides which price is
    respected, not an argument here.

    A point is produced at the **end of each anchor**, at that anchor's VWAP,
    and only when price came within `touch_vol` of it during the anchor. The
    confirmation time is the anchor's last bar: a VWAP is knowable only once
    the bars it averages have closed, and dating it from the anchor's start
    would be drawing a level at a price nobody could yet compute.

    Anchors are wall-clock buckets `span` bars wide, so the same calendar moment
    falls in the same anchor however much of the window has aged out. See the
    module note - blocking by array index instead moved every level on every
    bar.
    """
    n = len(times)
    if n < span or len({n, len(highs), len(lows), len(closes), len(volumes)}) != 1:
        return []
    unit = vol.price_units(float(closes[-1]), 1.0) if vol.bps else 0.0
    if unit <= 0:
        return []
    step = step_of(times)
    if step <= 0:
        return []
    width = span * step

    # Bars grouped by the bucket their stamp falls in, in order. A bucket short
    # of `span` bars is the one still filling, or one a gap ate; either way its
    # mean would move the next time it is asked, so it does not publish.
    buckets: dict[int, list[int]] = {}
    for i, stamp in enumerate(times):
        buckets.setdefault(int(float(stamp) // width), []).append(i)

    found: list[Point] = []
    for _, rows in sorted(buckets.items()):
        if len(rows) < span:
            continue
        start, stop = rows[0], rows[-1] + 1
        weighted = notional = 0.0
        seen = 0
        for i in range(start, stop):
            weight = float(volumes[i])
            if math.isnan(weight) or weight <= 0:
                continue
            notional += weight
            weighted += typical(highs[i], lows[i], closes[i]) * weight
            seen += 1
        # No volume means no level. A mean of the prices would be a different
        # object wearing this one's name, and indistinguishable downstream.
        if seen < MIN_WEIGHTED or notional <= 0:
            continue
        price = weighted / notional
        near = touch_vol * unit
        touched = any(
            float(lows[i]) - near <= price <= float(highs[i]) + near for i in range(start, stop)
        )
        if not touched:
            continue
        last = stop - 1
        found.append(
            Point(
                index=last,
                time=float(times[last]),
                price=price,
                # A VWAP has no side: it is where business was done, not a
                # place price turned from. `profile` says the same about a
                # busy band, and for the same reason.
                swing=Swing.HIGH if float(closes[last]) < price else Swing.LOW,
                prominence_bps=abs(price - float(closes[last])) / price * 10_000,
                confirmed=float(times[last]),
            )
        )
    return found
