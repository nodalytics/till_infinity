"""Which self-correcting percentiles should the envelope use: ACI, AgACI, regime-weighted, or SPCI?

`envelope.md` shipped the empirical envelope under ACI with one fixed step (gamma 0.005). It holds
10/50/90% at N = 5 and 10 bars, drifts at 20, and slips to about 88% at 50 bars (worst slices
81-87%). It is calibrated only on average across regimes (P90 88/90/92% from calm to volatile).
Three published ideas target exactly those two failures:

  AgACI    Zaffran et al. 2022 (arXiv 2202.07282): run ACI with a grid of steps and aggregate the
           experts online, the lower and upper bounds separately, weighted by the pinball loss at
           their own level (Bernstein Online Aggregation). Parameter-free - no gamma to pick.
  weighted MoE-CP (Kong et al., ICLR 2026): weight past outcomes by how similar the conditions
           were when they happened. Here the condition is the volatility state (the 14-bar EWMA of
           true range against its own 500-bar mean), so a volatile moment is quoted from volatile
           history - aimed at conditional coverage.
  SPCI     Xu & Xie 2023: predict the next outcome's quantiles from the autocorrelation of past
           residuals. Here: quantile boosting on volatility features plus the last resolved outcomes.

Every method quotes P10 / P50 / P90 of y = log(close[t+N] / close[t]) in units of the production
volatility, with feedback arriving N bars late as it would live. Scored on the last 40% of each
series: coverage, pinball, width, P90 across twenty slices of time, and P90 in calm / normal /
volatile thirds. N = 5, 20, 50 at 15m. FX, metals, crypto, and Volatility / Boom / Range Break
synthetics.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).parent))
import envelope as env  # the same frame and scoring as envelope.py

from fractal_twins import FAMILIES

TARGETS = (0.1, 0.5, 0.9)
GAMMAS = tuple(np.geomspace(0.0005, 0.1, 12))
WINDOW = 2000
HALF = 0.25  # bandwidth of the regime weighting, in log volatility ratio
LAGS = 5
GROUPS = {
    "fx": FAMILIES["fx"], "metals": FAMILIES["metal"], "crypto": FAMILIES["crypto"],
    "volatility": ["Volatility_10_Index", "Volatility_25_Index", "Volatility_75_Index", "Volatility_100_Index"],
    "boom/crash": ["Boom_500_Index", "Boom_1000_Index", "Crash_500_Index", "Crash_1000_Index"],
    "range break": ["Range_Break_100_Index", "Range_Break_200_Index"],
}


def pinball_grad(q, y, beta):
    """d pinball / d quote."""
    return (1.0 if y <= q else 0.0) - beta


class BOA:
    """Bernstein Online Aggregation (Wintenberger 2017) with the gradient trick and per-expert
    adaptive learning rates - the aggregation rule AgACI uses."""

    def __init__(self, k):
        self.k = k
        self.cum = np.zeros(k)  # cumulative linearised regret
        self.cum2 = np.zeros(k)

    def weights(self):
        # BOA's second-order weights: first-order regret plus a variance penalty, each expert with
        # its own adaptive learning rate.
        eta = np.minimum(0.5, np.sqrt(np.log(self.k) / (1.0 + self.cum2)))
        logw = -eta * self.cum - eta**2 * self.cum2
        logw -= logw.max()
        w = np.exp(logw)
        return w / w.sum()

    def update(self, experts, agg, y, beta):
        g = pinball_grad(agg, y, beta)
        loss = g * (experts - agg)  # linearised loss of each expert against the aggregate
        self.cum += loss
        self.cum2 += loss * loss


def run(g, method, gbm_pred=None, H=5):
    """Quotes for each target on the test block of one series."""
    y = g["y"].to_numpy()
    lv = g["lvol"].to_numpy()
    idx = np.flatnonzero(g["test"].to_numpy() & np.isfinite(y))
    if not len(idx):
        return idx, {q: np.array([]) for q in TARGETS}
    quotes = {q: np.full(len(idx), np.nan) for q in TARGETS}
    start = max(0, idx[0] - WINDOW - H)
    hist_y = list(y[start:idx[0] - H])
    hist_v = list(lv[start:idx[0] - H])
    a = {q: q for q in TARGETS}  # ACI state
    experts = {q: np.full(len(GAMMAS), q) for q in TARGETS}  # AgACI: one ACI level per gamma
    agg = {q: BOA(len(GAMMAS)) for q in TARGETS}
    expert_quotes = {q: np.zeros((len(idx), len(GAMMAS))) for q in TARGETS}
    sorted_y = None
    for k, i in enumerate(idx):
        if sorted_y is None or k % 10 == 0:
            arr_y, arr_v = np.asarray(hist_y[-WINDOW:]), np.asarray(hist_v[-WINDOW:])
            ok = np.isfinite(arr_y) & np.isfinite(arr_v)
            arr_y, arr_v = arr_y[ok], arr_v[ok]
            order = np.argsort(arr_y)
            sorted_y, sorted_v = arr_y[order], arr_v[order]
        n = len(sorted_y)

        def empirical(level):
            return sorted_y[int(round(np.clip(level, 0.0, 1.0) * (n - 1)))]

        def weighted(level):
            w = np.exp(-0.5 * ((sorted_v - lv[i]) / HALF) ** 2) if np.isfinite(lv[i]) else np.ones(n)
            c = np.cumsum(w)
            return sorted_y[min(np.searchsorted(c, np.clip(level, 0, 1) * c[-1]), n - 1)]

        for q in TARGETS:
            if method == "aci":
                Q = empirical(a[q])
            elif method == "agaci":
                eq = np.array([empirical(lvl) for lvl in experts[q]])
                expert_quotes[q][k] = eq
                Q = float(agg[q].weights() @ eq) if q != 0.5 else float(np.median(eq))
            elif method == "weighted":
                Q = weighted(q)
            elif method == "weighted aci":
                Q = weighted(a[q])
            elif method in ("gbm", "spci"):
                Q = np.interp(q, env.LEVELS, gbm_pred[i])
            elif method in ("gbm aci", "spci aci"):
                Q = np.interp(a[q], env.LEVELS, gbm_pred[i])
            quotes[q][k] = Q
        if k >= H:
            kk = k - H
            yy = y[idx[kk]]
            for q in TARGETS:
                hit = float(yy <= quotes[q][kk])
                if method.endswith("aci") and method != "agaci":
                    a[q] = float(np.clip(a[q] + env.GAMMA * (q - hit), 0.002, 0.998))
                if method == "agaci":
                    eq = expert_quotes[q][kk]
                    hits = (yy <= eq).astype(float)
                    experts[q] = np.clip(experts[q] + np.array(GAMMAS) * (q - hits), 0.002, 0.998)
                    agg[q].update(eq, quotes[q][kk], yy, q)
            hist_y.append(yy)
            hist_v.append(lv[idx[kk]])
    return idx, quotes


def main():
    horizons = tuple(int(x) for x in os.environ.get("HORIZONS", "5,20,50").split(","))
    interval = os.environ.get("INTERVAL", "15m")
    feats = ["lvol", "r1", "r5", "r20", "rng", "hour"]
    for H in horizons:
        env.H = H
        print(f"\n{'=' * 120}\nCONFORMAL {interval}, next {H} bars; test = last 40%")
        for name, syms in GROUPS.items():
            frames = []
            for s in syms:
                try:
                    f = env.frame(s, interval)
                except (ValueError, FileNotFoundError):
                    continue
                # SPCI: the last resolved outcomes (known H bars late), as features
                for j in range(LAGS):
                    f[f"ylag{j}"] = f["y"].shift(H + j)
                frames.append(f)
            if not frames:
                continue
            allf = pd.concat(frames, ignore_index=True)
            tr = allf[~allf["test"] & allf["y"].notna()].dropna(subset=[f"ylag{j}" for j in range(LAGS)])
            fit = tr.sample(min(150_000, len(tr)), random_state=0)
            spci_feats = feats + [f"ylag{j}" for j in range(LAGS)]
            models = {m: {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, max_depth=4, max_iter=150,
                                                           learning_rate=0.05, min_samples_leaf=500)
                          .fit(fit[fs], fit["y"]) for q in env.LEVELS}
                      for m, fs in (("gbm", feats), ("spci", spci_feats))}
            print(f"\n  {name}: {len(allf):,} bars")
            for method in ("aci", "agaci", "weighted", "weighted aci", "gbm", "gbm aci", "spci", "spci aci"):
                res = []
                for g in frames:
                    g = g.reset_index(drop=True)
                    pred = None
                    if method.startswith(("gbm", "spci")):
                        m = models["spci" if method.startswith("spci") else "gbm"]
                        fs = spci_feats if method.startswith("spci") else feats
                        pred = np.sort(np.column_stack([m[q].predict(g[fs].fillna(0.0)) for q in env.LEVELS]), axis=1)
                    idx, quotes = run(g, method, pred, H)
                    res.append({"y": g["y"].to_numpy()[idx], "lvol": g["lvol"].to_numpy()[idx], "Q": quotes})
                env.evaluate(method, res)


if __name__ == "__main__":
    main()
