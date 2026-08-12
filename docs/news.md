# News

`till_infinity.news` collects headlines and the economic calendar around them —
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
| `headlines` | TradingView's news feed — **symbol-attached**, with provider attribution and urgency |
| `forexfactory` | the weekly calendar JSON, keyed by currency |
| `tradingview` | the calendar service, keyed by country, with importance and raw numerics |
| `imf` | central bank reserve assets per country (IRFCL), monthly |

TradingView headlines are the one feed that arrives already tagged with the
instruments a story concerns (`OANDA:XAUUSD`, `TVC:GOLD`), so gold news lines up
against the gold series without a keyword search.

**Both calendars are kept.** They overlap, and that is the point — the same
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

- **`articles`** — a headline is immutable. `INSERT OR IGNORE`, keyed on
  `(source, id)`. Re-polling a feed writes nothing.
- **`events`** — a calendar row is *rewritten* when the print lands. The upsert
  fires only when `actual`, `forecast`, `previous` or `time` actually changed,
  so a quiet poll costs nothing and a release shows up as an update.
- **`observations`** — macro series, keyed on `(source, series, time)`. Reserves
  get revised, so a changed value rewrites its row and counts as an update.

ForexFactory supplies no event id, so one is derived from title + country +
date — stable across polls, which is what makes the rewrite work.

**Times are UTC**, stored as epoch seconds. The feeds send three different date
formats — ISO-8601 with a literal `Z`, ISO with a numeric offset, and RFC 2822
`pubDate` — and all three are parsed to the same absolute instant.

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

## Environment

`NEWS_DIR`, `NEWS_DB`, `NEWS_POLL`, `NEWS_CAL_POLL`, `NEWS_CAL_BACK_DAYS`,
`NEWS_CAL_FORWARD_DAYS`, `NEWS_CONCURRENCY`, `NEWS_RETRIES`, `NEWS_USER_AGENT`.

## Not yet included

**FRED** (US money supply, Fed balance sheet, credit facilities). Unreachable
from the machine this was built on: `fred.stlouisfed.org` and
`api.stlouisfed.org` both resolve to `104.82.240.89` but every TCP connection
times out, on the keyless `fredgraph.csv` endpoint and the root alike. The
integration is small — `fredgraph.csv?id=WALCL` returns plain CSV with no key —
but shipping it unverified would mean shipping a guess. Series worth adding
when it can be tested: `WALCL` (Fed total assets), `M2SL`, `RRPONTSYD`
(reverse repo), `WRESBAL` (reserves), `TOTBKCR` (bank credit),
`ECBASSETSW` (ECB), `JPNASSETS` (BoJ).

## IMF reserves

Central bank reserve assets per country from IRFCL, monthly, ~19k rows for the
six default countries (USA, GBR, JPN, CHN, DEU, CHE). Three findings cost real
time and are worth keeping:

The legacy SDMX host `dataservices.imf.org` is **gone** — absent from DNS, not
merely deprecated. The live service is `api.imf.org/external/sdmx/2.1`.

The series key is `COUNTRY.INDICATOR.SECTOR.FREQUENCY` and country codes are
**ISO-3**. `US...M` returns HTTP 200 with a valid, empty document; `USA...M`
returns the data. A wrong code and an empty period are indistinguishable from
the status line, which is what makes this expensive to debug.

Series carry `SCALE="6"`, which reads as "values are in millions" and is not:
the numbers are already plain USD. US reserves for 2026-07 arrive as
`252,708,091,800` — the $252.7bn actually held. Applying the exponent would
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
