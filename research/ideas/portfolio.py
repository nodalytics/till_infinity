"""The imported ideas that are portfolios, not trades: cross-sectional and time-series momentum,
currency strength, early acceleration, and the gold real-rate switch. Daily (or hourly) books on
the broker's own bars, charged the broker's spread on every change of position.

Pre-registered (2026-10-02), before any run.

  books      xsmom    rank the universe's L-day return (L 15, 30, 60); long the top 30%, short the
                      bottom 30%, equal weight; rebalance every H days (5, 10)
             ccy      currency strength from the USD pairs; long the strongest 2 / short the
                      weakest 2 by L-hour return (48, 120, 240), held 24h; and the reversal
             tsmom    per instrument, the 7/14/30/60-day sign ensemble, vol-scaled to 10% a year
                      (|position| <= 3), equal weight
             accel    the momentum ensemble's 3-day change, traded only while the ensemble is not
                      yet confirmed (|ens| < 0.5)
             gold     real 10y yield (FRED DFII10, a day late) falling over 63 days: momentum
                      ensemble (21/63/126/252); rising: fade z20 beyond 2, out at the mean
  universe   12 FX pairs, gold, silver, 7 indices, 2 oils, BTC, ETH, SOL; Deriv run apart
  costs      the broker's spread (median tick spread, else its quoted spread) on every unit of
             turnover, plus overnight swap ignored (stated)
  nulls      each book against 500 books with the same positions' sizes assigned at random to
             the instruments (cross-sectional) or with random signs (time-series)
  passes     Sharpe > 0 in both halves of the period, and above the 95th percentile of its null
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

DB = os.environ.get("MT5BT_DB")
OUT = Path(os.environ.get("OUT", ".data/ideas_portfolio"))
REAL = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY",
        "EURGBP", "AUDJPY", "USDCNH", "XAUUSD", "XAGUSD", "US SP 500", "US Tech 100", "Wall Street 30",
        "Germany 40", "UK 100", "Japan 225", "Australia 200", "US Oil", "UK Brent Oil", "BTCUSD",
        "ETHUSD", "SOLUSD"]
DERIV = ["Volatility 75 Index", "Volatility 25 Index", "Jump 50 Index", "Boom 1000 Index",
         "Crash 1000 Index", "Step Index", "Range Break 100 Index", "Drift Switch Index 10"]
USD_LEG = {"EURUSD": ("EUR", 1), "GBPUSD": ("GBP", 1), "AUDUSD": ("AUD", 1), "NZDUSD": ("NZD", 1),
           "USDJPY": ("JPY", -1), "USDCHF": ("CHF", -1), "USDCAD": ("CAD", -1), "USDCNH": ("CNH", -1)}


def closes(syms, iv):
    from mt5bt import load_bars
    out = {}
    for s in syms:
        try:
            df = load_bars(s, iv, "sqlite", DB)
        except (ValueError, OSError):
            continue
        t = pd.to_datetime(df["ts"], unit="s", utc=True)
        if iv == "1d":
            t = t.dt.normalize()
        out[s] = pd.Series(df["close"].to_numpy(), index=t)
    return pd.DataFrame(out).sort_index()


def spread_bps(syms, px: pd.DataFrame) -> pd.Series:
    """Each instrument's spread as a fraction of price, from ticks or the quoted spread."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out = {}
    for s in syms:
        rows = conn.execute("SELECT ask - bid FROM ticks WHERE symbol = ? ORDER BY ts_ms DESC LIMIT 100000",
                            (s,)).fetchall()
        raw = conn.execute("SELECT raw FROM specs WHERE symbol = ?", (s,)).fetchone()
        info = json.loads(raw[0]) if raw and raw[0] else {}
        if len(rows) > 1000:
            sp = float(np.median([r[0] for r in rows]))
        else:
            sp = float(info.get("spread") or 0) * float(info.get("point") or 0)
        out[s] = sp / float(px[s].dropna().iloc[-1]) if s in px and sp > 0 else 5e-4
    conn.close()
    return pd.Series(out)


