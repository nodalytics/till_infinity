"""Train the frozen shock model production ships, from production's own features.

`shockreplay.py` showed that the features `structures/learning/shocks.py` computes carry the signal
(gradient boosting on them: AUC 0.73-0.76 on real markets, about 0.5 on memoryless synthetics). An
online logistic model or an online count table on the same features recovered only 0.60-0.69. So
production runs a frozen boosted model instead: trained here, exported as plain trees, and evaluated
in `shocks.py` with no dependency.

This harness:
  1. replays every family's bars through production `shocks.Shocks` (features exactly as live);
  2. labels each bar with whether a shock arrives in the next `AHEAD` bars of the same series;
  3. fits gradient boosting on the first 60% of the replay by time;
  4. scores the last 40% per family and interval (AUC, halves, top-decile lift) and checks
     calibration by decile;
  5. exports the trees to JSON and checks the pure-Python evaluator in `shocks.py` reproduces
     sklearn's probabilities to 1e-9.

Run on the lab:  OUT=$HOME/till_infinity/data/shock_model.json python research/harness/shocktrain.py
"""
from __future__ import annotations

import heapq
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from shockreplay import GROUPS, SECONDS, bars

from till_infinity.structures.learning import shocks as sh

OUT = Path(os.environ.get("OUT", ".data/shock_model.json"))


def replay():
    streams = []
    for iv in ("15m", "1h"):
        for fam, syms in GROUPS.items():
            for s in syms:
                try:
                    spikerisk.load(None, s, "SEQLAB", iv)
                except (ValueError, FileNotFoundError):
                    continue
                streams.append(bars(s, iv, fam))
    model = sh.Shocks()
    rows = []
    for when, sym, iv, fam, h, lo, c in heapq.merge(*streams):
        model.observe(sym, iv, SECONDS[iv], when, h, lo, c)
        s = model.series.get(f"{sym}|{iv}")
        if s is None or not s.shocks:
            continue
        rows.append((when, fam, iv, f"{sym}|{iv}", s.shocks[-1], list(s.latest) if s.latest else None))
    d = pd.DataFrame(rows, columns=["when", "family", "interval", "key", "shock", "x"])
    d["y"] = np.nan
    for key, g in d.groupby("key"):
        v = g["shock"].to_numpy()
        fut = np.zeros(len(v))
        for j in range(1, sh.AHEAD + 1):
            fut = np.maximum(fut, np.r_[v[j:], np.zeros(j)])
        fut[len(v) - sh.AHEAD:] = np.nan
        d.loc[g.index, "y"] = fut
    d = d.dropna(subset=["y"])
    return d[d["x"].notna()]


def export(model, names, base_rate, scores):
    trees = []
    for predictors in model._predictors:
        nodes = predictors[0].nodes
        trees.append([[int(n["feature_idx"]), float(n["num_threshold"]), int(n["left"]), int(n["right"]),
                       int(n["is_leaf"]), float(n["value"]), int(n["missing_go_to_left"])] for n in nodes])
    return {
        "recipe": sh.RECIPE,
        "names": list(names),
        "baseline": float(np.ravel(model._baseline_prediction)[0]),
        "trees": trees,
        "base_rate": round(float(base_rate), 6),
        "ahead": sh.AHEAD,
        "shock_multiple": sh.SHOCK_MULTIPLE,
        "trained": datetime.now(UTC).strftime("%Y-%m-%d"),
        "test": scores,
    }


def main():
    d = replay()
    X = np.array(d["x"].tolist())
    y = d["y"].to_numpy()
    cut = d["when"].quantile(0.6)
    tr, te = (d["when"] < cut).to_numpy(), (d["when"] >= cut).to_numpy()
    mid = d.loc[te, "when"].quantile(0.5)
    fit = np.random.default_rng(0).choice(np.flatnonzero(tr), min(800_000, tr.sum()), replace=False)
    gbm = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=300)
    gbm.fit(X[fit], y[fit])
    p = gbm.predict_proba(X)[:, 1]
    base = y[tr].mean()
    print(f"\n{'=' * 100}\nSHOCK MODEL - trained on {len(fit):,} bars before {pd.Timestamp(cut, unit='s'):%Y-%m-%d}, "
          f"base rate {base:.2%}; scored on {te.sum():,} after")
    scores = {}
    for (iv, fam), g in d[te].groupby(["interval", "family"]):
        pos = d.index.get_indexer(g.index)
        if g["y"].nunique() < 2:
            continue
        auc = roc_auc_score(g["y"], p[pos])
        h = [roc_auc_score(g["y"][m], p[pos][m]) for m in (g["when"] < mid, g["when"] >= mid)]
        top = p[pos] >= np.quantile(p[pos], 0.9)
        lift = g["y"][top].mean() / g["y"].mean()
        shown = np.mean(p[pos] / base >= sh.CARD_LIFT)
        scores[f"{iv} {fam}"] = round(auc, 3)
        print(f"  {iv:<4} {fam:<11} AUC {auc:.3f} (halves {h[0]:.3f}/{h[1]:.3f}) top decile {g['y'][top].mean():.1%} "
              f"({lift:.1f}x) | card would show risk on {shown:.1%} of bars")
    q = pd.qcut(p[te], 10, labels=False, duplicates="drop")
    print("  calibration, test deciles (predicted / realised):", " ".join(
        f"{p[te][q == k].mean():.3f}/{y[te][q == k].mean():.3f}" for k in np.unique(q)))
    model = export(gbm, sh.NAMES, base, scores)
    # the evaluator production will run must reproduce sklearn exactly
    ours = np.array([sh.Frozen(model).predict(list(row)) for row in X[te][:20_000]])
    diff = np.max(np.abs(ours - p[te][:20_000]))
    print(f"  exported {len(model['trees'])} trees; production evaluator max |diff| vs sklearn {diff:.2e}")
    assert diff < 1e-9, "the exported model does not reproduce sklearn"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(model, separators=(",", ":")))
    print(f"  wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
