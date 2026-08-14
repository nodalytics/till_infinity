# Docs

| | |
|---|---|
| [todo.md](todo.md) | what is outstanding, ordered by what would change the numbers most |
| [idea.md](idea.md) | what the project is for, and the reasoning behind each part — the long version of the README's opening |
| [getting-started.md](getting-started.md) | how to use Till Infinity — install, first pull, keeping it current, reading the data back |
| [news.md](news.md) | headlines and the economic calendar — sources, two clocks, storage |
| [prices.md](prices.md) | OHLCV candles and realtime bid/ask across brokers — CLI, sources, storage, schema, library use |
| [notifications.md](notifications.md) | Telegram and Discord alerts — channels, level routing, chat discovery |
| [bus.md](bus.md) | the message bus — topics, publishing, fan-out, Redis |
| [structures.md](structures.md) | online models over price — cross-venue anomaly, drift, persistence |
| [score.md](score.md) | **planned** — one number per instrument in [−1, +1], smoothed three ways, thresholds it measures rather than assumes |
| [levels.md](levels.md) | key price levels — PIP swings, Kalman tracking, per-side directional inference |
| [agents.md](agents.md) | LLM analysis over the stored data — roles, tools, read-only access, watching |
| [journal.md](journal.md) | the decision journal — reasoning, outcomes, exporting for training |
| [deployment.md](deployment.md) | running it — one process, compose, or CI to a server |
| [logging.md](logging.md) | project logging: levels, JSON log files, adding a logger to a module |

Notes on what is *not* obvious about the data — which venues are missing from
which endpoint, where Yahoo's history stops, why a bar is or is not stored —
live in [prices.md](prices.md) rather than in the code, so they survive a
refactor.
