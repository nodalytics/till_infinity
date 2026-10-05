"""Read-only fetch of Range Break 100/200 bars and ticks from the broker bridge into rb100/data.
Bars -> rb_bars.db (symbol, interval, ts, o,h,l,c, tick_volume, spread); ticks -> ticks/<slug>/<YYYY-MM-DD>.npz
(ts_ms int64, bid, ask float64). One request at a time, spaced; the bridge is shared with the desk."""
import os, sys, time, sqlite3
from datetime import UTC, datetime
from pathlib import Path
import httpx
import numpy as np

BASE = os.environ.get("TRADING_MT5_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
KEY = os.environ.get("TRADING_MT5_API_KEY", "")
H = {"Accept": "application/json", **({"X-API-Key": KEY} if KEY else {})}
OUT = Path(os.environ.get("OUT", os.path.expanduser("~/till_infinity/rb100/data")))
GAP = float(os.environ.get("GAP", "1.5"))
SYMS = ["Range Break 100 Index", "Range Break 200 Index"]
TF = {"1m": ("M1", 60), "15m": ("M15", 900), "1h": ("H1", 3600), "4h": ("H4", 14400), "1d": ("D1", 86400)}
st = lambda s: datetime.fromtimestamp(s, UTC).strftime("%Y-%m-%d %H:%M:%S")


def ts_of(v):
    if isinstance(v, (int, float)):
        return int(v)
    return int(datetime.fromisoformat(str(v).replace("Z", "")).replace(tzinfo=UTC).timestamp())


def ms_of(v):
    if isinstance(v, (int, float)):
        return int(v)
    return int(round(datetime.fromisoformat(str(v).replace("Z", "")).replace(tzinfo=UTC).timestamp() * 1000))


def get(c, path, params):
    for k in range(5):
        try:
            r = c.get(BASE + path, params=params)
            return r.status_code, (r.json() if r.status_code == 200 else None)
        except Exception as e:  # noqa: BLE001
            print("  retry", path, repr(e)[:100], flush=True)
            time.sleep(10 * (k + 1))
    return -1, None


def bars(c):
    OUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(OUT / "rb_bars.db")
    db.execute("CREATE TABLE IF NOT EXISTS bars (symbol TEXT, interval TEXT, ts INTEGER, open REAL, high REAL, low REAL,"
               " close REAL, tick_volume REAL, spread REAL, PRIMARY KEY(symbol, interval, ts))")
    now = time.time()
    for sym in SYMS:
        for iv, (tf, sec) in TF.items():
            start = datetime(2019, 1, 1, tzinfo=UTC).timestamp()
            span = 40000 * sec
            n = 0
            t = start
            while t < now:
                code, j = get(c, "/symbols/rates/range", {"symbol": sym, "timeframe": tf, "start": st(t), "end": st(min(now, t + span))})
                rows = j if isinstance(j, list) else []
                db.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?)",
                               [(sym, iv, ts_of(r["time"]), r["open"], r["high"], r["low"], r["close"], r.get("tick_volume"), r.get("spread")) for r in rows])
                db.commit()
                n += len(rows)
                t += span
                time.sleep(GAP)
            print(f"{sym} {iv}: {n} bars", flush=True)


def ticks(c):
    now = time.time()
    day0 = int(now // 86400) * 86400
    for sym in SYMS:
        d = OUT / "ticks" / sym.split()[2]
        d.mkdir(parents=True, exist_ok=True)
        miss = 0
        for back in range(1, 760):
            t0 = day0 - back * 86400
            f = d / (datetime.fromtimestamp(t0, UTC).strftime("%Y-%m-%d") + ".npz")
            if f.exists():
                continue
            code, j = get(c, f"/symbols/ticks/{sym}/range", {"date_from": st(t0), "date_to": st(t0 + 86400 - 0.001)})
            time.sleep(GAP)
            if code == 404:
                miss += 1
                if miss >= 5:
                    print(f"{sym}: no ticks before {st(t0)}", flush=True)
                    break
                continue
            if code != 200 or not isinstance(j, list):
                print(f"{sym} {st(t0)}: HTTP {code}", flush=True)
                continue
            miss = 0
            ms = np.array([ms_of(r.get("time_msc") or r["time"]) for r in j], np.int64)
            bid = np.array([r["bid"] for r in j], float)
            ask = np.array([r["ask"] for r in j], float)
            k = (ms >= t0 * 1000) & (ms < (t0 + 86400) * 1000)
            np.savez_compressed(f, ms=ms[k], bid=bid[k], ask=ask[k])
            if back % 20 == 0:
                print(f"{sym} {st(t0)}: {k.sum()} ticks", flush=True)


if __name__ == "__main__":
    with httpx.Client(headers=H, timeout=300) as c:
        if "bars" in sys.argv[1:]:
            bars(c)
        if "ticks" in sys.argv[1:]:
            ticks(c)
    (OUT / "fetch.flag").write_text("done\n")
    print("fetch done", flush=True)
