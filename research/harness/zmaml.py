"""ZMA with machine learning on top: does a model find what the rule misses?

`structures/zma.py` is a hand-built mean-reversion detector: an attention-weighted z-score, a
normalised slope, and firing rules at percentile thresholds (`agrees`: stretched and already
turning; `stretched`: past the threshold). `research/docs/zma.md` measured the rule: it finds
reversion on an Ornstein-Uhlenbeck control in proportion to the reversion speed, finds none on this
desk's outright prices, and pays only on constructed spreads.

The question here is whether learning the combination (a model on ZMA's own outputs, and on those
plus context) finds anything the rules miss. It is measured the only way that can answer it: on
three universes run through the same code.
  positive   OU series at theta 0.02, 0.05, 0.15 - reversion exists and is graded; a model that
             cannot beat the rule here is not worth anything anywhere
  control    Deriv Volatility and Step indices - exact random walks; any skill here is the pipeline
  real       15 FX pairs, XAU, XAG, BTC, ETH, SOL
at 15m and 1h (the lab's broker bars). Production `Zma` is run bar by bar on closes.

Targets: the next bar's direction (what ZMA's own record settles on) and the direction over H = 8
bars. Models are fit on each universe's first 60% by time and scored on the last 40%:
  rule -z        the continuous stretch, as a score
  rule agrees    ZMA's call: +1/-1 when fired, 0 otherwise
  logistic       on ZMA's outputs (z, slope, thresholds, flags)
  GBM zma+ctx    on ZMA's outputs plus context (returns over 1/5/20 bars, volatility ratio, hour)
  GBM ctx only   the same context without ZMA - does ZMA add anything to plain returns?
Scored by AUC and Brier/log-loss skill against the training base rate, and, on real markets, as a
trade on the top and bottom decile of each model's score, net of spread, non-overlapping.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import COST_V, FAMILIES

from till_infinity.structures.zma import Zma

RNG = np.random.default_rng(23)
INTERVAL = os.environ.get("INTERVAL", "15m")
H = 8
SECONDS = {"15m": 900, "1h": 3600}
ZMA_COLS = ["z", "slope", "strong", "weak", "zrel", "rising", "agrees", "stretched"]
CTX_COLS = ["r1", "r5", "r20", "volratio", "hour"]


def features(close, ts, family, name):
    z = Zma()
    rows = np.full((len(close), 8), np.nan)
    for i, p in enumerate(close):
        z.observe(float(p))
        if z.warm:
            rows[i] = (z.z_score, z.slope, z.strong, z.weak, abs(z.z_score) / max(z.strong, 1e-9), float(z.rising),
                       float(z.agrees), float(z.stretched))
    lc = np.log(close)
    r = np.diff(lc, prepend=np.nan)
    base = pd.Series(np.abs(r)).rolling(500, min_periods=250).mean().to_numpy()
    d = pd.DataFrame(rows, columns=ZMA_COLS)
    d["r1"] = r / base
    d["r5"] = (lc - np.r_[np.full(5, np.nan), lc[:-5]]) / base
    d["r20"] = (lc - np.r_[np.full(20, np.nan), lc[:-20]]) / base
    d["volratio"] = pd.Series(np.abs(r)).rolling(20).mean().to_numpy() / base
    d["hour"] = pd.to_datetime(ts, unit="s").hour if ts is not None else 0
    d["y1"] = np.r_[lc[1:] - lc[:-1], np.nan] / base
    d["yH"] = np.r_[lc[H:] - lc[:-H], np.full(H, np.nan)] / base
    d["family"], d["series"], d["t"] = family, name, np.arange(len(close))
    d["test"] = d["t"] >= 0.6 * len(close)
    d["half"] = d["t"] >= 0.8 * len(close)
    return d.dropna(subset=ZMA_COLS + ["r20", "volratio", "yH"])


def ou(n, theta, rng):
    x = np.empty(n)
    x[0] = 0.0
    for i in range(1, n):
        x[i] = x[i - 1] - theta * x[i - 1] + rng.normal()
    return 100.0 * np.exp(0.001 * x)  # positive prices with a reverting log


def universe(name):
    parts = []
    if name == "positive":
        for theta in (0.02, 0.05, 0.15):
            for seed in range(3):
                parts.append(features(ou(20_000, theta, np.random.default_rng(seed)), None, f"OU {theta}", f"ou{theta}_{seed}"))
        return pd.concat(parts, ignore_index=True)
    fams = {"control": ["control"], "real": ["fx", "metal", "crypto"]}[name]
    for fam in fams:
        syms = FAMILIES[fam] if fam != "control" else ["Volatility_10_Index", "Volatility_25_Index", "Volatility_50_Index",
                                                       "Volatility_75_Index", "Volatility_100_Index", "Step_Index"]
        for s in syms:
            try:
                df = spikerisk.load(None, s, "SEQLAB", INTERVAL)
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {s}: {str(exc)[:60]}", flush=True)
                continue
            parts.append(features(df["close"].to_numpy(), df["ts"].to_numpy(), fam, s))
    return pd.concat(parts, ignore_index=True)


def skill(p, y, base):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    b = np.mean((p - y) ** 2)
    b0 = np.mean((base - y) ** 2)
    ll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    ll0 = -np.mean(y * np.log(base) + (1 - y) * np.log(1 - base))
    return 1 - b / b0, 1 - ll / ll0


def study(name, d):
    print(f"\n  {name}: {len(d):,} bars, {d['series'].nunique()} series")
    groups = [("all", d)] + ([(f, g) for f, g in d.groupby("family")] if name == "positive" else [])
    for target in ("y1", "yH"):
        dd = d[d[target] != 0]
        y = (dd[target] > 0).to_numpy(float)
        tr, te = ~dd["test"].to_numpy(), dd["test"].to_numpy()
        base = y[tr].mean()
        X_z = dd[ZMA_COLS].to_numpy()
        X_all = dd[ZMA_COLS + CTX_COLS].to_numpy()
        X_ctx = dd[CTX_COLS].to_numpy()
        # fit on a sample of training rows to keep it quick
        fit = RNG.choice(np.flatnonzero(tr), min(400_000, tr.sum()), replace=False)
        scores = {
            "rule -z": -dd["z"].to_numpy(),
            "rule agrees": dd["agrees"].to_numpy() + 1e-6 * RNG.standard_normal(len(dd)),
        }
        logit = LogisticRegression(max_iter=500).fit(X_z[fit], y[fit])
        scores["logistic zma"] = logit.predict_proba(X_z)[:, 1]
        g1 = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=500).fit(X_all[fit], y[fit])
        scores["GBM zma+ctx"] = g1.predict_proba(X_all)[:, 1]
        g2 = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=500).fit(X_ctx[fit], y[fit])
        scores["GBM ctx only"] = g2.predict_proba(X_ctx)[:, 1]
        print(f"   target {'next bar' if target == 'y1' else f'next {H} bars'} (train up-rate {base:.3f})")
        for gname, g in groups:
            m = te & dd.index.isin(g.index)
            cells = []
            for sname, s in scores.items():
                auc = roc_auc_score(y[m], s[m])
                cell = f"{sname} AUC {auc:.3f}"
                if sname.startswith(("logistic", "GBM")):
                    bss, lls = skill(s[m], y[m], base)
                    cell += f" BSS {bss:+.4f}"
                cells.append(cell)
            print(f"     {gname:<10} " + " | ".join(cells))
        if name == "real" and target == "yH":
            # trade the extremes of each score, net of spread, non-overlapping
            fam = dd["family"].to_numpy()
            cost = np.array([COST_V.get(f, 0.8) for f in fam]) / np.sqrt(SECONDS[INTERVAL] / 300)
            slot = (dd["t"].to_numpy() % H) == 0
            print("     trade top/bottom training decile of each score, H bars, in baseline moves:")
            for sname, s in scores.items():
                hi, lo = np.quantile(s[tr], 0.9), np.quantile(s[tr], 0.1)
                side = np.where(s >= hi, 1.0, np.where(s <= lo, -1.0, 0.0))
                k = te & slot & (side != 0)
                r = side[k] * dd[target].to_numpy()[k]
                half = dd["half"].to_numpy()[k]
                print(f"       {sname:<14} n={k.sum():>6} gross {r.mean():+.3f} net {np.mean(r - cost[k]):+.3f} "
                      f"(halves {np.mean((r - cost[k])[~half]):+.3f} / {np.mean((r - cost[k])[half]):+.3f})")


def main():
    print(f"\n{'=' * 110}\nZMA + ML, {INTERVAL}, production Zma on closes; fit on the first 60% of each universe, scored on the last 40%")
    for name in ("positive", "control", "real"):
        study(name, universe(name))


if __name__ == "__main__":
    main()
