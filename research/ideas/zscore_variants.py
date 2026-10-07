"""Four variants of the z-score, each answering something the level cannot.

Asked 2026-10-07, after `zscore-window.md` established that the level's reach is
decided by its window:

1. **Ceiling-normalised** - `z / ((N-1)/sqrt(N))`, the share of the attainable
   maximum. A threshold on the raw z is a different event at every window (0.57%
   of bars at N = 6, 12.7% at N = 36); the question is whether normalising makes
   it the same event, and whether the result survives.
2. **Term structure** - `zn_fast - zn_slow` at the **same bar**. A 4-bar z of 1.4
   inside a 36-bar z of 0.1 is a spike in a range; the same 1.4 inside a 36-bar z
   of 2.5 is a trend extending. The level cannot tell them apart.
3. **Volatility z**, not price - the same statistic on the bar's range. The
   target here is **not direction**: it is the forward realised range over the
   current ATR, because the desk's loss has been traced four ways to stops inside
   the instrument's own noise, and that is a sizing question.
4. **Cross-sectional z** - each instrument standardised against the others at the
   same timestamp rather than against its own past.

Day-block intervals throughout; the cross-sectional null shuffles instrument
labels within a timestamp, which keeps each bar's own move and destroys only
which instrument it belonged to.

  MT5BT_DB=... SYMBOLS=... IV=4h python research/ideas/zscore_variants.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

import prims as P  # noqa: E402

ZW = (4, 6, 8, 12, 20, 36)
PAIRS = ((4, 36), (6, 20), (8, 36))
HORIZONS = (3, 6)
IV = os.environ.get("IV", "4h")
OUT = Path(os.environ.get("OUT", ".data/zvar"))


def ceiling(n: int) -> float:
    return (n - 1) / np.sqrt(n)


def roll_z(x: np.ndarray, n: int) -> np.ndarray:
    s = pd.Series(x)
    sd = s.rolling(n).std(ddof=1)
    return ((s - s.rolling(n).mean()) / sd.replace(0.0, np.nan)).to_numpy()


def one(sym):
    import run as R
    import survivors
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, IV)
    if df is None:
        return None
    df = df.reset_index(drop=True)
    o, h_, l_, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = P.atr(df, 14)
    rng = np.maximum(h_ - l_, 1e-12)
    out = {"sym": sym, "ts": df["ts"].to_numpy()}
    for n in ZW:
        out[f"zn{n}"] = roll_z(c, n) / ceiling(n)
        # (3) the same statistic on the bar's range, in logs so it is symmetric
        out[f"v{n}"] = roll_z(np.log(rng), n) / ceiling(n)
    for f, s_ in PAIRS:
        out[f"ts{f}_{s_}"] = out[f"zn{f}"] - out[f"zn{s_}"]
    with np.errstate(invalid="ignore", divide="ignore"):
        for h in HORIZONS:
            fwd = np.full(len(c), np.nan)
            fwd[:-h] = c[h:] - c[:-h]
            out[f"y{h}"] = np.where(a > 0, fwd / a, np.nan)
            # forward realised range over the ATR now: the sizing target
            fr = np.full(len(c), np.nan)
            for k in range(len(c) - h):
                fr[k] = h_[k + 1:k + 1 + h].max() - l_[k + 1:k + 1 + h].min()
            out[f"r{h}"] = np.where(a > 0, fr / a, np.nan)
        out["ret"] = np.r_[np.nan, np.diff(np.log(c))]
    return pd.DataFrame(out)


def block_ci(v, days, draws=1500, seed=41):
    v = np.asarray(v, float)
    ok = np.isfinite(v)
    v, days = v[ok], np.asarray(days)[ok]
    if len(v) < 50:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(days, return_inverse=True)
    sums = np.bincount(inv, weights=v, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    pick = rng.integers(0, len(uniq), size=(draws, len(uniq)))
    got = sums[pick].sum(axis=1) / np.maximum(cnts[pick].sum(axis=1), 1.0)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def tails(d, col, tgt, cut):
    hi = d[d[col] >= cut]
    lo = d[d[col] <= -cut]
    m_h, l_h, h_h = block_ci(hi[tgt], hi["day"])
    m_l, l_l, h_l = block_ci(lo[tgt], lo["day"])
    return len(hi), len(lo), m_h, l_h, h_h, m_l, l_l, h_l


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        parts = [p for p in pool.map(one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    d["day"] = (d["ts"] // 86400).astype(int)
    pd.set_option("display.width", 230)
    pd.set_option("display.max_rows", 300)
    print(f"{len(d):,} {IV} bars, {d['sym'].nunique()} instruments\n")

    # ---------------------------------------------------------------- 1
    print("=== 1. ceiling-normalised z: is a threshold now the same event? ===")
    print("    share of bars past each fraction of the attainable maximum")
    rows = []
    for n in ZW:
        z = d[f"zn{n}"].dropna()
        rows.append({"N": n, **{f">{t:g}": float((z.abs() >= t).mean()) for t in (0.4, 0.6, 0.8, 0.9)}})
    print(pd.DataFrame(rows).set_index("N").round(4).to_string())
    print("\n    forward move at h = 3, in ATR, by normalised threshold")
    rows = []
    for n in ZW:
        g = d[np.isfinite(d[f"zn{n}"]) & np.isfinite(d["y3"])]
        for t in (0.4, 0.6, 0.8):
            nh, nl, mh, lh, hh, ml, ll, hl = tails(g, f"zn{n}", "y3", t)
            rows.append(dict(N=n, cut=t, n_hi=nh, hi=mh, hi_lo=lh, hi_hi=hh,
                             n_lo=nl, lo=ml, lo_lo=ll, lo_hi=hl, spread=mh - ml))
    v1 = pd.DataFrame(rows)
    print(v1.round(3).to_string(index=False))

    # ---------------------------------------------------------------- 2
    print("\n=== 2. term structure: the same fast reading, inside different slow ones ===")
    rows = []
    for f, s_ in PAIRS:
        col = f"ts{f}_{s_}"
        g = d[np.isfinite(d[col]) & np.isfinite(d[f"zn{f}"]) & np.isfinite(d["y3"])].copy()
        g["fast"] = np.where(g[f"zn{f}"] >= 0.5, "fast high",
                             np.where(g[f"zn{f}"] <= -0.5, "fast low", "fast mid"))
        g["slow"] = np.where(g[f"zn{s_}"] >= 0.4, "slow high",
                             np.where(g[f"zn{s_}"] <= -0.4, "slow low", "slow mid"))
        for a_ in ("fast high", "fast mid", "fast low"):
            for b_ in ("slow high", "slow mid", "slow low"):
                sub = g[(g["fast"] == a_) & (g["slow"] == b_)]
                m_, l_, h_ = block_ci(sub["y3"], sub["day"])
                rows.append(dict(pair=f"{f}/{s_}", fast=a_, slow=b_, n=len(sub),
                                 fwd=m_, lo=l_, hi=h_))
    v2 = pd.DataFrame(rows)
    for p_ in v2["pair"].unique():
        print(f"\n  pair {p_} - forward move at h = 3, in ATR")
        cut = v2[v2["pair"] == p_]
        print(cut.pivot(index="fast", columns="slow", values="fwd").round(3).to_string())
        print("  counts")
        print(cut.pivot(index="fast", columns="slow", values="n").astype(int).to_string())

    # ---------------------------------------------------------------- 3
    print("\n=== 3. volatility z: does it predict the forward range? ===")
    print("    (target is the next 3 bars' range over the ATR now - a sizing number,")
    print("     not a direction. 'flat' would mean the ATR already knows everything.)")
    rows = []
    for n in ZW:
        g = d[np.isfinite(d[f"v{n}"]) & np.isfinite(d["r3"])]
        ic = float(pd.Series(g[f"v{n}"].to_numpy()).corr(pd.Series(g["r3"].to_numpy()), method="spearman"))
        q = np.nanquantile(g[f"v{n}"], [0.2, 0.8])
        hi, lo = g[g[f"v{n}"] >= q[1]], g[g[f"v{n}"] <= q[0]]
        m_h, l_h, h_h = block_ci(hi["r3"], hi["day"])
        m_l, l_l, h_l = block_ci(lo["r3"], lo["day"])
        # and whether it says anything about direction, which it should not
        icd = float(pd.Series(g[f"v{n}"].to_numpy()).corr(
            pd.Series(np.abs(g["y3"].to_numpy())), method="spearman"))
        rows.append(dict(N=n, ic_range=ic, ic_absmove=icd, top=m_h, top_lo=l_h, top_hi=h_h,
                         bottom=m_l, bottom_lo=l_l, bottom_hi=h_l, ratio=m_h / m_l if m_l else np.nan))
    v3 = pd.DataFrame(rows)
    print(v3.round(3).to_string(index=False))

    # ---------------------------------------------------------------- 4
    print("\n=== 4. cross-sectional z: each instrument against the others, same bar ===")
    rows = []
    for n in (1, 4, 12):
        piv = d.pivot_table(index="ts", columns="sym", values="ret", aggfunc="first")
        roll = piv.rolling(n).sum() if n > 1 else piv
        x = roll.sub(roll.mean(axis=1), axis=0).div(roll.std(axis=1).replace(0, np.nan), axis=0)
        cs = x.stack().rename("cs").reset_index()
        g = cs.merge(d[["ts", "sym", "y3", "day"]], on=["ts", "sym"], how="inner")
        g = g[np.isfinite(g["cs"]) & np.isfinite(g["y3"])]
        ic = float(g["cs"].corr(g["y3"], method="spearman"))
        q = np.nanquantile(g["cs"], [0.1, 0.9])
        hi, lo = g[g["cs"] >= q[1]], g[g["cs"] <= q[0]]
        m_h, l_h, h_h = block_ci(hi["y3"], hi["day"])
        m_l, l_l, h_l = block_ci(lo["y3"], lo["day"])
        # null: shuffle which instrument a reading belongs to, within the bar
        rng = np.random.default_rng(9)
        sh = x.copy()
        vals = sh.to_numpy()
        for i in range(len(vals)):
            row = vals[i]
            ok = np.isfinite(row)
            if ok.sum() > 2:
                row[ok] = rng.permutation(row[ok])
        cs2 = pd.DataFrame(vals, index=x.index, columns=x.columns).stack().rename("cs").reset_index()
        g2 = cs2.merge(d[["ts", "sym", "y3"]], on=["ts", "sym"], how="inner")
        g2 = g2[np.isfinite(g2["cs"]) & np.isfinite(g2["y3"])]
        ic2 = float(g2["cs"].corr(g2["y3"], method="spearman"))
        rows.append(dict(lookback=n, n=len(g), ic=ic, ic_shuffled=ic2,
                         top=m_h, top_lo=l_h, top_hi=h_h, bottom=m_l, bottom_lo=l_l,
                         bottom_hi=h_l, spread=m_h - m_l))
    v4 = pd.DataFrame(rows)
    print(v4.round(4).to_string(index=False))

    OUT.mkdir(parents=True, exist_ok=True)
    for name, t in (("norm", v1), ("term", v2), ("vol", v3), ("cross", v4)):
        t.to_csv(OUT / f"{name}.csv", index=False)
    print(f"\nwritten: {OUT}")


if __name__ == "__main__":
    main()
