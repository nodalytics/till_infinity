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

## In plain words

Imagine a street where houses normally sell for about £300,000. One goes on the
market at £380,000. You do not know whether it will sell - but you do know it is
**unusually expensive for that street**, and you know roughly how much house
prices on it tend to wobble month to month.

This software does that for financial markets, continuously and automatically.

**It works out what something is worth right now.** It watches the price of one
thing - gold, say - from several different sources at once, because when they
disagree with each other, that disagreement is itself information. From that it
estimates a "fair price": not a prediction, just where the market currently
seems to agree the thing is worth.

**Then it measures how far the actual price has wandered from that.** That gap
is the whole point. A price far from fair value is a price somebody might trade
back toward it.

**It measures that gap in "how unusual is this", not in pounds.** Gold moving
$50 and the euro moving half a cent sound nothing alike, but they can be equally
unusual for the thing in question. Converting everything to "how unusual" is
what lets one set of rules work on gold, currencies, and crypto without being
retuned for each.

### What it can and cannot tell you

This is the part most trading software is dishonest about, so it is stated up
front.

**It cannot tell you whether the price will go up or down.** Not "it is not very
good at it" - it genuinely cannot, and neither can anything else we have been
able to measure here. Every attempt to predict direction in this project has
been tested and has come out indistinguishable from a coin flip. Those attempts
are all still written down, in `research/`, including the ones that looked
brilliant until they were checked properly.

**It can tell you two useful things instead:**

- **How bumpy the next stretch is likely to be.** Calm periods and wild periods
  come in clusters, and that is forecastable. Most usefully, the calendar does
  a lot of the work for free: on a scheduled announcement, prices move about
  **2.4x** as much as normal, and a few hours later about **0.9x** - quieter
  than usual. Those announcement times are published days in advance, so no
  crystal ball is needed.
- **Whether a price level will hold or give way.** If a price has turned around
  at £1,000 several times before, that history genuinely says something about
  whether it will turn there again. The longer price sits at a level without
  bouncing, the more likely it is to break through - and that flips from
  "probably holds" to "probably breaks" after about **four to seven** bars of
  whatever timeframe you are looking at.

Knowing *how much* something will move, and *how likely* a line is to hold, is
not the same as knowing which way it goes. They happen to be the questions the
data can actually answer.

**It writes down why it did things.** Every decision is recorded with the
reasoning that led to it at that moment. Prices can always be re-downloaded;
the reasoning behind a decision is gone forever if nobody saved it.

**And it grades its own homework.** When a model claims it will perform a
certain way, that claim is stored and the live results are scored against it.
Models that worked in testing and quietly stopped working in reality are the
normal case, not the exception, and nothing here is trusted just because it
once tested well.

The rest of this README is the detailed version of the above, for anyone who
wants the mechanics and the numbers.

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
predicts whether it holds** - hold rate on the arriving side separates 59% to
92% across four bands - though it is the record's *conviction* that carries
this and not its direction: over 293,252 live resolutions the raw reading scores
AUC 0.5005 and `|record - 0.5|` scores **0.6006**. **Price is not drawn to a
level**: reached within twenty bars 44.9% of the time against 49.5% for an
arbitrary price the same distance away. So the distance is an *opportunity*, not
a magnet.

### What it forecasts, and what it does not

The valuation fixes the side by arithmetic. On top of that sit two families that
genuinely predict, both measured on the desk's own record rather than on stored
history:

**Whether a level gives way.** `structures/learning/breaking.py` fits nine
inputs online and reaches **AUC 0.658**; the live instance refuses a call above
a 35% break risk. The largest single effect is free: `P(break | the touch is
still open at t)` runs from **14.4% to 77.8%** and crosses even money at **four
to seven bars of the level's own timeframe**, on every timeframe from 1m to 30m
- a thirtyfold span, so the rule is scale-free with one parameter.

**How volatile the next stretch is.** A trailing standard deviation is the
baseline, and it has beaten a three-state HMM, a fifty-neighbour analogue on 0
of 20 window-by-horizon cells, and an Ising susceptibility. What does add to it
is the calendar: net of the hour of the day, volatility runs **0.79x in the two
hours before a scheduled release and 2.42x on the print itself**, decaying to
0.92x - *below* normal - four hours later. A release time is published days
ahead, so that forecast needs no model of the future at all.

**Direction is still not forecast**, and that is a finding rather than a gap.
Every directional candidate here has died on measurement, most recently a
momentum-trajectory model whose velocity term prices at -0.00006 out of sample.
Hit rates land between 49% and 51% and the round trip costs 4bp. The two
families above work because they answer questions the data can answer: a
*magnitude* and a *conditional probability*, not a sign.

Every one of them is scored **live against the backtest that claimed it**
(`structures/context/registry.py`), because the record here is that point
estimates from backtests decay and nothing was previously arranged to notice.

### The parts

Six, in dependency order:

| | |
|---|---|
| `prices` | one instrument from **many venues**, because the disagreement between feeds carries information no single feed does |
| `structures` | arithmetic, not judgement - the online models that estimate fair value, and the **key levels** price keeps turning at, answered per approach side |
| `news` | the calendar and the headlines on the same clock, because a move with a release behind it is a different animal |
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

```bash
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

A level is a **latent state in a state-space model** rather than a line - each
touch is a noisy observation of where it sits, so the model's variance *is* the
zone. What comes out is a price when the band is tighter than the tick grid and
a **range** when it is not: the same object at two confidences, from one model
rather than an estimator with a width rule beside it. The filter doing the
inference today is a Kalman, which is one member of that family - particle
filters, hidden Markov models and random-finite-set filters are others, and
which one fits is a question asked per state. See
[`docs/levels.md`](docs/levels.md) §3.
Statistics are kept **per approach side**, because the same price met from
above and from below are two different objects, and every conditional sits
beside its base rate: a level whose P(up) matches the unconditional rate has
said nothing, however confident it looks.

Built on **1m through 1w**, each timeframe with its own volatility and its own
rate of forgetting - one volatility unit on gold is $0.75 on 5m and $52.23 on
1w. Levels at one price across timeframes combine, the higher carrying
significance and the lower placement.

The same thesis has a second subject. A level prices *an instrument* against
where its volatility turned; a **relationship** prices a pair or a panel
against where it normally sits, and the distance from it is the same kind of
claim - statistical arbitrage is this thesis with the subject changed, not a
different one. What changes is the cost: two legs, two spreads, and a
relationship that can end while still producing a confident deviation. Measured
here at a **gross Sharpe of +0.27 and a net of −0.97**, so the version held is
the deviation as a *reading* rather than a hedged book. See
[`docs/idea.md`](docs/idea.md).

Beyond the single level, it also publishes the **level range** price is sitting
in - the nearest agreed price above and below - with the room to each in
volatility units, and a model of **which wall gets reached first**. Those two
bounds are what a trade is made of - a price that says the reading was wrong
and one that says it was right - and they are measurements of structure rather
than risk settings; turning them into a stop and a target needs cost and size,
which is the trading layer's job and not the model's. That is an
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
