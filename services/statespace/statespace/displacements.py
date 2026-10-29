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


#: What kind of reversal a node is.
PEAK = 1
TROUGH = -1


@dataclass(frozen=True, slots=True)
class Node:
    """One confirmed reversal: a peak or a trough, at a level.

    `sequence` computed these internally from the start and threw the kind and
    the level away, keeping only the signed move between consecutive ones.
    That loses the two things the classical structural reading is built from:
    **which** kind a node is, and **where** it sat.

    The distinction matters because a peak-to-peak distance is a different
    quantity from a swing size. A swing size is always positive - it is how
    far price travelled - whereas the gap from one peak to the next is
    **signed**, and its sign is the whole content: higher highs are an
    uptrend, lower highs are not. Averaging the two together, which is what
    using `Displacement.size` alone does, discards exactly the part that says
    which way.
    """

    #: When the reversal happened, and when it became knowable.
    at: float
    confirmed: float
    #: The extreme itself - the high at a peak, the low at a trough.
    level: float
    #: `PEAK` or `TROUGH`.
    kind: int
    #: Where in the bar series it sat, for callers that need to align features.
    index: int

    @property
    def peak(self) -> bool:
        return self.kind == PEAK


def nodes(
    times: Sequence[float],
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    span: int,
) -> list[Node]:
    """Confirmed reversals as typed nodes, alternating peak and trough.

    The alternation is enforced here rather than downstream: two peaks in a
    row with no trough between them is the detector firing twice on one
    structure, and **the later of the two is kept** because it is the more
    extreme one by construction - the first could not have been a peak if the
    second exceeded it within the reach. Dropping the earlier keeps the
    sequence a sequence of extremes rather than of threshold crossings.

    `span` is the confirmation reach in bars. It is a bar count and that is
    correct: the reach is how many bars must pass before an extreme is known,
    which is a property of the detector rather than a duration.
    """
    n = min(len(times), len(closes), len(highs), len(lows))
    if n < 2 * span + 2 or span < 1:
        return []

    found: list[Node] = []
    for k in range(span, n - span):
        window = range(k - span, k + span + 1)
        kind = 0
        level = 0.0
        if all(highs[j] < highs[k] for j in window if j != k):
            kind, level = PEAK, float(highs[k])
        elif all(lows[j] > lows[k] for j in window if j != k):
            kind, level = TROUGH, float(lows[k])
        if not kind:
            continue
        made = Node(
            at=float(times[k]),
            confirmed=float(times[min(k + span, n - 1)]),
            level=level,
            kind=kind,
            index=k,
        )
        if found and found[-1].kind == kind:
            # Same kind twice: keep whichever is the more extreme, which is
            # the one the structure is actually built on.
            better = made.level > found[-1].level if kind == PEAK else made.level < found[-1].level
            if better:
                found[-1] = made
            continue
        found.append(made)
    return found


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
    if unit <= 0:
        return []
    found = nodes(times, closes, highs, lows, span=span)

    out: list[Displacement] = []
    for a, b in itertools.pairwise(found):
        gap = (b.at - a.at) / HOUR
        if gap <= 0:
            continue
        out.append(
            Displacement(
                ended=b.at,
                confirmed=b.confirmed,
                size=abs(b.level - a.level) / unit,
                hours=gap,
                direction=1 if b.level > a.level else -1,
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


#: The four structural labels. `HIGHER_HIGH` and `HIGHER_LOW` together are the
#: textbook uptrend; `LOWER_HIGH` and `LOWER_LOW` the downtrend. The mixed
#: pairs are the interesting ones, because that is where a trend is changing
#: its mind.
HIGHER_HIGH = "higher high"
LOWER_HIGH = "lower high"
HIGHER_LOW = "higher low"
LOWER_LOW = "lower low"


@dataclass(frozen=True, slots=True)
class Step:
    """The gap from one node to the **next of the same kind**.

    Peak to peak, or trough to trough. This is the quantity the user's
    question is about and it is not a swing size:

    * a **swing size** is `|level(b) - level(a)|` between *opposite* nodes,
      always positive, and says how far price travelled;
    * a **step** is `level(b) - level(a)` between *like* nodes, **signed**,
      and its sign is the structural reading. Higher highs are an uptrend.

    The displacement sequence this module started with keeps only the first,
    so a trend and a range with the same swing sizes look identical in it.
    That is almost certainly why the ratio work came back null: the ratios
    were computed on a quantity with the direction already removed.
    """

    #: When this node happened and when the step became knowable.
    at: float
    confirmed: float
    #: Signed, in volatility units. Positive means the extreme moved up.
    rise: float
    #: Hours from the previous like node. **Peak to peak is a cycle length**,
    #: directly comparable to `oscillator.period` and to the half-lives
    #: `spectrum.py` reads off a member's eigenvalues.
    hours: float
    #: `PEAK` or `TROUGH`: which sequence this step belongs to.
    kind: int
    #: One of the four structural labels.
    label: str

    @property
    def speed(self) -> float:
        """Signed volatility units per hour: the extreme's own drift."""
        return self.rise / self.hours if self.hours > 0 else 0.0


def steps(found: Sequence[Node], *, unit: float, kind: int | None = None) -> list[Step]:
    """The like-node distance sequence: peak to peak, trough to trough, or both.

    `kind` restricts to `PEAK` or `TROUGH`; `None` interleaves the two in time,
    which is the form a feature wants because it updates on every confirmed
    node rather than on every other one.

    Note the clock. Consecutive peaks are **two** swings apart, so a
    peak-to-peak step spans a full up-and-down cycle. Its duration is
    therefore a period and not a swing length, and the two differ by roughly a
    factor of two - which is exactly the sort of thing that makes a feature
    mean different things at different timeframes if it is not stated.
    """
    if unit <= 0:
        return []
    out: list[Step] = []
    for want in (PEAK, TROUGH) if kind is None else (kind,):
        same = [node for node in found if node.kind == want]
        for a, b in itertools.pairwise(same):
            gap = (b.at - a.at) / HOUR
            if gap <= 0:
                continue
            rise = (b.level - a.level) / unit
            if want == PEAK:
                label = HIGHER_HIGH if rise > 0 else LOWER_HIGH
            else:
                label = HIGHER_LOW if rise > 0 else LOWER_LOW
            out.append(
                Step(
                    at=b.at,
                    confirmed=b.confirmed,
                    rise=rise,
                    hours=gap,
                    kind=want,
                    label=label,
                )
            )
    out.sort(key=lambda step: step.confirmed)
    return out


def structure(found: Sequence[Node], *, unit: float) -> dict[str, float]:
    """The structural reading over a whole series, with its own null beside it.

    Returns the share of each label, the agreement between the two sequences -
    how often a higher high is accompanied by a higher low, which is the
    textbook definition of a trend rather than a drift - and the median
    peak-to-peak period in hours.

    **`agreement` is the number worth looking at and `drift` is its null.** A
    series with any upward drift produces higher highs *and* higher lows
    simply because everything is rising, so a high agreement on a drifting
    series says nothing. The share of upward steps is reported beside it, and
    agreement should be read against what two independent coin flips at that
    rate would give: `p^2 + (1-p)^2`.
    """
    moves = steps(found, unit=unit)
    if len(moves) < 6:
        return {}

    peaks = [m for m in moves if m.kind == PEAK]
    troughs = [m for m in moves if m.kind == TROUGH]
    if not peaks or not troughs:
        return {}

    up = statistics.fmean(1.0 if m.rise > 0 else 0.0 for m in moves)

    # Agreement: for each peak step, the sign of the nearest trough step that
    # was confirmed before it. Confirmed, not merely earlier, so the reading
    # is one a live feature could take.
    agreed: list[float] = []
    for peak in peaks:
        earlier = [t for t in troughs if t.confirmed <= peak.confirmed]
        if not earlier:
            continue
        agreed.append(1.0 if (earlier[-1].rise > 0) == (peak.rise > 0) else 0.0)

    return {
        "nodes": float(len(found)),
        "steps": float(len(moves)),
        "higher_highs": statistics.fmean(1.0 if m.rise > 0 else 0.0 for m in peaks),
        "higher_lows": statistics.fmean(1.0 if m.rise > 0 else 0.0 for m in troughs),
        "up_share": up,
        "agreement": statistics.fmean(agreed) if agreed else float("nan"),
        # What agreement would be if the two sequences were independent at the
        # same up-share. Printed beside it so the comparison is a number.
        "drift": up * up + (1.0 - up) * (1.0 - up),
        "period_hours": statistics.median([m.hours for m in peaks]),
        "swing_hours": statistics.median([abs(m.hours) for m in moves]) / 2.0,
    }
