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
  <a href="https://github.com/nodalytics/till_infinity/actions/workflows/deploy.yml">
    <img src="https://github.com/nodalytics/till_infinity/actions/workflows/deploy.yml/badge.svg" alt="Deploy">
  </a>
  <a href="https://t.me/till_infinity_signals">
    <img src="https://img.shields.io/badge/telegram-signals-2CA5E0?logo=telegram&logoColor=white" alt="Telegram">
  </a>
</p>

<p align="center">
  <a href="https://t.me/till_infinity_signals">
    <img src="docs/telegram-qr.png" alt="Scan to join t.me/till_infinity_signals" width="140">
  </a>
</p>

<p align="center">
  <b>Live alerts</b> — scan, or <a href="https://t.me/till_infinity_signals">t.me/till_infinity_signals</a>
</p>

## The idea

A directional call is only worth making when the price structure and the
fundamentals point the same way. Most setups see one or the other. This one is
built to see both at once, and to write down why it thought so at the time.

Five parts, in dependency order:

| | |
|---|---|
| `prices` | one instrument from **many venues**, because the disagreement between feeds carries information no single feed does |
| `structures` | arithmetic, not judgement — online models over the venues, and the **key levels** price keeps turning at, answered per approach side |
| `news` | the calendar and the headlines on the same clock, because a move with a release behind it is a different animal |
| `agents` | a model over the stored data, told plainly that "nothing is happening" is a correct answer. The only part needing a credential, and the only optional one |
| `journal` | what was decided, **why at that moment**, and what followed. Prices can be recomputed forever; the reasoning cannot be reconstructed once lost |

The load-bearing idea is that a level is **where volatility turns, not where
price poked**: the leg in and the leg out meet at an *origin*, and the wick
beyond it is the zone's width rather than its position. Everything is measured
in **volatility units**, so gold and EURUSD, 3m and 1w, are comparable without
per-instrument tuning.

**[The full version, with the reasoning behind each choice →](docs/idea.md)**

## Run it

### On a server

```bash
docker compose up -d        # one container per service, over Redis
```

Or push to `main` and let CI build, publish and deploy it. Sizing matters more
than preference — six services need about 861 MB, so a small box wants the
single process instead. Full guide: **[docs/deployment.md](docs/deployment.md)**.

### Locally

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

Fourteen instruments by default — the **seven FX majors**, **gold**, **BTC**,
**ETH**, **SOL**, **USDCNH**, **US100** (Nasdaq 100) and **SPX500** — each from
five to seven venues, on intervals from 1m to 1w. They answer to whatever you
call them (`-s nasdaq`, `-s sp500`, `-s kiwi`, `-s solana`),
and `-s` also takes `VENUE:TICKER` or a bare Yahoo ticker. Full guide:
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
noisy observation of where it sits, so the filter's variance *is* the zone.
Statistics are kept **per approach side**, because the same price met from
above and from below are two different objects:

```
gold arriving at 4405.5
  · 4405.5  (from above)  ↑ 59% vs 47% base   push +0.42v
  ! 4401.3  (from above)  ↑ 80% vs 47% base   push +1.78v
```

Every conditional sits beside its base rate. A level whose P(up) matches the
unconditional rate has said nothing, however confident it looks.

Three things happen at a level and the model tells them apart, because one with
only "held" and "broke" scores the other two wrong — on the stored history
**27 of 70 breakout attempts were false**, and every one had counted as a break
that worked:

| | what it is |
|---|---|
| **break** | through, and it stayed through |
| **false breakout** | through, then given back |
| **back check** | broke, pulled back, held, carried on — risk defined by the flipped level |

Built on **1m through 1w**, each timeframe with its own volatility and its own
rate of forgetting — one volatility unit on gold is $0.75 on 5m and $52.23 on
1w, seventy times end to end. Levels at one price across timeframes combine,
the higher carrying significance and the lower placement.

Guides: **[docs/structures.md](docs/structures.md)** and
**[docs/levels.md](docs/levels.md)**.

## Reading a signal

Everything published says the same three things: **what happened**, **how
unusual that is for this venue**, and **what it is being compared against**.
The last one is the part most signals leave out.

### Cross-venue signals

```
stale        BINANCE btc      has not moved in 67s while 4 other venues have
spread       FOREXCOM gold    2.4x the group at 2.11bps, wide even for this venue
dislocation  DERIV btc        +3.93bps from consensus, outside anything this venue normally does
```

| | what it means | needs a human? |
|---|---|---|
| `stale` | this venue stopped updating while the others carried on | **yes, now** — a dead feed needs no interpretation |
| `spread` | its spread is wide for the group *and* for its own history | only with context |
| `dislocation` | its price is away from where the others agree | only with context |
| `drift` | the volatility regime itself changed | it invalidates thresholds |

"Wide even for this venue" is doing real work. A venue quoting BTC at 20bps is
not wide; EURUSD at 3bps is. Each venue is scored against its own distribution,
so one number never has to be right for both.

### Level signals

A level is a price the market has turned at before. What it produces looks like:

```
us100 1h  29618   tested   from above 7.6x +1.87v   from below 6.6x -1.52v   strength 0.94
us100 1h  29391   tested   from above 17.3x +1.57v  from below 6.1x -1.71v   strength 0.88
```

Read left to right: the instrument and timeframe, the price, its state, then
**what it did to price arriving from each side** and how much evidence there is.

- **`7.6x`** — effective touches, decayed by age. Ten touches last quarter count
  for less than three this week, and the number already accounts for that.
- **`+1.87v`** — the average push in **volatility units**: `1v` is one typical
  move for that instrument on that timeframe. On gold 5m that is about $0.75;
  on gold weekly, about $52. It is the same number on BTC and EURUSD, which is
  the point.
- **`from above` / `from below`** — kept apart because they are different
  objects. At 29618 price arriving from above gets pushed **up** and arriving
  from below gets pushed **down**: that is a level holding both ways, and an
  average over the two would show roughly nothing.

### When price arrives

```
gold arriving at 4405.5
  · 4405.5  (from above, ~4.2h)  ↑ 59% vs 47% base   push +0.42v
  ! 4401.3  (from above, ~3.2d)  ↑ 80% vs 47% base   push +1.78v
```

**`vs 47% base` is the whole thing.** 59% sounds like an edge until you see the
unconditional rate is 47%; 80% against the same 47% is one. A level whose
probability matches the base rate has told you nothing, and you will see that
rather than a confident-looking number. `!` marks the ones clearing all three
bars — enough evidence, enough separation from the base rate, and a move big
enough to be worth the risk.

`~4.2h` is how long price typically takes to get there, from the distance and
current volatility. Time goes as the **square** of distance, so a level twice as
far away is four times as long, not twice.

### The three things that happen at a level

| | |
|---|---|
| **break** | through, and it stayed through — provisional until it survives |
| **false breakout** | through, then given back. Recorded with the push it *ended* on |
| **back check** | broke, pulled back, held, carried on — the stop is the flipped level |

Told apart because a model with only "held" and "broke" scores a trap as a
break that worked. On the stored history **27 of 70 breakout attempts were
false**.

### What is not claimed

No performance figures, and none until there are enough resolved outcomes to
compute them honestly. The system records every call with the state it was made
from and attaches what followed, so that question becomes answerable — it is
not answerable yet.

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

What this instance publishes goes to
**[t.me/till_infinity_signals](https://t.me/till_infinity_signals)**.

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
| [docs/deployment.md](docs/deployment.md) | one process, compose, or CI to a server — and how to size it |
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
