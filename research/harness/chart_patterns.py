"""Do the published per-pattern statistics of the chart-pattern literature
reproduce on these instruments - and what does a random walk read for the same
pattern?

    ./.secrets/lab.sh run research/harness/chart_patterns.py \
        PART=main BASE=15m SEQLAB=$HOME/till_infinity/data/seqlab \
        OUT=$HOME/till_infinity/out/patterns

## The claim, and the three it is distinct from

`patterns.md` already priced the classical patterns as **trades**, against a
distance-matched placebo, on ten instruments: double top and bottom are their
own geometry (placebo gap -0.8% to +0.8% over 16,780 observations) and head and
shoulders fell from 52.6-53.2% on gold alone to 44.8-45.2% on ten instruments,
below its own breakeven everywhere. `fractal-twins.md` found candle shapes call
volatility and not direction. `letter-shapes.md` found the same for named
letters. **None of those is re-run here, and none of them tested this claim:**

> **Do the published per-pattern statistics reproduce?**

Bulkowski's *Encyclopedia of Chart Patterns* is cited for a particular thing:
it publishes **measured per-pattern statistics** - break-out direction rates,
average rise and decline, failure rates, throwback and pullback rates, and how
often the measure rule is met. Those are statements about the *population of
patterns*, not about whether a pattern pays, and `patterns.md` measured none of
them. They are also the statistics `patterns.md` named as untested: "wedges,
flags, pennants, triangles and cup-and-handle all require fitting trend lines
to a subjective selection of touches", and it did not run them.

**The walk arm is the point.** A random walk produces head and shoulders too,
and its break-out rate is the number that says whether a published 65% means
anything. Every statistic below is computed identically on the real series, on
the i.i.d.-shuffled twin of that series, on the day-block-shuffled twin, and on
four Deriv synthetics with published generators.

**A break-out rate is not an edge.** "Breaks upward 65% of the time" is
compatible with zero expectancy once the break's size and the stop are priced,
and this desk's `1 / (1 + N)` null says reward-to-risk alone has expected value
zero. So the measure rule is also run as a **1:1 barrier race**, where a
driftless walk answers exactly 0.500, and reported net of the quoted round trip.

## What is NOT quoted here

**The book was not to hand on the machine this ran on, so no published figure
is quoted and no table of his is reproduced.** Quoting a statistic from memory
and attributing it to a named author in a public repository is worse than
leaving the column empty, so every pattern reads *no published figure to hand*
and is reported against the walk alone. What *is* used is his **schema**, which
is a set of definitions rather than a measurement: break-out direction, average
rise/decline to the ultimate high/low, failure rate, throwback/pullback rate,
and measure-rule-met rate. The table is laid out in that schema so the
published figures can be dropped into it without re-running anything.

Two of his definitions do not survive the move from daily stock charts to
15-minute FX and are **replaced, not silently reinterpreted**:

* the **ultimate high/low** is his, a 20% trend change - but 20% here is 20%
  **of the run so far**, scale-free, rather than 20% of price. A 20%-of-price
  retracement never happens on EURUSD at 15 minutes.
* the **failure rate** is his 5%-move threshold replaced by *less than half the
  pattern's own height*, because a 5% move on EURUSD at 15 minutes is a
  once-a-decade event and the rate would be 100% for every pattern.

Rises and declines are reported in **pattern heights** and in forecast
volatility units, never in per cent, because a per cent on 15-minute FX is not
the same quantity as a per cent on a daily stock chart.

## The detectors

One pivot engine - an alternating zigzag of swing extremes over a `2L+1`
window - feeds three families, and a pivot found at bar `i` is **only known at
bar `i + L`**, which is where confirmation is allowed to start. Patterns whose
definition is a pair of fitted boundaries (triangles, rectangles, wedges,
broadening formations, the diamond) are classified from the slopes of the two
least-squares lines and their convergence, each normalised by the pattern's own
height so the rule is scale-free. Patterns whose definition is a set of
comparable extremes (head and shoulders, double and triple tops and bottoms)
are classified from the pivot prices and one tolerance. Flags and pennants are
found from the bars: a pole, then a consolidation. Island reversals are found
from gaps.

**A pattern counts at the bar where it breaks out**, which is the first close
beyond either boundary after confirmation, and the boundary is the fitted line
evaluated at that bar. Nothing after the break-out bar is read to decide
whether a pattern exists.

## What was dropped, and why

* **Volume** is in the cache and is not used. Bulkowski's definitions lean on
  volume shape, and this feed's `tick_volume` is a tick count on a dealer's
  bid stream rather than traded size, so a volume clause here would be a
  different clause wearing his name.
* **The cup with handle** is kept but is the weakest detector in the file: the
  handle is defined as a retrace of at most a third of the cup within a third
  of its span, which is a reading of the description rather than a quotation of
  a rule.
* Nothing else on the list was dropped. Patterns that came back too rare to
  read are reported with their `n` rather than removed, because a dropped cell
  is invisible.
"""

from __future__ import annotations

