"""The sequence of moves between reversal points, as an observation process.

From a set of in-house papers on market geometry and nodal displacement
sequencing. Their shared claim, and the one worth keeping, is not about
patterns:

> symmetry transformations operate not on price, but on the sequence of
> *moves between reversal points*. While price levels change constantly, the
> geometric relationships between consecutive swings persist within a regime
> and break cleanly at regime boundaries.

That is a statement about **what to observe**, and this package has never
observed anything but price. Every member takes `measured` as a level and
asks where the level is going. A displacement sequence is a different series
with a different clock: it advances when price turns, not when the clock
ticks, and its elements are already differences, so the unit root is gone
before any model sees it.

`inputs.pivots` already finds confirmed reversals - marked where they are
confirmed rather than where they happened, which is what keeps them causal.
This turns them into the sequence.

## What is in a displacement

Each is a move from one confirmed pivot to the next: its **size** in
volatility units, its **duration** in hours, and its **direction**. From
consecutive pairs come the two quantities the papers build on - the **ratio**
of successive sizes and the **turn**, how the direction changed - and those
are what a symmetry transformation acts on.

Sizes are in volatility units and durations in hours for the usual reason:
the sequence has to mean the same thing at 15m and at 1d, and a displacement
measured in price and bars means two different things.

## The honest prior

This desk measured **counted pivots** - how many per hour, and their EMAs -
across 1,020 cells and found nothing: every family within 0.015 of zero net
of a trailing standard deviation. That is not evidence against this, because
a count is not a sequence and the ratios between displacements were never
tested. But it is the nearest measurement, and it was null.

## Nothing here publishes

This is an observation process, not a model. What it enables is a member
whose `measured` is a displacement rather than a price, and the null for any
such member is the same member driven by price - because if observing the
sequence buys nothing, the sequence is a re-encoding and not a signal.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

HOUR = 3600.0


@dataclass(frozen=True, slots=True)
class Displacement:
    """One move between consecutive confirmed reversals."""

    #: When the move ended, and when it became **knowable** - which differ by
    #: the confirmation lag, and conflating them is the leak this avoids.
    ended: float
    confirmed: float
    #: Size in volatility units, always positive.
    size: float
    #: Hours from the previous reversal to this one.
    hours: float
    #: `+1` for a move up, `-1` for a move down.
    direction: int

    @property
    def speed(self) -> float:
        """Volatility units per hour. The size with its duration divided out."""
        return self.size / self.hours if self.hours > 0 else 0.0


def sequence(
    times: Sequence[float],
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    span: int,
    unit: float,
) -> list[Displacement]:
    """Confirmed reversals, turned into the moves between them.

    `span` is the pivot's confirmation reach in bars and `unit` the series'
    volatility unit, both the caller's because both are series properties
    this module should not re-derive.

    **Each displacement carries the time it was confirmed, not just the time
    it ended.** A move that ended at bar `k` is only knowable at `k + span`,
    so a caller building features must filter on `confirmed`, and giving it
    both makes that possible rather than hoping.
    """
    n = min(len(times), len(closes), len(highs), len(lows))
    if n < 2 * span + 2 or span < 1 or unit <= 0:
        return []

    marks: list[tuple[int, float, int]] = []
    for k in range(span, n - span):
        window = range(k - span, k + span + 1)
        if all(highs[j] < highs[k] for j in window if j != k):
            marks.append((k, float(highs[k]), 1))
        elif all(lows[j] > lows[k] for j in window if j != k):
            marks.append((k, float(lows[k]), -1))

    out: list[Displacement] = []
    for a, b in itertools.pairwise(marks):
        if a[2] == b[2]:
            # Two highs in a row with no low between them is not a swing; it
            # is the detector firing twice on one structure. Keeping both
            # would make the sequence's alternation a property of the
            # threshold rather than of the market.
            continue
        gap = (float(times[b[0]]) - float(times[a[0]])) / HOUR
        if gap <= 0:
            continue
        out.append(
            Displacement(
                ended=float(times[b[0]]),
                confirmed=float(times[min(b[0] + span, n - 1)]),
                size=abs(b[1] - a[1]) / unit,
                hours=gap,
                direction=1 if b[1] > a[1] else -1,
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class Relation:
    """What one displacement is, relative to the one before it."""

    #: `size(t) / size(t-1)`. One means the swing repeated at the same scale.
    ratio: float
    #: `hours(t) / hours(t-1)`. Scaling in time rather than in price.
    stretch: float
    #: `+1` when the direction reversed, which is the usual case for an
    #: alternating sequence, and `-1` when it did not.
    turn: int
    #: Log ratio, which is the quantity to model: a ratio is bounded below by
    #: zero and multiplicative, so its logarithm is the additive one.
    log_ratio: float
    #: When this became knowable.
    confirmed: float


def relations(moves: Sequence[Displacement]) -> list[Relation]:
    """Consecutive pairs, as the ratios a symmetry transformation acts on."""
    out: list[Relation] = []
    for before, after in itertools.pairwise(moves):
        if before.size <= 0 or before.hours <= 0:
            continue
        ratio = after.size / before.size
        out.append(
            Relation(
                ratio=ratio,
                stretch=after.hours / before.hours,
                turn=1 if after.direction != before.direction else -1,
                log_ratio=math.log(ratio) if ratio > 0 else 0.0,
                confirmed=after.confirmed,
            )
        )
    return out


def summarise(moves: Sequence[Displacement]) -> dict[str, float]:
    """A few numbers about a sequence, for comparing series at a glance."""
    if len(moves) < 3:
        return {}
    sizes = [m.size for m in moves]
    hours = [m.hours for m in moves]
    pairs = relations(moves)
    alternating = statistics.fmean(1.0 if r.turn > 0 else 0.0 for r in pairs) if pairs else 0.0
    return {
        "count": float(len(moves)),
        "median_size": statistics.median(sizes),
        "median_hours": statistics.median(hours),
        # **The alternation rate is a check on the detector, not a finding.**
        # A sequence of swings should alternate nearly always; a rate far
        # below one means the pivot reach is too short and the detector is
        # firing inside single structures.
        "alternating": alternating,
        "median_ratio": statistics.median([r.ratio for r in pairs]) if pairs else 0.0,
        "log_ratio_sd": statistics.pstdev([r.log_ratio for r in pairs]) if len(pairs) > 1 else 0.0,
    }
