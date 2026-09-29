"""Anomalies before they happen: can the desk see a shock, a blowout or a gap coming, and how early?

Production's anomaly detection (`structures/learning/anomaly.py`) flags cross-venue dislocations as
they happen: a venue off consensus, a spread blowing out, a quote gone stale. Nothing forecasts
them. This asks whether anomalies are visible before they arrive.

Anomalies, per bar, each against the series' own trailing history (causal):
  shock    |return| > 4x the trailing 500-bar mean |return|
  range    high - low > 4x the trailing mean range
  spread   the bar's broker spread > 3x its trailing 500-bar median (FX and metals quote it; BTC's is
           fixed and cannot blow out)
  gap      |open - previous close| > 3x the trailing mean |return|
Target: any anomaly of that kind in the next 4 bars. The lead-time curve moves the window further
out - bars 1-4, 5-8, 9-12, 17-20 - to show how early any warning is.

Features known at the bar's close:
  vol       the 14-bar EWMA of true range over its 500-bar mean (log), its percentile in 1,500 bars
            (production's tr_percentile), and the volatility of volatility over 50 bars
  spread    spread over its 500-bar median, and its 5-bar over 50-bar mean (creep)
  history   anomalies of each kind in the last 20 and 100 bars (do they cluster?)
  calendar  bars until the next medium/high-importance release for either currency, bars since the
            last (FX and metals; crypto takes USD's), hour, weekday, hours to Friday 21:00 UTC
Models: each feature alone (AUC), and gradient boosting on all of them, fit on each family's first 60%
by time and scored on the last 40%: AUC, top-decile lift, both halves of the test.
Controls: the Deriv families whose shocks are published as memoryless (Boom, Crash, Jump) and the
Volatility indices (no clustering at all) - price anomalies there should be unpredictable.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import FAMILIES

CAL = Path(os.environ.get("CALENDAR", ".data/surprise/calendar.jsonl"))
KINDS = ("shock", "range", "spread", "gap")
WINDOWS = {"1-4": (1, 4), "5-8": (5, 8), "9-12": (9, 12), "17-20": (17, 20)}
GROUPS = {
    "fx": FAMILIES["fx"], "metals": FAMILIES["metal"], "crypto": FAMILIES["crypto"],
    "boom/crash (control)": ["Boom_500_Index", "Boom_1000_Index", "Crash_500_Index", "Crash_1000_Index"],
    "jump (control)": ["Jump_10_Index", "Jump_50_Index", "Jump_100_Index"],
    "volatility (control)": ["Volatility_25_Index", "Volatility_75_Index", "Volatility_100_Index"],
}
CCY = {"XAUUSD": ("USD",), "XAGUSD": ("USD",), "BTCUSD": ("USD",), "ETHUSD": ("USD",), "SOLUSD": ("USD",)}


def releases():
    if not CAL.exists():
        return {}
    d = pd.DataFrame([json.loads(x) for x in CAL.open()])
    d = d[(d["importance"] >= 0) & d["currency"].notna()]
    t = pd.to_datetime(d["date"], utc=True).astype("int64") // 10**9
    return {c: np.sort(t[d["currency"] == c].to_numpy()) for c in d["currency"].unique()}


def frame(sym, interval, cal):
    df = spikerisk.load(None, sym, "SEQLAB", interval)
    ts = df["ts"].to_numpy().astype(np.int64)
    o, h, l, c = (np.log(df[k].to_numpy()) for k in ("open", "high", "low", "close"))
    sp = df["spread"].to_numpy().astype(float) if "spread" in df else np.full(len(c), np.nan)
    r = np.diff(c, prepend=np.nan)
    prev = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.column_stack([h - l, np.abs(h - prev), np.abs(l - prev)]), axis=1)
    mabs = pd.Series(np.abs(r)).shift(1).rolling(500, min_periods=250).mean().to_numpy()
    mrng = pd.Series(h - l).shift(1).rolling(500, min_periods=250).mean().to_numpy()
    msp = pd.Series(sp).shift(1).rolling(500, min_periods=250).median().to_numpy()
    an = {
        "shock": np.abs(r) > 4 * mabs,
        "range": (h - l) > 4 * mrng,
        "spread": (sp > 3 * msp) & (msp > 0),
        "gap": np.abs(o - prev) > 3 * mabs,
    }
    ew = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean()
    d = pd.DataFrame({
        "lvol": np.log(ew / pd.Series(tr).rolling(500, min_periods=250).mean()).to_numpy(),
        "trpct": ew.rolling(1500, min_periods=300).rank(pct=True).to_numpy(),
        "volvol": pd.Series(np.log(tr + 1e-12)).rolling(50).std().to_numpy(),
        "spr": sp / msp, "creep": (pd.Series(sp).rolling(5).mean() / pd.Series(sp).rolling(50).mean()).to_numpy(),
        "hour": pd.to_datetime(ts, unit="s").hour, "dow": pd.to_datetime(ts, unit="s").dayofweek,
    })
    # hours to Friday 21:00 UTC (FX's weekly close)
    dt = pd.to_datetime(ts, unit="s")
    to_fri = ((4 - dt.dayofweek) % 7) * 24 + (21 - dt.hour)
    d["to_weekend"] = np.where(to_fri < 0, to_fri + 168, to_fri)
    # release proximity, in bars, for either currency of the pair
    secs = {"15m": 900, "1h": 3600}[interval]
    ccys = CCY.get(sym, (sym[:3], sym[3:]) if len(sym) == 6 and sym.isupper() else ())
    times = np.sort(np.concatenate([cal[x] for x in ccys if x in cal])) if ccys and cal else np.array([], np.int64)
    close_t = ts + secs
    if len(times):
        j = np.searchsorted(times, close_t, side="right")
        nxt = np.where(j < len(times), times[np.minimum(j, len(times) - 1)], close_t + 10**7)
        lst = np.where(j > 0, times[np.maximum(j - 1, 0)], close_t - 10**7)
        d["to_release"] = np.minimum((nxt - close_t) / secs, 200)
        d["since_release"] = np.minimum((close_t - lst) / secs, 200)
    else:
        d["to_release"], d["since_release"] = 200.0, 200.0
    for k, v in an.items():
        s = pd.Series(v.astype(float))
        d[f"n20_{k}"] = s.rolling(20).sum().to_numpy()
        d[f"n100_{k}"] = s.rolling(100).sum().to_numpy()
        for w, (a, b) in WINDOWS.items():
            fut = np.zeros(len(v), bool)
            for j in range(a, b + 1):
                fut |= np.r_[v[j:], np.zeros(j, bool)]
            fut[len(v) - b:] = False
            d[f"y_{k}_{w}"] = fut
        d[f"is_{k}"] = v
    d["sym"], d["t"] = sym, np.arange(len(d))
    d["test"] = d["t"] >= 0.6 * len(d)
    d["half"] = d["t"] >= 0.8 * len(d)
    d = d.iloc[1500:len(d) - 21]
    return d.dropna(subset=["lvol", "trpct", "volvol"])


FEATS = ["lvol", "trpct", "volvol", "spr", "creep", "hour", "dow", "to_weekend", "to_release", "since_release"] + \
        [f"n{w}_{k}" for w in (20, 100) for k in KINDS]


def main():
    cal = releases()
    for interval in os.environ.get("INTERVALS", "15m,1h").split(","):
        print(f"\n{'=' * 120}\nANOMALIES BEFORE THEY HAPPEN - {interval}; target: an anomaly in the next bars (window); "
              "fit on the first 60%, scored on the last 40%")
        for name, syms in GROUPS.items():
            frames = []
            for s in syms:
                try:
                    frames.append(frame(s, interval, cal))
                except (ValueError, FileNotFoundError, KeyError) as exc:
                    print(f"  skip {s}: {str(exc)[:60]}")
            if not frames:
                continue
            d = pd.concat(frames, ignore_index=True)
            tr, te = ~d["test"].to_numpy(), d["test"].to_numpy()
            X = d[FEATS].fillna(-1).to_numpy()
            print(f"\n  {name}: {len(d):,} bars; anomaly rates per bar: " +
                  ", ".join(f"{k} {d[f'is_{k}'].mean():.2%}" for k in KINDS))
            for k in KINDS:
                y = d[f"y_{k}_1-4"].to_numpy()
                if y[tr].mean() < 0.002 or y[te].mean() < 0.002:
                    print(f"    {k:<6} too rare to score")
                    continue
                # single features, test block
                singles = []
                for f in ("lvol", "trpct", "volvol", "spr", "creep", f"n100_{k}", "to_release", "to_weekend"):
                    x = d[f].fillna(-1).to_numpy()[te]
                    if np.std(x) > 0:
                        a = roc_auc_score(y[te], x)
                        singles.append((max(a, 1 - a), f, a))
                singles.sort(reverse=True)
                best = ", ".join(f"{f} {a:.3f}" for _, f, a in singles[:3])
                fit = np.random.default_rng(0).choice(np.flatnonzero(tr), min(400_000, tr.sum()), replace=False)
                g = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05,
                                                   min_samples_leaf=300).fit(X[fit], y[fit])
                p = g.predict_proba(X)[:, 1]
                auc = roc_auc_score(y[te], p[te])
                top = te & (p >= np.quantile(p[tr], 0.9))
                lift = y[top].mean() / max(y[te].mean(), 1e-9)
                h = [roc_auc_score(y[te & (d['half'] == v)], p[te & (d['half'] == v)]) for v in (False, True)]
                curve = []
                for w in WINDOWS:
                    yw = d[f"y_{k}_{w}"].to_numpy()
                    gw = HistGradientBoostingClassifier(max_depth=4, max_iter=150, learning_rate=0.05,
                                                        min_samples_leaf=300).fit(X[fit], yw[fit])
                    curve.append(f"{w} {roc_auc_score(yw[te], gw.predict_proba(X[te])[:, 1]):.3f}")
                print(f"    {k:<6} base {y[te].mean():.2%} | GBM AUC {auc:.3f} (halves {h[0]:.3f}/{h[1]:.3f}), top decile "
                      f"{y[top].mean():.1%} = {lift:.1f}x | lead time {' '.join(curve)} | best single: {best}")


if __name__ == "__main__":
    main()
