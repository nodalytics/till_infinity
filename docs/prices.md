# Prices

`till_infinity.prices` fetches OHLCV candles and realtime bid/ask for the same
instrument across many brokers, then stores them.

The point of tracking one instrument across brokers is that the *differences*
are the signal: cross-broker spread, which venue leads, where quotes diverge.

**Defaults**: EURUSD, GBPUSD, gold (XAUUSD) and BTC - each from every broker
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
update - a glance, with the database holding the detail.

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

`bars --once` is a *full* pass, not one bar - it sweeps every symbol ×
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

Fourteen tracked by default, each quoted by several venues - the disagreement
between them is the point, so a one-venue instrument would not earn its place.

| feed | what it is | venues |
|---|---|---|
| `gold` | spot gold | 6 TradingView + Yahoo `GC=F` |
| `btc` | bitcoin | 6 exchanges + Yahoo `BTC-USD` |
| `eth` | ether | 6 exchanges + Yahoo `ETH-USD` |
| `sol` | solana | 6 exchanges + Yahoo `SOL-USD` |
| `eurusd`, `gbpusd` | major FX | 6 each + Yahoo |
| `usdjpy`, `audusd`, `usdcad`, `usdchf`, `nzdusd` | the rest of the majors | 6 each + Yahoo |
| `usdcnh` | offshore yuan | 6 + Yahoo `CNH=X` |
| `us100` | Nasdaq 100 | 5 + Yahoo `^NDX`, `NQ=F` |
| `spx500` | S&P 500 | 6 + Yahoo `^GSPC`, `ES=F` |

**The seven majors are tracked together because they are one basket priced
against one currency.** A dollar move shows up in all of them at once, and
holding only two of them meant reading a dollar story as a euro story.

**`usdcny` is an alias onto `usdcnh`, not a feed.** Onshore CNY is carried by
exactly one of our venues, which is below the three-venue quorum a consensus
bar needs - so a `usdcny` feed would form no levels and would do it silently,
the failure that looks exactly like a quiet market. CNH is the rate that trades
outside the mainland's daily band and all six venues quote it.

**Instruments answer to whatever you call them.** `us100`, `nas100`, `nasdaq`,
`ndx`, `nq` all reach the same feed; so do `spx500`, `spx`, `us500`, `sp500`,
`s&p500`, `es`. There is no canonical name for an index in practice, so the
aliases are the interface. The same holds for crypto - `eth`, `ether`,
`ethereum`, `ethusdt` are one feed, as are `sol`, `solana`, `solusdt` - and for
the majors under their desk names: `yen`, `aussie`, `loonie`, `swissy`, `kiwi`.

**Every venue on a feed was checked against the live socket before it was
listed**, rather than assumed from a sibling. The three crypto feeds share
Binance, Bybit, Coinbase, Bitstamp, Kraken and Deriv - but Bybit quotes BTC and
ETH in both USD and USDT while carrying SOL only in USDT, so the USDT pair is
what all three have in common. Guessing the other way costs a `symbol_error`
on every sweep, forever, which is the same reason SAXO and DERIV are absent
from `us100`.

The venue lists for the indices are shorter and less uniform than for FX, and
that is checked rather than assumed: brokers quote the Nasdaq CFD under
`NAS100USD`, `NAS100`, `NSXUSD` and `US100`, while SAXO, DERIV and BLACKBULL do
not carry it at all. Listing a venue that does not have a symbol would log a
`symbol_error` on every sweep, forever, for something nobody expects to appear.

Both index feeds carry the **cash index and the continuous future** - `^NDX`
with `NQ=F`, `^GSPC` with `ES=F` - because the future trades when the cash
index does not, and the gap between them at the open is itself information.

## Sources

| | TradingView | Yahoo | ccxt | broker (MT5) |
|---|---|---|---|---|
| candles | chart websocket, per broker | yfinance | `fetch_ohlcv`, per exchange | bridge, per symbol |
| intervals | all seven | 1m/5m/15m/1h/1d native, 2h and 4h resampled from 1h | those the exchange names natively | all seven |
| depth | paginated via `request_more_data` | capped per interval (1m→7d, 5m/15m→60d, 1h→729d, 1d→unlimited) | per-exchange `limit` | bridge default |
| bid/ask | quote websocket, pushed | last trade only - no real book for FX or futures | not collected - candles only | bridge tick |
| instruments | named in `SYMBOLS` | named in `SYMBOLS` | **discovered** | `PRICES_BROKER_SYMBOLS` |

### ccxt is the only source that picks its own instruments

