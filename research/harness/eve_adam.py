"""An Eve-and-Adam double bottom, stopped at half the pattern height and
targeted at the measure rule: does it beat `1/(1+2)`?

    ./.secrets/lab.sh run research/harness/eve_adam.py \
        PART=main BASE=15m SEQLAB=$HOME/till_infinity/data/seqlab \
        OUT=$HOME/till_infinity/out/eve_adam

## The rule, and the two things it adds to what is already measured

[`chart-patterns.md`](../docs/chart-patterns.md) ran a **generic** double bottom
as a **1:1** race and found it on 0.500. This rule is narrower in two ways, and
both are the point:

1. **The Eve/Adam sub-classification.** Bulkowski distinguishes Eve-Eve,
   Eve-Adam, Adam-Eve and Adam-Adam, where an Adam bottom is a narrow V - often
   a one- or two-bar spike - and an Eve bottom is wide and rounded. All four
   are reported here, not Eve-Adam alone: a four-way split is a finer claim,
   and a sub-classification that is really noise is a worse answer than an
   empty cell. **Whether the four are separable at all is tested before any of
   them is traded**, with two criteria that are measured independently.
2. **The geometry is 2:1, not 1:1.** Target at one pattern height projected
   from the break-out, stop at half a pattern height, so a driftless walk
   answers **1/(1+2) = 0.3333** and not 0.500. The walk arms answer it for
   themselves here rather than being handed 0.3333 on trust.

## Three things already measured that decide this before it runs

* **The measure rule is volatility clustering.** `chart-patterns.md` found 274
  of 919 measure-rule-met cells survive BH against the i.i.d. walk at up to
  2.5x its rate, and the **day-block shuffle reproduces it almost exactly**
  (head and shoulders 0.070 real, 0.045 i.i.d., 0.074 day-block). This rule's
  target *is* the measure rule, so a high hit rate against the i.i.d. walk is
  already explained. **The day-block arm is the one that decides this rule**,
  and the i.i.d. arm is carried to show the difference.
* **Halving the stop doubles the cost in R.** Cost in R is `cost_px / risk` and
  `risk` is the stop. At 1:1 - a stop twice as wide as this one - 6 of 8 traded
  instruments were already negative net of the quoted round trip. Cost in R is
  printed beside every hit rate here.
* **The 1:1 race on these same events is the control.** It is recomputed on
  exactly this event set rather than quoted, so "0.500 at 1:1 and 0.333 at 2:1"
  is a statement about the same patterns. If both hold, the pattern is a fair
  game at both geometries and `1/(1+N)` is doing what it does.

## The classification, as frozen before the run

A bottom is described by **two quantities that are measured from different
things**, so that their agreement is evidence rather than arithmetic:

* **width**, `w`: the number of bars in the contiguous run containing the
  bottom whose low sits within `WIDTH_FRAC` of the pattern height above the
  bottom price. Measured inside the bottom's own pivot window `[i-L, i+L]`,
  which is exactly the information that made it a pivot - so it is known at
  confirmation and reads no bar the detector has not already read.
* **shape**, `v`: the correlation of the z-scored close path over that same
  window with a **V** template minus its correlation with a **U** template,
  using the templates from [`letter_shapes.py`](letter_shapes.py). Positive is
  V-like, negative is rounded.

The label comes from the **width** alone - `Adam` at `w <= 2` bars, which is
the description's "one- or two-bar spike", `Eve` at `w >= 5`, and
**`unclassified` in between, reported rather than forced into a bucket**. The
**shape** is never used to label; it is held back as the independent criterion
the width is scored against, and Cohen's kappa between the two is the
separability test. A kappa near zero means the two criteria disagree and the
four-way split is noise.

## The nulls

Identical to `chart-patterns.md`: 12 i.i.d.-shuffled twins and 12
day-block-shuffled twins per instrument, each carrying every bar's return and
its two wick fractions together; four Deriv synthetics, each for one named
property of its published generator, as the arm that must come back empty; a
day-block bootstrap on every rate; and Benjamini-Hochberg over the full cell
count including the four variants.
"""

from __future__ import annotations

import os
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research.harness.chart_patterns import (
    BREAK_SPAN,
    LOOKBACKS,
    MAXFWD,
    TIMEFRAMES,
    TOL,
    aggregate,
    bins,
    order_dayblock,
    order_iid,
    rebuild,
    seqlab,
    wicks,
    zigzag,
)
from research.harness.letter_shapes import (
    POINT,
    PROPERTY,
    SPREAD_POINTS,
    SYNTH,
    TRADED,
    bh,
    boot_mean,
    rank_p,
)

