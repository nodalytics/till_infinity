"""Can ML say which of the envelope's bands price touches first, or whether it touches them at all?

The envelope (`structures/vol/envelope.py`) quotes P10 / P50 / P90 of the next N bars, corrected by
AgACI. Those are statements about where price *ends* N bars on. A trader cares about the path:
which band is touched first, and whether one is touched at all. This asks whether a model can
forecast that beyond what the bands' own geometry already says.

Bands: AgACI's online P10 / P50 / P90 of y = log(close[t+N] / close[t]) in units of the EWMA of
true range (the production unit), quoted at every bar from its own past only, as production would
quote them. As prices around the close: P = close * exp(Q * sig).

Targets, read off the next N bars' highs and lows:
  race       P90 touched before P10 (1), P10 before P90 (0); neither, or both in the same bar, is
             excluded from the binary. The three-way share (up / down / neither) is reported too.
  touch90    P90 touched at any time within N          touch10  the same for P10
  both       both touched within N (range expansion)
  after P50  having closed the first bar above (below) P50, the share that touch P90 (P10) first

Baselines the model must beat - the headline is skill over them, not raw AUC:
  race       gambler's ruin on the bar's own distances: p_up = d10 / (d90 + d10), in vol units.
             On a driftless walk this *is* the answer; beating it is a direction call
  touch      the training period's rate for that family and horizon, and the reflection principle
             P(max >= d) = 2 (1 - Phi(d / (s sqrt N))), s the per-bar sd of returns in vol units
  both       the training period's rate

Model: gradient boosting on the first 60% of each series by time, scored on the last 40%.
Features, all known at the bar's close: lvol, the unit's percentile in its last 500 bars, vol of
vol, r1 / r5 / r20 and the bar's range in vol units, the hour (sin, cos), hours to the weekend
close, and the bands themselves: d90, d10 and the asymmetry (P90 - P50) / (P50 - P10).

Scoring: AUC and Brier skill (1 - B / B_baseline) with 95% intervals from resampling whole days,
calibration by decile, both halves of the test period, per family - FX, metals, crypto and Deriv's
indices as markets - and two controls we generate:
  walks   iid Student-t(3), no clustering: the model should beat neither geometry nor the rate
  garch   GARCH(1,1) with t(4) shocks: volatility clusters, so touch skill *should* appear, and a
          race should not - the check that the harness can find skill where it exists

Race tradeability: where the model's p_up departs from geometry's by more than the training
period's 90th percentile of |p_model - p_geo|, trade toward the favoured band with the other as the
stop, exiting at N. Net R after costs (COST_V in 5-minute vol units, scaled by sqrt(5 / minutes)),
same-bar ties counted as stops. By the barrier theorem it is about -cost without real direction.

Pre-registered pass bars:
  race           Brier skill over geometry >= 0.01, CI above 0, both halves, not on the walks
  touch / both   AUC over the training rate >= 0.60 (the rate itself has AUC 0.5), calibrated
                 within +-20% in every decile, not on the iid walks

Run on the lab, one process per horizon:
  INTERVAL=15m N=20 SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/bandrace.py
"""
from __future__ import annotations

import math
import os
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

from conformal import BOA, GAMMAS, GROUPS, TARGETS

INTERVAL = os.environ.get("INTERVAL", "15m")
N = int(os.environ.get("N", "20"))
MINUTES = {"15m": 15, "1h": 60}[INTERVAL]
WINDOW = 1000  # production's history depth
WARM = 1200
COST_V = {"fx": 0.8, "metals": 0.16, "crypto": 0.5, "deriv": 0.15, "walks": 0.15, "garch": 0.15}
DERIV = ("volatility", "boom/crash", "range break")
FEATURES = ["lvol", "tr_pct", "vov", "r1", "r5", "r20", "rng", "hsin", "hcos", "to_weekend",
            "d90", "d10", "asym"]
SIM_SERIES, SIM_BARS = 6, 60_000


# ---------------------------------------------------------------------------------------- the bars


def sim(kind: str, seed: int) -> pd.DataFrame:
    """Our controls, with coherent highs and lows from eight sub-steps per bar."""
    rng = np.random.default_rng(seed)
    sub = 8
    n = SIM_BARS * sub
    if kind == "walks":
        steps = rng.standard_t(3, n) * 0.001 / math.sqrt(sub)
    else:
        z = rng.standard_t(4, SIM_BARS) / math.sqrt(2.0)
        var, sig = np.empty(SIM_BARS), 1e-6
        omega, alpha, beta = 1e-6 * 0.02, 0.08, 0.90
        for i in range(SIM_BARS):
            var[i] = sig
            sig = omega + alpha * (z[i] ** 2) * sig + beta * sig
        per_bar = np.sqrt(var) / math.sqrt(sub)
        steps = np.repeat(per_bar, sub) * rng.standard_t(4, n) / math.sqrt(2.0)
    path = 100 * np.exp(np.cumsum(steps)).reshape(SIM_BARS, sub)
    opens = np.r_[100.0, path[:-1, -1]]
    return pd.DataFrame({
        "ts": (1_700_000_000 + MINUTES * 60 * np.arange(SIM_BARS)).astype(np.int64),
        "open": opens, "high": np.maximum(path.max(axis=1), opens),
        "low": np.minimum(path.min(axis=1), opens), "close": path[:, -1],
    })


