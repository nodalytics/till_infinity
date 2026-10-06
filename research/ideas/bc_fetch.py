"""Read-only fetch of Boom/Crash ticks, warm-up bars and swap specs from the lab's MT5 bridge.

Frozen in `bc_rule.json` (data). One request at a time, spaced; the bridge is shared with the desk.

  OUT=$HOME/till_infinity/boomcrash/data python research/ideas/bc_fetch.py ticks bars info

Ticks -> OUT/ticks/<slug>/<YYYY-MM-DD>.npz (ms int64, bid, ask float64), one UTC day per request.
Bars  -> OUT/bars.db (symbol, interval, ts, open, high, low, close, tick_volume, spread), H1/H4/D1 from 2019.
Info  -> OUT/info.json (the bridge's symbol info, swap fields).
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

BASE = os.environ.get("TRADING_MT5_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
KEY = os.environ.get("TRADING_MT5_API_KEY", "")
HDR = {"Accept": "application/json", **({"X-API-Key": KEY} if KEY else {})}
OUT = Path(os.environ.get("OUT", os.path.expanduser("~/till_infinity/boomcrash/data")))
GAP = float(os.environ.get("GAP", "1.5"))
SYMS = ["Boom 300 Index", "Boom 500 Index", "Boom 1000 Index", "Crash 300 Index", "Crash 500 Index", "Crash 1000 Index"]
FIRST_DAY = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp())
TF = {"1h": ("H1", 3600), "4h": ("H4", 14400), "1d": ("D1", 86400)}


def slug(sym):
    return sym.lower().replace(" index", "").replace(" ", "_")


def st(s):
    return datetime.fromtimestamp(s, UTC).strftime("%Y-%m-%d %H:%M:%S")


def ts_of(v):
    if isinstance(v, (int, float)):
        return int(v)
    return int(datetime.fromisoformat(str(v).replace("Z", "")).replace(tzinfo=UTC).timestamp())


def ms_of(v):
    if isinstance(v, (int, float)):
        return int(v) if v > 1e11 else int(v * 1000)
    return int(round(datetime.fromisoformat(str(v).replace("Z", "")).replace(tzinfo=UTC).timestamp() * 1000))


def get(c, path, params=None):
    for k in range(6):
        try:
            r = c.get(BASE + path, params=params)
            return r.status_code, (r.json() if r.status_code == 200 else None)
        except Exception as e:  # noqa: BLE001 - transient: wait and retry
            print("  retry", path, repr(e)[:100], flush=True)
            time.sleep(15 * (k + 1))
    return -1, None


def ticks(c):
    last = int(time.time() // 86400) * 86400 - 86400       # the last complete UTC day
    for sym in SYMS:
        d = OUT / "ticks" / slug(sym)
        d.mkdir(parents=True, exist_ok=True)
        n_ok = 0
        for t0 in range(FIRST_DAY, last + 1, 86400):
            f = d / (datetime.fromtimestamp(t0, UTC).strftime("%Y-%m-%d") + ".npz")
            if f.exists():
                continue
            code, j = get(c, f"/symbols/ticks/{sym}/range", {"date_from": st(t0), "date_to": st(t0 + 86400 - 0.001)})
            time.sleep(GAP)
            if code == 404:
                np.savez_compressed(f, ms=np.zeros(0, np.int64), bid=np.zeros(0), ask=np.zeros(0))
                print(f"{sym} {st(t0)}: 404", flush=True)
                continue
            if code != 200 or not isinstance(j, list):
                print(f"{sym} {st(t0)}: HTTP {code}, retry on the next pass", flush=True)
                continue
            ms = np.array([ms_of(r.get("time_msc") or r["time"]) for r in j], np.int64)
            bid = np.array([r["bid"] for r in j], float)
            ask = np.array([r["ask"] for r in j], float)
            k = (ms >= t0 * 1000) & (ms < (t0 + 86400) * 1000)
            o = np.argsort(ms[k], kind="stable")
            np.savez_compressed(f, ms=ms[k][o], bid=bid[k][o], ask=ask[k][o])
            n_ok += 1
            if n_ok % 30 == 0:
                print(f"{sym} {st(t0)}: {k.sum()} ticks", flush=True)
        print(f"{sym}: done", flush=True)


def bars(c):
    OUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(OUT / "bars.db")
    db.execute("CREATE TABLE IF NOT EXISTS bars (symbol TEXT, interval TEXT, ts INTEGER, open REAL, high REAL, low REAL,"
               " close REAL, tick_volume REAL, spread REAL, PRIMARY KEY(symbol, interval, ts))")
    now = time.time()
    for sym in SYMS:
        for iv, (tf, sec) in TF.items():
            t, n, span = datetime(2019, 1, 1, tzinfo=UTC).timestamp(), 0, 40000 * sec
            while t < now:
                code, j = get(c, "/symbols/rates/range", {"symbol": sym, "timeframe": tf, "start": st(t),
                                                         "end": st(min(now, t + span))})
                rows = j if isinstance(j, list) else []
                db.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?)",
                               [(sym, iv, ts_of(r["time"]), r["open"], r["high"], r["low"], r["close"],
                                 r.get("tick_volume"), r.get("spread")) for r in rows])
                db.commit()
                n += len(rows)
                t += span
                time.sleep(GAP)
            print(f"{sym} {iv}: {n} bars", flush=True)


def info(c):
    out = {}
    for sym in SYMS:
        for path in (f"/symbols/info/{sym}", "/symbols/info"):
            code, j = get(c, path, None if path.endswith(sym) else {"symbol": sym})
            time.sleep(GAP)
            if code == 200 and j:
                out[sym] = j
                break
    (OUT / "info.json").write_text(json.dumps(out, indent=1, default=str))
    print("info:", {k: {f: v.get(f) for f in ("swap_mode", "swap_long", "swap_short", "point", "digits")}
                    for k, v in out.items() if isinstance(v, dict)}, flush=True)


if __name__ == "__main__":
    import httpx
    with httpx.Client(headers=HDR, timeout=600) as c:
        if "info" in sys.argv[1:]:
            info(c)
        if "bars" in sys.argv[1:]:
            bars(c)
        if "ticks" in sys.argv[1:]:
            ticks(c)
    (OUT / "fetch.flag").write_text("done\n")
    print("fetch done", flush=True)
