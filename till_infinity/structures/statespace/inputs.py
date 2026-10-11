"""`B` and `u`: the input channel, with every window measured in **time**.

`I1` has said since this package started that "there is no input; `B` and `u` do
not exist here". This is that gap, and it is the one that stops a state space
conditioning on an arbitrary function of the past - "the highest high in a week",
"how long since this level was swept". Such a thing has nowhere to go in
`x' = A x`: either it becomes a state, which needs a dynamic for it, or it
arrives as an input.

## Windows are hours, never bars

Asked for 2026-10-11 and it is the right call. **"200 bars" is not a horizon, it
is a horizon times a timeframe**: ten hours at 3m, eight months at 1d. A feature
defined that way means something different on every series it is computed on,
and the comparison across timeframes that this package keeps making would be
comparing definitions rather than behaviour.

So a window here is `Window(hours=...)`, and the bar count is derived per series
from the bars actually seen. One week is one week at 3m and at 1d; the number of
bars differs and the meaning does not.

**A week is seven calendar days and `coverage` does the rest.** The first
version made `WEEK` five days, on the grounds that a trading week is five days
and the weekend is a closed market rather than a quiet one. That is right for
FX and **wrong for crypto and for the Deriv synthetics, which trade all seven**
- so a hardcoded five-day week silently shortened every crypto window by two
sevenths.

A constant cannot be right for both, and a per-symbol table would be another
thing to keep in step with reality. So the window is stated in **calendar**
hours - 168 for a week - and converted using the series' own **coverage**: the
share of calendar time it actually trades, inferred from its timestamps. FX
comes out near 5/7 and anything continuous near 1, and the same `Window(168)`
then spans five trading days on one and seven on the other, which is what "one
week" means in both cases.

## What an input is, and where it is weak

`B u` is a **known external force** on the state: known at prediction time,
not inferred from the measurement. The textbook cases here are the ones
`subjects.py` already names:

* **`INSTRUMENT`** - its family's move is a genuine exogenous driver. If the
  whole FX complex moves, a single pair's deviation from it has been pushed by
  something the model can be told about rather than having to infer.
* **`RELATION`** - the hedge ratio's own drift, likewise.

**For `LEVEL` the case is weaker and should be said so.** A level's position is
not obviously driven by anything external; the honest use there is not `B u` at
all but scaling the *process noise* with a volatility forecast, which is a
different mechanism and is `README.md`'s improvement 2. An input that cannot be
named is a state that has not been thought about - `I8`, "state, input or output
- the question a feature list never asks".

## Causality is the whole correctness of this

Every feature here is computed from bars **strictly before** the one it is
attached to. A window that includes the current bar leaks the present into a
prediction of the present, and the four-symbol harness has already shown what
that looks like: a 15m innovation attached to 3m bars from the same timestamp
produced `t = +20.8` on five symbols including a generated one.

So `at` takes the index it is being computed *for* and reads `[start:index]`,
never `[start:index + 1]`. There is a test for exactly that off-by-one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

#: Seconds in an hour, as everywhere else in this package.
HOUR = 3600.0

#: A week in **calendar** hours. Seven days, because that is what a week is;
#: how much of it a given market trades is `coverage`'s job and not a constant's.
WEEK = 7 * 24.0


@dataclass(frozen=True, slots=True)
class Window:
    """A lookback in hours, converted to bars per series rather than fixed.

    The conversion needs the bar length, which is read from the timestamps
    rather than declared - a series labelled 15m with gaps in it is 15m only on
    average, and the median spacing is what a window should be measured in.
    """

    hours: float
    name: str = ""

    def bars(self, bar_hours: float, coverage: float = 1.0) -> int:
        """How many bars this window spans, for a market open `coverage` of the time.

        `hours` is **calendar** time and `coverage` is the share of it this
        series trades, so one week is five trading days on FX and seven on
        crypto and the synthetics without either being a special case.
        """
        if bar_hours <= 0:
            return 0
        return max(round(self.hours * max(coverage, 0.0) / bar_hours), 1)

    def label(self) -> str:
        if self.name:
            return self.name
        if self.hours >= WEEK:
            return f"{self.hours / WEEK:g}w"
        if self.hours >= 24.0:
            return f"{self.hours / 24.0:g}d"
        return f"{self.hours:g}h"


#: The windows asked for: one to four weeks, portable by construction.
WEEKS = (
    Window(1 * WEEK, "1w"),
    Window(2 * WEEK, "2w"),
    Window(3 * WEEK, "3w"),
    Window(4 * WEEK, "4w"),
)

#: **The ladder, seconds to weeks.** A fixed set of windows cannot suit every
#: series: a one-week window is 2,400 bars at 3m and five at 1d, and a
#: one-minute window is a fifth of a bar at 5m and twelve bars at 5s. So the
#: ladder spans the whole range and `resolvable` picks the rungs a given series
#: can actually compute - which is the portable version of choosing a window,
#: where "200 bars" was the unportable one.
LADDER = (
    Window(10.0 / 3600.0, "10s"),
    Window(30.0 / 3600.0, "30s"),
    Window(1.0 / 60.0, "1m"),
    Window(5.0 / 60.0, "5m"),
    Window(15.0 / 60.0, "15m"),
    Window(30.0 / 60.0, "30m"),
    Window(1.0, "1h"),
    Window(4.0, "4h"),
    Window(12.0, "12h"),
    Window(24.0, "1d"),
    Window(3 * 24.0, "3d"),
    Window(1 * WEEK, "1w"),
    Window(2 * WEEK, "2w"),
    Window(4 * WEEK, "4w"),
)

#: Fewest bars a window must span to mean anything. Two, because one bar is the
#: bar itself and a "range" over it is that bar's own high and low - which is
#: already a feature and does not need a window to say so.
LEAST_BARS = 2


def resolvable(
    bar: float,
    length: int,
    ladder: tuple[Window, ...] = LADDER,
    share: float = 0.25,
) -> tuple[Window, ...]:
    """The rungs this series can compute: at least `LEAST_BARS`, at most a share.

    Two bounds, and both are about the window meaning what it says:

    * **below `LEAST_BARS` it is not a window.** A rung shorter than two bars
      clamps to one and reports that bar's own high and low under a name that
      claims a horizon - a 10s window on 15m bars would read as "the last ten
      seconds" while being the last fifteen minutes.
    * **above `share` of the series it is not estimable.** A four-week window on
      a thousand 1d bars leaves fewer than forty independent observations of it,
      and the slope-fade harness has already shown what that does: an apparent
      `t` of -10.8 that was entirely overlapping windows.

    So a 3m series resolves minutes to days and a 1d series resolves days to
    weeks, from one ladder and without either being a special case.
    """
    if bar <= 0 or length < LEAST_BARS * 2:
        return ()
    cap = max(int(length * share), LEAST_BARS)
    out = []
    for window in ladder:
        span = window.bars(bar)
        if LEAST_BARS <= span <= cap:
            out.append(window)
    return tuple(out)


def bar_hours(times: Sequence[float], sample: int = 500) -> float:
    """The series' own bar length in hours, as the median spacing.

    Median rather than mean, because a weekend gap or a feed outage is one
    enormous spacing and the mean would carry it into every window.
    """
    gaps = sorted(
        (float(times[i]) - float(times[i - 1])) / HOUR
        for i in range(1, min(len(times), sample))
        if times[i] > times[i - 1]
    )
    if not gaps:
        return 0.0
    middle = len(gaps) // 2
    return gaps[middle] if len(gaps) % 2 else 0.5 * (gaps[middle - 1] + gaps[middle])


def coverage(times: Sequence[float], bar: float | None = None) -> float:
    """The share of calendar time this series actually trades, from its own clock.

    `(n - 1) * bar_hours / span_hours`: how much bar time fits in the calendar
    time it covers. An FX series stops for the weekend and comes out near
    **5/7 = 0.714**; crypto and the Deriv synthetics run continuously and come
    out near **1.0**.

    Inferred rather than declared for the same reason `bar_hours` is: a
    per-symbol table of trading calendars is one more thing to keep in step
    with reality, and the timestamps already know.

    Clamped to `(0, 1]`. A series whose bars overlap would read above one, which
    is a broken feed rather than a market open more than all the time.
    """
    if len(times) < 3:
        return 1.0
    step = bar if bar is not None else bar_hours(times)
    span = (float(times[-1]) - float(times[0])) / HOUR
    if step <= 0 or span <= 0:
        return 1.0
    return min((len(times) - 1) * step / span, 1.0)


def _running(source: Sequence[float], span: int, pick) -> list[float]:
    """Causal rolling `max` or `min`. `out[k]` covers `source[k - span + 1 .. k]`.

    The simple `O(n * span)` form. A monotonic deque would be `O(n)` and is not
    written, because the windows here are at most a quarter of the series by
    construction and this is built once per series rather than per call.
    """
    out = [0.0] * len(source)
    for k in range(len(source)):
        start = max(0, k - span + 1)
        out[k] = pick(source[start : k + 1])
    return out


def ema(source: Sequence[float], span: int) -> list[float]:
    """Causal exponential average, `alpha = 2 / (span + 1)`.

    Moved here from `research/ideas/slope_fade.py`, where the two signals that
    survived the overlap correction were built on it - the raw slope did not.
    Causal and nothing here sees ahead: `out[k]` uses `source[0 .. k]`.
    """
    if span < 1:
        return [0.0] * len(source)
    alpha = 2.0 / (span + 1.0)
    out = [0.0] * len(source)
    current = 0.0
    for k, value in enumerate(source):
        current = value if k == 0 else current + alpha * (value - current)
        out[k] = current
    return out


def rolling(source: Sequence[float], span: int) -> list[float]:
    """Causal rolling mean. `out[k]` uses `source[max(0, k - span + 1) .. k]`."""
    if span < 1:
        return [0.0] * len(source)
    out = [0.0] * len(source)
    run = 0.0
    for k in range(len(source)):
        if k < span:
            run = sum(source[: k + 1]) / (k + 1)
        else:
            run += (source[k] - source[k - span]) / span
        out[k] = run
    return out


def parkinson(highs: Sequence[float], lows: Sequence[float]) -> list[float]:
    """Per-bar Parkinson variance: `ln(high/low)^2 / (4 ln 2)`.

    **The estimator the package had the data for and never used.** A
    close-to-close variance sees two numbers a bar; the range sees how far price
    actually travelled, and Parkinson is more efficient for the same sample.

    Measured on eurusd: as part of a multi-scale blend it takes the volatility
    forecast from 64% of achievable to **79%** at 15m and 24% to 53% at 1h. It
    is *worse* than close-only on daily bars - 4.6% against 6.0% - because a
    daily extreme carries thin-liquidity spikes that are not representative
    travel, so this is an intraday estimator and `README.md` says so.
    """
    out = []
    scale = 4.0 * math.log(2.0)
    for high, low in zip(highs, lows, strict=True):
        if high > 0 and low > 0 and high >= low:
            out.append(math.log(high / low) ** 2 / scale)
        else:
            out.append(0.0)
    return out


def garman_klass(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> list[float]:
    """Per-bar Garman-Klass variance, which adds the open to Parkinson's range."""
    out = []
    factor = 2.0 * math.log(2.0) - 1.0
    for open_, high, low, close in zip(opens, highs, lows, closes, strict=True):
        if min(open_, high, low, close) > 0 and high >= low:
            hl = math.log(high / low)
            co = math.log(close / open_)
            out.append(max(0.5 * hl * hl - factor * co * co, 0.0))
        else:
            out.append(0.0)
    return out


