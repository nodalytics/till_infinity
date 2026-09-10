"""Pull bars and **ticks** from the broker bridge into a research database.

TradingView is a second opinion; MT5 is the price we actually trade on. For the
Deriv synthetics that is not a preference - they are generated instruments that
exist nowhere else, so the broker is the only authoritative source. yfinance has
never heard of them and ccxt is crypto.

## Ticks, which I said were unavailable and was wrong about

`trading/venues/mt5_http.py` wraps one rates route, so a first reading of it
suggested the bridge could only serve bars counted back from the present. The
bridge's own OpenAPI says otherwise:

    /api/v1/symbols/rates/range          copy_rates_range
    /api/v1/symbols/ticks/{symbol}/range copy_ticks_range
    /api/v1/symbols/book/{symbol}        market depth

The client is the limited thing, not the service. That matters more than a
convenience: `decay.py` measures what price does in the seconds after a call,
and it has been reading the **quote table**, which is a sampled stream. Ticks
are the record. A measurement whose entire subject is the first few seconds
should not be built on a sample of them if the real thing is one route away.

## Two jobs, one file

`bars` fills deep history per interval; `ticks` fills windows around whatever
the caller asks about. Ticks are enormous - a volatility index prints one a
second, so a day is ~86,000 rows per symbol - which is why they are pulled for
*windows* rather than for a span. `decay.py` needs sixty seconds around each
call, not a fortnight of everything.

## It shares the broker connection with the desk

The bridge is the same one the live trader places orders through. A research
script hammering it is a way to lose fills, so requests are spaced and the
default set of symbols is small. The desk has lost enough uptime this week
without help from research.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime

import httpx

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/data/research.db"))
BASE = os.environ.get("TRADING_MT5_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
KEY = os.environ.get("TRADING_MT5_API_KEY", "")
GAP = float(os.environ.get("GAP", "1.0"))

TIMEFRAMES = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D1",
}

#: The full generated book. Five volatility indices have 1s counterparts and
#: are the twins; 150/200/250 exist only as 1s. Boom and Crash come in matched
#: pairs, which is the mirror hypothesis in `twins.py`.
SYNTHETICS = [
    "Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index",
    "Volatility 75 Index", "Volatility 100 Index",
    "Volatility 10 (1s) Index", "Volatility 25 (1s) Index",
    "Volatility 50 (1s) Index", "Volatility 75 (1s) Index",
    "Volatility 100 (1s) Index", "Volatility 150 (1s) Index",
    "Volatility 200 (1s) Index", "Volatility 250 (1s) Index",
    "Boom 300 Index", "Boom 500 Index", "Boom 1000 Index",
    "Crash 300 Index", "Crash 500 Index", "Crash 1000 Index",
    "Jump 10 Index", "Jump 25 Index", "Jump 50 Index",
    "Jump 75 Index", "Jump 100 Index",
    "Step Index", "Range Break 100 Index", "Range Break 200 Index",
]

#: The traded book that is **not** generated - broker name to our feed slug.
#: Needed because the journal keys on our slug and the bridge on the broker's,
#: and the two disagree on nearly every instrument that is not a currency pair.
REAL = {
    "EURUSD": "eurusd", "GBPUSD": "gbpusd", "USDJPY": "usdjpy",
    "AUDUSD": "audusd", "USDCAD": "usdcad", "USDCHF": "usdchf",
    "NZDUSD": "nzdusd", "EURGBP": "eurgbp", "EURJPY": "eurjpy",
    "GBPJPY": "gbpjpy", "AUDJPY": "audjpy", "CHFJPY": "chfjpy",
    "EURAUD": "euraud", "EURCHF": "eurchf", "CADJPY": "cadjpy",
    "XAUUSD": "gold", "XAGUSD": "silver",
    "BTCUSD": "btc", "ETHUSD": "eth",
    "US Tech 100": "us100", "US 500": "spx500", "Wall Street 30": "us30",
    "Germany 40": "ger40", "UK 100": "uk100", "France 40": "fra40",
    "Australia 200": "aus200", "Japan 225": "jp225", "Hong Kong 50": "hk50",
}


def slug(name: str) -> str:
    """Broker name to the slug the journal and the harnesses key on.

    The generated series follow a rule - `Volatility 75 (1s) Index` becomes
    `volatility_75_1s_index` - and the rest do not: `XAUUSD` is `gold` and
    `US Tech 100` is `us100`. A harness joining bars to journal calls has to
    agree with the journal, so the exceptions are listed rather than derived.
    """
    if name in REAL:
        return REAL[name]
    return name.lower().replace("(", "").replace(")", "").replace("  ", " ").replace(" ", "_")


def store(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=180.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bars ("
        " feed TEXT NOT NULL, interval TEXT NOT NULL, ts INTEGER NOT NULL,"
        " open REAL, high REAL, low REAL, close REAL, volume REAL,"
        " PRIMARY KEY (feed, interval, ts))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ticks ("
        " feed TEXT NOT NULL, ts INTEGER NOT NULL, bid REAL, ask REAL,"
        " PRIMARY KEY (feed, ts, bid, ask))"
    )
    # Indexed the way the harnesses query. `prices.db` leads its index on
    # (source, venue, ticker), so filtering on `feed` scans 21 million rows and
    # sorts them - which is what made an extract take two hours before dying.
    conn.execute("CREATE INDEX IF NOT EXISTS bars_feed_iv_ts ON bars (feed, interval, ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS ticks_feed_ts ON ticks (feed, ts)")
    conn.commit()
    return conn


def when_ms(value) -> int | None:
    """Epoch milliseconds from whatever the bridge returned.

    It sends ISO strings - `2026-09-10T11:40:20` for bars and
    `2026-09-10T11:40:20.223000` for `time_msc` - not epoch numbers, which is
    what a first pass through this assumed. They carry **no timezone**, and the
    bridge answered a UTC-framed request with matching times, so they are read
    as UTC. If the terminal is ever moved to a server on a different offset,
    every timestamp here shifts silently and nothing in the data would say so -
    the check is that a tick's time lands inside the window that asked for it.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        v = float(value)
        return int(v) if v > 1e11 else int(v * 1000)
    try:
        return int(datetime.fromisoformat(str(value)).replace(tzinfo=UTC).timestamp() * 1000)
    except Exception:
        return None


