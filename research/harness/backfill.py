"""Pull deep history from TradingView into a research database of our own.

Every measurement in `research/` currently reads `prices.db`, which is the
production instance's store. That is one dependency doing three jobs and it has
failed at all three today:

* **It is not deep enough.** It holds what the live collector has gathered since
  the instance was last cold-started. A structure-function estimate or a
  lead-lag across timeframes wants years, not weeks.
* **It is not complete.** The 1s volatility indices produce calls on the live
  path and returned *no rows* from the bars table, so a harness reading it
  silently measures a book missing several instruments.
* **Reading it costs production.** It lives on a two-core box behind a 2.6GB
  container limit, and querying it for research OOM-killed the live desk three
  times on 2026-09-10 (`research/starving.md`).

`prices/tradingview.py` already solves the collection problem - per-broker
OHLCV, no API key, and `request_more_data` pagination so depth is not capped at
one 5,000-bar request. What was missing is something that drives it for
*research* rather than for the live path, and writes somewhere production never
touches.

## What this is not

It is not a second live collector and it must never become one. It runs by hand
on the research machine, writes to its own file, and nothing in the trading path
reads what it produces. Two collectors writing one store is how a price series
acquires two versions of the same bar with different values, and no measurement
survives that.

## Depth is requested per interval, not uniformly

5,000 bars is sixteen hours at 1m and fifty-four years at 1w. Asking for the
same count everywhere would spend the whole budget on the fine end and return
almost nothing usable at the coarse. The depth below is chosen so each interval
covers a comparable *span*, which is what a cascade test across timeframes
needs - see `research/cascading.md`.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import time

REPO = os.environ.get("REPO", os.path.expanduser("~/till_infinity/repo"))
sys.path.insert(0, REPO)

from till_infinity.prices.config import Settings  # noqa: E402
from till_infinity.prices.models import INTERVALS, Bar, Symbol  # noqa: E402
from till_infinity.prices.source import Job  # noqa: E402
from till_infinity.prices.tradingview import TradingViewSource  # noqa: E402

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/data/research.db"))

#: Bars to request per interval. Chosen for comparable span rather than a flat
#: count: 5,000 is sixteen hours at 1m and a decade at 1d.
DEPTH = {
    "1m": 5_000,
    "5m": 5_000,
    "15m": 5_000,
    "1h": 5_000,
    "4h": 5_000,
    "1d": 5_000,
}

#: `venue:ticker` as TradingView names them, mapped to our own feed slug.
#: Deriv publishes its synthetics on TradingView, which is the only public
#: source for them - yfinance has no idea they exist and ccxt is crypto only.
SYMBOLS = {
    "eurusd": ("OANDA", "EURUSD"),
    "gbpusd": ("OANDA", "GBPUSD"),
    "usdjpy": ("OANDA", "USDJPY"),
    "audjpy": ("OANDA", "AUDJPY"),
    "gold": ("OANDA", "XAUUSD"),
    "silver": ("OANDA", "XAGUSD"),
    "spx500": ("OANDA", "SPX500USD"),
    "us100": ("OANDA", "NAS100USD"),
    "btc": ("BITSTAMP", "BTCUSD"),
}


def store(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=120.0)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bars ("
        " feed TEXT NOT NULL, interval TEXT NOT NULL, ts INTEGER NOT NULL,"
        " open REAL, high REAL, low REAL, close REAL, volume REAL,"
        " PRIMARY KEY (feed, interval, ts))"
    )
    # Indexed the way the harnesses actually query, which `prices.db` is not:
    # its index leads on (source, venue, ticker), so a filter on `feed` scans
    # 21 million rows and sorts them. That is what made an extract take two
    # hours and then get OOM-killed.
    conn.execute("CREATE INDEX IF NOT EXISTS bars_feed_iv_ts ON bars (feed, interval, ts)")
    conn.commit()
    return conn


async def main() -> None:
    only = tuple(f for f in os.environ.get("FEEDS", "").split(",") if f)
    intervals = tuple(os.environ.get("INTERVALS", "1m,5m,15m,1h,4h,1d").split(","))
    conn = store(OUT)
    settings = Settings.from_env()
    source = TradingViewSource(settings)

    wanted = {k: v for k, v in SYMBOLS.items() if not only or k in only}
    print(f"{len(wanted)} feeds x {len(intervals)} intervals -> {OUT}\n")

    total = 0
    for feed, (venue, ticker) in wanted.items():
        for name in intervals:
            iv = INTERVALS.get(name)
            if iv is None:
                print(f"  {feed} {name}: unknown interval, skipping")
                continue
            rows: list[Bar] = []

            async def sink(_key, bars, _rows=rows):
                _rows.extend(bars)
                return None

            job = Job(
                source="tradingview",
                feed=feed,
                symbol=Symbol(venue, ticker),
                intervals=(iv,),
            )
            try:
                await source.fetch(job, DEPTH.get(name, 5_000), sink)
            except Exception as exc:
                print(f"  {feed} {name}: {type(exc).__name__}: {exc}")
                continue
            # `Bar.time` is the bar's **open** time in epoch *seconds*; the
            # production store keys on milliseconds, so this converts rather
            # than inventing a third convention for the harnesses to trip on.
            kept = [
                (feed, name, int(b.time) * 1000, b.open, b.high, b.low, b.close, b.volume)
                for b in rows
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?)", kept
            )
            conn.commit()
            total += len(kept)
            span = ""
            if kept:
                lo = time.strftime("%Y-%m-%d", time.gmtime(min(r[2] for r in kept) / 1000))
                hi = time.strftime("%Y-%m-%d", time.gmtime(max(r[2] for r in kept) / 1000))
                span = f"  {lo} .. {hi}"
            print(f"  {feed:10s} {name:4s} {len(kept):6d} bars{span}")
            await asyncio.sleep(settings.tv_request_gap)

    print(f"\n{total:,} bars written to {OUT}")
    got = conn.execute("SELECT COUNT(*), COUNT(DISTINCT feed) FROM bars").fetchone()
    print(f"database now holds {got[0]:,} bars over {got[1]} feeds")


if __name__ == "__main__":
    asyncio.run(main())
