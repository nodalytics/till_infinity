"""Zone-fill probability: does price reach the nearest liquidity zone, and does trading it pay?

The method under test, as described by its author: for every liquidity zone near the price,
estimate the probability that price fills it, from four inputs - how hard price is moving,
how directional the motion is (directional efficiency), how large the zone is, and how far
away it is - through a hand-weighted function; then trade toward the zone with the highest
probability, at first only when that probability is 1. Framed as a quantum analogy (the
position is only known as a probability until the wave collapses), it is mathematically a
classical first-passage probability, and with the hand weights replaced by fitted ones it is a
logistic regression.

Two results already in this repository bound what it can do:
- first passage of a random walk to a level is set almost entirely by distance over
  volatility (the reflection principle), so a near zone is "high probability" for free;
- `barrier-geometry-is-irrelevant.md`: a stop-and-target trade earns the drift over its hold
  and nothing else, so a high fill probability buys a high win rate, not expectancy, unless
  the inputs carry direction.

So the test is whether speed and efficiency add anything beyond distance, whether the
probabilities are calibrated (above all at "certainty"), and whether the trade pays net.

Zones: the nearest untaken 50-bar swing high above and swing low below - resting liquidity -
sized by how many of the last 50 highs (lows) lie within a quarter of a baseline move of it.
(Fair value gaps as zones were measured in `imbalance.md`: directions right, nothing paying.)

Inputs, per zone, all causal: distance (baseline units), zone size, speed (10-bar mean |r| over
baseline), push velocity (5-bar mean signed return toward the zone, baseline units) and
directional efficiency (20-bar net move over path, signed toward the zone).
Label: the zone is touched by a wick within H bars.

Probabilities compared, fit on each series' first 60% by time, scored on the last 40%:
  physics   2 x (1 - Phi(d / (sigma sqrt H))), sigma from the baseline - distance alone, no fit
  distance  logistic on distance and speed only
  full      logistic on all five inputs - the method with its weights fitted

Trade: toward the zone with the highest full-model probability, target at the zone, stop at 1x
or 2x the zone's distance on the other side, resolved on wicks (`bars.py`), net of spread,
non-overlapping, both halves of the test reported. Also the "certainty" buckets, P >= 0.95 and
P >= 0.99.

Run on the lab:
  ./.secrets/lab.sh run research/harness/zonefill.py SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=8
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
from bars import Bars, long_R

SEQLAB = Path(os.environ.get("SEQLAB", ".data/seqlab"))
H = 8
LOOK = 50
FAMILIES = {
    "fx": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
           "EURGBP", "AUDJPY", "EURAUD"],
    "metal": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    # the control: exact random walks (`twins.md`) - no input can carry direction here
    "synthetic": ["Volatility_25_Index", "Volatility_75_Index", "Volatility_100_Index", "Step_Index"],
}
COST_V = {"fx": 0.8, "metal": 0.16, "crypto": 0.5, "synthetic": 0.15}  # round trip, M5-vol units
MINUTES = {"15m": 15, "1h": 60}
INPUTS = ["dist", "size", "speed", "velocity", "efficiency"]


def series(sym, interval):
    z = np.load(SEQLAB / f"{sym}.{interval}.npz")  # plain arrays; never allow_pickle
    df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close")}).drop_duplicates("time")
    df = df.sort_values("time").reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


def zones(df):
    """One row per bar and side (+1 above, -1 below): the nearest untaken swing extreme."""
    lo_, hi_, lc = np.log(df.low), np.log(df.high), np.log(df.close)
    r = lc.diff()
    base = r.abs().rolling(500, min_periods=250).mean()
    speed = r.abs().rolling(10).mean() / base
    path = r.abs().rolling(20).sum()
    eff = (lc - lc.shift(20)) / path
    vel = r.rolling(5).mean() / base
    out = []
    for side in (1, -1):
        if side > 0:
            level = hi_.shift(1).rolling(LOOK).max()  # the highest high of the previous 50 bars
            dist = (level - lc) / base
        else:
            level = lo_.shift(1).rolling(LOOK).min()
            dist = (lc - level) / base
        # zone size: extremes within a quarter of a baseline move of the level
        band = 0.25 * base
        if side > 0:
            cluster = sum((hi_.shift(k) >= level - band).astype(float) for k in range(1, LOOK + 1))
        else:
            cluster = sum((lo_.shift(k) <= level + band).astype(float) for k in range(1, LOOK + 1))
        z = pd.DataFrame({
            "t": np.arange(len(df)), "side": side, "level": level, "dist": dist, "size": cluster,
            "speed": speed, "velocity": side * vel, "efficiency": side * eff, "base": base,
        })
        z = z[z.dist > 0]  # a zone the close already sits beyond is not ahead of it
        out.append(z)
    return pd.concat(out, ignore_index=True)


def label_and_trade(df, z, interval, family):
    lc = np.log(df.close.to_numpy())
    n = len(lc)
    idx = z.t.to_numpy()
    ok = idx + H < n
    z = z[ok].copy()
    idx = z.t.to_numpy()
    side = z.side.to_numpy()

    def ahead(col):
        a = np.log(df[col].to_numpy())
        return np.column_stack([a[idx + k] - lc[idx] for k in range(1, H + 1)])

    P = Bars(ahead("open"), ahead("high"), ahead("low"), ahead("close"))
    P = P * side  # the zone's side is "up" from here on
    reach = z.dist.to_numpy() * z.base.to_numpy()
    z["filled"] = (np.nanmax(P.h, axis=1) >= reach).astype(float)
    cost = COST_V[family] * z.base.to_numpy() / np.sqrt(MINUTES[interval] / 5)
    first = np.argmax((P.h >= reach[:, None]) | (P.l <= -reach[:, None]), axis=1)
    rows_ = np.arange(len(first))
    # the first bar that touches either level touches both: `bars.py` scores it as the stop
    z["tie"] = ((P.h[rows_, first] >= reach) & (P.l[rows_, first] <= -reach)).astype(float)
    z["dist_bar"] = reach / np.nanmean(P.h[:, :1] - P.l[:, :1])  # zone distance over one bar's range
    for k in (1, 2):
        R, _ = long_R(P, reach, k * reach)
        z[f"R{k}"] = R
        z[f"cost{k}"] = cost / (k * reach)
    sigma = z.base.to_numpy() * np.sqrt(np.pi / 2)
    z["physics"] = np.clip(2 * (1 - norm.cdf(reach / (sigma * np.sqrt(H)))), 0, 1)
    return z


def study(interval):
    parts = []
    for family, syms in FAMILIES.items():
        for s in syms:
            f = SEQLAB / f"{s}.{interval}.npz"
            if not f.exists():
                continue
            df = series(s, interval)
            z = label_and_trade(df, zones(df), interval, family).dropna(subset=INPUTS + ["filled", "R1"])
            z["family"], z["sym"] = family, s
            cut = z.t.quantile(0.6)
            z["test"] = z.t >= cut
            z["half"] = z.t >= z.t.quantile(0.8)
            parts.append(z)
    d = pd.concat(parts, ignore_index=True)
    X = d[INPUTS].to_numpy(float)
    X[:, 0] = np.log(X[:, 0])  # distance enters as a log - first passage is not linear in it
    X[:, 1] = np.log1p(X[:, 1])
    tr, te = ~d.test.to_numpy(), d.test.to_numpy()
    y = d.filled.to_numpy()
    print(f"\n{'=' * 110}\n{interval}: {d.sym.nunique()} series, {len(d):,} zone-bars, H={H} bars; "
          f"test fill rate {y[te].mean():.1%}")

    def fit(cols):
        m = LogisticRegression(max_iter=2000).fit(X[tr][:, cols], y[tr])
        return m.predict_proba(X[:, cols])[:, 1], m

    p_dist, _ = fit([0, 2])
    p_full, m_full = fit([0, 1, 2, 3, 4])
    d["p"] = p_full
    print("coefficients (full): " + ", ".join(f"{c} {w:+.2f}" for c, w in zip(INPUTS, m_full.coef_[0])))
    for fam in ["all", *FAMILIES]:
        k = te if fam == "all" else te & (d.family == fam).to_numpy()
        if k.sum() < 200:
            continue
        yt = y[k]
        row = []
        for name, p in (("physics", d.physics.to_numpy()), ("distance", p_dist), ("full", p_full)):
            row.append(f"{name} AUC {roc_auc_score(yt, p[k]):.3f} Brier {brier_score_loss(yt, p[k]):.3f}")
        print(f"  {fam:<9} n={k.sum():>7,} fill {yt.mean():5.1%} | " + " | ".join(row))

    print("  calibration of the full model on the test block (predicted -> realised):")
    for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, .95), (.95, .99), (.99, 1.01)):
        k = te & (p_full >= lo) & (p_full < hi)
        if k.sum():
            print(f"    P in [{lo:.2f},{min(hi, 1):.2f}): n={k.sum():>7,}  predicted {p_full[k].mean():.3f}  "
                  f"realised {y[k].mean():.3f}")

    # trade: per bar the zone with the higher probability, non-overlapping per series
    best = d.loc[d.groupby(["sym", "t"]).p.idxmax()].sort_values(["sym", "t"])
    keep = []
    for _, g in best.groupby("sym"):
        last = -10**9
        for i, t in zip(g.index, g.t):
            if t - last >= H:
                keep.append(i)
                last = t
    b = best.loc[keep]
    b = b[b.test]
    print("  trade toward the most probable zone (target = zone), net R per trade:")
    for label, sel in (("every bar", np.ones(len(b), bool)), ("P >= 0.80", b.p >= 0.8),
                       ("P >= 0.95 ('certainty')", b.p >= 0.95), ("P >= 0.99", b.p >= 0.99)):
        s = b[sel.to_numpy() if hasattr(sel, "to_numpy") else sel]
        if len(s) < 20:
            print(f"    {label:<26} n={len(s)}")
            continue
        for kk in (1, 2):
            net = s[f"R{kk}"] - s[f"cost{kk}"]
            geo = 1 / (1 + 1 / kk)  # random-walk win rate for target at d, stop at k*d: k/(1+k)
            a_, b_ = net[~s.half].mean(), net[s.half].mean()
            fams = " ".join(f"{f[:3]}{net[s.family == f].mean():+.3f}" for f in FAMILIES
                            if (s.family == f).sum() >= 20)
            print(f"    {label:<26} stop {kk}x: n={len(s):>6,} win {np.mean(s[f'R{kk}'] > 0):5.1%} "
                  f"(random walk {geo:.0%}) | gross {s[f'R{kk}'].mean():+.3f} cost {s[f'cost{kk}'].mean():.3f} "
                  f"tie {s.tie.mean():.0%} dist {s.dist.median():.2f}x base "
                  f"| net {net.mean():+.3f} +- {net.std() / np.sqrt(len(s)):.3f} "
                  f"| halves {a_:+.3f} {b_:+.3f} | {fams}")


if __name__ == "__main__":
    for iv in ("15m", "1h"):
        study(iv)
