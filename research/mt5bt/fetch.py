"""Pull bars **with their spread**, ticks and symbol specs from the MT5 bridge into the mt5bt store.

`research/harness/mt5fill.py` keeps bars without the spread, which a CFD backtest needs. This
keeps it, plus the broker's symbol info parsed exactly as production parses it.

    python research/mt5bt/fetch.py specs --symbols EURUSD,XAUUSD
    python research/mt5bt/fetch.py bars  --symbols EURUSD --intervals 15m,1h --days 730
    python research/mt5bt/fetch.py ticks --symbols EURUSD --start 2026-09-01 --end 2026-09-02

It shares the broker connection with the live desk: requests are spaced (GAP seconds), long
ranges are fetched in chunks, and it is run niced on the lab - never on the production hosts.
How deep the history goes is the broker's server's choice; MT5 serves what it holds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))

from mt5fill import TIMEFRAMES, rows_of, stamp, when_ms  # noqa: E402

from till_infinity.trading.venues.mt5_http import _spec_from  # noqa: E402

DB = os.environ.get("MT5BT_DB", os.path.expanduser("~/till_infinity/data/mt5bt.db"))
BASE = os.environ.get("TRADING_MT5_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
KEY = os.environ.get("TRADING_MT5_API_KEY", "")
ACCOUNT = os.environ.get("MT5BT_ACCOUNT_CCY", "USD")
GAP = float(os.environ.get("GAP", "1.0"))
CHUNK_DAYS = {"1m": 20, "5m": 60, "15m": 180, "30m": 365, "1h": 730, "4h": 3000, "1d": 20000}


def store(path: str = DB) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=180.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bars (symbol TEXT NOT NULL, interval TEXT NOT NULL,
            ts INTEGER NOT NULL, open REAL, high REAL, low REAL, close REAL, volume REAL,
            spread REAL, PRIMARY KEY (symbol, interval, ts));
        CREATE TABLE IF NOT EXISTS ticks (symbol TEXT NOT NULL, ts_ms INTEGER NOT NULL,
            bid REAL, ask REAL, PRIMARY KEY (symbol, ts_ms, bid, ask));
        CREATE TABLE IF NOT EXISTS specs (symbol TEXT PRIMARY KEY, spec TEXT, raw TEXT,
            fetched INTEGER);
    """)
    return conn


async def get(client, path, params=None):
    r = await client.get(f"{BASE}{path}", params=params or {}, timeout=120.0)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
    return r.json()


async def do_specs(client, conn, symbols):
    for name in symbols:
        raw = None
        for path in (f"/symbols/info/{name}", f"/symbols/{name}"):
            try:
                raw = await get(client, path)
                break
            except Exception:
                continue
        if not isinstance(raw, dict):
            print(f"  {name:20s} no spec")
            continue
        raw = raw.get("data", raw) if isinstance(raw.get("data"), dict) else raw
        spec = _spec_from(raw, name, ACCOUNT)
        conn.execute("INSERT OR REPLACE INTO specs VALUES (?,?,?,?)",
                     (name, json.dumps(asdict(spec)), json.dumps(raw), int(time.time())))
        conn.commit()
        print(f"  {name:20s} tick {spec.tick_size:g} = {spec.tick_value:g} {ACCOUNT}, "
              f"lot {spec.volume_min:g}/{spec.volume_step:g}, swap {spec.swap_long:g}/"
              f"{spec.swap_short:g} mode {spec.swap_mode}")
        await asyncio.sleep(GAP)


async def do_bars(client, conn, symbols, intervals, days):
    end = time.time()
    for name in symbols:
        for iv in intervals:
            tf = TIMEFRAMES[iv]
            total, t1 = 0, end
            start = end - days * 86400
            while t1 > start:
                t0 = max(start, t1 - CHUNK_DAYS.get(iv, 180) * 86400)
                try:
                    got = rows_of(await get(client, "/symbols/rates/range", {
                        "symbol": name, "timeframe": tf, "start": stamp(t0), "end": stamp(t1)}))
                except Exception as exc:
                    print(f"  {name:20s} {iv:4s} {stamp(t0)}: {exc}")
                    got = []
                rows = []
                for r in got:
                    ms = when_ms(r.get("time")) if isinstance(r, dict) else None
                    if ms is not None:
                        rows.append((name, iv, ms // 1000, r.get("open"), r.get("high"),
                                     r.get("low"), r.get("close"),
                                     r.get("tick_volume") or r.get("volume"), r.get("spread")))
                conn.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?)", rows)
                conn.commit()
                total += len(rows)
                await asyncio.sleep(GAP)
                if not got:  # the server holds nothing older
                    break
                t1 = t0
            print(f"  {name:20s} {iv:4s} {total:8d} bars")


async def do_ticks(client, conn, symbols, start, end, hours_per_call=6):
    for name in symbols:
        total, t0 = 0, start
        while t0 < end:
            t1 = min(end, t0 + hours_per_call * 3600)
            try:
                got = rows_of(await get(client, f"/symbols/ticks/{name}/range",
                                        {"date_from": stamp(t0), "date_to": stamp(t1)}))
            except Exception as exc:
                print(f"  {name:20s} {stamp(t0)}: {exc}")
                got = []
            rows = []
            for r in got:
                ms = when_ms(r.get("time_msc")) or when_ms(r.get("time"))
                if ms is not None:
                    rows.append((name, ms, r.get("bid"), r.get("ask")))
            conn.executemany("INSERT OR REPLACE INTO ticks VALUES (?,?,?,?)", rows)
            conn.commit()
            total += len(rows)
            t0 = t1
            await asyncio.sleep(GAP)
        print(f"  {name:20s} {total:9d} ticks")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("specs", "bars", "ticks"))
    ap.add_argument("--symbols", required=True, help="broker names, comma separated")
    ap.add_argument("--intervals", default="15m,1h")
    ap.add_argument("--days", type=float, default=365.0)
    ap.add_argument("--start")
    ap.add_argument("--end")
    args = ap.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    conn = store()
    headers = {"Accept": "application/json"} | ({"X-API-Key": KEY} if KEY else {})
    async with httpx.AsyncClient(headers=headers) as client:
        if args.what == "specs":
            await do_specs(client, conn, symbols)
        elif args.what == "bars":
            await do_bars(client, conn, symbols, args.intervals.split(","), args.days)
        else:
            import pandas as pd
            s = pd.Timestamp(args.start, tz="UTC").timestamp()
            e = pd.Timestamp(args.end, tz="UTC").timestamp()
            await do_ticks(client, conn, symbols, s, e)
    print(f"-> {DB}")


if __name__ == "__main__":
    asyncio.run(main())
