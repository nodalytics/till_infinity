"""Trend: what line price is on, and whether it is going anywhere.

Grouped the way `nautilus_trader.indicators.trend` is grouped, and holding
three readings of the same question at different resolutions:

* **`ratio` / `Trend`** - Kaufman's efficiency: how much of the distance
  travelled went somewhere. One is a move that went straight there, zero is
  ground covered to no end. Bounded in [0, 1] by the triangle inequality, so
  it needs no scaling and compares across instruments as it stands.
* **`Trendlines`** - lines through *confirmed* pivots, from the top and from
  the bottom, with the break reading. The pivots are the point: a line drawn
  through extremes marked where they happened rather than where they were
  confirmed could not have been drawn at the time.
* **`Channel` / `fit`** - the linear regression channel: the line, how tight
  it is, which way it leans.

**Nautilus has `trend.LinearRegression`, `MovingAverageConvergenceDivergence`,
`AroonOscillator`, `DirectionalMovement`, `Swings` and `Bias`** - take those
from there. Three notes from the audit in this package's `__init__`:

* `LinearRegression`'s slope and R² agree with `fit`'s to 1e-9, so **prefer
  the framework's for the fit**. What `Channel` adds is the bands and the
  vol-scaled readings.
* `momentum.EfficiencyRatio` is the same statistic as `ratio` and is
  **arithmetically wrong** - `(period-1)/period` on a straight line, where the
  answer is 1.0 by definition. `ratio` is the corrected one; a test pins it.
* `Swings` reports a *running* extreme, not a confirmed pivot, which is why
  `Trendlines` detects its own.

**Three different `SPAN`s met when these modules merged** - 100 for the
channel, 120 for the pivot window, and 40 for a displacement leg, which went
to `levels.py` - so the pivot window here is `PIVOT_SPAN` and `SPAN` stays the
channel's, which is the one a test asserts the value of. `PIVOT_SPAN` is the
one with a live caller: it is `Trendlines`' default, and `Trendlines` is in
`BAR_DETECTORS`. `SPAN` is read only by the fit and feature functions below,
which nothing in the live tree calls yet.
"""

from __future__ import annotations

import itertools
import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from till_infinity.utils.state import Restorable

from .bars import NANOS, Reading, bar_input, check_feed, check_scale, reset_state
from .candles import Bar as Ohlc

# ==========================================================================
# the efficiency ratio
# ==========================================================================

WINDOW = 12
#: Below this many, no opinion is offered. Two points is one step, which is
#: trivially perfectly efficient and says nothing.
FEWEST = 3


def ratio(prices: Sequence[float]) -> float | None:
    """How much of the distance travelled went somewhere. Kaufman's ratio.

    **Nautilus ships this as `indicators.momentum.EfficiencyRatio` and its
    arithmetic is wrong.** Measured on 1.221.0: fed a perfectly straight line,
    where every step goes the same way and the ratio is 1.0 by definition,
    `EfficiencyRatio(period)` reports `(period - 1) / period` - 0.5 at period
    2, 0.8 at 5, 0.95 at 20 - for every period tried. It takes the numerator
    over one fewer step than the denominator, so it is bounded above by
    `(period - 1) / period` and can never report a perfectly efficient move.
    The bias is `1 / period`, which is largest exactly where a short window is
    wanted. `test_indicators.py` pins the behaviour so a fixed upstream shows
    up as a failing test rather than as a silent change of meaning.

    That is the second framework indicator this package replaces for an
    arithmetic fault rather than for taste - see `spread.py` for the first -
    and both are documented rather than quietly worked around.

        |last - first| / sum(|step|)

    One is a move that went straight there; zero is ground covered to no end.
    Bounded in `[0, 1]` by the triangle inequality, which is why it needs no
    scaling and compares across instruments as it stands. `None` where there
    was no path to measure - which is not the same answer as zero, and the
    callers want to tell them apart.

    **A module-level function rather than a method**, because it was asked of
    two different series. `Trend` asks it of recent *level prices*, to scale
    sizing; the other caller was `touches.base`, which asked it of recent *bar
    closes* as a model feature and retired to
    `research/retire/structures/engine/learning/touches.py`. Same statistic,
    different input, and one copy - the second copy was written and deleted
    before it shipped. `Trend` is the only live caller today.
    """
    xs = list(prices)
    if len(xs) < 2:
        return None
    travelled = sum(abs(b - a) for a, b in itertools.pairwise(xs))
    return abs(xs[-1] - xs[0]) / travelled if travelled > 0 else None


