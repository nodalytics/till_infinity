"""Shapes as an enumerated candidate family, not as a chart vocabulary.

Asked for on 2026-11-01 - "state space should also be able to discover
geometrical shapes and different kinds of other shapes too". A shape here is
one more family in `searching`'s sweep, scored against the same arms, and the
design choice that matters is **enumeration over naming**.

## Why the grid and not the names

A triangle, a wedge, a flag and a channel are all the same object: two fitted
lines and a test on how they relate. So the family is the *complete grid* of
`(high-line slope, low-line slope, how the pair relates)` - and the familiar
names are labels on some of its cells, attached in `NAMED` for a report to
read, carrying no weight in the sweep.

That is not tidiness. The classical geometric families on this desk are
**already measured null** - pivot, Elliott, Wyckoff and Gann all came out
null, and `topology-restates-volatility` found levels, ranges and shapes null
together with the strata sweep as the thing that mattered. The named cells are
therefore the ones most likely to be post-hoc, and a sweep that tested only
them would be testing the ones with the worst prior. Enumerating the grid puts
`(up, up, converging)` - a rising wedge, which has a name - beside
`(up, down, parallel)`, which is geometrically impossible, and
`(flat, down, diverging)`, which has no name and no literature and exactly the
same claim to a trial.

## When a shape becomes knowable, which is the trap specific to shapes

**A triangle is only a triangle once it has broken out**, so a "confirmed"
shape carries the future in its definition. That is the same bug as
`open-gap-filters-are-lookahead`, where `drawing.gaps` emitted only *unfilled*
gaps and read +0.50R a trade as a bias.

Every shape here therefore records `at`: the index of the bar on which its
definition **completed** - the bar that confirmed the newest pivot the fit
used, from `Pivot.confirmed`, which exists for this reason. `reader()` emits
the shape at that bar and at no earlier one. `broken_out()` is the lookahead
version, kept and named so the comparison can be made, and
`searching.score` **refuses** a candidate built from it.

## What is reused rather than rebuilt

`indicators.trend.pivots` and `fit_line` are pure functions over
`(high, low, when)` tuples, and `indicators.candles` is pure functions over an
OHLC record - so the primitives are the desk's measured ones and nothing here
re-implements a pivot. `fit_line` re-centres time on the newest pivot before
fitting, because unix seconds are around 1.8e9 and prices around 1, and a raw
fit squares that ratio into the normal equations.

## What a shape score may be, and what it may not

**A hit rate is geometry.** The displacement origin's 82% return rate is
matched by a distance-matched placebo on every class and a random walk reads
0.825 - so a shape scored on "how often did price reach the apex" is scoring
the distance it chose. Every reader here is therefore an **indicator**: 1.0 on
the bar the shape completed, `nan` elsewhere. The outcome is `searching`'s
forward absolute move in trailing-sd units, and the distance-matched placebo
arm is what keeps the geometry out of it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import product

from till_infinity.indicators.candles import Bar as Ohlc
from till_infinity.indicators.candles import engulfing, hammer, shooting_star
from till_infinity.indicators.levels import DEFAULT_CONFIRM, points, structure, turns
from till_infinity.indicators.trend import FIT_PIVOTS, REACH, Pivot, fit_line, pivots

from .searching import Candidate

#: Bars of history a shape is looked for over. 120 at 1h is five days, which
#: is long enough for three pivots a side at `REACH` 3 and short enough that
#: the two lines are a local description rather than a fit to the whole sample.
WINDOW = 120

#: How flat a gradient counts as flat, in trailing standard deviations per
#: bar. **A threshold in volatility units and not in price**, because a
#: gradient in price per second reads as steep on gold and flat on EURUSD for
#: no reason but the quote - which is the units error `bars.check_scale`
#: refuses at wiring time and which nothing refuses here.
FLAT = 0.05

#: How close two gradients must be, as a share of the larger, to count as
#: parallel. 0.25 rather than something tighter because two least-squares fits
#: through three pivots each carry a lot of gradient error, and a tolerance
#: narrower than that error makes `PARALLEL` a cell no real shape lands in -
#: which would silently drop a third of the grid.
PARALLEL_SHARE = 0.25


class Slope(StrEnum):
    """What one fitted line does, in volatility units per bar."""

    UP = "up"
    FLAT = "flat"
    DOWN = "down"


class Pair(StrEnum):
    """How the two lines relate, by whether their separation is closing."""

    CONVERGING = "converging"
    PARALLEL = "parallel"
    DIVERGING = "diverging"


#: The familiar names, by the cell each occupies. **Labels, not a filter.**
#: Every cell in `families()` gets a trial whether it appears here or not; a
#: cell with no entry is reported by its coordinates, which is the honest way
#: to report a shape nobody has drawn.
NAMED: dict[tuple[Slope, Slope, Pair], str] = {
    (Slope.UP, Slope.UP, Pair.CONVERGING): "rising wedge",
    (Slope.DOWN, Slope.DOWN, Pair.CONVERGING): "falling wedge",
    (Slope.DOWN, Slope.UP, Pair.CONVERGING): "symmetrical triangle",
    (Slope.FLAT, Slope.UP, Pair.CONVERGING): "ascending triangle",
    (Slope.DOWN, Slope.FLAT, Pair.CONVERGING): "descending triangle",
    (Slope.UP, Slope.UP, Pair.PARALLEL): "rising channel",
    (Slope.DOWN, Slope.DOWN, Pair.PARALLEL): "falling channel",
    (Slope.FLAT, Slope.FLAT, Pair.PARALLEL): "rectangle",
    (Slope.UP, Slope.DOWN, Pair.DIVERGING): "broadening formation",
}
# A name for a cell `feasible` excludes is noise - the shape cannot occur, so
# nothing will ever be filed under it and a reader counting the names gets a
# number larger than the grid. `(down, up, diverging)` was in this table for
# exactly that reason until a test counted it.


def feasible(high: Slope, low: Slope, pair: Pair) -> bool:
    """Whether a cell of the grid can occur at all.

    Three constraints, each geometric rather than stylistic:

    * **Parallel needs equal gradients**, so the two lines cannot carry
      opposite signs. `(up, down, parallel)` is not a rare shape, it is not a
      shape.
    * **A converging pair must be able to close.** An upper line rising faster
      than a lower one is diverging by construction, but the *classes* here
      are signs rather than magnitudes, so only the pair where the upper rises
      and the lower falls is excluded - that one cannot converge whatever the
      magnitudes.
    * Its mirror for diverging.

    Stated as a function rather than a hand-written list so that the count of
    live cells is derived. A list would be a place for a cell to go missing,
    and a missing cell is a family that was never tried and never reported.
    """
    if pair is Pair.PARALLEL:
        return high is low
    if pair is Pair.CONVERGING:
        return not (high is Slope.UP and low is Slope.DOWN)
    return not (high is Slope.DOWN and low is Slope.UP)


def cells() -> list[tuple[Slope, Slope, Pair]]:
    """Every geometrically possible line-pair cell. **19** of the 27 combinations.

    Three parallel (the two gradients must match), eight converging and eight
    diverging. The count is asserted in a test rather than trusted here: a
    cell that silently stops being enumerated is a family that was never
    tried and never reported.
    """
    return [
        (high, low, pair)
        for high, low, pair in product(Slope, Slope, Pair)
        if feasible(high, low, pair)
    ]


@dataclass(frozen=True, slots=True)
class Shape:
    """One detection, with the bar its definition completed on.

    `at` is an index into the candle series and is the only time a score may
    read. It is the confirmation index of the newest pivot the fit used, not
    the index of the extreme and not the index of a later breakout.
    """

    cell: tuple[Slope, Slope, Pair]
    at: int
    #: Gradients in trailing standard deviations per bar, upper then lower.
    high_slope: float
    low_slope: float
    #: Pivots in each fit. Two is a chord, more is a regression.
    points: int

    @property
    def name(self) -> str:
        return NAMED.get(self.cell, "-".join(self.cell))


def _classify(gradient: float, flat: float) -> Slope:
    if gradient > flat:
        return Slope.UP
    return Slope.DOWN if gradient < -flat else Slope.FLAT


def _pair(high: float, low: float, share: float) -> Pair:
    """Converging when the gap closes, parallel when the gradients agree.

    The gap closes when the upper line's gradient is below the lower line's -
    an upper falling toward a rising lower is the textbook triangle, and the
    sign of the difference is the whole test.
    """
    scale = max(abs(high), abs(low), 1e-12)
    if abs(high - low) <= share * scale:
        return Pair.PARALLEL
    return Pair.CONVERGING if high < low else Pair.DIVERGING


def shapes(
    candles: Sequence[tuple[float, float, float, float]],
    *,
    window: int = WINDOW,
    reach: int = REACH,
    use: int = FIT_PIVOTS,
    flat: float = FLAT,
    share: float = PARALLEL_SHARE,
) -> list[Shape]:
    """Every line-pair shape in the series, at the bar each became knowable.

    One shape per bar at most, and a shape is emitted only on the bar where
    the newest pivot in *both* fits is confirmed - so a shape that persists for
    thirty bars is one detection and not thirty, which is what stops the event
    count being a measure of how long the window is.

    Times are **absolute bar indices** rather than seconds or window offsets.
    `fit_line` re-centres on its newest pivot before fitting, so the gradient
    comes out in price per index step, which is what the volatility scaling
    below needs; passing seconds would make the gradient depend on the
    timeframe and the `flat` threshold meaningless, and passing window-relative
    offsets would make `Pivot.when` repeat on every window, which silently
    collapsed the de-duplication below to two detections in 1,200 bars.

    **One pivot pass over the whole series, not one per bar.** A pivot's
    definition reaches `reach` bars either side and no further, so the global
    pass and a per-window pass agree on every pivot that is at least `reach`
    from a window edge - which is all of the ones used, because a pivot is
    only taken once `confirmed <= t`. The per-window version was
    `O(n * window * reach)`, which at 4,000 bars and a 120-bar window is 3.4
    million comparisons per *draw* - and a sweep runs the reader again on every
    null draw of every arm, so it was the whole cost of the harness.
    """
    if len(candles) < window + reach + 2:
        return []
    frame = [(c[1], c[2], float(i)) for i, c in enumerate(candles)]
    found = pivots(frame, reach=reach)
    if not found:
        return []
    #: Pivots in the order they became knowable, so a forward walk can take
    #: "everything confirmed by now" without re-filtering the whole list.
    found.sort(key=lambda p: (p.confirmed, p.when))
    out: list[Shape] = []
    seen: set[tuple[int, int]] = set()
    highs: list[Pivot] = []
    lows: list[Pivot] = []
    at_index = 0
    # `len(candles) + 1`, so the last bar can carry a detection. Stopping at
    # `len(candles)` made the newest knowable shape unreachable, which is
    # invisible on a long series and is exactly the off-by-one a causality
    # test catches: truncating the series at the detection bar made the
    # detection disappear.
    for end in range(window, len(candles) + 1):
        at = end - 1
        fresh = False
        while at_index < len(found) and found[at_index].confirmed <= at:
            pivot = found[at_index]
            (highs if pivot.side == 1 else lows).append(pivot)
            fresh = fresh or int(pivot.confirmed) == at
            at_index += 1
        if not fresh:
            continue  # nothing became knowable on this bar
        oldest = end - window
        live_highs = [p for p in highs if p.when >= oldest][-max(2, use) :]
        live_lows = [p for p in lows if p.when >= oldest][-max(2, use) :]
        if len(live_highs) < 2 or len(live_lows) < 2:
            continue
        key = (int(live_highs[-1].when), int(live_lows[-1].when))
        if key in seen:
            continue
        seen.add(key)
        top = fit_line(live_highs, use=use)
        bottom = fit_line(live_lows, use=use)
        if top is None or bottom is None:
            continue
        unit = _unit(candles, end)
        if unit <= 0.0:
            continue
        high_slope, low_slope = top.gradient / unit, bottom.gradient / unit
        cell = (
            _classify(high_slope, flat),
            _classify(low_slope, flat),
            _pair(high_slope, low_slope, share),
        )
        if not feasible(*cell):
            # A measured pair can land on an impossible cell when the gradient
            # classes and the convergence test disagree inside the tolerance.
            # Dropped rather than forced, because forcing it would file a
            # detection under a shape the geometry does not support.
            continue
        out.append(
            Shape(
                cell=cell,
                at=at,
                high_slope=high_slope,
                low_slope=low_slope,
                points=min(top.points, bottom.points),
            )
        )
    return out


def _unit(candles: Sequence[tuple[float, float, float, float]], end: int, span: int = 64) -> float:
    """A trailing standard deviation of closes, as the gradient's unit.

    `drive-q-from-the-range` puts the range estimator ahead of the close one
    by a ratio of 0.648 within strata on FX, but a gradient is a *close*
    quantity and dividing it by a range unit mixes the two - so this is the
    close estimator on purpose, and the choice is recorded rather than
    inherited.
    """
    low = max(0, end - span)
    closes = [c[3] for c in candles[low:end]]
    if len(closes) < 3:
        return 0.0
    steps = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    mean = sum(steps) / len(steps)
    var = sum((s - mean) ** 2 for s in steps) / len(steps)
    return math.sqrt(max(var, 0.0))


def reader(
    cell: tuple[Slope, Slope, Pair], **kwargs: object
) -> Callable[[Sequence[tuple[float, float, float, float]]], list[float]]:
    """A `searching.Reader` that fires on one cell of the grid.

    1.0 on the bar the shape's definition completed, `nan` on every other bar.
    An indicator rather than a score, for the reason the module docstring
    gives: a shape scored by a hit rate is scored by the distance it chose.
    """

    def read(candles: Sequence[tuple[float, float, float, float]]) -> list[float]:
        out = [math.nan] * len(candles)
        for shape in shapes(candles, **kwargs):  # type: ignore[arg-type]
            if shape.cell == cell and 0 <= shape.at < len(out):
                out[shape.at] = 1.0
        return out

    return read


def broken_out(
    cell: tuple[Slope, Slope, Pair], **kwargs: object
) -> Callable[[Sequence[tuple[float, float, float, float]]], list[float]]:
    """The **lookahead** version, kept so the difference can be measured.

    Fires on the bar the shape completed only if price later left the pair's
    envelope - which is how a chart reader identifies a triangle, and which
    reads the future at the bar it claims to be reporting. Any candidate built
    from this must set `Candidate.lookahead=True`, and `searching.score`
    refuses it: `drawing.gaps` emitted only *unfilled* gaps and the same
    mistake read +0.50R a trade.
    """

    def read(candles: Sequence[tuple[float, float, float, float]]) -> list[float]:
        out = [math.nan] * len(candles)
        for shape in shapes(candles, **kwargs):  # type: ignore[arg-type]
            if shape.cell != cell or not 0 <= shape.at < len(out) - 1:
                continue
            after = [c[3] for c in candles[shape.at + 1 :]]
            inside = candles[shape.at][1] - candles[shape.at][2]
            if any(abs(p - candles[shape.at][3]) > inside for p in after):
                out[shape.at] = 1.0
        return out

    return read


# ───────────────────────── the structure alphabet ─────────────────────────

#: The four labels `indicators.levels.Structure` assigns a confirmed swing.
#: A transition alphabet with, until now, no model over it.
LETTERS: tuple[str, ...] = ("HH", "LH", "HL", "LL")


def words(length: int = 2) -> list[tuple[str, ...]]:
    """Every word of `length` over the structure alphabet.

    `4 ** length` of them, which is the multiplicity this family costs: 16 at
    two and 64 at three. Enumerated rather than named for the reason the
    module docstring gives - a double top is `(HH, LH)` and a double bottom is
    `(LL, HL)`, and the two cells with names have no stronger claim than the
    fourteen without.
    """
    return [tuple(w) for w in product(LETTERS, repeat=max(1, int(length)))]


def labels(
    candles: Sequence[tuple[float, float, float, float]],
    *,
    window: int = WINDOW,
    count: int = 12,
    confirm: int = DEFAULT_CONFIRM,
    stride: int = 1,
) -> list[tuple[int, str]]:
    """`(index, label)` per confirmed turn, in the order they became knowable.

    The index is the **confirmation** index, not the index of the extreme.
    `Point.confirmed` carries `inf` while a swing still is not knowable, which
    is what makes a trailing swing fall out rather than claim to be settled -
    every lookahead bug in `levels.py` would live in a clamp of that value.

    ## The selection is global within its window, so this is `O(n)` selections

    There is no incremental form that gives the same answer - `extract` picks
    the globally most prominent points - and at 4,000 bars with a 120-bar
    window and 12 points that is 11.5 seconds, which a sweep pays again on
    every null draw of every arm.

    `stride` is a **declared compute budget**, in the same spirit as
    `Changepoint`'s `MAX_RUN`: at `stride=k` only every `k`th window is
    evaluated, so about `1/k` of the confirmations are found. It does **not**
    re-date anything. The tempting version - evaluate every `k`th window and
    accept confirmations from the last `k` bars - would score a point using a
    window with up to `k-1` bars of data that did not exist when it was
    confirmed, which is a lookahead of exactly the shape this module exists to
    prevent. So a stride costs power and nothing else, and the arms run at the
    same stride so the comparison is unaffected.
    """
    out: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    step = max(1, int(stride))
    for end in range(window, len(candles) + 1, step):
        start = end - window
        times = list(range(end - start))
        closes = [candles[i][3] for i in range(start, end)]
        found = points(times, closes, count, confirm=confirm)
        for point, label in structure(turns(found)):
            if label is None or not math.isfinite(point.confirmed):
                continue
            at = start + int(point.confirmed)
            # Only a confirmation that landed on this window's last bar: an
            # earlier one is re-found by the window that ended on it, and at
            # `stride > 1` it is simply not found, which is the power cost.
            if at != end - 1 or (at, str(label)) in seen:
                continue
            seen.add((at, str(label)))
            out.append((at, str(label)))
    out.sort()
    return out


def word_reader(
    word: Sequence[str], **kwargs: object
) -> Callable[[Sequence[tuple[float, float, float, float]]], list[float]]:
    """A reader that fires when the last `len(word)` labels match `word`.

    Fires at the confirmation index of the word's **last** letter, which is
    when the word became knowable.
    """
    wanted = tuple(word)

    def read(candles: Sequence[tuple[float, float, float, float]]) -> list[float]:
        out = [math.nan] * len(candles)
        found = labels(candles, **kwargs)  # type: ignore[arg-type]
        for i in range(len(wanted) - 1, len(found)):
            run = tuple(label for _at, label in found[i - len(wanted) + 1 : i + 1])
            if run == wanted:
                at = found[i][0]
                if 0 <= at < len(out):
                    out[at] = 1.0
        return out

    return read


# ───────────────────────────── the bar shapes ─────────────────────────────

#: The bar-shape family, by name. `candles` gates on `Bar.is_revision` on the
#: live path so only confirmed bars count; here the series is closed bars by
#: construction, and the equivalent care is that `engulfing` needs the
#: previous bar, so it fires one bar later than the shape it names.
BAR_SHAPES: tuple[str, ...] = ("hammer", "shooting_star", "engulfing_up", "engulfing_down", "doji")


def bar_reader(
    kind: str,
) -> Callable[[Sequence[tuple[float, float, float, float]]], list[float]]:
    """A reader for one bar shape, firing on the bar that completes it."""
    if kind not in BAR_SHAPES:
        raise ValueError(f"{kind!r} is not a bar shape. Known: {sorted(BAR_SHAPES)}")

    def read(candles: Sequence[tuple[float, float, float, float]]) -> list[float]:
        out = [math.nan] * len(candles)
        previous: Ohlc | None = None
        for i, (open_, high, low, close) in enumerate(candles):
            bar = Ohlc(open=open_, high=high, low=low, close=close, time=float(i))
            hit = False
            if kind == "hammer":
                hit = hammer(bar)
            elif kind == "shooting_star":
                hit = shooting_star(bar)
            elif kind == "doji":
                hit = bar.doji
            elif previous is not None:
                got = engulfing(previous, bar)
                hit = got == ("up" if kind == "engulfing_up" else "down")
            if hit:
                out[i] = 1.0
            previous = bar
        return out

    return read


# ───────────────────────────── the candidates ─────────────────────────────


def candidates(
    *,
    question: str = "dispersion",
    word_length: int = 2,
    window: int = WINDOW,
    word_stride: int = 1,
    word_count: int = 12,
) -> list[Candidate]:
    """Every shape family as a `searching.Candidate`, grid first.

    The count is the point, and it is reported rather than reduced: 19 line
    cells plus `4 ** word_length` structure words plus 5 bar shapes - **40** at
    two-letter words, and 88 at three. **At a target Sharpe of 1.5 one month of data supports
    about one trial**, so 42 is a multiplicity that has to be declared, and
    `Sweep.effective_trials` is what discounts it for the overlap these
    families have with each other: an engulfing bar is the *opposite shape* to
    a displacement origin, and the best vs-walk z over 516 rows was +1.95.

    The threshold is 1.0 for every one of them, because each reader is an
    indicator. There is nothing to sweep, which is the other half of the
    argument for an indicator: a shape with a continuous score would need a
    threshold grid per cell and the trial count would multiply by its length.
    """
    out: list[Candidate] = [
        Candidate(
            family="shape",
            name=NAMED.get(cell, "-".join(cell)),
            question=question,
            threshold=1.0,
            reader=reader(cell, window=window),
            source="lines",
        )
        for cell in cells()
    ]
    out.extend(
        Candidate(
            family="shape",
            name="".join(word),
            question=question,
            threshold=1.0,
            reader=word_reader(word, window=window, stride=word_stride, count=word_count),
            source="structure",
        )
        for word in words(word_length)
    )
    out.extend(
        Candidate(
            family="shape",
            name=kind,
            question=question,
            threshold=1.0,
            reader=bar_reader(kind),
            source="bar",
        )
        for kind in BAR_SHAPES
    )
    return out


def lookahead_candidate(
    cell: tuple[Slope, Slope, Pair], *, question: str = "dispersion", window: int = WINDOW
) -> Candidate:
    """The breakout-conditioned twin of one cell, declared as lookahead.

    Built so the refusal in `searching.score` has something to refuse, and so
    a harness can measure how much a shape's apparent edge is the breakout
    condition. Not in `candidates()`: a sweep that included it would be
    sweeping a known bug.
    """
    return Candidate(
        family="shape",
        name=f"{NAMED.get(cell, '-'.join(cell))} (broken out)",
        question=question,
        threshold=1.0,
        reader=broken_out(cell, window=window),
        source="lines",
        lookahead=True,
    )


__all__ = [
    "BAR_SHAPES",
    "FLAT",
    "LETTERS",
    "NAMED",
    "PARALLEL_SHARE",
    "WINDOW",
    "Pair",
    "Pivot",
    "Shape",
    "Slope",
    "bar_reader",
    "broken_out",
    "candidates",
    "cells",
    "feasible",
    "labels",
    "lookahead_candidate",
    "reader",
    "shapes",
    "word_reader",
    "words",
]