Every other source is given a list. ccxt is given *filters* and finds the
list: it reads each exchange's board, drops what is wide, dead, newly listed
or not a perpetual **on that exchange**, ranks what survives by summed 24h
quote volume **across** exchanges, and registers the top slice as ordinary
feeds. A pair several of them carry becomes one feed with a symbol per
exchange, which is the same shape a TradingView instrument has - so the
consensus layer compares crypto venues exactly as it compares FX brokers.

The cut is global and applied once. Applying `PRICES_CCXT_TOP` per exchange
and merging would give the union of several top-250s, which is neither 250
pairs nor the 250 largest.

Off unless a filter says how much to carry, so a deployment that has not opted
in pays no start-up call. See `.env.example` for the block and
[research/crypto.md](../research/crypto.md) for what each exchange answers.

**Funding rates, open interest and the long/short split are written and not
wired.** `prices/funding.py` and `prices/positioning.py` are library code with
no caller: the collection loop does not run them and nothing is stored. They
are listed here so nobody goes looking for the data expecting to find it.

### Things that will otherwise surprise you

**Yahoo has no spot XAUUSD.** `XAUUSD=X` 404s, and so does `XAU=X`. Gold there
is `GC=F` (COMEX continuous) - it tracks spot closely, but it is a futures
contract, not the instrument the FX brokers quote. Treat the two as related
series, not the same one.

**FXCM is gone from TradingView.** Symbol search returns nothing for that
exchange, on any endpoint, so it is not in the feed list.

**DERIV works, but only over the websockets.** The scanner endpoint 404s on it
while the chart and quote sockets serve it fine - which is one reason the
socket is the default quote transport.

**Yahoo's minute history stops at 7 days.** Asking for 5000 1m bars gets you
whatever exists inside the window; the request start is clamped rather than
failing.

## Quote transports

`prices quotes -S <transport>`:

| | how it works |
|---|---|
| `tradingview` (default) | quote websocket. One connection, all symbols, server *pushes* every change - so a write lands the moment a broker moves, not on a timer. Covers DERIV and fills in the last price the scanner leaves null. |
| `scanner` | `scanner.tradingview.com/symbol`. Request/response, so it must be polled. Stateless and simpler to reason about; misses DERIV and returns a null last price on FX. |
| `yahoo` | last trade and previous close. |

With the default transport `--poll` does **not** control how often quotes are
captured - it only sets how often you get a summary line (and how often
`scanner`/`yahoo` re-fetch). Measured over 44 seconds with `--poll 10`, each
active venue landed ~40 rows, one per actual move; a quiet venue landed 2.

Both TradingView transports write to the **same series** - storage is keyed on
the venue (`tradingview`/`OANDA`/`XAUUSD`), not on how the quote was fetched -
so switching between them, or running one after the other, does not fragment
the store.

## The broker's own book

Every other source here is somebody else's opinion of the price.
`PRICES_BROKER_SYMBOLS` adds instruments read straight from the trading
terminal over the MT5 bridge, and it is off unless set.

Two reasons it is worth having. **Coverage**: the consensus venues carry the
majors and nothing else, while the account offers 798 symbols, 71 of them
synthetics - which have no underlying and therefore no other source by
construction. Without this they cannot be traded at all, because `structures`
builds levels out of quotes and there are none to build from. **Agreement**: a
level built from six venues and an order filled on one broker's book answer
slightly different questions, and that gap is what `dislocation` exists to
police. A level built from the broker's own quotes has no gap.

```
PRICES_BROKER_SYMBOLS="Volatility 75 Index,Step Index,Boom 1000 Index"
```

The broker's own name is the symbol, verbatim - nothing is guessed or probed.
The feed name is a slug of it (`volatility_75_index`), because feed names
travel through journal keys and log lines. A name the account does not carry
simply never quotes and says so once.

**It polls; there is no stream.** The bridge publishes no websocket and no SSE
- forty-seven routes, and its only `subscribe` is
`/symbols/book/{symbol}/subscribe`, which is MT5 market *depth* and is itself
read by polling. "Stream prices from the terminal" is the obvious way to
describe the goal and is not what the transport does.

**A symbol has to be selected before it will quote, and skipping that is
silent.** MT5 only streams ticks for symbols in Market Watch; an unselected one
answers the tick endpoint with `bid 0.0, ask 0.0, time 0` - HTTP 200,
well-formed, and empty. Measured on the live bridge:

| symbol | before select | after select |
| --- | --- | --- |
| Volatility 75 Index | `0.0 / 0.0` | `51418.35 / 51436.01` |
| Step Index | `0.0 / 0.0` | `7731.6 / 7731.7` |