def book_returns(pos: pd.DataFrame, rets: pd.DataFrame, cost: pd.Series) -> pd.Series:
    """Daily P&L of positions held from one close to the next, net of spread on turnover."""
    held = pos.shift(1).fillna(0.0)
    gross = (held * rets).sum(axis=1)
    turn = (pos.fillna(0.0) - pos.shift(1).fillna(0.0)).abs()
    return gross - (turn * cost.reindex(turn.columns).fillna(5e-4)).sum(axis=1)


def sharpe(r: pd.Series, per_year: float) -> float:
    r = r.dropna()
    return float(r.mean() / r.std() * np.sqrt(per_year)) if len(r) > 20 and r.std() > 0 else np.nan


def judge(name, pnl, null, per_year, rows):
    pnl = pnl.dropna()
    pnl = pnl[pnl.index >= pnl.index[0] + pd.Timedelta(days=90)]  # warm-up
    mid = pnl.index[len(pnl) // 2]
    s, a, b = sharpe(pnl, per_year), sharpe(pnl[pnl.index < mid], per_year), sharpe(pnl[pnl.index >= mid], per_year)
    nulls = np.array([sharpe(x.reindex(pnl.index), per_year) for x in null])
    p95 = float(np.nanquantile(nulls, 0.95)) if len(nulls) else np.nan
    ann = float(pnl.mean() * per_year)
    dd = float((pnl.cumsum() - pnl.cumsum().cummax()).min())
    passed = bool(a > 0 and b > 0 and s > p95)
    rows.append(dict(book=name, sharpe=round(s, 3), first=round(a, 3), second=round(b, 3),
                     null_p95=round(p95, 3), share_of_null_beaten=round(float(np.nanmean(nulls < s)), 3),
                     ann_return=round(ann, 4), max_dd=round(dd, 4), days=len(pnl), passes=passed))
    print(rows[-1], flush=True)


def xsmom(px, cost, rows, label, rng):
    rets = px.pct_change(fill_method=None)
    for L in (15, 30, 60):
        for H in (5, 10):
            mom = px / px.shift(L) - 1
            pos = pd.DataFrame(0.0, index=px.index, columns=px.columns)
            nulls_pos = [pos.copy() for _ in range(200)]
            for k, t in enumerate(px.index):
                if k % H or k < L:
                    if k:
                        pos.iloc[k] = pos.iloc[k - 1]
                        for npos in nulls_pos:
                            npos.iloc[k] = npos.iloc[k - 1]
                    continue
                m = mom.iloc[k].dropna()
                if len(m) < 6:
                    continue
                n = max(1, int(len(m) * 0.3))
                order = m.sort_values()
                w = pd.Series(0.0, index=px.columns)
                w[order.index[-n:]] = 1.0 / (2 * n)
                w[order.index[:n]] = -1.0 / (2 * n)
                pos.iloc[k] = w.to_numpy()
                for npos in nulls_pos:
                    shuffled = pd.Series(0.0, index=px.columns)
                    names = rng.permutation(m.index.to_numpy())
                    shuffled[names[-n:]] = 1.0 / (2 * n)
                    shuffled[names[:n]] = -1.0 / (2 * n)
                    npos.iloc[k] = shuffled.to_numpy()
            pnl = book_returns(pos, rets, cost)
            judge(f"{label} xsmom L{L} H{H}", pnl, [book_returns(n_, rets, cost) for n_ in nulls_pos], 252, rows)


def ensemble(px, lags):
    return sum(np.sign(px / px.shift(L) - 1) for L in lags) / len(lags)


def tsmom(px, cost, rows, label, rng):
    rets = px.pct_change(fill_method=None)
    ens = ensemble(px, (7, 14, 30, 60))
    vol = rets.rolling(30).std()
    pos = (ens * (0.10 / np.sqrt(252)) / vol).clip(-3, 3) / px.shape[1]
    pos = pos.where(np.isfinite(pos), 0.0)
    null = [book_returns(pos * np.sign(rng.standard_normal(pos.shape)), rets, cost) for _ in range(200)]
    judge(f"{label} tsmom", book_returns(pos, rets, cost), null, 252, rows)
    # early acceleration
    mom = sum((px / px.shift(L) - 1) / (rets.rolling(20).std() * np.sqrt(L)) for L in (7, 14, 30, 60)) / 4
    accel = mom.diff(3)
    early = np.sign(accel).where(ens.abs() < 0.5, 0.0) / px.shape[1]
    early = early.where(np.isfinite(early), 0.0)
    null = [book_returns(early * np.sign(rng.standard_normal(early.shape)), rets, cost) for _ in range(200)]
    judge(f"{label} accel", book_returns(early, rets, cost), null, 252, rows)


def currency(rows, rng):
    px = closes(list(USD_LEG), "1h")
    cost = spread_bps(list(USD_LEG), px)
    rets = px.pct_change(fill_method=None)
    ccy = pd.DataFrame({USD_LEG[s][0]: USD_LEG[s][1] * rets[s] for s in px}).fillna(0.0)
    for L in (48, 120, 240):
        strength = ccy.rolling(L).sum()
        for kind, sgn in (("mom", 1), ("rev", -1)):
            pos = pd.DataFrame(0.0, index=px.index, columns=px.columns)
            nulls = [pos.copy() for _ in range(100)]
            last = None
            for k in range(L, len(px), 24):
                s = strength.iloc[k].dropna().sort_values()
                if len(s) < 6:
                    continue
                pick = {**dict.fromkeys(s.index[-2:], sgn * 0.25), **dict.fromkeys(s.index[:2], -sgn * 0.25)}
                w = pd.Series({p: pick.get(USD_LEG[p][0], 0.0) * USD_LEG[p][1] for p in px})
                pos.iloc[k:k + 24] = w.to_numpy()
                for npos in nulls:
                    names = rng.permutation(s.index.to_numpy())
                    pk = {**dict.fromkeys(names[-2:], 0.25), **dict.fromkeys(names[:2], -0.25)}
                    npos.iloc[k:k + 24] = [pk.get(USD_LEG[p][0], 0.0) * USD_LEG[p][1] for p in px]
                last = k
            if last is None:
                continue
            judge(f"currency {kind} L{L}h", book_returns(pos, rets, cost),
                  [book_returns(n_, rets, cost) for n_ in nulls], 252 * 24, rows)


def gold(rows, rng):
    px = closes(["XAUUSD"], "1d")["XAUUSD"]
    path = OUT / "DFII10.csv"
    if not path.exists():
        data = urllib.request.urlopen("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10", timeout=30).read()
        path.write_bytes(data)
    rr = pd.read_csv(path, parse_dates=["observation_date"], na_values=".")
    rr = rr.set_index(rr["observation_date"].dt.tz_localize("UTC"))["DFII10"].astype(float)
    rr = rr.shift(1, freq="D").reindex(px.index, method="ffill")  # known a day late
    falling = rr < rr.shift(63)
    ens = sum(np.sign(px / px.shift(L) - 1) for L in (21, 63, 126, 252)) / 4
    z = (px - px.rolling(20).mean()) / px.rolling(20).std()
    pos = pd.Series(0.0, index=px.index)
    for k in range(253, len(px)):
        if falling.iloc[k]:
            pos.iloc[k] = 1.0 if ens.iloc[k] >= 0.5 else (-1.0 if ens.iloc[k] <= -0.5 else 0.0)
        else:
            prev = pos.iloc[k - 1]
            if z.iloc[k] < -2:
                pos.iloc[k] = 1.0
            elif z.iloc[k] > 2:
                pos.iloc[k] = -1.0
            elif prev != 0 and np.sign(z.iloc[k]) == np.sign(prev):
                pos.iloc[k] = 0.0  # back through the mean
            else:
                pos.iloc[k] = prev if not falling.iloc[k - 1] else 0.0
    cost = spread_bps(["XAUUSD"], px.to_frame())
    rets = px.pct_change(fill_method=None).to_frame()
    P = pos.to_frame("XAUUSD")
    null = [book_returns(P * np.sign(rng.standard_normal(P.shape)), rets, cost) for _ in range(300)]
    judge("gold real-rate switch", book_returns(P, rets, cost), null, 252, rows)
    mom = ens.where(ens.abs() >= 0.5, 0.0).apply(np.sign).to_frame("XAUUSD")
    judge("gold momentum alone", book_returns(mom, rets, cost),
          [book_returns(mom * np.sign(rng.standard_normal(mom.shape)), rets, cost) for _ in range(300)], 252, rows)


FRESH = ("AAVUSD,ADAUSD,ALGUSD,APEUSD,APTUSD,AVAUSD,BATUSD,BCHUSD,BNBUSD,COMUSD,DOGUSD,DOTUSD,DSHUSD,"
         "ETCUSD,FILUSD,IMXUSD,IOTUSD,LNKUSD,LTCUSD,MLNUSD,NEOUSD,NERUSD,SANUSD,SHBUSD,TRUUSD,TRXUSD,"
         "UNIUSD,XLMUSD,XMRUSD,XRPUSD,XTZUSD,ZECUSD").split(",")


def fresh(rng):
    """The frozen portfolio candidates on instruments they never saw (candidates.json)."""
    rows = []
    px = closes(FRESH, "1d").dropna(how="all")
    px = px[px.index >= "2016-01-01"]
    cost = spread_bps(list(px.columns), px)
    rets = px.pct_change(fill_method=None)
    ens = ensemble(px, (7, 14, 30, 60))
    vol = rets.rolling(30).std()
    pos = ((ens * (0.10 / np.sqrt(252)) / vol).clip(-3, 3) / px.shape[1])
    pos = pos.where(np.isfinite(pos), 0.0)
    null = [book_returns(pos * np.sign(rng.standard_normal(pos.shape)), rets, cost) for _ in range(200)]
    judge("fresh crypto tsmom", book_returns(pos, rets, cost), null, 252, rows)
    keep = []
    xsmom(px, cost, keep, "fresh crypto", rng)
    rows += [r for r in keep if any(k in r["book"] for k in ("L30 H5", "L30 H10", "L60 H5"))]
    for metal in ("XPTUSD", "XPDUSD"):
        m = closes([metal], "1d")[metal].dropna()
        e = sum(np.sign(m / m.shift(L) - 1) for L in (21, 63, 126, 252)) / 4
        posm = e.where(e.abs() >= 0.5, 0.0).apply(np.sign).to_frame(metal)
        r = m.pct_change(fill_method=None).to_frame()
        c = spread_bps([metal], m.to_frame())
        judge(f"{metal} momentum (gold rule)", book_returns(posm, r, c),
              [book_returns(posm * np.sign(rng.standard_normal(posm.shape)), r, c) for _ in range(300)], 252, rows)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "fresh_books.csv", index=False)
    print(df.to_string(index=False))


def main():
    if os.environ.get("FRESH"):
        OUT.mkdir(parents=True, exist_ok=True)
        fresh(np.random.default_rng(41))
        return
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(23)
    rows = []
    for label, syms in (("real", REAL), ("deriv", DERIV)):
        px = closes(syms, "1d").dropna(how="all")
        px = px[px.index >= "2016-01-01"]
        cost = spread_bps(list(px.columns), px)
        xsmom(px, cost, rows, label, rng)
        tsmom(px, cost, rows, label, rng)
    currency(rows, rng)
    gold(rows, rng)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "books.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
