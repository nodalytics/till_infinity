"""The rollover on ticks (fxml_add_rule.json section 1): is the 1h direction skill at the rollover a bid quote?

Read-only on the lab's stored ticks (the bridge needs credentials this study does not read):
  mt5bt.db ticks        EURUSD, XAUUSD, 2026-09-02 .. 10-02 (every daily rollover in that month)
  research.db ticks     16 FX / metal feeds, 2026-09-09 .. 09-10
  reopen_ticks.db       the 12 FX pairs' weekend reopen windows (15 min before to 3 h after), 2024-11 ..

  R1  the spread by minute around the rollover, against the floor charged
  R2  the next-bar sign from mid prices against bid prices, and the frozen 1h model's AUC on each
  R3  the frozen conformal-set trade on rollover bars, priced on ticks at the executable side

  OUT=... MT5BT_DB=... python research/ideas/fxml_ticks.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fxml_data as D  # noqa: E402
import fxml_models as M  # noqa: E402

OUT = D.OUT
REP = OUT / "report"
DATA = Path(os.path.expanduser("~/till_infinity/data"))
FEED = {"eurusd": "EURUSD", "gbpusd": "GBPUSD", "usdjpy": "USDJPY", "audusd": "AUDUSD", "usdcad": "USDCAD",
        "usdchf": "USDCHF", "nzdusd": "NZDUSD", "eurjpy": "EURJPY", "gbpjpy": "GBPJPY", "eurgbp": "EURGBP",
        "audjpy": "AUDJPY", "gold": "XAUUSD", "silver": "XAGUSD", "eurchf": "EURCHF", "chfjpy": "CHFJPY",
        "euraud": "EURAUD"}
ROLL = {19, 20, 21, 22}
STALE_MS = 5 * 60 * 1000


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def load_ticks():
    """sym -> DataFrame(ts_ms, bid, ask), every stored source merged."""
    out = {}
    c = ro(os.environ["MT5BT_DB"])
    for sym in ("EURUSD", "XAUUSD"):
        d = pd.read_sql_query("SELECT ts_ms, bid, ask FROM ticks WHERE symbol = ? ORDER BY ts_ms", c, params=(sym,))
        out.setdefault(sym, []).append(d)
    c.close()
    c = ro(DATA / "research.db")
    for feed, sym in FEED.items():
        d = pd.read_sql_query("SELECT ts AS ts_ms, bid, ask FROM ticks WHERE feed = ? ORDER BY ts", c, params=(feed,))
        if len(d) and d["ts_ms"].max() < 1e11:
            d["ts_ms"] = d["ts_ms"] * 1000
        out.setdefault(sym, []).append(d)
    c.close()
    c = ro(DATA / "reopen_ticks.db")
    for sym in D.FX:
        d = pd.read_sql_query("SELECT ts_ms, bid, ask FROM ticks WHERE sym = ? ORDER BY ts_ms", c, params=(sym,))
        out.setdefault(sym, []).append(d)
    c.close()
    res = {}
    for sym, parts in out.items():
        d = pd.concat(parts, ignore_index=True).dropna()
        d = d[(d["ask"] >= d["bid"]) & (d["bid"] > 0)].drop_duplicates("ts_ms").sort_values("ts_ms")
        if len(d):
            res[sym] = d.reset_index(drop=True)
    return res


def last_before(tk, t_ms):
    """bid, ask of the last tick at or before t_ms (NaN if none within STALE_MS)."""
    ts = tk["ts_ms"].to_numpy(np.int64)
    i = np.searchsorted(ts, t_ms, side="right") - 1
    ok = (i >= 0)
    ii = np.clip(i, 0, None)
    ok &= (t_ms - ts[ii]) <= STALE_MS
    bid = np.where(ok, tk["bid"].to_numpy()[ii], np.nan)
    ask = np.where(ok, tk["ask"].to_numpy()[ii], np.nan)
    return bid, ask


def r1_spread(ticks, rows):
    """Median spread by UTC minute 20:00-24:00 on days with ticks, in pips and in 1h ATR."""
    out = []
    for sym, tk in ticks.items():
        t = pd.to_datetime(tk["ts_ms"], unit="ms", utc=True)
        mins = t.dt.hour * 60 + t.dt.minute
        sp = (tk["ask"] - tk["bid"]).to_numpy()
        m = rows[rows.sym == sym]
        atr_med = float(np.nanmedian(m["atr"])) if len(m) else np.nan
        cost_med = float(np.nanmedian(m["cost_atr"] * m["atr"])) if len(m) else np.nan
        wd = t.dt.weekday.to_numpy()
        for kind, sel in (("weekday", wd < 5), ("sunday", wd == 6)):
            for b0 in range(18 * 60, 24 * 60, 10):
                mm = sel & (mins.to_numpy() >= b0) & (mins.to_numpy() < b0 + 10)
                if mm.sum() < 20:
                    continue
                s = float(np.median(sp[mm]))
                out.append(dict(sym=sym, days=kind, minute=b0, spread=s, spread_atr=s / atr_med,
                                floor=cost_med, ratio_to_floor=s / cost_med if cost_med else np.nan,
                                n=int(mm.sum())))
    return pd.DataFrame(out)


def r2_labels(ticks, rows, pred):
    """Next-bar sign from bid and from mid at the bar closes, where ticks exist at both closes."""
    out = []
    for sym, tk in ticks.items():
        m = rows[(rows.sym == sym) & (rows.ts >= D.SPLIT)]
        if not len(m):
            continue
        ts = m["ts"].to_numpy(np.int64)
        b0, a0 = last_before(tk, (ts + 3600) * 1000 - 1)
        b1, a1 = last_before(tk, (ts + 7200) * 1000 - 1)
        ok = np.isfinite(b0) & np.isfinite(b1)
        if not ok.any():
            continue
        d = m[ok].copy()
        d["bid_lab"] = (b1[ok] > b0[ok]).astype(float)
        d["mid_lab"] = (((b1 + a1) / 2)[ok] > ((b0 + a0) / 2)[ok]).astype(float)
        d.loc[b1[ok] == b0[ok], "bid_lab"] = np.nan
        d.loc[(b1 + a1)[ok] == (b0 + a0)[ok], "mid_lab"] = np.nan
        d["spread0"] = (a0 - b0)[ok]
        d["spread1"] = (a1 - b1)[ok]
        d["p"] = pred[d.index.to_numpy()]
        out.append(d)
    if not out:
        return pd.DataFrame(), pd.DataFrame()
    L = pd.concat(out)
    L["roll"] = L["hour"].astype(int).isin(ROLL)
    res = []
    for part, sel in (("rollover", L.roll), ("other", ~L.roll)):
        x = L[sel]
        for lab in ("sign1", "bid_lab", "mid_lab"):
            ok = np.isfinite(x[lab]) & np.isfinite(x["p"])
            res.append(dict(part=part, label=lab, n=int(ok.sum()), auc=M.auc(x[lab][ok].to_numpy(), x["p"][ok].to_numpy()),
                            up_rate=float(x[lab][ok].mean())))
        agree = np.isfinite(x.bid_lab) & np.isfinite(x.mid_lab)
        res.append(dict(part=part, label="bid=mid agreement", n=int(agree.sum()),
                        auc=float((x.bid_lab[agree] == x.mid_lab[agree]).mean()), up_rate=np.nan))
    return L, pd.DataFrame(res)


def r3_trades(ticks, bars, trades):
    """The frozen 1R / 2R trade on rollover-hour signals, priced on ticks at the executable side."""
    out = []
    for r in trades.itertuples():
        tk = ticks.get(r.sym)
        b = bars.get(r.sym)
        if tk is None or b is None:
            continue
        t = int(r.t)
        if t + 1 >= len(b):
            continue
        o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        a = b["atr"].to_numpy(float)
        ts = b["ts"].to_numpy(np.int64)
        side = int(r.side)
        E = o[t + 1]
        if side > 0:
            stop0 = min(l[max(t - 2, 0):t + 1]) - D.PAD * a[t]
            risk = max(E - stop0, D.MIN_RISK * a[t])
            stop0 = E - risk
        else:
            stop0 = max(h[max(t - 2, 0):t + 1]) + D.PAD * a[t]
            risk = max(stop0 - E, D.MIN_RISK * a[t])
            stop0 = E + risk
        t_ms = ts[t + 1] * 1000
        tsk = tk["ts_ms"].to_numpy(np.int64)
        i0 = np.searchsorted(tsk, t_ms)
        if i0 >= len(tsk) or tsk[i0] - t_ms > 60_000:
            continue  # no tick within a minute of the entry bar's open
        j1 = np.searchsorted(tsk, t_ms + 6 * 3600 * 1000)
        bid = tk["bid"].to_numpy()[i0:j1]
        ask = tk["ask"].to_numpy()[i0:j1]
        entry = ask[0] if side > 0 else bid[0]
        row = dict(sym=r.sym, ts=int(r.ts), side=side, risk_px=risk, entry_bar=E, entry_tick=entry,
                   entry_spread=float(ask[0] - bid[0]), bar_g1=r.g1, bar_net1=r.net1, n_ticks=len(bid))
        for N in (1, 2):
            tgt = E + side * N * risk
            if side > 0:
                hit_stop, hit_tgt = bid <= stop0, bid >= tgt
            else:
                hit_stop, hit_tgt = ask >= stop0, ask <= tgt
            ks = int(np.argmax(hit_stop)) if hit_stop.any() else len(bid)
            kt = int(np.argmax(hit_tgt)) if hit_tgt.any() else len(bid)
            if ks <= kt and ks < len(bid):
                res = side * ((bid[ks] if side > 0 else ask[ks]) - entry) / risk
                row[f"tick_open{N}"] = False
            elif kt < len(bid):
                res = side * (tgt - entry) / risk
                row[f"tick_open{N}"] = False
            else:  # unresolved within six hours: marked at the last executable price
                res = side * ((bid[-1] if side > 0 else ask[-1]) - entry) / risk
                row[f"tick_open{N}"] = True
            row[f"tick_R{N}"] = res
        out.append(row)
    return pd.DataFrame(out)


def main():
    REP.mkdir(parents=True, exist_ok=True)
    ticks = load_ticks()
    print({k: len(v) for k, v in ticks.items()}, flush=True)
    d = pd.read_pickle(OUT / "ds_1h_real.pkl")["rows"]  # our own pickle
    rows = d[["sym", "cls", "ts", "bar", "hour", "atr", "cost_atr", "sign1"]].reset_index(drop=True)
    r1 = r1_spread(ticks, rows)
    r1.to_csv(REP / "ticks_r1_spread.csv", index=False)
    pr = pd.read_pickle(OUT / "pred" / "1h_real_sign1.pkl")  # our own pickle
    L, r2 = r2_labels(ticks, rows, pr["pred"]["hgb"].astype(float))
    r2.to_csv(REP / "ticks_r2_labels.csv", index=False)
    if len(L):
        L.to_csv(REP / "ticks_r2_rows.csv", index=False)
    T = pd.read_pickle(REP / "trades.pkl")  # our own pickle
    T = T[(T.tf == "1h") & (T.source == "real")]
    T = T[((T.ts // 3600) % 24).isin(sorted(ROLL))]
    bars = pd.read_pickle(OUT / "bars_1h_real.pkl")  # our own pickle
    r3 = r3_trades(ticks, bars, T)
    r3.to_csv(REP / "ticks_r3_trades.csv", index=False)
    if len(r3):
        print(r3[["bar_g1", "bar_net1", "tick_R1", "tick_R2"]].describe().round(3).to_string(), flush=True)
    print(r2.to_string(), flush=True)
    print("ticks done", flush=True)


if __name__ == "__main__":
    main()