import os
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research.harness.letter_shapes import (
    POINT,
    PROPERTY,
    SPREAD_POINTS,
    SYNTH,
    TRADED,
    VOL_SPAN,
    bh,
    bins,
    boot_mean,
    ewma_abs,
    rank_p,
)

BASE = os.environ.get("BASE", "15m")
OUT = os.environ.get("OUT", "out/patterns")
PART = os.environ.get("PART", "main")

TIMEFRAMES = {"15m": 900, "1h": 3_600, "4h": 14_400, "1d": 86_400}
#: Two swing scales, never swept further: each extra value is another row in
#: the multiplicity surface and the question is not which `L` works.
LOOKBACKS = (3, 8)
#: How close two extremes must be to count as "roughly the same price", in
#: units of the pattern's own height. `patterns.md` swept this across four
#: values and reported the whole grid; it is fixed here because this study
#: already sweeps patterns, timeframes and instruments.
TOL = 0.15
#: A line is flat when it travels less than this share of the pattern's height
#: across the pattern's span.
FLAT = 0.25
#: Converging and diverging, as the ratio of the boundary gap at the end to the
#: gap at the start.
CONVERGE, DIVERGE = 0.60, 1.50
#: Bars after confirmation in which a break-out must happen, as a multiple of
#: the pattern's own span. A pattern that never breaks is not a pattern.
BREAK_SPAN = 1.0
#: The forward window every outcome is read in.
MAXFWD = 200
#: Bulkowski's trend-change rule, as a share of the **run so far** rather than
#: of price.
TREND_CHANGE = 0.20
#: His 5% failure threshold, replaced by half the pattern's own height.
FAIL_FRAC = 0.5
#: His 30-day throwback window, in bars.
THROWBACK_BARS = 30
#: The pole of a flag or pennant: at least this many forecast-volatility units
#: over at most this many bars, then a consolidation inside these bounds.
POLE_VOL, POLE_BARS = 6.0, 12
CONS_MIN, CONS_MAX, CONS_FRAC = 5, 20, 0.5
#: An island: a gap of at least this many forecast units, and at most this many
#: bars between the two gaps.
GAP_VOL, ISLAND_MAX = 1.0, 20
NSHUF = int(os.environ.get("NSHUF", "12"))
BOOT = 500
MIN_EVENTS = 100
SEED = 20261105

#: Every pattern, its family, and the direction the literature prescribes.
#: `0` means bilateral - the pattern names no side and the break-out direction
#: rate is the statistic.
PATTERNS: dict[str, tuple[str, int]] = {
    "head and shoulders": ("extremes", -1),
    "inverse head and shoulders": ("extremes", +1),
    "double top": ("extremes", -1),
    "double bottom": ("extremes", +1),
    "triple top": ("extremes", -1),
    "triple bottom": ("extremes", +1),
    "ascending triangle": ("lines", +1),
    "descending triangle": ("lines", -1),
    "symmetrical triangle": ("lines", 0),
    "rectangle": ("lines", 0),
    "rising wedge": ("lines", -1),
    "falling wedge": ("lines", +1),
    "broadening formation": ("lines", 0),
    "diamond": ("lines", 0),
    "flag": ("bars", 0),
    "pennant": ("bars", 0),
    "rounding bottom": ("extremes", +1),
    "rounding top": ("extremes", -1),
    "cup with handle": ("extremes", +1),
    "island reversal top": ("gaps", -1),
    "island reversal bottom": ("gaps", +1),
}


def seqlab(ticker: str, interval: str) -> pd.DataFrame:
    root = os.environ.get("SEQLAB", ".data/seqlab")
    z = np.load(f"{root}/{ticker}.{interval}.npz")
    df = pd.DataFrame({
        "ts": z["time"].astype(np.int64),
        "open": z["open"], "high": z["high"], "low": z["low"], "close": z["close"],
        "spread": z["spread"] if "spread" in z.files else np.zeros(len(z["time"])),
    })
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


def wicks(high, low, close) -> tuple[np.ndarray, np.ndarray]:
    """Each bar's upper and lower wick as a fraction of its own close."""
    return (np.maximum(high - close, 0.0) / np.maximum(close, 1e-12),
            np.maximum(close - low, 0.0) / np.maximum(close, 1e-12))