@dataclass(slots=True)
class Trend(Indicator, Restorable):
    """Efficiency of recent level prices on one feed and interval."""

    window: int = WINDOW
    seen: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))

    # ---------------------------------------------------- the engine's path
    #: Which float of a bar this reads when the Nautilus engine feeds it.
    #: Unused when a caller drives `observe` directly. See `bars.Reading`.
    source: Reading = Reading.CLOSE
    #: One volatility unit in price, fixed. Zero takes the unit off each bar
    #: through `unit_from` instead, which is the default.
    unit: float = 0.0
    #: Where a per-bar unit comes from. The **range**, because the range-based
    #: estimator beats close-to-close as a volatility driver: the range-vs-close
    #: ratio reads 0.648 within strata on FX and 0.667 on 371 of 392 equities,
    #: and it grows as the window shortens - which is the regime a one-bar unit
    #: is in. `candle-screen.md` in research/docs.
    unit_from: Reading | None = Reading.RANGE
    #: EWMA half-life in bars for `unit_from`. Zero uses each bar's own
    #: reading, which is noisier but carries no warmup.
    unit_span: int = 0
    _bar_prev: float | None = field(default=None, repr=False)
    _bar_scale: float = field(default=0.0, repr=False)

    #: The fields a reset keeps. Everything else is state.
    _CONFIG: ClassVar[frozenset[str]] = frozenset(
        {"window", "source", "unit", "unit_from", "unit_span"}
    )

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen an observation.

        Called when the engine rewinds. Every field outside `_CONFIG`
        goes back to its initial value - see `bars.reset_state`.
        """
        reset_state(self, self._CONFIG)
        self._set_has_inputs(False)
        self._set_initialized(False)

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point, once registered for a bar type.

        Efficiency is a ratio of net travel to gross, so it is already
        dimensionless: the per-bar scale is computed and thrown away, which is
        what the `_` is. `unit_from` is still required, because `check_scale`
        uses it to catch a reading fed in the wrong dimension, and that is a
        different error from a missing unit.
        """
        value, _ = bar_input(self, bar)
        if value is None:
            return
        self._set_has_inputs(True)
        self.observe(value)
        if not self.initialized and self.efficiency is not None:
            self._set_initialized(True)

    def __post_init__(self) -> None:
        """Give the deque the window it was actually asked for.

        `default_factory` cannot see the instance, so it always built a
        twelve-deep window whatever `window` said - the parameter existed, was
        accepted, and did nothing. A caller asking for twenty-four got twelve
        and no error, which is the shape of bug that survives because every
        test that would catch it passes for the wrong reason.
        """
        if self.seen.maxlen != self.window:
            self.seen = deque(self.seen, maxlen=max(1, self.window))
        Indicator.__init__(self, [self.window, self.source])
        check_scale(type(self).__name__, self.source, self.unit, self.unit_from)

    def observe(self, level: float) -> None:
        """Fold in a level. Call *after* reading, never before."""
        self.seen.append(float(level))

    @property
    def efficiency(self) -> float | None:
        """0 ranges, 1 trends, None when there is not enough to say."""
        if len(self.seen) < FEWEST:
            return None
        return ratio(self.seen)

    def scale(self, span: float) -> float:
        """A sizing multiplier from the trend context, centred on 1.

        See `structures-context-trend.md` in research/docs.
        """
        if span <= 0:
            return 1.0
        ratio = self.efficiency
        if ratio is None:
            return 1.0
        return 1.0 + span * (2.0 * ratio - 1.0)


# ==========================================================================
# the trendlines
# ==========================================================================

REACH = 3

#: Confirmed pivots kept per side. Two are needed for a line; more let the fit
#: be least-squares rather than a chord through the latest pair, which is less
#: sensitive to one bad extreme.
PIVOT_KEEP = 6

#: Pivots the fit uses. Two is the chord a reader draws; more is a regression
#: through the pivots, which is not the same line and is steadier.
FIT_PIVOTS = 3

#: Bars kept, which has to exceed `2 * REACH + 1` for any pivot to confirm.
PIVOT_SPAN = 120


@dataclass(frozen=True, slots=True)
class Pivot:
    """One confirmed reversal, with both of its times.

    `when` is when the extreme printed and `confirmed` is when it could first
    be known. The gap between them is `reach` bars, and keeping both is what
    lets a caller check that a study used the second one.
    """

    #: +1 for a pivot high, -1 for a pivot low.
    side: int
    price: float
    #: Unix seconds of the bar holding the extreme.
    when: float
    #: Unix seconds of the bar that confirmed it.
    confirmed: float

    @property
    def lag(self) -> float:
        """Hours between the extreme and knowing about it."""
        return max(0.0, (self.confirmed - self.when) / 3_600.0)


@dataclass(frozen=True, slots=True)
class Trendline:
    """A line in (seconds, price), fitted through confirmed pivots."""

    #: +1 joins pivot highs (resistance), -1 joins pivot lows (support).
    side: int
    #: Price per second, and the price at `anchor`.
    gradient: float
    intercept: float
    #: Unix seconds the intercept is quoted at: the newest pivot in the fit.
    anchor: float
    #: How many pivots the fit used.
    points: int

    def at(self, when: float) -> float:
        """Where the line is at `when`, extrapolating freely.

        A trendline is *used* extrapolated - that is what makes it a line
        rather than a list of pivots - so this does not refuse to, and a caller
        that cares how far it has been extended reads `anchor`.
        """
        return self.intercept + self.gradient * (when - self.anchor)

    def per_hour(self) -> float:
        """The gradient in price per hour, which is the readable unit."""
        return self.gradient * 3_600.0