BASE = os.environ.get("BASE", "15m")
OUT = os.environ.get("OUT", "out/eve_adam")
PART = os.environ.get("PART", "main")

#: The level, as a share of the pattern height above the bottom, at which a
#: bottom's width is read.
WIDTH_FRAC = 0.25
#: The half-window the width and the duration are read in, in bars, **fixed
#: and independent of the pivot lookback**. Reading them inside the pivot's own
#: window instead capped the width at `2L+1` and made the whole classification
#: a function of `L`: on a 200,000-step walk the mix went from 31% Adam-Adam
#: and 3.9% Eve-Eve at L=3 to 9.4% and 23% at L=8, which is a statement about
#: the detector and not about the bottoms.
#:
#: **Four, because it is the largest half-window that drops nothing.** A
#: pattern whose break-out arrives before the right bottom's window closes
#: cannot be labelled without reading past the break-out, so it would have to
#: be dropped - and dropping selects on how fast the break-out came, which is a
#: property of the trade. At 4 the drop rate is **0% at both lookbacks**
#: (against 27% at 5, 43% at 6 and 67% at 8 for `L = 3`), and the agreement
#: between the two criteria is also highest there: Spearman +0.67, kappa +0.62.
WIDTH_WIN = 4
#: "A one- or two-bar spike", and "wide and rounded".
ADAM_W, EVE_W = 2, 5
#: The trade: target one pattern height, stop half a pattern height, so the
#: driftless-walk answer is exactly 1/(1+2).
TARGET_H, STOP_H = 1.0, 0.5
NSHUF = int(os.environ.get("NSHUF", "12"))
BOOT = 500
MIN_EVENTS = 100
SEED = 20261105
VARIANTS = ("Eve-Eve", "Eve-Adam", "Adam-Eve", "Adam-Adam")


def fair_rate() -> float:
    """`1/(1+N)` for this geometry: N = target / stop = 2, so 0.3333."""
    return 1.0 / (1.0 + TARGET_H / STOP_H)


def classify(low: np.ndarray, close: np.ndarray, i: int, price: float,
             height: float) -> tuple[int, int]:
    """One bottom's **width** in bars and its **duration** in bars.

    Two measurements of the same idea - how narrow the bottom is - computed
    from different things, so that their agreement is evidence rather than
    arithmetic:

    * `width`: bars in the contiguous run containing the bottom whose **low**
      sits within `WIDTH_FRAC` of the pattern height above the bottom price.
    * `duration`: bars from the last **close** above half the pattern height
      down to the bottom, plus bars from the bottom back up to the first close
      above that level. A different level, a different series and a different
      shape of count.

    Both inside `[i - WIDTH_WIN, i + WIDTH_WIN]`, which the caller guarantees
    closes at or before the break-out bar.
    """
    lo = max(0, i - WIDTH_WIN)
    hi = min(len(close) - 1, i + WIDTH_WIN)
    level = price + WIDTH_FRAC * height
    inside = low[lo:hi + 1] <= level
    here = i - lo
    width = 1
    j = here - 1
    while j >= 0 and inside[j]:
        width += 1
        j -= 1
    j = here + 1
    while j < len(inside) and inside[j]:
        width += 1
        j += 1
    half = price + 0.5 * height
    ahead = close[i:hi + 1]
    up = np.flatnonzero(ahead >= half)
    back = close[lo:i + 1][::-1]
    down = np.flatnonzero(back >= half)
    recover = int(up[0]) if len(up) else WIDTH_WIN + 1
    descend = int(down[0]) if len(down) else WIDTH_WIN + 1
    return width, recover + descend


def roundedness(close: np.ndarray, i: int) -> float:
    """R-squared of a quadratic minus R-squared of a V kinked at the bottom.

    **Reported and not used.** It was the first candidate for the second
    criterion and it does not work: on a 200,000-step walk it separates narrow
    bottoms from wide ones by 0.20 standard deviations at one lookback and
    -0.03 at the other, for a kappa of +0.065 and -0.002. A parabola and a
    kinked line fit a noisy nine-bar path about equally well. Its predecessor
    was worse - the difference of the correlations with the `V` and `U`
    templates - because **those two templates are 0.942 correlated** at this
    length, so their difference is a small residual of two nearly identical
    things.
    """
    lo = max(0, i - WIDTH_WIN)
    hi = min(len(close) - 1, i + WIDTH_WIN)
    path = close[lo:hi + 1].astype(float)
    if len(path) < 2 * WIDTH_WIN + 1 or path.std() <= 0:
        return float("nan")
    t = np.arange(len(path)) - (i - lo)
    z = (path - path.mean()) / path.std()
    tss = float(np.sum((z - z.mean()) ** 2))
    if tss <= 0:
        return float("nan")
    quad = np.polyfit(t, z, 2)
    r_quad = 1 - float(np.sum((z - np.polyval(quad, t)) ** 2)) / tss
    design = np.stack([np.ones_like(t, dtype=float), np.abs(t).astype(float)], 1)
    beta, *_ = np.linalg.lstsq(design, z, rcond=None)
    r_vee = 1 - float(np.sum((z - design @ beta) ** 2)) / tss
    return r_quad - r_vee


