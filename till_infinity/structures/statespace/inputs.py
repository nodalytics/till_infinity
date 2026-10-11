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
    #: A 1m feed can carry a 3m window - three bars - and the ladder had no
    #: rung for it, so the finest thing a 1m series could answer was five
    #: minutes. The rungs are the horizons the desk's own feeds are stored at
    #: (3m, 15m, 1h, 4h, 6h, 8h, 12h, 1d), which is a reason to pick them
    #: rather than a preference: a window the desk already keeps a feed for is
    #: a window somebody will ask about.
    Window(3.0 / 60.0, "3m"),
    Window(5.0 / 60.0, "5m"),
    Window(15.0 / 60.0, "15m"),
    Window(30.0 / 60.0, "30m"),
    Window(1.0, "1h"),
    Window(4.0, "4h"),
    Window(6.0, "6h"),
    Window(8.0, "8h"),
    Window(12.0, "12h"),
    Window(24.0, "1d"),
    Window(3 * 24.0, "3d"),
    Window(1 * WEEK, "1w"),
    Window(2 * WEEK, "2w"),
    Window(4 * WEEK, "4w"),
)

#: How many times its own trailing body a bar must have to count as a spike.
#: Three, which is roughly a 99th percentile for a Gaussian body and is not
#: fitted - the harness sweeps it.
SPIKE = 3.0

#: How many times its body a wick must be to count as a long one. Two is the
#: usual reading of a rejection candle and is likewise not fitted.
WICK = 2.0

#: Fewest bars a window must span to mean anything. Two, because one bar is the
#: bar itself and a "range" over it is that bar's own high and low - which is
#: already a feature and does not need a window to say so.
LEAST_BARS = 2


