"""Linear regression channel: the line price is on, how tight it is, which way it leans.

The desk has three readings of movement and none of them is a trend. `speeds`
keeps exponential averages of a *score*; `efficiency` is a ratio of net travel
to gross; `momentum_agree` counts how many timeframes nod. All three answer "is
something happening", and a strategy that wants to know "is price on a line,
and which way does the line point" has been reading them as a proxy for a
question they do not ask.

This module fits the line. Ordinary least squares on the last `span` closes,
with the three numbers that make a fit usable rather than decorative:

* the **slope**, reported in volatility units per bar and not price units per
  bar. A price-unit slope is not comparable between an index at 122,000 and a
  rate at 0.65, which is the same reason every other distance in this repo is
  measured in volatility units.
* **r-squared**, the share of variance the line explains. A slope quoted
  without it is the headline of a fit nobody checked: twenty bars of noise have
  a slope too, and it is as steep as the noise is loud.
* the **residual standard error**, which is the channel. Price inside its own
  channel is doing what the line says. Price outside it is either leaving, or
  the fit has expired and the line is describing a regime that ended.

**Why least squares rather than the slope of a moving average.** A moving
average's slope is a difference of two averages, so however many bars it
smooths it still answers a question about two points. The regression uses every
bar in the window *and* reports how well they agree - and that agreement is the
part a gate needs. The difference between "price rose" and "price has been
rising steadily" is precisely `r2`, and only the fit produces it.

## What is measured here and what is not

The arithmetic is arithmetic and the tests pin it against hand-computed fits.

**The thresholds are still not measured against outcomes**, but two of them are
no longer mine. `SPAN` and `MIN_R2` are now the reference indicators' own
values - 100 bars, and `|R| > 0.8` written as `r2 > 0.64` - recorded in
`research/docs/lrc-retest.md`. A number taken from the script a human is
actually looking at beats a number taken from my reasoning about holding
periods, because the whole point of publishing these is to compare them with
what the chart says. `FLAT_ACROSS` and `STRONG_ACROSS` have no reference value
to borrow, since the scripts colour a slope rather than thresholding it, and
they remain arguable constants stated out loud.

**On DGT's slope.** That script computes the slope as
`correlation * stdev(close) / stdev(bar_index)`, which looks like a second
method and is not one: `r * sigma_y / sigma_x` *is* the least-squares slope,
exactly, by the algebra of r. The two scripts the desk sent therefore compute
one number two ways. What was missing here was the correlation itself, because
`r2` discards the sign - so `Channel.correlation` reports it signed, in the
units the reference states its threshold in. There is no second slope
calculation because there is no second slope.

So this module **does not gate a trade**. It publishes features and renders an
arrow, and `Trader._read_the_trend` is what puts them on every decision - which
is the step that was missing, and the reason nothing could be scored. A gate
that reads them should be a separate, measured change, and should be weighed
against turning on `max_against_vol`, which is the momentum filter this
deployment already has and currently runs at 1.5.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .candles import Bar

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


def true_ranges(bars: Sequence[Bar]) -> list[float]:
    """True range per bar. The first has no previous close, so it is its range."""
    out: list[float] = []
    for i, b in enumerate(bars):
        span = b.high - b.low
        if i:
            previous = bars[i - 1].close
            span = max(span, abs(b.high - previous), abs(b.low - previous))
        out.append(span)
    return out


def atr(bars: Sequence[Bar], n: int = ATR_SPAN) -> float:
    """Mean true range over the last `n` bars, or NaN if there are not enough.

    A simple mean rather than Wilder's smoothing: this is a scale for dividing a
    slope by, not a published indicator anybody is going to compare against a
    chart, and the two differ by less than the thresholds above are specified to.
    """
    if n <= 0 or len(bars) < n:
        return NAN
    window = true_ranges(bars[-n:])
    return sum(window) / float(n)


def fit(bars: Sequence[Bar], span: int = SPAN) -> Channel | None:
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

    `unit` is whatever the caller already uses as one volatility unit - the
    strategies pass `price_distance(spot, vol_bps, 1.0)` and `atr` is here for
    callers that have bars but no signal. NaN when there is no scale to divide
    by, which is the honest answer and not zero: zero would read as "flat".
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
    bars: Sequence[Bar],
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
    bars: Sequence[Bar],
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
    composes with the other cards in `_announce_fill` - every one of them
    contributes zero or more lines and the caller drops the empties.
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
