"""Does production's shock forecaster (`structures/learning/shocks.py`) keep what `anomalies.py` found?

`anomalies.md` measured shocks as predictable at AUC 0.76-0.79 with an offline gradient-boosted model
and a split in time. Production runs something simpler: one online logistic model across the book,
predicting before it learns. This replays that class exactly - every family's bars interleaved in
time, as the engine would see them - and scores each bar's published probability against whether a
shock actually arrived in the next `AHEAD` bars. Real markets should keep most of the offline AUC;
the memoryless synthetics must read about 0.5 even though they share the pooled model.

Reported on the last 40% of the replay by time, and both halves of that.
"""
from __future__ import annotations

import heapq
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import FAMILIES

from till_infinity.structures.learning import shocks as sh

GROUPS = {
    "fx": FAMILIES["fx"], "metals": FAMILIES["metal"], "crypto": FAMILIES["crypto"],
    "boom/crash": ["Boom_500_Index", "Boom_1000_Index", "Crash_500_Index", "Crash_1000_Index"],
    "jump": ["Jump_10_Index", "Jump_50_Index", "Jump_100_Index"],
    "volatility": ["Volatility_25_Index", "Volatility_75_Index", "Volatility_100_Index"],
}
SECONDS = {"15m": 900, "1h": 3600}


