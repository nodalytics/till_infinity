# Docs

| | |
|---|---|
| [todo.md](todo.md) | what is outstanding, ordered by what would change the numbers most |
| [idea.md](idea.md) | what the project is for, and the reasoning behind each part - the long version of the README's opening |
| [getting-started.md](getting-started.md) | **retired commands** - how the desk was used when it was a CLI over six services; install, first pull, keeping it current, reading the data back |
| [news.md](news.md) | headlines and the economic calendar - sources, two clocks, storage |
| [news-dedup.md](news-dedup.md) | **measured** - 7.8% of headlines are duplicates, 89% of them our own collection counting one outlet twice; the crowding signal is not there |
| [prices.md](prices.md) | OHLCV candles and realtime bid/ask across brokers - sources, storage, schema, library use. The commands in it retired with the collector |
| [notifications.md](notifications.md) | Telegram and Discord alerts - channels, level routing, chat discovery |
| [bus.md](bus.md) | **retired** - the message bus as it was: topics, publishing, fan-out, Redis. Nautilus's bus replaced it and nothing imports Redis now |
| [structures.md](structures.md) | **retired 2026-10-29** - online models over price: cross-venue anomaly, drift, persistence. `statespace/` is the successor and the measurements still stand |
| [levels.md](levels.md) | key price levels - PIP swings, Kalman tracking, per-side directional inference |
| [behaviours.md](behaviours.md) | **planned** - what price does at a level, which of it we already model under another name, and the three gaps worth building |
| [absorption.md](absorption.md) | **measured** - absorption and compression both fail to separate; three defects found on the way that matter more than the nulls |
| [magnet.md](magnet.md) | **measured** - levels do not attract price; 44 of 45 estimates negative, and the negative is selection rather than repulsion |
| [trading.md](trading.md) | trading the level calls - MT5 on Windows, a Wine bridge on Linux, paper unless armed; scalps and swings, session hours, origins, risk plans and the gates. Written against the retired service; the gates and the reasoning carried over to `strategies/` |
| [journal.md](journal.md) | the decision journal - reasoning, outcomes, exporting for training |
| [edge.md](edge.md) | **measured** - the 0.08 alert gate sits in a flat region and should be 0.11; a rolling quantile is worse than a constant, and why |
| [ledger.md](ledger.md) | what the journal can answer about money - per level, per instrument, per decision |
| [reading.md](reading.md) | how to read a level call: the fields, the push, what the numbers mean next to each other |
| [deployment.md](deployment.md) | running it - the node, compose, or CI to a server; what it needs from a box |
| [backtest-engine-abort.md](backtest-engine-abort.md) | the day `BacktestEngine.run()` aborted with a double free, both wrong guesses, and the bisection that pinned it on `nautilus_trader` |
| [environment.md](environment.md) | every environment variable: default, effect, the research behind it, and whether changing it moves trading |
| [logging.md](logging.md) | project logging: levels, JSON log files, adding a logger to a module |
| [recovering-a-grown-wal.md](recovering-a-grown-wal.md) | the one-off recovery when the prices file has outgrown its box - 29.5 GB with a 13 GB write-ahead log took the desk out for a day; three omissions let it happen and all three are now closed |

Three directories are not in the table because they are records rather than
descriptions. [adr/](adr) holds the decision records: an ADR says what was
decided at the time and is not rewritten when a later decision supersedes it,
so read the whole set rather than one. [specs/](specs) holds designs, some
still being built. [plans/](plans) holds the plans work was done from.

Notes on what is *not* obvious about the data - which venues are missing from
which endpoint, where Yahoo's history stops, why a bar is or is not stored -
live in [prices.md](prices.md) rather than in the code, so they survive a
refactor.