def stamp(when: float) -> str:
    return datetime.fromtimestamp(when, UTC).strftime("%Y-%m-%d %H:%M:%S")


async def get(client: httpx.AsyncClient, path: str, params: dict):
    r = await client.get(f"{BASE}{path}", params=params, timeout=90.0)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
    return r.json()


def rows_of(payload):
    """The bridge returns either a list or an envelope; accept both."""
    if isinstance(payload, list):
        return payload
    for key in ("data", "rates", "ticks", "result", "items"):
        got = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(got, list):
            return got
    return []


async def do_bars(client, conn, symbols, intervals, days):
    end = time.time()
    start = end - days * 86400
    total = missing = 0
    for name in symbols:
        feed = slug(name)
        for iv in intervals:
            tf = TIMEFRAMES.get(iv)
            if not tf:
                continue
            try:
                got = rows_of(await get(client, "/symbols/rates/range", {
                    "symbol": name, "timeframe": tf,
                    "start": stamp(start), "end": stamp(end),
                }))
            except Exception as exc:
                print(f"  {feed:28s} {iv:4s} {exc}")
                await asyncio.sleep(GAP)
                continue
            kept = []
            for row in got:
                ms = when_ms(row.get("time")) if isinstance(row, dict) else None
                if ms is None:
                    continue
                kept.append((feed, iv, ms, row.get("open"), row.get("high"),
                             row.get("low"), row.get("close"),
                             row.get("tick_volume") or row.get("volume")))
            if not kept:
                missing += 1
                print(f"  {feed:28s} {iv:4s} (nothing)")
                await asyncio.sleep(GAP)
                continue
            conn.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?)", kept)
            conn.commit()
            total += len(kept)
            lo = time.strftime("%Y-%m-%d", time.gmtime(min(r[2] for r in kept) / 1000))
            hi = time.strftime("%Y-%m-%d", time.gmtime(max(r[2] for r in kept) / 1000))
            print(f"  {feed:28s} {iv:4s} {len(kept):7d}  {lo} .. {hi}")
            await asyncio.sleep(GAP)
    print(f"\n{total:,} bars written, {missing} (symbol, interval) pairs empty")