def resolvable(
    bar: float,
    length: int,
    ladder: tuple[Window, ...] = LADDER,
    share: float = 0.25,
    cover: float = 1.0,
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

    **`cover` is required for the first bound to work and was missing.** The
    count of bars in a calendar window depends on how much of the calendar the
    market trades: half an hour is two bars of 15m on a market open all week and
    about one on FX, which closes at the weekend. Computed without coverage this
    function admitted a window that `Features._build` then built with a span of
    one - the exact failure the first bound exists to prevent, since that rung
    reports a single bar's own high and low under a name claiming a horizon.

    It is a default rather than a required argument because a `Window` on a 24/7
    series is the same either way, and `coverage` is what tells the two apart.
    """
    if bar <= 0 or length < LEAST_BARS * 2:
        return ()
    cap = max(int(length * share), LEAST_BARS)
    out = []
    for window in ladder:
        span = window.bars(bar, cover)
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


def spiking(
    opens: Sequence[float] | None,
    closes: Sequence[float],
    span: int,
    multiple: float = SPIKE,
) -> list[bool]:
    """Bars whose **body** is unusually large for this series.

    The body is `|close - open|`, or `|close - previous close|` when there are
    no opens - a feed without them is not a reason to drop the feature, and
    close-to-close is the same quantity measured across the gap.

    "Unusually" is against the series' own trailing mean body over `span`,
    which makes it scale-free and comparable across instruments. Causal: bar
    `k` is judged against bars before it.
    """
    n = len(closes)
    bodies = [0.0] * n
    for k in range(1, n):
        bodies[k] = (
            abs(closes[k] - opens[k]) if opens is not None else abs(closes[k] - closes[k - 1])
        )
    typical = rolling(bodies, span)
    return [
        k > 0 and typical[k - 1] > 0 and bodies[k] > multiple * typical[k - 1] for k in range(n)
    ]


def wicking(
    opens: Sequence[float] | None,
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    multiple: float = WICK,
) -> list[bool]:
    """Bars with a **long wick** - a rejection, in the usual reading.

    Either wick longer than `multiple` times the body. No window is needed:
    this is a comparison within the bar, so it is already scale-free and
    already causal.

    A doji - a body at or near zero - would make every bar a wick, so the body
    is floored at a thousandth of the bar's range. That is the degenerate case
    this feature has, and leaving it unhandled would make a quiet session read
    as continuous rejection.
    """
    n = len(closes)
    out = [False] * n
    for k in range(n):
        top = opens[k] if opens is not None else closes[k - 1] if k else closes[k]
        body_high, body_low = max(top, closes[k]), min(top, closes[k])
        span = highs[k] - lows[k]
        if span <= 0:
            continue
        body = max(abs(closes[k] - top), span / 1000.0)
        upper = highs[k] - body_high
        lower = body_low - lows[k]
        out[k] = max(upper, lower) > multiple * body
    return out


def pivots(highs: Sequence[float], lows: Sequence[float], span: int) -> list[bool]:
    """Swing highs and lows, **marked where they are confirmed**, not where they are.

    This is the one of the three that can leak, and the leak is the whole
    difficulty. A pivot at bar `k` is only *knowable* at `k + span`, once
    `span` bars have failed to exceed it. Marking it at `k` would be a feature
    that knows the future - which is the shape of the cross-resolution bug this
    project has already paid for once, at `t = +20.8` on five symbols.

    So the flag is set at `k + span`: "a swing was confirmed here". A caller
    counting pivots over a window is counting confirmations, which is the only
    version of the count that existed at the time.
    """
    n = len(highs)
    out = [False] * n
    if span < 1:
        return out
    for k in range(span, n - span):
        high, low = highs[k], lows[k]
        # **Strict, and the test caught why.** With `<=` a flat stretch makes
        # every bar both a swing high and a swing low, because every
        # neighbour ties with it - a synthetic fixture of constant lows
        # flagged thirty consecutive pivots. A flat series has no swings, and
        # strict comparison is what says so.
        up = all(highs[j] < high for j in range(k - span, k + span + 1) if j != k)
        down = all(lows[j] > low for j in range(k - span, k + span + 1) if j != k)
        if up or down:
            out[k + span] = True
    return out


def pivot_levels(
    highs: Sequence[float],
    lows: Sequence[float],
    span: int,
) -> tuple[list[float], list[float]]:
    """`(last confirmed swing high, last confirmed swing low)` at each bar.

    **Not the same thing as the rolling high and low**, which `Features`
    already carries as `high_<tag>` and `low_<tag>`. The difference matters:

    * a rolling high is *the highest price in the window*. It always exists,
      it can be the current bar, and it moves whenever a new extreme is made.
    * a swing high is *a turning point* - a bar higher than `span` bars on
      both sides. It may not exist in a window at all, it is only knowable
      `span` bars later, and it does **not** move when price makes a new high
      without turning.

    A desk reading "the last swing high" is reading the second. Both are
    useful and they answer different questions, which is why this is here
    rather than folded into `_running`.

    Carried forward between pivots, so the level is the most recent one
    confirmed - and zero before the first, which a caller should treat as
    absent rather than as a price.
    """
    n = len(highs)
    tops = [0.0] * n
    bottoms = [0.0] * n
    if span < 1:
        return tops, bottoms
    top = bottom = 0.0
    for k in range(n):
        middle = k - span
        if span <= middle < n - span:
            high, low = highs[middle], lows[middle]
            window = range(middle - span, middle + span + 1)
            if all(highs[j] < high for j in window if j != middle):
                top = high
            if all(lows[j] > low for j in window if j != middle):
                bottom = low
        tops[k] = top
        bottoms[k] = bottom
    return tops, bottoms


def per_hour(flags: Sequence[bool], span: int, bar: float) -> list[float]:
    """Count of `flags` over the trailing `span` bars, **as a rate per hour**.

    The whole point of the three features above, and the package rule applied
    to a count: "eleven spikes in the window" is eleven per 2.75 hours at 15m
    and eleven per 11 hours at 1h, which is two different statements. A rate
    per hour is one.
    """
    counts = rolling([1.0 if f else 0.0 for f in flags], span)
    hours = max(span * bar, 1e-9)
    return [c * span / hours for c in counts]


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

    #: **Quotes, optional.** Either the broker's spread per bar, or the bid
    #: and ask it came from. Absent by default - a bar feed is the common
    #: case and a feature that silently reads zeros would be worse than one
    #: that is not there.
    #:
    #: `spreads` is in the **same units as the prices**. The seqlab feeds
    #: store it in *points*, and the conversion is the caller's: reading a
    #: point count as a price inflates every cost by `1/tick`, which is how
    #: one harness came to report a spread of 136 volatility units on a
    #: market that trades.
    spreads: Sequence[float] | None = None
    bids: Sequence[float] | None = None
    asks: Sequence[float] | None = None
    #: Empty means "whatever this series resolves", which is the portable
    #: default - see `resolvable`. Pass an explicit tuple to override it.
    windows: tuple[Window, ...] = ()
    #: Set from the series on construction, so every window converts once.
    _bar: float = field(default=0.0, init=False)
    #: The share of calendar time this series trades - near 5/7 for FX, near 1
    #: for crypto and the synthetics. Inferred, never declared.
    #: Build the counted-event features - spiking bodies, long wicks,
    #: confirmed pivots, their EMAs and the distances to the last swing.
    #:
    #: **Off by default, because they were measured and carry nothing.** Over
    #: 1,020 cells on six instruments and two timeframes, every family's rank
    #: correlation with the next move's size was within 0.032 of its own
    #: rotated control, and **net of a trailing standard deviation every one
    #: was within 0.015 of zero** - see
    #: `research/docs/statespace-counted-events.md`.
    #:
    #: Kept rather than deleted because the measurement is worth more than the
    #: code, and a null that is easy to re-run is a null that stays checked.
    #: Off rather than on because 48 features widen the multiple-comparison
    #: surface for everything built on `Features`, and features that measure
    #: nothing should not charge that to every caller.
    counted: bool = False

    _coverage: float = field(default=1.0, init=False)
    #: The three counted-event streams, kept so `since_last` need not rebuild
    #: them. Flags, not rates: a rate has a window and "hours since" does not.
    _events: dict[str, list[bool]] = field(default_factory=dict, init=False)
    #: Every feature as a causal series, built once. See `_build`.
    _series: dict[str, list[float]] = field(default_factory=dict, init=False)
    _moves: list[float] = field(default_factory=list, init=False)
    _zmoves: list[float] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._bar = bar_hours(self.times)
        self._coverage = coverage(self.times, self._bar)
        if not self.windows:
            self.windows = resolvable(self._bar, len(self.closes), cover=self._coverage)
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
        # so the z-scores react at the series' own pace. **With coverage**, like
        # every other conversion here: without it this was longer than the
        # shortest span actually built six lines below, so the z-scores reacted
        # more slowly than the window they are named for.
        shortest = min((w.bars(self._bar, self._coverage) for w in self.windows), default=20)
        # **Clamped, because a running-sum rolling mean can go slightly
        # negative.** `rolling` adds and subtracts to stay `O(n)`, so a window
        # of near-zero squares can cancel to `-1e-20` - and `math.sqrt` raises
        # rather than returning a tiny number. It surfaced on a real series
        # only after the counted-event features put `Features` on a code path
        # with long flat stretches, which is how a latent domain error waits.
        sigma = [math.sqrt(max(v, 0.0)) for v in rolling(squares, max(shortest, 2))]
        self._zmoves = [moves[k] / sigma[k] if sigma[k] > 0 else 0.0 for k in range(n)]

        # **Counted events, as rates per hour.** Spiking bodies, long wicks and
        # confirmed pivots - each a count over the window divided by the hours
        # the window spans, so "three pivots an hour" means the same thing on
        # every timeframe. The pivot flag is set where a swing is *confirmed*
        # rather than where it happened, which is what keeps it causal.
        shortest_span = max(shortest, 2)
        spikes = spiking(self.opens, closes, shortest_span)
        wicks = wicking(self.opens, self.highs, self.lows, closes)
        reach = max(shortest_span // 2, 1)
        swings = pivots(self.highs, self.lows, reach)
        tops, bottoms = pivot_levels(self.highs, self.lows, reach)

        # **Distance, in hours since the last event.** Not a rate and not a
        # count: a rate says how often, this says how long it has been, and
        # the two come apart exactly where it matters - a market that has not
        # spiked in eight hours is in a different state from one averaging the
        # same rate with a spike a minute ago. One feature each rather than one
        # per window, because "hours since" has no window.
        self._series = {}
        self._events = {"spike": spikes, "wick": wicks, "pivot": swings}

        self._quotes(closes, sigma, shortest_span, n)
        self._swings(closes, sigma, tops, bottoms, n)
        for window in self.windows:
            span = window.bars(self._bar, self._coverage)
            tag = window.label()
            self._series[f"high_{tag}"] = _running(self.highs, span, max)
            self._series[f"low_{tag}"] = _running(self.lows, span, min)
            self._series[f"rv_{tag}"] = [math.sqrt(max(v, 0.0)) for v in rolling(squares, span)]
            self._series[f"parkinson_{tag}"] = [
                math.sqrt(max(v, 0.0)) for v in rolling(park_bar, span)
            ]
            if gk_bar is not None:
                self._series[f"gk_{tag}"] = [math.sqrt(max(v, 0.0)) for v in rolling(gk_bar, span)]
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
            if self.counted:
                spike_rate = per_hour(spikes, span, self._bar)
                wick_rate = per_hour(wicks, span, self._bar)
                pivot_rate = per_hour(swings, span, self._bar)
                self._series[f"spikes_{tag}"] = spike_rate
                self._series[f"wicks_{tag}"] = wick_rate
                self._series[f"pivots_{tag}"] = pivot_rate
                # **EMAs of the rates**, which answer a different question from the
                # rates: a window says how many events there were, an exponential
                # average weights the recent ones more and so says whether the
                # count is *becoming* unusual. Same span, so the pair is a level
                # and its smoothing rather than two windows.
                self._series[f"ema_spikes_{tag}"] = ema(spike_rate, span)
                self._series[f"ema_wicks_{tag}"] = ema(wick_rate, span)
                self._series[f"ema_pivots_{tag}"] = ema(pivot_rate, span)

        # The blend that won: three rungs of the ladder on the better
        # per-bar estimator. Spans come from the windows actually resolved, so
        # this is portable for the same reason everything else here is.
        spans = sorted({w.bars(self._bar, self._coverage) for w in self.windows})
        if len(spans) >= 3:
            triple = (spans[0], spans[len(spans) // 2], spans[-1])
            self._series["har"] = [math.sqrt(max(v, 0.0)) for v in har(squares, triple)]
            self._series["har_parkinson"] = [math.sqrt(max(v, 0.0)) for v in har(park_bar, triple)]

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

    def _swings(
        self,
        closes: Sequence[float],
        sigma: list[float],
        tops: list[float],
        bottoms: list[float],
        n: int,
    ) -> None:
        """Distance to the last confirmed swing. Behind `counted`, untested."""
        if not self.counted:
            return
        # Both sides are **logs**. The first version divided a *price*
        # difference by `sigma`, which is a standard deviation of *log*
        # returns, and reported 267 volatility units on a series whose
        # swings are under a percent - the same unit mismatch that once
        # read a spread of 136 volatility units on a market that trades.
        # Zero before the first pivot, which means absent rather than "at
        # the price".
        unit = [max(v, 1e-12) for v in sigma]
        self._series["to_swing_high"] = [
            math.log(tops[k] / closes[k]) / unit[k] if tops[k] > 0 and closes[k] > 0 else 0.0
            for k in range(n)
        ]
        self._series["to_swing_low"] = [
            math.log(closes[k] / bottoms[k]) / unit[k] if bottoms[k] > 0 and closes[k] > 0 else 0.0
            for k in range(n)
        ]

    def _quotes(
        self,
        closes: Sequence[float],
        sigma: list[float],
        span: int,
        n: int,
    ) -> None:
        """Quote-derived features, when quotes were given. Absent otherwise.

        The cost of crossing is the one quantity on this desk that is
        **observed** rather than inferred, and every gate here currently uses
        a constant for it - which the SEC's payment-for-order-flow study says
        is wrong, because the number moves with the composition of the flow.
        """
        quoted = self._spread_series()
        if quoted is None:
            return
        unit = [max(v, 1e-12) for v in sigma]
        # In volatility units, so a spread on gold and on the euro are the
        # same number when they cost the same.
        self._series["cost"] = [quoted[k] / max(closes[k], 1e-12) / unit[k] for k in range(n)]
        self._series["ema_cost"] = ema(self._series["cost"], span)
        if self.bids is None or self.asks is None:
            return
        # Where the close sat between the quotes: -1 at the bid, +1 at the
        # ask. **Roll's bounce read directly** rather than inferred from
        # serial covariance - a close persistently at one side is informed
        # flow, and one alternating is the spread being paid both ways.
        self._series["at_ask"] = [
            2.0 * (closes[k] - self.bids[k]) / (self.asks[k] - self.bids[k]) - 1.0
            if self.asks[k] > self.bids[k]
            else 0.0
            for k in range(n)
        ]

    def _spread_series(self) -> list[float] | None:
        """The spread per bar, from whichever quote input was given.

        `spreads` wins if both are present, because a broker's own number is
        the one the desk is charged - and the disagreement between it and
        `ask - bid` is itself a measurement worth having rather than an
        inconsistency to resolve silently.
        """
        if self.spreads is not None:
            return [float(v) for v in self.spreads]
        if self.bids is not None and self.asks is not None:
            return [
                max(float(a) - float(b), 0.0) for a, b in zip(self.asks, self.bids, strict=True)
            ]
        return None

    def since_last(self, kind: str, index: int) -> float:
        """Hours since the last `spike`, `wick` or `pivot` strictly before `index`.

        `inputs.since` does the arithmetic; this names the three event streams
        so a caller need not rebuild them. Returns the age of the series when
        nothing has happened yet, which is a true statement rather than a
        zero that would read as "just now".
        """
        flags = self._events[kind]
        return since(flags[:index], max(index - 1, 0), self._bar)

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