def frame(df: pd.DataFrame) -> pd.DataFrame:
    """Features at each bar's close, in the production unit, plus the log path for the labels."""
    o, h, lo, c = (np.log(df[k].to_numpy(float)) for k in ("open", "high", "low", "close"))
    prev = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.column_stack([h - lo, np.abs(h - prev), np.abs(lo - prev)]), axis=1)
    sig = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    long = pd.Series(tr).rolling(500, min_periods=250).mean().to_numpy()
    s = pd.Series(sig)
    t = pd.to_datetime(df["ts"].to_numpy(), unit="s")
    hour = t.hour + t.minute / 60
    week_hour = (df["ts"].to_numpy() / 3600 + 72) % 168
    d = pd.DataFrame({
        "ts": df["ts"].to_numpy(), "c": c, "h": h, "lo": lo, "sig": sig,
        "lvol": np.log(sig / long),
        "tr_pct": s.rolling(500, min_periods=250).rank(pct=True).to_numpy(),
        "vov": pd.Series(np.log(sig)).rolling(50, min_periods=25).std().to_numpy(),
        "r1": np.r_[np.nan, np.diff(c)] / sig,
        "r5": (c - np.r_[np.full(5, np.nan), c[:-5]]) / sig,
        "r20": (c - np.r_[np.full(20, np.nan), c[:-20]]) / sig,
        "rng": (h - lo) / sig,
        "hsin": np.sin(2 * np.pi * hour / 24), "hcos": np.cos(2 * np.pi * hour / 24),
        "to_weekend": (4 * 24 + 21 - week_hour) % 168,
    })
    d["y"] = np.r_[c[N:] - c[:-N], np.full(N, np.nan)] / sig
    return d


# ---------------------------------------------------------------------------------------- the bands


def bands(d: pd.DataFrame) -> np.ndarray:
    """AgACI's P10 / P50 / P90 of y at every bar, from its own past only (feedback N bars late)."""
    y = d["y"].to_numpy()
    out = np.full((len(d), 3), np.nan)
    experts = {q: np.full(len(GAMMAS), q) for q in TARGETS}
    agg = {q: BOA(len(GAMMAS)) for q in TARGETS}
    hist: deque = deque(maxlen=WINDOW)
    sorted_y = None
    g = np.array(GAMMAS)
    quotes: dict[int, tuple] = {}
    for i in range(len(d)):
        # y[i - N] is known now: it enters the history, and teaches whatever quoted it.
        j = i - N
        if j >= 0 and np.isfinite(y[j]):
            hist.append(y[j])
            made = quotes.pop(j, None)
            if made is not None:
                eqs, Qs = made
                for k, q in enumerate(TARGETS):
                    experts[q] = np.clip(experts[q] + g * (q - (y[j] <= eqs[k])), 0.002, 0.998)
                    agg[q].update(eqs[k], Qs[k], y[j], q)
        quotes.pop(j, None)
        if len(hist) < 200:
            continue
        if sorted_y is None or i % 10 == 0:
            sorted_y = np.sort(np.fromiter(hist, float))
        n = len(sorted_y)
        eqs, Qs = [], []
        for q in TARGETS:
            eq = sorted_y[np.rint(experts[q] * (n - 1)).astype(int)]
            eqs.append(eq)
            Qs.append(float(np.median(eq)) if q == 0.5 else float(agg[q].weights() @ eq))
        out[i] = Qs
        quotes[i] = (eqs, Qs)
    return out


