<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/logo-light.svg">
    <img src="docs/logo.svg" alt="Till Infinity" width="92">
  </picture>
</p>

<h1 align="center">Till Infinity</h1>

<p align="center">
  We price the market, and take a stance on the distance.
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
    <img src="docs/telegram-qr.png" alt="Scan for live alerts on Telegram" width="140">
  </a>
  <br><b>Live alerts</b> - scan, or use the badge above
</p>

## The idea

**A level is the market's fair price, and the turn is what that costs.**

Price does not stop at a level because the line is special. It stops because
enough of the market agrees, for now, that the instrument is worth about that
much - and a price away from it is a price somebody is prepared to trade back.
The turn is the *consequence* of fair value, not the definition of it: the
level is a claim about value that can be wrong, rather than a shape on a chart
that either repeats or does not.

**So we price the market, and take a stance relative to where that price
lands.** Fair value above the market and the stance is long; below it and the
stance is short. The distance between the two is what the trade is worth, and
it is the only quantity that has to be estimated.

Everything is measured in **volatility units**, so gold and EURUSD, 3m and 1w
compare without per-instrument tuning - and "how far from fair value" means
the same thing everywhere.

Two things have been tested rather than asserted. **A level's own record
predicts the next turn**: hold rate on the arriving side separates 59% to 92%
across four bands, AUC 0.648. **Price is not drawn to a level**: reached within
twenty bars 44.9% of the time against 49.5% for an arbitrary price the same
distance away. So the distance is an *opportunity*, not a magnet.

### The parts

Six, in dependency order:

| | |
|---|---|
| `prices` | one instrument from **many venues**, because the disagreement between feeds carries information no single feed does |
| `structures` | arithmetic, not judgement - the online models that estimate fair value, and the **key levels** price keeps turning at, answered per approach side |
| `news` | the calendar and the headlines on the same clock, because a move with a release behind it is a different animal |
| `agents` | a model over the stored data, told plainly that "nothing is happening" is a correct answer. The only part needing a credential |
| `trading` | the only part that can lose money, and the only one armed by a switch of its own - MT5 on Windows, the same code over a Wine bridge on Linux |
| `journal` | what was decided, **why at that moment**, and what followed. Prices can be recomputed forever; the reasoning cannot be reconstructed once lost |

## Run it

### On a server

```bash
docker compose up -d        # one container per service, over Redis
```

Or push to `main` and let CI build, publish and deploy it. Sizing matters more
than preference - six services need about 861 MB, so a small box wants the

### Locally

