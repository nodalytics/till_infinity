"""Is a level a barrier in the path? The matched-distance first-passage test.

The entry side of levels is closed on this desk: `docs/magnet.md` has levels
reached *less* often than an arbitrary price the same distance away (44.9%
against 49.5%), `topology.md` concluded that levels, ranges and shapes restate
volatility, and a return rate is geometry - a walk reads 0.825 where the
displacement origin read 0.82.

This asks a different question with the same primitive, and it is an **exit**
question rather than an entry one. Not "does price go to the level" but:

    given a fixed distance d, does price travel d LESS often when a level sits
    in the path than when the path is clear?

If it does, the same number is a target rule and a stop rule with opposite
signs:

* **target** - a take-profit beyond a level is reached less often than its
  distance implies, so place it *in front of* the nearest level;
* **stop** - a protective stop beyond a level is reached less often than its
  distance implies, which is *free survival*: the level has to break first.

`magnet.md`'s own number already points this way. "Reached less often than a
matched arbitrary price" is bad news for a target and good news for a stop, and
nothing on this desk has read it for the stop.

## What is held fixed, and why each control is here

**The distance is matched.** Both arms travel the same `d` in the same
volatility unit, so geometry is identical and `a-return-rate-is-geometry`
cannot explain a gap. This is `surrogates.distance_matched` in the form the
question takes: the placebo is not a random anchor, it is *this anchor with no
level in the path*.

**Volatility is stratified.** This is the confound that matters and the one
`topology.md` found: a level 1.5 units away means price turned 1.5 units away
recently, which means a quiet or ranging stretch, which predicts a smaller
forward excursion for a reason that has nothing to do with a barrier. Every
gap is reported within quintiles of trailing compression, never pooled -
`pooled-medians-invert-subgroups`.

**Three null arms, decided on the hardest.** `walk-geometry` is
`node/surrogates.walk_with_bar_geometry`: this market's wickiness and step
distribution, no path structure and no clustering. `garch-bars` keeps
clustering, which `walk-geometry` removes, because the conditioning event
*is* a statement about the recent path and clustering is the mechanical way
that pays off. `bar-shuffle` is the no-memory floor. Every arm runs the same
detector over the same bar geometry, which is what
`null-structure-claims-on-the-same-detector` asks for, and the deciding arm is
the one the real result beats by least.

**Overlap is reported both ways.** Dense anchors with a day-block bootstrap,
and a non-overlapping subsample at `step = horizon`.
`overlapping-windows-inflate-permutation-nulls` is the recorded failure: a
level finding at p 0.015 was anchor overlap, and the tell was the no-level
control passing too.

**Power before any null.** `plant()` injects a reflecting barrier of known
strength and sweeps it, so a null comes with the strength at which this test
goes blind.

## What this cannot settle

Nothing here is priced. These are hit rates and distances - geometry and
mechanics in the sense `node/corpus.py` means. A P&L statement needs the six
feeds with a measured spread and is made separately. The feeds used here for
geometry include the ones with no recorded quotes, which is sound precisely
because no cost is charged: `corpus.write` skips them rather than guess a
spread, and guessing one is still refused.
"""

import math
import os
import random
import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from till_infinity.indicators.levels import FORGET_BARS, KEEP, MERGE_VOL, TOUCH_NOISE_VOL, Levels
from till_infinity.indicators.trend import REACH
from till_infinity.node.surrogates import walk_with_bar_geometry

#: The price store. Relative by default so the study runs anywhere the repo
#: is checked out; `SHIELD_STORE` points it at a copy on a bigger box.
STORE = os.environ.get("SHIELD_STORE") or "file:.data/prices/prices.db?mode=ro"
NANOS = 1_000_000_000

#: Feeds carried, one venue each. The venue is chosen by **bar count at that
#: interval**, ties alphabetically - a data-volume rule fixed before any
#: result, never a venue that read better. `spread_bps` in `node/corpus.py`
#: is why a venue is never pooled: the same instrument runs 0.17 to 3.30 bps
#: across venues, a nineteenfold range.
FEEDS = (
    "eurusd",
    "gbpusd",
    "gold",
    "btc",
    "us100",
    "spx500",
    "audusd",
    "nzdusd",
    "usdcad",
    "usdchf",
    "usdjpy",
    "usdcnh",
    "eth",
    "sol",
)

