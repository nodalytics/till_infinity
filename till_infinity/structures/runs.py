"""Swings as run boundaries rather than bar extremes.

[levels.md](../../docs/levels.md), "A level spans periods too", argues that the
quantisation removed from *touches* is still present in *formation*. `pips.py`
selects bar indices, so a level is the high or low of whichever bar was picked,
and the same structure observed at 3m and at 1d gets two different prices. The
inverse-variance fusion in confluence then spends its precision reconciling a
sampling artefact rather than a disagreement about the market.

Price does not turn at a bar. It turns where one run of volatility ends and the
next begins, and that meeting point is the same price whichever resolution
watched it — the runs differ in length, the intersection does not.

This is written to be **compared, not adopted**. It produces the same `Point`
objects `pips.points` does, so `levels.form` consumes either without knowing
which it was handed, and both can be run over one history to see which set
price respects more often. The counter-argument is real and is in the doc: a
daily close is a price participants act on, so some bar-quantised levels are
levels *because* they are bar-quantised. If that is right the two coexist
rather than one replacing the other.

## Confirmation comes for free here

A PIP needs `confirm` bars after it before it can be called a turn, and the
count is a choice. A run boundary settles when price has retraced from it by
the threshold — the retracement *is* the proof, so `confirmed` is the bar that
completed it rather than a fixed offset. A boundary the series has not yet
turned away from is not emitted at all, which is the same guarantee `as_of`
gives, arrived at by construction instead of by filtering.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from .pips import Point, Swing
from .volatility import Volatility

#: How far price must come back off an extreme before the run is over, in
#: volatility units.
#:
#: Coarser than `ARRIVAL_RUN_VOL` (0.5), which answers a different question.
#: That one decides where *within* an interaction the leg in ended, with the
#: interaction already established; this one decides whether a turn is a
#: structure at all. A move that reverses by less than one typical move has not
#: shown that anybody defended it.
#:
#: The first thing to sweep when comparing the two formations — it is the knob
#: that decides how many levels exist, and a threshold chosen to produce a
#: pleasing number would be the same mistake as a hand-picked tolerance.
RUN_SWING_VOL = 1.0

#: Below this there is not enough series to establish a direction, let alone a
#: reversal. Matches `pips.MIN_POINTS` so the two formations refuse on the same
#: input rather than one quietly returning levels the other could not.
MIN_BARS = 4


def points(
    times: Sequence[int],
    prices: Sequence[float],
    vol: Volatility,
    *,
    threshold: float = RUN_SWING_VOL,
) -> list[Point]:
    """Turning points where one run ends and the next begins.

    Walks the series once, holding the current run's direction and its extreme.
    When price has come back off that extreme by `threshold` volatility units,
    the run is over: the extreme was a turn, and the bar that completed the
    retracement is when it became knowable.

    Returns points in the order they were *settled*, which is also the order
    they became usable. An unfinished trailing run contributes nothing — its
    extreme may still be exceeded, and emitting it would be the trailing-swing
    look-ahead that `pips.confirmed` exists to prevent.
    """
    if len(times) != len(prices):
        raise ValueError("times and prices must be the same length")
    if len(prices) < MIN_BARS or not vol.bps:
        return []

    found: list[Point] = []
    direction = 0  # +1 while the run is making highs, -1 while making lows
    extreme = prices[0]
    extreme_at = 0
    start = prices[0]

    for index in range(1, len(prices)):
        price = prices[index]
        if not price:
            continue
        moved = _units(extreme, price, vol)

        if direction == 0:
            # No run yet: the first move past the threshold sets the direction,
            # and the point it left behind is the first boundary candidate.
            if moved >= threshold:
                direction = 1 if price > extreme else -1
                extreme, extreme_at = price, index
            elif (price > extreme) != (price > start):
                extreme, extreme_at = price, index
            continue

        extends = price > extreme if direction > 0 else price < extreme
        if extends:
            extreme, extreme_at = price, index
            continue

        if moved < threshold:
            continue  # a pause, not a turn

        found.append(
            Point(
                index=extreme_at,
                time=times[extreme_at],
                price=extreme,
                swing=Swing.HIGH if direction > 0 else Swing.LOW,
                # How far the run ran, in basis points — the analogue of a
                # PIP's prominence, and a measurement rather than a distance
                # from an imaginary chord.
                prominence_bps=abs((extreme - start) / start * 10_000) if start else 0.0,
                # The retracement is the proof, so this is when it was settled
                # rather than a fixed number of bars later.
                confirmed=float(times[index]),
            )
        )
        direction = -direction
        start = extreme
        extreme, extreme_at = price, index

    return found


def _units(a: float, b: float, vol: Volatility) -> float:
    """Distance between two prices in volatility units."""
    if not a or not vol.bps:
        return 0.0
    return abs((b - a) / a * 10_000) / vol.bps


def spans(found: Sequence[Point]) -> list[tuple[Point, Point]]:
    """Consecutive boundaries, which is what a run actually is.

    A level found this way is defined by the period on each side of it rather
    than by one bar, and this is the pair a caller needs to say so. Unused by
    formation today — kept because the whole argument for run boundaries is
    that a level *spans* something, and the shape should exist before anything
    is built on it.
    """
    return list(pairwise(found))


def summary(found: Sequence[Point]) -> dict[str, float]:
    """Enough to compare one formation against another at a glance."""
    if not found:
        return {"swings": 0, "highs": 0, "lows": 0, "median_prominence_bps": 0.0}
    proms = sorted(point.prominence_bps for point in found)
    middle = proms[len(proms) // 2]
    return {
        "swings": len(found),
        "highs": sum(1 for point in found if point.swing is Swing.HIGH),
        "lows": sum(1 for point in found if point.swing is Swing.LOW),
        "median_prominence_bps": round(middle, 4) if not math.isnan(middle) else 0.0,
    }
