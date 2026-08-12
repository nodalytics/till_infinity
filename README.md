# Till Infinity

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
uv run till-infinity prices bars          # new bars every 60s, forever
uv run till-infinity prices quotes        # stream live bid/ask, forever
uv run till-infinity prices info          # what is stored
```

Defaults to EURUSD, GBPUSD, gold and BTC; `-s` takes anything else
(`-s OANDA:XAUUSD`, `-s AAPL`). Full guide: **[docs/prices.md](docs/prices.md)**.

## Docs

| | |
|---|---|
| [docs/getting-started.md](docs/getting-started.md) | **start here** — install to stored data, and how to read it back |
| [docs/prices.md](docs/prices.md) | candles, quotes, sources, storage, schema, library use |
| [docs/logging.md](docs/logging.md) | log levels, JSON log files, adding a logger |

## Development

```bash
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv add <package>       # add a dependency
uv add --dev <package> # add a dev dependency
```
