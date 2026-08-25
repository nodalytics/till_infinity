# Trading

Turning level calls into positions, on MetaTrader 5 or on paper.

This is the only part of the project that can lose money. Everything about how
it is built follows from that: it is off unless asked for, on paper unless
separately armed, refuses far more often than it acts, and writes down both.

```
structures ──▶ structures.signals ──▶ trading ──┬──▶ broker (mt5 | bridge | paper)
prices     ──▶ prices.quotes     ──┘            ├──▶ alerts
                                                └──▶ journal
```

## Two switches, and neither implies the other

```bash
TRADING_ENABLED=1 uv run till-infinity run      # the service starts, on paper
TRADING_ENABLED=1 TRADING_LIVE=1 ...            # and orders reach the account
```

`TRADING_ENABLED` starts the service. `TRADING_LIVE` arms it. Configuring a
terminal does **not** arm it, and neither does anything else — there is exactly
one variable that puts money at risk, and it is printed at start-up whichever
way it is set.

On paper the whole path runs: symbols resolved against the broker, positions
sized against real equity, stops and targets placed, fills simulated against
the live bid/ask, outcomes journalled. What does not happen is the order.

## Windows and Linux

The `MetaTrader5` Python package is a binding onto a running Windows terminal —
an in-process call into a Win32 DLL. There is no Linux wheel and there will not
be one. So there are three backends and the host decides which:

| backend | runs on | reaches MT5 by |
|---|---|---|
| `mt5` | Windows, or a Wine prefix with a Windows Python | `import MetaTrader5`, in-process |
| `mt5-http` | anywhere, this Linux box included | HTTP to a bridge running MT5 under Wine |
| `paper` | anywhere, no terminal at all | nothing; fills simulated against the quote |