Requires [uv](https://docs.astral.sh/uv/). Python 3.11 is pinned in `.python-version`.

```bash
uv sync                      # runtime + dev deps
cp .env.example .env         # optional: every setting, documented
uv run till-infinity run     # collectors, levels, journal - all of it
```

That is the whole thing running: prices and news collecting, `structures`
finding levels and anomalies, the journal recording, notifications delivering.
One bus, one process.

```
till infinity · in-process bus · journal, structures, prices, news
00:33:18  structures  dislocation gold/PEPPERSTONE +1.06bps off where 5 other venues agree
00:33:22  structures  spread gold/SAXO 2.2x the group at 0.88bps
```

**Agents are off by default** - they are the only part needing a paid
credential, and the rest should not be hostage to it:

```bash
AGENTS_ENABLED=1 uv run till-infinity run     # or --agents
uv run till-infinity run --for 300 -s gold    # one instrument, five minutes
uv run till-infinity run --once               # one collection pass, then stop
```

Anything that cannot start says why at second zero and the others carry on.
Settings come from `.env` - see [.env.example](.env.example) - with real
environment variables winning, so a deployment is never overridden by a file.

For a shared bus across machines, set `TILL_REDIS_URL` and run the services
separately; see [how the parts talk](#how-the-parts-talk).

## Structures

Online models over the price data: every venue measured against the consensus
of the others, and the key levels price keeps turning at.

```bash
uv run till-infinity structures levels            # what it has found
uv run till-infinity structures levels --at 4405  # what the history says
uv run till-infinity structures watch             # run it on its own
```

A level is tracked as a **Kalman state** rather than a line - each touch is a
noisy observation of where it sits, so the filter's variance *is* the zone.
Statistics are kept **per approach side**, because the same price met from
above and from below are two different objects, and every conditional sits
beside its base rate: a level whose P(up) matches the unconditional rate has
said nothing, however confident it looks.

Built on **1m through 1w**, each timeframe with its own volatility and its own
rate of forgetting - one volatility unit on gold is $0.75 on 5m and $52.23 on
1w. Levels at one price across timeframes combine, the higher carrying
significance and the lower placement.

Beyond the single level, it also publishes the **level range** price is sitting
in - the nearest agreed price above and below - with the room to each in
volatility units, and a model of **which wall gets reached first**. That is an
entry and a target made of prices the market drew rather than a stop multiple.
Both are published as features and read by nothing yet, which is deliberate:
the record gets to say whether they predict anything before they are worth
money.

## How the parts talk

Collectors publish what they store, agents consume it and publish alerts,
notifications deliver those. The databases stay the source of truth - the bus
carries notice that something happened, not the data itself.

```
  tradingview ─┐
  yahoo ───────┤
  ccxt ────────┤
  MT5 bridge ──┴──▶ prices ──▶ prices.bars, prices.quotes ──┐
                                                            │
  news ──────────▶ news.articles, news.events ──────────────┤
                                                            ▼
                                                       structures
                                                            │
                                                            ▼
                                                  structures.signals
                                                       │        │
                                       ┌───────────────┘        └───────────┐
                                       ▼                                    ▼
                                    agents                               trading
                                       │                                    │
                                       └──────────▶ alerts ◀────────────────┤
                                                       │                    │
                                                       ▼                    ▼
                                                 notifications         MT5 bridge
                                                                            │
                                                                            ▼
                                                                   trading terminal

  structures, agents, trading ──▶ journal ──▶ journal.db
```

`ccxt` is the crypto leg and it discovers its own instruments rather than being
given a list: the board is ranked across exchanges by 24h volume, the top slice
is registered as ordinary feeds, and a pair several of them carry becomes one
feed with a symbol per exchange - the same shape a TradingView instrument has,
so the consensus layer treats them alike. See
[research/crypto.md](research/crypto.md).

**Two crypto collectors are written and not in this diagram, deliberately.**
`prices/funding.py` and `prices/positioning.py` read funding rates, open
interest and the long/short split, and nothing calls them yet - they are
library code with no caller. Drawing an arrow for them would say the desk is
collecting something it is not, which is the failure this project keeps
finding rather than one to add to the picture.

The bridge appears twice on purpose. It is the **execution** path - orders out,
fills and positions back - and since synthetics exist it is also a **price**
source, because instruments with no underlying are quoted nowhere else. One
transport, two directions, and the same tick time is read for both: a frozen
one is how a shut market is recognised.

Every part is a service and every arrow is a bus topic - including the
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

## Where it lands

SQLite by default, under `.data/` and gitignored. JSONL alongside it with
`--store both`.

```
.data/prices/prices.db      bars + quotes
.data/news/news.db          articles + events + observations
.data/journal/journal.db    decisions + observations + outcomes
.data/structures/           online model state, restored on restart
.data/trading/day.json      the day: high-water marks, the running loss, the ranking
```

Nothing is regenerated on restart that does not have to be: the online models
are restored, and the level windows warm from the stored bars.

Everything is stored as epoch seconds in **UTC** - local time never enters the
project. Re-running a collector is cheap and safe: bars key on their open time,
headlines on their id, calendar events get rewritten in place when the print
lands, and journal entries are content-addressed.

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

The same checks - lint, format, tests - run in CI on every push and pull
request (`.github/workflows/ci.yml`). No test touches the network.
