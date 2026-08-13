# Prices

`till_infinity.prices` fetches OHLCV candles and realtime bid/ask for the same
instrument across many brokers, then stores them.

The point of tracking one instrument across brokers is that the *differences*
are the signal: cross-broker spread, which venue leads, where quotes diverge.

**Defaults**: EURUSD, GBPUSD, gold (XAUUSD) and BTC — each from every broker
configured for it. Anything else works too.

## Commands

```bash
uv run till-infinity prices symbols            # what -s accepts
uv run till-infinity prices backfill           # deep history, all sources
uv run till-infinity prices collect            # bars + quotes together, with a ticker
uv run till-infinity prices bars               # new bars every 60s, forever
uv run till-infinity prices quotes             # stream live bid/ask, forever
uv run till-infinity prices quotes --once      # one cross-broker snapshot
uv run till-infinity prices info               # what is stored
```

`collect` is the everyday command: it sweeps candles on the slow clock while
quotes stream, and prints one compact line per tick rather than a line per
update — a glance, with the database holding the detail.

```
20:15:23 eurusd 1.15223 ·   gbpusd 1.34904 ·   gold 4,409.60 ·   btc 63,452.01 ·
20:15:32 bars  8073 new, 0 updated across 27 symbol sweeps in 13.6s
20:15:33 eurusd 1.15222 ▼   gbpusd 1.34904 ·   gold 4,409.52 ▼   btc 63,450.19 ▼
```

The price shown per instrument is the tightest-spread broker's mid, and the
arrow is its direction since the previous line. `--source` there selects candle
providers; quotes always use the socket transport.

`--once` makes `bars` and `quotes` do a single pass and exit. Without it they
run until interrupted: `bars` sweeps every `--cycle` seconds (default 60),
`quotes` streams continuously.

`bars --once` is a *full* pass, not one bar — it sweeps every symbol ×
interval asking for `--bars` recent candles each (default 300). Dedup is what
makes that cheap: only genuinely new closed bars get written.

Common options: `-i/--interval` (`1m 5m 15m 1h 2h 4h 1d`), `-S/--source`,
`--store` (`sqlite`, `jsonl`, `both`), `--bars`, `--include-partial`,
`-v/--verbose`, `-q/--quiet`, `--log-file`.

## Picking symbols

`-s` takes three forms, and they mix:

```bash
-s gold -s eurusd          # tracked instrument (aliases: xauusd, btc, bitcoin, ...)
-s OANDA:XAUUSD            # one exact TradingView series
-s AAPL -s YAHOO:GC=F      # a bare ticker goes to Yahoo
```

A bare ticker goes to Yahoo because TradingView needs a venue prefix to resolve
a symbol at all. `prices symbols <anything>` shows what a given input resolves
to before you commit to a long run.

## Instruments

Six tracked by default, each quoted by several venues — the disagreement
between them is the point, so a one-venue instrument would not earn its place.

| feed | what it is | venues |
|---|---|---|
| `gold` | spot gold | 6 TradingView + Yahoo `GC=F` |
| `btc` | bitcoin | 5 exchanges + Yahoo |
| `eurusd`, `gbpusd` | major FX | 6 each + Yahoo |
| `us100` | Nasdaq 100 | 5 + Yahoo `^NDX`, `NQ=F` |
| `spx500` | S&P 500 | 6 + Yahoo `^GSPC`, `ES=F` |

**Indices answer to whatever you call them.** `us100`, `nas100`, `nasdaq`,
`ndx`, `nq` all reach the same feed; so do `spx500`, `spx`, `us500`, `sp500`,
`s&p500`, `es`. There is no canonical name for an index in practice, so the
aliases are the interface.

The venue lists for the indices are shorter and less uniform than for FX, and
that is checked rather than assumed: brokers quote the Nasdaq CFD under
`NAS100USD`, `NAS100`, `NSXUSD` and `US100`, while SAXO, DERIV and BLACKBULL do
not carry it at all. Listing a venue that does not have a symbol would log a
`symbol_error` on every sweep, forever, for something nobody expects to appear.

Both index feeds carry the **cash index and the continuous future** — `^NDX`
with `NQ=F`, `^GSPC` with `ES=F` — because the future trades when the cash
index does not, and the gap between them at the open is itself information.

## Sources

| | TradingView | Yahoo |
|---|---|---|
| candles | chart websocket, per broker | yfinance |
| intervals | all seven | 1m/5m/15m/1h/1d native, 2h and 4h resampled from 1h |
| depth | paginated via `request_more_data` | capped per interval (1m→7d, 5m/15m→60d, 1h→729d, 1d→unlimited) |
| bid/ask | quote websocket, pushed | last trade only — no real book for FX or futures |

### Things that will otherwise surprise you

**Yahoo has no spot XAUUSD.** `XAUUSD=X` 404s, and so does `XAU=X`. Gold there
is `GC=F` (COMEX continuous) — it tracks spot closely, but it is a futures
contract, not the instrument the FX brokers quote. Treat the two as related
series, not the same one.

