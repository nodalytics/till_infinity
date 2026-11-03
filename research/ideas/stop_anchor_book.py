"""A stop anchored at a level's floor, against one placed by volatility alone.

`strategies/surprise.py` computes `risk = stop_vol * unit` and never reads the
level book. `indicators/grouping.py` added `Anchor.FLOOR`/`CEILING`/`SIDED` and
`Group.price(anchor, side=)` for the opposite rule - put the stop beyond the
nearest cluster's *extreme*, so the level has to break before the stop is
reached - and that primitive has **no caller anywhere**. This decides whether
it should.

## The claim, and the two arms that can refute it without a P&L

The argument is that a support cluster's weighted mean sits inside the body of
touches, so a stop below the mean is still above the lowest touch. Four touches
at 99.80/99.95/100.00/100.02 weighted 1,3,4,2 give a centre of 99.969 against a
floor of 99.800.

That is arithmetic and is not in dispute. What is in dispute is whether the
distinction buys anything, and there are two ways it can look like it does
without carrying any level information:

* **width.** A floor is further away than a centre by the group's span, so a
  floor-anchored stop is simply a *wider* stop. On a time exit a wider stop is
  hit less often for purely geometric reasons - `a-return-rate-is-geometry`,
  where a distance-matched placebo matched an 82% return rate on every class.
  So `matched` permutes the floor arm's own distances across anchors: the same
  width distribution, no pairing with any level. **`floor` against `matched` is
  what decides this study.**
* **consulting a book at all.** If `floor` beats `vol` and `centre` beats `vol`
  by the same amount, the gain is from reading levels, not from the anchor, and
  the anchor is not the finding. `centre` is the same group under
  `Anchor.CENTRE`, so the two arms differ in one call argument.

## Why this is entry-agnostic, and what that costs

Every bar past warm-up is an anchor, on both sides, with no signal. The
recorded catalogue's own rule gives 75 trades over six feeds at a per-trade sd
of 2.4R, so its standard error is 0.20-0.95R and it cannot see an effect
smaller than the whole standing claim for the rule (`smc-bos-reconcile.md`).
A stop rule is not a function of the entry signal, so dropping the signal buys
a 19.2-19.9 year daily history on eight feeds and tens of thousands of anchors
on the same geometry - and `stop_anchor.py` runs the signal-conditioned version
beside it, net of the modelled spread, as the mechanics check.

**Nothing here is priced.** These are stop-out rates and R measured against the
stop's own distance, so the figures are **gross**. Only six feeds have a
measurable spread (`node/corpus.py`) and no spread is invented for the rest.

## What is reported, and why not the raw mean

Two statistics per cell, both per instrument and never only pooled
(`pooled-medians-invert-subgroups`):

* **P(stopped)** before the clock. A level that shields shows a lower stop-out
  rate at the *same* distance than a stop that is merely that far away.
* **mean R**, which decides, with the stop filled at the stop - so a stop-out
  is exactly -1R. Overshoot past the stop is real (+0.363R median on spx500,
  `smc-bos-reconcile.md`) and **grows with the distance to the barrier**, so
  modelling it here would hand the wide-stop arm a width-dependent debit on top
  of a width-dependent advantage. It is left out and the comparison is made
  against the same race on matched surrogates instead, never against a closed
  form: `level-shield.md` measured a bar-extreme race departing from
  1/(1+N) by -0.25 to +0.12R, monotone in (stop - target), with every surrogate
  doing it three to seven times harder.

Both are reported **within strata of the stop's own width in volatility
units** as well as pooled, because the width is the confound and standardising
on it is the direct control. The gap between the stratified and the pooled
contrast is itself the size of the geometric advantage.

## The nulls

Every arm runs through the same book, the same clustering and the same race on
each of three surrogate series as well as on the real one
(`null-structure-claims-on-the-same-detector`). The arms are
`level_shield.py`'s, reused rather than rewritten so the two studies cannot
disagree about what an arm is: `garch-bars` keeps clustering, `walk-geometry`
keeps bar wickiness and the step distribution, `bar-shuffle` keeps neither.

`garch-bars` is not optional here. A level below price is a price price has
recently turned at, so "a level is 2 units away" is a statement about the
recent path, and volatility clustering is the mechanical route by which that
predicts a smaller forward excursion. An arm without clustering cannot judge
the claim.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np

from till_infinity.indicators.grouping import WIDTH_VOL, Anchor, cluster
from till_infinity.indicators.levels import FORGET_BARS, KEEP
from till_infinity.indicators.trend import REACH

#: Bars each side of a pivot, and the cluster width in volatility units. The
#: production book's: `trend.REACH` 3 and `grouping.WIDTH_VOL` 0.35, which is
#: `levels.MERGE_VOL`. Taken rather than chosen so this measures the book a
#: strategy would read.
BOOK_REACH = REACH
BOOK_WIDTH = WIDTH_VOL

#: Volatility units the stop clears the anchor by. Swept, not chosen -
#: `sweep-thresholds-on-the-mean-not-z`, and the whole grid is reported.
BUFFERS = (0.0, 0.25, 0.5, 1.0)

#: Fixed stop distances for the incumbent arm, in volatility units.
#: `SurpriseProfile.stop_vol` is 2.0, which is the middle of this grid.
WIDTHS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)

#: Volatility units a level has to clear before the `beyond` book will anchor
#: on it. `SurpriseProfile.stop_vol`, so the `beyond` arms and `vol-2` are
#: comparable widths rather than a 4x apart.
#:
#: **This exists because the nearest cluster is not a wide stop, it is a very
#: tight one.** Measured on 19.2 years of daily eurusd: the nearest group below
#: the close has a median of 2 touches, a span of 0.142 volatility units, and
#: its floor sits 0.427 units below the close against the incumbent's 2.0. So
#: the premise that a floor-anchored stop wins by being wider is false in the
#: opposite direction, and an arm anchored on the nearest level is mostly a
#: statement about `cost_px / risk` - which the stop sets and no exit rule can
#: repair.
MIN_VOL = 2.0

#: Width strata in volatility units, as bin edges. Fixed rather than per-arm
#: quantiles, because a stratum has to mean the same distance in every arm for
#: the standardised contrast to compare like with like.
#:
#: **Quarter-unit bins where the arms live, and that is not cosmetic.** On the
#: first version's half-unit grid the bin [2.0, 3.0) held both `vol-2` at
#: exactly 2.000 and `beyond-floor+0.25` at 2.560, and the "stratified"
#: stop-out contrast between them still read -0.11 - which is width leaking
#: through a bin, not a level. A fixed-distance arm occupies exactly **one**
#: bin, so where two arms barely share one the standardised contrast is
#: reported with the share of weight it was computed on and must not be read as
#: a matched comparison at all.
EDGES = (
    0.0,
    0.25,
    0.5,
    0.75,
    1.0,
    1.25,
    1.5,
    1.75,
    2.0,
    2.25,
    2.5,
    2.75,
    3.0,
    3.25,
    3.5,
    4.0,
    5.0,
    6.0,
    8.0,
)

#: Anchors whose level-derived stop is wider than this are dropped from every
#: arm, so all arms run on one anchor set. A stop 8 volatility units away over
#: a 20-48 bar horizon is almost never reached, and such a cell measures the
#: cap rather than the anchor. The drop rate is reported.
MAX_VOL = 8.0

#: Draws for the permuted-distance placebo. Eight, because the quantity read
#: off it is a mean over anchors and its own spread across draws is reported -
#: `the-placebo-arm-selects-the-null` is why the arm is drawn repeatedly rather
#: than once.
PLACEBO_DRAWS = 8


@dataclass(frozen=True, slots=True)
class Arm:
    """One stop rule. `kind` is what it reads; `name` is how it is reported.

    An arm is a stop *distance* and nothing else: the entry, the side, the
    horizon, the bar path and the clock are shared, so a difference between two
    arms is a difference between two stop distances and cannot be anything
    else.

    **`formed` is not raced and that is deliberate.** `Anchor.SIDED` reads the
    level's own formed side, so it names the group's *ceiling* whenever the
    group below a long was built mostly from pivot highs - a price above the
    entry, which is not a stop at all. Racing it would mean either dropping
    those anchors, which biases the shared anchor set towards supports, or
    folding them in as a tight stop, which is two rules under one name. It is
    reported as a disagreement **rate** instead, by `_formed_agrees`.
    """

    name: str
    #: `vol`, `floor`, `centre`, `matched`, `mirror`, or `formed`.
    kind: str
    #: Volatility units past the anchor, for the level-reading arms.
    buffer: float = 0.0
    #: Fixed distance in volatility units, for `vol`.
    width: float = 0.0
    #: Which book to read: `near` the nearest cluster, `beyond` the nearest
    #: clearing `MIN_VOL`. Ignored by `vol`.
    pick: str = "near"


def arms(buffers=BUFFERS, widths=WIDTHS) -> list[Arm]:
    """The grid, in reporting order. `vol` first because it is the incumbent.

    Both books are carried for every level-reading arm, so a reader can see
    which of the two readings of the claim a number belongs to without
    inferring it from the size.
    """
    out = [Arm(f"vol-{w:g}", "vol", width=w) for w in widths]
    for pick in ("near", "beyond"):
        for b in buffers:
            for kind in ("floor", "centre", "matched", "mirror"):
                out.append(Arm(f"{pick}-{kind}+{b:g}", kind, buffer=b, pick=pick))
    return out


# ───────────────────────────── the causal book ─────────────────────────────


@dataclass(frozen=True, slots=True)
class Nearest:
    """The cluster nearest the close on one side, as a stop rule reads it.

    One group is chosen per side by its **centre**, before any anchor is read,
    so the `floor` and `centre` arms read the same group and differ in nothing
    but the argument to `Group.price`. Choosing the group per anchor would let
    the two arms pick different levels and the contrast would stop being about
    the anchor at all.
    """

    low: float
    centre: float
    high: float
    #: The net pivot side of its touches: +1 more highs, -1 more lows, 0 a tie.
    side: int
    members: int


class Walker:
    """The cluster book, fed one closed bar at a time.

    **The one implementation, driven by both halves of this study** - the
    vectorised panel through `book_path` and the Nautilus engine through
    `stop_anchor.Anchored`. Two copies of a causal book is how the measurement
    and the deployment come to disagree, which is the defect this repo is
    organised around.

    `indicators/levels.Levels` is deliberately not used, and the reason is a
    finding rather than a preference: it keeps a Kalman posterior per level and
    **discards the touch prices**, so no floor or ceiling can be recovered from
    it. Wiring `Anchor.FLOOR` into production would have to change that first.

    Causal by construction: a pivot at bar `j` is admitted at bar `j + reach`,
    which is when `trend.pivots` confirms it, and nothing reads a bar past the
    one just handed over.
    """

    __slots__ = ("_bars", "_pivots", "_seen", "forget", "keep", "reach", "unit", "unit_a", "width")

    def __init__(
        self,
        *,
        reach: int = BOOK_REACH,
        width_vol: float = BOOK_WIDTH,
        keep: int = KEEP,
        forget: int = FORGET_BARS,
        unit_span: int = 48,
    ) -> None:
        self.reach = int(reach)
        self.width = float(width_vol)
        self.keep = int(keep)
        self.forget = int(forget)
        self.unit_a = 2.0 / (max(1, int(unit_span)) + 1.0)
        self.unit = 0.0
        self._bars: list[tuple[float, float]] = []
        self._pivots: list[tuple[int, float, int]] = []
        self._seen = 0

    def update(self, high: float, low: float) -> list[tuple[int, float, int]]:
        """One closed bar: advance the unit, confirm any pivot, prune the book.

        Returns the pivots this bar confirmed, as `(bar, price, side)`, which
        is what the sanity check compares against `trend.pivots` - reading them
        off `_pivots` instead is wrong, because the same call prunes the front
        of that list and the indices shift under the reader.

        The unit is a causal EWMA of the bar **range** and includes this bar's,
        which has closed. The range and not a close-to-close sigma because
        `drive-q-from-the-range` is the measured choice: the range-vs-close
        estimator ratio reads 0.648 within strata on FX and 0.667 on 371 of 392
        equities.
        """
        span = max(0.0, float(high) - float(low))
        self.unit = (
            span if self.unit <= 0.0 else (1.0 - self.unit_a) * self.unit + self.unit_a * span
        )
        self._seen += 1
        self._bars.append((float(high), float(low)))
        width = 2 * self.reach + 1
        if len(self._bars) > width:
            del self._bars[0]
        found: list[tuple[int, float, int]] = []
        if len(self._bars) == width:
            # The middle bar of the window is `reach` bars old, which is
            # exactly when `trend.pivots` confirms it. Ties go to neither: a
            # flat top of two equal highs is not a reversal, and admitting it
            # would let a sideways stretch nominate a pivot every bar.
            mid = self._bars[self.reach]
            others = [b for k, b in enumerate(self._bars) if k != self.reach]
            if all(b[0] < mid[0] for b in others):
                found.append((self._seen, mid[0], 1))
            if all(b[1] > mid[1] for b in others):
                found.append((self._seen, mid[1], -1))
        self._pivots.extend(found)
        if self._pivots and self._pivots[0][0] < self._seen - self.forget:
            cut = self._seen - self.forget
            self._pivots = [p for p in self._pivots if p[0] >= cut]
        return found

    def around(self, close: float, *, beyond: float = 0.0) -> tuple[Nearest | None, ...]:
        """The cluster each side of `close`: `(below, above, far below, far above)`.

        The first pair is the **nearest** group each side. The second pair is
        the nearest group whose own extreme is at least `beyond` volatility
        units away, which is a different and more defensible reading of "put
        the stop beyond the level": measured on 19 years of daily eurusd the
        nearest cluster's floor sits **0.43 volatility units** below the close
        at the median, against `SurpriseProfile.stop_vol` of 2.0 - so anchoring
        on the nearest level makes the stop four to five times *tighter*, not
        wider, and `cost_px / risk` rises in proportion. Both readings are
        carried because the first is the claim as written and the second is the
        claim as meant.

        The group is chosen by the extreme on the trade's own side in the `far`
        pair, so `floor` and `centre` still read **one** group and differ only
        in the argument to `Group.price`.

        Clustering is `grouping.cluster`, complete linkage, so a group's span
        is bounded by `width_vol` units and the partition does not depend on
        the order the touches arrived in or on their weights - which is the
        chaining defect `grouping`'s own docstring measures, nine touches
        becoming one level 6.9 times the gap wide.

        Each pivot is one touch of weight one, so the weighted mean is the mean
        of the touch prices: a level's evidence is how many *independent* turns
        agree (`a-magnet-is-a-shared-reference`), not how often one was retested
        within a single stretch.
        """
        if not self._pivots or self.unit <= 0.0:
            return None, None, None, None
        prices = [p[1] for p in self._pivots]
        sides = [p[2] for p in self._pivots]
        groups = cluster(prices, self.width * self.unit)
        if len(groups) > self.keep:
            # The book is capped at `KEEP` 24, and the ones kept are the
            # nearest to price - which is what a stop rule reads.
            groups = sorted(groups, key=lambda g: abs(g.centre - close))[: self.keep]
        under = [g for g in groups if g.centre < close]
        over = [g for g in groups if g.centre > close]
        gap = max(0.0, beyond) * self.unit
        deep = [g for g in under if close - g.low >= gap]
        high_up = [g for g in over if g.high - close >= gap]
        return (
            self._read(max(under, key=lambda g: g.centre), prices, sides) if under else None,
            self._read(min(over, key=lambda g: g.centre), prices, sides) if over else None,
            self._read(max(deep, key=lambda g: g.low), prices, sides) if deep else None,
            self._read(min(high_up, key=lambda g: g.high), prices, sides) if high_up else None,
        )

    def edges(self) -> list[float]:
        """Every live cluster's floor and ceiling, for the power sweep.

        **Both extremes of every group, not the nearest group's.** A barrier
        planted only at the nearest level would miss the `beyond` arms
        entirely, since those anchor on the first cluster clearing `MIN_VOL`
        volatility units - so the sweep would report the blind point of a test
        for an effect it never planted where that test looks.
        """
        if not self._pivots or self.unit <= 0.0:
            return []
        prices = [p[1] for p in self._pivots]
        out: list[float] = []
        for group in cluster(prices, self.width * self.unit):
            out.append(group.low)
            if group.high != group.low:
                out.append(group.high)
        return out

    def _read(self, group, prices, sides) -> Nearest:
        total = sum(s for p, s in zip(prices, sides, strict=True) if group.low <= p <= group.high)
        return Nearest(
            low=group.price(Anchor.FLOOR),
            centre=group.price(Anchor.CENTRE),
            high=group.price(Anchor.CEILING),
            side=int(np.sign(total)),
            members=group.members,
        )


@dataclass(frozen=True, slots=True)
class Book:
    """The nearest cluster each side of the close, per bar, as flat arrays.

    NaN where there was no group on that side, which is how an anchor leaves
    every arm at once - see `usable`.
    """

    below_low: np.ndarray
    below_centre: np.ndarray
    below_high: np.ndarray
    below_side: np.ndarray
    below_members: np.ndarray
    above_low: np.ndarray
    above_centre: np.ndarray
    above_high: np.ndarray
    above_side: np.ndarray
    above_members: np.ndarray
    #: The volatility unit the book itself used, so distances and clustering
    #: cannot be measured in two different units.
    unit: np.ndarray


FIELDS = (
    "below_low",
    "below_centre",
    "below_high",
    "below_side",
    "below_members",
    "above_low",
    "above_centre",
    "above_high",
    "above_side",
    "above_members",
)


def book_path(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    reach: int = BOOK_REACH,
    width_vol: float = BOOK_WIDTH,
    keep: int = KEEP,
    forget: int = FORGET_BARS,
    unit_span: int = 48,
    beyond: float = MIN_VOL,
) -> dict[str, Book]:
    """`Walker` over a whole series, as the arrays the race wants.

    Two books from one pass: `near` is the nearest cluster each side and
    `beyond` is the nearest whose extreme clears `beyond` volatility units.
    One pass rather than two because the clustering is the cost and both
    readings come off the same partition - so the two books cannot disagree
    about what the book held.
    """
    n = len(close)
    out = {pick: {key: np.full(n, np.nan) for key in FIELDS} for pick in ("near", "beyond")}
    unit = np.zeros(n)
    walker = Walker(reach=reach, width_vol=width_vol, keep=keep, forget=forget, unit_span=unit_span)
    for i in range(n):
        walker.update(float(high[i]), float(low[i]))
        unit[i] = walker.unit
        below, above, far_below, far_above = walker.around(float(close[i]), beyond=beyond)
        for pick, tag, found in (
            ("near", "below", below),
            ("near", "above", above),
            ("beyond", "below", far_below),
            ("beyond", "above", far_above),
        ):
            if found is None:
                continue
            here = out[pick]
            here[f"{tag}_low"][i] = found.low
            here[f"{tag}_centre"][i] = found.centre
            here[f"{tag}_high"][i] = found.high
            here[f"{tag}_side"][i] = found.side
            here[f"{tag}_members"][i] = found.members
    return {pick: Book(unit=unit, **fields) for pick, fields in out.items()}


# ──────────────────────────── the stop distances ────────────────────────────


def distances(
    books: dict[str, Book], close: np.ndarray, unit: np.ndarray, arm: Arm, side: int
) -> np.ndarray:
    """The stop distance in **price**, per bar, for one arm and one side.

    NaN where the arm has no reading, which is how an anchor leaves every arm
    at once: `usable` intersects the arms so a cell never compares one arm's
    easy anchors against another's.

    `side` is +1 long and -1 short, `statespace-signal-is-minus-one-to-plus-
    one`'s convention. A long's stop is below the entry and reads the group
    below it; a short's is above and reads the group above.
    """
    if arm.kind == "vol":
        return arm.width * unit
    book = books[arm.pick]
    if arm.kind == "mirror":
        # The group on the **far** side of the entry, where a level cannot
        # shield the stop, at its own extreme. Same book, same construction,
        # same clustering - only the side it is read from differs.
        anchor = book.above_high if side > 0 else book.below_low
    elif arm.kind == "formed":
        # `Anchor.SIDED` as its own docstring defines it: the extreme named by
        # the **level's** formed side - low for a support, high for a
        # resistance, the centre where no side formed - which is *not* the
        # trade's side. The two disagree whenever the nearest group below a
        # long was built mostly from pivot highs, and that rate is reported,
        # because the claim is stated in the trade's side and the primitive is
        # keyed on the level's.
        low_a = book.below_low if side > 0 else book.above_low
        high_a = book.below_high if side > 0 else book.above_high
        centre_a = book.below_centre if side > 0 else book.above_centre
        formed = book.below_side if side > 0 else book.above_side
        anchor = np.where(formed < 0, low_a, np.where(formed > 0, high_a, centre_a))
    elif arm.kind == "centre":
        anchor = book.below_centre if side > 0 else book.above_centre
    else:
        # `floor` and `matched`: the extreme on the trade's own side, which is
        # the claim as stated - the floor for a long, the ceiling for a short.
        anchor = book.below_low if side > 0 else book.above_high
    # The mirror's anchor is on the **far** side of the entry, so it
    # contributes a *distance* that is then placed on the trade's own side;
    # signing it would make every mirror distance negative and `usable` would
    # drop the whole panel. Every other arm is signed on purpose: `formed` can
    # name a price on the wrong side of the entry - the group below a long is
    # handed its own ceiling whenever its touches were mostly pivot highs -
    # and that anchor is not a stop. Those anchors are **dropped** by `usable`,
    # not folded in as a tight stop, because a mixture of two stop rules under
    # one name is exactly what makes a column unreadable later.
    gap = np.abs(close - anchor) if arm.kind == "mirror" else (close - anchor) * side
    return gap + arm.buffer * unit


def usable(d: dict[str, np.ndarray], unit: np.ndarray, horizon: int) -> np.ndarray:
    """Anchors where every arm has a positive, finite, capped stop distance.

    One anchor set for every arm, so no arm is scored on a different sample.
    An arm that fell back to the volatility stop where the book was empty would
    be a **mixture of two rules** reported under one name, which is the defect
    `one column, one unit` names in the skill; here the anchor is dropped and
    the drop rate is reported instead.
    """
    n = len(unit)
    ok = (unit > 0.0) & np.isfinite(unit)
    ok[: max(1, horizon)] = False
    ok[n - horizon - 1 :] = False
    for values in d.values():
        with np.errstate(invalid="ignore"):
            ok &= np.isfinite(values) & (values > 0.0) & (values <= MAX_VOL * unit)
    return ok


# ──────────────────────────────── the race ────────────────────────────────


def race(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    stop_px: np.ndarray,
    side: int,
    horizon: int,
) -> tuple[np.ndarray, np.ndarray]:
    """`(stopped, R)` per anchor: a stop against a clock, nothing else.

    No target, which is the exit rule `strategies/structure.py` names and the
    only one on which the stop *width* can matter at all. With a target at
    `target_r * risk` the width cancels out of R exactly - the race is
    1/(1+target_r) whatever the stop - so a stop-width question posed against a
    risk-scaled target is answering nothing. That is why the clock is the
    primary rule here and is stated rather than assumed.

    A stop fills **at the stop**, so a stop-out is exactly -1R. Overshoot past
    the stop is real and grows with the distance to the barrier, so charging it
    would give the wide arm a width-dependent debit against a width-dependent
    advantage; the control for both is the same race on matched surrogates.
    """
    n = len(close)
    span = max(1, horizon)
    if n < span + 2:
        return np.zeros(0, dtype=bool), np.zeros(0)
    extreme = low if side > 0 else high
    window = np.lib.stride_tricks.sliding_window_view(extreme, span)
    worst = window.min(axis=1) if side > 0 else window.max(axis=1)
    # The window starting at i+1 covers bars i+1 .. i+horizon, so the anchor
    # bar's own range is excluded - a stop cannot be hit by the bar whose close
    # is the entry.
    reach = np.full(n, np.nan)
    reach[: len(worst) - 1] = worst[1:]
    exits = np.full(n, np.nan)
    exits[: n - span] = close[span:]
    risk = (close - stop_px) * side
    hit = ((stop_px - reach) * side >= 0.0) & np.isfinite(reach)
    with np.errstate(invalid="ignore", divide="ignore"):
        clock = (exits - close) * side / risk
    return hit, np.where(hit, -1.0, clock)


def strata(stop_px: np.ndarray, close: np.ndarray, unit: np.ndarray, side: int) -> np.ndarray:
    """Which width stratum each anchor falls in, as an index into `EDGES`.

    The stop's own distance in volatility units, binned on `EDGES`. The
    confound this study is about is width, so every contrast is reported
    standardised on this as well as pooled, and the difference between the two
    numbers is how much of the raw gap is geometry.
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        vol = (close - stop_px) * side / unit
    return np.digitize(vol, EDGES[1:], right=True)


def permute(values: np.ndarray, mask: np.ndarray, rng: random.Random) -> np.ndarray:
    """`values` with the entries under `mask` shuffled among themselves.

    The distance-matched placebo, applied to the distance in **volatility
    units** rather than in price: permuting a price distance across a 19-year
    series would hand a 2006 anchor a 2024 distance and the arm would differ
    from `floor` in the level of volatility as well as in the pairing. In vol
    units the marginal width distribution is preserved exactly and the only
    thing destroyed is which anchor got which width.
    """
    out = values.copy()
    idx = np.flatnonzero(mask)
    order = list(idx)
    rng.shuffle(order)
    out[idx] = values[np.asarray(order)]
    return out
