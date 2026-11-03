"""Grouping candidate prices into levels: clustering, nearest neighbours, and
what a factor decomposition can and cannot do here.

A level is a price many participants compute the same way, so deciding *which
touches are one level* is a clustering problem on the price axis and nothing
else. `levels.Levels._merge` already does a version of it, and this module
exists because that version has a defect worth naming.

## The defect, measured

`_merge` walks levels in price order and folds a neighbour into the running
one when they are closer than `merge_vol`, keeping whichever has more touches.
Keeping the better-evidenced centre is right, but it **moves the anchor**, so
the next comparison is against the new price - and a run of touches each
inside the gap collapses without limit.

Nine levels 0.30 units apart, `merge_vol` 0.35, each later one carrying more
touches than the last: all nine become **one** level spanning **2.40 units,
6.9 times the gap**, centred at 102.4 - the end of the run, a price only one
of the nine touches sat at. With equal touch counts the anchor holds and the
same input gives five levels, so the collapse depends on the touch counts
rather than on the prices. The reinforcement case, where a later touch has
seen more, is the common one live.

That is single-linkage chaining. `cluster` here is **complete linkage**: a
group is admitted only while its whole span stays inside the width, so the
span is bounded by construction and the answer does not depend on the order
the prices arrive in or on their weights.

## What is a cluster and what is a mode

Two questions that look alike and are not:

`cluster` answers *which of these touches are the same level* - a partition,
bounded span, every input in exactly one group. That is the merge question.

`modes` answers *where is the agreement* - the peaks of the weighted density.
A mode is not a partition: a broad shelf of touches has one mode and a bounded
span would cut it into three. This is the estimator for watchedness, which is
what `a-magnet-is-a-shared-reference` says to measure: liquidity rests where
many participants compute the same price, so the quantity of interest is how
many *independent* turns agree, not how tightly a group fits.

**The confound to carry, before either is read as a signal.** A dense patch of
touches is partly an occupancy artefact: price produces more turns at prices
where it spent more time, and it spent more time where it ranged. So a density
peak is evidence about where price has been as much as about agreement. Any
claim built on `modes` needs an occupancy-matched control - the same count of
turns placed by time spent - and the level-shield study is the cautionary
case: its single most impressive cell was reproduced by a walk with the same
bar geometry.

## On a factor decomposition, since it gets asked

**PCA cannot find a level.** A level is a location on one axis, and a
one-dimensional cloud has exactly one principal component, which is that axis.
"The first component of a price distribution" is the price axis restated, so
there is no decomposition to do and nothing to rank.

What a decomposition *can* do is change the series the levels are found in.
`common` takes a panel of returns and returns the leading component, which on
FX is the dollar move; `residual` removes it and rebuilds a path. A level in
the residual is a price specific to that instrument rather than a reflection
of a move its whole panel made - a different and testable object, and the one
use here that is not a category error. `currency-triangles-are-the-positive-
control` is the check: a screen over the residuals that misses the triangles
is broken.

The other thing PCA is often reached for - compressing a level's attributes
(touch count, age, push, wick share) into a component or two - is predicted
null by this desk's own record and is deliberately not built. It is a weighted
sum, `only-the-sign-survives-into-a-weighted-sum` holds that activation, scale
and per-term offset are rank identities within one, and `fit-on-the-edge-not-
the-raw-score` measured fitted weights beating hand-tuned ones on AUC 0.604
against 0.556 while **losing on edge, +0.002 against +0.019**. A component is
a fitted weighting chosen by variance rather than by edge, which is the worse
of the two objectives.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

#: How far apart two touches may sit and still be one level, in volatility
#: units. `levels.MERGE_VOL`, repeated rather than imported so this module
#: stays a leaf that `levels` can import.
WIDTH_VOL = 0.35

#: Default neighbours for `crowding`. Three, because two gives a single gap
#: and no notion of a local density at all, and the book is capped near two
#: dozen so a large k would read the whole book rather than the neighbourhood.
NEIGHBOURS = 3


class Anchor(StrEnum):
    """Which price in a group is *the* level.

    **A floor is where price stopped, not the average of where it stopped.** A
    support cluster's lowest touch is the price that actually held; the
    weighted mean sits inside the body of touches, which is a price price has
    already traded through. Put a stop below the mean of a support cluster and
    it is inside the cluster - the level has to be broken before the stop is
    even reached, which is the opposite of what the stop is for.

    The trade-off is robustness, and it runs the other way. An extreme is one
    touch, so a single spike moves the level and nothing averages it out,
    where `CENTRE` is an estimate over the whole group. So the extreme is the
    better *definition* and the noisier *estimate*, and which to use depends
    on whether the number is being placed against (an edge) or compared
    (a centre).
    """

    #: The weighted mean. The best-evidenced single price for the group.
    CENTRE = "centre"
    #: The lowest touch - a support level, the price that held from above.
    FLOOR = "floor"
    #: The highest touch - a resistance level, the price that held from below.
    CEILING = "ceiling"
    #: `FLOOR` for a support, `CEILING` for a resistance, by **the level's
    #: own formed side** - `levels.Level.side`, +1 resistance and -1 support,
    #: the pivot side that made it rather than where it sits relative to price
    #: now. Stable, because the latter flips as price moves.
    #:
    #: **Not the anchor for placing a stop**, and measured: `stop-anchor.md`
    #: found this hands a long the group's *ceiling* - a price above the entry
    #: - on 36 to 49% of anchors, because which pivot formed a level says
    #: nothing about which way the trade faces. Use `PROTECTIVE` there.
    SIDED = "sided"
    #: The edge a stop belongs beyond, by **the trade's** side: the floor for
    #: a long, the ceiling for a short, so the level has to break before the
    #: stop is reached.
    #:
    #: Separate from `SIDED` rather than a second meaning for its argument,
    #: because the two differ on a third to a half of anchors and reading one
    #: as the other returns a price on the wrong side of the entry - which
    #: prices an order rather than raising.
    PROTECTIVE = "protective"


@dataclass(frozen=True, slots=True)
class Group:
    """One cluster of candidate prices.

    `centre` is the weighted mean rather than the midpoint: a level's price is
    where the evidence is, and an unweighted midpoint moves with the
    stragglers at the edge of the group. `price` is how to ask for an edge
    instead - see `Anchor`.
    """

    centre: float
    low: float
    high: float
    weight: float
    members: int

    @property
    def span(self) -> float:
        return self.high - self.low

    def price(
        self,
        anchor: Anchor | str = Anchor.CENTRE,
        *,
        side: int = 0,
        trade: int = 0,
    ) -> float:
        """The group's level price, under `anchor`.

        **Two different sides, and they are separate arguments because
        confusing them prices an order rather than raising.** `side` is the
        level's own formed side and is read only by `SIDED`; `trade` is the
        trade's side and is read only by `PROTECTIVE`. `stop-anchor.md`
        measured the two disagreeing on 36 to 49% of anchors, so one argument
        serving both would hand a long a price above its entry on a third of
        them.

        A `SIDED` level with no formed side falls back to the centre: an
        unformed side is an absence, and picking the floor for it would make
        every sideless level a support. A `PROTECTIVE` anchor with no trade
        side **raises**, because there is no neutral answer to "which edge
        does this stop go beyond" and returning the centre would put the stop
        inside the cluster, which is the failure the anchor exists to avoid.
        """
        try:
            chosen = Anchor(anchor)
        except ValueError as exc:
            raise ValueError(
                f"{anchor!r} is not an anchor. Known: {', '.join(a.value for a in Anchor)}."
            ) from exc
        if chosen is Anchor.FLOOR:
            return self.low
        if chosen is Anchor.CEILING:
            return self.high
        if chosen is Anchor.PROTECTIVE:
            if trade == 0:
                raise ValueError(
                    "Anchor.PROTECTIVE needs the trade's side - `trade=+1` for a "
                    "long, so the stop goes beyond the floor, or `trade=-1` for a "
                    "short. There is no neutral edge, and the centre would put the "
                    "stop inside the cluster."
                )
            return self.low if trade > 0 else self.high
        if chosen is Anchor.SIDED:
            if side < 0:
                return self.low
            if side > 0:
                return self.high
        return self.centre


def _weights(prices: Sequence[float], weights: Sequence[float] | None) -> list[float]:
    if weights is None:
        return [1.0] * len(prices)
    if len(weights) != len(prices):
        raise ValueError(
            f"{len(weights)} weights for {len(prices)} prices - a weight paired "
            f"with the wrong price moves a level towards the wrong evidence"
        )
    return [max(0.0, float(w)) for w in weights]


def cluster(
    prices: Sequence[float],
    width: float,
    *,
    weights: Sequence[float] | None = None,
) -> list[Group]:
    """Partition `prices` into groups no wider than `width`.

    **Complete linkage, so a group's span is bounded and the result does not
    depend on the order or the weights.** Single linkage - fold a neighbour if
    it is within the width of the running centre - is what chains, and the
    chaining is not hypothetical: see the module docstring for nine touches
    becoming one level 6.9 times the gap wide.

    A greedy left-to-right pass over sorted prices is optimal for this
    constraint on a line: starting a new group only when forced is never worse
    than starting one early, because any price that fits with the current
    group's lowest member fits with every member between them.

    Groups come back in price order. A zero or negative width gives one group
    per price, which is the honest reading of "nothing is close enough to
    anything".
    """
    if not prices:
        return []
    found = _weights(prices, weights)
    order = sorted(range(len(prices)), key=lambda i: prices[i])

    out: list[Group] = []
    start = 0
    for position in range(len(order) + 1):
        if position < len(order):
            here = prices[order[position]]
            anchor = prices[order[start]]
            # The first price of a group always joins it - without that a
            # zero width emits an empty group before every real one. Closed on
            # the width, so two prices exactly `width` apart are one level,
            # which is the convention `_merge` uses with `<=`.
            if position == start or (width > 0.0 and here - anchor <= width):
                continue
        out.append(_group(prices, found, order[start:position]))
        start = position
    return out


def _group(prices: Sequence[float], weights: Sequence[float], members: Sequence[int]) -> Group:
    total = sum(weights[i] for i in members)
    picked = [prices[i] for i in members]
    # An all-zero-weight group still has a position; the unweighted mean is
    # the only centre available and is better than refusing the group.
    centre = (
        sum(prices[i] * weights[i] for i in members) / total
        if total > 0.0
        else sum(picked) / len(picked)
    )
    return Group(
        centre=centre,
        low=min(picked),
        high=max(picked),
        weight=total,
        members=len(members),
    )


def modes(
    prices: Sequence[float],
    bandwidth: float,
    *,
    weights: Sequence[float] | None = None,
    steps: int = 64,
) -> list[Group]:
    """The peaks of the weighted density of `prices`, in price order.

    Mean shift with a Gaussian kernel: every price is walked uphill until it
    stops moving, and prices arriving at the same place are one mode. Unlike
    `cluster` this is **not a partition with a bounded span** - a broad shelf
    of agreement is one mode where a width constraint would cut it into
    several, which is the point. A mode says *where* the agreement is; the
    group's own span says how broad it is, and a broad one is weaker evidence
    of a shared reference than a tight one at the same weight.

    `bandwidth` is the kernel's sigma in price units and sets what counts as
    the same place. A Gaussian rather than a box kernel because a box gives a
    piecewise-constant density whose modes sit wherever the bins fell.
    """
    if not prices or bandwidth <= 0.0:
        return []
    found = _weights(prices, weights)
    if sum(found) <= 0.0:
        return []

    settled = [_uphill(float(p), prices, found, bandwidth, steps) for p in prices]
    # Two walks that stop within a tenth of a bandwidth are the same peak;
    # a mean shift converges towards a mode rather than onto it exactly.
    return cluster(settled, bandwidth * 0.1, weights=found)


def _uphill(
    start: float,
    prices: Sequence[float],
    weights: Sequence[float],
    bandwidth: float,
    steps: int,
) -> float:
    """One mean-shift walk, from `start` to the nearest density peak."""
    here = start
    for _ in range(max(1, steps)):
        top = 0.0
        bottom = 0.0
        for price, weight in zip(prices, weights, strict=True):
            if weight <= 0.0:
                continue
            gap = (price - here) / bandwidth
            if abs(gap) > 6.0:  # the kernel is numerically zero past six sigma
                continue
            pull = weight * math.exp(-0.5 * gap * gap)
            top += pull * price
            bottom += pull
        if bottom <= 0.0:
            return here
        moved = top / bottom
        if abs(moved - here) < bandwidth * 1e-4:
            return moved
        here = moved
    return here


def nearest(
    price: float,
    candidates: Sequence[float],
    k: int = NEIGHBOURS,
) -> list[tuple[float, float]]:
    """The `k` candidates closest to `price`, as `(distance, price)` pairs.

    Sorted by distance, then by price so a tie is resolved the same way every
    time - a level above and one below at the same distance is the common tie
    and an unstable order there would make a "nearest level" feature flicker
    between two prices without either moving.
    """
    if not candidates or k <= 0:
        return []
    found = sorted(((abs(c - price), c) for c in candidates), key=lambda pair: (pair[0], pair[1]))
    return found[: int(k)]


def crowding(
    price: float,
    candidates: Sequence[float],
    k: int = NEIGHBOURS,
    *,
    unit: float = 1.0,
) -> float:
    """How tightly `k` neighbours cluster around `price`, in inverse units.

    The reciprocal of the mean distance to the `k` nearest, so a price with
    several turns right beside it reads high and an isolated one reads low.
    This is a **watchedness** estimator and inherits the occupancy confound in
    the module docstring: it is large where price has spent time, whether or
    not anybody is computing that price.

    Zero when there is nothing to measure against - no candidates, or a
    non-positive unit - rather than an infinity, so a caller comparing feeds
    does not have to special-case an empty book.
    """
    if unit <= 0.0:
        return 0.0
    found = nearest(price, candidates, k)
    if not found:
        return 0.0
    mean = sum(distance for distance, _ in found) / len(found) / unit
    # A neighbour at the price itself gives a zero mean. Capped at the unit
    # rather than returned as an infinity: "closer than a hundredth of a
    # volatility unit" and "exactly here" are the same statement about a
    # level, and one of them is not a larger number.
    return 1.0 / max(mean, 1e-2)


# ------------------------------------------------------------ the factor path


def _project(
    weights: Sequence[float],
    rows: Sequence[Sequence[float]],
    length: int,
) -> list[float]:
    """The panel projected onto one vector: a score per time step."""
    return [sum(w * row[t] for w, row in zip(weights, rows, strict=True)) for t in range(length)]


def common(panel: Sequence[Sequence[float]]) -> list[float]:
    """The leading principal component of a panel of return series.

    `panel` is one row per instrument, all the same length, aligned on time by
    the caller - **aligned, then differenced, never the other way round**:
    `difference-before-aligning` records that aligning returns on common
    timestamps and differencing afterwards turns every session gap into a fake
    one-bar return.

    Returned as the component's time series, scaled so its own standard
    deviation is one, which is what `residual` regresses against. On FX this
    is the dollar move and typically carries the majority of the variance.

    Computed by power iteration on the covariance rather than by a full
    eigendecomposition, because only the leading vector is wanted and this
    keeps the module free of a numerical dependency.
    """
    rows = [list(map(float, row)) for row in panel if len(row) > 1]
    if len(rows) < 2:
        return []
    length = len(rows[0])
    if any(len(row) != length for row in rows):
        raise ValueError(
            "the panel's rows are different lengths - align the series before "
            "differencing them, or every session gap becomes a one-bar return"
        )

    centred = [[v - sum(row) / length for v in row] for row in rows]
    weights = [1.0 / math.sqrt(len(centred))] * len(centred)
    for _ in range(64):
        # One power-iteration step, as covariance-times-vector without ever
        # forming the covariance: project the panel onto the current vector,
        # then project the result back onto each series.
        scores = _project(weights, centred, length)
        moved = [sum(row[t] * scores[t] for t in range(length)) for row in centred]
        size = math.sqrt(sum(v * v for v in moved))
        if size <= 0.0:
            return []
        nxt = [v / size for v in moved]
        if sum(abs(a - b) for a, b in zip(nxt, weights, strict=True)) < 1e-10:
            weights = nxt
            break
        weights = nxt

    scores = _project(weights, centred, length)
    mean = sum(scores) / length
    sd = math.sqrt(sum((s - mean) ** 2 for s in scores) / max(1, length - 1))
    return [(s - mean) / sd for s in scores] if sd > 0.0 else []


def residual(
    series: Sequence[float],
    factor: Sequence[float],
    *,
    start: float = 0.0,
) -> list[float]:
    """`series` with the `factor` regressed out, rebuilt as a path.

    `series` is returns and `factor` is what `common` produced; the result is a
    cumulative path starting at `start`, which is what a level book wants to
    be fed. **A level found here is specific to this instrument** rather than a
    price its whole panel passed through together.

    The beta is a plain least squares fit over the whole series, which is a
    look-ahead and acceptable only for an exploratory read. Anything causal
    needs a trailing beta, and `never-test-cointegration-on-a-live-ratio` is
    the warning: an adaptively fitted ratio gave a null t of -29 from noise
    where a training-half fit put it at -3.46.
    """
    if len(series) != len(factor) or not series:
        raise ValueError(
            f"{len(series)} returns against {len(factor)} factor readings - a "
            f"residual is only defined where both are known for the same bar"
        )
    bottom = sum(f * f for f in factor)
    beta = sum(s * f for s, f in zip(series, factor, strict=True)) / bottom if bottom > 0.0 else 0.0
    path = [start]
    for value, driver in zip(series, factor, strict=True):
        path.append(path[-1] + value - beta * driver)
    return path[1:]
