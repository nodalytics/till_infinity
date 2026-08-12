# Using Till Infinity

From nothing to a database of cross-broker prices.

## 1. Install

Requires [uv](https://docs.astral.sh/uv/). Python 3.11 is pinned in
`.python-version`, so uv will fetch it if you do not have it.

```bash
uv sync                 # runtime + dev dependencies
uv sync --extra speed   # optional: uvloop, a faster event loop
```

Check it works:

```bash
uv run till-infinity --help
uv run till-infinity prices symbols
```

`prices symbols` prints the instruments tracked by default (EURUSD, GBPUSD,
gold, BTC) and every broker configured for each. Nothing is fetched yet.

## 2. Pull some history

Start small — one instrument, two timeframes — so you can see the shape of the
output before committing to a full run:

```bash
uv run till-infinity prices backfill -s gold -i 1h -i 1d --bars 500
```

```
  ✓ tradingview  OANDA:XAUUSD           +598 new, 0 updated
  ✓ tradingview  PEPPERSTONE:XAUUSD     +598 new, 0 updated
  ✓ tradingview  TVC:GOLD               +598 new, 0 updated
  ✓ yahoo        YAHOO:GC=F             +701 new, 0 updated
backfill: 2392 new, 0 updated across 4 symbol sweeps in 3.6s
```

Then the real thing. `--bars 5000` is about as deep as TradingView will go per
series, and each source is capped by its own retention anyway:

```bash
uv run till-infinity prices backfill --bars 5000
```

Re-running a backfill is safe and cheap — bars are keyed on their open time, so
the second run writes only what is genuinely new.

## 3. See what you have

```bash
uv run till-infinity prices info
```

```
┏━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━┳━━━━┳━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ source      ┃ feed ┃ symbol       ┃ tf ┃ bars ┃ from         ┃ to           ┃
┡━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━╇━━━━╇━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ tradingview │ gold │ OANDA:XAUUSD │ 1h │  299 │ 2026-07-24…  │ 2026-08-12…  │
└─────────────┴──────┴──────────────┴────┴──────┴──────────────┴──────────────┘
```

Everything lands in `.data/prices/prices.db` unless you pass `--db`.

## 4. Keep it current

Two long-running commands. Both stop cleanly on Ctrl-C.

```bash
uv run till-infinity prices bars     # new candles, a full sweep every 60s
uv run till-infinity prices quotes   # live bid/ask, streamed as it moves
```

`bars` fills in candles as they close. `quotes` holds a websocket open and
writes the moment a broker's book changes — it is not polling, so a busy venue
produces ~40 rows a minute and a quiet one produces two.

Add `--once` to either for a single pass, which is what you want from cron or
while testing.

Running them together, logging to file:

```bash
uv run till-infinity prices bars --log-file logs/bars.log &
uv run till-infinity prices quotes --log-file logs/quotes.log &
```

## 5. Read the data back

It is a plain SQLite file, so anything can read it:

```bash
sqlite3 .data/prices/prices.db \
  "SELECT venue, ts, close FROM bars
   WHERE feed='gold' AND interval='1h' ORDER BY ts DESC LIMIT 5;"
```

Which broker is quoting gold tightest right now:

```bash
sqlite3 .data/prices/prices.db \
  "SELECT venue, ROUND(AVG(spread_bps),2) AS bps FROM quotes
   WHERE feed='gold' GROUP BY venue ORDER BY bps;"
```

From Python, without the CLI:

```python
import asyncio
from till_infinity.prices import Settings, SeriesKey, SqliteStore, Symbol


async def main():
    settings = Settings.from_env()
    async with SqliteStore(settings.database) as store:
        key = SeriesKey("tradingview", "gold", Symbol("OANDA", "XAUUSD"), "1h")
        for bar in await store.bars(key, limit=5):
            print(bar.time, bar.close)


asyncio.run(main())
```

Pandas, via the same file:

```python
import pandas as pd, sqlite3

with sqlite3.connect(".data/prices/prices.db") as conn:
    df = pd.read_sql(
        "SELECT ts, open, high, low, close, volume FROM bars"
        " WHERE feed=? AND venue=? AND interval=? ORDER BY ts",
        conn,
        params=("gold", "OANDA", "1h"),
        index_col="ts",
    )
df.index = pd.to_datetime(df.index, unit="s", utc=True)
```

## 6. Add the context

Prices tell you *that* something moved. The news collector tells you why, and
runs the same way — poll, store, query:

```bash
uv run till-infinity news collect --once   # headlines, calendars, IMF reserves
uv run till-infinity news upcoming --high  # what is about to move the market
```

It lands in its own database (`.data/news/news.db`) with headlines, calendar
events and macro observations. Full guide: [news.md](news.md).

## 7. Get told about it

Alerts go to Telegram and Discord, to as many chats or webhooks as you list:

```bash
export TELEGRAM_BOT_TOKEN=123456:AA...
uv run till-infinity notify chats          # find your chat ids
export TELEGRAM_CHAT_IDS="ops=-1001111"
uv run till-infinity notify test           # prove it works
```

Each channel can set its own minimum level, so an on-call chat and a firehose
can share one bot. Full guide: [notifications.md](notifications.md).

## 8. Tune it

Anything you pass repeatedly belongs in the environment:

```bash
export PRICES_DB=/data/prices.db
export PRICES_CYCLE_S=30          # bars sweeps twice a minute
export PRICES_BACKFILL_BARS=5000
export NEWS_POLL=180              # headlines every three minutes
export TILL_LOG_LEVEL=DEBUG
```

Full lists in [prices.md](prices.md#environment), [news.md](news.md#environment),
[notifications.md](notifications.md#setup) and [logging.md](logging.md).

## Troubleshooting

**`symbol_not_exists` warnings.** That venue does not carry that symbol on that
endpoint. It is logged once, the sweep continues, and the other brokers are
unaffected. DERIV on the `scanner` transport is the common one — use the
default socket transport instead.

**A source returns nothing for 1m.** Check the retention caps in
[prices.md](prices.md#sources); Yahoo's minute data stops at 7 days.

**Quotes look frozen.** They probably are — outside market hours FX stops
moving, and the store only writes changes. `--all-ticks` records every update
if you want proof of liveness.

**Nothing in stdout when piping.** Log records go to stderr on purpose, so
`... | grep` sees only data. Use `2>&1` if you want both.
