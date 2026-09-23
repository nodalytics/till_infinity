"""Crash and rally models on a wide feature set - technicals and borrowed fields.

`crashside.py` found the volatility state tells you a large bar is coming and
almost nothing about its sign. This asks whether a much wider net does better,
with one model per side:

  crash  some bar in the next H closes below -K x trailing baseline   (short)
  rally  some bar in the next H closes above +K x trailing baseline   (long)

and the question that separates a direction signal from a size signal: among
windows holding a large bar, does the crash score rank the down ones above the
up ones? A model that has only learned "volatile" scores ~0.50 there however
well it predicts its own target.

Features, all trailing and dimensionless (baseline = trailing mean |r|):

  technical  zscore20, rsi14, mom5/20/60, macd, stoch14, bbwidth, fatigue (run of
             same-sign closes), swing extension, bars since the swing began, and an
             impulse count - consecutive zigzag legs making new extremes, the
             mechanical part of an Elliott count (a 5th leg is the "wave 5" claim)
  vol        short, shock, downshare (downside semivariance share), skew100, kurt100
  climate    critical slowing down: lag-1 autocorrelation over 100 bars and its
             50-bar change, and the variance trend - early-warning signals of a
             tipping point
  info       permutation entropy (order 3, 60 bars) - how orderly the path is
  fractal    variance ratio VR(4) as a Hurst proxy, Katz fractal dimension
  physics    super-exponential growth: the quadratic coefficient of log price over
             100 bars - the core of Sornette's LPPL bubble signature, without the
             log-periodic fit
  seismology Hawkes/Omori intensity: exponentially decayed counts of past large
             down and up bars - aftershocks
  contagion  the rest of the universe at the same timestamp: mean |r| and share
             of series printing a large bar in the last 4
  calendar   hour and weekday on the circle (intraday only)

Scored on the last 40% of each series by time, models fit on the first 60%.
The trade check uses non-overlapping bars only (every H-th), because an overlapping
H-bar forward return counts one move H times and shrinks every standard error.

Run from the repository root:  .venv-research/bin/python research/harness/crashlab.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
from spikerisk import DAILY, DB, K, SERIES, SETUPS, load


def rolling_apply(x, window, fn):
    return pd.Series(x).rolling(window, min_periods=window).apply(fn, raw=True).to_numpy()


def perm_entropy(r, window=60):
    """Order-3 permutation entropy, normalised to [0, 1]."""
    a, b, c = r.shift(2), r.shift(1), r
    code = (a > b).astype(int) * 4 + (b > c).astype(int) * 2 + (a > c).astype(int)
    code[r.isna() | a.isna()] = -1
    counts = [(code == k).astype(float).rolling(window, min_periods=window).sum() for k in range(8)]
    tot = sum(counts)
    h = sum(-(n / tot) * np.log(np.where(n > 0, n / tot, 1)) for n in counts)
    return h / np.log(6)


def zigzag(lc, thr):
    """Swing features from a zigzag at `thr` log units (a per-bar array)."""
    n = len(lc)
    ext = np.full(n, np.nan)      # current swing's travel from its pivot, baseline units later
    age = np.full(n, np.nan)      # bars since the swing's pivot
    impulse = np.full(n, np.nan)  # signed count of consecutive legs making new extremes
    if n == 0:
        return ext, age, impulse
    direction, pivot_i, pivot = 0, 0, lc[0]
    hi_i, lo_i = 0, 0
    legs = []  # (direction, end price)
    run = 0
    for t in range(1, n):
        p = lc[t]
        if np.isnan(p) or np.isnan(thr[t]):
            continue
        if direction >= 0:
            if p > lc[hi_i]:
                hi_i = t
            if lc[hi_i] - p > thr[t] and (direction == 1 or t > hi_i):
                legs.append((1, lc[hi_i]))
                direction, pivot_i, lo_i = -1, hi_i, t
        if direction <= 0:
            if p < lc[lo_i]:
                lo_i = t
            if p - lc[lo_i] > thr[t] and (direction == -1 or t > lo_i):
                legs.append((-1, lc[lo_i]))
                direction, pivot_i, hi_i = 1, lo_i, t
        if len(legs) >= 3 and legs[-1][0] == legs[-3][0]:
            d, e = legs[-1]
            better = (e > legs[-3][1]) if d == 1 else (e < legs[-3][1])
            run = run + 1 if better and np.sign(run) in (0, d) else (d if better else 0)
            legs = legs[-3:]
        ext[t] = lc[t] - lc[pivot_i]
        age[t] = t - pivot_i
        impulse[t] = run
    return ext, age, impulse


def features(df, seconds, long, season):
    df = df[df.close > 0].reset_index(drop=True)
    for c in ("open", "high", "low"):  # a close-only series (a pair ratio) has no bar
        if c not in df:
            df[c] = df.close
    lc = np.log(df.close)
    r = lc.diff()
    if seconds < 86400:
        r[df.ts.diff() != seconds] = np.nan
    a = r.abs()
    base = a.rolling(long, min_periods=long // 2).mean()
    z = r / base
    o = pd.DataFrame({"ts": df.ts})
    # technical
    ma, sd = lc.rolling(20).mean(), lc.rolling(20).std()
    o["zscore20"] = (lc - ma) / sd
    up, dn = r.clip(lower=0), (-r).clip(lower=0)
    o["rsi14"] = 100 - 100 / (1 + up.ewm(alpha=1 / 14).mean() / dn.ewm(alpha=1 / 14).mean())
    for w in (5, 20, 60):
        o[f"mom{w}"] = lc.diff(w) / (base * np.sqrt(w))
    o["macd"] = (lc.ewm(span=12).mean() - lc.ewm(span=26).mean()) / base
    hi, lo = np.log(df.high).rolling(14).max(), np.log(df.low).rolling(14).min()
    o["stoch14"] = (lc - lo) / (hi - lo)
    o["bbwidth"] = np.log(sd / base)
    sign = np.sign(r.fillna(0))
    grp = (sign != sign.shift()).cumsum()
    o["fatigue"] = sign * sign.groupby(grp).cumcount().add(1)
    ext, age, impulse = zigzag(lc.to_numpy(), (3 * base).to_numpy())
    o["swing_ext"] = ext / base
    o["swing_age"] = np.log1p(age)
    o["impulse"] = impulse
    # vol
    o["short"] = np.log(a.rolling(10).mean() / base)
    o["shock"] = np.log(a.rolling(20).max() / base)
    sq = r.pow(2)
    o["downshare"] = sq.where(r < 0, 0).rolling(20).sum() / sq.rolling(20).sum()
    o["skew100"] = r.rolling(100, min_periods=80).skew()
    o["kurt100"] = np.log1p(r.rolling(100, min_periods=80).kurt().clip(lower=-0.99))
    # climate: critical slowing down
    o["ac1"] = r.rolling(100, min_periods=80).corr(r.shift(1))
    o["ac1_trend"] = o["ac1"].diff(50)
    o["var_trend"] = np.log(sq.rolling(50).mean() / sq.shift(50).rolling(50).mean())
    # information
    o["perm_ent"] = perm_entropy(r)
    # fractal
    r4 = lc.diff(4)
    o["vr4"] = np.log(r4.rolling(200, min_periods=150).var() / (4 * r.rolling(200, min_periods=150).var()))
    path = a.rolling(50).sum()
    span = lc.rolling(50).max() - lc.rolling(50).min()
    o["katz"] = np.log10(50) / (np.log10(50) + np.log10(span / path))
    # physics: super-exponential curvature over 100 bars
    x = np.arange(100) - 49.5
    x2 = x**2 - (x**2).mean()
    o["superexp"] = lc.rolling(100).apply(lambda y: (x2 @ y) / (x2 @ x2), raw=True) * 100**2 / (base * 10)
    # seismology: Hawkes / Omori intensity, half-life 10 bars
    decay = 0.5 ** (1 / 10)
    o["hawkes_dn"] = (z < -3).astype(float).ewm(alpha=1 - decay, adjust=False).mean()
    o["hawkes_up"] = (z > 3).astype(float).ewm(alpha=1 - decay, adjust=False).mean()
    if season:
        t = pd.to_datetime(df.ts, unit="s")
        h = t.dt.hour + t.dt.minute / 60
        o["hour_s"], o["hour_c"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
        o["dow_s"], o["dow_c"] = np.sin(2 * np.pi * t.dt.dayofweek / 7), np.cos(2 * np.pi * t.dt.dayofweek / 7)
    # bar shape: what the close alone throws away
    lo_, hi_, op = np.log(df.low), np.log(df.high), np.log(df.open)
    rng = (hi_ - lo_).replace(0, np.nan)
    body_top, body_bot = np.maximum(op, lc), np.minimum(op, lc)
    o["range"] = np.log((hi_ - lo_).rolling(10).mean() / base)            # Parkinson-style scale
    rs = (hi_ - lc) * (hi_ - op) + (lo_ - lc) * (lo_ - op)                 # Rogers-Satchell
    o["rs_vol"] = np.log(np.sqrt(rs.clip(lower=0).rolling(10).mean()) / base)
    o["range_last"] = (hi_ - lo_) / base
    o["upwick"] = ((hi_ - body_top) / rng).rolling(10, min_periods=5).mean()
    o["dnwick"] = ((body_bot - lo_) / rng).rolling(10, min_periods=5).mean()
    o["wick_skew"] = o["dnwick"] - o["upwick"]                             # rejection of lows vs highs
    o["clv"] = ((lc - lo_) - (hi_ - lc)) / rng                             # close location in the bar
    o["clv5"] = o["clv"].rolling(5, min_periods=3).mean()
    o["body"] = ((lc - op) / rng).rolling(5, min_periods=3).mean()
    o["gap"] = (op - lc.shift(1)) / base
    if (df.high == df.low).all():  # a close-only series (a pair ratio) has no bar to describe
        o[["range", "rs_vol", "range_last", "upwick", "dnwick", "wick_skew", "clv", "clv5", "body", "gap"]] = np.nan
    o["_z"], o["_absz"] = z, z.abs()
    o["_lc"], o["_base"] = lc, base
    o["_op"], o["_hi"], o["_lo"] = op, hi_, lo_
    o["_volume"] = df["volume"].where(df["volume"] > 0) if "volume" in df else np.nan
    return o.replace([np.inf, -np.inf], np.nan)


def targets(o, horizon):
    z = o["_z"]
    rev = lambda s: s[::-1].rolling(horizon, min_periods=1).agg("min" if s.name == "lo" else "max")[::-1].shift(-1)
    lo = rev(z.rename("lo"))
    hi = rev(z.rename("hi"))
    o["crash"] = (lo < -K).astype(float)
    o["rally"] = (hi > K).astype(float)
    o["fwd"] = (o["_lc"].shift(-horizon) - o["_lc"]) / o["_base"]
    o.loc[o.index[-horizon:], ["crash", "rally", "fwd"]] = np.nan
    return o


def build(interval, universe):
    seconds, horizon, long, season = SETUPS[interval]
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    parts = []
    for family, pairs in universe.items():
        for ticker, venue in pairs:
            df = load(conn, ticker, venue, interval)
            if len(df) < long * 3:
                continue
            o = targets(features(df, seconds, long, season), horizon)
            o["family"], o["ticker"] = family, ticker
            parts.append(o)
    d = pd.concat(parts, ignore_index=True)
    # contagion: everyone else at this timestamp
    big = (d["_absz"] > K).astype(float)
    d["_big4"] = big.groupby(d.ticker).transform(lambda s: s.rolling(4, min_periods=1).max())
    g = d.groupby("ts")
    n = g["_absz"].transform("count")
    d["cx_absz"] = (g["_absz"].transform("sum") - d["_absz"].fillna(0)) / (n - 1).clip(lower=1)
    d["cx_big4"] = (g["_big4"].transform("sum") - d["_big4"]) / (n - 1).clip(lower=1)
    d.loc[n < 3, ["cx_absz", "cx_big4"]] = np.nan
    cols = [c for c in d.columns if not c.startswith("_") and c not in
            ("ts", "family", "ticker", "crash", "rally", "fwd")]
    d = d.dropna(subset=["crash", "rally", "fwd", "_base"]).reset_index(drop=True)
    d["test"] = d.groupby("ticker").cumcount() >= d.groupby("ticker").ts.transform("size") * 0.6
    d["slot"] = d.groupby("ticker").cumcount() % horizon == 0
    return d, cols, horizon


def spec_auc(score, crash, rally):
    """Among windows with exactly one kind of large bar: does the score rank down above up?"""
    m = (crash + rally) == 1
    return roc_auc_score(crash[m], score[m]) if m.sum() > 20 and 0 < crash[m].mean() < 1 else np.nan


def run(interval, universe):
    d, cols, horizon = build(interval, universe)
    tr, te = ~d.test.to_numpy(), d.test.to_numpy()
    X = d[cols].to_numpy()
    crash, rally, fwd = d.crash.to_numpy(), d.rally.to_numpy(), d.fwd.to_numpy()
    print(f"\n{'=' * 100}\n{interval}: {d.ticker.nunique()} series, {len(d):,} bars, H={horizon}, K={K:g}, "
          f"{len(cols)} features. test base: crash {crash[te].mean():.2%}, rally {rally[te].mean():.2%}")

    # Single features: AUC on own target, and direction specificity.
    rows = []
    for i, c in enumerate(cols):
        s = np.nan_to_num(X[te, i], nan=np.nanmedian(X[tr, i]))
        rows.append((c, roc_auc_score(crash[te], s), roc_auc_score(rally[te], s),
                     spec_auc(s, crash[te], rally[te])))
    t = pd.DataFrame(rows, columns=["feature", "auc_crash", "auc_rally", "down_vs_up"])
    t["dir"] = (t.down_vs_up - 0.5).abs()
    print("\nsingle features, most directional first (down_vs_up: >0.5 means high value -> crash, <0.5 -> rally)")
    print(t.sort_values("dir", ascending=False).drop(columns="dir").head(12).to_string(index=False, float_format="%.3f"))

    Xf = np.where(np.isnan(X), np.nanmedian(X[tr], axis=0), X)
    models = {
        "logit": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=0.1)),
        "gbm": lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300,
                                                      min_samples_leaf=200, l2_regularization=1.0),
    }
    fam = d.family.to_numpy()[te]
    slot = d.slot.to_numpy()[te]
    for side, y, trade in (("crash/short", crash, -1), ("rally/long", rally, +1)):
        print(f"\n--- {side} ---")
        for name, make in models.items():
            m = make().fit(Xf[tr], y[tr])
            p = m.predict_proba(Xf[te])[:, 1]
            auc = roc_auc_score(y[te], p)
            other = roc_auc_score(rally[te] if trade < 0 else crash[te], p)
            spec = spec_auc(p if trade < 0 else -p, crash[te], rally[te])
            cut = np.quantile(p, 0.95)
            alarm = p >= cut
            lift = y[te][alarm].mean() / y[te].mean()
            k = alarm & slot
            pnl = trade * fwd[te][k]
            print(f"{name:>6}: AUC own {auc:.3f} | AUC on the opposite event {other:.3f} | "
                  f"direction {spec:.3f} | lift@5% {lift:.2f} | trade top5% (non-overlap n={k.sum()}): "
                  f"{pnl.mean():+.3f} +- {pnl.std() / np.sqrt(max(k.sum(), 1)):.3f} base units, win {np.mean(pnl > 0):.1%}")
            if name == "gbm":
                for family in universe:
                    kk = k & (fam == family)
                    if kk.sum() >= 20:
                        pp = trade * fwd[te][kk]
                        print(f"        {family:>7} n={kk.sum():>4}  {pp.mean():+.3f} +- {pp.std() / np.sqrt(kk.sum()):.3f}"
                              f"  win {np.mean(pp > 0):.1%}")
    allp = fwd[te][slot]
    print(f"\nunconditional non-overlapping fwd: {allp.mean():+.3f} +- {allp.std() / np.sqrt(len(allp)):.3f} (n={len(allp)})")


if __name__ == "__main__":
    for interval in ("15m", "1h"):
        run(interval, SERIES)
    run("1d", DAILY)
