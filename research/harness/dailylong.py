"""Stress-testing the one directional lead: the daily long model.

`horizons.py` found a gradient-boosted long model on daily bars beating plain
buy-and-hold at 1, 5 and 20 days, in both halves of its test period and in every
family. Four ways that could be something else:

  1  it is "buy when volatility is high" (or "buy the dip") with extra steps -
     compared head to head with those rules, on identical entries
  2  it is the 2014-2026 bull market - split by whether the series was above its
     own 200-day average at entry, and by calendar year
  3  it is one lucky split - re-fit every year on everything before it and
     scored on the next year only (rolling origin, 2012 onwards)
  4  it does not survive costs - net of the spread assumption in questions.py

Run from the repository root:  .venv-research/bin/python research/harness/dailylong.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).parent))
from horizons import build
from spikerisk import DAILY

COST_V = {"fx": 0.8, "metal": 0.16, "crypto": 0.5, "index": 0.5}


def gbm():
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=250,
                                          min_samples_leaf=300, l2_regularization=1.0)


def stat(x):
    x = x[~np.isnan(x)]
    if len(x) < 2:
        return f"{'-':>22}"
    return f"{x.mean():+.3f} +- {x.std(ddof=1) / np.sqrt(len(x)):.3f} (n={len(x):>4})"


def main():
    d, cols = build("1d", DAILY)
    X = d[cols].to_numpy(float)
    year = pd.to_datetime(d.ts, unit="s").dt.year.to_numpy()
    lc = d["_lc"]
    above200 = (lc > d.groupby("ticker")["_lc"].transform(lambda s: s.rolling(200, min_periods=150).mean())).to_numpy()
    fam = d.family.to_numpy()
    for H in (1, 5, 20):
        R = d[f"R@{H}"].to_numpy()
        y = d[f"tb_up@{H}"].to_numpy()
        U = 1.5 * d["_base"].to_numpy() * np.sqrt(H)
        cost = pd.Series(fam).map(COST_V).to_numpy() * d["_base"].to_numpy() / np.sqrt(288) / U
        net = R - cost
        slot = (d["_pos"].to_numpy() % H) == 0
        ok = ~np.isnan(R)
        split = d.split.to_numpy()
        tr, te = ok & (split == 0), ok & (split > 0)

        # (1) the original split, model vs rules on identical test bars
        p = np.full(len(d), np.nan)
        p[ok] = gbm().fit(X[tr], y[tr]).predict_proba(X[ok])[:, 1]
        short = d["short"].to_numpy()
        peak = d.groupby("ticker")["_lc"].transform(lambda s: s.rolling(50, min_periods=40).max())
        dd = ((peak - d["_lc"]) / d["_base"]).to_numpy()
        rules = {
            "always long": np.ones(len(d), bool),
            "model top 5%": p >= np.quantile(p[tr], 0.95),
            "model top 20%": p >= np.quantile(p[tr], 0.80),
            "high vol (top 5%)": short >= np.nanquantile(short[tr], 0.95),
            "high vol (top 20%)": short >= np.nanquantile(short[tr], 0.80),
            "dip (drawdown top 5%)": dd >= np.nanquantile(dd[tr], 0.95),
            "dip (drawdown top 20%)": dd >= np.nanquantile(dd[tr], 0.80),
        }
        print(f"\n{'=' * 100}\nH = {H} days. Net R per long trade, non-overlapping entries, test period "
              f"(last 40% of each series)")
        print(f"{'rule':<24} {'all':>30} {'above 200d':>30} {'below 200d':>30}")
        for name, m in rules.items():
            k = te & slot & m
            print(f"{name:<24} {stat(net[k]):>30} {stat(net[k & above200]):>30} {stat(net[k & ~above200]):>30}")
        both = te & slot & rules["model top 5%"]
        overlap = (both & rules["high vol (top 5%)"]).sum() / max(both.sum(), 1)
        print(f"share of model top-5% entries that are also high-vol top-5%: {overlap:.0%}; "
              f"also dip top-5%: {(both & rules['dip (drawdown top 5%)']).sum() / max(both.sum(), 1):.0%}")
        k = te & slot & rules["model top 5%"]
        print("model top 5% by family: " + ", ".join(
            f"{f} {stat(net[k & (fam == f)])}" for f in COST_V if (k & (fam == f)).sum() >= 10))
        print("model top 5% minus always-long, by family: " + ", ".join(
            f"{f} {net[k & (fam == f)].mean() - net[te & slot & (fam == f)].mean():+.3f}"
            for f in COST_V if (k & (fam == f)).sum() >= 10))

        # (3) rolling origin: fit on everything before year Y, score year Y
        rows = []
        for Y in range(2012, int(year.max()) + 1):
            trn, tst = ok & (year < Y), ok & (year == Y)
            if trn.sum() < 3000 or tst.sum() < 100 or y[trn].min() == y[trn].max():
                continue
            m = gbm().fit(X[trn], y[trn])
            q = m.predict_proba(X[tst])[:, 1]
            cut = np.quantile(m.predict_proba(X[trn][-20000:])[:, 1], 0.95)
            idx = np.flatnonzero(tst)
            pick = idx[(q >= cut) & slot[idx]]
            hv = idx[(short[idx] >= np.nanquantile(short[trn], 0.95)) & slot[idx]]
            base = idx[slot[idx]]
            rows.append((Y, len(pick), net[pick].mean() if len(pick) else np.nan,
                         net[hv].mean() if len(hv) else np.nan, net[base].mean()))
        t = pd.DataFrame(rows, columns=["year", "n_model", "model", "high_vol", "always_long"])
        t["model_minus_long"] = t.model - t.always_long
        print(f"\nrolling origin, H={H}: model beats always-long in {(t.model_minus_long > 0).sum()} of "
              f"{t.model_minus_long.notna().sum()} years; beats high-vol rule in "
              f"{(t.model > t.high_vol).sum()} of {(t.model.notna() & t.high_vol.notna()).sum()}")
        print(t.to_string(index=False, float_format="%+.3f"))
        Path(".data/research").mkdir(parents=True, exist_ok=True)
        t.to_csv(f".data/research/dailylong_rolling_H{H}.csv", index=False)


if __name__ == "__main__":
    main()