def labels(d: pd.DataFrame, Q: np.ndarray) -> pd.DataFrame:
    """First-touch and touch labels over the next N bars, bands as log prices around the close."""
    c, h, lo, sig = (d[k].to_numpy() for k in ("c", "h", "lo", "sig"))
    T = len(d)
    up = c + Q[:, 2] * sig
    mid = c + Q[:, 1] * sig
    dn = c + Q[:, 0] * sig
    t_up = np.full(T, np.inf)
    t_dn = np.full(T, np.inf)
    for j in range(1, N + 1):
        hh = np.r_[h[j:], np.full(j, np.nan)]
        ll = np.r_[lo[j:], np.full(j, np.nan)]
        t_up = np.where(np.isinf(t_up) & (hh >= up), j, t_up)
        t_dn = np.where(np.isinf(t_dn) & (ll <= dn), j, t_dn)
    valid = np.arange(T) < T - N
    first_close = np.r_[c[1:], np.nan]
    out = pd.DataFrame({
        "touch90": (t_up <= N).astype(float), "touch10": (t_dn <= N).astype(float),
        "race": np.where(t_up < t_dn, 1.0, np.where(t_dn < t_up, 0.0, np.nan)),
        "tie": ((t_up == t_dn) & np.isfinite(t_up)).astype(float),
        "t_up": t_up, "t_dn": t_dn,
        "above50": np.where(first_close > mid, 1.0, np.where(first_close < mid, 0.0, np.nan)),
        "exit": np.r_[c[N:] - c[:-N], np.full(N, np.nan)] / sig,
    })
    out["both"] = out["touch90"] * out["touch10"]
    out.loc[~valid, :] = np.nan
    return out


def build(df: pd.DataFrame, family: str, key: str) -> pd.DataFrame:
    d = frame(df)
    Q = bands(d)
    lab = labels(d, Q)
    d["q10"], d["q50"], d["q90"] = Q[:, 0], Q[:, 1], Q[:, 2]
    d["d90"], d["d10"] = Q[:, 2], -Q[:, 0]
    d["asym"] = (Q[:, 2] - Q[:, 1]) / (Q[:, 1] - Q[:, 0])
    d = pd.concat([d, lab], axis=1)
    d["family"], d["key"] = family, key
    d["pos"] = np.arange(len(d)) / len(d)
    d = d.iloc[WARM:]
    return d[np.isfinite(d["d90"]) & (d["d90"] > 0) & (d["d10"] > 0) & np.isfinite(d["touch90"])]


# ---------------------------------------------------------------------------------------- scoring


def boot(fn, days: np.ndarray, n: int = 300, seed: int = 0):
    """95% interval of fn(index) resampling whole days."""
    uniq = np.unique(days)
    idx = {u: np.flatnonzero(days == u) for u in uniq}
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        pick = np.concatenate([idx[u] for u in rng.choice(uniq, len(uniq))])
        vals.append(fn(pick))
    return np.nanquantile(vals, [0.025, 0.975])


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def bss(p, base, y):
    return 1 - brier(p, y) / brier(base, y)


def calib(p, y):
    """Worst |realised / predicted - 1| over deciles of the prediction."""
    edges = np.quantile(p, np.linspace(0, 1, 11))
    worst = 0.0
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        m = (p >= a) & (p <= b)
        if m.sum() > 30 and p[m].mean() > 0:
            worst = max(worst, abs(y[m].mean() / p[m].mean() - 1))
    return worst


def fit(tr: pd.DataFrame, target: str):
    tr = tr[np.isfinite(tr[target])]
    if len(tr) > 400_000:
        tr = tr.sample(400_000, random_state=0)
    model = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05,
                                           min_samples_leaf=300)
    model.fit(tr[FEATURES].fillna(0.0), tr[target])
    return model


