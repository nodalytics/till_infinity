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

**Which way we trade follows from the gap, and nothing else decides it.**
Fair price above the market and we buy, below it and we sell. That is
deliberate rather than minimal: the gap is the only thing here that has to be
estimated, so it is the only thing that can be wrong.

**A price stops at a line because enough people agree, not because the line is
special.** This is the whole difference between this and reading shapes off a
chart. Price turns at £1,000 because enough of the market agrees, for now, that
the thing is worth about £1,000 - so the turn is a consequence of what people
think it is worth, and a line that stops working was a claim about value that
turned out to be wrong. A shape on a chart cannot be wrong about anything; it
either repeats or it does not.

**It measures that gap in "how unusual is this", not in pounds.** Gold moving
$50 and the euro moving half a cent sound nothing alike, but they can be equally
unusual for the thing in question. Converting everything to "how unusual" is
what lets one set of rules work on gold, currencies, and crypto without being
retuned for each.

**A long way from fair price is an opportunity, not a promise.** Nothing drags
a price back because it has gone far: it arrives at a level within twenty bars
**44.9%** of the time, against **49.5%** for an arbitrary price the same
distance away. Being far away is a reason to be interested, and not a reason to
expect a return.

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

### What it forecasts, and what it does not

Everything is measured in **volatility units**, so gold and EURUSD, 3m and 1w
compare without per-instrument tuning - and "how far from fair value" means the
same thing everywhere.

**A level's own record predicts whether it holds** - hold rate on the arriving
side separates 59% to 92% across four bands - though it is the record's
*conviction* that carries this and not its direction: over 293,252 live
resolutions the raw reading scores AUC 0.5005 and `|record - 0.5|` scores
**0.6006**. The no-magnet figures above are the control for it.

The valuation fixes the side by arithmetic. On top of that sit two families that
genuinely predict, both measured on the desk's own record rather than on stored
history:

**Whether a level gives way.** `research/retire/structures/engine/learning/
breaking.py` fits nine inputs online and reaches **AUC 0.658**; it refused a
call above a 35% break risk. That file retired with the rest of `structures`
on 2026-10-29 and `statespace/` is its successor, so the measurement stands
and the implementation is in the archive rather than on the traded path. The largest single effect is free: `P(break | the touch is
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

Every number in this section and the last is measured, and the measurement is
written down: [research/docs/](research/docs/) holds one document per question
with the harness that answered it, indexed in its own README, and
[docs/idea.md](docs/idea.md) carries the same figures in their argument. A
number here without a document there would be a guess, and there are not
supposed to be any.

**Direction is still not forecast**, and that is a finding rather than a gap.
Every directional candidate here has died on measurement, most recently a
momentum-trajectory model whose velocity term prices at -0.00006 out of sample.
Hit rates land between 49% and 51% and the round trip costs 4bp. The two
families above work because they answer questions the data can answer: a
*magnitude* and a *conditional probability*, not a sign.

Every one of them is scored **live against the backtest that claimed it** -
`research/retire/structures/engine/context/registry.py`, archived with the
package it belonged to - because the record here is that point estimates from
backtests decay and nothing was previously arranged to notice. The successor
in `statespace/` has not yet been given the same scoring, which is a gap
rather than a decision.

### The parts

Seven, in dependency order. The names changed with the port on 2026-11-01:
`prices`, `news`, `structures`, `trading` and `bus` were five of six services,
and what each of them did is now either an adapter, an indicator or an actor
inside one node.

| | |
|---|---|
| `adapters/` | the venues, as Nautilus adapters. `mt5/` is the Deriv/MT5 feed and the only thing here that can place an order. `news/` is the calendar and the headlines on the same clock, because a move with a release behind it is a different animal - written, and registered by no node yet |
| `domain/` | the vocabulary - an `Intent`, a `Position`, a `Side` - with no dependency on a venue or on a model |
| `indicators/` | arithmetic, not judgement, as `nautilus_trader` `Indicator`s: momentum, trend, changepoints, and the **key levels** price keeps turning at, answered per approach side |
| `statespace/` | the online models that price an instrument against where it should be, as a predictive distribution rather than a pattern that matched or did not |
| `risk/` | how much may be lost, per trade and per day, and whether *this account, right now* may take another one. Above Nautilus rather than inside it, because its risk engine is not pluggable |
| `strategies/` | the only part that can lose money, and the only one armed by a switch of its own. One `Strategy` per rule, entry and instrument |
| `journal/` | what was decided, **why at that moment**, and what followed. Prices can be recomputed forever; the reasoning cannot be reconstructed once lost |

`node/` assembles them and `utils/` is beneath all of it.

## Run it

### On a server

```bash
docker compose up -d                     # the node, unarmed
TRADING_LIVE=1 docker compose up -d      # the node, able to place orders
```

Or push to `main` and let CI build, publish and deploy it. There is one
service in the compose file, because the port left one process behind; see
[deployment.md](docs/deployment.md) for what it needs from a box.

### Locally

Requires [uv](https://docs.astral.sh/uv/). Python 3.13 is pinned in
`.python-version` - 3.12 is the floor, because every `nautilus_trader` release
that does not abort inside `BacktestEngine.run()` requires it.

```bash
uv sync                                  # runtime + dev deps
cp .env.example .env                     # optional: every setting, documented
uv run python -m till_infinity.node.live      # the node
uv run python -m till_infinity.node.backtest  # whether this box may sweep, and what it would cost
```

That is one `TradingNode`: the MT5 adapter for data and execution, the
statespace fold as an `Actor`, the journal and the notifier as `Actor`s, and
one `Strategy` per (rule, entry, instrument). They share one message bus, one
cache and one portfolio - which is what makes exposure answerable across
venues rather than a packaging choice.

**There is no `till-infinity` command**, deliberately. A 2,852-line CLI
retired with the services it drove, and a second way to run the desk is a
second thing to go stale. The node module is the entry point, and the image's
`ENTRYPOINT` is the same line.

**Nothing arms it but `TRADING_LIVE`.** Unset, the node connects, reconciles,
subscribes and computes - those are reads, and they are how the desk is
observed - while its risk engine sits in `HALTED` and every order is denied
inside the engine, below the strategies and above the client.

```bash
uv run python -m till_infinity.node.status   # up, fresh, and trading something?
```

Settings come from `.env` - see [.env.example](.env.example) - with real
environment variables winning, so a deployment is never overridden by a file.

## Structures

**Retired on 2026-10-29**, with the eight level-scalper strategies that read
it. The commands below no longer exist and the package is in
`research/retire/structures/`; what it did is described here because the model
is the ancestor of `statespace/` and the reasoning is worth keeping.

The successor answers the same question - "is this instrument away from where
it should be, and by how much" - as a predictive distribution with a
likelihood that can be scored against a null, rather than as a pattern that
either matched or did not.

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

Everything above happens inside one `TradingNode`, on one message bus, over
one cache and one portfolio.

```
  MT5 bridge ──▶ MT5DataClient ──┐
                                 │
  stored bars (backtest) ────────┤
                                 ▼
                        statespace Actor ──▶ readings ──┐
                                                        ▼
                                  Strategy per (rule, entry, instrument)
                                              │                 │
                                     orders   │                 │   intents, refusals
                                              ▼                 ▼
                                      MT5ExecClient       journal Actor ──▶ journal.db
                                              │                 │
                                              ▼                 ▼
                                    trading terminal     notifier Actor ──▶ Telegram, Discord

  the node ──▶ heartbeat Actor ──▶ status.json ──▶ the container's HEALTHCHECK