#: The six feeds with enough recorded quotes to measure a median spread on
#: some venue. Only these may carry a costed number; the rest are geometry.
COSTED = {"eurusd", "gbpusd", "gold", "btc", "us100", "spx500"}

#: Per interval: the forward horizon in bars, and the span of the EWMA bar
#: range that is the volatility unit. The horizon is about two days of bars at
#: 15m and 1h and a month at 1d, which is the span over which a stop or a
#: target on that interval is live.
#: Per interval: the forward horizon in bars, and the span of the EWMA bar
#: range that is the volatility unit.
#:
#: **Every parameter here is in bars, which is the mapping between intervals
#: and has to be stated rather than assumed.** A level at 1d is a different
#: object from one at 15m: `reach` 3, `merge_vol` 0.35 units, `forget` 500
#: bars and `keep` 24 are held fixed across intervals, so what scales is the
#: unit - an EWMA of the bar range - and nothing else. `FORGET_BARS` in
#: `indicators/levels.py` makes the same argument for the same reason: in bars
#: a horizon is interval-independent, and a level on a daily chart needs weeks
#: where one on a 1-minute chart needs hours.
SETTINGS = {
    "15m": {"horizon": 48, "unit_span": 48},
    "1h": {"horizon": 48, "unit_span": 48},
    "4h": {"horizon": 30, "unit_span": 30},
    "1d": {"horizon": 20, "unit_span": 20},
}

#: Distances tested, in volatility units. Pre-registered, and swept rather
#: than chosen: `sweep-thresholds-on-the-mean-not-z` is why the whole grid is
#: reported with its mean rather than the best cell with its z.
DISTANCES = (1.0, 1.5, 2.0, 3.0, 4.0)

#: Where in the path a level has to sit to count as shielding it, as a
#: fraction of the distance. Not from 0: a level price is already sitting at
#: is a different condition, and admitting it would measure "price is at a
#: level" rather than "a level is in the way".
SHIELD_LO, SHIELD_HI = 0.30, 0.90

#: The clear arm needs nothing in the path **and** nothing just past the
#: target, so the two arms differ in one thing only.
CLEAR_TO = 1.20

#: Strata on trailing compression, as quintiles of each arm's own
#: distribution. Per arm, because the arms have different volatility
#: processes and real edges applied to a null arm would misalign the bins.
STRATA = 5

#: Eras the span is cut into, so a result cannot be one regime. Crossed with
#: the compression quintiles when `SHIELD_ERAS` is set, which multiplies the
#: strata count and is only affordable where the span is long - 19 years of
#: daily bars, not 76 days of 15-minute ones.
ERAS = int(os.environ.get("SHIELD_ERAS") or 1)

#: Total strata: compression quintile crossed with era. The aggregation sizes
#: its count tensor on this, so the two knobs cannot disagree.
BINS = STRATA * ERAS


# ─────────────────────────────── the data ───────────────────────────────


@dataclass(frozen=True, slots=True)
class Series:
    feed: str
    venue: str
    interval: str
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    @property
    def name(self) -> str:
        return f"{self.feed}.{self.venue}.{self.interval}"

    @property
    def days(self) -> float:
        return float(self.ts[-1] - self.ts[0]) / 86_400.0


def venue_for(con, feed: str, interval: str) -> str | None:
    """The venue with the most bars for this feed at this interval.

    Fixed by bar count before any result is seen. One venue per (feed,
    interval): several venues of one feed are one instrument reported more
    than once, and counting them as independent cells is the multiplicity
    mistake the skill names.
    """
    rows = con.execute(
        "select venue, count(*) n from bars where feed=? and interval=? and closed=1 "
        "group by venue order by n desc, venue asc limit 1",
        (feed, interval),
    ).fetchall()
    return rows[0][0] if rows else None


def load(con, feed: str, interval: str) -> Series | None:
    venue = venue_for(con, feed, interval)
    if venue is None:
        return None
    rows = con.execute(
        "select ts, open, high, low, close from bars where feed=? and venue=? "
        "and interval=? and closed=1 order by ts",
        (feed, venue, interval),
    ).fetchall()
    if len(rows) < 500:
        return None
    arr = np.asarray(rows, dtype=float)
    return Series(
        feed=feed,
        venue=venue,
        interval=interval,
        ts=arr[:, 0],
        open=arr[:, 1],
        high=arr[:, 2],
        low=arr[:, 3],
        close=arr[:, 4],
    )


