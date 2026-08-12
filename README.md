<p align="center">
  <img src="docs/logo.svg" alt="Till Infinity" width="150">
</p>

<h1 align="center">Till Infinity</h1>

<p align="center">
  Market data for gold, BTC and FX — the same instrument priced by many brokers
  at once, with the news and macro releases that move it.
  <br>No API keys.
</p>

<p align="center">
  <a href="https://github.com/nodalytics/till_infinity/actions/workflows/ci.yml">
    <img src="https://github.com/nodalytics/till_infinity/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
</p>

The point of collecting one instrument from six venues is that the
*differences* are the signal: cross-broker spread, which venue leads, where
quotes diverge — and, alongside them, the calendar entry that explains the
move.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.11 is pinned in `.python-version`.

```bash
uv sync                 # runtime + dev deps
uv sync --extra speed   # adds uvloop
```

## Prices

OHLCV candles and realtime bid/ask for the same instrument across many brokers,
from TradingView and Yahoo. No API keys.

```bash
uv run till-infinity prices backfill      # deep history
uv run till-infinity prices collect       # bars + quotes together, with a ticker
uv run till-infinity prices bars          # new bars every 60s, forever
uv run till-infinity prices quotes        # stream live bid/ask, forever
uv run till-infinity prices info          # what is stored
```

Defaults to EURUSD, GBPUSD, gold and BTC; `-s` takes anything else
(`-s OANDA:XAUUSD`, `-s AAPL`). Full guide: **[docs/prices.md](docs/prices.md)**.

## News

Headlines, the economic calendar around them, and central bank reserves — from
five RSS feeds, TradingView, ForexFactory and the IMF.

```bash
uv run till-infinity news collect         # poll headlines + calendars + IMF
uv run till-infinity news upcoming --high # next high-impact releases
uv run till-infinity news latest          # recent headlines
```

Two calendars are kept side by side on purpose, so a print can be cross-checked
between providers. Full guide: **[docs/news.md](docs/news.md)**.

## Notifications

Alerts to Telegram and Discord, fanned out across as many chats or webhooks as
you list, with per-channel level routing.

```bash
uv run till-infinity notify chats          # discover Telegram chat ids
uv run till-infinity notify test           # prove the wiring
uv run till-infinity notify send "..." -l warning
```

Full guide: **[docs/notifications.md](docs/notifications.md)**.

## Where it lands

SQLite by default, under `.data/` and gitignored. JSONL alongside it with
`--store both`.

```
.data/prices/prices.db    bars + quotes
.data/news/news.db        articles + events + observations
```

Everything is stored as epoch seconds in **UTC** — local time never enters the
project. Re-running a collector is cheap and safe: bars key on their open time,
headlines on their id, calendar events get rewritten in place when the print
lands.

## Docs

| | |
|---|---|
| [docs/getting-started.md](docs/getting-started.md) | **start here** — install to stored data, and how to read it back |
| [docs/prices.md](docs/prices.md) | candles, quotes, sources, storage, schema, library use |
| [docs/news.md](docs/news.md) | headlines, economic calendar, event storage |
| [docs/notifications.md](docs/notifications.md) | Telegram and Discord alerts, channels, chat discovery |
| [docs/logging.md](docs/logging.md) | log levels, JSON log files, adding a logger |

## Development

```bash
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv add <package>           # add a dependency
uv add --dev <package>     # add a dev dependency
```

Linting is [ruff](https://docs.astral.sh/ruff/) only. It covers pylint's checks
(the `PL` rules) alongside pyflakes, isort, bugbear, async correctness and the
rest, so there is one tool and one config in `pyproject.toml` rather than two
that overlap and disagree.

Run the hooks on every commit:

```bash
uv run pre-commit install       # one time
uv run pre-commit run --all-files
```

The same checks — lint, format, tests — run in CI on every push and pull
request (`.github/workflows/ci.yml`). No test touches the network.
