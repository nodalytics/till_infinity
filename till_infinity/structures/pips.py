"""Perceptually Important Points: the swings a person would actually draw.

A price series has thousands of bars and perhaps a dozen turns that matter.
PIP finds those turns by repeatedly keeping whichever point sits furthest from
the line joining the points already kept, so the shape survives while the noise
does not. It is the right primitive for levels because the levels people trade
are drawn at swing highs and lows - not at round numbers, and not at every
local extreme.

Distance is measured **vertically**, not perpendicularly. Time and price are
different units, so a perpendicular distance quietly depends on the aspect
ratio of an imaginary chart: rescale the x-axis and the "important" points
change. Vertical distance asks how far the price was from where a straight line
between its neighbours said it should be, which is a question about price
alone.

## Point-in-time correctness

This is the part that silently ruins backtests. A turning point is only
recognisable as one *after* the bars that follow it, so a PIP found in a window
that includes future bars was not knowable when it formed. Levels built from
those PIPs would be levels nobody could have drawn, and every measurement
against them flatters itself.

So every point here carries `confirmed`, the timestamp of the bar that settled
it, and callers asking "what was visible at time T" must filter on that rather
than on `time`. `as_of()` does it for you.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .state import Restorable

#: A swing needs this many bars after it before it is treated as established.
#: Fewer and every wiggle is a turning point; more and levels arrive too late
#: to be useful. Three is the smallest number that survives a single outlier.
DEFAULT_CONFIRM = 3

#: Below four points there is nothing to select - the endpoints are the series.
MIN_POINTS = 4


class Swing(StrEnum):
    HIGH = "high"
    LOW = "low"
    #: An endpoint, or a point on a straight run. Carries no level information.
    EDGE = "edge"


@dataclass(frozen=True, slots=True)
class Point(Restorable):
    """One perceptually important point."""

    index: int
    time: int
    price: float
    swing: Swing
    #: How far this point sat from the line joining its neighbours, in basis
    #: points of price. The selection criterion, kept because it is also the
    #: best single measure of how pronounced the swing was.
    prominence_bps: float
    #: When this became knowable, or `inf` while it still is not.
    #:
    #: Infinity rather than "the end of the window" matters more than it looks:
    #: clamping would let a swing one bar from the edge claim to be settled
    #: after one bar instead of `confirm`, and those trailing swings are
    #: precisely the ones that have not earned it yet. Every look-ahead bug in
    #: this file would live in that clamp.
    confirmed: float

    @property
    def is_turn(self) -> bool:
        return self.swing is not Swing.EDGE


def _vertical_gap(prices: Sequence[float], left: int, right: int, i: int) -> float:
    """How far `prices[i]` is from the chord between `left` and `right`."""
    span = right - left
    if span <= 0:
        return 0.0
    slope = (prices[right] - prices[left]) / span
    expected = prices[left] + slope * (i - left)
    return abs(prices[i] - expected)


def extract(prices: Sequence[float], count: int) -> list[int]:
    """The `count` most important indices, in order. Endpoints are always in.

    The classic algorithm: start with both ends, then repeatedly add whichever
    remaining point is furthest from the line joining its two current
    neighbours, until there are enough.
    """
    n = len(prices)
    if n <= 2 or count <= 2:
        return list(range(n)) if n <= 2 else [0, n - 1]

    kept = [0, n - 1]
    while len(kept) < min(count, n):
        best_gap, best_index, best_slot = 0.0, -1, -1
        for slot in range(len(kept) - 1):
            left, right = kept[slot], kept[slot + 1]
            for i in range(left + 1, right):
                gap = _vertical_gap(prices, left, right, i)
                if gap > best_gap:
                    best_gap, best_index, best_slot = gap, i, slot
        if best_index < 0:
            break  # a perfectly straight run: nothing left worth keeping
        kept.insert(best_slot + 1, best_index)
    return kept


def _classify(prices: Sequence[float], kept: Sequence[int], slot: int) -> Swing:
    """High, low, or neither, judged against the adjacent kept points."""
    if slot == 0 or slot == len(kept) - 1:
        return Swing.EDGE
    here = prices[kept[slot]]
    before, after = prices[kept[slot - 1]], prices[kept[slot + 1]]
    if here > before and here > after:
        return Swing.HIGH
    if here < before and here < after:
        return Swing.LOW
    return Swing.EDGE


def points(
    times: Sequence[int],
    prices: Sequence[float],
    count: int,
    *,
    confirm: int = DEFAULT_CONFIRM,
) -> list[Point]:
    """PIPs with their swing type, prominence and confirmation time.

    `prices` is normally the close series. Highs and lows can be passed instead
    when wicks matter, but mixing them within one call would compare points
    that never coexisted.
    """
    if len(times) != len(prices):
        raise ValueError("times and prices must be the same length")
    if len(prices) < MIN_POINTS:
        return []

    kept = extract(prices, count)
    last = len(prices) - 1
    found: list[Point] = []
    for slot, index in enumerate(kept):
        swing = _classify(prices, kept, slot)
        left = kept[slot - 1] if slot > 0 else index
        right = kept[slot + 1] if slot < len(kept) - 1 else index
        gap = _vertical_gap(prices, left, right, index) if left != right else 0.0
        price = prices[index]
        # Confirmation is a *bar* offset, so a gap in the series (a weekend)
        # does not make a swing look confirmed sooner than it was. A swing
        # without `confirm` bars after it yet is not confirmed at all.
        if swing is Swing.EDGE:
            settled: float = times[index]
        elif index + confirm <= last:
            settled = times[index + confirm]
        else:
            settled = math.inf
        found.append(
            Point(
                index=index,
                time=times[index],
                price=price,
                swing=swing,
                prominence_bps=(gap / price * 10_000) if price else 0.0,
                confirmed=max(float(times[index]), settled),
            )
        )
    return found


def as_of(found: Sequence[Point], when: float) -> list[Point]:
    """Only the points that were knowable at `when`.

    The whole reason `confirmed` exists. Filtering on `time` instead would
    include swings that had not yet happened as far as anyone watching could
    tell, which is the difference between a backtest and a fiction.
    """
    # Trailing swings carry `inf` until enough bars follow them, so they fall
    # out here without needing a special case.
    return [point for point in found if point.confirmed <= when]


def turns(found: Sequence[Point]) -> list[Point]:
    """Just the highs and lows - the points a level can be drawn at."""
    return [point for point in found if point.is_turn]
