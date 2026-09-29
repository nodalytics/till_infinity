"""The next 5 bars as a distribution: P10 / P50 / P90, and percentiles that correct themselves.

The ask: profile or predict the distribution of the next 5 bars, publish P90 / P50 / P10 ("bullish
ceiling", "consensus median", "downside support"), and notice when a stated percentile has drifted -
"P90" covering like P80 now - and correct it dynamically.

Target: y = log(close[t+5] / close[t]), in units of sigma_t, the production volatility (the 14-bar
EWMA of true range, `ranges.TR_ALPHA`), so every series and regime shares one scale.

Base forecasters, all causal:
  gauss      a normal with one scale constant fit on the training block
  empirical  the quantiles of the last 2,000 resolved standardised 5-bar moves (fat tails, skew)
  gbm        gradient-boosted quantile regression on volatility and return features, fit on the first
             60% at the levels 0.05 ... 0.95 and interpolated between them
Each also runs with adaptive conformal inference (ACI; Gibbs & Candes 2021) on top. For each target
level q, the level actually quoted, a_t, moves after every resolved outcome by
a <- a + gamma * (q - hit), where hit = 1 if y fell below the quantile it was quoted. A "P90" that is
being hit 80% of the time is quoted at a higher level until it covers 90% again. Feedback arrives
5 bars late, as it would live.

Scored on the last 40% of each series:
  coverage          the share of outcomes below each quoted quantile (target 10 / 50 / 90%)
  pinball           the proper score for a quantile (lower is better)
  width             P90 - P10 in sigma
  stability         P90 coverage in 20 consecutive chunks of the test block: its spread and worst chunk
  by regime         P90 coverage in low / mid / high thirds of sigma relative to its 500-bar mean
  direction         AUC of the P50 for the sign of y - does the median say anything about which way
Families: 15 FX pairs, XAU/XAG, BTC/ETH/SOL, and every Deriv synthetic family on the lab (Volatility,
Volatility 1s, Jump, Step, Skew Step, Boom, Crash, DEX, Drift Switch, Range Break), at 15m and 1h,
over N = 5, 10, 20 and 50 bars (HORIZONS). Width / sqrt(N) profiles how the band grows with N: flat is
the random-walk law.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import FAMILIES

H = 5  # set per run from HORIZONS
HORIZONS = tuple(int(x) for x in os.environ.get("HORIZONS", "5,10,20,50").split(","))
LEVELS = (0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95)
TARGETS = (0.1, 0.5, 0.9)
GAMMA = float(os.environ.get("GAMMA", "0.005"))
WINDOW = 2000
RNG = np.random.default_rng(47)


def frame(sym, interval):
    df = spikerisk.load(None, sym, "SEQLAB", interval)
    o, h, l, c = (np.log(df[k].to_numpy()) for k in ("open", "high", "low", "close"))
    prev = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.column_stack([h - l, np.abs(h - prev), np.abs(l - prev)]), axis=1)
    sig = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    long = pd.Series(tr).rolling(500, min_periods=250).mean().to_numpy()
    r = np.diff(c, prepend=np.nan)
    d = pd.DataFrame({
        "y": np.r_[c[H:] - c[:-H], np.full(H, np.nan)] / sig,
        "lvol": np.log(sig / long), "r1": r / sig, "r5": (c - np.r_[np.full(5, np.nan), c[:-5]]) / sig,
        "r20": (c - np.r_[np.full(20, np.nan), c[:-20]]) / sig, "rng": (h - l) / sig,
        "hour": pd.to_datetime(df["ts"].to_numpy(), unit="s").hour, "sig": sig,
    })
    d["sym"], d["t"] = sym, np.arange(len(d))
    d["test"] = d["t"] >= 0.6 * len(d)
    return d.dropna(subset=["lvol", "r20"]).reset_index(drop=True)


def run_series(g, base, gbm_pred, scale):
    """Quotes for each target level on one series' test block: raw and with ACI. Returns dict of arrays."""
    y = g["y"].to_numpy()
    te = g["test"].to_numpy()
    idx = np.flatnonzero(te & np.isfinite(y))
    out = {}
    for mode in ("raw", "aci"):
        a = {q: q for q in TARGETS}
        quotes = {q: np.full(len(idx), np.nan) for q in TARGETS}
        hist = list(y[max(0, idx[0] - WINDOW - H):idx[0] - H]) if len(idx) else []
        cached = None
        for k, i in enumerate(idx):
            if base == "empirical" and (cached is None or k % 25 == 0):
                # The window moves one bar at a time and its quantiles barely at all; re-sorting every 25
                # bars keeps the run tractable across ninety series and four horizons.
                arr = np.asarray(hist[-WINDOW:])
                cached = np.sort(arr[np.isfinite(arr)])
            for q in TARGETS:
                lvl = a[q] if mode == "aci" else q
                if base == "gauss":
                    Q = stats.norm.ppf(lvl) * scale
                elif base == "empirical":
                    n = len(cached)
                    Q = cached[int(round(lvl * (n - 1)))] if n > 200 else stats.norm.ppf(lvl) * scale
                else:
                    Q = np.interp(lvl, LEVELS, gbm_pred[i])
                quotes[q][k] = Q
            # outcomes resolve H bars later: update ACI then
            if k >= H:
                kk = k - H
                for q in TARGETS:
                    hit = float(y[idx[kk]] <= quotes[q][kk])
                    if mode == "aci":
                        a[q] = float(np.clip(a[q] + GAMMA * (q - hit), 0.002, 0.998))
                hist.append(y[idx[kk]])
        out[mode] = quotes
    return idx, out


