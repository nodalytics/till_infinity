"""The rolling z-score of the close on 4h bars, at every lookback from 2 to 36.

Asked for 2026-10-07. One question - does an extreme z-score mean the move
continues or reverses - asked at every window from 2 to 36, because the window is the
whole parameter and a result that only exists at one value of it is a result
about this sample.

    z[t] = (close[t] - mean(close[t-N+1 .. t])) / std(close[t-N+1 .. t])

The current bar is **inside** its own window, which is what every charting
package computes and what a reader is looking at. Nothing after `t` is used, so
there is no look-ahead; the forward return is measured from `t`'s close.

Outcome: the return from `t` to `t+h`, divided by the ATR at `t`, so instruments
and eras are comparable. Reported per (N, h):

  ic        Spearman correlation of z with the forward return
  spread    top z-decile's mean forward move minus the bottom's, in ATR
  p         against a shuffle of z **within symbol** - a permutation across the
            whole sample would destroy the instrument as well as the pairing and
            report the difference between instruments as a property of z
  q         Benjamini-Hochberg over the whole (N, h) grid

Also reported, because it decides what any threshold on z can mean: the largest
|z| a window of N points can produce at all.

  MT5BT_DB=... SYMBOLS=... IV=4h python research/ideas/zscore_window.py
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

WINDOWS = range(2, 37)
HORIZONS = (1, 3, 6, 12)
#: Thresholds asked for alongside the windows. They interact with the window in a
#: way that decides the answer before any data is seen - see `max |z|` below.
THRESHOLDS = (1.0, 2.0, 3.0, 4.0)
IV = os.environ.get("IV", "4h")
OUT = Path(os.environ.get("OUT", ".data/zwin"))


def zscores(c: np.ndarray, n: int) -> np.ndarray:
    """The rolling z-score, the current bar inside its own window."""
    s = pd.Series(c)
    m = s.rolling(n).mean()
    sd = s.rolling(n).std(ddof=1)
    return ((s - m) / sd.replace(0.0, np.nan)).to_numpy()


def one(job):
    import run as R
    import survivors
    sym = job
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, IV)
    if df is None:
        return None
    df = df.reset_index(drop=True)
    c = df["close"].to_numpy()
    a = P.atr(df, 14)
    o, hi_, lo_ = (df[k].to_numpy() for k in ("open", "high", "low"))
    rng = np.maximum(hi_ - lo_, 1e-12)
    out = {"sym": sym, "day": (df["ts"].to_numpy() // 86400).astype(int),
           # **The bar's own character**, asked for alongside the thresholds.
           # `body70` is the rule's own impulsive candle - `PUSH_BODY` of its
           # range - and `disp` is the `displace` trigger's definition, a body of
           # a whole ATR. They are different claims: a 70% body can be a small
           # candle, and a 1-ATR body can be 50% body on a huge range.
           "body": np.abs(c - o) / rng,
           "body70": (np.abs(c - o) / rng) >= 0.70,
           "disp": np.where(a > 0, np.abs(c - o) >= a, False),
           "up": c >= o}
    for n in WINDOWS:
        out[f"z{n}"] = zscores(c, n)
    for h in HORIZONS:
        fwd = np.full(len(c), np.nan)
        fwd[:-h] = (c[h:] - c[:-h])
        with np.errstate(invalid="ignore", divide="ignore"):
            out[f"f{h}"] = np.where(a > 0, fwd / a, np.nan)
    return pd.DataFrame(out)


def decile_spread(z, f):
    q = np.nanquantile(z, [0.1, 0.9])
    lo, hi = f[z <= q[0]], f[z >= q[1]]
    if len(lo) < 50 or len(hi) < 50:
        return np.nan
    return float(np.nanmean(hi) - np.nanmean(lo))


def block_ci(v, days, draws=2000, seed=17):
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


def shuffled_p(d: pd.DataFrame, zc: str, fc: str, draws=400, seed=5) -> float:
    """P(a within-symbol shuffle of z reaches this |spread|)."""
    want = decile_spread(d[zc].to_numpy(), d[fc].to_numpy())
    if not np.isfinite(want):
        return np.nan
    rng = np.random.default_rng(seed)
    idx = [np.flatnonzero(d["sym"].to_numpy() == s) for s in d["sym"].unique()]
    z, f = d[zc].to_numpy(), d[fc].to_numpy()
    hits = 0
    for _ in range(draws):
        y = z.copy()
        for w in idx:
            y[w] = rng.permutation(z[w])
        got = decile_spread(y, f)
        hits += np.isfinite(got) and abs(got) >= abs(want)
    return hits / draws


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        parts = [p for p in pool.map(one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    print(f"{len(d):,} {IV} bars over {d['sym'].nunique()} instruments\n")

    OUT.mkdir(parents=True, exist_ok=True)
    print("=== how far a z-score can reach at all ===")
    print("  N   max |z| seen   (N-1)/sqrt(N)   share |z| > 2")
    for n in WINDOWS:
        z = d[f"z{n}"].to_numpy()
        z = z[np.isfinite(z)]
        print(f"  {n:>2}      {np.abs(z).max():>6.3f}          {(n - 1) / np.sqrt(n):>6.3f}"
              f"         {np.mean(np.abs(z) > 2):>7.4%}")

    cohorts = {
        "all": np.ones(len(d), bool),
        "body>=70%": d["body70"].to_numpy(),
        "disp (1 ATR body)": d["disp"].to_numpy(),
        "both": d["body70"].to_numpy() & d["disp"].to_numpy(),
    }
    print("\n=== how common each cohort is ===")
    for k, m_ in cohorts.items():
        print(f"  {k:<20} {m_.sum():>8,}  {m_.mean():>7.2%}")

    tr = []
    for coh, mask in cohorts.items():
        dc = d[mask]
        for n in WINDOWS:
            for t_ in THRESHOLDS:
                for h in HORIZONS:
                    zc, fc = f"z{n}", f"f{h}"
                    g = dc[np.isfinite(dc[zc]) & np.isfinite(dc[fc])]
                    for sign in (1, -1):
                        sub = g[g[zc] * sign >= t_]
                        m_, l_, h_ = block_ci(sub[fc], sub["day"]) if len(sub) else (np.nan,) * 3
                        tr.append(dict(cohort=coh, N=n, z=f"{'+' if sign > 0 else '-'}{t_:g}",
                                       h=h, n=len(sub), share=len(sub) / max(len(g), 1),
                                       fwd=m_, lo=l_, hi=h_))
    th = pd.DataFrame(tr)
    print("\n=== the bar's own character, at |z| >= 2, h = 3 ===")
    cut = th[(th["h"] == 3) & (th["z"].isin(["+2", "-2"]))]
    print(cut.pivot_table(index="N", columns=["cohort", "z"], values="fwd").round(3).to_string())
    print("\n  counts")
    print(cut.pivot_table(index="N", columns=["cohort", "z"], values="n").fillna(0).astype(int).to_string())
    print("\n=== and at |z| >= 1, h = 3 ===")
    cut1 = th[(th["h"] == 3) & (th["z"].isin(["+1", "-1"]))]
    print(cut1.pivot_table(index="N", columns=["cohort", "z"], values="fwd").round(3).to_string())
    print("\n=== after a reading past the threshold (all bars): mean forward move, in ATR ===")
    print("(blank = the window cannot produce that reading at all)")
    allb = th[th["cohort"] == "all"]
    for h in HORIZONS:
        piv = allb[allb["h"] == h].pivot(index="N", columns="z", values="fwd")
        cnt = allb[allb["h"] == h].pivot(index="N", columns="z", values="n")
        print(f"\nh = {h} bars - mean forward move")
        print(piv.round(3).to_string())
        print(f"h = {h} bars - how many bars qualified")
        print(cnt.astype(int).to_string())
    th.to_csv(OUT / "zthresh.csv", index=False) if OUT.exists() else None

    rows = []
    for n in WINDOWS:
        for h in HORIZONS:
            zc, fc = f"z{n}", f"f{h}"
            g = d[np.isfinite(d[zc]) & np.isfinite(d[fc])]
            if len(g) < 500:
                continue
            ic = float(pd.Series(g[zc].to_numpy()).corr(pd.Series(g[fc].to_numpy()), method="spearman"))
            q = np.nanquantile(g[zc], [0.1, 0.9])
            hi = g[g[zc] >= q[1]]
            lo = g[g[zc] <= q[0]]
            m_hi, l_hi, h_hi = block_ci(hi[fc], hi["day"])
            m_lo, l_lo, h_lo = block_ci(lo[fc], lo["day"])
            rows.append(dict(N=n, h=h, n=len(g), ic=ic, top=m_hi, top_lo=l_hi, top_hi=h_hi,
                             bottom=m_lo, bottom_lo=l_lo, bottom_hi=h_lo,
                             spread=m_hi - m_lo, p=shuffled_p(g, zc, fc)))
    t = pd.DataFrame(rows)
    pv = t["p"].fillna(1.0).to_numpy()
    order = np.argsort(pv)
    m = len(pv)
    qv = np.empty(m)
    qv[order] = np.minimum.accumulate((pv[order] * m / np.arange(1, m + 1))[::-1])[::-1]
    t["q"] = np.minimum(qv, 1.0)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 200)
    print("\n=== z against the forward move, in ATR ===")
    print(t.round(4).to_string(index=False))
    print("\n=== spread by window and horizon (positive = continuation) ===")
    print(t.pivot(index="N", columns="h", values="spread").round(3).to_string())
    print("\n=== Spearman IC ===")
    print(t.pivot(index="N", columns="h", values="ic").round(4).to_string())
    print("\nsurviving BH at q < 0.10:")
    got = t[t["q"] < 0.10]
    print(got.round(4).to_string(index=False) if len(got) else "  nothing")
    OUT.mkdir(parents=True, exist_ok=True)
    th.to_csv(OUT / "zthresh.csv", index=False)
    t.to_csv(OUT / "zwin.csv", index=False)
    print(f"\nwritten: {OUT / 'zwin.csv'}")


if __name__ == "__main__":
    main()
