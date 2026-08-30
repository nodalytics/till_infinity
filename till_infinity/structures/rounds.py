"""Levels at round numbers, because the claim is cheap to test and often made.

4400 on gold, 80,000 on bitcoin, 1.1000 on eurusd. The claim is that people
place orders at numbers they can say out loud, so a round price accumulates
resting interest that has nothing to do with what happened there before.

This is the only formation here that needs **no history at all**. Every other
one reads the window: a pip is a turn that happened, an origin is an impulse
that happened, a mode is where activity was. A round number is a level before
the instrument has printed a single bar, which makes it either a free level or
a superstition, and there is no way to tell which without measuring.

It is built for exactly that reason. It costs almost nothing, it plugs into the
same outcome machinery as everything else, and if it is noise the record will
say so in a few thousand touches rather than in an argument.

## What counts as round is relative, and has to be

"Ends in zero" is meaningless without a scale: gold at 4400 and eurusd at 1.1000
are both round and differ by four orders of magnitude. So the step is chosen
from the instrument's own volatility - the smallest power of ten that is at
least `STEP_VOL` volatility units wide, so a round number is a price about that
far from its neighbours whatever the instrument is.

The alternative, a table of steps per instrument, is what this repository keeps
finding bugs in: a new instrument arrives, nobody adds a row, and the formation
silently draws nothing for it.

## Halves as well as wholes

A step of 100 on gold gives 4400 and 4500 and nothing between, which is a level
every 2-3 volatility units at ordinary gold volatility - too sparse to be the
level price is actually at. Half-steps (4450) are the usual desk convention and
are included, ranked below whole ones, which is the claim: 4400 is rounder than
4450 and both are rounder than 4437.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .pips import Point, Swing
from .volatility import Volatility

#: How far apart round numbers should be, in volatility units. The step is the
#: smallest power of ten at least this wide, so this sets the density of the
#: grid rather than its position.
STEP_VOL = 5.0

#: How far either side of the last price to emit levels, in volatility units.
#: A round number thirty units away is not a level anything will reach inside a
#: hold, and emitting it costs a level slot for nothing.
REACH_VOL = 12.0

#: Prominence for a whole step against a half step, in basis points. Whole
#: numbers are the claim; halves are the convention that grew around it.
WHOLE_BPS, HALF_BPS = 10_000.0, 5_000.0


def step_for(price: float, vol: Volatility, *, step_vol: float = STEP_VOL) -> float:
    """The smallest power of ten at least `step_vol` units wide, at this price.

    Relative rather than tabulated: a new instrument gets a sensible grid on
    its first bar instead of drawing nothing until somebody adds a row for it.
    """
    want = vol.price_units(price, step_vol)
    if want <= 0 or price <= 0:
        return 0.0
    return 10.0 ** math.ceil(math.log10(want))


def levels_near(
    price: float,
    vol: Volatility,
    *,
    step_vol: float = STEP_VOL,
    reach_vol: float = REACH_VOL,
) -> list[tuple[float, float]]:
    """`(price, prominence)` for the round numbers within reach, nearest first."""
    step = step_for(price, vol, step_vol=step_vol)
    if step <= 0:
        return []
    reach = vol.price_units(price, reach_vol)
    if reach <= 0:
        return []

    found: list[tuple[float, float]] = []
    first = math.floor((price - reach) / step)
    last = math.ceil((price + reach) / step)
    # Guard against a volatility estimate so wide that the grid is enormous.
    if last - first > 200:
        return []
    for n in range(first, last + 1):
        for offset, weight in ((0.0, WHOLE_BPS), (0.5, HALF_BPS)):
            at = (n + offset) * step
            if at <= 0 or abs(at - price) > reach:
                continue
            found.append((at, weight))
    found.sort(key=lambda pair: abs(pair[0] - price))
    return found


def points(
    times: Sequence[float],
    prices: Sequence[float],
    vol: Volatility,
    *,
    step_vol: float = STEP_VOL,
    reach_vol: float = REACH_VOL,
) -> list[Point]:
    """Round numbers as turning points, so levels can form at them.

    **These are not turns and the code should not pretend otherwise.** Every
    other formation emits a price where something happened; this emits a price
    because of how it is written. It is given `Swing.HIGH` above the last price
    and `Swing.LOW` below for the same reason a mode is - those are the only
    two `form` accepts - and the `index` and `time` are the last bar's, because
    a round number has no moment of its own.

    That is a real weakness and it is the reason this is worth measuring rather
    than assuming: a formation with no history behind it either works or is
    superstition, and the touch record is what separates those.
    """
    if not prices or len(times) != len(prices):
        return []
    spot = prices[-1]
    settled = float(times[-1])
    return [
        Point(
            index=len(prices) - 1,
            time=int(settled),
            price=at,
            swing=Swing.HIGH if at > spot else Swing.LOW,
            prominence_bps=weight,
            confirmed=settled,
        )
        for at, weight in levels_near(spot, vol, step_vol=step_vol, reach_vol=reach_vol)
    ]