def pivots(
    window: Sequence[tuple[float, float, float]],
    reach: int = REACH,
    *,
    reach_up: int = 0,
    reach_down: int = 0,
) -> list[Pivot]:
    """Confirmed pivots in `window`, oldest first.

    `window` is `(high, low, when)` per bar, oldest first. A bar is a pivot
    high when no bar within `reach` either side printed a higher high, and the
    confirmation time is the bar `reach` later - which is why the last `reach`
    bars never produce one.

    Ties go to **neither**: a flat top of two equal highs is not a reversal,
    and admitting it would let a sideways stretch produce a pivot every bar.

    `reach_up` and `reach_down` take a different lookback per side, zero
    meaning "use `reach`". **Measured null** on the BOS rule over six feeds, 75
    trades: a 3x3 reach grid's best asymmetric cell beat its best symmetric one
    by -0.285R pooled while the side-reversed mirror, which has no asymmetry in
    it, gained more on 5 of 6 instruments - so the gain is the max of six noisy
    cells. The mirror's own gains run +0.117 to +0.692R, which is where the
    test goes blind. See `research/docs/smc-bos-reconcile.md`.

    **Zero on both is arithmetically identical to the version without them.**
    That is the only safe default: a pair of windows is `k**2` cells and not
    `2k`, because a confirmed high and a confirmed low both feed one trend
    label, so an asymmetric default would be two confounded parameters wearing
    one name.
    """
    up = reach_up or reach
    down = reach_down or reach
    if min(up, down) < 1:
        # Refused, not clamped: at a reach below one `range(i - up, i + up + 1)`
        # is empty, `all(...)` of nothing is True, and every bar in the window
        # is nominated a pivot - a detector that fires on everything.
        raise ValueError(f"a pivot needs at least one bar each side, not {min(up, down)}")
    out: list[Pivot] = []
    n = len(window)
    for i in range(min(up, down), n - min(up, down)):
        high, low, when = window[i]
        if (
            up <= i < n - up
            # The confirmation is that side's own bar, so an asymmetric pair
            # dates a high and a low found on one bar to different moments -
            # which is the whole content of the asymmetry and the easiest
            # thing to lose by taking one `confirmed` for both.
            and all(window[k][0] < high for k in range(i - up, i + up + 1) if k != i)
        ):
            out.append(Pivot(side=1, price=high, when=when, confirmed=window[i + up][2]))
        if down <= i < n - down and all(
            window[k][1] > low for k in range(i - down, i + down + 1) if k != i
        ):
            out.append(Pivot(side=-1, price=low, when=when, confirmed=window[i + down][2]))
    return out


def fit_line(found: Sequence[Pivot], *, use: int = FIT_PIVOTS) -> Trendline | None:
    """A least-squares line through the newest `use` pivots, or None.

    None below two points: one pivot is a level, not a line. With exactly two
    this is the chord through them, which is what a reader draws; with more it
    is a regression, which is steadier and is not the same line - so `points`
    records which was used.

    Time is re-centred on the newest pivot before the fit. Unix seconds are
    around 1.8e9 and prices are around 1, so a raw fit squares that ratio into
    the normal equations and loses the gradient to rounding.
    """
    if len(found) < 2:
        return None
    taken = list(found)[-max(2, use) :]
    anchor = taken[-1].when
    xs = [p.when - anchor for p in taken]
    ys = [p.price for p in taken]
    n = float(len(taken))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0.0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    gradient = sxy / sxx
    return Trendline(
        side=taken[-1].side,
        gradient=gradient,
        intercept=mean_y + gradient * (0.0 - mean_x),
        anchor=anchor,
        points=len(taken),
    )


