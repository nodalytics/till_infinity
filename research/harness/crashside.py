"""Crashes only: can anything tell a large move *down* from a large move up?

`spikerisk.py` found the volatility state lifts the odds of a large bar three to
five times - but its crash score and its spike score rank the same bars, which is
what a *size* signal does. A short needs the sign. Three questions, same series,
same 60/40 time split, same event (a bar beyond K x trailing baseline in the next H):

  A  direction   among windows that do contain a large bar, is the first one down?
                 A classifier on directional features, scored by AUC on the test 40%.
  B  short pays  the forward H-bar return, in baseline units, when the crash model
                 is in its top 5% - against every bar. Gross, before any spread.
  C  after onset once a large down bar has printed, does the next H bars keep falling?
                 Detection rather than prediction - the version a desk can act on.

Run from the repository root:  .venv-research/bin/python research/harness/crashside.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
from spikerisk import DAILY, DB, K, SERIES, SETUPS, load

DIRECTIONAL = ["mom5", "mom20", "drawdown", "rally", "downshare", "last", "short", "shock"]


def frame(df, seconds, horizon, long):
    df = df[df.close > 0].reset_index(drop=True)
    lc = np.log(df.close)
    r = lc.diff()
    if seconds < 86400:
        r[df.ts.diff() != seconds] = np.nan
    a = r.abs()
    base = a.rolling(long, min_periods=long // 2).mean()
    o = pd.DataFrame({"ts": df.ts})
    o["mom5"] = lc.diff(5) / (base * np.sqrt(5))
    o["mom20"] = lc.diff(20) / (base * np.sqrt(20))
    o["drawdown"] = (lc.rolling(50, min_periods=40).max() - lc) / base
    o["rally"] = (lc - lc.rolling(50, min_periods=40).min()) / base
    sq = r.pow(2)
    o["downshare"] = sq.where(r < 0, 0).rolling(20, min_periods=15).sum() / sq.rolling(20, min_periods=15).sum()
    o["last"] = r / base
    o["short"] = np.log(a.rolling(10, min_periods=8).mean() / base)
    o["shock"] = np.log(a.rolling(20, min_periods=15).max() / base)

    z = (r / base).to_numpy()
    n = len(z)
    first = np.full(n, np.nan)  # sign of the first large bar in (t, t+H], nan if none
    crash = np.full(n, np.nan)
    fwd = np.full(n, np.nan)
    for t in range(n - horizon):
        w = z[t + 1 : t + 1 + horizon]
        if np.isnan(w).all():
            continue
        crash[t] = float(np.nanmin(w) < -K)
        big = np.where(np.abs(np.nan_to_num(w)) > K)[0]
        if len(big):
            first[t] = float(w[big[0]] < 0)
        fwd[t] = (lc.iloc[t + horizon] - lc.iloc[t]) / base.iloc[t]
    o["first_down"], o["crash"], o["fwd"] = first, crash, fwd
    return o.dropna(subset=DIRECTIONAL + ["crash", "fwd"])


def run(interval, universe):
    seconds, horizon, long, _ = SETUPS[interval]
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    parts = []
    for family, pairs in universe.items():
        for ticker, venue in pairs:
            df = load(conn, ticker, venue, interval)
            if len(df) < long * 3:
                continue
            f = frame(df, seconds, horizon, long)
            f["test"] = np.arange(len(f)) >= int(len(f) * 0.6)
            f["family"], f["ticker"] = family, ticker
            parts.append(f)
    d = pd.concat(parts, ignore_index=True)
    X = d[DIRECTIONAL].to_numpy()
    tr, te = ~d.test.to_numpy(), d.test.to_numpy()
    print(f"\n=== {interval}: {d.ticker.nunique()} series, {len(d):,} bars, H={horizon}, K={K:g} ===")

    # A - direction, given a large bar is coming.
    ev = ~d.first_down.isna().to_numpy()
    y = d.first_down.to_numpy()
    m = LogisticRegression(max_iter=2000).fit(X[tr & ev], y[tr & ev])
    p = m.predict_proba(X[te & ev])[:, 1]
    yt = y[te & ev]
    print(f"A  direction of the first large bar: {int(ev[te].sum()):,} test windows, "
          f"{yt.mean():.1%} down, AUC {roc_auc_score(yt, p):.3f}")
    fam = d.family.to_numpy()[te & ev]
    for family in universe:
        k = fam == family
        if k.sum() >= 30 and 0 < yt[k].mean() < 1:
            print(f"   {family:>8} n={k.sum():>5}  down {yt[k].mean():5.1%}  AUC {roc_auc_score(yt[k], p[k]):.3f}")
    print("   coefficients: " + ", ".join(f"{c}={w:+.2f}" for c, w in zip(DIRECTIONAL, m.coef_[0])))

    # B - does shorting the crash model's top 5% pay, gross?
    yc = d.crash.to_numpy()
    mc = LogisticRegression(max_iter=2000).fit(X[tr], yc[tr])
    pc = mc.predict_proba(X[te])[:, 1]
    fw = d.fwd.to_numpy()[te]
    alarm = pc >= np.quantile(pc, 0.95)
    se = fw[alarm].std() / np.sqrt(alarm.sum())
    print(f"B  crash model top 5%: crash rate {yc[te][alarm].mean():.1%} vs {yc[te].mean():.1%};"
          f" fwd return {fw[alarm].mean():+.3f} +- {se:.3f} baseline units vs {fw.mean():+.3f};"
          f" down {np.mean(fw[alarm] < 0):.1%} vs {np.mean(fw < 0):.1%}")
    famt = d.family.to_numpy()[te]
    for family in universe:
        k = (famt == family) & alarm
        if k.sum() >= 30:
            print(f"   {family:>8} alarms={k.sum():>5}  short gross {-fw[k].mean():+.3f} +- "
                  f"{fw[k].std() / np.sqrt(k.sum()):.3f}  down {np.mean(fw[k] < 0):5.1%}")

    # C - after a large down bar has printed.
    onset = d["last"].to_numpy() < -K
    k = onset & te
    if k.sum() >= 10:
        f = d.fwd.to_numpy()[k]
        print(f"C  after a {K:g}x down bar ({k.sum()} test cases): next {horizon} bars {f.mean():+.3f} +- "
              f"{f.std() / np.sqrt(len(f)):.3f} baseline units, down {np.mean(f < 0):.1%}")
        up = (d["last"].to_numpy() > K) & te
        g = d.fwd.to_numpy()[up]
        print(f"   after a {K:g}x up bar ({up.sum()}):   next {horizon} bars {g.mean():+.3f} +- "
              f"{g.std() / np.sqrt(max(len(g), 1)):.3f}, down {np.mean(g < 0):.1%}")


if __name__ == "__main__":
    for interval in ("15m", "1h"):
        run(interval, SERIES)
    run("1d", DAILY)