def score(name: str, d: pd.DataFrame) -> None:
    tr, te = d[d["pos"] < 0.6], d[d["pos"] >= 0.6].copy()
    if len(te) < 2000:
        return
    te["day"] = (te["ts"] // 86_400).astype(int)
    half = te["pos"] < te["pos"].median()
    s1 = np.nanstd(tr["r1"].to_numpy())
    print(f"\n  {name}: {len(d):,} bars, test {len(te):,}", flush=True)
    three = te[["race", "t_up"]]
    up = np.mean(three["race"] == 1)
    down = np.mean(three["race"] == 0)
    print(f"    race three-way: P90 first {up:.1%} · P10 first {down:.1%} · neither or same bar "
          f"{1 - up - down:.1%} | touch90 {te['touch90'].mean():.1%} touch10 {te['touch10'].mean():.1%}"
          f" both {te['both'].mean():.1%}")

    # race against gambler's ruin
    tr = tr.assign(geo=tr["d10"] / (tr["d90"] + tr["d10"]))
    te["geo"] = te["d10"] / (te["d90"] + te["d10"])
    m = fit(tr, "race")
    r = te[np.isfinite(te["race"])].copy()
    r["p"] = m.predict_proba(r[FEATURES].fillna(0.0))[:, 1]
    y, p, g = r["race"].to_numpy(), r["p"].to_numpy(), r["geo"].to_numpy()
    days = r["day"].to_numpy()
    lo_hi = boot(lambda ix: bss(p[ix], g[ix], y[ix]), days)
    halves = [bss(p[mk], g[mk], y[mk]) for mk in (half[r.index].to_numpy(), ~half[r.index].to_numpy())]
    print(f"    race    n={len(r):,} up-first {y.mean():.3f} geo {g.mean():.3f} | AUC model "
          f"{roc_auc_score(y, p):.3f} geo {roc_auc_score(y, g):.3f} | Brier skill over geometry "
          f"{bss(p, g, y):+.4f} [{lo_hi[0]:+.4f}, {lo_hi[1]:+.4f}] halves {halves[0]:+.4f} / "
          f"{halves[1]:+.4f} | calib worst {calib(p, y):.0%}")
    for side in (1.0, 0.0):
        mk = r["above50"] == side
        if mk.sum() > 100:
            print(f"      after closing {'above' if side else 'below'} P50 first: P90 first "
                  f"{r.loc[mk, 'race'].mean():.3f} (geo {r.loc[mk, 'geo'].mean():.3f}, n={int(mk.sum()):,})")

    # race as a trade
    trp = m.predict_proba(tr[FEATURES].fillna(0.0))[:, 1]
    q = np.nanquantile(np.abs(trp - tr["geo"].to_numpy()), 0.9)
    edge = p - g
    go = np.abs(edge) > q
    cost = COST_V.get(r["family"].iloc[0], 0.5) * math.sqrt(5 / MINUTES)
    net = []
    for (_, row), e in zip(r[go].iterrows(), edge[go], strict=True):
        long = e > 0
        target_d, stop_d = (row["d90"], row["d10"]) if long else (row["d10"], row["d90"])
        t_target, t_stop = (row["t_up"], row["t_dn"]) if long else (row["t_dn"], row["t_up"])
        if t_stop <= t_target and np.isfinite(t_stop):
            got = -1.0
        elif np.isfinite(t_target):
            got = target_d / stop_d
        else:
            got = (row["exit"] if long else -row["exit"]) / stop_d
        net.append(got - cost / stop_d)
    net = np.array(net)
    if len(net) > 30:
        nd = r[go]["day"].to_numpy()
        sums = pd.Series(net - net.mean()).groupby(nd).sum()
        se = np.sqrt((sums**2).sum()) / len(net)
        hh = half[r[go].index].to_numpy()
        print(f"    race trade: n={len(net):,} ({go.mean():.1%} of races) net R {net.mean():+.3f} "
              f"(t {net.mean() / se:+.1f}) halves {net[hh].mean():+.3f} / {net[~hh].mean():+.3f}")

    # touch and both against the training rate (and reflection for touch)
    for target, dist in (("touch90", "d90"), ("touch10", "d10"), ("both", None)):
        mm = fit(tr, target)
        yy = te[target].to_numpy()
        pp = mm.predict_proba(te[FEATURES].fillna(0.0))[:, 1]
        rate = np.full(len(te), tr[target].mean())
        parts = [f"    {target:7s} rate {yy.mean():.3f} (train {rate[0]:.3f}) | AUC {roc_auc_score(yy, pp):.3f}"]
        dd = te["day"].to_numpy()
        ci = boot(lambda ix, pp=pp, yy=yy: roc_auc_score(yy[ix], pp[ix]), dd, n=150)
        parts.append(f"[{ci[0]:.3f}, {ci[1]:.3f}]")
        hs = [roc_auc_score(yy[mk], pp[mk]) for mk in (half.to_numpy(), ~half.to_numpy())]
        parts.append(f"halves {hs[0]:.3f} / {hs[1]:.3f} | BSS vs rate {bss(pp, rate, yy):+.4f}")
        if dist:
            refl = np.clip(2 * (1 - _phi(te[dist].to_numpy() / (s1 * math.sqrt(N)))), 0, 1)
            parts.append(f"vs reflection {bss(pp, refl, yy):+.4f} (reflection AUC {roc_auc_score(yy, refl):.3f})")
        parts.append(f"calib worst {calib(pp, yy):.0%}")
        print(" ".join(parts), flush=True)


def _phi(x):
    from scipy.stats import norm

    return norm.cdf(x)


def main():
    print(f"BAND RACE {INTERVAL}, N = {N}; AgACI bands; train first 60%, test last 40%", flush=True)
    groups = dict(GROUPS)
    for name, syms in groups.items():
        family = "deriv" if name in DERIV else name
        frames = []
        for s in syms:
            try:
                df = spikerisk.load(None, s, "SEQLAB", INTERVAL)
            except (ValueError, FileNotFoundError):
                continue
            frames.append(build(df, family, s))
            print(f"    built {s}: {len(frames[-1]):,}", flush=True)
        if frames:
            score(f"{name}{' (Deriv, a market)' if family == 'deriv' else ''}", pd.concat(frames, ignore_index=True))
    for kind in ("walks", "garch"):
        frames = [build(sim(kind, 100 + i), kind, f"{kind}{i}") for i in range(SIM_SERIES)]
        score(f"{kind} (control we generate)", pd.concat(frames, ignore_index=True))


if __name__ == "__main__":
    main()
