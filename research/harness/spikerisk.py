"""Do the volatility features we already have raise the odds of a large move?

Not "can we call a crash" - whether the state of the market *now* changes the
probability that one of the next H bars is a large move, and by how much.

Event: some bar in the next H has |return| > K x baseline, where baseline is the
trailing mean |return| over LONG bars. The baseline is deliberately slow: normalising
by current volatility would define "large" relative to a regime that is already
elevated and hide exactly the lift being asked about. `crash` is the same with a
signed return below -K x baseline.

Features, all read strictly before the bars they are scored on:

  short    mean |r| over the last 10 bars / baseline      - the regime now
  shock    max |r| over the last 20 bars / baseline       - a recent large bar
  season   same hour-of-week's mean |r| in prior weeks / baseline (intraday only)
  drawdown distance below the 50-bar high, in baseline units

One series per underlying, the busiest venue. Returns are only taken across
bars one interval apart intraday, so a weekend gap is not a "spike". Each series
is split by time, 60/40; a logistic regression is fit on every series' first 60%
pooled and scored on the last 40%. Reported per family, never only pooled.

Run from the repository root:  .venv-research/bin/python research/harness/spikerisk.py
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

DB = ".data/prices/prices.db"

SERIES = {
    "fx": [("EURUSD", "OANDA"), ("GBPUSD", "OANDA"), ("AUDUSD", "OANDA"), ("NZDUSD", "OANDA"),
           ("USDCAD", "OANDA"), ("USDCHF", "OANDA"), ("USDJPY", "OANDA"), ("USDCNH", "OANDA")],
    "metal": [("XAUUSD", "OANDA")],
    "crypto": [("BTCUSD", "COINBASE"), ("ETHUSD", "COINBASE"), ("SOLUSD", "COINBASE")],
    "index": [("US500", "PEPPERSTONE"), ("NAS100", "PEPPERSTONE")],
}
# Daily history. Not yahoo: its daily FX bars leak - where the close sits in day t's range
# predicts day t+1's return at corr -0.44 on EURUSD=X and JPY=X (OANDA: +0.002), and its
# "open" tracks the same day's close at +0.91, so high/low/open are not the close's bar.
# Cash indices on yahoo and TVC carry the milder form (+0.62). Every source below was
# screened for both (crash-timing.md, "The leak"): |corr| <= 0.07 and <= 0.17.
DAILY = {
    "fx": [("EURUSD", "OANDA"), ("GBPUSD", "OANDA"), ("USDJPY", "OANDA"), ("AUDUSD", "OANDA")],
    "metal": [("XAUUSD", "OANDA")],
    "crypto": [("BTCUSD", "BITSTAMP"), ("ETHUSD", "COINBASE")],
    "index": [("SPX500USD", "OANDA"), ("NAS100USD", "OANDA")],
}
SETUPS = {  # interval: (seconds, horizon bars, baseline bars, uses season)
    "15m": (900, 4, 500, True),
    "1h": (3600, 4, 500, True),
    "1d": (86400, 5, 250, False),
}
K = 4.0
FEATURES = ["short", "shock", "season", "drawdown"]


def load(conn, ticker, venue, interval):
    """OHLC, oldest first. The bar is repaired to contain its own open and close: yahoo's daily
    FX and gold carry 1-2% of bars whose high sits below the close or low above the open."""
    rows = conn.execute(
        "select ts, open, high, low, close, volume from bars where ticker=? and venue=? and interval=?"
        " and closed=1 order by ts",
        (ticker, venue, interval),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    leak_check(df, f"{ticker}/{venue}/{interval}")
    return df


def leak_check(df, name):
    """Refuse a bar series whose shape predicts the *next* close - its fields are not one bar.

    Where the close sits in the bar's range should say almost nothing about the next return
    (|corr| <= 0.07 on every clean source screened). Yahoo's daily FX read -0.44, and every
    model built on it looked like a 94% winner.
    """
    if len(df) < 300:
        return
    lc = np.log(df.close)
    rng = (np.log(df.high) - np.log(df.low)).replace(0, np.nan)
    clv = ((lc - np.log(df.low)) - (np.log(df.high) - lc)) / rng
    c = clv.corr(lc.diff().shift(-1))
    if abs(c) > 0.15:
        raise ValueError(f"{name}: close location predicts the next return at {c:+.2f} - "
                         "the bar's fields are misaligned, and anything built on them leaks")


def frame(df, seconds, horizon, long, season):
    df = df[df.close > 0].reset_index(drop=True)
    r = np.log(df.close).diff()
    if seconds < 86400:
        r[df.ts.diff() != seconds] = np.nan  # no return across a gap
    a = r.abs()
    base = a.rolling(long, min_periods=long // 2).mean()
    out = pd.DataFrame({"ts": df.ts})
    out["short"] = a.rolling(10, min_periods=8).mean() / base
    out["shock"] = a.rolling(20, min_periods=15).max() / base
    peak = np.log(df.close).rolling(50, min_periods=40).max()
    out["drawdown"] = (peak - np.log(df.close)) / base
    if season:
        t = pd.to_datetime(df.ts, unit="s")
        key = t.dt.dayofweek * 10_000 + t.dt.hour * 100 + t.dt.minute
        norm = a / base
        # Mean of prior weeks at this slot only: shift inside the group before expanding.
        prior = norm.groupby(key).transform(lambda s: s.shift(1).expanding(min_periods=3).mean())
        out["season"] = prior.fillna(1.0)
    else:
        out["season"] = 1.0
    # Targets: any of the next `horizon` bars is large (spike) or large and down (crash).
    big = (a > K * base).astype(float)
    down = (r < -K * base).astype(float)
    big[r.isna()] = 0.0
    down[r.isna()] = 0.0
    fwd = lambda s: s[::-1].rolling(horizon, min_periods=horizon).max()[::-1].shift(-1)
    out["spike"] = fwd(big)
    out["crash"] = fwd(down)
    return out.dropna(subset=FEATURES + ["spike", "crash"])


def lift_at(y, score, share):
    cut = np.quantile(score, 1 - share)
    alarm = score >= cut
    base = y.mean()
    hit = y[alarm].mean()
    recall = y[alarm].sum() / max(y.sum(), 1)
    return hit / base if base else np.nan, recall


def xform(X):
    return np.log(np.clip(X, 1e-3, None)) if X.ndim else X


def run(interval, universe):
    seconds, horizon, long, season = SETUPS[interval]
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    parts = []
    for family, pairs in universe.items():
        for ticker, venue in pairs:
            df = load(conn, ticker, venue, interval)
            if len(df) < long * 3:
                continue
            f = frame(df, seconds, horizon, long, season)
            cut = int(len(f) * 0.6)
            f["test"] = np.arange(len(f)) >= cut
            f["family"], f["ticker"] = family, ticker
            parts.append(f)
    if not parts:
        return
    d = pd.concat(parts, ignore_index=True)
    feats = FEATURES if season else [c for c in FEATURES if c != "season"]
    X = np.log(np.clip(d[feats].to_numpy(), 1e-3, None))
    X[:, feats.index("drawdown")] = d["drawdown"].to_numpy()  # already signed-ish, keep linear
    tr, te = ~d.test.to_numpy(), d.test.to_numpy()

    days = (d.ts.max() - d.ts.min()) / 86400
    print(f"\n=== {interval}: {d.ticker.nunique()} series, {len(d):,} bars, ~{days:.0f} days,"
          f" event = a bar > {K:g}x baseline in the next {horizon} bars ===")
    for target in ("spike", "crash"):
        y = d[target].to_numpy()
        model = LogisticRegression(max_iter=1000).fit(X[tr], y[tr])
        p = model.predict_proba(X[te])[:, 1]
        print(f"\n[{target}] test base rate {y[te].mean():.2%} ({int(y[te].sum()):,} bars flagged by the event)")
        print(f"{'':>10} {'AUC':>6} {'lift@5%':>8} {'recall@5%':>10} {'lift@10%':>9}")
        rows = [("model", p)] + [(c, X[te][:, i]) for i, c in enumerate(feats)]
        for name, s in rows:
            yt = y[te]
            if yt.min() == yt.max():
                continue
            l5, r5 = lift_at(yt, s, 0.05)
            l10, _ = lift_at(yt, s, 0.10)
            print(f"{name:>10} {roc_auc_score(yt, s):6.3f} {l5:8.2f} {r5:10.1%} {l10:9.2f}")
        print(f"  by family (model):")
        fam = d.family.to_numpy()[te]
        for family in universe:
            m = fam == family
            yt = y[te][m]
            if m.sum() == 0 or yt.sum() < 5 or yt.min() == yt.max():
                continue
            l5, r5 = lift_at(yt, p[m], 0.05)
            print(f"  {family:>8} n={m.sum():>7,} events={int(yt.sum()):>5} base={yt.mean():6.2%}"
                  f"  AUC={roc_auc_score(yt, p[m]):.3f}  lift@5%={l5:5.2f}  recall@5%={r5:5.1%}")
        coef = ", ".join(f"{c}={w:+.2f}" for c, w in zip(feats, model.coef_[0]))
        print(f"  coefficients: {coef}")


if __name__ == "__main__":
    for interval in ("15m", "1h"):
        run(interval, SERIES)
    run("1d", DAILY)
