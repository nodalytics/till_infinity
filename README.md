<p align="center">
  <img src="docs/logo.svg" alt="Till Infinity" width="150">
</p>

<h1 align="center">Till Infinity</h1>

<p align="center">
  Finding high-probability directional structures in price, backed by
  fundamentals.
</p>

<p align="center">
  <a href="https://github.com/nodalytics/till_infinity/actions/workflows/ci.yml">
    <img src="https://github.com/nodalytics/till_infinity/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
</p>

## The idea

A directional call is only worth making when the price structure and the
fundamentals point the same way. Most setups see one or the other. This one is
built to see both at once, and to write down why it thought so at the time.

Five things follow from that, and they are the five parts of the project:

**Structure needs more than one view of the price.** The same instrument is
quoted by six brokers at once, so the *differences* carry information a single
feed cannot: which venue leads, where quotes diverge, when liquidity thins ahead
of a move. That is why `prices` collects one instrument from many venues rather
than many instruments from one.

**Finding the structure is arithmetic, not judgement.** `structures` measures
every venue against the median of the others and learns, online, what normal
looks like for each — because "unusual" only means anything relative to
something, and a constant threshold is the wrong something. It also finds the
**key levels** price keeps turning at, and infers which way it goes from what
happened last time it arrived *from that side*. It runs continuously,
independently of anything else.

**Fundamentals separate a structure from a coincidence.** A move with a release
behind it is a different animal from the same move on a quiet calendar. `news`
keeps the economic calendar, the headlines and central bank reserves alongside
the prices, on the same clock.

**Judgement has to happen where both are visible.** `agents` puts a model over
the stored data with read-only tools, and tells it plainly that "nothing is
happening" is a correct answer. Most windows are.

**Every call gets written down with its reasoning.** `journal` records what was
decided, *why at that moment*, the state it was decided from, and what happened
afterwards. Prices can be recomputed forever; the reasoning cannot be
reconstructed at all once it is lost — which is what makes it the one thing
worth capturing from day one.

## Run it

