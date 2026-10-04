"""The FX 1h gap fade replayed on the broker's ticks at the reopen, at the price a trader actually gets.

Registered in `gapfade_replay_rule.json` before any reopen tick was fetched. `mean_reversion.py` picked and
confirmed the FX 1h gap fade (`mr_selected.json`), but MT5's bars are bid prices and their spread field is
the bar's minimum, so the bars' reopen price may be one nobody could buy at. This fetches each pair's
reopen windows from the lab's MT5 bridge (read-only), measures the spread there, and replays every
confirmation trade with ticks: entering at the first executable price, and 5, 15 and 60 minutes later.

  MODE=fetch    pull the reopen windows into data/reopen_ticks.db (needs the bridge's env; spaced requests)
  MODE=measure  the reopen spread per pair against the bar's recorded spread and the weekday floor
  MODE=replay   the registered replay and its verdict

  OUT=... MT5BT_DB=... MR_OUT=out/mr REOPEN_DB=data/reopen_ticks.db python research/ideas/gapfade_replay.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import mean_reversion as M  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/gapfade_replay"))
DB = os.environ.get("MT5BT_DB")
MR_OUT = Path(os.environ.get("MR_OUT", os.path.expanduser("~/till_infinity/out/mr")))
TICKS = Path(os.environ.get("REOPEN_DB", os.path.expanduser("~/till_infinity/data/reopen_ticks.db")))
PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
         "AUDJPY", "USDCNH")
START = int(pd.Timestamp("2024-11-01", tz="UTC").timestamp())
END = int(pd.Timestamp("2026-10-03", tz="UTC").timestamp())
PRE, POST, HOLE = 900, 3 * 3600, 24 * 3600
GAP_S = float(os.environ.get("GAP", "1.0"))
DELAYS = {"T0": 0, "T5": 300, "T15": 900, "T60": 3600}
H = 8  # the frozen time stop: the close of the 8th bar from the reopen bar


def pip(sym):
    return 0.01 if sym.endswith("JPY") else 0.0001


def bars(sym):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql_query("SELECT ts, open, high, low, close, spread FROM bars WHERE symbol = ? AND interval = '1h'"
                          " ORDER BY ts", conn, params=(sym,))
    point = float(json.loads(conn.execute("SELECT spec FROM specs WHERE symbol = ?", (sym,)).fetchone()[0])["point"])
    conn.close()
    return d.drop_duplicates("ts").reset_index(drop=True), point


def reopens(b):
    ts = b["ts"].to_numpy(np.int64)
    i = np.flatnonzero(np.diff(ts) >= HOLE) + 1
    return [int(x) for x in ts[i] if START <= x <= END]


def store():
    TICKS.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(TICKS, timeout=180.0)
    conn.execute("CREATE TABLE IF NOT EXISTS ticks (sym TEXT, ts_ms INTEGER, bid REAL, ask REAL, PRIMARY KEY (sym, ts_ms, bid, ask))")
    conn.execute("CREATE TABLE IF NOT EXISTS windows (sym TEXT, reopen_ts INTEGER, status INTEGER, n INTEGER, "
                 "fetched INTEGER, PRIMARY KEY (sym, reopen_ts))")
    conn.execute("CREATE INDEX IF NOT EXISTS ticks_sym_ts ON ticks (sym, ts_ms)")
    conn.commit()
    return conn


def _ms(v):
    if v is None:
        return None
    if isinstance(v, int | float):
        return int(v) if v > 1e11 else int(v * 1000)
    try:
        return int(datetime.fromisoformat(str(v)).replace(tzinfo=UTC).timestamp() * 1000)
    except ValueError:
        return None


def _rows(payload):
    if isinstance(payload, list):
        return payload
    for k in ("data", "ticks", "result", "items"):
        if isinstance(payload, dict) and isinstance(payload.get(k), list):
            return payload[k]
    return []


def fetch():
    """One request per reopen window, spaced; the bridge is shared with the live desk."""
    import httpx
    base = os.environ.get("TRADING_MT5_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
    key = os.environ.get("TRADING_MT5_API_KEY", "")
    headers = {"Accept": "application/json", **({"X-API-Key": key} if key else {})}
    conn = store()
    done = set(conn.execute("SELECT sym, reopen_ts FROM windows WHERE status IN (200, 404)").fetchall())
    stamp = lambda s: datetime.fromtimestamp(s, UTC).strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731
    with httpx.Client(headers=headers) as client:
        for sym in PAIRS:
            b, _ = bars(sym)
            for r in reopens(b):
                if (sym, r) in done:
                    continue
                status, kept = -1, []
                try:
                    resp = client.get(f"{base}/symbols/ticks/{sym}/range",
                                      params={"date_from": stamp(r - PRE), "date_to": stamp(r + POST)}, timeout=180)
                    status = resp.status_code
                    if status == 200:
                        for row in _rows(resp.json()):
                            ms = _ms(row.get("time_msc")) or _ms(row.get("time"))
                            if ms is not None and (r - PRE) * 1000 <= ms <= (r + POST) * 1000:
                                kept.append((sym, ms, row.get("bid"), row.get("ask")))
                except Exception as e:  # noqa: BLE001 - record the failure and move on
                    print(f"  {sym} {stamp(r)}: {e!r}", flush=True)
                conn.executemany("INSERT OR IGNORE INTO ticks VALUES (?,?,?,?)", kept)
                conn.execute("INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?)", (sym, r, status, len(kept), int(time.time())))
                conn.commit()
                print(f"  {sym} {stamp(r)}: HTTP {status}, {len(kept)} ticks", flush=True)
                time.sleep(GAP_S)


def window(conn, sym, r):
    d = pd.read_sql_query("SELECT ts_ms, bid, ask FROM ticks WHERE sym = ? AND ts_ms BETWEEN ? AND ? ORDER BY ts_ms",
                          conn, params=(sym, (r - PRE) * 1000, (r + POST) * 1000))
    return d[(d["bid"] > 0) & (d["ask"] > 0)].reset_index(drop=True)


def measure():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = store()
    costs = json.loads((MR_OUT / "costs.json").read_text())
    rows = []
    for sym in PAIRS:
        b, point = bars(sym)
        a = M.atr(*(b[k].to_numpy(float) for k in ("high", "low", "close")))
        ts = b["ts"].to_numpy(np.int64)
        for r in reopens(b):
            w = window(conn, sym, r)
            w = w[w["ts_ms"] >= r * 1000]
            if not len(w):
                continue
            s = int(np.searchsorted(ts, r))
            sp = (w["ask"] - w["bid"]).to_numpy()
            t0 = int(w["ts_ms"].iat[0])
            el = (w["ts_ms"].to_numpy() - t0) / 60000.0
            at60 = sp[el >= 60][0] if (el >= 60).any() else np.nan
            rows.append(dict(sym=sym, reopen=r, first_tick_s=(t0 / 1000 - r), first=sp[0],
                             **{f"med{m}": float(np.median(sp[el < m])) for m in (1, 5, 15, 60)}, at60=at60,
                             bar_rec=float(b["spread"].iat[s]) * point, floor=float(costs[sym][0]),
                             atr=float(a[s - 1]), pip=pip(sym)))
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "reopen_spreads.csv", index=False)
    pd.set_option("display.width", 220)
    cols = ["first", "med1", "med5", "med15", "med60", "at60", "bar_rec", "floor"]
    for unit, div in (("pips", "pip"), ("ATR(14, 1h)", "atr")):
        x = d[cols].div(d[div], axis=0).assign(sym=d["sym"])
        print(f"\nREOPEN SPREAD, median per pair, in {unit} ({len(d)} reopens with ticks)")
        g = x.groupby("sym").median()
        g["n"] = x.groupby("sym").size()
        print(pd.concat([g, x[cols].median().to_frame("ALL").T.assign(n=len(x))]).round(3).to_string())
    print("\nfirst-tick spread / the reopen bar's recorded spread: median "
          f"{(d['first'] / d['bar_rec'].replace(0, np.nan)).median():.1f}x; / weekday floor: "
          f"{(d['first'] / d['floor']).median():.1f}x; quartiles of the first spread in ATR: "
          f"{np.round(np.quantile(d['first'] / d['atr'], [0.25, 0.5, 0.75, 0.9]), 3).tolist()}")


def replay():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = store()
    costs = json.loads((MR_OUT / "costs.json").read_text())
    gc = pd.read_pickle(MR_OUT / "gapcheck.pkl")  # mean_reversion.py's own outputs, never external data
    gc = gc[(gc["source"] == "real") & (gc["iv"] == "1h") & (gc["fam"] == "fx")]
    rows = []
    for sym in PAIRS:
        p = MR_OUT / "trades" / "real" / f"single__mt5__{sym}__1h.pkl"
        if not p.exists():
            continue
        tr = pd.read_pickle(p)
        tr = tr[(tr["rule"] == "gap") & (tr["hu"] >= M.HU_T) & (tr["ts"] >= M.SPLIT)]
        if not len(tr):
            continue
        b, _ = bars(sym)
        o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        ts = b["ts"].to_numpy(np.int64)
        a = M.atr(h, l, c)
        n = len(c)
        spr = float(costs[sym][0])
        g_sym = gc[gc["sym"] == sym]
        for _, x in tr.iterrows():
            t, side = int(x["t"]), int(x["side"])
            s = t + 1
            if s + H - 1 >= n or ts[s] != int(x["ts"]):
                continue
            fri, os_ = c[t], o[s]
            risk = side * (fri - os_) + M.PAD * a[t]
            target, stop = fri, os_ - side * risk
            slip = M.SLIP * a[t]
            base = dict(sym=sym, ts=int(ts[s]), side=side, risk_atr=risk / a[t], gap_atr=(os_ - fri) / a[t],
                        frozen=float(x["own"] - x["cost"]))
            for chk, off in (("a_bar_spread", 0), ("b_close_entry", 3600)):
                m = g_sym[(g_sym["check"] == chk) & (g_sym["ts"] == ts[s] + off) & (g_sym["side"] == side) & (g_sym["hu"] >= M.HU_T)]
                base[chk] = float((m["own"] - m["cost"]).iat[0]) if len(m) else np.nan
            w = window(conn, sym, int(ts[s]))
            w = w[w["ts_ms"] >= ts[s] * 1000].reset_index(drop=True)
            if not len(w):
                rows.append(dict(**base, entry="none", R=np.nan, skipped=False, ticks=False))
                continue
            tm, bid, ask = w["ts_ms"].to_numpy(), w["bid"].to_numpy(), w["ask"].to_numpy()
            j0 = int(np.searchsorted(ts, ts[s] + POST))  # the first bar the ticks do not cover
            for name, delay in DELAYS.items():
                k0 = int(np.searchsorted(tm, (ts[s] + delay) * 1000))
                if k0 >= len(tm):
                    rows.append(dict(**base, entry=name, R=np.nan, skipped=True, ticks=True))
                    continue
                pre_b, pre_a = bid[:k0], ask[:k0]
                if side > 0:
                    touched = (pre_b >= target).any() or (pre_b <= stop).any()
                else:
                    touched = (pre_a <= target).any() or (pre_a >= stop).any()
                if touched:
                    rows.append(dict(**base, entry=name, R=np.nan, skipped=True, ticks=True))
                    continue
                entry = ask[k0] if side > 0 else bid[k0]
                px = None
                for k in range(k0 + 1, len(tm)):
                    if side > 0:
                        if bid[k] <= stop:
                            px = bid[k]
                            break
                        if bid[k] >= target:
                            px = target
                            break
                    else:
                        if ask[k] >= stop:
                            px = ask[k]
                            break
                        if ask[k] <= target:
                            px = target
                            break
                if px is None:
                    for j in range(j0, s + H):
                        if side > 0:
                            if l[j] <= stop:
                                px = min(o[j], stop) - slip
                                break
                            if h[j] >= target:
                                px = max(o[j], target)
                                break
                        else:
                            if h[j] + spr >= stop:
                                px = max(o[j] + spr, stop) + slip
                                break
                            if l[j] + spr <= target:
                                px = min(o[j] + spr, target)
                                break
                    if px is None:
                        px = c[s + H - 1] + (spr if side < 0 else 0.0)
                rows.append(dict(**base, entry=name, R=side * (px - entry) / risk, skipped=False, ticks=True,
                                 entry_spread_R=(ask[k0] - bid[k0]) / risk))
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "replay_trades.csv", index=False)
    report(d)


def report(d):
    from scipy.stats import norm
    pd.set_option("display.width", 220)
    first = d.drop_duplicates(["sym", "ts", "side"])
    cov = first[first["ticks"]]
    print(f"\nconfirmation trades: {len(first)}; with reopen ticks: {len(cov)} "
          f"(first {pd.Timestamp(cov['ts'].min(), unit='s'):%Y-%m-%d} .. {pd.Timestamp(cov['ts'].max(), unit='s'):%Y-%m-%d})")

    def stat(R, ts, label, seed=3):
        x = pd.DataFrame({"R": R, "day": np.asarray(ts) // 86400, "N": 1.0}).dropna()
        dd = x.groupby("day").sum()
        m, se = M.cluster(dd["R"].to_numpy(), dd["N"].to_numpy())
        lo, hi = M.boot_ci(dd["R"].to_numpy(), dd["N"].to_numpy(), seed)
        cum = np.cumsum(dd["N"].to_numpy())
        half = cum <= cum[-1] / 2
        return dict(version=label, n=len(x), R=m, lo=lo, hi=hi, p=float(norm.sf(m / se)) if se and se > 0 else np.nan,
                    R_h1=dd["R"][half].sum() / max(dd["N"][half].sum(), 1),
                    R_h2=dd["R"][~half].sum() / max(dd["N"][~half].sum(), 1))

    rows = [stat(first["frozen"], first["ts"], "frozen, all 585-trade set"),
            stat(cov["frozen"], cov["ts"], "frozen, trades with ticks"),
            stat(cov["a_bar_spread"], cov["ts"], "(a) bar spread, trades with ticks"),
            stat(cov["b_close_entry"], cov["ts"], "(b) entry at the reopen bar's close, trades with ticks")]
    for name in DELAYS:
        x = d[(d["entry"] == name) & d["ticks"]]
        r = stat(x["R"], x["ts"], f"replay {name}")
        r["skipped"] = int(x["skipped"].sum())
        r["entry_spread_R"] = float(x["entry_spread_R"].median()) if "entry_spread_R" in x else np.nan
        r["R_long"] = float(x.loc[x["side"] > 0, "R"].mean())
        r["R_short"] = float(x.loc[x["side"] < 0, "R"].mean())
        rows.append(r)
    t = pd.DataFrame(rows)
    reps = t["version"].str.startswith("replay")
    t.loc[reps, "bh"] = M.bh(t.loc[reps, "p"].to_numpy())
    t.to_csv(OUT / "replay_summary.csv", index=False)
    print(t.round(3).to_string(index=False))
    per = d[d["ticks"] & ~d["skipped"]].groupby(["sym", "entry"])["R"].mean().unstack().round(3)
    per["frozen"] = cov.groupby("sym")["frozen"].mean().round(3)
    per["n"] = cov.groupby("sym").size()
    print("\nper pair, mean R:")
    print(per.to_string())
    ok = t[reps & (t["R"] > 0) & (t["lo"] > 0) & t["bh"].fillna(False).astype(bool)]
    print("\nVERDICT:", "tradeable at " + ", ".join(ok["version"]) if len(ok) else
          "no executable entry keeps R > 0 with its interval above 0 - the frozen pass is the bid-bar fill at the reopen")


def main():
    {"fetch": fetch, "measure": measure, "replay": replay}[os.environ.get("MODE", "replay")]()


if __name__ == "__main__":
    main()