async def do_ticks(client, conn, symbols, hours):
    end = time.time()
    start = end - hours * 3600
    total = 0
    for name in symbols:
        feed = slug(name)
        try:
            got = rows_of(await get(client, f"/symbols/ticks/{name}/range", {
                "date_from": stamp(start), "date_to": stamp(end),
            }))
        except Exception as exc:
            print(f"  {feed:28s} {exc}")
            await asyncio.sleep(GAP)
            continue
        kept = []
        for row in got:
            # `time_msc` first: it is the same instant to the millisecond, and
            # a measurement about the first few seconds cannot round to one.
            ms = when_ms(row.get("time_msc")) or when_ms(row.get("time"))
            if ms is None:
                continue
            kept.append((feed, ms, row.get("bid"), row.get("ask")))
        if kept:
            conn.executemany("INSERT OR REPLACE INTO ticks VALUES (?,?,?,?)", kept)
            conn.commit()
            total += len(kept)
            lo = time.strftime("%m-%d %H:%M", time.gmtime(min(r[1] for r in kept) / 1000))
            hi = time.strftime("%m-%d %H:%M", time.gmtime(max(r[1] for r in kept) / 1000))
            print(f"  {feed:28s} {len(kept):8d} ticks  {lo} .. {hi}")
        else:
            print(f"  {feed:28s} (no ticks)")
        await asyncio.sleep(GAP)
    print(f"\n{total:,} ticks written")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("bars", "ticks", "probe"))
    ap.add_argument("--days", type=float, default=30.0)
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--intervals", default="1m,5m,15m,1h,4h,1d")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--real", action="store_true",
                    help="include the non-generated book (FX, metals, indices, crypto)")
    args = ap.parse_args()

    universe = SYNTHETICS + list(REAL) if args.real else SYNTHETICS
    symbols = [s for s in universe
               if not args.symbols or slug(s) in args.symbols or s in args.symbols]
    conn = store(OUT)
    headers = {"Accept": "application/json"}
    if KEY:
        headers["X-API-Key"] = KEY

    async with httpx.AsyncClient(headers=headers) as client:
        if args.what == "probe":
            # Ask for one bar and one minute of ticks on one symbol, so a
            # misconfigured key or a renamed route fails in five seconds rather
            # than half way through a long pull.
            name = symbols[0]
            for label, path, params in (
                ("rates/pos", "/symbols/rates/pos",
                 {"symbol": name, "timeframe": "M5", "num_bars": 3}),
                ("rates/range", "/symbols/rates/range",
                 {"symbol": name, "timeframe": "M5",
                  "start": stamp(time.time() - 3600), "end": stamp(time.time())}),
                ("ticks/range", f"/symbols/ticks/{name}/range",
                 {"date_from": stamp(time.time() - 120), "date_to": stamp(time.time())}),
            ):
                try:
                    got = rows_of(await get(client, path, params))
                    head = got[0] if got else None
                    print(f"  {label:12s} {len(got):6d} rows   {str(head)[:90]}")
                except Exception as exc:
                    print(f"  {label:12s} {exc}")
            return
        if args.what == "bars":
            print(f"{len(symbols)} symbols, {args.days:g} days -> {OUT}\n")
            await do_bars(client, conn, symbols, tuple(args.intervals.split(",")), args.days)
        else:
            print(f"{len(symbols)} symbols, {args.hours:g} hours of ticks -> {OUT}\n")
            await do_ticks(client, conn, symbols, args.hours)

    got = conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
    ticks = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
    feeds = conn.execute("SELECT COUNT(DISTINCT feed) FROM bars").fetchone()[0]
    ones = conn.execute(
        "SELECT COUNT(DISTINCT feed) FROM bars WHERE feed LIKE '%\\_1s\\_%' ESCAPE '\\'"
    ).fetchone()[0]
    print(f"\ndatabase: {got:,} bars over {feeds} feeds ({ones} are 1s series), {ticks:,} ticks")


if __name__ == "__main__":
    asyncio.run(main())
