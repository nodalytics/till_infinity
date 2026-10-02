"""Re-check the three directional leads directional-questions.md parked, on the weeks since.

Pre-registered (2026-10-02), before any run. Each lead is rebuilt exactly as it was measured -
same features, labels, model and threshold - on the broker's bars, over the same start date, with
everything before T0 (the day the original data ended) playing the original's role: its first 60%
trains, the threshold is set where the original set it. Then the frozen model is scored on bars
after T0 only, which no version of it has seen.

  leads    1. intraday short models (horizons.py): P(lower barrier first), top 5% of the test
              block -> short; 15m at H 4 and 8, 1h at H 5. Reported gross, as the original was
           2. daily +3:-1 long (questions.py Q4): P(win) top 20% by the training quantile
           3. daily pair-spread reversion (questions.py Q2): |z| > 2 -> fade the spread
  T0       intraday 2026-08-19, daily 2026-08-17 (the local database's last bars)
  reads    each lead's R a trade after T0 with its n, beside the same rebuild on the original test
           block - if the rebuild does not reproduce the original there, the feed differs and the
           fresh number says nothing about the lead
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import horizons as hz  # noqa: E402
import questions as qs  # noqa: E402

DB = os.environ.get("MT5BT_DB", os.path.expanduser("~/till_infinity/data/mt5bt.db"))
BROKER = {"US500": "US SP 500", "NAS100": "US Tech 100", "SPX500USD": "US SP 500", "NAS100USD": "US Tech 100"}
START = {"15m": "2026-06-24", "1h": "2025-10-24", "1d": "2007-05-10"}
T0 = {"15m": "2026-08-19", "1h": "2026-08-19", "1d": "2026-08-17"}


def broker_load(_conn, ticker, _venue, interval):
    sym = BROKER.get(ticker, ticker)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    df = pd.read_sql_query("SELECT ts, open, high, low, close, volume FROM bars WHERE symbol = ? AND interval = ? "
                           "ORDER BY ts", conn, params=(sym, interval))
    conn.close()
    df = df.drop_duplicates("ts").reset_index(drop=True)
    df = df[df["ts"] >= pd.Timestamp(START[interval], tz="UTC").timestamp()].reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


hz.load = broker_load
hz.DB = qs.DB = DB  # opened by build() before it calls the loader; the loader reads the broker's bars
qs.load = broker_load


def resplit(d, interval):
    """The original's split, on the rows before T0 only; rows after T0 are the fresh block (3)."""
    t0 = pd.Timestamp(T0[interval], tz="UTC").timestamp()
    old = d["ts"] < t0
    size = d[old].groupby("ticker").ts.transform("size")
    pos = d[old].groupby("ticker").cumcount()
    split = np.full(len(d), 3)
    split[old.to_numpy()] = np.select([pos < size * 0.6, pos < size * 0.8], [0, 1], 2)
    d = d.copy()
    d["split"] = split
    return d


def summary(name, R, mask, rows):
    x = R[mask]
    x = x[np.isfinite(x)]
    se = x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else np.nan
    rows.append(dict(lead=name, n=len(x), R=round(float(x.mean()), 3) if len(x) else np.nan,
                     se=round(float(se), 3) if np.isfinite(se) else np.nan,
                     win=round(float((x > 0).mean()), 3) if len(x) else np.nan))
    print(rows[-1], flush=True)


def lead1(rows):
    for interval, Hs in (("15m", (4, 8)), ("1h", (5,))):
        d, cols = hz.build(interval, hz.SERIES)
        d = resplit(d, interval)
        X = d[cols].to_numpy(float)
        split = d["split"].to_numpy()
        for H in Hs:
            y = d[f"tb_dn@{H}"].to_numpy()
            Rs = d[f"Rs@{H}"].to_numpy()
            ok = ~np.isnan(y)
            tr, te, fr = ok & (split == 0), ok & np.isin(split, (1, 2)), ok & (split == 3)
            p = np.full(len(d), np.nan)
            m = hz.gbm().fit(X[tr], y[tr])
            p[te | fr] = m.predict_proba(X[te | fr])[:, 1]
            cut = np.nanquantile(p[te], 0.95)  # where the original set it: the test block's top 5%
            slot = (d["_pos"].to_numpy() % H) == 0
            summary(f"1 short {interval} H{H} - original test block", Rs, te & (p >= cut) & slot, rows)
            summary(f"1 short {interval} H{H} - fresh, after T0", Rs, fr & (p >= cut) & slot, rows)


def lead2(rows):
    interval, H = "1d", qs.H_FOR["1d"]
    d, cols = qs.build(interval, qs.DAILY)
    d = d.drop(columns=[c for c in d.columns if "@" in c])
    d = resplit(d, interval)
    X = d[cols].to_numpy(float)
    fut = qs.paths(d, H)
    unit = d["_base"].to_numpy() * np.sqrt(H)
    R, _ = qs.long_R(fut, 3 * unit, 1 * unit)
    cost = qs.cost_R(d, interval, unit)
    y = (R > 0).astype(float)
    split = d["split"].to_numpy()
    tr = (split == 0) & ~np.isnan(R)
    te = np.isin(split, (1, 2)) & ~np.isnan(R)
    fr = (split == 3) & ~np.isnan(R)
    m = qs.Fitted(qs.gbm(), X[tr], y[tr])
    p = np.full(len(d), np.nan)
    p[tr | te | fr] = m.predict_proba(X[tr | te | fr])[:, 1]
    pick = p >= np.quantile(p[tr], 0.8)
    net = R - cost
    summary("2 daily long +3:-1 top 20% - original test block (net)", net, qs.thin(d, te & pick, H), rows)
    summary("2 daily long +3:-1 top 20% - fresh, after T0 (net)", net, qs.thin(d, fr & pick, H), rows)


def lead3(rows):
    interval, H = "1d", qs.H_FOR["1d"]
    d, _cols = qs.pair_frame(interval)
    t0 = pd.Timestamp(T0[interval], tz="UTC").timestamp()
    fut = qs.paths(d, H)
    U = 1.5 * d["_base"].to_numpy() * np.sqrt(H)
    R, _ = qs.long_R(fut, U, U)
    Rs, _ = qs.long_R(fut * -1, U, U)
    legs = (d["_base_a"] + d["_base_b"]).to_numpy() * d.family.map(qs.COST_V).to_numpy() / np.sqrt(qs.MINUTES[interval] / 5)
    cost = legs / U
    zs = d.zscore20.to_numpy()
    side = np.where(np.abs(zs) > 2, -np.sign(zs), 0)
    g = np.where(side == 1, R, np.where(side == -1, Rs, np.nan)) - cost
    old = (d["ts"] < t0).to_numpy()
    size = d[old].groupby("ticker").ts.transform("size")
    pos = d[old].groupby("ticker").cumcount()
    test = np.zeros(len(d), bool)
    test[old] = (pos >= size * 0.6).to_numpy()
    summary("3 daily pair reversion |z|>2 - original test block (net)", g, qs.thin(d, test & (side != 0), H), rows)
    summary("3 daily pair reversion |z|>2 - fresh, after T0 (net)", g, qs.thin(d, ~old & (side != 0), H), rows)


def main():
    rows = []
    lead1(rows)
    lead2(rows)
    lead3(rows)
    out = Path(os.environ.get("OUT", ".data/leads_recheck"))
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "leads.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