class Trendlines(Indicator):
    """Support and resistance lines through confirmed pivots, one bar at a time.

    Registered with `Actor.register_indicator_for_bars` or the identical method
    on `Strategy`. Distances are reported in volatility units through
    `bars.bar_input`, so `distance_vol` means the same thing on gold as on
    EURUSD.
    """

    def __init__(
        self,
        *,
        reach: int = REACH,
        keep: int = PIVOT_KEEP,
        use: int = FIT_PIVOTS,
        span: int = PIVOT_SPAN,
        source: Reading = Reading.CLOSE,
        unit: float = 0.0,
        unit_from: Reading | None = Reading.RANGE,
        unit_span: int = 0,
    ) -> None:
        check_scale(type(self).__name__, source, unit, unit_from)
        if reach < 1:
            raise ValueError(
                f"reach={reach} confirms a pivot with no bars either side, "
                f"which makes every bar a pivot."
            )
        if span < 2 * reach + 1:
            raise ValueError(
                f"span={span} cannot hold a pivot at reach={reach}: a "
                f"confirmation needs {2 * reach + 1} bars, so no pivot would "
                f"ever be found and both lines would stay None forever."
            )
        super().__init__([reach, keep, use, span])
        self.reach = int(reach)
        self.keep = int(keep)
        self.use = int(use)
        self.span = int(span)
        self.source = source
        self.unit = float(unit)
        self.unit_from = unit_from
        self.unit_span = int(unit_span)
        self._bar_prev: float | None = None
        self._bar_scale = 0.0
        self._window: deque[tuple[float, float, float]] = deque(maxlen=self.span)
        self._highs: deque[Pivot] = deque(maxlen=self.keep)
        self._lows: deque[Pivot] = deque(maxlen=self.keep)
        self._seen: set[float] = set()
        self.price = 0.0
        self.when = 0.0
        self.resistance: Trendline | None = None
        self.support: Trendline | None = None
        self._broke = 0
        self._held = 0

    # ------------------------------------------------------------- the engine

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. `ts_event` is the bar's close.

        A pivot is added once and never revised. The scan runs over the whole
        window each bar and `_seen` drops the ones already held, rather than
        trusting that the scan returns them in a stable order - a pivot that
        reappeared with a different confirmation time would quietly re-date
        itself, and a re-dated pivot is the lookahead this module exists to
        avoid.
        """
        bar_input(self, bar)
        self.price = float(bar.close)
        self.when = bar.ts_event / NANOS
        self._window.append((float(bar.high), float(bar.low), self.when))
        self._set_has_inputs(True)
        for pivot in pivots(self._window, self.reach):
            if pivot.when in self._seen:
                continue
            self._seen.add(pivot.when)
            (self._highs if pivot.side > 0 else self._lows).append(pivot)
        self._seen = {p.when for p in (*self._highs, *self._lows)}
        self.resistance = fit_line(self._highs, use=self.use)
        self.support = fit_line(self._lows, use=self.use)
        self._breakout()
        if not self.initialized and self.resistance is not None and self.support is not None:
            self._set_initialized(True)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a bar."""
        self._window.clear()
        self._highs.clear()
        self._lows.clear()
        self._seen.clear()
        self.price = 0.0
        self.when = 0.0
        self.resistance = None
        self.support = None
        self._broke = 0
        self._held = 0
        self._bar_prev = None
        self._bar_scale = 0.0
        self._set_has_inputs(False)
        self._set_initialized(False)

    # ------------------------------------------------------------ the reading

    @property
    def highs(self) -> tuple[Pivot, ...]:
        """Confirmed pivot highs held, oldest first."""
        return tuple(self._highs)

    @property
    def lows(self) -> tuple[Pivot, ...]:
        """Confirmed pivot lows held, oldest first."""
        return tuple(self._lows)

    def distance_vol(self, line: Trendline | None) -> float | None:
        """Signed distance from price to `line` now, in volatility units.

        Positive when price is above the line. None without a line or a scale,
        rather than 0.0: a zero would read later as "price was on the line",
        which is the opposite of "there was no line".
        """
        if line is None or self._bar_scale <= 0.0:
            return None
        return (self.price - line.at(self.when)) / self._bar_scale

    @property
    def inside(self) -> bool | None:
        """Is price between the two lines? None until both exist."""
        if self.support is None or self.resistance is None:
            return None
        return self.support.at(self.when) <= self.price <= self.resistance.at(self.when)

    @property
    def spread_vol(self) -> float | None:
        """Width between the lines now, in volatility units.

        Negative when they have crossed, which is a real shape and not an
        error: two lines fitted independently through different pivots converge
        and then cross, and the crossing is the apex a reader would draw.
        """
        if self.support is None or self.resistance is None or self._bar_scale <= 0.0:
            return None
        return (self.resistance.at(self.when) - self.support.at(self.when)) / self._bar_scale

    @property
    def converging(self) -> bool | None:
        """Are the lines closing on each other? None until both exist."""
        if self.support is None or self.resistance is None:
            return None
        return self.resistance.gradient < self.support.gradient

    # ----------------------------------------------------------- the breakout

    @property
    def broke(self) -> int:
        """+1 through resistance, -1 through support, 0 neither.

        **A close, not a touch.** A wick through a line and back is the shape
        the line was drawn to describe - price reached the level and was
        rejected there - so counting it as a break makes the reading fire on
        exactly the bars that confirm the line instead of the ones that end it.

        A break is reported for as long as price stays past the line, not once
        at the crossing. `held` is how many consecutive bars that has been, and
        a caller wanting the crossing alone reads `held == 1`.
        """
        return self._broke

    @property
    def held(self) -> int:
        """Consecutive bars closed past a line, in the `broke` direction.

        0 when there is no break. The desk's own measurement of the nearest
        primitive, in `order-block-zones.md` in research/docs: of 6,008
        displacements at 4h, 889 closed past the 20-bar high (14.8%) and only
        515 **held** (8.6%). So two in five crossings do not hold, and a
        reading that counted the crossing alone would be 1.7 times the number
        that matters. Measured on a 20-bar high after a displacement rather
        than on a trendline, which is why it is the primitive this feeds and
        not this.
        """
        return self._held

    @property
    def extent_vol(self) -> float | None:
        """How far past the broken line price has closed, in volatility units.

        Always non-negative when there is a break. None when there is none, or
        without a scale - not 0.0, which would read as "it broke by nothing".
        """
        if not self._broke or self._bar_scale <= 0.0:
            return None
        line = self.resistance if self._broke > 0 else self.support
        if line is None:
            return None
        return abs(self.price - line.at(self.when)) / self._bar_scale

    def _breakout(self) -> None:
        """Update the break state from this bar's close.

        Called from `handle_bar` **after** the lines are refitted, so a break
        is measured against the line as it stands now. Refitting can move a
        line past price and end a break without price moving, which is
        correct: a line that a newly confirmed pivot has redrawn above price
        was not broken, and carrying the old break forward would be a reading
        about a line that no longer exists.
        """
        side = 0
        if self.resistance is not None and self.price > self.resistance.at(self.when):
            side = 1
        elif self.support is not None and self.price < self.support.at(self.when):
            side = -1
        self._held = self._held + 1 if side and side == self._broke else (1 if side else 0)
        self._broke = side


# ==========================================================================
# the regression channel
# ==========================================================================

NAN = float("nan")

#: Bars in the fit. **100, which is the reference indicator's own default** -
#: see `research/docs/lrc-retest.md`, where the two TradingView scripts this
#: module was asked for are recorded as `len` 100, 200 and 50.
#:
#: It was 20 when this module was written, chosen because 20 bars is one
#: trading hour on a 3m chart and most of this desk's entries are 5m or faster.
#: That was a reasonable guess and it was still a guess, and the scripts the
#: desk actually reads were specified afterwards. A number taken from the
#: indicator a human is looking at is worth more than a number taken from my
#: reasoning about holding periods, because the point of publishing these is to
#: compare them against what the chart says.
SPAN = 100

#: The three reference lengths, fitted together. A trend that only exists at one
#: window is a property of the window, and the cheapest way to see that is to
#: report all three rather than to pick one and hope.
SPANS: tuple[int, ...] = (50, 100, 200)

#: Bars for the true-range average that normalises the slope. Fourteen is the
#: conventional ATR window and is used here for the same reason the rest of
#: this file states its constants: so the number is arguable, not implicit.
ATR_SPAN = 14

#: Flat and steep, **in volatility units across the whole window** rather than
#: per bar. Per bar was the original form and it does not survive a change of
#: span: 0.05 a bar is one unit over 20 bars and five units over 100, so
#: lengthening the window silently moved the thresholds by 5x. Stating the
#: across-window figure and dividing by `span` keeps the meaning the original
#: comments described - "one whole unit" and "four units across the window" -
#: whatever the window is.
#:
#: Still unmeasured against outcomes. Unlike `MIN_R2` these have no reference
#: value to borrow, because the scripts colour a slope rather than thresholding
#: it.
FLAT_ACROSS = 1.0
STRONG_ACROSS = 4.0