def har(source: Sequence[float], spans: tuple[int, int, int]) -> list[float]:
    """Corsi's blend: a short, a medium and a long rolling mean, averaged.

    **The robust gain in the volatility work** - it won or tied on every series
    measured, which is why it is the standard benchmark in that literature. The
    weights are equal rather than fitted, so this is a benchmark and not a
    tuned model; fitting them is the obvious next step and would need its own
    held-out comparison.

    On variance, not volatility: the inputs are variances and the root is taken
    once, where it is reported. That is the Cboe lesson and it is the reason
    this takes a variance series rather than a volatility one.
    """
    short, medium, long = (rolling(source, span) for span in spans)
    return [(a + b + c) / 3.0 for a, b, c in zip(short, medium, long, strict=True)]


@dataclass(slots=True)
class Exogenous:
    """`u`, built from windows of the past, for one bar.

    Names and values travel together so a `B` can be lined up against them by
    name rather than by position - which is the failure mode `frozen.vector`
    exists to prevent one layer down: a model fed its features in the caller's
    order instead of its own.
    """

    names: tuple[str, ...]
    values: tuple[float, ...]

    def __len__(self) -> int:
        return len(self.values)

    def of(self, name: str) -> float:
        """One component by name. `KeyError` rather than a plausible zero."""
        try:
            return self.values[self.names.index(name)]
        except ValueError as exc:
            raise KeyError(f"no input named {name!r}; have {self.names}") from exc


