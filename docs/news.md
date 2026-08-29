# News

`till_infinity.news` collects headlines and the economic calendar around them -
the event-proximity context a vol or regime model needs to know *why* a price
moved.

```bash
uv run till-infinity news collect          # poll forever
uv run till-infinity news collect --once   # a single pass
uv run till-infinity news upcoming --high  # next high-impact releases
uv run till-infinity news latest           # most recent headlines
uv run till-infinity news info             # what is stored
uv run till-infinity news sources          # the configured feeds
```

## Sources

| source | what it gives |
|---|---|
| `rss` | ForexLive, FXStreet, Investing (macro/FX) and CoinDesk, CoinTelegraph (crypto) |
| `headlines` | TradingView's news feed - **symbol-attached**, with provider attribution and urgency |
| `forexfactory` | the weekly calendar JSON, keyed by currency |
| `tradingview` | the calendar service, keyed by country, with importance and raw numerics |
| `imf` | central bank reserve assets per country (IRFCL), monthly |

TradingView headlines are the one feed that arrives already tagged with the
instruments a story concerns (`OANDA:XAUUSD`, `TVC:GOLD`), so gold news lines up
against the gold series without a keyword search.

**Both calendars are kept.** They overlap, and that is the point - the same
print appears under TradingView's `GB / GDP MoM` and ForexFactory's
`GBP / GDP m/m`, so a number can be cross-checked between providers exactly the
way a price is cross-checked between brokers.

## Two clocks

Headlines arrive continuously; a calendar barely changes until a print lands.
So the sources run on separate schedules:

| | default | env |
|---|---|---|
| headlines and RSS | every 300s | `NEWS_POLL` |
| calendars and IMF | every 900s | `NEWS_CAL_POLL` |

The calendar is re-polled rather than fetched once because an event exists for
days as a forecast and only gains its `actual` at the moment of release.

## Storage

SQLite by default, and the two tables deliberately behave differently:

- **`articles`** - a headline is immutable. `INSERT OR IGNORE`, keyed on
  `(source, id)`. Re-polling a feed writes nothing.
- **`events`** - a calendar row is *rewritten* when the print lands. The upsert
  fires only when `actual`, `forecast`, `previous` or `time` actually changed,
  so a quiet poll costs nothing and a release shows up as an update.
- **`observations`** - macro series, keyed on `(source, series, time)`. Reserves
  get revised, so a changed value rewrites its row and counts as an update.

ForexFactory supplies no event id, so one is derived from title + country +
date - stable across polls, which is what makes the rewrite work.

**Times are UTC**, stored as epoch seconds. The feeds send three different date
formats - ISO-8601 with a literal `Z`, ISO with a numeric offset, and RFC 2822
`pubDate` - and all three are parsed to the same absolute instant.

```
.data/news/news.db                        # sqlite: articles + events
.data/news/news/forexlive.jsonl           # jsonl headlines, one file per source
.data/news/calendar/tradingview.jsonl     # jsonl events
```

JSONL is append-only, so a release appends a second, fuller copy of the event
rather than editing the first. Use SQLite if you want one row per event.

## Queries

The next high-impact US releases:

```sql
SELECT datetime(time,'unixepoch'), country, title, forecast, previous
FROM events
WHERE importance = 2 AND country IN ('US','USD') AND time > strftime('%s','now')
ORDER BY time LIMIT 10;
```

Everything published about gold in the last day:

```sql
SELECT datetime(published,'unixepoch'), provider, title
FROM articles
WHERE symbols LIKE '%XAUUSD%' AND published > strftime('%s','now','-1 day')
ORDER BY published DESC;
```

Surprise (actual − forecast) is computed on the `Event` model rather than
stored, since both fields are kept raw:

```python
from till_infinity.news import SqliteStore, Settings

async with SqliteStore(Settings.from_env().database) as store:
    for event in await store.upcoming(min_importance=2):
        print(event.title, event.forecast, event.surprise)
```