def evaluate(name, rows):
    """rows: list of (y, lvol, quotes dict for q) concatenated across series."""
    y = np.concatenate([r["y"] for r in rows])
    lv = np.concatenate([r["lvol"] for r in rows])
    Q = {q: np.concatenate([r["Q"][q] for r in rows]) for q in TARGETS}
    cov = {q: np.mean(y <= Q[q]) for q in TARGETS}
    pin = {q: np.mean(np.maximum(q * (y - Q[q]), (q - 1) * (y - Q[q]))) for q in TARGETS}
    width = np.mean(Q[0.9] - Q[0.1])
    chunks = np.array_split(np.arange(len(y)), 20)
    c90 = np.array([np.mean(y[c] <= Q[0.9][c]) for c in chunks])
    terc = np.quantile(lv, [1 / 3, 2 / 3])
    reg = [np.mean(y[m] <= Q[0.9][m]) for m in (lv <= terc[0], (lv > terc[0]) & (lv <= terc[1]), lv > terc[1])]
    auc = roc_auc_score(y > 0, Q[0.5]) if np.std(Q[0.5]) > 0 else 0.5
    print(f"    {name:<16} cover P10/P50/P90 {cov[0.1]:.1%} / {cov[0.5]:.1%} / {cov[0.9]:.1%} | pinball "
          f"{pin[0.1]:.3f} / {pin[0.5]:.3f} / {pin[0.9]:.3f} | width {width:.2f} (/sqrt N {width / np.sqrt(H):.2f}) | P90 by chunk sd {c90.std():.1%} "
          f"worst {c90.min():.1%} | P90 by vol third {reg[0]:.1%} / {reg[1]:.1%} / {reg[2]:.1%} | P50 AUC {auc:.3f}")


SYNTHETICS = {
    "volatility": [f"Volatility_{v}_Index" for v in (5, 10, 15, 25, 30, 50, 75, 90, 100)],
    "volatility 1s": [f"Volatility_{v}_1s_Index" for v in (5, 10, 15, 25, 30, 50, 75, 90, 100, 150, 250)],
    "jump": [f"Jump_{v}_Index" for v in (10, 25, 50, 75, 100)],
    "step": ["Step_Index", "Step_Index_200", "Multi_Step_2_Index", "Multi_Step_3_Index", "Multi_Step_4_Index"],
    "skew step": ["Skew_Step_Index_4_Up", "Skew_Step_Index_4_Down", "Skew_Step_Index_5_Up", "Skew_Step_Index_5_Down"],
    "boom": [f"Boom_{v}_Index" for v in (50, 100, 150, 200, 300, 500, 600, 900, 1000)],
    "crash": [f"Crash_{v}_Index" for v in (50, 100, 150, 200, 300, 500, 600, 900, 1000)],
    "dex": [f"DEX_{v}_{d}_Index" for v in (600, 900, 1500) for d in ("UP", "DOWN")],
    "drift switch": [f"Drift_Switch_Index_{v}" for v in (10, 20, 30)],
    "range break": ["Range_Break_100_Index", "Range_Break_200_Index"],
}


def main():
    global H
    groups = {"fx": FAMILIES["fx"], "metals": FAMILIES["metal"], "crypto": FAMILIES["crypto"], **SYNTHETICS}
    feats = ["lvol", "r1", "r5", "r20", "rng", "hour"]
    runs = [(i, h) for i in os.environ.get("INTERVALS", "15m,1h").split(",") for h in HORIZONS]
    for interval, H in runs:
        print(f"\n{'=' * 120}\nENVELOPE {interval}, next {H} bars, y in units of the production volatility; ACI gamma {GAMMA}; test = last 40%")
        for name, syms in groups.items():
            frames = []
            for s in syms:
                try:
                    frames.append(frame(s, interval))
                except (ValueError, FileNotFoundError) as exc:
                    print(f"  skip {s}: {str(exc)[:60]}")
            allf = pd.concat(frames, ignore_index=True)
            tr = allf[~allf["test"] & allf["y"].notna()]
            scale = tr["y"].std()
            fit = tr.sample(min(150_000, len(tr)), random_state=0)
            models = {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, max_depth=4, max_iter=200,
                                                       learning_rate=0.05, min_samples_leaf=500).fit(fit[feats], fit["y"])
                      for q in LEVELS}
            print(f"\n  {name}: {len(allf):,} bars, train sd of y {scale:.2f} (a random walk's {H}-bar sd would be about "
                  f"{np.sqrt(H) / 1.25:.2f} in these units)")
            for base in ("gauss", "empirical", "gbm"):
                res = {"raw": [], "aci": []}
                for g in frames:
                    g = g.reset_index(drop=True)
                    pred = np.column_stack([models[q].predict(g[feats]) for q in LEVELS]) if base == "gbm" else None
                    if pred is not None:
                        pred = np.sort(pred, axis=1)  # no crossing quantiles
                    idx, out = run_series(g, base, pred, scale)
                    for mode in res:
                        res[mode].append({"y": g["y"].to_numpy()[idx], "lvol": g["lvol"].to_numpy()[idx], "Q": out[mode]})
                for mode in ("raw", "aci"):
                    evaluate(f"{base} {mode}", res[mode])


if __name__ == "__main__":
    main()