# ───────────────────────────── the null arms ─────────────────────────────


def bar_shuffle(series: Series, rng: random.Random) -> Series:
    """Each bar's own shape, attached to a permuted close-to-close step.

    The no-memory floor. The marginal step distribution and every bar's
    wick-to-body proportion survive exactly; where price has been does not, so
    a level is no longer a place price turned.
    """
    n = len(series.close)
    steps = np.diff(series.close)
    span = series.high - series.low
    frac_o = np.where(span > 0, (series.open - series.low) / np.maximum(span, 1e-12), 0.5)
    frac_c = np.where(span > 0, (series.close - series.low) / np.maximum(span, 1e-12), 0.5)
    order = list(range(n - 1))
    rng.shuffle(order)
    shapes = list(range(n))
    rng.shuffle(shapes)
    close = np.empty(n)
    close[0] = series.close[0]
    close[1:] = series.close[0] + np.cumsum(steps[order])
    pick = np.asarray(shapes)
    width = span[pick]
    low = close - frac_c[pick] * width
    return Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=low + frac_o[pick] * width,
        high=low + width,
        low=low,
        close=close,
    )


def walk_geometry(series: Series, rng: random.Random) -> Series:
    """`node/surrogates.walk_with_bar_geometry`, as a `Series`.

    The repo's own topological null, used rather than re-implemented so this
    harness and the module agree on what the arm is.
    """
    bars = list(
        zip(
            series.open.tolist(),
            series.high.tolist(),
            series.low.tolist(),
            series.close.tolist(),
            strict=True,
        )
    )
    made = walk_with_bar_geometry(bars, rng=rng)
    arr = np.asarray(made, dtype=float)
    return Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=arr[:, 0],
        high=arr[:, 1],
        low=arr[:, 2],
        close=arr[:, 3],
    )


def fit_garch(returns: np.ndarray) -> tuple[float, float, float]:
    """GARCH(1,1) by a coarse grid on (alpha, beta), omega from the variance.

    Coarse on purpose. The arm exists to supply **clustering of about the
    right strength**, not to be the best model of this series: a tightly
    fitted null is a different claim than a null that keeps one property, and
    `a-control-is-only-for-a-named-property` is the rule. The property is
    clustering, and a grid that lands near the FX consensus (alpha about 0.08,
    beta about 0.90) keeps it.
    """
    r = returns - returns.mean()
    var = float(np.var(r)) or 1e-12
    best = (0.08, 0.90, -1e18)
    for alpha in (0.02, 0.05, 0.08, 0.12, 0.18):
        for beta in (0.70, 0.80, 0.88, 0.93, 0.96):
            if alpha + beta >= 0.999:
                continue
            omega = var * (1.0 - alpha - beta)
            sigma2 = var
            total = 0.0
            for x in r:
                total += -0.5 * (math.log(sigma2) + x * x / sigma2)
                sigma2 = omega + alpha * x * x + beta * sigma2
            if total > best[2]:
                best = (alpha, beta, total)
    alpha, beta, _ = best
    return omega_for(var, alpha, beta), alpha, beta


def omega_for(var: float, alpha: float, beta: float) -> float:
    return var * (1.0 - alpha - beta)