## Which instrument a headline is about

Publishers tag articles `VENUE:TICKER` - 641 distinct strings across 3,058
articles, and none of them the feed names the rest of this project uses.
[`news/symbols.py`](../till_infinity/news/symbols.py) maps them onto feeds,
building its table from the symbols `prices` already collects rather than from
a second hand-written list: `prices.config` already knows `BTCUSD` on Bitstamp
and `BTC-USD` on Yahoo are both `btc`, because it had to in order to collect
them, and a second copy would go stale the first time a venue was added.

The venue half is noise. `BITSTAMP:BTCUSD`, `BINANCE:BTCUSDT` and
`COINBASE:BTC-USD` are one instrument; matching on the prefix would need every
venue any publisher might name. Three passes, narrowing: the ticker as given,
the ticker stripped to bare alphanumerics (which turns `EURUSD_TOD`,
`EURUSDTDTM` and `EURUSD.SIM` into `EURUSD`), then the longest known ticker it
starts with, at six characters or more. Six is the length of a currency pair
and below it a prefix stops being evidence - `SPX` would claim anything.

44% of articles carry tags at all; 60% of those name a tracked instrument:

| feed | articles | | feed | articles |
|---|---|---|---|---|
| btc | 336 | | usdcad | 82 |
| eurusd | 275 | | nzdusd | 77 |
| gbpusd | 230 | | eth | 69 |
| usdjpy | 209 | | gold | 65 |
| audusd | 107 | | usdcnh | 45 |

The remaining 40% of tagged articles map to nothing - `XRPUSD`, `DXY`,
`POLYMARKET`, `HYPEUSD`, `USDINR`, `COIN`, `BNBUSD`, `USDKRW` - and that is the
correct answer rather than a gap. They are instruments this project does not
price, so a headline about one cannot be joined to anything. Mapping `USDINR`
to `usdjpy` because both are dollar pairs would invent a relationship, and
`EURJPY` is not `eurusd` however much of the alphabet they share.

This is what lets a headline **wake an agent** rather than merely be readable
once one is awake. See [agents.md](agents.md), "News can wake the analyst".

## Environment

`NEWS_DIR`, `NEWS_DB`, `NEWS_POLL`, `NEWS_CAL_POLL`, `NEWS_CAL_BACK_DAYS`,
`NEWS_CAL_FORWARD_DAYS`, `NEWS_CONCURRENCY`, `NEWS_RETRIES`, `NEWS_USER_AGENT`.

## Monetary policy, as data

The calendar says *when* a central bank will speak. This says what its policy
actually **is** between those dates: how much money exists, what it costs, and
what the market thinks inflation will be. Those are the inputs a rate
differential is built from, and a rate differential is most of why one currency
moves against another - so this is the sentiment layer under an FX view rather
than a separate interest.

`fred` collects thirteen series, and they are of two kinds that must not be
read as one:

| kind | series | character |
| --- | --- | --- |
| **policy stock** | `WALCL`, `M2SL`, `RRPONTSYD`, `WRESBAL`, `TOTBKCR`, `ECBASSETSW`, `JPNASSETS` | slow, revised, the ground truth of how much money exists |
| **market expectation** | `DGS2`, `DGS10`, `DFII10`, `T5YIE`, `T10YIE`, `T5YIFR` | daily, never revised, an opinion rather than a fact |

### Why daily, when CPI is monthly

Official inflation *cannot* be daily. A CPI is a multi-week survey of physical
and digital prices, so the BLS and Eurostat publish monthly or quarterly and no
amount of wanting will change it.

Markets do not wait. A **breakeven** is the nominal yield minus the
inflation-protected yield at the same maturity - what inflation is being priced
right now - and it trades every day. Live on 2026-08-27: `DGS10` 4.67 minus
`DFII10` 2.34 is 2.33, against `T10YIE` 2.31. That identity is kept as a test,
as a check on our reading rather than on the bond market: if the three stop
lining up, the parse is wrong.