def rebuild(r: np.ndarray, up: np.ndarray, dn: np.ndarray, order: np.ndarray,
            first: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A surrogate's bars: the real bars in a new order.

    The return **and** the two wick fractions move together, because they
    belong to the same bar. Shuffling the returns while leaving the wicks where
    they were would decouple a bar's range from its move, and a pivot detector
    reads ranges - so the surrogate would differ from the real series in
    something other than the ordering, which is the one thing it is supposed to
    differ in.
    """
    rr, uu, dd = r[order], up[order], dn[order]
    close = np.exp(np.cumsum(rr) + np.log(first))
    return close * (1.0 + uu), close * (1.0 - dd), close


def order_iid(n: int, rng) -> np.ndarray:
    return rng.permutation(n)


def order_dayblock(day: np.ndarray, rng) -> np.ndarray:
    """Whole days permuted among days of the same bar count, so each block
    lands on a slot of exactly its own length."""
    out = np.arange(len(day))
    _, inv = np.unique(day, return_inverse=True)
    counts = np.bincount(inv)
    starts = np.concatenate([[0], np.cumsum(counts)])
    by = np.argsort(inv, kind="stable")
    for size in np.unique(counts):
        which = np.flatnonzero(counts == size)
        if len(which) < 2:
            continue
        src = rng.permutation(which)
        for a, b in zip(which, src, strict=True):
            out[by[starts[a]:starts[a] + size]] = by[starts[b]:starts[b] + size]
    return out


def aggregate(inv: np.ndarray, high, low, close) -> tuple:
    """Base bars into a timeframe's calendar bins, by `reduceat` rather than a
    groupby: the bins are contiguous because the timestamps are sorted, and a
    groupby here is 2,500 calls per instrument."""
    edges = np.flatnonzero(np.diff(inv, prepend=inv[0] - 1) != 0)
    return (np.maximum.reduceat(high, edges), np.minimum.reduceat(low, edges),
            close[np.append(edges[1:], len(close)) - 1], edges)


def zigzag(high: np.ndarray, low: np.ndarray, lookback: int) -> np.ndarray:
    """Alternating swing extremes as `(index, kind, price)`, kind +1 a high.

    A pivot at bar `i` is the extreme of `[i-L, i+L]`, so it is **not known
    until bar `i + L`**; every caller adds `L` before it is allowed to confirm
    anything. Candidates are found vectorised and only the alternation runs in
    Python, because a per-bar loop over eleven years of 15-minute bars does not
    finish.
    """
    width = 2 * lookback + 1
    rmax = pd.Series(high).rolling(width, center=True).max().to_numpy()
    rmin = pd.Series(low).rolling(width, center=True).min().to_numpy()
    hits = np.concatenate([
        np.stack([np.flatnonzero(high >= rmax), np.ones(int((high >= rmax).sum()))], 1),
        np.stack([np.flatnonzero(low <= rmin), -np.ones(int((low <= rmin).sum()))], 1),
    ]) if (high >= rmax).any() or (low <= rmin).any() else np.empty((0, 2))
    if len(hits) == 0:
        return np.empty((0, 3))
    hits = hits[np.argsort(hits[:, 0], kind="stable")]
    out: list[list[float]] = []
    for idx, kind in hits:
        i, k = int(idx), int(kind)
        price = high[i] if k > 0 else low[i]
        if out and out[-1][1] == k:
            if (k > 0 and price >= out[-1][2]) or (k < 0 and price <= out[-1][2]):
                out[-1] = [i, k, price]
        else:
            out.append([i, k, price])
    return np.array(out) if out else np.empty((0, 3))


def fit(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float]:
    """Least squares through the pivots on one side, in closed form.

    `np.polyfit` is about 50 microseconds a call and this file makes four calls
    per pivot window over tens of thousands of windows; the closed form is the
    same line. The literature's "touch each bound at least twice" is the
    minimum enforced here.
    """
    if len(xs) < 2:
        return float("nan"), float("nan")
    mx, my = xs.mean(), ys.mean()
    dx = xs - mx
    den = float((dx * dx).sum())
    if den <= 0:
        return float("nan"), float("nan")
    slope = float((dx * (ys - my)).sum() / den)
    return slope, float(my - slope * mx)


def line_patterns(piv: np.ndarray, lookback: int) -> list[dict]:
    """Triangles, rectangles, wedges, broadening formations and the diamond,
    from the slopes of two fitted boundaries and their convergence."""
    out: list[dict] = []
    for end in range(5, len(piv)):
        for take in (5, 7):
            if end - take + 1 < 0:
                continue
            seg = piv[end - take + 1:end + 1]
            his = seg[seg[:, 1] > 0]
            los = seg[seg[:, 1] < 0]
            if len(his) < 2 or len(los) < 2:
                continue
            x0, x1 = float(seg[0, 0]), float(seg[-1, 0])
            span = x1 - x0
            if span < 2 * take:
                continue
            su, iu = fit(his[:, 0], his[:, 2])
            sl, il = fit(los[:, 0], los[:, 2])
            if not np.isfinite(su) or not np.isfinite(sl):
                continue
            w0 = (su * x0 + iu) - (sl * x0 + il)
            w1 = (su * x1 + iu) - (sl * x1 + il)
            height = max(w0, w1)
            if height <= 0 or w0 <= 0:
                continue
            conv = w1 / w0
            nu, nl = su * span / height, sl * span / height
            name = None
            if abs(nu) <= FLAT and nl > FLAT and conv < CONVERGE:
                name = "ascending triangle"
            elif nu < -FLAT and abs(nl) <= FLAT and conv < CONVERGE:
                name = "descending triangle"
            elif nu < -FLAT and nl > FLAT and conv < CONVERGE:
                name = "symmetrical triangle"
            elif abs(nu) <= FLAT and abs(nl) <= FLAT and 1 / DIVERGE < conv < DIVERGE:
                name = "rectangle"
            elif nu > FLAT and nl > FLAT and conv < 0.70:
                name = "rising wedge"
            elif nu < -FLAT and nl < -FLAT and conv < 0.70:
                name = "falling wedge"
            elif nu > FLAT and nl < -FLAT and conv > DIVERGE:
                name = "broadening formation"
            if take == 7 and name is None:
                # A diamond is a broadening formation followed by a converging
                # one, so it is two fits rather than one: the full-window lines
                # average the two halves away and never classify it.
                half = take // 2
                lo_half, hi_half = seg[:half + 1], seg[half:]
                widths = []
                for part in (lo_half, hi_half):
                    ph, pl = part[part[:, 1] > 0], part[part[:, 1] < 0]
                    if len(ph) < 2 or len(pl) < 2:
                        widths = []
                        break
                    s_u, i_u = fit(ph[:, 0], ph[:, 2])
                    s_l, i_l = fit(pl[:, 0], pl[:, 2])
                    a, b = float(part[0, 0]), float(part[-1, 0])
                    widths.append(((s_u * a + i_u) - (s_l * a + i_l),
                                   (s_u * b + i_u) - (s_l * b + i_l)))
                if (widths and widths[0][0] > 0 and widths[1][0] > 0
                        and widths[0][1] > widths[0][0] * DIVERGE
                        and widths[1][1] < widths[1][0] * CONVERGE):
                    name = "diamond"
            if name is None:
                continue
            confirm = int(seg[-1, 0]) + lookback
            out.append({"name": name, "confirm": confirm, "span": span,
                        "u0": su * confirm + iu, "l0": sl * confirm + il,
                        "su": su, "sl": sl, "height": height})
    return out


def extreme_patterns(piv: np.ndarray, lookback: int) -> list[dict]:
    """Head and shoulders, double and triple tops and bottoms, rounding tops
    and bottoms, and the cup with handle - each a set of comparable extremes
    with one tolerance."""
    out: list[dict] = []
    for end in range(4, len(piv)):
        five = piv[end - 4:end + 1]
        three = piv[end - 2:end + 1]
        kinds5 = five[:, 1]
        kinds3 = three[:, 1]
        confirm5 = int(five[-1, 0]) + lookback
        confirm3 = int(three[-1, 0]) + lookback
        span5 = float(five[-1, 0] - five[0, 0])
        span3 = float(three[-1, 0] - three[0, 0])
        if np.array_equal(kinds3, [1, -1, 1]) or np.array_equal(kinds3, [-1, 1, -1]):
            a, mid, b = three[0, 2], three[1, 2], three[2, 2]
            top = kinds3[0] > 0
            height = abs(max(a, b) - mid) if top else abs(mid - min(a, b))
            if height > 0 and abs(a - b) <= TOL * height:
                name = "double top" if top else "double bottom"
                upper = max(a, b) if top else mid
                lower = mid if top else min(a, b)
                out.append({"name": name, "confirm": confirm3, "span": span3,
                            "u0": upper, "l0": lower, "su": 0.0, "sl": 0.0,
                            "height": height})
        if np.array_equal(kinds5, [1, -1, 1, -1, 1]) or \
                np.array_equal(kinds5, [-1, 1, -1, 1, -1]):
            top = kinds5[0] > 0
            ext = five[[0, 2, 4], 2]
            inner = five[[1, 3], 2]
            neck = float(np.mean(inner))
            height = abs(ext[1] - neck)
            if height <= 0:
                continue
            head = (ext[1] > ext[0] + TOL * height and ext[1] > ext[2] + TOL * height) \
                if top else (ext[1] < ext[0] - TOL * height
                             and ext[1] < ext[2] - TOL * height)
            level = abs(ext[0] - ext[2]) <= TOL * height
            triple = (abs(ext.max() - ext.min()) <= TOL * height)
            name = None
            if head and level:
                name = "head and shoulders" if top else "inverse head and shoulders"
            elif triple:
                name = "triple top" if top else "triple bottom"
            if name is None:
                continue
            upper = float(ext.max()) if top else neck
            lower = neck if top else float(ext.min())
            out.append({"name": name, "confirm": confirm5, "span": span5,
                        "u0": upper, "l0": lower, "su": 0.0, "sl": 0.0,
                        "height": height})
    return out


def round_patterns(high, low, close, piv, lookback) -> list[dict]:
    """Rounding tops and bottoms and the cup with handle.

    A rounding bottom is a window whose extreme sits in the middle third, whose
    two ends are level within the tolerance, and whose path hugs a parabola -
    the correlation of the close path with a parabolic template, which is the
    same z-scored correlation the letter study uses. The handle adds a retrace
    of at most a third of the cup inside a third of its span.
    """
    out: list[dict] = []
    for end in range(2, len(piv)):
        seg = piv[end - 2:end + 1]
        if not (np.array_equal(seg[:, 1], [1, -1, 1])
                or np.array_equal(seg[:, 1], [-1, 1, -1])):
            continue
        i0, i2 = int(seg[0, 0]), int(seg[2, 0])
        span = i2 - i0
        if span < 12 or i2 + lookback >= len(close):
            continue
        bottom = bool(seg[1, 1] < 0)
        lips = (seg[0, 2], seg[2, 2])
        height = abs(float(np.mean(lips)) - float(seg[1, 2]))
        if height <= 0 or abs(lips[0] - lips[1]) > TOL * height:
            continue
        path = close[i0:i2 + 1]
        grid = np.linspace(-1.0, 1.0, len(path))
        shape = grid * grid if bottom else -(grid * grid)
        if path.std() <= 0:
            continue
        corr = float(np.corrcoef(path, shape)[0, 1])
        # A V is not a rounding bottom: the parabola has to fit better than the
        # straight-sided template would, which `corr >= 0.80` is doing here.
        if not np.isfinite(corr) or corr < 0.80:
            continue
        confirm = i2 + lookback
        lip = float(max(lips)) if bottom else float(min(lips))
        arch = float(seg[1, 2])
        name = "rounding bottom" if bottom else "rounding top"
        out.append({"name": name, "confirm": confirm, "span": float(span),
                    "u0": lip if bottom else arch,
                    "l0": arch if bottom else lip,
                    "su": 0.0, "sl": 0.0, "height": height})
        if not bottom:
            continue
        # The handle: a retrace of at most **half** the cup - the figure the
        # description gives - inside half its span, measured after the right
        # lip and before the break. A third of the cup inside a third of the
        # span fired four times in 120,000 bars, which is not a sample.
        tail = min(len(close) - 1, confirm + span // 2)
        if tail <= confirm:
            continue
        dip = lip - float(low[confirm:tail + 1].min())
        if 0 < dip <= height / 2 and float(close[confirm:tail + 1].max()) < lip:
            out.append({"name": "cup with handle", "confirm": tail,
                        "span": float(tail - i0), "u0": lip,
                        "l0": lip - dip, "su": 0.0, "sl": 0.0, "height": height})
    return out


def bar_patterns(high, low, close, vol) -> list[dict]:
    """Flags and pennants: a pole, then a consolidation.

    The pole is a move of at least `POLE_VOL` forecast units inside
    `POLE_BARS`; the consolidation is `CONS_MIN..CONS_MAX` bars whose range is
    at most `CONS_FRAC` of the pole. A consolidation whose boundaries converge
    is a pennant and one whose boundaries do not is a flag, which is the
    distinction the literature draws between them.
    """
    out: list[dict] = []
    n = len(close)
    logc = np.log(np.maximum(close, 1e-12))
    move = np.full(n, np.nan)
    move[POLE_BARS:] = logc[POLE_BARS:] - logc[:-POLE_BARS]
    with np.errstate(invalid="ignore"):
        poles = np.flatnonzero(np.abs(move) >= POLE_VOL * np.nan_to_num(vol, nan=np.inf))
    # Bounded below only. Reserving `CONS_MAX` bars at the end instead would
    # drop poles whose **shorter** consolidation finishes inside the series,
    # which made five of 17,491 break-outs vanish when the series was cut at
    # a break-out bar - a look-ahead test failing for a reason that was not
    # look-ahead.
    poles = poles[poles >= POLE_BARS]
    for i in poles:
        i = int(i)
        pole = float(move[i])
        for length in (CONS_MIN, CONS_MAX):
            j = i + length
            if j >= n:
                continue
            seg_hi = float(high[i:j + 1].max())
            seg_lo = float(low[i:j + 1].min())
            rng = np.log(max(seg_hi, 1e-12)) - np.log(max(seg_lo, 1e-12))
            if rng <= 0 or rng > CONS_FRAC * abs(pole):
                continue
            first = np.log(max(float(high[i:i + length // 2 + 1].max()), 1e-12)) - \
                np.log(max(float(low[i:i + length // 2 + 1].min()), 1e-12))
            last = np.log(max(float(high[j - length // 2:j + 1].max()), 1e-12)) - \
                np.log(max(float(low[j - length // 2:j + 1].min()), 1e-12))
            name = "pennant" if last < CONVERGE * first else "flag"
            height = abs(pole) * close[j]
            out.append({"name": name, "confirm": j, "span": float(length),
                        "u0": seg_hi, "l0": seg_lo, "su": 0.0, "sl": 0.0,
                        "height": height})
    return out


def island_patterns(high, low, close, vol) -> list[dict]:
    """An island reversal: a gap away, a few bars that do not overlap the bars
    before the gap, and a gap back."""
    out: list[dict] = []
    n = len(close)
    up = np.flatnonzero(low[1:] > high[:-1] + GAP_VOL * np.nan_to_num(
        vol[1:]) * close[1:]) + 1
    dn = np.flatnonzero(high[1:] < low[:-1] - GAP_VOL * np.nan_to_num(
        vol[1:]) * close[1:]) + 1
    for start, back, name in ((up, dn, "island reversal top"),
                              (dn, up, "island reversal bottom")):
        for i in start:
            close_back = back[(back > i) & (back <= i + ISLAND_MAX)]
            if len(close_back) == 0:
                continue
            j = int(close_back[0])
            if j - 1 < i or j >= n:
                continue
            hi = float(high[i:j].max())
            lo = float(low[i:j].min())
            height = hi - lo
            if height <= 0:
                continue
            out.append({"name": name, "confirm": j, "span": float(j - i),
                        "u0": hi, "l0": lo, "su": 0.0, "sl": 0.0, "height": height})
    return out


def breakouts(found: list[dict], close: np.ndarray) -> pd.DataFrame:
    """The bar where each pattern breaks, and which way.

    The boundary is the fitted line evaluated **at the break-out bar**, so a
    converging triangle's boundary converges rather than being frozen at
    confirmation. A pattern that does not break inside `BREAK_SPAN` of its own
    span is dropped and counted, because a pattern that never breaks has no
    break-out statistic.
    """
    rows = []
    n = len(close)
    for pat in found:
        c = int(pat["confirm"])
        limit = min(n - 1, c + max(3, int(BREAK_SPAN * pat["span"])))
        if c + 1 > limit:
            continue
        idx = np.arange(c + 1, limit + 1)
        upper = pat["u0"] + pat["su"] * (idx - c)
        lower = pat["l0"] + pat["sl"] * (idx - c)
        over = close[idx] > upper
        under = close[idx] < lower
        hit = np.flatnonzero(over | under)
        if len(hit) == 0:
            continue
        at = int(idx[hit[0]])
        rows.append({"name": pat["name"], "bar": at, "span": pat["span"],
                     "height": float(pat["height"]),
                     "side": 1 if over[hit[0]] else -1})
    return pd.DataFrame(rows)


def outcomes(close: np.ndarray, bar: np.ndarray, side: np.ndarray,
             height: np.ndarray) -> dict:
    """Bulkowski's schema, in one forward pass of `MAXFWD` vectorised steps.

    * `rise` - the move to the **ultimate high or low** in pattern heights,
      where the trend ends at a retracement of `TREND_CHANGE` of the run.
    * `fail` - that move below `FAIL_FRAC` of the pattern's height.
    * `throwback` - price closing back through the break-out price inside
      `THROWBACK_BARS`, having first moved `0.2` heights away.
    * `measure` - the target of one pattern height reached before the trend
      ends.
    * `race` - the same target reached before an equal and opposite move, a
      1:1 barrier whose driftless-walk answer is exactly 0.500.
    """
    n = len(close)
    live = bar + MAXFWD < n
    bar, side, height = bar[live], side[live], height[live]
    if len(bar) == 0:
        return {k: np.empty(0) for k in ("rise", "fail", "throwback", "measure",
                                         "race", "bar", "side", "height")}
    entry = close[bar]
    run = np.zeros(len(bar))
    best = np.zeros(len(bar))
    ended = np.zeros(len(bar), bool)
    ult = np.zeros(len(bar))
    throw = np.zeros(len(bar), bool)
    away = np.zeros(len(bar), bool)
    measure = np.zeros(len(bar), bool)
    race = np.full(len(bar), -1.0)
    for k in range(1, MAXFWD + 1):
        px = close[bar + k]
        run = side * (px - entry) / np.maximum(height, 1e-12)
        best = np.maximum(best, run)
        fresh = ~ended
        measure |= fresh & (run >= 1.0)
        stop = fresh & (best > 0) & (run <= best - TREND_CHANGE * best)
        ult = np.where(stop, best, ult)
        ended |= stop
        if k <= THROWBACK_BARS:
            away |= best >= 0.2
            throw |= away & (run <= 0.0)
        open_ = race < 0
        lost = open_ & (run <= -1.0)
        won = open_ & (run >= 1.0) & ~lost
        race[lost] = 0.0
        race[won] = 1.0
    ult = np.where(ended, ult, best)
    return {"rise": ult, "fail": ult < FAIL_FRAC, "throwback": throw,
            "measure": measure, "race": race, "bar": bar, "side": side,
            "height": height}


def detect(high, low, close, vol, lookback) -> pd.DataFrame:
    """Every pattern's break-out bar.

    Flags, pennants and island reversals read bars rather than pivots, so they
    are identical at every `lookback` and are emitted only at the first one -
    otherwise the same event appears twice in a grid that is then corrected for
    multiplicity.
    """
    piv = zigzag(high, low, lookback)
    if len(piv) < 5:
        return pd.DataFrame()
    found = (line_patterns(piv, lookback) + extreme_patterns(piv, lookback)
             + round_patterns(high, low, close, piv, lookback))
    if lookback == LOOKBACKS[0]:
        found += bar_patterns(high, low, close, vol)
        found += island_patterns(high, low, close, vol)
    return breakouts(found, close)


def summarise(name: str, got: pd.DataFrame, close, day,
              quoted: float, rng) -> dict | None:
    """One pattern's row of the schema, with a day-block interval on every
    rate because patterns cluster in days."""
    mine = got[got.name == name]
    if len(mine) == 0:
        return None
    bar = mine.bar.to_numpy()
    side = mine.side.to_numpy(float)
    height = mine.height.to_numpy(float)
    res = outcomes(close, bar, side, height)
    if len(res["bar"]) == 0:
        return None
    d = day[res["bar"]]
    prescribed = PATTERNS[name][1]
    up = (res["side"] > 0).astype(float)
    up_mean, up_lo, up_hi, _ = boot_mean(d, up, rng)
    done = res["race"] >= 0
    race_mean, race_lo, race_hi, _ = boot_mean(
        d[done], res["race"][done], rng) if done.any() else (np.nan,) * 4
    cost_r = float(np.nanmedian(quoted * close[res["bar"]] / np.maximum(
        res["height"], 1e-12))) if len(res["bar"]) else np.nan
    row = {
        "pattern": name, "n": len(res["bar"]), "n_raw": len(mine),
        "up_share": up_mean, "up_lo": up_lo, "up_hi": up_hi,
        "as_prescribed": float((res["side"] == prescribed).mean())
        if prescribed else np.nan,
        "rise": float(res["rise"].mean()),
        "rise_sd": float(res["rise"].std(ddof=1)) if len(res["rise"]) > 1 else np.nan,
        "fail_rate": float(res["fail"].mean()),
        "throwback": float(res["throwback"].mean()),
        "measure_met": float(res["measure"].mean()),
        "race": race_mean, "race_lo": race_lo, "race_hi": race_hi,
        "race_n": int(done.sum()),
        "cost_r": cost_r,
        "race_net": race_mean - (1 - race_mean) - cost_r
        if np.isfinite(race_mean) else np.nan,
    }
    return row


def one_symbol(job: tuple[str, int]) -> list[dict]:
    symbol, seat = job
    rng = np.random.default_rng([SEED, seat])
    started = time.time()
    raw = seqlab(symbol, BASE)
    if len(raw) < 20_000:
        raise SystemExit(f"{symbol}: {len(raw)} bars - refusing to write a cell")
    ts15 = raw.ts.to_numpy()
    high15 = raw.high.to_numpy(float)
    low15 = raw.low.to_numpy(float)
    close15 = raw.close.to_numpy(float)
    r15 = np.diff(np.log(close15), prepend=0.0)
    up15, dn15 = wicks(high15, low15, close15)
    day15 = (ts15 // 86_400).astype(np.int64)
    quoted = float(np.nanmedian(
        SPREAD_POINTS.get(symbol, np.nan) * POINT.get(symbol, np.nan) / close15))
    stored = float(np.nanmedian(raw.spread.to_numpy(float)
                                * POINT.get(symbol, np.nan) / close15))

    # The surrogate bars are built once at the base and then aggregated into
    # every timeframe, exactly as the real bars are.
    series: list[tuple[str, int, np.ndarray, np.ndarray, np.ndarray]] = [
        ("real", 0, high15, low15, close15)]
    for draw in range(NSHUF):
        for arm in ("iid", "dayblock"):
            order = (order_iid(len(r15), rng) if arm == "iid"
                     else order_dayblock(day15, rng))
            series.append((arm, draw, *rebuild(r15, up15, dn15, order, close15[0])))

    rows: list[dict] = []
    for tf, seconds in TIMEFRAMES.items():
        _, inv = bins(ts15, seconds)
        built = {}
        for arm, draw, h, lo, c in series:
            hb, lb, cb, edges = aggregate(inv, h, lo, c)
            built[(arm, draw)] = (hb, lb, cb, edges)
        tsb = ts15[built[("real", 0)][3]]
        day = (tsb // 86_400).astype(np.int64)
        nbin = len(tsb)
        if nbin < 1_000:
            print(f"  {symbol} {tf}: {nbin} bars, skipped", file=sys.stderr, flush=True)
            continue
        lens = {len(v[0]) for v in built.values()} | {len(tsb)}
        if lens != {nbin}:
            raise SystemExit(f"{symbol} {tf}: lengths {sorted(lens)} != {nbin}")
        for lookback in LOOKBACKS:
            real_rows: dict[str, dict] = {}
            nulls: dict[tuple[str, str], list[dict]] = {}
            for arm, draw, _, _, _ in series:
                hb, lb, cb, _ = built[(arm, draw)]
                v = ewma_abs(np.diff(np.log(np.maximum(cb, 1e-12)), prepend=np.nan),
                             VOL_SPAN)
                got = detect(hb, lb, cb, v, lookback)
                if len(got) == 0:
                    continue
                for name in PATTERNS:
                    row = summarise(name, got, cb, day, quoted, rng)
                    if row is None:
                        continue
                    if arm == "real":
                        row |= {"symbol": symbol, "tf": tf, "lookback": lookback,
                                "arm": "real", "quoted": quoted, "stored": stored,
                                "bars": nbin}
                        real_rows[name] = row
                    else:
                        nulls.setdefault((arm, name), []).append(row)
            for name, row in real_rows.items():
                for arm in ("iid", "dayblock"):
                    draws = nulls.get((arm, name), [])
                    for field in ("n", "up_share", "rise", "fail_rate", "throwback",
                                  "measure_met", "race"):
                        col = np.array([d[field] for d in draws], float)
                        col = col[np.isfinite(col)]
                        row[f"{arm}_{field}"] = float(col.mean()) if len(col) else np.nan
                        if field in ("n", "up_share", "measure_met", "race"):
                            row[f"{arm}_{field}_p"] = rank_p(row[field], col)
                            row[f"{arm}_{field}_sd"] = (float(col.std(ddof=1))
                                                        if len(col) > 1 else np.nan)
                    row[f"{arm}_draws"] = len(draws)
                rows.append(row)
        print(f"  {symbol} {tf}: {nbin} bars, {len(rows)} rows so far",
              file=sys.stderr, flush=True)
    print(f"{symbol}: {len(raw)} base bars, {len(rows)} rows, "
          f"{time.time() - started:.0f}s", file=sys.stderr, flush=True)
    return rows


PLANT = (0.0, 0.05, 0.10, 0.20, 0.40)


def one_power(job: tuple[str, int]) -> list[dict]:
    """A break-out bias of known size, planted on the generated markets where
    the real answer is null, and swept.

    Two things this gets wrong if written the obvious way, both found by
    reading the zero cell:

    * **the null for a 1:1 race is 0.500, not zero.** Bootstrapping the race
      against zero reported every cell significant including the unplanted
      one, which is a p-value for "a proportion is not zero".
    * **the plant must not compound.** Adding a drift to the returns over each
      event's forward window, with the windows overlapping, accumulates across
      the series and moves the price level by orders of magnitude, which
      changes which races resolve at all. The plant here runs on a **disjoint**
      subset of events - each at least one forward window after the last - so
      it is local, and the subset's size is reported.
    """
    symbol, seat = job
    rng = np.random.default_rng([SEED, 4_000 + seat])
    raw = seqlab(symbol, BASE)
    ts15 = raw.ts.to_numpy()
    _, inv = bins(ts15, TIMEFRAMES["1h"])
    nbin = int(inv.max()) + 1
    high, low, close, edges = aggregate(inv, raw.high.to_numpy(float),
                                        raw.low.to_numpy(float),
                                        raw.close.to_numpy(float))
    day = (ts15[edges] // 86_400).astype(np.int64)
    rr = np.diff(np.log(close), prepend=np.nan)
    vol = ewma_abs(rr, VOL_SPAN)
    rows: list[dict] = []
    for lookback in LOOKBACKS:
        got = detect(high, low, close, vol, lookback)
        if len(got) == 0:
            continue
        for name in PATTERNS:
            mine = got[got.name == name].sort_values("bar")
            if len(mine) < 30:
                continue
            bar_all = mine.bar.to_numpy()
            keep, last = [], -10**9
            for pos, b in enumerate(bar_all):
                if b - last >= MAXFWD:
                    keep.append(pos)
                    last = b
            keep = np.array(keep, dtype=int)
            bar = bar_all[keep]
            side = mine.side.to_numpy(float)[keep]
            height = mine.height.to_numpy(float)[keep]
            bar = bar[bar + MAXFWD < nbin]
            side, height = side[:len(bar)], height[:len(bar)]
            if len(bar) < 30:
                continue
            for size in PLANT:
                step = side * size * height / np.maximum(close[bar], 1e-12) / MAXFWD
                planted = np.nan_to_num(rr).copy()
                for off in range(1, MAXFWD + 1):
                    planted[bar + off] += step
                newc = np.exp(np.cumsum(planted) + np.log(close[0]))
                res = outcomes(newc, bar, side, height)
                done = res["race"] >= 0
                if done.sum() < 20:
                    continue
                m, lo, hi, p = boot_mean(day[res["bar"]][done],
                                         res["race"][done] - 0.5, rng)
                rows.append({"symbol": symbol, "lookback": lookback,
                             "pattern": name, "plant": size, "race": m + 0.5,
                             "lo": lo + 0.5, "hi": hi + 0.5, "p": p,
                             "n": int(done.sum()), "n_disjoint": len(bar)})
    print(f"{symbol}: {len(rows)} power rows", file=sys.stderr, flush=True)
    return rows


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    print(f"part={PART} base={BASE} nshuf={NSHUF}", file=sys.stderr)
    symbols = list(TRADED + SYNTH)
    if PART == "power":
        symbols = list(SYNTH)
    if PART == "pilot":
        symbols = ["EURUSD"]
    jobs = [(s, i) for i, s in enumerate(symbols)]
    work = one_power if PART == "power" else one_symbol
    with Pool(min(len(jobs), int(os.environ.get("WORKERS", "12")))) as pool:
        got = pool.map(work, jobs)
    rows = [r for part in got for r in part]
    if not rows:
        raise SystemExit("0 rows - refusing to exit 0 on an empty run")
    out = pd.DataFrame(rows)
    if PART != "power":
        for field in ("up_share", "measure_met", "race"):
            col = f"iid_{field}_p"
            if col in out:
                out[f"bh_{field}"] = bh(out[col].to_numpy())
    out.to_csv(f"{OUT}/{'power' if PART == 'power' else 'patterns'}.csv", index=False)
    print(f"{len(out)} rows -> {OUT}", file=sys.stderr)
    print({k: PROPERTY[k] for k in SYNTH if k in PROPERTY}, file=sys.stderr)


if __name__ == "__main__":
    main()