Requires [uv](https://docs.astral.sh/uv/). Python 3.11 is pinned in `.python-version`.

```bash
uv sync                      # runtime + dev deps
cp .env.example .env         # optional: every setting, documented
uv run till-infinity run     # collectors, levels, journal — all of it
```

That is the whole thing running: prices and news collecting, `structures`
finding levels and anomalies, the journal recording, notifications delivering.
One bus, one process.

```
till infinity · in-process bus · journal, structures, prices, news
00:33:18  structures  dislocation gold/PEPPERSTONE +1.06bps off where 5 other venues agree
00:33:22  structures  spread gold/SAXO 2.2x the group at 0.88bps
```

**Agents are off by default** — they are the only part needing a paid
credential, and the rest should not be hostage to it:

```bash
AGENTS_ENABLED=1 uv run till-infinity run     # or --agents
uv run till-infinity run --for 300 -s gold    # one instrument, five minutes
uv run till-infinity run --once               # one collection pass, then stop
```

Anything that cannot start says why at second zero and the others carry on.
Settings come from `.env` — see [.env.example](.env.example) — with real
environment variables winning, so a deployment is never overridden by a file.

For a shared bus across machines, set `TILL_REDIS_URL` and run the services
separately; see [how the parts talk](#how-the-parts-talk).

## Prices

OHLCV candles and realtime bid/ask for the same instrument across many brokers,
from TradingView and Yahoo.

```bash
uv run till-infinity prices backfill      # deep history
uv run till-infinity prices collect       # bars + quotes together, with a ticker
uv run till-infinity prices bars          # new bars every 60s, forever
uv run till-infinity prices quotes        # stream live bid/ask, forever
uv run till-infinity prices info          # what is stored
```

Defaults to EURUSD, GBPUSD, gold and BTC; `-s` takes anything else
(`-s OANDA:XAUUSD`, `-s AAPL`). Intervals run 1m to 1w. Full guide:
**[docs/prices.md](docs/prices.md)**.

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

## Structures

Online models over the price data: every venue measured against the consensus
of the others, and the key levels price keeps turning at.

```bash
uv run till-infinity structures levels            # what it has found
uv run till-infinity structures levels --at 4405  # what the history says
uv run till-infinity structures watch             # run it on its own
```

A level is tracked as a **Kalman state** rather than a line — each touch is a
noisy observation, so the filter's variance *is* the zone, and it widens with
volatility on its own. Statistics are kept **per approach side**, because the
same price met from above and from below are two different objects:

```
gold arriving at 4405.5
  · 4405.5  (from above)  ↑ 59% vs 47% base   push +0.42v
  ! 4401.3  (from above)  ↑ 80% vs 47% base   push +1.78v
```

Every conditional is shown beside its base rate — a level whose P(up) matches
the unconditional rate has said nothing.

**False breakouts are a distinct outcome**, because they are neither a break
nor a rejection and a model with only those two words scores a trap as a break
that worked. A break stays provisional until it survives; give it back and it
is a trap, recorded with the push it *ended* on. On the stored history 27 of 70
breakout attempts were false — 39%.

Levels are built on **5m, 15m, 1h, 4h, 1d and 1w**, and each timeframe keeps
its own volatility and its own rate of forgetting. Those differ by more than
anyone guesses:

| | 1 volatility unit (gold) | evidence half-life |
|---|---|---|
| 5m | $0.75 | 0.9 days |
| 1h | $2.07 | 10 days |
| 4h | $9.87 | 42 days |
| 1d | $27.80 | 250 days |
| **1w** | **$52.23** | **1750 days** |

Seventy times, end to end. One estimate for all of them puts a weekly level to
the nearest dollar and makes it forget a touch before the next one arrives —
which is why the higher timeframes produced almost nothing until this was
per-timeframe.

Levels at one price across timeframes are then combined, the higher timeframe
carrying significance and the lower one placement:

```
btc   63500.18  [1h+15m+5m]  span=1h  precision=5m  6.7 touches  strength 0.90
gold   4339.46  [1d+15m]     span=1d  precision=15m
```

It warms from stored history on start — 25,000 bars in under two seconds — so
levels exist immediately instead of after days of listening. Guides:
**[docs/structures.md](docs/structures.md)** and
**[docs/levels.md](docs/levels.md)**.

## Agents

A model over the stored data — ask it a question, or leave one watching and
alerting when price and fundamentals line up.

```bash
uv run till-infinity agents ask "is anyone quoting gold out of line?"
uv run till-infinity agents watch --redis redis://localhost:6379
uv run till-infinity agents roles         # market, macro, risk
```

Every store an analyst reads is opened read-only, so a prompt injection in a
headline reaches a model whose only verbs are SELECT. Full guide:
**[docs/agents.md](docs/agents.md)**.

## Journal

What was decided, why at that moment, and what happened next.

```bash
uv run till-infinity journal listen --redis redis://localhost:6379  # record
uv run till-infinity journal list
uv run till-infinity journal add "Widened the spread threshold to 12bps" \
    --why "8bps fired six times overnight on TVC, none of them real"
uv run till-infinity journal export -o data/journal.jsonl
```

Append-only and point-in-time: the state behind a decision is copied in, not
referenced, so an entry read back a year later still shows the world it was
actually made in. Full guide: **[docs/journal.md](docs/journal.md)**.

## Notifications

Alerts to Telegram and Discord, fanned out across as many chats or webhooks as
you list, with per-channel level routing.

```bash
uv run till-infinity notify chats          # discover Telegram chat ids
uv run till-infinity notify listen         # deliver what the agents publish
uv run till-infinity notify send "..." -l warning
```

Full guide: **[docs/notifications.md](docs/notifications.md)**.

## How the parts talk

Collectors publish what they store, agents consume it and publish alerts,
notifications deliver those. The databases stay the source of truth — the bus
carries notice that something happened, not the data itself.

```
prices ──┬─▶ structures ─┬─▶ structures.signals ─┐
         │               └───────────────────────┼─▶ alerts ─▶ notifications
news  ───┴─────────────────────▶ agents ─────────┘
                                   │
             structures, agents ───┴──▶ journal ──▶ journal.db
```

Every part is a service and every arrow is a bus topic — including the
journal, so one process writes it and a service on another machine can record
a decision at all. `structures` reaches `alerts` directly for findings that
interpret themselves: a feed that has stopped needs no model and no calendar.

`till-infinity run` starts all of these in one process against one bus, which
is what you want for a laptop or an end-to-end check. Run them separately when
they should scale or fail independently:

```bash
uv run till-infinity prices collect    --publish redis://localhost:6379 &
uv run till-infinity news collect      --publish redis://localhost:6379 &
uv run till-infinity structures watch  --redis   redis://localhost:6379 &
uv run till-infinity agents watch      --redis   redis://localhost:6379 &
uv run till-infinity journal listen    --redis   redis://localhost:6379 &
uv run till-infinity notify listen     --redis   redis://localhost:6379 &
```

Full guide: **[docs/bus.md](docs/bus.md)**.

## Where it lands

SQLite by default, under `.data/` and gitignored. JSONL alongside it with
`--store both`.

```
.data/prices/prices.db      bars + quotes
.data/news/news.db          articles + events + observations
.data/journal/journal.db    decisions + observations + outcomes
.data/structures/           online model state, restored on restart
```

Nothing is regenerated on restart that does not have to be: the online models
are restored, and the level windows warm from the stored bars.

Everything is stored as epoch seconds in **UTC** — local time never enters the
project. Re-running a collector is cheap and safe: bars key on their open time,
headlines on their id, calendar events get rewritten in place when the print
lands, and journal entries are content-addressed.

## Docs

| | |
|---|---|
| [docs/getting-started.md](docs/getting-started.md) | **start here** — install to stored data, and how to read it back |
| [docs/prices.md](docs/prices.md) | candles, quotes, sources, storage, schema, library use |
| [docs/news.md](docs/news.md) | headlines, economic calendar, event storage |
| [docs/structures.md](docs/structures.md) | online models, cross-venue features, avoiding false positives |
| [docs/levels.md](docs/levels.md) | key levels — PIP swings, Kalman tracking, per-side directional inference |
| [docs/agents.md](docs/agents.md) | analysts, tools, models, read-only access, watching the bus |
| [docs/journal.md](docs/journal.md) | decisions, reasoning, outcomes, exporting for training |
| [docs/notifications.md](docs/notifications.md) | Telegram and Discord alerts, channels, chat discovery |
| [docs/bus.md](docs/bus.md) | topics, publishing, fan-out, Redis |
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
