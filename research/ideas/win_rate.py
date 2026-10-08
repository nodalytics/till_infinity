"""Which of the structures the desk already computes separates a winner from a loser?

Asked 2026-10-08: "looking at structures internally, how can we improve win rate
of our system". The desk journals an **outcome** entry per closed position
carrying `r_multiple` *and* the whole structures context that was live when it
opened - roughly 140 fields: `zma_*`, `origin_*`, `regression_*`,
`env5/20/50_*`, `barrier_*`, `sweep_*`, `wick_*`, `macro_*`. Nothing needs to be
built to answer this; it needs reading.

Two questions, in the order that matters:

1. **Are the desk's own probabilities calibrated?** `barrier_p`,
   `probability`, `probability_up`, `break_probability_calibrated`,
   `expansion_probability`, `shock_probability` and `edge` are predictions this
   system already makes. If one of them is calibrated, gating on it raises the
   win rate with no new model - and if it is not, that is a defect worth more
   than any new feature.
2. **Does any field separate winners from losers?** Split each at its median and
   compare the win rate above against below, with a day-block interval and
   Benjamini-Hochberg over every field tested - because testing 140 fields finds
   seven at p < 0.05 on noise alone.

The desk-wide win rate is 46.6% and the mechanical base rate for a symmetric
+-1 ATR barrier on this book is 48.6%, so the target is not "beat 50%"; it is
"find the two points this system is giving away".

  python research/ideas/win_rate.py .data/live/journal_full.csv
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

csv.field_size_limit(10 ** 7)
PROBS = ("barrier_p", "probability", "probability_up", "break_probability",
         "break_probability_calibrated", "expansion_probability", "shock_probability", "edge")
MIN_N = 120


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["kind"] != "outcome":
                continue
            try:
                d = json.loads(r["context"])
            except Exception:
                continue
            d["_t"] = float(r["time"])
            rows.append(d)
    d = pd.DataFrame(rows)
    d["day"] = (d["_t"] // 86400).astype(int)
    d = d[np.isfinite(pd.to_numeric(d.get("r_multiple"), errors="coerce"))]
    d["r"] = pd.to_numeric(d["r_multiple"], errors="coerce")
    d["win"] = (d["r"] > 0).astype(float)
    return d


def block_ci(v, days, draws=4000, seed=19):
    v = np.asarray(v, float)
    ok = np.isfinite(v)
    v, days = v[ok], np.asarray(days)[ok]
    if len(v) < 20:
        return (float(v.mean()) if len(v) else np.nan), np.nan, np.nan
    rng = np.random.default_rng(seed)
    u, inv = np.unique(days, return_inverse=True)
    s = np.bincount(inv, weights=v, minlength=len(u))
    c = np.bincount(inv, minlength=len(u)).astype(float)
    p = rng.integers(0, len(u), size=(draws, len(u)))
    got = s[p].sum(1) / np.maximum(c[p].sum(1), 1)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def bh(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    q = np.empty(m)
    q[o] = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    return np.minimum(q, 1.0)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else ".data/live/journal_full.csv"
    d = load(path)
    print(f"{len(d)} closed positions with an R, "
          f"{d['_t'].min():.0f}-{d['_t'].max():.0f}, {d['day'].nunique()} days")
    print(f"win rate {d.win.mean():.1%}   mean R {d.r.mean():+.3f}   "
          f"median R {d.r.median():+.3f}\n")

    print("=== 1. the desk's own probabilities, against what happened ===")
    print("    (a calibrated p should have win rate ~ p in each bucket)")
    for name in PROBS:
        if name not in d:
            continue
        v = pd.to_numeric(d[name], errors="coerce")
        g = d[np.isfinite(v)].assign(p=v[np.isfinite(v)])
        if len(g) < MIN_N:
            print(f"  {name:<32} only {len(g)} rows")
            continue
        corr = float(pd.Series(g.p).corr(pd.Series(g.win), method="spearman"))
        qs = np.quantile(g.p, [0, 1 / 3, 2 / 3, 1.0])
        parts = []
        for lo, hi in zip(qs[:-1], qs[1:]):
            sub = g[(g.p >= lo) & (g.p <= hi)]
            if len(sub) < 20:
                continue
            parts.append(f"p~{sub.p.mean():.2f}->{sub.win.mean():.0%} (n={len(sub)})")
        print(f"  {name:<32} n={len(g):>5}  IC {corr:+.3f}   " + "  ".join(parts))

    print("\n=== 2. every field, above its median against below ===")
    rows = []
    for name in d.columns:
        if name in ("r", "win", "day", "_t", "r_multiple", "profit", "exit", "best_r",
                    "adverse_r", "best_after", "worst_after"):
            continue
        v = pd.to_numeric(d[name], errors="coerce")
        g = d[np.isfinite(v)].assign(v=v[np.isfinite(v)])
        if len(g) < MIN_N or g.v.nunique() < 4:
            continue
        cut = g.v.median()
        hi, lo = g[g.v > cut], g[g.v <= cut]
        if min(len(hi), len(lo)) < 40:
            continue
        mh, lh, hh = block_ci(hi.win, hi.day)
        ml, _, _ = block_ci(lo.win, lo.day)
        # a permutation of the field within day: keeps the day's outcomes, breaks the pairing
        rng = np.random.default_rng(5)
        null = []
        for _ in range(400):
            s = g.copy()
            s["v"] = s.groupby("day")["v"].transform(lambda x: rng.permutation(x.to_numpy()))
            c2 = s.v.median()
            null.append(s[s.v > c2].win.mean() - s[s.v <= c2].win.mean())
        null = np.asarray(null)
        want = mh - ml
        p = float((np.abs(null) >= abs(want)).mean())
        rows.append(dict(field=name, n=len(g), above=mh, below=ml, gap=want,
                         lo=lh, hi=hh, p=p))
    t = pd.DataFrame(rows)
    if t.empty:
        print("  nothing with enough coverage")
        return
    t["q"] = bh(t.p.to_numpy())
    t = t.sort_values("p")
    pd.set_option("display.width", 200)
    print(t.head(25).round(4).to_string(index=False))
    print(f"\n{len(t)} fields tested. Surviving BH at q < 0.10:")
    got = t[t.q < 0.10]
    print(got.round(4).to_string(index=False) if len(got) else "  nothing")


if __name__ == "__main__":
    main()
