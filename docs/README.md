# Docs

| | |
|---|---|
| [handoff.md](handoff.md) | **start here** — what is broken, what to do first, and what cost time before |
| [todo.md](todo.md) | what is outstanding, ordered by what would change the numbers most |
| [idea.md](idea.md) | what the project is for, and the reasoning behind each part — the long version of the README's opening |
| [getting-started.md](getting-started.md) | how to use Till Infinity — install, first pull, keeping it current, reading the data back |
| [news.md](news.md) | headlines and the economic calendar — sources, two clocks, storage |
| [news-models.md](news-models.md) | **planned** — models that could process the news data, what each costs on a 640MB box, and the cheapest wins first |
| [news-dedup.md](news-dedup.md) | **measured** — 7.8% of headlines are duplicates, 89% of them our own collection counting one outlet twice; the crowding signal is not there |
| [prices.md](prices.md) | OHLCV candles and realtime bid/ask across brokers — CLI, sources, storage, schema, library use |
| [notifications.md](notifications.md) | Telegram and Discord alerts — channels, level routing, chat discovery |
| [bus.md](bus.md) | the message bus — topics, publishing, fan-out, Redis |
| [structures.md](structures.md) | online models over price — cross-venue anomaly, drift, persistence |
| [score.md](score.md) | **planned** — one number per instrument in [−1, +1], smoothed three ways, thresholds it measures rather than assumes |
| [levels.md](levels.md) | key price levels — PIP swings, Kalman tracking, per-side directional inference |
| [strength.md](strength.md) | **measured** — a level's own record predicts holding, confluence breadth does not, and the composite loses to its own best term |
| [behaviours.md](behaviours.md) | **planned** — what price does at a level, which of it we already model under another name, and the three gaps worth building |
| [absorption.md](absorption.md) | **measured** — absorption and compression both fail to separate; three defects found on the way that matter more than the nulls |
| [magnet.md](magnet.md) | **measured** — levels do not attract price; 44 of 45 estimates negative, and the negative is selection rather than repulsion |
| [trading.md](trading.md) | scalping the level calls — MT5 on Windows, a Wine bridge on Linux, paper unless armed; strategies, risk plans and the gates |
| [agents.md](agents.md) | LLM analysis over the stored data — roles, tools, read-only access, watching |
| [journal.md](journal.md) | the decision journal — reasoning, outcomes, exporting for training |
| [edge.md](edge.md) | **measured** — the 0.08 alert gate sits in a flat region and should be 0.11; a rolling quantile is worse than a constant, and why |
| [calibration.md](calibration.md) | **planned** — does 80% mean 80%; what to measure, what falsifies it, and why the obvious fix makes the model worse |
| [deployment.md](deployment.md) | running it — one process, compose, or CI to a server |
| [logging.md](logging.md) | project logging: levels, JSON log files, adding a logger to a module |

Notes on what is *not* obvious about the data — which venues are missing from
which endpoint, where Yahoo's history stops, why a bar is or is not stored —
live in [prices.md](prices.md) rather than in the code, so they survive a
refactor.