def label(width: int) -> str:
    if width <= ADAM_W:
        return "Adam"
    if width >= EVE_W:
        return "Eve"
    return "mid"


def double_bottoms(high, low, close, lookback, shapes: bool = False
                   ) -> pd.DataFrame:
    """Every double bottom, its Eve/Adam variant, and the bar it breaks on.

    The break-out is the first close above the intervening peak (an upward
    break, which is the pattern confirming) or below the lower bottom (the
    pattern failing), inside one pattern span of confirmation. The trade arm
    keeps the upward breaks; the downward ones are counted.
    """
    piv = zigzag(high, low, lookback)
    if len(piv) < 3:
        return pd.DataFrame()
    n = len(close)
    rows, dropped = [], 0
    for e in range(2, len(piv)):
        seg = piv[e - 2:e + 1]
        if not np.array_equal(seg[:, 1], [-1.0, 1.0, -1.0]):
            continue
        i0, i1, i2 = int(seg[0, 0]), int(seg[1, 0]), int(seg[2, 0])
        b0, peak, b1 = float(seg[0, 2]), float(seg[1, 2]), float(seg[2, 2])
        floor = min(b0, b1)
        height = peak - floor
        if height <= 0 or abs(b0 - b1) > TOL * height:
            continue
        confirm = i2 + lookback
        if confirm + 1 >= n:
            continue
        span = i2 - i0
        limit = min(n - 1, confirm + max(3, int(BREAK_SPAN * span)))
        idx = np.arange(confirm + 1, limit + 1)
        if len(idx) == 0:
            continue
        over = close[idx] > peak
        under = close[idx] < floor
        hit = np.flatnonzero(over | under)
        if len(hit) == 0:
            continue
        bar = int(idx[hit[0]])
        # The right bottom's window must close at or before the break-out, or
        # the label would read bars the trade has not seen.
        if i2 + WIDTH_WIN > bar:
            dropped += 1
            continue
        w0, d0 = classify(low, close, i0, b0, height)
        w1, d1 = classify(low, close, i2, b1, height)
        rows.append({
            "bar": bar, "side": 1 if over[hit[0]] else -1,
            "height": height, "span": span, "peak": peak,
            "w_left": w0, "w_right": w1, "d_left": d0, "d_right": d1,
            "r_left": roundedness(close, i0) if shapes else np.nan,
            "r_right": roundedness(close, i2) if shapes else np.nan,
            "left": label(w0), "right": label(w1),
            "variant": f"{label(w0)}-{label(w1)}"
            if "mid" not in (label(w0), label(w1)) else "unclassified",
            "i1": i1,
        })
    out = pd.DataFrame(rows)
    out.attrs["dropped_short_window"] = dropped
    return out


def race(close: np.ndarray, bar: np.ndarray, height: np.ndarray,
         target: float, stop: float) -> np.ndarray:
    """Long from the break-out close: target first (1), stop first (0), or
    neither inside `MAXFWD` bars (-1).

    When both barriers fall in the same bar the **stop** is taken, which is the
    conservative reading and the one a real fill gives more often than not.
    """
    n = len(close)
    live = bar + MAXFWD < n
    bar, height = bar[live], height[live]
    if len(bar) == 0:
        return np.empty(0)
    entry = close[bar]
    up = target * height
    dn = -stop * height
    out = np.full(len(bar), -1.0)
    for k in range(1, MAXFWD + 1):
        run = close[bar + k] - entry
        open_ = out < 0
        lost = open_ & (run <= dn)
        won = open_ & (run >= up) & ~lost
        out[lost] = 0.0
        out[won] = 1.0
    return out