def bars(sym, interval, family):
    df = spikerisk.load(None, sym, "SEQLAB", interval)
    for t, h, lo, c in zip(df["ts"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()):
        yield (int(t) + SECONDS[interval], sym, interval, family, float(h), float(lo), float(c))


def main():
    intervals = os.environ.get("INTERVALS", "15m,1h").split(",")
    streams = []
    for iv in intervals:
        for fam, syms in GROUPS.items():
            for s in syms:
                try:
                    spikerisk.load(None, s, "SEQLAB", iv)
                except (ValueError, FileNotFoundError):
                    continue
                streams.append(bars(s, iv, fam))
    model = sh.Shocks()
    rows = []  # (when, family, key, p or nan, shock flag)
    for when, sym, iv, fam, h, lo, c in heapq.merge(*streams):
        model.observe(sym, iv, SECONDS[iv], when, h, lo, c)
        key = f"{sym}|{iv}"
        s = model.series.get(key)
        if s is None or not s.shocks:
            continue
        got = model.reading(sym, iv)
        rows.append((when, fam, iv, key, got.get("shock_probability", np.nan), s.shocks[-1],
                     list(s.latest) if s.latest else None))
    d = pd.DataFrame(rows, columns=["when", "family", "interval", "key", "p", "shock", "x"])
    # the label: a shock in the next AHEAD bars of the same series
    d["y"] = 0.0
    for key, g in d.groupby("key"):
        v = g["shock"].to_numpy()
        fut = np.zeros(len(v))
        for j in range(1, sh.AHEAD + 1):
            fut = np.maximum(fut, np.r_[v[j:], np.zeros(j)])
        fut[len(v) - sh.AHEAD:] = np.nan
        d.loc[g.index, "y"] = fut
    # the series' own recent shock rate (causal), a per-series intercept the pooled model lacks
    d["own_rate"] = d.groupby("key")["shock"].transform(lambda v: v.shift(1).rolling(500, min_periods=100).mean())
    d = d.dropna(subset=["p", "y"])
    cut = d["when"].quantile(0.6)
    mid = d.loc[d["when"] >= cut, "when"].quantile(0.5)
    te = d[d["when"] >= cut]
    print(f"\n{'=' * 100}\nSHOCK REPLAY - production shocks.Shocks, one pooled online model, {', '.join(intervals)}; "
          f"{len(d):,} scored bars, test = last 40% by time")
    print(f"  model: seen {model.model.seen:.0f} (decayed), running base rate {model.base_rate():.2%}")
    for (iv, fam), g in te.groupby(["interval", "family"]):
        if g["y"].nunique() < 2:
            continue
        auc = roc_auc_score(g["y"], g["p"])
        h = [roc_auc_score(x["y"], x["p"]) if x["y"].nunique() > 1 else np.nan
             for x in (g[g["when"] < mid], g[g["when"] >= mid])]
        top = g["p"] >= g["p"].quantile(0.9)
        lifted = (g["p"] / model.base_rate() >= sh.CARD_LIFT).mean()
        print(f"  {iv:<4} {fam:<11} n={len(g):>8,} shock-ahead rate {g['y'].mean():.2%} | AUC {auc:.3f} (halves {h[0]:.3f}/{h[1]:.3f}) "
              f"| top decile {g.loc[top, 'y'].mean():.1%} ({g.loc[top, 'y'].mean() / g['y'].mean():.1f}x) | "
              f"card would show risk on {lifted:.1%} of bars")
    diagnose(d, cut)


def diagnose(d, cut):
    """Same features, fit offline on the first 60%: is the gap the online learner, the pooling, or the
    features? Logistic and gradient boosting, with and without each series' own recent shock rate."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    d = d[d["x"].notna() & d["own_rate"].notna()]
    X = np.array(d["x"].tolist())
    Xo = np.column_stack([X, np.log(d["own_rate"].to_numpy() + 1e-4)])
    y = d["y"].to_numpy()
    tr, te = (d["when"] < cut).to_numpy(), (d["when"] >= cut).to_numpy()
    rng = np.random.default_rng(0)
    fit = rng.choice(np.flatnonzero(tr), min(600_000, tr.sum()), replace=False)
    fits = {
        "logistic": LogisticRegression(max_iter=500).fit(X[fit], y[fit]).predict_proba(X)[:, 1],
        "logistic + own rate": LogisticRegression(max_iter=500).fit(Xo[fit], y[fit]).predict_proba(Xo)[:, 1],
        "gbm": HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=300)
        .fit(X[fit], y[fit]).predict_proba(X)[:, 1],
        "gbm + own rate": HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=300)
        .fit(Xo[fit], y[fit]).predict_proba(Xo)[:, 1],
    }
    # An online count table: a cell per (volatility rank decile, volatility-vs-norm band, recent
    # shocks), its hit rate shrunk toward the running base rate, each outcome counted only once its
    # window has closed - exactly what production could run with no training.
    import collections
    order = np.argsort(d["when"].to_numpy(), kind="stable")
    when = d["when"].to_numpy()[order]
    secs = np.where(d["interval"].to_numpy()[order] == "1h", 3600, 900)
    xs = X[order]
    ys = y[order]
    rank_cell = np.minimum((xs[:, 2] * 10).astype(int), 9)
    norm_cell = np.digitize(xs[:, 0], [-0.5, -0.2, 0.0, 0.2, 0.5])
    shock_cell = np.digitize(xs[:, 6] * 100, [0.5, 1.5, 3.5])
    cells = rank_cell * 100 + norm_cell * 10 + shock_cell
    hits, seen = collections.defaultdict(float), collections.defaultdict(float)
    tot_h, tot_n = 0.0, 0.0
    queue = collections.deque()
    table = np.empty(len(ys))
    for i in range(len(ys)):
        while queue and queue[0][0] <= when[i]:
            _, c, lab = queue.popleft()
            hits[c] += lab
            seen[c] += 1
            tot_h += lab
            tot_n += 1
        base = tot_h / tot_n if tot_n else 0.05
        c = cells[i]
        table[i] = (hits[c] + 20 * base) / (seen[c] + 20)
        queue.append((when[i] + 4 * secs[i], c, ys[i]))
    fits["online table"] = np.empty(len(ys))
    fits["online table"][order] = table
    print("\n  DIAGNOSIS - the same features fit offline on the first 60%, test AUC")
    for (iv, fam), g in d[te].groupby(["interval", "family"]):
        if g["y"].nunique() < 2:
            continue
        idx = g.index
        pos = d.index.get_indexer(idx)
        cells = [f"online {roc_auc_score(g['y'], g['p']):.3f}"] + [f"{k} {roc_auc_score(g['y'], v[pos]):.3f}" for k, v in fits.items()]
        print(f"  {iv:<4} {fam:<11} " + " | ".join(cells))


if __name__ == "__main__":
    main()