**FXCM is gone from TradingView.** Symbol search returns nothing for that
exchange, on any endpoint, so it is not in the feed list.

**DERIV works, but only over the websockets.** The scanner endpoint 404s on it
while the chart and quote sockets serve it fine — which is one reason the
socket is the default quote transport.

**Yahoo's minute history stops at 7 days.** Asking for 5000 1m bars gets you
whatever exists inside the window; the request start is clamped rather than
failing.

## Quote transports

`prices quotes -S <transport>`:

| | how it works |
|---|---|
| `tradingview` (default) | quote websocket. One connection, all symbols, server *pushes* every change — so a write lands the moment a broker moves, not on a timer. Covers DERIV and fills in the last price the scanner leaves null. |
| `scanner` | `scanner.tradingview.com/symbol`. Request/response, so it must be polled. Stateless and simpler to reason about; misses DERIV and returns a null last price on FX. |
| `yahoo` | last trade and previous close. |

With the default transport `--poll` does **not** control how often quotes are
captured — it only sets how often you get a summary line (and how often
`scanner`/`yahoo` re-fetch). Measured over 44 seconds with `--poll 10`, each
active venue landed ~40 rows, one per actual move; a quiet venue landed 2.

Both TradingView transports write to the **same series** — storage is keyed on
the venue (`tradingview`/`OANDA`/`XAUUSD`), not on how the quote was fetched —
so switching between them, or running one after the other, does not fragment
the store.

## Storage

SQLite is the default and the reason is dedup. The primary key is the bar's
open time, so re-running a backfill is free, and a bar that was still forming
when first seen gets **corrected** once it closes. JSONL is append-only: good
for grepping and streaming into other tools, but it can never rewrite a bar,
which is why the still-forming bar is dropped unless you pass
`--include-partial`.

```
.data/prices/prices.db                                   # sqlite: bars + quotes
.data/prices/tradingview/gold_OANDA_XAUUSD_1h.jsonl      # jsonl candles
.data/prices/quotes/tradingview/gold_OANDA_XAUUSD.jsonl  # jsonl quotes
```

Quotes are only written when the top of book actually moves; `--all-ticks`
stores every update instead.

### Schema

```sql
bars   (source, feed, venue, ticker, interval, ts, open, high, low, close,
        volume, closed, updated)   PRIMARY KEY (source, feed, venue, ticker, interval, ts)
quotes (source, feed, venue, ticker, ts, bid, ask, last, mid, spread,
        spread_bps, volume, change, change_pct)  PRIMARY KEY (…, ts)
```

**Everything is UTC.** `bars.ts` is the bar's **open** time in epoch seconds;
`quotes.ts` is epoch **milliseconds**, since quotes arrive faster than one a
second. Yahoo frames are converted with `tz_convert("UTC")` before storage, 2h
and 4h buckets are resampled with `origin="epoch"` so they align to UTC
midnight, and every timestamp printed by the CLI — including log records — is
rendered in UTC. Local time never enters the project. `bars.closed`
records whether the window had elapsed when the row was written — the UPSERT
only overwrites rows where it is 0, so history is immutable and forming bars
are not.

Cross-broker spread for one instrument is then a plain query:

```sql
SELECT venue, ts, spread_bps FROM quotes
WHERE feed = 'gold' AND ts > ? ORDER BY ts;
```

## Library use

```python
from till_infinity.prices import Settings, SqliteStore, backfill, resolve_symbols
from till_infinity.prices.models import resolve_intervals

settings = Settings.from_env()
async with SqliteStore(settings.database) as store:
    summary = await backfill(
        settings=settings,
        store=store,
        feeds=resolve_symbols(("gold", "OANDA:EURUSD")),
        intervals=resolve_intervals(("1h", "1d")),
    )
```

Streaming quotes straight into your own handler, no store involved:

```python
from till_infinity.prices import Settings, resolve_symbols, stream


async def on_quote(key, quote):
    from till_infinity.prices import WriteResult

    print(key.symbol.full, quote.bid, quote.ask, quote.spread_bps)
    return WriteResult()


await stream(settings=Settings(), feeds=resolve_symbols(("gold",)), sink=on_quote)
```

## Layout

| file | |
|---|---|
| `models.py` | `Bar`, `Quote`, `Symbol`, `Interval`, keys |
| `config.py` | feeds, symbol resolution, `Settings` |
| `source.py` | the contract candle sources implement |
| `tradingview.py` | chart websocket, candles |
| `yahoo.py` | yfinance in a thread pool, candles |
| `quotes.py` | live bid/ask — socket and scanner transports |
| `store.py` | SQLite and JSONL |
| `service.py` | concurrent sweeps, retries |

## Environment

`PRICES_DIR`, `PRICES_DB`, `PRICES_BACKFILL_BARS`, `PRICES_LIVE_BARS`,
`PRICES_CYCLE_S`, `PRICES_QUOTE_POLL`, `PRICES_QUOTE_CONCURRENCY`,
`PRICES_TV_CONCURRENCY`, `PRICES_YAHOO_CONCURRENCY`, `PRICES_RETRIES`,
`PRICES_USER_AGENT`.