#: The same two at the default span, kept as module constants because that is
#: how callers without a span in hand read them.
FLAT_VOL = FLAT_ACROSS / SPAN
STRONG_VOL = STRONG_ACROSS / SPAN

#: Below this r-squared the slope is not describing the bars it was fitted to,
#: and the arrow should say so rather than point confidently at noise.
#:
#: **0.64, which is the reference's |R| > 0.8 squared.** DGT's script calls a
#: trend usable at a correlation of 0.8 and r-squared is that correlation
#: squared, so the two thresholds are the same threshold written in different
#: units - see `research/docs/lrc-retest.md`.
#:
#: It was 0.25 here, which is a far weaker line: a quarter of the variance
#: explained. That was deliberately permissive and aimed only at catching fits
#: that explain nothing, which is a different job from "is this a trend".
MIN_R2 = 0.64

#: Glyphs for the five states. Triangles rather than words because these land in
#: an alert line beside the emoji the other cards use, and a reader scanning a
#: phone notification sees a shape before they read a number.
RISING_FAST = "▲▲"
RISING = "▲"
FLAT = "▬"
FALLING = "▼"
FALLING_FAST = "▼▼"


@dataclass(frozen=True, slots=True)
class Channel:
    """One least-squares fit over a window of closes.

    `intercept` is the fitted value at the **first** bar of the window and
    `slope` is per bar, so `at(span - 1)` is the line's value at the most recent
    close. Anchoring at the window start rather than at some absolute time keeps
    the two numbers independent of when the fit was taken.
    """

    slope: float
    intercept: float
    #: Standard error of the residuals: the channel's half-width at one sigma.
    stderr: float
    r2: float
    span: int

    @property
    def correlation(self) -> float:
        """Pearson's r for the fit, **signed** - the reference script's `R`.

        `r2` loses the direction, and the direction is in `slope`, so nothing
        needed this until the threshold had to be stated in the same units the
        indicator states it in: DGT's script tests `|R| > 0.8`, which is
        `r2 > 0.64`.

        See the note on `slope` in this module's docstring for why there is no
        second slope calculation to go with this: `r * stdev(y) / stdev(x)` is
        the least-squares slope, exactly, so the script's two formulations are
        one number.
        """
        root = math.sqrt(self.r2) if self.r2 > 0 else 0.0
        return -root if self.slope < 0 else root

    @property
    def last(self) -> float:
        """The line's value at the most recent close in the window."""
        return self.at(self.span - 1)

    def at(self, i: int) -> float:
        """The fitted value `i` bars after the window's first bar."""
        return self.intercept + self.slope * i

    def band(self, k: float = 2.0) -> tuple[float, float]:
        """Channel edges at the most recent close, `k` residual sigmas out."""
        half = abs(k) * self.stderr
        return self.last - half, self.last + half

    def place(self, price: float) -> float:
        """Where `price` sits in the channel, in residual sigmas.

        Zero is on the line, +1 is one sigma above it. Returns NaN when the fit
        has no residual spread at all, which happens on a perfectly straight
        series and means "the channel has no width", not "price is on the line".
        """
        if not self.stderr > 0:
            return NAN
        return (price - self.last) / self.stderr


def true_ranges(bars: Sequence[Ohlc]) -> list[float]:
    """True range per bar. The first has no previous close, so it is its range."""
    out: list[float] = []
    for i, b in enumerate(bars):
        span = b.high - b.low
        if i:
            previous = bars[i - 1].close
            span = max(span, abs(b.high - previous), abs(b.low - previous))
        out.append(span)
    return out


def atr(bars: Sequence[Ohlc], n: int = ATR_SPAN) -> float:
    """Mean true range over the last `n` bars, or NaN if there are not enough.

    A simple mean rather than Wilder's smoothing: this is a scale for dividing a
    slope by, not a published indicator anybody is going to compare against a
    chart, and the two differ by less than the thresholds above are specified to.
    """
    if n <= 0 or len(bars) < n:
        return NAN
    window = true_ranges(bars[-n:])
    return sum(window) / float(n)


def fit(bars: Sequence[Ohlc], span: int = SPAN) -> Channel | None:
    """Least squares on the last `span` closes, or None if it cannot be fitted.

    None rather than a Channel full of NaN, because every caller has to make a
    decision about an absent fit and a sentinel object invites arithmetic that
    silently produces nothing. Three bars is the floor: `stderr` divides by
    `span - 2`, so two bars fit a line through both points with no residual
    degrees of freedom and no honest channel width.
    """
    if span < 3 or len(bars) < span:
        return None
    closes = [float(b.close) for b in bars[-span:]]
    n = float(span)
    # x is 0..span-1, so the sums are closed forms rather than loops, and the
    # variance of x can never be zero for span >= 2.
    mean_x = (n - 1.0) / 2.0
    mean_y = sum(closes) / n
    var_x = 0.0
    cov = 0.0
    for i, y in enumerate(closes):
        dx = i - mean_x
        var_x += dx * dx
        cov += dx * (y - mean_y)
    if not var_x > 0:
        return None
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    residuals = 0.0
    var_y = 0.0
    for i, y in enumerate(closes):
        residual = y - (intercept + slope * i)
        residuals += residual * residual
        dy = y - mean_y
        var_y += dy * dy
    # A flat series explains none of a variance that is itself zero. Calling
    # that a perfect fit would let `r2` certify a line through identical closes.
    r2 = 1.0 - residuals / var_y if var_y > 0 else 0.0
    stderr = math.sqrt(residuals / (n - 2.0)) if residuals > 0 else 0.0
    return Channel(slope=slope, intercept=intercept, stderr=stderr, r2=r2, span=span)