The bridge is [`nodalytics/mt5-api`](https://github.com/nodalytics/mt5-api) —
MT5 under Wine in a container, behind FastAPI. `mt5_http.py` speaks its actual
routes, including its quirks: specs come from `/symbols/{symbol}` rather than
`/symbols/info/{symbol}`, because the `info` route's response model drops
`trade_tick_value` and `trade_tick_size`, which are exactly what sizing needs.

Selection is automatic, in a fixed order — explicit `TRADING_BACKEND`, then the
native package, then the bridge, then paper — because a config file that has to
change between the two operating systems will be wrong on one of them. What it
never does is fall back quietly: dropping from a terminal to paper is the
difference between trading and pretending to.

```bash
uv run till-infinity trading doctor
```

```
┏━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ backend  ┃ usable       ┃ why not                                          ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ mt5      │ no           │ the MetaTrader5 package is Windows-only and this  │
│          │              │ is Linux — use the mt5-http bridge                │
│ mt5-http │ yes          │                                                  │
│ paper    │ yes (chosen) │                                                  │
└──────────┴──────────────┴──────────────────────────────────────────────────┘
```

One line per backend, not just the chosen one: "why is it on paper" has an
answer per backend, and printing one of them is how the other gets missed.

## What can be traded here

Gold and BTC by default. The other twelve instruments the price side tracks can
be named, and will only trade if the broker actually quotes them — a retail MT5
account carrying `XAUUSD` and `BTCUSD` very often carries no `SOLUSD` under any
name, and no `US100` either.

So availability is discovered once, at start-up, against the terminal:

```bash
uv run till-infinity trading symbols -s gold -s btc -s sol
```

Brokers also suffix every symbol by account type — `.raw`, `.r`, `m`, `.pro` —
and the suffix is the same across the account. It is **learned** rather than
enumerated: probing ten suffixes against five candidate names for fourteen
instruments is seven hundred round trips over the bridge, and noticing that
`XAUUSD.raw` worked makes everything after it a single probe.

A symbol that is quoted but not open for trading is reported as such, with that
reason, because "the broker does not have it" and "the broker will not let you
open one right now" lead to different fixes.

## Strategies

Four, and none of them claims an edge of its own. Every one reads the same
measured `LEVEL` signal `structures` publishes; they differ in which calls they
act on and where they put the stop and target. Adding a strategy is a claim
that a *subset* of those calls behaves differently — which the journal can
settle — not a new indicator.

```bash
uv run till-infinity trading strategies
TRADING_STRATEGIES=level-scalp,approach-scalp
```

| strategy | takes | stop | target |
|---|---|---|---|
| `level-scalp` | every actionable call | beyond the level | the expected push |
| `confluence-scalp` | only calls another timeframe agrees on | 1.5× wider | the expected push |
| `momentum-scalp` | only calls agreeing with three speeds of recent edge | beyond the level | the expected push |
| `approach-scalp` | a call confirming direction toward another level | beyond the level | the next level, short of it |

Several may run together. The first one to want a trade gets it, and the
one-position-per-instrument limit is what stops two of them doubling up.

### `momentum-scalp`, and the turn it will always miss

score.md §2 keeps three exponential averages and treats their agreement as the
confidence. The same three speeds run here over the signed edge of arriving
calls, and a trade needs all three to agree with the direction it states. The
cost is stated rather than hidden: the trade at the exact moment a move
reverses is the one all three disagree with.

It learns from **every** call published, including the ones it refuses.
Accumulating only from calls that reached the gate would have the three lines
agreeing with themselves by construction.

### The strategy that is not here

A fifth was written and removed: take the top decile of each instrument's own
recent `|edge|` rather than a fixed threshold, on the strength of
[score.md](score.md) §3's argument that a constant is a claim about a
distribution nobody has measured.

[edge.md](edge.md) had already measured it, on 10,483 call-outcome pairs. The
rolling quantile lost to the constant passing exactly the same volume by four
to ten points of direction, in all four comparisons, and the reason is specific:

> `edge` is *already* scale-free: it is a difference of two probabilities, and
> 0.11 means the same thing everywhere by construction. Normalising it per cell
> therefore destroys the comparability it already had.

That document ends with "do not build the rolling quantile, and record why,
because the instinct will recur". It recurred, here, and this is the record.
Rolling quantiles remain right for anything in volatility units — which is most
of this project — and wrong for this one quantity.

The same reading fixed a second thing. This module first shipped `min_edge` at
**0.08**, below the **0.10** `reactions.MIN_EDGE` that `structures` already
applies. Every call reaching the bus had cleared 0.10, so the trading gate
could not refuse anything: it looked like a limit and was not one. It is now
0.15, above the 0.0968 step edge.md measures and inside the band where
direction keeps improving, and a start-up warning fires if it is ever
configured at or below the upstream gate again.

### `approach-scalp`, and a null it is built around

The desk's setup: a level below price is something to sell down to, a level
above is something to buy up to, once something confirms the direction. The
confirmation is the ordinary level call; the target is the next level the book
knows about in that direction. The geometry is inverted from the others — they
enter at a level and take the push, this one enters on a call and exits at a
level — while the stop is unchanged, still anchored beyond the confirming
level, because that is still what makes the read wrong.

**[magnet.md](magnet.md) tested whether levels pull price and found they do
not.** Across 22,219 evaluation bars a level was reached within twenty bars
44.9% of the time against 49.5% for an arbitrary price the same distance away;
with the day held fixed the gap is nine-tenths of a point and indistinguishable
from zero. So this strategy is not an attraction bet, and it is built so as not
to become one:

- the target stops `approach_buffer_vol` (a quarter unit) **short** of the
  level, because the last stretch into the zone is precisely the part the
  measurement does not support;
- the distance is checked against `structures.timing` — magnet.md's own
  baseline — and refused when a driftless walk would rarely cover it inside the
  hold.

What remains is a rule for choosing a *target distance*, which the null does
not touch, on an entry that is separately measured. It is worth being clear
that this is the one strategy here resting on a desk observation rather than a
measurement in this repository, and that the repository's nearest measurement
is a null.

It is also given longer to work — forty-five minutes rather than the default
thirty — because the observation is that it takes twenty to thirty minutes to
deliver, and the default hold would close a good trade at the moment it started
paying. A strategy declares its own hold; it is carried on the intent, so a
position is timed out against the thesis that opened it.

The level map is built from the signals this module has already seen. It is a
cache of things published, honest about being one: levels within 0.35v are
merged, because the engine's Kalman mean moves as touches fold in, and anything
nobody has published a call for in six hours is forgotten rather than kept as a
description of last week.

## Risk plans

Ten numbers control how much this can lose, and set individually they are ten
chances to be inconsistent — 2% per trade under a 3% daily stop halts the day
on the second loss, which is not a plan. So they are grouped and named:

```bash
TRADING_RISK_PLAN=conservative
uv run till-infinity trading plans
```

| plan | per trade | per day | losses to halt | open | min p | min RR |
|---|---|---|---|---|---|---|
| conservative | 0.10% | 1.2% | 12 | 2 | 62% | 1.5 |
| standard | 0.25% | 3.0% | 12 | 4 | 58% | 1.2 |
| aggressive | 0.50% | 6.0% | 12 | 6 | 55% | 1.0 |

Each keeps the same relationship between per-trade risk and the daily stop — a
dozen consecutive losses to a halt — so moving between them changes what is at
stake without changing how the account behaves on a bad run. What varies is
selectivity: the conservative plan demands a higher probability and a better
reward-to-risk, and therefore trades less.

**A plan is a floor, not a cage.** Any individual `TRADING_*` variable that is
actually set wins over it, because a prop evaluation with a hard 4% ceiling
wants `standard` with one number changed, not a fourth plan. What the plan
guarantees is that the numbers you did not set are consistent with the ones you
did.

## The gates

Strategy decides whether a signal is worth trading. Risk decides whether *this
account, right now* should take another one. Three are worth their reasoning:

**One position per instrument.** A level fires repeatedly — that is what a
level is — and `structures` re-arms it after each resolution. Without this, a
level that is quietly wrong is not one loss but one loss per re-arm, all the
same direction, all for the same reason.

**A daily stop that halts rather than shrinks.** Reducing size after losses
sounds prudent and keeps trading a system that is currently wrong. The
reference is the day's opening equity, so the limit is a fact about today and
cannot be walked forward by a recovery. It lifts when the day does, and no
later: otherwise the size of the loss decides how long trading stops, which is
not a rule anybody chose.

**Spread as a fraction of the target.** Two pips is nothing against a target of
forty and fatal against one of five, and a scalper's targets are small by
construction.

## Sizing

Two conversions, both of which have to be the right way round.

Volatility units to price, because `structures` measures everything in them:
`price × vol_bps × multiple / 10_000`. The signal carries `risk_vol` and
`expected_push_vol` as multiples and `vol_bps` as the unit — the last of those
was added for this module, since a consumer reading signals off the bus cannot
price a distance without it.

Price to money, because MT5 states risk per lot as tick value over tick size: a
stop `d` away costs `d / tick_size × tick_value` per lot. Inverting that
against the risk budget gives lots.

Then round **down** to the broker's lot step and check the result still clears
the minimum lot — in that order. Clamping up to the minimum first silently
turns "this trade is too small to take" into "take it anyway at a risk nobody
authorised", which on a 0.25% budget and a tight stop is most trades on an
account whose minimum lot is 0.1. When it does not fit, the refusal says what
the minimum lot *would* have risked.

## What gets written down

Every fill is a `decide` with the numbers it was made from. Every close is an
`outcome` pointing back at it — the label. Every trade the strategy wanted and
the account refused is an `observe`, because that is the half of the record
that says what the limits cost.

Strategy-level refusals are counted per gate but not journalled: a strategy
declining on probability is the normal case, hundreds a day, and writing all of
it down would bury the refusals that matter under the filter working.

Positions are **reconciled, not assumed**. A stop hit server-side leaves no
message on any bus — the position is simply gone next time it is asked for — so
the open set is compared on every heartbeat and a vanished ticket is settled at
its last known price. That is exact on paper and slightly stale against a real
broker, and the journal entry says which, in `exit_source`.

## Announcements

Gated three ways, because the three messages have very different volumes:

```bash
TRADING_NOTIFY=1            # the master switch
TRADING_NOTIFY_FILLS=1      # rare, always worth seeing
TRADING_NOTIFY_CLOSES=1
TRADING_NOTIFY_DECLINES=0   # the most informative, and the easiest to drown in
```

Declines are off by default: every gate doing its job produces one, and a
halted day produces one per signal until the clock rolls over.

All of it still passes through the notification layer's own filter. Trade
alerts carry shape `trade`, so if `NOTIFY_SHAPES` has been narrowed, `trade`
has to be in it or none of these arrive however they are set here.

## Running it

```bash
# everything together, on paper
TRADING_ENABLED=1 uv run till-infinity run

# just the trader, against a shared bus
uv run till-infinity trading run --redis redis://host:6379 --plan conservative

# what this host can do, without touching a terminal
uv run till-infinity trading doctor
```

On its own the trader attaches, resolves what it can trade, and then waits for
signals — it needs `structures` publishing to the same bus, which on one
machine means `till-infinity run` and across several means Redis. It says so at
start-up rather than sitting silent.

## What this does not claim

No strategy here has been evaluated against its own outcomes. The signal they
all read is measured; the rules for acting on it are not, and the journal is
being collected so that they can be. Until that evaluation runs — the same
progressive-validation discipline `facto.py` uses, against the same baselines —
this is a way of acting on the level model consistently and recording what
happened, which is a different and smaller claim than an edge.