def garch_bars(series: Series, rng: random.Random, fitted=None) -> Series:
    """Clustering kept, path structure removed.

    `walk_geometry` resamples steps i.i.d., so it has this market's tails and
    none of its volatility clustering - and clustering is exactly the
    mechanical route by which "a level is nearby" predicts a smaller forward
    excursion, because a level nearby means price has been turning nearby.
    An arm that lacks it cannot judge the claim, so this one has it: a
    GARCH(1,1) close path, with each bar's range scaled to the simulated
    volatility and its wick proportions resampled from the real bars.
    """
    n = len(series.close)
    rets = np.diff(np.log(np.maximum(series.close, 1e-12)))
    omega, alpha, beta = fitted or fit_garch(rets)
    span = series.high - series.low
    rel = np.where(series.close > 0, span / np.maximum(series.close, 1e-12), 0.0)
    scale = float(np.median(np.abs(rets))) or 1e-9
    #: Each bar's range as a multiple of the typical absolute return, so the
    #: range travels with the simulated volatility instead of being pasted on
    #: at the real series' level.
    ratio = rel / scale
    frac_o = np.where(span > 0, (series.open - series.low) / np.maximum(span, 1e-12), 0.5)
    frac_c = np.where(span > 0, (series.close - series.low) / np.maximum(span, 1e-12), 0.5)

    var = float(np.var(rets)) or 1e-12
    sigma2 = var
    close = np.empty(n)
    low = np.empty(n)
    high = np.empty(n)
    open_ = np.empty(n)
    price = float(series.close[0])
    close[0], low[0], high[0], open_[0] = price, price, price, price
    idx = len(ratio)
    for i in range(1, n):
        sigma = math.sqrt(max(sigma2, 1e-18))
        step = rng.gauss(0.0, 1.0) * sigma
        sigma2 = omega + alpha * step * step + beta * sigma2
        price *= math.exp(step)
        k = rng.randrange(idx)
        width = max(price * ratio[k] * sigma, price * 1e-9)
        bottom = price - frac_c[k] * width
        close[i], low[i], high[i] = price, bottom, bottom + width
        open_[i] = bottom + frac_o[k] * width
    return Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=open_,
        high=high,
        low=low,
        close=close,
    )


def plant(series: Series, price: float, strength: float, rng: random.Random) -> Series:
    """A reflecting barrier of known strength at `price`, for the power sweep.

    Every bar that closes beyond `price` is reflected back across it with
    probability `strength`, carrying its own range with it. `strength` 0 is the
    series untouched and 1 is a hard wall. This is the planted effect the skill
    asks for: a null is only worth reporting with the strength at which the
    test stops seeing one.
    """
    n = len(series.close)
    out = [series.open.copy(), series.high.copy(), series.low.copy(), series.close.copy()]
    shift = 0.0
    for i in range(n):
        c = series.close[i] + shift
        if (c - price) * (series.close[0] - price) < 0 and rng.random() < strength:
            shift += 2.0 * (price - c)
        out[0][i] = series.open[i] + shift
        out[1][i] = series.high[i] + shift
        out[2][i] = series.low[i] + shift
        out[3][i] = series.close[i] + shift
    return Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=out[0],
        high=out[1],
        low=out[2],
        close=out[3],
    )


ARMS = {
    "real": None,
    "garch-bars": garch_bars,
    "walk-geometry": walk_geometry,
    "bar-shuffle": bar_shuffle,
}


# ──────────────────────────── the level book ────────────────────────────


class _Bar:
    """What `Levels.handle_bar` reads off a bar, and nothing else.

    A Nautilus `Bar` carries fixed-precision `Price` objects and a bar type;
    constructing five million of them to drive an indicator costs more than
    the measurement. `indicators/bars.read` is duck-typed through `float()`,
    so this is the same input by the only path that matters.
    """

    __slots__ = ("close", "high", "low", "open", "ts_event", "volume")

    def __init__(self, o: float, h: float, lo: float, c: float, ts: float) -> None:
        self.open, self.high, self.low, self.close = o, h, lo, c
        self.volume = 0.0
        self.ts_event = ts * NANOS


def book_path(
    series: Series,
    *,
    reach: int = REACH,
    keep: int = KEEP,
    merge_vol: float = MERGE_VOL,
    touch_noise_vol: float = TOUCH_NOISE_VOL,
    forget: float = FORGET_BARS,
    unit_span: int = 48,
) -> list[list[tuple[float, int]]]:
    """The book as of each bar, as `(price, touches)` per level.

    The repo's own `Levels`, bar by bar, so what is measured here is what a
    strategy would read. Causal by construction: `trend.pivots` only returns a
    pivot once the window holds `reach` bars past it, and the fold is stamped
    at `pivot.confirmed`.
    """
    book = Levels(
        reach=reach,
        keep=keep,
        merge_vol=merge_vol,
        touch_noise_vol=touch_noise_vol,
        forget=forget,
        span=max(240, 2 * reach + 1),
        unit_span=unit_span,
    )
    out: list[list[tuple[float, int]]] = []
    for i in range(len(series.close)):
        book.handle_bar(
            _Bar(
                float(series.open[i]),
                float(series.high[i]),
                float(series.low[i]),
                float(series.close[i]),
                float(series.ts[i]),
            )
        )
        when = book.when
        out.append([(lv.at(when), lv.touches) for lv in book.levels])
    return out