def kappa(a: np.ndarray, b: np.ndarray) -> float:
    """Cohen's kappa for two binary labellings of the same bottoms."""
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok].astype(bool), b[ok].astype(bool)
    if len(a) < 20:
        return float("nan")
    agree = float((a == b).mean())
    pa = a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean())
    return float((agree - pa) / (1 - pa)) if pa < 1 else float("nan")


def summarise(got: pd.DataFrame, close, day, quoted: float, rng,
              name: str) -> dict | None:
    """One cell: the 2:1 race against 1/(1+N), the 1:1 control on the same
    events, and the cost in R for this geometry."""
    if len(got) == 0:
        return None
    bar = got.bar.to_numpy()
    height = got.height.to_numpy(float)
    live = bar + MAXFWD < len(close)
    res = race(close, bar, height, TARGET_H, STOP_H)
    ctrl = race(close, bar, height, 1.0, 1.0)
    done = res >= 0
    if done.sum() == 0:
        return None
    bars = bar[live][done]
    edge, lo, hi, p_fair = boot_mean(day[bars], res[done] - fair_rate(), rng)
    stop_px = STOP_H * height[live][done]
    cost_r = float(np.nanmedian(quoted * close[bars] / np.maximum(stop_px, 1e-12)))
    cdone = ctrl >= 0
    return {
        "cell": name, "n": len(got), "races": int(done.sum()),
        "hit": edge + fair_rate(), "hit_lo": lo + fair_rate(),
        "hit_hi": hi + fair_rate(), "fair": fair_rate(),
        "edge": edge, "p_vs_fair": p_fair,
        "unresolved": float((res < 0).mean()), "cost_r": cost_r,
        # Expectancy in R at this geometry: a win pays target/stop = 2R.
        "net_r": (edge + fair_rate()) * (TARGET_H / STOP_H)
                 - (1 - edge - fair_rate()) - cost_r,
        "race_1to1": float(ctrl[cdone].mean()) if cdone.any() else np.nan,
        "n_1to1": int(cdone.sum()),
        "w_left": float(got.w_left.mean()), "w_right": float(got.w_right.mean()),
        "d_left": float(got.d_left.mean()), "d_right": float(got.d_right.mean()),
    }