def slope_vol(channel: Channel | None, unit: float) -> float:
    """The slope in volatility units per bar, given one unit of price.

    `unit` is whatever the caller already uses as one volatility unit -
    `risk.sizing.price_distance(spot, vol_bps, 1.0)` is the one a strategy
    would have, and `atr` is here for callers that have bars but no signal. NaN
    when there is no scale to divide by, which is the honest answer and not
    zero: zero would read as "flat".
    """
    if channel is None or not unit > 0 or math.isnan(unit):
        return NAN
    return channel.slope / unit


def flat_vol(span: int = SPAN) -> float:
    """`FLAT_ACROSS` as a per-bar slope at this span."""
    return FLAT_ACROSS / float(span) if span > 0 else NAN


def strong_vol(span: int = SPAN) -> float:
    """`STRONG_ACROSS` as a per-bar slope at this span."""
    return STRONG_ACROSS / float(span) if span > 0 else NAN


def arrow(slope: float, r2: float = 1.0, span: int = SPAN) -> str:
    """The glyph for a slope in volatility units per bar.

    A fit that explains less than `MIN_R2` of its own window reads flat whatever
    its slope, because the slope of a cloud is not a direction. An absent
    reading reads flat too - the alert says "no trend", which is what an unknown
    trend means to someone looking at it.

    `span` because the thresholds are stated across the window: the same per-bar
    slope is a gentle drift over 200 bars and a steep line over 50.
    """
    if math.isnan(slope) or math.isnan(r2) or r2 < MIN_R2:
        return FLAT
    steep, gentle = strong_vol(span), flat_vol(span)
    if slope >= steep:
        return RISING_FAST
    if slope >= gentle:
        return RISING
    if slope <= -steep:
        return FALLING_FAST
    if slope <= -gentle:
        return FALLING
    return FLAT


def agrees(slope: float, r2: float, buying: bool, span: int = SPAN) -> bool | None:
    """Whether a trade in this direction runs with the line.

    None when there is no usable fit, and that is deliberately not False: a gate
    reading this has to distinguish "the trend is against you" from "there is no
    trend reading", and the two have produced the same refusal in this repo
    before.
    """
    if math.isnan(slope) or math.isnan(r2) or r2 < MIN_R2:
        return None
    if abs(slope) < flat_vol(span):
        return None
    return (slope > 0) == buying