def units(series: Series, span: int) -> np.ndarray:
    """The volatility unit: a causal EWMA of the bar range.

    The range and not a close-to-close sigma, because
    `drive-q-from-the-range` is the measured choice: the range-vs-close
    estimator ratio carries within strata on FX and on 371 of 392 equities.
    `unit_span` on the indicator does the same thing, and is passed the same
    value, so the book and the distances share one unit.
    """
    span = max(1, span)
    alpha = 2.0 / (span + 1.0)
    rng_ = series.high - series.low
    out = np.empty(len(rng_))
    cur = 0.0
    for i, x in enumerate(rng_):
        cur = x if cur <= 0.0 else (1.0 - alpha) * cur + alpha * max(x, 0.0)
        out[i] = cur
    return out


# ──────────────────────────── the measurement ────────────────────────────


@dataclass(slots=True)
class Rows:
    """One row per (anchor, side, distance). Flat, so aggregation is a mask."""

    side: np.ndarray
    dist: np.ndarray
    cls: np.ndarray
    reached: np.ndarray
    first: np.ndarray
    #: Compression quintile crossed with era, so `0 <= stratum < BINS`.
    stratum: np.ndarray
    day: np.ndarray
    touches: np.ndarray
    anchor: np.ndarray
    blocked: np.ndarray

    def __len__(self) -> int:
        return len(self.side)


#: Class codes. `OTHER` is kept rather than dropped so the three shares are
#: reportable: a rule that fires on 2% of bars is a different object than one
#: that fires on 40%, and a harness that only emits its two arms hides that.
CLEAR, SHIELD, OTHER = 0, 1, 2


def passage(series: Series, unit: np.ndarray, horizon: int, anchors: np.ndarray):
    """First-passage bar index for each anchor, each distance, each side.

    `horizon + 1` means not reached inside the window. One forward walk serves
    every distance and both sides, and any (target, stop) race is then a
    comparison of two entries rather than another walk - which is what keeps
    the target reading and the stop reading the *same* measurement.
    """
    n = len(series.close)
    nd = len(DISTANCES)
    up = np.full((len(anchors), nd), horizon + 1, dtype=np.int32)
    dn = np.full((len(anchors), nd), horizon + 1, dtype=np.int32)
    high, low = series.high, series.low
    for row, t in enumerate(anchors):
        c, u = series.close[t], unit[t]
        up_thr = [c + d * u for d in DISTANCES]
        dn_thr = [c - d * u for d in DISTANCES]
        iu = idn = 0
        hi, lo = -math.inf, math.inf
        stop = min(n, t + horizon + 1)
        for k in range(t + 1, stop):
            if high[k] > hi:
                hi = high[k]
                while iu < nd and hi >= up_thr[iu]:
                    up[row, iu] = k - t
                    iu += 1
            if low[k] < lo:
                lo = low[k]
                while idn < nd and lo <= dn_thr[idn]:
                    dn[row, idn] = k - t
                    idn += 1
            if iu == nd and idn == nd:
                break
    return up, dn


def classify(book: list[tuple[float, int]], close: float, unit: float, d: float, side: int):
    """`(class, strongest touches, levels in the path)` for one anchor and side.

    `side` is +1 for the up path and -1 for the down path. A level counts as
    shielding when it sits between `SHIELD_LO` and `SHIELD_HI` of the way to
    the target; the path is clear when nothing sits anywhere from here to
    `CLEAR_TO` of it. Everything else is `OTHER`, which is neither arm.

    **The count is returned because the two-arm split is badly unbalanced**,
    and that is a property of the book rather than a defect of the test: at
    `KEEP` 24 levels, about 80% of anchors have something in the path at 15m
    and only 7% are clear. A presence test therefore rests on a thin and
    peculiar arm - a clear path is itself a regime - so the dose version,
    which reads the reach rate against how many levels block the way, uses
    every anchor and is the one with power.
    """
    reach = d * unit
    if reach <= 0.0:
        return OTHER, 0, 0
    best = 0
    count = 0
    shielded = False
    occupied = False
    for price, touches in book:
        frac = side * (price - close) / reach
        if frac <= 0.0 or frac > CLEAR_TO:
            continue
        occupied = True
        if frac <= 1.0:
            count += 1
        if SHIELD_LO <= frac <= SHIELD_HI:
            shielded = True
            best = max(best, touches)
    if shielded:
        return SHIELD, best, count
    return (OTHER, 0, count) if occupied else (CLEAR, 0, 0)


