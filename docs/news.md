# News

`till_infinity.news` collects headlines and the economic calendar around them —
the event-proximity context a vol or regime model needs to know *why* a price
moved. No API keys.

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
| calendars | every 900s | `NEWS_CAL_POLL` |

The calendar is re-polled rather than fetched once because an event exists for
days as a forecast and only gains its `actual` at the moment of release.

## Storage

SQLite by default, and the two tables deliberately behave differently:

- **`articles`** — a headline is immutable. `INSERT OR IGNORE`, keyed on
  `(source, id)`. Re-polling a feed writes nothing.
- **`events`** — a calendar row is *rewritten* when the print lands. The upsert
  fires only when `actual`, `forecast`, `previous` or `time` actually changed,
  so a quiet poll costs nothing and a release shows up as an update.

ForexFactory supplies no event id, so one is derived from title + country +
date — stable across polls, which is what makes the rewrite work.

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

Two sources were asked for and are **not** here, both for reasons found by
probing rather than assumed:

**FRED** (US money supply, Fed balance sheet, credit facilities). Unreachable
from the machine this was built on: `fred.stlouisfed.org` and
`api.stlouisfed.org` both resolve to `104.82.240.89` but every TCP connection
times out, on the keyless `fredgraph.csv` endpoint and the root alike. The
integration is small — `fredgraph.csv?id=WALCL` returns plain CSV with no key —
but shipping it unverified would mean shipping a guess. Series worth adding
when it can be tested: `WALCL` (Fed total assets), `M2SL`, `RRPONTSYD`
(reverse repo), `WRESBAL` (reserves), `TOTBKCR` (bank credit),
`ECBASSETSW` (ECB), `JPNASSETS` (BoJ).

**IMF** (international reserves, IRFCL). The legacy SDMX host
`dataservices.imf.org` no longer exists in DNS. The replacement,
`https://api.imf.org/external/sdmx/2.1/`, does work — `IMF.STA:IRFCL` version
`12.0.0` is live and `data/IMF.STA,IRFCL,+/all` returns 200 — but an
unfiltered pull is 13 MB and the country-key layout still needs pinning down
against the datastructure before it is worth wiring in.