def features(
    bars: Sequence[Ohlc],
    *,
    unit: float = 0.0,
    span: int = SPAN,
    step: int = 0,
) -> dict[str, float]:
    """The fit as journal features, named so they can be scored later.

    `unit` of zero falls back to `atr`, so a caller with bars and no signal
    still gets comparable numbers. `step` is how far back the earlier fit is
    taken for the acceleration; zero means a quarter of the window, which is the
    shortest shift that moves the fit by more than one bar on the default span.

    Empty when there is no fit. A partial dict of NaNs would be written to the
    journal on every decision and read, later, as a measurement.
    """
    channel = fit(bars, span)
    if channel is None:
        return {}
    scale = unit if unit > 0 else atr(bars)
    if not scale > 0 or math.isnan(scale):
        return {}
    per_bar = slope_vol(channel, scale)
    out = {
        "regression_slope_vol": per_bar,
        "regression_r2": channel.r2,
        # Signed, and the reference's own threshold unit: the script tests
        # |R| > 0.8 where this file tests r2 > 0.64. Published beside r2 rather
        # than instead of it so a reading can be compared with either.
        "regression_correlation": channel.correlation,
        "regression_span": float(channel.span),
        # The channel's half-width in volatility units: how wide the line's own
        # error is, which is the scale any "price left the channel" test needs.
        "regression_width_vol": channel.stderr / scale,
        # Where the latest close sits, in sigmas. The close rather than the mid,
        # because the fit is on closes and mixing the two would put price
        # systematically off its own line by half a spread.
        "regression_place": channel.place(float(bars[-1].close)),
    }
    back = step if step > 0 else max(1, span // 4)
    if len(bars) >= span + back:
        earlier = fit(bars[: len(bars) - back], span)
        if earlier is not None:
            was = slope_vol(earlier, scale)
            if not math.isnan(was) and not math.isnan(per_bar):
                # Signed change in the slope, not its absolute value: a line
                # that is falling less steeply and one that is rising faster are
                # different events and a magnitude cannot tell them apart.
                out["regression_accel_vol"] = per_bar - was
    return out


def features_across(
    bars: Sequence[Ohlc],
    *,
    unit: float = 0.0,
    spans: Sequence[int] = SPANS,
    step: int = 0,
) -> dict[str, float]:
    """`features` at each reference length, the default span unsuffixed.

    `SPAN` keeps the bare `regression_*` names so `card_line` and anything else
    reading one fit is unaffected; the other lengths are suffixed with their own
    span - `regression_slope_vol_50`, `regression_r2_200`.

    Three windows rather than one because a slope that only exists at one length
    is a property of the length. Nothing here compares them: the comparison is
    the point of writing all three to the journal, and it is a question for the
    record rather than for this function.

    Empty when not one of the spans could be fitted, for the same reason
    `features` is empty rather than NaN-filled.
    """
    out: dict[str, float] = {}
    for span in sorted({int(s) for s in spans}):
        got = features(bars, unit=unit, span=span, step=step)
        if not got:
            continue
        if span == SPAN:
            out.update(got)
        else:
            out.update({f"{k}_{span}": v for k, v in got.items()})
    return out


def card_line(got: dict[str, float]) -> list[str]:
    """The trend line for an alert card, or nothing when there is no fit.

    A list rather than a string, and empty rather than a placeholder, so this
    composes with the other card lines - `levels.card_line` is the other one -
    every one of them contributing zero or more lines and the caller dropping
    the empties. The caller that did the composing was `_announce_fill`, which
    retired to `research/retire/strategies/service.py`; nothing in the live
    tree calls either `card_line` yet.
    """
    slope = got.get("regression_slope_vol")
    r2 = got.get("regression_r2")
    if slope is None or r2 is None:
        return []
    slope = float(slope)
    r2 = float(r2)
    if math.isnan(slope) or math.isnan(r2):
        return []
    span = int(float(got.get("regression_span") or SPAN))
    glyph = arrow(slope, r2, span)
    # The slope is quoted per bar and across the window, because per bar is the
    # comparable number and across the window is the one a reader can see on a
    # chart. Stating only the first has had people read 0.08 as "nothing".
    across = slope * float(span)
    line = f"{glyph} trend {slope:+.3f}v/bar ({across:+.1f}v over {span}) · r² {r2:.2f}"
    place = got.get("regression_place")
    if place is not None and not math.isnan(float(place)):
        line += f" · {float(place):+.1f}sd in channel"
    accel = got.get("regression_accel_vol")
    if accel is not None and not math.isnan(float(accel)):
        line += f" · {'steepening' if float(accel) * slope > 0 else 'easing'}"
    return [line]


# ==========================================================================
# the variance ratio
# ==========================================================================

#: Horizon the ratio is taken at, in observations. `VR(q)` compares the
#: variance of `q`-period returns with `q` times the variance of one-period
#: returns, so `q` is the horizon the question is asked over.
VR_HORIZON = 5

#: Observations kept. Twenty times the horizon, which is `VR_LEAST`.
VR_WINDOW = 200

#: Observations per unit of horizon, at least.
#:
#: **Measured, not chosen - but the measurement was never written up.** These
#: figures appear nowhere in `research/docs` or `docs`; the only thing outside
#: this comment that pins any of them is
#: `test_a_sweep_beyond_the_usable_range_returns_nothing`, which records the
#: 0.908 at a `q/n` of 0.1 on one series. Treat the table as a note of a
#: simulation nobody can re-run from here.
#:
#: Even with Lo and MacKinlay's unbiased estimator a residual downward bias
#: remains, and it scales as roughly `q/n`. Over 20 random walks, where the
#: answer is 1:
#:
#: | q/n | mean VR |
#: |---|---|
#: | 0.010 | 0.990 |
#: | 0.025 | 0.962 to 0.988 |
#: | 0.050 | 0.926 to 0.956 |
#: | 0.100 | 0.908 |
#:
#: So 20 keeps `q/n` at 0.05 and the bias under about 5%. The first version of
#: this guard allowed four, which is a `q/n` of 0.25 - and a sweep at that
#: ratio reads a pure random walk as strongly mean reverting, which is the
#: overlap artefact this desk already has on record from permutation nulls.
#:
#: **The bias is downward**, so a reading below one is the direction to
#: distrust and a reading above one is the direction to believe.
VR_LEAST = 20


class VarianceRatio(Indicator):
    """Lo and MacKinlay's variance ratio: is this a walk, a trend, or reverting?

    `VR(q) = Var(r_q) / (q * Var(r_1))`, where `r_q` is the `q`-period return.
    Under a random walk the variance of a sum is the sum of the variances, so
    **VR = 1 exactly** - which is why this is the one trend statistic here with
    a null rather than a convention.

    | | means |
    |---|---|
    | **VR < 1** | reverting - the `q`-period move is smaller, so steps cancel |
    | **VR = 1** | a walk - the steps are independent |
    | **VR > 1** | trending - the steps reinforce |

    ## Why this and not `ratio`

    `trend.ratio` - Kaufman's efficiency - answers the same question as a
    **heuristic**: net travel over gross, bounded in [0, 1], with no null and
    no sampling distribution. It is readable and it cannot be tested. The
    variance ratio can: `z` below is Lo-MacKinlay's standardised statistic
    under the homoscedastic null, so "is this trending" becomes a number with a
    reference point rather than a number with a threshold somebody chose.

    Keep both. Efficiency is what a reader looks at; this is what a claim is
    checked against.

    ## It is already the desk's regime definition, un-named

    `statespace/switching.py` represents exactly three regimes - balance,
    imbalance, trending - and its own docstring says they are *the three things
    the variance ratio can say*: "an integrated state has VR = 1 by
    construction and a trend does not". A companion measurement put the traded
    ratio at **0.980 falling to 0.924 across horizons against 1.000 on an
    i.i.d. control**, so the three states are things the data distinguishes.
    That figure is carried in `statespace/switching.py`'s own docstring and
    nowhere in `research/docs`, so it is a sibling's note rather than a
    write-up anybody can check.

    What was missing was anything that computed it. The switching member
    infers the regime through a mixture; this reports the statistic.

    **Expect numbers near one.** 0.980 to 0.924 is the traded range, so a
    reading of 1.4 is a bug or a tiny sample before it is a trend.

    ## The null is homoscedastic, and markets are not

    `z` assumes constant variance. Volatility clusters, which inflates the
    statistic's variance and makes `z` **anti-conservative** - too ready to
    call a walk a trend. Lo and MacKinlay give a heteroscedasticity-robust
    version; this does not implement it, and `z` is therefore an upper bound on
    the evidence rather than a p-value. Said here rather than discovered later.
    """

    def __init__(
        self,
        *,
        horizon: int = VR_HORIZON,
        window: int = VR_WINDOW,
        source: Reading = Reading.LOG_RETURN,
        unit: float = 0.0,
        unit_from: Reading | None = Reading.RELATIVE_RANGE,
        unit_span: int = 0,
    ) -> None:
        check_scale(type(self).__name__, source, unit, unit_from)
        if horizon < 2:
            raise ValueError(
                f"horizon={horizon} compares one-period returns with "
                f"themselves, which is 1 by construction."
            )
        if window < horizon * VR_LEAST:
            raise ValueError(
                f"window={window} at horizon={horizon} is a q/n of "
                f"{horizon / window:.3f}, and the estimator's residual bias is "
                f"about q/n: measured over 20 random walks it reads 0.908 at "
                f"0.100 and 0.962 to 0.988 at 0.025. Use a window of at least "
                f"{horizon * VR_LEAST}, or a shorter horizon."
            )
        super().__init__([horizon, window, source])
        self.horizon = int(horizon)
        self.window = int(window)
        self.source = source
        self.unit = float(unit)
        self.unit_from = unit_from
        self.unit_span = int(unit_span)
        self._bar_prev: float | None = None
        self._bar_scale = 0.0
        self._fed = ""
        self._values: deque[float] = deque(maxlen=self.window)

    # ------------------------------------------------------------- the engine

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. Scale-free, so the unit is read and unused.

        The ratio is a ratio of variances of the *same* series, so any common
        scaling cancels - which is the property that lets it compare a currency
        with gold without a volatility unit. `unit_from` is still required for
        the dimension check, because a reading fed levels where it expects
        returns is a different error and that check catches it.
        """
        check_feed(self, "bars")
        value, _ = bar_input(self, bar)
        if value is None:
            return
        self._values.append(value)
        self._set_has_inputs(True)
        if not self.initialized and len(self._values) >= self.window:
            self._set_initialized(True)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a bar."""
        self._values.clear()
        self._bar_prev = None
        self._bar_scale = 0.0
        self._fed = ""
        self._set_has_inputs(False)
        self._set_initialized(False)

    # ------------------------------------------------------------ the reading

    @property
    def value(self) -> float | None:
        """`VR(q)`, or None before there is enough to say.

        None rather than 1.0 on a short sample. One is the *null*, and
        returning it for "no data" would make an unwarmed indicator look like a
        confident finding of a random walk.
        """
        return self.at(self.horizon)

    def at(self, horizon: int) -> float | None:
        """`VR(q)` for an arbitrary `q`, so the ratio can be swept.

        **Overlapping `q`-period returns**, which is Lo-MacKinlay's own
        estimator and is deliberate: non-overlapping windows waste most of the
        sample. The cost is that the `q`-period returns are correlated by
        construction, which `z` accounts for through its `2(2q-1)(q-1)/3q`
        term - the same overlap this desk has been bitten by elsewhere, handled
        here because the statistic's author handled it.
        """
        values = list(self._values)
        n = len(values)
        if horizon < 2 or n < horizon * VR_LEAST:
            return None
        mean = sum(values) / n
        one = sum((v - mean) ** 2 for v in values) / (n - 1)
        if one <= 0.0:
            return None

        # **Lo and MacKinlay's unbiased overlapping estimator**, and the
        # correction is not cosmetic. The naive version - a sample variance of
        # the overlapping sums divided by `q` times the one-period variance -
        # reads **0.440 at q = 20 on a 200-observation random walk**, where the
        # answer is 1 - the figure
        # `test_a_sweep_beyond_the_usable_range_returns_nothing` records.
        # It would be reported as strong mean reversion and it is
        # the overlap, which is the artefact this desk already has on record
        # from permutation nulls on overlapping windows.
        #
        # The fix is the denominator: `m = q(n - q + 1)(1 - q/n)` rather than
        # the sum count, which is what makes the estimator unbiased under the
        # null. Deviations are taken from `q * mean`, not from the sums' own
        # mean, for the same reason - the null's mean is known.
        sums = [sum(values[i : i + horizon]) for i in range(n - horizon + 1)]
        m = horizon * (n - horizon + 1) * (1.0 - horizon / n)
        if m <= 0.0:
            return None
        many = sum((total - horizon * mean) ** 2 for total in sums) / m
        if many <= 0.0:
            return None
        return many / one

    @property
    def z(self) -> float | None:
        """`VR - 1` in standard errors, under the **homoscedastic** null.

        Lo-MacKinlay's asymptotic variance for the overlapping estimator is
        `2(2q - 1)(q - 1) / (3 * q * n)`. Positive is trending, negative
        reverting, and anything inside about two is a walk as far as this
        statistic can tell.

        **An upper bound on the evidence, not a p-value**: the null assumes
        constant variance and volatility clusters, which makes this
        anti-conservative. See the class docstring.
        """
        got = self.value
        n = len(self._values)
        if got is None or n <= 0:
            return None
        q = self.horizon
        variance = 2.0 * (2.0 * q - 1.0) * (q - 1.0) / (3.0 * q * n)
        if variance <= 0.0:
            return None
        return (got - 1.0) / math.sqrt(variance)

    @property
    def regime(self) -> str:
        """ "reverting", "walk" or "trending" - the three `switching.py` holds.

        `walk` wherever `z` is inside two, which is the honest middle: the
        middle state is pinned by theory - an integrated series has VR = 1 by
        construction - rather than estimated, and that is what gives the other
        two anchors.
        """
        got = self.z
        if got is None:
            return "walk"
        if got > 2.0:
            return "trending"
        return "reverting" if got < -2.0 else "walk"


def _variance(values: Sequence[float]) -> float:
    """Sample variance, zero below two observations."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return sum((v - mean) ** 2 for v in values) / (n - 1)