@dataclass(slots=True)
class Features:
    """Builds `u` from a series, over windows measured in hours.

    Hold one per series. `at(i)` returns the inputs for bar `i`, computed from
    bars strictly before it.
    """

    times: Sequence[float]
    highs: Sequence[float]
    lows: Sequence[float]
    closes: Sequence[float]
    #: Optional. Garman-Klass needs it; without it that feature is omitted
    #: rather than faked from the close.
    opens: Sequence[float] | None = None
    #: Empty means "whatever this series resolves", which is the portable
    #: default - see `resolvable`. Pass an explicit tuple to override it.
    windows: tuple[Window, ...] = ()
    #: Set from the series on construction, so every window converts once.
    _bar: float = field(default=0.0, init=False)
    #: The share of calendar time this series trades - near 5/7 for FX, near 1
    #: for crypto and the synthetics. Inferred, never declared.
    _coverage: float = field(default=1.0, init=False)
    #: Every feature as a causal series, built once. See `_build`.
    _series: dict[str, list[float]] = field(default_factory=dict, init=False)
    _moves: list[float] = field(default_factory=list, init=False)
    _zmoves: list[float] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._bar = bar_hours(self.times)
        self._coverage = coverage(self.times, self._bar)
        if not self.windows:
            self.windows = resolvable(self._bar, len(self.closes))
        self._build()

    def _build(self) -> None:
        """Precompute every rolling series once, so `at` is a lookup.

        The first version recomputed each window from the raw bars on every
        call, which is `O(window)` per feature per call - fine for a one-off
        and quadratic for a harness that walks the series. These are all causal
        rolling quantities and there is no reason to compute them more than
        once.

        **The alignment rule is unchanged**: each series here is built so that
        `series[k]` uses bars `0 .. k`, and `at(i)` reads index `i - 1`. That
        keeps "strictly before `i`" true, which is the property the leak test
        pins.
        """
        closes = self.closes
        n = len(closes)
        moves = [0.0] + [
            math.log(closes[k] / closes[k - 1]) if closes[k] > 0 and closes[k - 1] > 0 else 0.0
            for k in range(1, n)
        ]
        self._moves = moves
        squares = [m * m for m in moves]
        park_bar = parkinson(self.highs, self.lows)
        gk_bar = (
            garman_klass(self.opens, self.highs, self.lows, closes)
            if self.opens is not None
            else None
        )

        # A rolling spread for standardising, on the shortest resolvable window
        # so the z-scores react at the series' own pace.
        shortest = min((w.bars(self._bar) for w in self.windows), default=20)
        sigma = [math.sqrt(v) for v in rolling(squares, max(shortest, 2))]
        self._zmoves = [moves[k] / sigma[k] if sigma[k] > 0 else 0.0 for k in range(n)]

        self._series = {}
        for window in self.windows:
            span = window.bars(self._bar, self._coverage)
            tag = window.label()
            self._series[f"high_{tag}"] = _running(self.highs, span, max)
            self._series[f"low_{tag}"] = _running(self.lows, span, min)
            self._series[f"rv_{tag}"] = [math.sqrt(v) for v in rolling(squares, span)]
            self._series[f"parkinson_{tag}"] = [math.sqrt(v) for v in rolling(park_bar, span)]
            if gk_bar is not None:
                self._series[f"gk_{tag}"] = [math.sqrt(v) for v in rolling(gk_bar, span)]
            # **The raw slope, per hour.** `rolling(moves, span)` is the mean
            # log move per *bar* over the window, which is a slope in bars and
            # therefore not comparable across timeframes - the package rule
            # applies to a rate as much as to a horizon. Dividing by the bar
            # length makes it a log return an hour, which means one thing
            # everywhere.
            #
            # It is here as the **baseline the EMA variants have to beat**: the
            # raw slope's survivors in `slope_fade.py` were killed by the
            # stricter overlap correction and the EMA ones were not, so leaving
            # it out would remove the comparison that result rests on.
            per_bar = rolling(moves, span)
            self._series[f"slope_{tag}"] = [v / self._bar for v in per_bar]
            self._series[f"ema_slope_{tag}"] = [v / self._bar for v in ema(moves, span)]
            self._series[f"ema_z_{tag}"] = ema(self._zmoves, span)

        # The blend that won: three rungs of the ladder on the better
        # per-bar estimator. Spans come from the windows actually resolved, so
        # this is portable for the same reason everything else here is.
        spans = sorted({w.bars(self._bar, self._coverage) for w in self.windows})
        if len(spans) >= 3:
            triple = (spans[0], spans[len(spans) // 2], spans[-1])
            self._series["har"] = [math.sqrt(v) for v in har(squares, triple)]
            self._series["har_parkinson"] = [math.sqrt(v) for v in har(park_bar, triple)]

    @property
    def bar(self) -> float:
        return self._bar

    @property
    def open_share(self) -> float:
        """How much of the calendar this series trades. See `coverage`."""
        return self._coverage

    def names(self) -> tuple[str, ...]:
        """Every feature, in a stable order. Built once, so this is a key list."""
        return tuple(self._series)

    def at(self, index: int) -> Exogenous:
        """`u` for bar `index`, from bars **strictly before** it.

        Reads each precomputed series at `index - 1`, because `series[k]` is
        built from bars `0 .. k`. A window that includes the bar it is
        predicting leaks the present, which is the mistake that produced
        `t = +20.8` across five symbols in the cross-resolution test - one of
        them a generated series, which is how it was caught.
        """
        names = self.names()
        if index <= 0:
            return Exogenous(names, tuple(0.0 for _ in names))
        k = min(index - 1, len(self.closes) - 1)
        values = []
        for name in names:
            series = self._series[name]
            values.append(series[k] if k < len(series) else 0.0)
        # `position` is derived rather than stored: it needs the high and the
        # low together, and keeping it out of `_series` avoids a third pass.
        return Exogenous(names, tuple(values))

    def position(self, index: int, window: Window) -> float:
        """Where the last close sits in the window's range, in `[0, 1]`.

        Unit-free, so it travels across symbols as well as timeframes - which a
        raw high does not. Kept as a method rather than a stored feature
        because it is a ratio of two that are already stored.
        """
        if index <= 0:
            return 0.5
        tag = window.label()
        k = min(index - 1, len(self.closes) - 1)
        top = self._series.get(f"high_{tag}", [0.0])[k]
        bottom = self._series.get(f"low_{tag}", [0.0])[k]
        here = self.closes[k]
        width = top - bottom
        return (here - bottom) / width if width > 0 else 0.5


def since(flags: Sequence[bool], index: int, bar: float) -> float:
    """Hours since the last true flag before `index`, or `inf` if never.

    The "time since the last sweep" case, in hours rather than bars so it is
    portable for the same reason the windows are. `inf` rather than a large
    number, because a caller that forgets to check will get an obvious failure
    rather than a plausible one.
    """
    for back in range(index - 1, -1, -1):
        if flags[back]:
            return (index - back) * bar
    return math.inf
