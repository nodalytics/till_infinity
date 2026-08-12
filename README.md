<p align="center">
  <img src="docs/logo.svg" alt="Till Infinity" width="480">
</p>

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