Alternatives exist and are not collected. Scraped daily indices (Truflation,
the Billion Prices lineage) are a real approach and a vendor dependency with an
unaudited methodology; the breakeven is free, standard, and is what the people
setting prices are actually looking at.

### The same themes in crypto, where they invert

Crypto has no monetary policy in the FX sense, and the interesting part is
*which* half is missing.

**Issuance is fixed by protocol.** There is no committee, no meeting, no
surprise - the supply schedule is published years ahead and a halving is a
calendar entry, not a decision. So the entire "what will they do" layer that
drives FX before a central bank speaks simply does not exist. What replaces it:

| FX | crypto analogue | why |
| --- | --- | --- |
| M2, balance sheet | **stablecoin supply** | the money that actually buys the asset, and the one supply number that *is* discretionary |
| policy rate | **perp funding, basis** | the price of leverage, set by demand rather than by a committee |
| breakeven | **no clean equivalent** | nothing prices expected issuance, because issuance is not in doubt |
| foreign reserves | **exchange balances, ETF holdings** | who is holding, and where |

**Cost basis is the one that touches this system directly.** Glassnode's
long-term-holder cost-basis distribution - for instance 1.05m BTC held between
$83k and $86k while spot is near $79k - is structurally the *same object* this
repository already models. A price where a large amount of supply changed hands
is a price where a large amount of supply wants out at break-even, and that is
an origin with a size attached: unfilled interest, at a known level, with a
count behind it.

That is a genuine bridge rather than an analogy, and it is not built. It would
arrive as a level with an external provenance and a size, and the honest first
question is the one asked of every other level here - does price respect it more
than an arbitrary price the same distance away.

## Not yet included

**FRED is now included** - see above. This section used to say it was
unreachable - every TCP connection to
`api.stlouisfed.org` timed out, so the integration was left unwritten rather
than shipped unverified. **That is no longer true.** Retested with a key:

```
GET /fred/series/observations?series_id=DGS10  ->  200, data from 1962
```

Whether the earlier failure was the network, the host or the keyless endpoint
is not worth reconstructing; what matters is that it is testable now, so the
reason for leaving it out is gone.

It needs `FRED_API_KEY` and a source module in the shape of the others. Series
worth having: `WALCL` (Fed total assets), `M2SL`, `RRPONTSYD` (reverse repo),
`WRESBAL` (reserves), `TOTBKCR` (bank credit), `DGS10` and `DGS2` (the curve
the levels model would actually use), `ECBASSETSW` (ECB), `JPNASSETS` (BoJ).

## IMF reserves

Central bank reserve assets per country from IRFCL, monthly, ~19k rows for the
six default countries (USA, GBR, JPN, CHN, DEU, CHE). Three findings cost real
time and are worth keeping:

The legacy SDMX host `dataservices.imf.org` is **gone** - absent from DNS, not
merely deprecated. The live service is `api.imf.org/external/sdmx/2.1`.

The series key is `COUNTRY.INDICATOR.SECTOR.FREQUENCY` and country codes are
**ISO-3**. `US...M` returns HTTP 200 with a valid, empty document; `USA...M`
returns the data. A wrong code and an empty period are indistinguishable from
the status line, which is what makes this expensive to debug.

Series carry `SCALE="6"`, which reads as "values are in millions" and is not:
the numbers are already plain USD. US reserves for 2026-07 arrive as
`252,708,091,800` - the $252.7bn actually held. Applying the exponent would
overstate every figure by a million, so `scale` is stored as provenance and
never multiplied. Sanity check across countries, latest period:

| | USD |
|---|---|
| CHN | 3.95T |
| JPN | 1.32T |
| CHE | 1.09T |
| DEU | 536B |
| GBR | 268B |
| USA | 253B |

Set the country list with `Settings.imf_countries`.