```

The bridge appears twice on purpose. It is the **execution** path - orders out,
fills and positions back - and since synthetics exist it is also a **price**
source, because instruments with no underlying are quoted nowhere else. One
transport, two directions, and the same tick time is read for both: a frozen
one is how a shut market is recognised.

The sharing is the reason the node is one process rather than a convenience.
One cache and one portfolio is what makes "what is this account risking,
across every venue" a question with an answer - `risk/exposure.py` exists
because that is a property of an account and not of a ticket - and a process
per service would put each one's positions out of the others' sight.

**Until 2026-11-01 each part was its own service over Redis**, started by its
own subcommand of the `till-infinity` CLI, publishing to bus topics that the
next one subscribed to. The collectors wrote SQLite and the bus carried notice
that something had happened rather than the data itself. That topology, the
CLI and the six processes retired together, and Redis went with them: nothing
under `till_infinity/` imports it, Nautilus's bus is in-process, and a bus
nothing publishes to is a dependency that can only fail.

**Two things are written, wired to nothing, and deliberately absent from the
diagram above.** `adapters/news/` is a complete Nautilus data client for the
calendar and the headlines, and no node registers it. `research/retire/prices/
funding.py` and `positioning.py` read funding rates, open interest and the
long/short split, and retired with the collector that would have called them.
Drawing an arrow for either would say the desk is collecting something it is
not, which is the failure this project keeps finding rather than one to add to
the picture.

## Where it lands

Under `.data/`, gitignored, mounted as a volume in the compose file. Unmounted
the record starts empty on every deploy and the health probe has nothing to
read.

```
.data/journal/journal.db            decisions + observations + outcomes
.data/statespace/progress.msgpack   online model state, restored on restart
.data/status.json                   what the node established about itself; the HEALTHCHECK reads it
.data/news/news.db                  articles + events + observations
```

The first three are written by a running node. The fourth is written by
`adapters/news/`, which nothing registers, so on a node today that file is
whatever the retired collector last left there.

Bars and quotes are **not** stored any more. `.data/prices/prices.db` was the
price collector's database and the collector retired with the CLI; the node
subscribes to the venue and keeps what it needs in the Nautilus cache, and a
backtest reads a catalogue it is given rather than that file. An existing
`prices.db` is history, not a live store - see
[recovering-a-grown-wal.md](docs/recovering-a-grown-wal.md) for what it cost
when it grew to 29.5 GB.

Nothing is regenerated on restart that does not have to be: the online models
are restored from `progress.msgpack`, and the level windows warm from the bars
the venue replays.

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