So `prepare` selects every symbol once at start-up. Without it the source polls
happily and publishes nothing, which is the failure that looks like working
code.

**The tick's own time is kept, not restamped.** A frozen tick time is how a
shut market is recognised - see `_shut_for` in [trading.md](trading.md) - and
overwriting it with `time.time()` would erase exactly that evidence. Synthetics
are the interesting case here: they quoted normally on a Saturday, when every
real market on the account was hours stale.

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
midnight, and every timestamp printed by the CLI - including log records - is
rendered in UTC. Local time never enters the project. `bars.closed`
records whether the window had elapsed when the row was written - the UPSERT
only overwrites rows where it is 0, so history is immutable and forming bars
are not.

Cross-broker spread for one instrument is then a plain query:

```sql
SELECT venue, ts, spread_bps FROM quotes
WHERE feed = 'gold' AND ts > ? ORDER BY ts;
```

### Retention

Nothing expires on its own. Bars accumulate for as long as the collector runs,
and on a 6.7GB box that is the constraint which bites first - 1m candles across
fourteen instruments and six venues are most of the growth.

```bash
till-infinity prices prune                 # keep 1,000 bars per series
till-infinity prices prune --keep 500      # tighter
till-infinity prices prune --vacuum        # ...and actually shrink the file
```

It reports what it would delete and asks before doing it. `--yes` skips the
question, which is what a cron entry wants.

**Per series, and by count.** The unit is `(source, feed, venue, ticker,
interval)`, so a quiet weekly series is never pruned to make room for a busy
1m one - a whole-table cap would do exactly that. A count rather than a cutoff
date because the models consume a *window of bars*. `Engine.seed` reads
`bars * 8` rows per `(feed, interval)` - 4,000 - shared across the dozen
venue-and-source series making up one instrument's timeframe, so each needs
around 333; 1,000 is three times that. One number also self-scales into roughly
the horizon each timeframe's evidence survives anyway - 1,000 bars is about
seventeen hours of 1m and about nineteen years of 1w - so no table of
per-interval durations is needed.

**Size it against the data, not a formula.** The first version took four times
the engine's window and landed on 2,000, which was above every series that
existed: the largest on production held 1,733 bars and the average 602, so it
would have deleted nothing while reporting success.

**Deleting does not shrink the file.** SQLite frees the pages for reuse, so
growth stops and the size does not fall. `--vacuum` rebuilds the file and does
shrink it, measurably: 84.4MB → 15.9MB pruning a real database to 200 bars a
series. It needs room for a second copy while it runs, which is precisely what
is scarce when retention is being reached for, so it is off by default.

**Quotes are left alone, and that is now questionable.** The reasoning was that
they feed the spread median which prices every level call, and that the store's
dedup bounds them. The dedup only drops *unchanged* top-of-book, which on a
moving market bounds very little: production holds **1,775,491 quote rows
against 536,827 bars**, so quotes are three times the thing retention actually
prunes. Worth revisiting - the spread median reads a window of the recent ones
and has no use for last month's.

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
| `quotes.py` | live bid/ask - socket and scanner transports |
| `store.py` | SQLite and JSONL |
| `service.py` | concurrent sweeps, retries |

## Environment

`PRICES_DIR`, `PRICES_DB`, `PRICES_BACKFILL_BARS`, `PRICES_LIVE_BARS`,
`PRICES_CYCLE_S`, `PRICES_QUOTE_POLL`, `PRICES_QUOTE_CONCURRENCY`,
`PRICES_TV_CONCURRENCY`, `PRICES_YAHOO_CONCURRENCY`, `PRICES_RETRIES`,
`PRICES_USER_AGENT`.

Crypto, all off by default: `PRICES_CCXT_EXCHANGES` (comma-separated; falls
back to `PRICES_CCXT_EXCHANGE`), `PRICES_CCXT_MARKET_TYPE`,
`PRICES_CCXT_SWAPS_ONLY`, `PRICES_CCXT_TOP`, `PRICES_CCXT_MIN_VOLUME`,
`PRICES_CCXT_MAX_SPREAD`, `PRICES_CCXT_MIN_DAYS`, `PRICES_CCXT_MIN_PRICE`,
`PRICES_CCXT_MIN_RANGE`, `PRICES_CCXT_QUOTES`.

Discovery is skipped entirely unless one of `TOP`, `MIN_VOLUME` or `QUOTES` is
set, so a deployment that has not opted in makes no exchange call at all.