def one_symbol(job: tuple[str, int]) -> tuple[list[dict], list[dict]]:
    symbol, seat = job
    rng = np.random.default_rng([SEED, seat])
    started = time.time()
    raw = seqlab(symbol, BASE)
    if len(raw) < 20_000:
        raise SystemExit(f"{symbol}: {len(raw)} bars - refusing to write a cell")
    ts15 = raw.ts.to_numpy()
    high15, low15 = raw.high.to_numpy(float), raw.low.to_numpy(float)
    close15 = raw.close.to_numpy(float)
    r15 = np.diff(np.log(close15), prepend=0.0)
    up15, dn15 = wicks(high15, low15, close15)
    day15 = (ts15 // 86_400).astype(np.int64)
    quoted = float(np.nanmedian(
        SPREAD_POINTS.get(symbol, np.nan) * POINT.get(symbol, np.nan) / close15))
    stored = float(np.nanmedian(raw.spread.to_numpy(float)
                                * POINT.get(symbol, np.nan) / close15))

    series = [("real", 0, high15, low15, close15)]
    for draw in range(NSHUF):
        for arm in ("iid", "dayblock"):
            order = (order_iid(len(r15), rng) if arm == "iid"
                     else order_dayblock(day15, rng))
            series.append((arm, draw, *rebuild(r15, up15, dn15, order, close15[0])))

    rows: list[dict] = []
    seps: list[dict] = []
    for tf, seconds in TIMEFRAMES.items():
        _, inv = bins(ts15, seconds)
        built = {}
        for arm, draw, h, lo, c in series:
            built[(arm, draw)] = aggregate(inv, h, lo, c)
        edges = built[("real", 0)][3]
        tsb = ts15[edges]
        day = (tsb // 86_400).astype(np.int64)
        nbin = len(tsb)
        if nbin < 1_000:
            continue
        lens = {len(v[0]) for v in built.values()} | {len(tsb)}
        if lens != {nbin}:
            raise SystemExit(f"{symbol} {tf}: lengths {sorted(lens)} != {nbin}")
        for lookback in LOOKBACKS:
            real_cells: dict[str, dict] = {}
            nulls: dict[tuple[str, str], list[dict]] = {}
            for arm, draw, _, _, _ in series:
                hb, lb, cb, _ = built[(arm, draw)]
                got = double_bottoms(hb, lb, cb, lookback,
                                     shapes=(arm == "real"))
                if len(got) == 0:
                    continue
                if arm == "real":
                    seps.append({
                        "symbol": symbol, "tf": tf, "lookback": lookback,
                        "patterns": len(got),
                        "up_break": float((got.side > 0).mean()),
                        **separability(got),
                    })
                up = got[got.side > 0]
                cells = {"all": up}
                for name in (*VARIANTS, "unclassified"):
                    cells[name] = up[up.variant == name]
                for name, sub in cells.items():
                    out = summarise(sub, cb, day, quoted, rng, name)
                    if out is None:
                        continue
                    if arm == "real":
                        out |= {"symbol": symbol, "tf": tf, "lookback": lookback,
                                "quoted": quoted, "stored": stored, "bars": nbin,
                                "patterns": len(got),
                                "up_break": float((got.side > 0).mean())}
                        real_cells[name] = out
                    else:
                        nulls.setdefault((arm, name), []).append(out)
            for name, out in real_cells.items():
                for arm in ("iid", "dayblock"):
                    draws = nulls.get((arm, name), [])
                    for field in ("hit", "race_1to1", "races", "cost_r"):
                        col = np.array([d[field] for d in draws], float)
                        col = col[np.isfinite(col)]
                        out[f"{arm}_{field}"] = float(col.mean()) if len(col) else np.nan
                        if field in ("hit", "race_1to1"):
                            out[f"{arm}_{field}_sd"] = (float(col.std(ddof=1))
                                                        if len(col) > 1 else np.nan)
                            out[f"{arm}_{field}_p"] = rank_p(out[field], col)
                    out[f"{arm}_draws"] = len(draws)
                rows.append(out)
        print(f"  {symbol} {tf}: {nbin} bars, {len(rows)} cells so far",
              file=sys.stderr, flush=True)
    print(f"{symbol}: {len(raw)} base bars, {len(rows)} cells, "
          f"{time.time() - started:.0f}s", file=sys.stderr, flush=True)
    return rows, seps


def separability(got: pd.DataFrame) -> dict:
    """Are the four variants separable at all, or is the split noise?

    The label comes from the **width**; the **duration** is never used to
    label, so the agreement between them is a test of the classification
    rather than a restatement of it. Both bottoms of every pattern are pooled,
    because a bottom is a bottom. Reported three ways, two of them
    threshold-free:

    * Spearman correlation between width and duration over all bottoms;
    * Cohen's kappa between "narrow by width" and "below the median duration",
      on the bottoms the width decides;
    * the duration gap between the Adam and Eve classes, in standard
      deviations.

    `roundedness` is reported beside them and is **not** a criterion - see its
    docstring for the numbers that disqualified it.
    """
    w = np.concatenate([got.w_left.to_numpy(float), got.w_right.to_numpy(float)])
    d = np.concatenate([got.d_left.to_numpy(float), got.d_right.to_numpy(float)])
    r = np.concatenate([got.r_left.to_numpy(float), got.r_right.to_numpy(float)])
    narrow, wide = w <= ADAM_W, w >= EVE_W
    decided = narrow | wide
    rank_w = pd.Series(w).rank().to_numpy()
    rank_d = pd.Series(d).rank().to_numpy()
    spearman = (float(np.corrcoef(rank_w, rank_d)[0, 1])
                if w.std() > 0 and d.std() > 0 else np.nan)
    out = {
        "bottoms": len(w), "share_adam": float(narrow.mean()),
        "share_eve": float(wide.mean()), "share_mid": float((~decided).mean()),
        "w_mean": float(w.mean()), "w_sd": float(w.std(ddof=1)),
        "d_mean": float(d.mean()), "d_sd": float(d.std(ddof=1)),
        "spearman_w_d": spearman,
        "kappa": kappa(narrow[decided].astype(float),
                       (d[decided] <= np.median(d)).astype(float)),
        "d_adam": float(d[narrow].mean()) if narrow.any() else np.nan,
        "d_eve": float(d[wide].mean()) if wide.any() else np.nan,
        "kappa_roundedness": kappa(
            narrow[decided].astype(float),
            (r[decided] <= np.nanmedian(r)).astype(float))
        if np.isfinite(r).any() else np.nan,
    }
    out["d_gap_sd"] = ((out["d_eve"] - out["d_adam"]) / out["d_sd"]
                       if out["d_sd"] > 0 else np.nan)
    mix = got.variant.value_counts(normalize=True).to_dict()
    for name in (*VARIANTS, "unclassified"):
        out[f"mix_{name}"] = float(mix.get(name, 0.0))
    return out


PLANT = (0.0, 0.05, 0.10, 0.20, 0.40)


def one_power(job: tuple[str, int]) -> list[dict]:
    """A drift of known size in pattern heights, planted on the generated
    markets where the real answer is `1/(1+N)`, on a **disjoint** subset of
    break-outs so the plant stays local and does not compound."""
    symbol, seat = job
    rng = np.random.default_rng([SEED, 7_000 + seat])
    raw = seqlab(symbol, BASE)
    ts15 = raw.ts.to_numpy()
    _, inv = bins(ts15, TIMEFRAMES["1h"])
    high, low, close, edges = aggregate(inv, raw.high.to_numpy(float),
                                        raw.low.to_numpy(float),
                                        raw.close.to_numpy(float))
    nbin = len(close)
    day = (ts15[edges] // 86_400).astype(np.int64)
    rr = np.diff(np.log(close), prepend=np.nan)
    rows: list[dict] = []
    for lookback in LOOKBACKS:
        got = double_bottoms(high, low, close, lookback)
        if len(got) == 0:
            continue
        up = got[got.side > 0]
        for name in ("all", *VARIANTS):
            sub = up if name == "all" else up[up.variant == name]
            if len(sub) < 30:
                continue
            bar_all = sub.bar.to_numpy()
            keep, last = [], -10**9
            for pos, b in enumerate(np.sort(bar_all)):
                if b - last >= MAXFWD:
                    keep.append(pos)
                    last = b
            order = np.argsort(bar_all)
            bar = bar_all[order][keep]
            height = sub.height.to_numpy(float)[order][keep]
            bar = bar[bar + MAXFWD < nbin]
            height = height[:len(bar)]
            if len(bar) < 20:
                continue
            for size in PLANT:
                step = size * height / np.maximum(close[bar], 1e-12) / MAXFWD
                planted = np.nan_to_num(rr).copy()
                for off in range(1, MAXFWD + 1):
                    planted[bar + off] += step
                newc = np.exp(np.cumsum(planted) + np.log(close[0]))
                res = race(newc, bar, height, TARGET_H, STOP_H)
                done = res >= 0
                if done.sum() < 20:
                    continue
                m, lo, hi, p = boot_mean(day[bar][done],
                                         res[done] - fair_rate(), rng)
                rows.append({"symbol": symbol, "lookback": lookback, "cell": name,
                             "plant": size, "hit": m + fair_rate(), "lo": lo,
                             "hi": hi, "p": p, "n": int(done.sum()),
                             "disjoint": len(bar)})
    print(f"{symbol}: {len(rows)} power rows", file=sys.stderr, flush=True)
    return rows


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    print(f"part={PART} base={BASE} nshuf={NSHUF} fair={fair_rate():.4f}",
          file=sys.stderr)
    symbols = list(TRADED + SYNTH)
    if PART == "power":
        symbols = list(SYNTH)
    if PART == "pilot":
        symbols = ["EURUSD"]
    jobs = [(s, i) for i, s in enumerate(symbols)]
    with Pool(min(len(jobs), int(os.environ.get("WORKERS", "12")))) as pool:
        got = pool.map(one_power if PART == "power" else one_symbol, jobs)
    if PART == "power":
        rows = [r for part in got for r in part]
        if not rows:
            raise SystemExit("power: 0 rows - refusing to exit 0 on an empty run")
        pd.DataFrame(rows).to_csv(f"{OUT}/power.csv", index=False)
        print(f"power.csv: {len(rows)} rows", file=sys.stderr)
        return
    rows = [r for part in got for r in part[0]]
    seps = [r for part in got for r in part[1]]
    if not rows or not seps:
        raise SystemExit("0 rows - refusing to exit 0 on an empty run")
    frame = pd.DataFrame(rows)
    for arm in ("iid", "dayblock"):
        frame[f"bh_{arm}"] = bh(frame[f"{arm}_hit_p"].to_numpy())
    frame.to_csv(f"{OUT}/cells.csv", index=False)
    pd.DataFrame(seps).to_csv(f"{OUT}/separability.csv", index=False)
    print(f"cells.csv: {len(frame)} rows, separability.csv: {len(seps)} rows",
          file=sys.stderr)
    print({k: PROPERTY[k] for k in SYNTH if k in PROPERTY}, file=sys.stderr)
    print(f"cells under {MIN_EVENTS} races: "
          f"{int((frame.races < MIN_EVENTS).sum())} of {len(frame)}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
