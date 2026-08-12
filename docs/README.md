# Docs

| | |
|---|---|
| [getting-started.md](getting-started.md) | how to use Till Infinity — install, first pull, keeping it current, reading the data back |
| [prices.md](prices.md) | OHLCV candles and realtime bid/ask across brokers — CLI, sources, storage, schema, library use |
| [logging.md](logging.md) | project logging: levels, JSON log files, adding a logger to a module |

Notes on what is *not* obvious about the data — which venues are missing from
which endpoint, where Yahoo's history stops, why a bar is or is not stored —
live in [prices.md](prices.md) rather than in the code, so they survive a
refactor.