@dataclass(slots=True)
class Walked:
    """One arm's whole forward walk: the rows, and the raw first-passage grid.

    `up` and `dn` are `(anchor, distance)` first-passage bar counts, which is
    what makes the target reading and the stop reading **one** measurement: a
    race at target `dt` against stop `ds` is `up[:, dt] < dn[:, ds]`, not
    another walk over the bars.
    """

    rows: Rows
    up: np.ndarray
    dn: np.ndarray
    anchors: np.ndarray
    unit: np.ndarray
    horizon: int
    #: Calendar day per anchor, for the block bootstrap. Days and not anchor
    #: indices: a bootstrap over overlapping anchors resamples the same
    #: twelve hours fifty times and reports an sd for a sample it does not
    #: have.
    day: np.ndarray
    #: Levels in the path at each (anchor, distance), per side, for the race.
    blocked_up: np.ndarray
    blocked_dn: np.ndarray


def measure(series: Series, settings: dict, *, step: int = 1, book=None, unit=None) -> Walked:
    """Every anchor's rows and first-passage grid, for one series on one arm."""
    horizon = settings["horizon"]
    span = settings["unit_span"]
    unit = units(series, span) if unit is None else unit
    book = book_path(series, unit_span=span) if book is None else book
    n = len(series.close)
    #: Warm-up: the book needs a few pivots and the unit needs its span.
    start = max(span, 4 * REACH + 2)
    anchors = np.arange(start, max(start, n - horizon - 1), step, dtype=np.int64)
    nd = len(DISTANCES)
    if len(anchors) == 0:
        empty = np.zeros((0, nd), dtype=np.int32)
        return Walked(
            Rows(*[np.zeros(0) for _ in range(10)]),
            empty,
            empty,
            anchors,
            unit,
            horizon,
            np.zeros(0, dtype=np.int64),
            empty,
            empty,
        )
    up, dn = passage(series, unit, horizon, anchors)

    compress = compression(unit, span)
    edges = np.nanquantile(compress[anchors], np.linspace(0, 1, STRATA + 1)[1:-1])
    #: Era by position in the anchor sequence, not by calendar date, so each
    #: era holds the same number of anchors whatever the gaps in the history.
    era_of = (np.arange(len(anchors)) * ERAS // max(1, len(anchors))).astype(np.int64)
    blocked_up = np.zeros((len(anchors), nd), dtype=np.int8)
    blocked_dn = np.zeros((len(anchors), nd), dtype=np.int8)

    cols: list[list] = [[] for _ in range(10)]
    for row, t in enumerate(anchors):
        c, u = series.close[t], unit[t]
        if u <= 0.0:
            continue
        here = book[t]
        bucket = int(np.searchsorted(edges, compress[t])) * ERAS + int(era_of[row])
        day = int(series.ts[t] // 86_400)
        for di, d in enumerate(DISTANCES):
            for side, first in ((1, up[row, di]), (-1, dn[row, di])):
                cls, touches, count = classify(here, c, u, d, side)
                if side > 0:
                    blocked_up[row, di] = min(count, 127)
                else:
                    blocked_dn[row, di] = min(count, 127)
                for col, value in zip(
                    cols,
                    (
                        side,
                        di,
                        cls,
                        1 if first <= horizon else 0,
                        first,
                        bucket,
                        day,
                        touches,
                        t,
                        count,
                    ),
                    strict=True,
                ):
                    col.append(value)
    kinds = (
        np.int8,
        np.int8,
        np.int8,
        np.int8,
        np.int32,
        np.int16,
        np.int64,
        np.int16,
        np.int64,
        np.int8,
    )
    return Walked(
        rows=Rows(*[np.asarray(c, dtype=k) for c, k in zip(cols, kinds, strict=True)]),
        up=up,
        dn=dn,
        anchors=anchors,
        unit=unit,
        horizon=horizon,
        day=(series.ts[anchors] // 86_400).astype(np.int64),
        blocked_up=blocked_up,
        blocked_dn=blocked_dn,
    )


def compression(unit: np.ndarray, span: int) -> np.ndarray:
    """`log(unit / a slower unit)`: is volatility compressed right now.

    The stratification variable. A level nearby means price turned nearby
    means a quiet stretch, and that is the whole of `topology.md`'s finding -
    so the comparison has to happen inside bins of this, never pooled.
    """
    slow = max(1, 4 * span)
    alpha = 2.0 / (slow + 1.0)
    out = np.empty(len(unit))
    cur = 0.0
    for i, x in enumerate(unit):
        cur = x if cur <= 0.0 else (1.0 - alpha) * cur + alpha * x
        out[i] = math.log(max(unit[i], 1e-18) / max(cur, 1e-18))
    return out


# ───────────────────────── the target and stop race ─────────────────────────


@dataclass(frozen=True, slots=True)
class Race:
    """A (target, stop) race, and what the walk's own geometry would pay.

    `expected` is `1/(1+N)` at `N = target / stop`, which is the walk's hit
    rate and the only number a reward:risk can be judged against. `edge_r` is
    the mean R per race at that hit rate - zero on a walk by construction, so
    it is the excess and not a return.
    """

    n: int
    target: float
    stop: float
    won: float
    expected: float
    edge_r: float
    sd: float
    #: Share of decided races where both barriers were first reached in the
    #: **same bar**, so which came first is not in the data.
    ties: float

    @property
    def z(self) -> float:
        return self.edge_r / self.sd if self.sd > 0 else 0.0


def race(
    walked: Walked,
    *,
    target: int,
    stop: int,
    side: int,
    pick: np.ndarray | None = None,
    draws: int = 200,
    seed: int = 0,
) -> Race | None:
    """The race at `DISTANCES[target]` against `DISTANCES[stop]`, one side.

    A race is **undecided** when neither barrier is reached inside the
    horizon, and those are dropped rather than scored as losses: a vertical
    barrier that expires is not a stop-out, and counting it as one is how a
    hold rate becomes a measurement of how often the window ran out
    (`Visit.broke_edge` in `indicators/levels.py` makes the same point).

    **A tie goes to the stop, and `ties` says how often that decided it.**
    Bar-level first passage cannot resolve which barrier a bar touched first
    when it touched both, so the conservative rule is the only honest one -
    and it is a *bias against the target*, biggest where the stop is tight.
    Any pattern in the edge across stop widths has to be read against the tie
    share before it is read as a finding; this is the bar-replay optimism
    `range-break-100.md` records, taken the other way round.
    """
    first_t = (walked.up if side > 0 else walked.dn)[:, target]
    first_s = (walked.dn if side > 0 else walked.up)[:, stop]
    live = (first_t <= walked.horizon) | (first_s <= walked.horizon)
    if pick is not None:
        live = live & pick
    if live.sum() < 50:
        return None
    won = (first_t < first_s)[live]
    tied = float(((first_t == first_s) & (first_t <= walked.horizon))[live].mean())
    n_over_1 = DISTANCES[target] / DISTANCES[stop]
    expected = 1.0 / (1.0 + n_over_1)
    rate = float(won.mean())
    edge = rate * n_over_1 - (1.0 - rate)
    day = walked.day[live]
    rng = random.Random(seed)
    keys = sorted(set(day.tolist()))
    spread: list[float] = []
    chunks = {k: won[day == k] for k in keys}
    for _ in range(draws):
        got = np.concatenate([chunks[keys[rng.randrange(len(keys))]] for _ in keys])
        r = float(got.mean())
        spread.append(r * n_over_1 - (1.0 - r))
    return Race(
        n=int(live.sum()),
        target=DISTANCES[target],
        stop=DISTANCES[stop],
        won=rate,
        expected=expected,
        edge_r=edge,
        sd=st.pstdev(spread) if len(spread) > 5 else 0.0,
        ties=tied,
    )
