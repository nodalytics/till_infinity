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
terminal does **not** arm it, and neither does anything else - there is exactly
one variable that puts money at risk, and it is printed at start-up whichever
way it is set.

On paper the whole path runs: symbols resolved against the broker, positions
sized against real equity, stops and targets placed, fills simulated against
the live bid/ask, outcomes journalled. What does not happen is the order.

## Windows and Linux

The `MetaTrader5` Python package is a binding onto a running Windows terminal -
an in-process call into a Win32 DLL. There is no Linux wheel and there will not
be one. So there are three backends and the host decides which:

| backend | runs on | reaches MT5 by |
|---|---|---|
| `mt5` | Windows, or a Wine prefix with a Windows Python | `import MetaTrader5`, in-process |
| `mt5-rpyc` | anywhere | a proxy of the module itself, over RPyC |
| `mt5-http` | anywhere | HTTP to a bridge running MT5 under Wine |
| `paper` | anywhere, no terminal at all | nothing; fills simulated against the quote |

The middle two both put the terminal on another host and differ in what crosses
the wire.

**RPyC carries the module.** A Windows Python inside the Wine prefix serves the
`MetaTrader5` module, and this process gets a proxy of it - same functions,
same arguments, same namedtuples - so the native backend drives it with no
changes at all. `mt5_rpyc.py` is connection handling on top of `mt5_native.py`
and no trading logic of its own, which is the point: a second copy would be a
second place for the filling-mode logic to drift.

```bash
# in the Wine prefix, once - the mt5linux package packages exactly this
wine python -m rpyc.utils.server --port 18812 ThreadedServer

TRADING_RPYC_HOST=127.0.0.1 uv run till-infinity trading doctor
```

Its cost is round trips: RPyC returns *netrefs*, handles to objects still
living on the other side, so reading eleven fields off a position is eleven
socket calls rather than eleven memory reads. Results are therefore
materialised as they arrive - one round trip instead of dozens - falling back
to the netref when a value will not copy, because slow still works.

**Never expose the RPyC server.** `allow_all_attrs` makes it a
remote-code-execution service by design. Bind it to localhost or a private
network and tunnel over SSH if the terminal is elsewhere. The HTTP bridge is
the one that can safely face a network; RPyC is the faster and more complete
one behind a boundary you control.

### Two bridges, one client

There are two of these and they are **not the same API**:
[`metatrader-terminal`](https://github.com/nodalytics/metatrader-terminal), the
published and more complete one, and `mt5-api`, an earlier variant that may
only exist locally. They share the `/api/v1` prefix, the `X-API-Key` header,
`POST /trading/order` and `POST /positions/close`, and differ exactly where it
matters:

| | `metatrader-terminal` | `mt5-api` |
|---|---|---|
| account | `GET /terminal/account/info` | none - falls back to `TRADING_ACCOUNT_EQUITY` |
| symbol list | `GET /symbols/` returns every name | none - suffixes must be probed |
| symbol spec | `GET /symbols/info/{symbol}` | `GET /symbols/{symbol}` |
| health | `GET /terminal/ping` | `GET /account/health` |
| move a stop | `POST /positions/modify` by ticket | only by internal `trade_id` |
| order reply | the terminal's `result` | the stored row, which serialised to `{}` |

The last two were added to `metatrader-terminal` for this client. Trailing a
stop over HTTP was impossible without a ticket route - the old one keys on a
row in the bridge's own database, so a position it had not recorded could not
be touched - and an order used to come back carrying no ticket, no retcode and
no fill price, leaving the caller to infer what it had just opened. Both are
read defensively, so an older bridge still works.

The client probes and adapts rather than picking one. That last row is not
cosmetic: `metatrader-terminal` has **no** bare `/symbols/{symbol}` route, so a
client hard-wired to it 404s on every symbol and concludes the broker carries
none - a total failure that looks exactly like a naming problem. And on
`mt5-api` the `info` route is the unusable one, because its response model
narrows the payload and drops `trade_tick_value` and `trade_tick_size`, which
are precisely what sizing needs. Each project's working route is the other's
broken one, so both are tried and the answer is accepted only when it carries a
tick value - a 200 with a narrowed body is not an error, so status alone cannot
tell them apart.

Where the symbol list exists it is used, and that is much the better path: the
account's suffix is found rather than guessed from a list that cannot be
complete.

Selection is automatic, in a fixed order - explicit `TRADING_BACKEND`, then the
native package, then the bridge, then paper - because a config file that has to
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
│          │              │ is Linux - use the mt5-http bridge                │
│ mt5-http │ yes          │                                                  │
│ paper    │ yes (chosen) │                                                  │
└──────────┴──────────────┴──────────────────────────────────────────────────┘
```

One line per backend, not just the chosen one: "why is it on paper" has an
answer per backend, and printing one of them is how the other gets missed.

## What can be traded here

Gold and BTC by default. The other twelve instruments the price side tracks can
be named, and will only trade if the broker actually quotes them - a retail MT5
account carrying `XAUUSD` and `BTCUSD` very often carries no `SOLUSD` under any
name, and no `US100` either.

So availability is discovered once, at start-up, against the terminal:

```bash
uv run till-infinity trading symbols -s gold -s btc -s sol
```

Brokers also suffix every symbol by account type - `.raw`, `.r`, `m`, `.pro` -
and the suffix is the same across the account. It is **learned** rather than
enumerated: probing ten suffixes against five candidate names for fourteen
instruments is seven hundred round trips over the bridge, and noticing that
`XAUUSD.raw` worked makes everything after it a single probe.

A symbol that is quoted but not open for trading is reported as such, with that
reason, because "the broker does not have it" and "the broker will not let you
open one right now" lead to different fixes.

## Strategies

Twelve. Eleven are arithmetic over the measured signal and claim no edge of
their own; the twelfth is a panel of agents that reasons its own way to an
answer. Every one reads the same measured `LEVEL` signal `structures`
publishes; they differ in which calls they act on and where they put the stop
and target. Adding a strategy is a claim that a *subset* of those calls behaves
differently - which the journal can settle - not a new indicator.

```bash
uv run till-infinity trading strategies
TRADING_STRATEGIES=snap,thesis-only,runner,confluence-scalp,sweep-aware,fade-to-value,approach-scalp,level-scalp
```

Each stamps its own magic number on the orders it places, so the journal can
say which strategy a position belonged to after a restart - see "Which strategy
opened it".

| strategy | magic | takes | stop | target |
|---|---:|---|---|---|
| `level-scalp` | 777702 | every actionable call | beyond the level | the expected push |
| `confluence-scalp` | 777703 | only calls another timeframe agrees on | 1.5× wider | the expected push |
| `momentum-scalp` | 777704 | only calls agreeing with three speeds of recent edge | beyond the level | the expected push |
| `approach-scalp` | 777705 | a call confirming direction toward another level | beyond the level | the next level, short of it |
| `swing-level` | 777706 | a 4h/1d/1w level, triggered as low as 15m | beyond the level, 1.5× | the expected push |
| `sweep-aware` | 777707 | the plain call, unless the stop is in front of liquidity | beyond the zone | the expected push |
| `fade-to-value` | 777708 | the distance from spot to the best-evidenced level | beyond the triggering level | short of fair value |
| `council` | 777709 | whatever four agents agree on, or nothing | as the panel proposes, clamped | as the panel proposes, clamped |
| `snap` | 777710 | the same call as `level-scalp` | the same | the same, on a two-minute clock |
| `thesis-only` | 777711 | the same call as `level-scalp` | a circuit breaker, far out | the same |
| `runner` | 777712 | the same call as `level-scalp` | the same | 3× the push, the trail exits |
| `inverse` | 777713 | the calls the model rates highest, traded the other way | the same | the same |

### The last four are experiments, and each changes exactly one thing

`snap`, `thesis-only`, `runner` and `inverse` all take the identical call
`level-scalp` takes. That is deliberate: run beside it on the same signals,
each becomes a controlled comparison rather than another opinion.

* **`snap`** holds for two minutes instead of thirty. The median touch resolves
  in **eighteen seconds** and the fast ones carry the *larger* push, so holding
  longer gets less of the move while staying exposed to what comes next.
* **`thesis-only`** moves the stop out to a circuit breaker. Six of twelve
  stopped trades later reached their target, by 3.7R to 25.7R, so this tests
  the stops directly rather than adjusting them again.
* **`runner`** moves the target out past the push distribution and lets the
  trail end the trade. Replayed, letting the move run returned +8.4R against
  +1.7R for a fixed target.
* **`inverse`** trades the opposite side. If it loses what the others lose,
  direction is not the problem; if it wins, the entries and stops have been
  polishing a sign error. Disabled 2026-08-27 after five trades.

### `high-timeframe` was removed

Added and removed the same day, as a near-duplicate of `swing-level`: they
shared entries, context and the requirement that a higher timeframe agree. What
it had that swing-level did not - a resting entry, protection scaled to the
horizon, the momentum filter - moved across, and then became general (see
"Protection scales with the horizon"). Its magic slot stays reserved, because
that table is append-only: a magic that has been on live orders has to keep
resolving to the name that placed them.

### Protection scales with the horizon

Break-even, the trail and the momentum filter are all denominated in **one bar
of the entry interval**, and a trade is held for many. That is the same mistake
`stop_hold_scaling` exists to correct, so `Strategy.horizon` stretches them by
the square root of the hold, capped at `max_stop_scale`.

They used to be constants on each strategy, which meant every new one
rediscovered the arithmetic and `high-timeframe` carried hand-picked doubles of
the scalpers' numbers. Now a strategy states its intent once and it means the
same thing on a two-minute hold and a two-day one.

**Break-even is deliberately excluded.** It is in R, and R is measured against
a stop this same reasoning has already widened - scaling it again counts the
horizon twice and put `level-scalp` on a 5.5R break-even, a threshold that
never fires.

Several may run together. The first one to want a trade gets it, and the
one-position-per-instrument limit is what stops two of them doubling up.

### The order they are listed in is a decision

Because the first taker wins, `TRADING_STRATEGIES` is not a set. It is a
priority list, and getting it backwards silently disables strategies rather
than failing.

**The rule: most selective first, the permissive one last.** A strategy that is
another strategy plus extra refusals can only ever trade what the permissive
one declined - and it declined those for reasons the stricter one would decline
too. Listed second, it never fires at all, and nothing says so: the log shows
it loaded, the config shows it enabled, and it books no trades forever.

`sweep-aware` is exactly that shape - `level-scalp` with two extra refusals -
so `level-scalp,sweep-aware` runs one strategy wearing two names. Reversed,
the same pair splits the flow: `sweep-aware` takes the calls whose stop is not
standing in front of resting liquidity, `level-scalp` takes the rest. Same
signal stream, two comparable books, which is what makes
`till-infinity trading report` worth reading.

So `level-scalp` belongs last. It is the baseline every other strategy is a
restriction of, and last is where a catch-all does its job instead of starving
the others:

```bash
TRADING_STRATEGIES=sweep-aware,fade-to-value,approach-scalp,level-scalp
```

Ordering does **not** flip a trade's direction. Every strategy here reads the
same directional call; they differ in which calls they act on, where the stop
goes and where the target goes. `approach-scalp` enters on a call and exits at
the next level where the others take the expected push, so what the order
decides is the target geometry and the hold, not the side.

### Entry and anchor: two timeframe sets, not one

The service accepts **every timeframe a level forms on** - 1m, 3m, 5m, 15m, 1h,
4h, 1d, 1w. Each strategy then declares two things, and the split is the useful
part:

- **`entries`** - where a trade may be *triggered*. The entry fixes the stop,
  so this is the lower set.
- **`context`** - where the *bias* comes from. Higher timeframes that trigger
  nothing and say whether a trigger is worth taking.

| strategy | triggers on | anchored to | needs it | hold |
|---|---|---|---|---|
| `level-scalp` | 1m, 3m, 5m | 15m, 1h, 4h | no | 30m |
| `confluence-scalp` | 1m, 3m, 5m | 15m, 1h, 4h, 1d | **yes** | 30m |
| `momentum-scalp` | 1m, 3m, 5m | 15m, 1h | no | 30m |
| `approach-scalp` | 1m, 3m, 5m, 15m | 1h, 4h, 1d | no | 45m |
| `swing-level` | 15m, 1h, 4h | 4h, 1d, 1w | **yes** | 6h |
| `council` | whatever is allowed | whatever is allowed | no | 45m |

**`swing-level` is the clearest case.** Its bias is the daily, but it triggers
as low as 15m - because the entry is what fixes the stop, and a stop measured
on 15m is a fraction of one measured on 1d for the identical idea. Same thesis,
smaller distance to being wrong, so the same money buys more of it. That is
risk reduction, not a different trade.

Context reaches a strategy through the signal's `confluence` - the timeframes
`structures` already found agreeing on that price. It is read rather than
recomputed: asking again here would be a second, differently-wrong answer to a
question settled upstream.

An anchor has to be **higher**, not merely different. A 1m call confirmed by 3m
is the same fast noise seen twice, which is a weaker claim than the one
`confluence-scalp`'s name makes - and is what it used to accept.

The effective entry set is the **intersection** of what the strategy claims and
what `TRADING_INTERVALS` allows, so configuration can narrow a strategy and
never widen one onto data its reasoning was not built for.

This was wrong for a day and cost what that kind of bug costs. The module
accepted `1m,5m` on the false grounds that "structures only builds levels on
those two"; that is `structures.config.INTERVALS`, the *anomaly detector's*
fast-data set. Six of eight timeframes were discarded in silence, and the first
live signal was a 3m EURUSD call delivered to Telegram and ignored by the
trader in the same second.

### `confluence-scalp`, and a measurement that argues against it

It takes only calls another timeframe agrees on. The intuition is the level
model's own - several timeframes on one price is one structure seen several
times - and it is worth knowing that **the only measurement bearing on it found
nothing**.

[strength.md](strength.md) tested confluence depth against whether a level
holds. Four runs produced four different orderings, and as a ranking signal
depth scores an **AUC of 0.476 and 0.452** - below 0.5, meaning that if
anything more agreement goes very slightly with breaking. `depth >= 3` against
`depth < 3` is −2.2 [−6.3, +1.7], −5.2 [−9.4, −1.2] and +0.3 [−4.2, +4.9]: not
one interval excludes zero the way this strategy assumes. The same document
calls `Zone.strength`'s `1 + 0.15 × (depth − 1)` multiplier "unearned".

Two things separate this strategy from that result, and neither is a defence
strong enough to call it validated. What was measured is *did price get through
the level*, which strength.md is explicit is not *did the trade make money* - a
level that holds after a 3v excursion is a hold and a loss. And this **selects**
on depth rather than weighting by it, which is a different object from a
multiplier on a score.

Treat it as unvalidated and probably not better than `level-scalp`. It stays a
named strategy so the journal can settle it, rather than the assumption living
as a flag inside the default.

### `momentum-scalp`, and the turn it will always miss

score.md §2 keeps three exponential averages and treats their agreement as the
confidence. The same three speeds run here over the signed edge of arriving
calls, and a trade needs all three to agree with the direction it states. The
cost is stated rather than hidden: the trade at the exact moment a move
reverses is the one all three disagree with.

It learns from **every** call published, including the ones it refuses.
Accumulating only from calls that reached the gate would have the three lines
agreeing with themselves by construction.

### `fade-to-value` - the thesis, plainly

Every other strategy reacts *at* a level. This one asks the question the README
opens with, and takes the difference.

**Fair value is the best-evidenced level within reach, not the nearest one.** A
price the instrument has turned at forty times is a claim about value; one it
clipped twice is barely a claim at all. Taking the closest level regardless
would make the valuation a function of where price happens to be standing,
which is not an estimate of anything.

**The stance is arithmetic.** Fair value above the market is a long, below it is
a short. Nothing is forecast.

**The distance has to clear the noise.** Fair value is a distribution and
volatility is its width, so inside `fade_min_distance_vol` there is nothing to
say. And the target stops short of fair value, for the reason `approach-scalp`
does: price is not drawn to a level, so the last stretch into the zone is the
part that was measured and did not survive.

The stop goes beyond the level price is standing *at*, outside its zone - if
price settles through that, the estimate that said it was cheap here is what
failed.

### `sweep-aware` - refusing to stand in front of the door

`level-scalp` places its stop outside the zone and stops thinking about it.
This one asks whether that stop sits between price and the next obvious pool of
resting orders, using two numbers `structures.sweeps` publishes:

- `sweep_rate` - the share of this level's decisive interactions, on this side,
  that were `TRAP`. A level run four times in ten is telling you about itself
  directly.
- `liquidity_beyond_vol` - how far to the next level out, on the side a sweep
  would travel.

Their ratio is what gets judged. A 1.2v stop with liquidity 1.0v beyond sits
*past* the pool, which is the worst place to stand.

**It refuses rather than widening the stop.** Widening keeps the trade and
changes what it costs, which sizes a worse trade smaller rather than declining
it - and sizing already assumes the stop is where the thesis is wrong, not
where it is convenient.

### `council` - agents that reason their own way to a trade

The other four read the measured signal and apply arithmetic. This one hands
the same evidence to several models with **different reasoning modes** and lets
them reach their own conclusion, including that there is no trade.

```bash
TRADING_STRATEGIES=level-scalp,council
```

**Why different modes rather than several copies.** Asking one model five times
gives five answers with the same blind spots. Four told to reason in different
ways fail differently - and only then does agreement mean anything. A committee
that agrees because every member made the same mistake has confirmed nothing.

| voice | argues from | its characteristic error |
|---|---|---|
| `trend` | continuation | late, buying exhaustion |
| `contrarian` | exhaustion, mean reversion | standing in front of something that keeps going |
| `quant` | the numbers only, against base rates | blind to context |
| `skeptic` | refusal - must be convinced | abstaining when there was a trade |

The skeptic matters most. Somebody whose job is to say no is the difference
between a panel and a chorus.

**They discuss, once.** First independently - a first round that could see its
neighbours would collapse onto whoever answered first, which is the failure a
committee exists to avoid. Then each sees what the others concluded and may
revise. One round only, because the second is where a panel starts agreeing for
social rather than evidential reasons, and because every round is four more
model calls.

There is no judge. A judge is another model with another blind spot; the
resolution is arithmetic - a quorum on a side, and the median of what those who
agreed proposed.

**Abstaining is a real answer** and is removed from the count rather than
counted as opposition. A panel that cannot say "I don't know" will always find
a trade.

**What they may and may not decide.** They choose the side and the stop and
target *in volatility units* - the shape of the trade, in the project's own
scale-free currency. They do not choose the size: that is `sizing.lots` against
the risk budget, and it is not a matter of opinion. Their numbers are clamped
to 0.4-4v on the stop and 0.5-8v on the target, because a model proposing a
forty-unit stop is failing rather than being bold, and clamping makes the
failure harmless instead of expensive.

**Everything still passes the gates.** The council's intent goes through
`Guard` exactly as any other - news blackout, drift pause, broker dislocation,
exposure, reward-to-risk, spread, the daily stop. It decides what to propose,
not what is allowed.

**It costs money.** Four voices over two rounds is eight model calls per signal
considered, so `TRADING_COUNCIL_DAILY_CALLS` is a ceiling rather than a tuning
knob. Any failure - timeout, no credential, a malformed answer - reads as an
abstention, because a model that timed out has not made a case for a trade.

Like every other strategy here, it is **unvalidated**. It is a named strategy
precisely so `trading report` scores it against the arithmetic ones rather than
the question being settled by which sounds cleverer.

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
Rolling quantiles remain right for anything in volatility units - which is most
of this project - and wrong for this one quantity.

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
knows about in that direction. The geometry is inverted from the others - they
enter at a level and take the push, this one enters on a call and exits at a
level - while the stop is unchanged, still anchored beyond the confirming
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
- the distance is checked against `structures.timing` - magnet.md's own
  baseline - and refused when a driftless walk would rarely cover it inside the
  hold.

What remains is a rule for choosing a *target distance*, which the null does
not touch, on an entry that is separately measured. It is worth being clear
that this is the one strategy here resting on a desk observation rather than a
measurement in this repository, and that the repository's nearest measurement
is a null.

It is also given longer to work - forty-five minutes rather than the default
thirty - because the observation is that it takes twenty to thirty minutes to
deliver, and the default hold would close a good trade at the moment it started
paying. A strategy declares its own hold; it is carried on the intent, so a
position is timed out against the thesis that opened it.

The level map is built from the signals this module has already seen. It is a
cache of things published, honest about being one: levels within 0.35v are
merged, because the engine's Kalman mean moves as touches fold in, and anything
nobody has published a call for in six hours is forgotten rather than kept as a
description of last week.

## Scalping, swinging, both, or neither

`TRADING_STYLE` is a coarser switch than `TRADING_STRATEGIES`, and the two
compose - it filters whatever that list selected. Values are `scalp`, `swing`,
`both` (the default, which changes nothing) and `none`.

`none` is a useful state rather than a broken one: the service connects, warms
every estimator, publishes signals and takes no trades. It says so loudly at
start-up, because a process doing that looks identical to a fault.

**A strategy declares its own style, and the names do not decide it.**

| swing | why |
| --- | --- |
| `swing-level` | six hours, anchored on the daily |
| `approach-scalp` | forty-five minutes - longer than `max_hold`, despite the name |
| `fade-to-value` | forty-five minutes, and a thesis about value rather than the next few ticks |
| `runner` | a swing by target rather than clock: `target_multiple` 3.0 puts the exit past the modelled push |

Everything else is a scalp: `snap` at two minutes, and `level-scalp`,
`confluence-scalp`, `momentum-scalp`, `thesis-only`, `sweep-aware` and
`inverse` at the configured `max_hold`.

**An unrecognised value runs everything rather than nothing.** A typo in an
environment variable must not be able to stop trading - a mis-set base-rate
floor once refused 99 signals out of 99 and did exactly that.

## The swing that runs between two origins

An origin is where volatility turned - the last opposing bar before an impulse,
kept as a zone because the zone is what price reacts to. `origin-swing` trades
the space between two of them.

When price sits between an origin above and an origin below there are two
places worth trading and one question: which does price reach first. It
arrives, it is confirmed there, and the trade runs to the opposite origin. Long
from the one below, short from the one above.

**The side comes from the origin, not the published direction.** The direction
on the call is about the level, and this strategy is not trading the level. It
is set in `quality` and read by `orient`, which run in that order, and it is
reset on every call so a refused signal cannot hand its side to the next one.

**The target is structure, not a multiple.** `expected_push_vol` is a forecast
about the next few bars; over a swing horizon the honest answer to "how far
does this go" is "to the next place that stopped it last time".

**The stop clears the origin being traded, by an amount the instrument sets** -
the far edge of the zone plus half a volatility unit. Inside the zone is where
the wicks are, and a stop there is taken out by the rejection the trade exists
to trade. Anchoring on the level, as every other strategy does, put the stop on
the wrong side of the fill outright: a long at the lower origin, 2v under the
level, got a stop *above* its own entry and was refused as already through.

**Both witnesses, not either.** The 4h rejection candle says the auction failed
there; the momentum ensemble below 1h says it is failing *now*. The disjunction
the scalps use is right for them - a scalp cannot wait four hours for a bar to
close, and requiring both would refuse a clean fast turn for having no candle
yet. A swing has the time, and an origin price merely touched is not one that
rejected it. `needs_both_witnesses` is what separates the two.

**What is claimed, and what is not.** Origin *freshness* separates: never
revisited returned 1.136R against 0.822R for twice revisited. Origin
*proximity* did not - it read +0.299 on the first live sample and **-0.166 over
49,619**. So nothing here scores on distance. The bracket is used as geometry -
where to enter, where to aim, where the stop clears - and that is a placement
decision this repository has not measured either way. It is a hypothesis with
its reasoning written down, not a finding.

## Risk plans

Ten numbers control how much this can lose, and set individually they are ten
chances to be inconsistent - 2% per trade under a 3% daily stop halts the day
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

Each keeps the same relationship between per-trade risk and the daily stop - a
dozen consecutive losses to a halt - so moving between them changes what is at
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

**One position per instrument.** A level fires repeatedly - that is what a
level is - and `structures` re-arms it after each resolution. Without this, a
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

Four more come from outside the level model, in `context.py` and
`exposure.py`. All of them fail open - a missing input never stops the system
trading, because a collector restarting is not a reason to halt.

**A high-impact release about to land.** `news.events` is on the bus with
importance and country, so the trader stands aside around anything rated high.
A US print blacks out gold, BTC *and* all seven majors, because the dollar is
on one side of every one of them. The window is asymmetric and wider after the
print than before: beforehand the job is only to not be holding when the number
lands, whereas afterwards the spread is at its widest and the first move
frequently reverses.

The `country` field carries **both** an ISO code and a currency code depending
on the source - TradingView writes `US`, `DE`, `GB`; ForexFactory writes `USD`,
`EUR`, `GBP` - which was checked against the stored events rather than assumed.
Both forms are mapped.

**Our broker out of line with the venues.** You have six venues quoting each
instrument and one broker filling. Two checks fall out for free: refuse to
enter when our quote sits more than `max_dislocation_bps` from the venue
median, and refuse when our spread is more than `max_spread_ratio` times the
group's. Both need three venues before they say anything, matching the quorum
`structures` requires of a consensus bar, and a venue that has stopped updating
drops out after ninety seconds so one dead feed cannot manufacture a
dislocation on everybody else.

**A regime change.** A `drift` signal means every level on that instrument
learned its behaviour in a regime that has ended. `structures` already
discounts them; the trader stops entering for `drift_pause` seconds while they
re-form.

**Too much of the book on one currency.** `max_positions` counts tickets. Long
EURUSD, long GBPUSD and long AUDUSD is **three positions and one trade** -
all short dollars, right together and wrong together - and a limit reading "3
of 4 used" has authorised triple what it thinks. So exposure is decomposed into
currency legs and limited there, weighted by money at risk rather than by lots,
since a 0.01-lot gold position and a 1-lot EURUSD position are comparable in
nothing else.

The decomposition is structural, not fitted: EURUSD and GBPUSD share a dollar
leg by construction, and gold, the crypto and the indices are all treated as
long-the-thing, short-USD because that is how they are quoted. A measured
correlation matrix would be better on the day it was fitted and would then need
refitting and monitoring; this version cannot go stale. The limit is 2x the
per-trade risk in every plan, so the third same-direction dollar trade is the
one refused - which is the case it exists for.

## Moving a stop, once the trade is on

Break-even and trailing stops are implemented and **off by default**.

```bash
TRADING_BREAK_EVEN_AT=1.0     # stop to entry once 1R in front
TRADING_BREAK_EVEN_TICKS=2    # a cushion, because a long exits on the bid
TRADING_TRAIL_VOL=1.0         # trail a volatility unit behind the best price
```

They are off because both cut the loss tail *and* cut winners, and which
dominates is an empirical question about this strategy on these instruments
that nothing here answers. Shipping them on would be asserting the answer. They
exist so the experiment can be run: four combinations, compared on the journal
once there are enough closed trades.

The stop only ever moves toward profit - every path returns the existing stop
unless the new one is strictly better. A rule that can widen a stop is not risk
management, it is the trade asking for more room after it has started going
wrong, and that does not get cheaper for being automated.

If you turn these on, **switch the mt5-api trailing handler off**. It runs on
its own twenty-second timer, and two things moving the same stop on different
clocks race - with the loser looking like a broker fault.

## The hold releases what is not working, not what is

`_expire` closes a position that has outstayed the hold its strategy asked
for. It used to do that on **age alone**, without asking what the trade was
doing - so a position a point in front at the thirty-minute mark went out at
market and the rest of the move happened without us. Observed on gold: out at
4623 on a fall that carried to 4592.

That is a defect in the hold's own intent rather than a strategy choice. The
hold exists to release capital from a thesis that is not playing out. Capping
one that is playing out is a different rule, and not one anything here argued
for.

So a trade past its hold is kept instead of closed when three things are true:

* **it is in front** by `hold_extends_at` times the risk it was sized for,
  measured from the price it would actually close at rather than the mid, and
  from the current price rather than the best seen - the best price is history
  the trade may already have given back;
* **it can be protected** - the stop moves to break even plus the spread
  cushion *before* the extension is granted, so the worst outcome after that
  point is a scratch. If the broker refuses the move the trade closes on the
  clock as before, rather than being held unprotected;
* **it ends** - `max_hold_multiple` caps total age, because a position kept
  indefinitely accrues swap, crosses sessions it was never measured in, and
  eventually sits over a weekend.

Off by default (`hold_extends_at = 0`), like the rules in `manage.py` and for
the same reason: which side of the trade-off wins is an empirical question the
journal has not answered yet. Unlike those, this one cannot cost a winner - it
only declines to cut one - and its downside is bounded at a scratch by the
break-even move it requires.

## Ground truth on the bus

`structures.resolutions` carries what a touch actually did - held, broke,
trapped, chopped, with the push and the time it took. It went only to the
journal until now, which left everything consuming `structures.signals` blind
to whether the calls it acted on were right.

It is published **unconditionally**, not only for touches something predicted:
most resolutions were never called by anything, and those are exactly the ones
a consumer learning what levels do needs to see. Gating on "did we have a
decision for this" would publish only the sample that teaches least.

The trader subscribes and counts them today, and acts on none of them. That is
deliberate - the topic has a subscriber from the day it shipped, so whatever is
built on it first is not also debugging whether the messages arrive. What it
unlocks: the back-check strategy (a measured asymmetry - 27 of 70 breakout
attempts were false), edge.md's accuracy-targeting gate, and eventually a Kelly
fraction. None of them exists yet.

## Where the stop goes

Three things decide it, and they are applied in this order.

**Beyond the level, not beyond the entry.** The level is what is being traded,
so the trade is wrong when price is through *it*, whatever the fill happened to
be. Anchoring to the fill would move the invalidation point every time the
spread widened.

**Outside the zone.** A level is a range: the origin at the centre, each edge
stretched by how far the wick ran past it on that side. A stop at
`origin - distance` can sit inside the band where wicks routinely reach, which
is a standing offer to be swept and then watch the trade work without you.

**At least one volatility unit away.** Fair value is a distribution and
volatility is its width, so a stop closer than a unit is inside the estimate it
is protecting. This is the same sentence the thesis uses about distance - one
unit is noise, three is a statement - applied to the stop before the entry.

The third exists because the first two were not enough. Measured on the first
two live trades, both gold sells: `risk_vol` of 0.53 and 0.61. The second was
stopped at 4626.09 on a 1.05-point stop and price then fell to 4615. The zone
check had worked - the zone edge was 4625.58 and the stop went outside it at
4626.02 - but the level was young, its recorded wick was 0.35v, and a narrow
zone cannot widen a stop that was never wide enough.

`risk_vol` comes from the level model, which is answering "where does this level
stop being true". What a *tradable* stop costs is a different question, and
answering both with one number lets the cheaper answer win silently.

**Widening shrinks the size, not the risk.** The budget is fixed, so a wider
stop buys fewer lots, and a trade that can no longer make the minimum lot is
refused. A stop inside the noise is not a cheaper trade, it is a worse one.

### The stop clears the fill, not only the level

Two rules above place the stop against the **level**: beyond the zone, and at
least `min_stop_vol` away. Both are right, and neither says anything about
where the fill landed.

Entry is a market order, so it lands wherever price is when the call arrives -
which can be most of the way to a level-anchored stop. `approach-scalp` feels
this hardest, because entering away from the level it measures is its whole
geometry. Sizing then measures `abs(entry - stop)`, correctly, because that is
what is actually lost. Put together they are a trap: a fill one unit above its
own stop is sized as a one-unit trade, which is a **large** one, and is then
taken out by ordinary movement rather than by the thesis breaking.

Live, on gold: a buy filled at 4620.8 against a stop at 4619.4 that sat a
proper 5.9v below the level at 4627.7 but only 1.0v below the fill. Sized 0.18
lots on the short distance. Stopped within minutes for -26.64.

So the floor is applied from both anchors. It can only push the stop further
from the fill, so it can only reduce size for the same money at risk, and it
never moves a stop closer in.

**It runs after the `through` check, and that order is not a detail.** A fill on
the far side of the level-anchored stop is a trade that has already been
invalidated, not one to re-stop. Applying the floor first quietly rebases the
stop below such a fill and turns a refusal into a position - which is exactly
what the first attempt at this did, and what an existing test caught.

## Sizing

Two conversions, both of which have to be the right way round.

Volatility units to price, because `structures` measures everything in them:
`price × vol_bps × multiple / 10_000`. The signal carries `risk_vol` and
`expected_push_vol` as multiples and `vol_bps` as the unit - the last of those
was added for this module, since a consumer reading signals off the bus cannot
price a distance without it.

Price to money, because MT5 states risk per lot as tick value over tick size: a
stop `d` away costs `d / tick_size × tick_value` per lot. Inverting that
against the risk budget gives lots.

Then round **down** to the broker's lot step and check the result still clears
the minimum lot - in that order. Clamping up to the minimum first silently
turns "this trade is too small to take" into "take it anyway at a risk nobody
authorised", which on a 0.25% budget and a tight stop is most trades on an
account whose minimum lot is 0.1. When it does not fit, the refusal says what
the minimum lot *would* have risked.

## What gets written down

Every fill is a `decide` with the numbers it was made from. Every close is an
`outcome` pointing back at it - the label. Every trade the strategy wanted and
the account refused is an `observe`, because that is the half of the record
that says what the limits cost.

Strategy-level refusals are counted per gate but not journalled: a strategy
declining on probability is the normal case, hundreds a day, and writing all of
it down would bury the refusals that matter under the filter working.

Positions are **reconciled, not assumed**. A stop hit server-side leaves no
message on any bus - the position is simply gone next time it is asked for - so
the open set is compared on every heartbeat and a vanished ticket is settled at
its last known price. That is exact on paper and slightly stale against a real
broker, and the journal entry says which, in `exit_source`.

## Which strategy opened it

Several strategies run side by side, and the position they leave at the broker
has to say which one asked for it. Otherwise a report merges two books into one
number, and the number is the one somebody decides on.

The order comment carries the name, but a comment is advisory: MT5 caps it at
31 characters and brokers truncate and rewrite it. **Magic is the field that
survives.** So `TRADING_MAGIC` is not a single number any more, it is the base
of a band:

| magic | means |
| --- | --- |
| `base` | ours, strategy unknown - a trade opened before this existed, or by a plugin |
| `base + 1 .. base + 8` | one fixed slot per name in `MAGIC_ORDER` |
| the rest of the band | anything registered from outside the package, hashed |
| outside the band | **not ours.** Never touched, never closed |

With the default base of `777701` that reads `level-scalp=777702`,
`sweep-aware=777707`, `fade-to-value=777708`, and so on. The map is printed at
start-up.

Three decisions in there are worth more than the numbers.

**`MAGIC_ORDER` is append-only.** These numbers end up on positions held at a
broker and in journal entries that outlive any one release. Reordering the
tuple would silently reattribute history - a trade opened by one strategy would
start reading as another's, and nothing would look wrong.

**The offset does not come from the configured list.** Deriving it from
`TRADING_STRATEGIES` would be the same bug in a worse form: editing that
variable would renumber every open position, and a restart mid-trade could not
say who owned what. It comes from the name.

**Ownership is a band, not an equality.** This is the part that had to change
in three places at once. The comparison used to be `magic == settings.magic`,
and left alone it would have made every position opened by a named strategy
look like somebody else's - so the trader would have stopped managing and
closing its own trades. The HTTP bridge also stopped *sending* a magic in the
positions query for the same reason: a query parameter can ask for one exact
number, and one exact number is now the wrong question.

Two strategies can only collide in the hashed tail, and start-up says so out
loud when they do rather than leaving it to be found in a scorecard that looks
fine.

## Managing a trade once it is on

Three rules, and all three were switched on only after something in the record
asked for them.

**Break-even** at `break_even_at` R in front moves the stop to the entry plus a
spread cushion, so a trade that was won cannot become one that was lost. It
earned its keep within two minutes of being enabled - a uk100 short went 4.4R
in front, the stop moved, and it closed for +69.

**Trailing** keeps the stop behind the best price the trade has seen, and the
distance is **the level's own** rather than a flat number. `trail_vol` is in
volatility units so it already adapts across instruments - 2v on gold is not 2v
on the FTSE - but it did not adapt to how far *this level's* pullbacks run, and
that is what a trail has to survive. A level whose wicks reach 3v takes out a
2v trail on an ordinary retracement while the move is still going, which is
being stopped by noise in profit. The wick mean plus a share of its spread is
the floor now, with `trail_vol` as the minimum.

**The hold extension** keeps a trade past its clock if it is working, after
moving the stop to break even first - see below.

**All three announce themselves.** Fills and closes were announced and stop
moves were not, so the channel showed a trade opening at one risk and closing
at another with nothing in between to explain it. A stop move gets its own
event kind so it neither suppresses nor is suppressed by the fill and the close
it sits between.

## Sizing for the stop we get, not the stop we place

Stopped trades cost **1.09R** against the 1.00R they were sized for, and the
number held steady across 13, 25 and 27 stops - the most stable measurement in
the journal. The decomposition says where it comes from, and it is not where a
day of entry work assumed:

| | mean |
| --- | ---: |
| entry slippage - filled worse than decided | +0.025R |
| exit slippage - closed beyond the stop | **+0.062R** |
| together | +0.087R |

**The exit is two and a half times the entry.** Candlestick confirmation, the
momentum filter and the pullback all target the entry, which is the smaller
half.

The exit half is not a defect to remove. A broker stop is a market order once
triggered, so it fills through the spread and any gap; that is what a stop is.
The defect is *sizing* against the stop we place rather than the one we get,
which breaches the risk budget on every loss - quietly, and by a constant.

`stop_slippage` inflates the distance `lots` sizes against, so a stop filling
9% past its price costs the money it was budgeted to cost.

**This does not improve returns and should not be read as if it does.**
Positions get about 8% smaller and losses land where they were meant to. What
it buys is that `max_risk_money`, the daily loss fraction and every per-trade
budget mean what they say, instead of being exceeded by 9% whenever a trade
loses - which is the direction that matters.

### `risk_money` changed meaning, and it is easy to trip over

It is now the loss a stop is **expected to cost**, computed from the inflated
distance - not the loss at the drawn stop. The two differ by the slippage.

That is the more useful definition, because it can be compared straight
against the risk budget. But it no longer reconciles against `volume x
stop_distance x tick_value`, so anyone checking the number against the stop on
the chart will find it does not add up, and will be right that it does not.

### Two sizing factors now compound

`trend_sizing` and `stop_slippage` are independent and multiply. In deep chop
that is roughly 0.75 x 0.92, so about **0.69x** the position the same signal
would have taken before either existed. Both factors are individually
measured; nobody chose 0.69. If sizes look too small, `trend_sizing` is the
dial to turn first - it has the larger effect and the thinner evidence behind
it.

## Three more, about execution rather than direction

Added together because they answer one question - what to do with a position
once it exists - and none of them needs a view on where price is going. All
three are off by default.

**Scaling out** takes `scale_out_fraction` of the position off at
`scale_out_at` R and lets the rest run. The push distribution is wide - median
2.24v, p75 3.37v, p90 4.93v - and a single exit has to choose which half of it
to serve. Banking part at the modelled push and running the remainder serves
both, and it is the honest form of `runner`, which bets the whole position on
the tail and will pay for that in win rate.

It reads the **current** price, after a first version read the best price and
was wrong about it. The original argument was that a trade which touched 1.2R
and retraced had already *earned* the partial. Production showed what that
means: a us30 position logged `banking 50% at 1.5R` and booked **−1.14**,
because the trigger read a high-water mark while the close executed at market
whenever the manage loop next ran - by which time price was back through the
entry.

The point of banking is to capture a gain that is *there*. A high-water mark
is a gain that *was* there, and arming a market order against it prices an
offer nobody is making any more. The log line then describes an event that did
not happen, which is worse than not banking at all.

Break-even and trailing still read `best`, and correctly: they protect a trade
against giving back what it made, which is a different question from realising
it.

The volume arithmetic is where this rule breaks if it breaks, and the failure
is not a refusal. A minimum-lot position cannot be halved, and a broker asked
to close 0.005 of a 0.01 lot may close the lot instead - a scale-out that has
silently become a full exit while still reading as a scale-out in the log. So
the slice rounds *down* to the volume step, both halves must clear
`volume_min`, and if either would not, nothing comes off and the position runs
whole.

**The stale exit** closes a trade that has gone nowhere. The median touch
resolves in eighteen seconds and 84% inside five minutes, against holds here
measured in half hours. A position still sitting at its entry long past
`stale_after` is not waiting for its thesis - it is giving noise time to reach
the stop, which is a losing trade arrived at slowly. Closing flat costs the
spread instead. Measured from the best price again, which is the conservative
direction: a trade that reached `stale_move` R and retraced has started, so
only the ones that never moved at all qualify. Skipped once a position has
been scaled, because banking part has already dealt with what this protects
against.

**Re-entry** takes a stopped-out setup again, up to `reentry_max` times. Six
of twelve stopped trades in the sample later reached the target they were
aiming at, by 3.7R to 25.7R - the level survived being crossed, which is what
a sweep looks like from the outside, and the stop settled only that *that
fill* was early.

What re-arms is the **signal**, not the intent. The payload goes back through
`on_signal` and therefore every gate, so a setup whose probability has decayed
or whose instrument has gone wide is refused exactly like a new one.
Resurrecting the intent would re-enter on reasoning the stop had already
contradicted.

It requires `pullback_fraction` to be above zero, and that guard is what makes
it safe rather than a way to lose twice quickly. At the moment a stop fills,
price is by definition at the worst point the trade has seen; re-entering at
market buys the extreme. With the pullback on, the re-armed signal parks and
waits for price to come back to the level - the entry the thesis wanted in the
first place. With it off, the rule declines to fire rather than firing badly.

Re-arms are queued and drained by the loop rather than entered from inside
`_settle`, which runs during reconciliation. Opening a position from inside
the walk over the position set is how that walk starts disagreeing with the
broker.

## The control that trades against the model

`inverse` takes the calls the model likes best and trades the opposite side.

It exists because the account has been going down, and two explanations fit
that equally well from outside: the direction is right and the execution gives
it back, or the direction is wrong and better execution loses money faster.
Everything built here has assumed the first. Nothing had tested the second.

The gates run **unchanged, on the side the call named**, so it selects the same
signals `level-scalp` selects; only the trade is flipped. That is what makes it
a comparison rather than a different strategy. Same entries, anchors, stop rule
and target.

If it loses roughly what the others lose, direction is not the problem and the
execution work is aimed correctly. If it wins, the direction model is worse
than nothing and the entries, stops and trails have been polishing a sign
error. It is not a prediction that the model is backwards - anti-correlation
strong enough to trade is rare and usually a measurement artefact - but a
control expected to lose is still worth running, because the alternative is
continuing to assume the answer.

The flip is a hook on the shared `consider`, not an override of it.
`fade-to-value` came to run none of the shared gates by overriding `consider`,
while reading from the configuration as though it ran all of them, and a test
asserts the gates still run before the side is flipped.

## The three direction gates, measured - and none of them survived

Measured on 2026-08-27 (`research/harness/gates.py`, written up in
[replay.md](../research/replay.md)). The question is not whether these numbers
mean something - they are model outputs and they do - but whether trades above
a floor do better than trades below it. A gate that does not separate is not
neutral: it costs every trade it refuses and returns nothing.

Mean R at a 0.5v stop, by decile, over the 4,378 resolutions carrying these
fields. **Base rate is shown turned to face the trade**, which is what the gate
compares - `base_up` for a buy, `1 - base_up` for a sell:

| decile | probability | base rate (facing) | edge |
| --- | ---: | ---: | ---: |
| 1 (lowest) | 0.978 | 0.900 | 1.024 |
| 2 | 0.934 | 0.995 | 0.888 |
| 4 | 0.987 | 0.986 | 0.944 |
| 6 | 0.942 | **0.879** | 0.945 |
| 8 | 1.003 | 1.002 | 1.038 |
| 10 (highest) | 0.913 | 1.009 | 0.901 |
| spread | 0.090 | 0.130 | 0.153 |

**None of the three separates outcomes, and all three are now off.**
Probability and edge both slope slightly the wrong way across spreads
indistinguishable from noise. Base rate has the largest spread of the three at
0.130 and it is **not monotonic**: deciles 2 to 4, which sit *below* an even
chance at 0.38 to 0.48, return about 0.99 - better than deciles 5 to 7 at 0.88
to 0.94. A floor anywhere in the middle removes good trades and keeps worse
ones. The old 0.51 floor sat exactly there.

### The correction that produced this, because it is the instructive part

The first version of this measurement bucketed **raw `base_rate_up`** and found
a top decile returning 1.130 - the standout cell in the table. On the strength
of it the floor was raised from 0.51 to 0.56.

It refused 99 signals out of 99. Nothing traded.

The raw value is not what the gate compares. A raw 0.60 is a strong buy *and a
weak sell*, so pooling both into one decile measures neither, and a threshold
read off that distribution has no defined meaning against a gate that
direction-adjusts. Turned to face the trade, the standout decile is not
standout: 1.009 against a 0.90-1.00 field.

This is the second time raw versus direction-adjusted `base_rate_up` has
produced a confident and backwards reading in this repository. The harness now
does the adjustment in `_facing` with the reason attached, and the join is a
real one rather than a restatement - the approach side is recorded, both sides
carry every outcome, and a touch approached from above that rejects is price
falling to a level and turning up, which is a buy.

**What replaces them is confirmation, not another direction gate.** The
momentum filter and its candlestick fallback ask about *timing* - has the level
finished being tested - which is a different question from whether the level is
any good, and is the one the record says was being got wrong.

**Watch what volume does.** With all three floors gone, trade count should rise
sharply. If it rises without the loss rate falling, the gates were removing
volume rather than losses, which is itself the answer.

## The probability floor is per direction - kept, and now inert

*The floor below is switched off by the measurement above. The reasoning is
kept because the bug it fixed is real and will recur the moment an absolute
floor is reintroduced.*



One absolute number produced a one-sided book: 21 sells to 4 buys, from signals
that were offered 48% up and 52% down. The model is not biased about what it
says - it is **more confident when it says down**, median 0.880 against 0.824 -
so a single floor at 0.75 passed 96% of sells and 80% of buys. The gate made
the skew, not the market.

`floors.py` sits at the same *percentile* of each direction's own distribution
instead. It can only ever raise the bar above the absolute floor, and it cannot
see outcomes - what it tracks is the distribution of what the model says, never
what happened next, because a floor that tightens after a loss was measured
losing to having no floor at all.

The matched-constant version - two fixed numbers, one per direction - is beside
it in `floors.by_direction` and is what this repository's evidence generally
favours. See [replay.md](../research/replay.md) for why a quantile is
defensible in this one case and was not in the others.

## What the gates are actually for

Three numbers describe a call and they do different jobs. Measured over the
first nineteen closed live trades - a small sample, and one coherent story
across three cuts rather than three findings:

| gate | job | what the trades said |
| --- | --- | --- |
| `min_edge` | **floor** | inert above the step; ranking by it puts the losers on top |
| `min_probability` | selection | winners 0.838, losers 0.816; sorting by it puts winners on top |
| `min_base_rate` | selection | below 0.55: eight trades, one winner, -6.74R |

`edge = probability - base_rate`, so wanting a high conditional **and** a high
baseline means wanting their difference to be small. A large edge is by
construction a large departure from a weak baseline, which is the worse trade -
and is exactly what ranking by edge selects.

That takes nothing away from [edge.md](edge.md), which measured edge as a
floor: below about 0.10 the mean realised push is zero, located twice over
10,483 calls. The floor stays and is still the only thing keeping coin flips
out. What is new is that above it, edge does not rank - which edge.md itself
allowed for, saying the accuracy either side of the step "is not a number to
quote".

**The base rate is read in the direction claimed.** `base_rate_up` is always
the *up* rate, so a sell has to flip it. Comparing it raw across a set that was
fifteen sells and four buys described the direction mix rather than the levels
and produced a reading exactly backwards from the truth. There is a test for
the flip because the mistake is silent.

**Adaptive thresholds were tested and lost.** Walk-forward, raising the bar
after a loss and lowering it after a win came out *worse than no floor at all*
- it tightens after the market punishes you and loosens after it rewards you,
which is backwards unless outcomes are serially correlated. Third time this
repository has measured a dynamic rule losing to a constant.

## A shut market will still take an order

A closed instrument does not stop quoting - it keeps its last quote, frozen,
and the broker will still accept an order against it. What it will not do is
let the position back out. A us30 position could not be closed for twenty
minutes through the index's daily break; the error was a bare 400 with no
retcode, and what actually identified the cause was the quote not having moved
in thirty minutes, bid, ask and timestamp identical to half an hour earlier.

`spec.tradable` is no help here. It reports whether an instrument is *enabled*,
not whether it is *trading*, and it said `True` throughout that break.

So the same staleness test that decides whether a close should be deferred now
also decides whether a position may be opened at all: a market silent for
`stale_quote_after` refuses on gate `shut`. A market we cannot get out of is
not one to get into.

**Which clock, though.** The first version of this gate read `_quoted_at`,
which is fed from the quotes bus - a consensus of other venues. That is the
wrong clock, and it was wrong within the hour: a `buy 1.2 Wall Street 30`
was refused by the broker with `400 Order failed: Market closed` while the
consensus feed looked perfectly live, because OANDA and the rest carry on
quoting an index our broker has closed.

Only the broker's own tick time answers the question actually being asked,
which is whether *this* broker will let a position out. Measured across the
bridge on a Friday evening, ours and theirs are the same epoch and the two
states separate cleanly:

| symbol | last tick | |
| --- | --- | --- |
| BTCUSD | -2s | 24/7, trading |
| Australia 200 | 696s | shut |
| Japan 225 | 696s | shut |
| EURUSD | 997s | shut |
| Wall Street 30 | 1597s | shut - the refused order |
| US Tech 100 | 1596s | shut |

Checked against the order that actually failed: Wall Street 30's last tick was
20:44:58 and the order went at 20:52:07, so the market had been silent **429
seconds** against a 300-second threshold. The gate would have refused it.

`_shut_for` is that one definition, read by the entry gate and the close
deferral alike. It prefers the tick in hand, falls back to a cached broker
tick, and falls back again to the consensus feed for a bridge that reports no
tick time.

**The close path has to ask.** The cached clock is only trusted while the
observation behind it is fresh, and nothing on the close path was refreshing
it - so the shut test fell back to the consensus feed and `#5759753523` retried
its close every minute for eight hours of a shut US Tech 100, logging a warning
each time. A position past its hold now quotes its own symbol before the
deferral is judged. Only positions already at their limit pay for the call.

**An adopted position needs its symbol, not its feed.** A position adopted
after a restart is given `feed = position.symbol.lower()` - `"us tech 100"`,
which is not a feed key, so both lookups miss and a shut market reads as
trading. That is why `#5759753523` went on attempting a close even once the
clock was being refreshed. A caller holding the position knows its symbol
outright, and the close path passes it.

**And the broker's own words settle it.** Every clock here is an inference
about the broker's state; `400 Order failed: Market closed` is the broker
stating it, and it cannot be wrong. A close refused with that message is
logged as a shut market rather than a fault. It is matched as a string because
the bridge sends no retcode - the same reason the original us30 diagnosis had
to go by the quote not moving.

**The cached clock needs its own freshness check.** A tick time goes on ageing
whether or not we are still asking, so an instrument we simply stopped quoting
would drift into looking shut. If the observation itself is older than
`stale_quote_after` the broker's clock is not used at all. Neither missing
evidence nor our own silence is evidence of a closed market - the same reason
a feed that has never quoted is not called shut.

**A weekend is this failure with a longer clock.** The hold defers a close
while the market is shut, but `max_hold_multiple` caps that deferral at four
times the hold - so a position carried into a Friday close goes out at whatever
is offered when the cap expires, not on Monday. Refusing the *entry* is the
half of the problem that can be solved cheaply.

A feed that has never quoted is *not* treated as shut, deliberately: silence at
start-up is not evidence of a closed market, and refusing everything until the
first quote would be a worse failure than the one this prevents.

## A market about to shut

The other half, and the one that costs money. `shut` catches a market that has
already closed. A market about to close takes the order happily and then will
not give the position back: opened at 20:52 on a Friday, it cannot be closed
until Sunday night, and `max_hold_multiple` does not save it because the shut
branch of the deferral has no cap.

**The broker does not publish its hours.** MT5 keeps them behind
`symbol_info_session_quote` and the bridge has no route for it - forty-seven
routes, none for sessions. `symbol_info` *does* carry `session_open` and
`session_close`, which look like the answer and are not: they are the session's
open and close **prices**. Wall Street 30 reports `session_close: 53556.35`.

So they are learned from where bars exist, which is the same evidence by a
different road and needs nothing from the bridge. Fifteen-minute bars over
about three weeks give a schedule that matches what each instrument visibly
does:

| instrument | Mon-Thu | Friday | weekend |
| --- | --- | --- | --- |
| Wall Street 30 | 00:00-21:00, 22:00-24:00 | to 20:45 | Sun from 22:00 |
| Australia 200 | 00:00-21:00, 22:00-24:00 | to 21:00 | Sun from 22:00 |
| EURUSD | continuous | to 21:00 | Sun from 21:00 |
| BTCUSD | continuous | continuous | continuous |

The 21:00-22:00 gap is the daily break a us30 position could not be closed
through. Friday's 20:45 is seven minutes before the order the broker refused.
Both were diagnosed from tick times first and appear here independently, which
is the only reason to trust either.

**Times are UTC.** The bars arrive as ISO strings in broker server time, which
is UTC on this account: Wall Street 30's last Friday bar opens 20:45 and its
last tick was 20:44:58 UTC. Worth stating, because a silent offset would put
every session hours out and nothing would look wrong.

**The gate is per trade, not per clock.** `session_margin` refuses a trade
whose *own hold* does not fit before the close. Twenty minutes out, a
two-minute scalp is fine and a thirty-minute swing is not, and a blanket "no
trading after 20:30" would refuse both. The hold is the thing that has to fit,
so the hold is what it is measured against.

**A minute is trading if it traded in any observed week** - the union, not the
intersection. A holiday, an outage or a week not fetched would otherwise carve
false closures into the schedule, and each one would refuse a trade that should
have been allowed. The union errs towards allowing: Friday reads 21:00 rather
than 20:45 for an instrument that has done both. This is a filter for the
large, regular closures it can see clearly, not a calendar, and `shut` remains
the backstop for what it misses.

**Learning costs 0.72s per instrument**, which is 24 seconds of start-up across
thirty-three - time spent not trading, with the gate unarmed. Six concurrent
fetches bring it under five seconds without asking the bridge to serve
thirty-three at once. An instrument whose bars cannot be read has no session
opinion and the gate stands aside for it, as it does for the ones that never
close.

## When the whole market goes wide

`structures` already scores spread per venue and publishes an anomaly whenever
one is out of line with the group. `trading` was not listening: `observe_signal`
handled `drift` and ignored everything else, so a detector that already existed
had no effect on a single decision.

It is wired in now, with one condition that decides whether the idea works at
all. **Those anomalies fire continuously, and they are supposed to** - one venue
quoting badly is exactly what the detector is for - so standing aside on each
would stop trading altogether. What is worth acting on is several venues
widening *at the same moment*: that is not one venue misbehaving, it is the
instrument thinning out everywhere, and there is no good fill to be had from
anyone.

So the gate needs `wide_venues` distinct venues flagged inside `wide_pause`,
and the same venue reporting five times counts once. The pause is much shorter
than `drift_pause` - a widening passes, a regime change does not.

This is the case `dislocation` cannot cover, and the two are complements rather
than duplicates: `dislocation` judges **our broker against the group**, which
needs a healthy group to judge against. This one fires precisely when the group
itself is the problem.

## Spread, when there is nothing to compare it against

Two gates already judge spread and both are right. `Context.dislocation`
compares ours against the **peer group's spread at that instant**, which is the
best available test - if six venues have all widened, ours widening with them
is the market and not the broker. `Guard.allows` compares it against the
**trade's own reward**, which is the economic question: a cost that eats the
target refuses the trade whatever the reason for it.

Between them the ordinary case is covered, including the one a time-of-day
model is usually reached for. When spread widens at rollover, `spread / reward`
rises and the trade is refused already. A per-hour gate layered on top of that
would refuse trades that are economically fine.

**The gap is the fail-open.** The peer test needs `MIN_VENUES` fresh quotes and
returns "" without them - no spread check of any kind. That is not a rare path.
It is thin hours, rollover, holidays, and any instrument carried by fewer
venues than the majors, which is exactly the set of moments a broker's spread
is worst.

So `spreads.py` supplies a reference from the instrument's own history at that
hour, and only on that path. It cannot overrule the peer test, only stand in
when there is none, and on that path the current behaviour is to allow
everything - so its only possible effect is to refuse a trade that would
otherwise have been taken on an unexamined spread.

**Why this is not the rolling quantile that was already refuted.**
[edge.md](edge.md) measured a rolling quantile against a matched constant and
the constant won by four to ten points, four times out of four. The reasoning
is what carries over: `edge` was *already scale-free*, so normalising it per
cell destroyed a comparability it already had. A broker's spread in bps is not
in that position - no constant could mean the same thing on gold at rollover
and on EURUSD at the London open - and on this path there is no reference of
any kind to destroy.

It is also not a quantile. Quantiles need a stored distribution and a warm-up
long enough to fill it, and edge.md's second finding was that 9 of 24 cells
never reached the 50 observations the rolling rule needed. This keeps a decayed
mean and a count, shrinks the hour toward the instrument's own pooled spread,
and reports `0.0` rather than `1.0` when it has too little to speak - so an
unmeasured instrument can never be mistaken for a normal one.

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
signals - it needs `structures` publishing to the same bus, which on one
machine means `till-infinity run` and across several means Redis. It says so at
start-up rather than sitting silent.

## Scoring it

```bash
uv run till-infinity trading report              # paper by default
uv run till-infinity trading report --mode live
uv run till-infinity trading report --strategy approach-scalp
```

Every trade writes a `decision` with the numbers it was sized from and an
`outcome` pointing back at it. Pairing them is the whole evaluation, and three
things about how it reports are deliberate:

**R, not money.** A win of 40 on a trade risking 20 and a win of 40 on one
risking 200 are not the same result, and averaging currency hides it. R is
profit over the risk the trade was sized for - the only unit in which trades of
different sizes compare.

**The count, always, beside the number.** Under thirty closed trades the rates
print as dashes and the report says so in full. A 70% win rate over ten trades
is a coin that came up heads seven times, and this project's own history is
mostly of numbers that looked principled while describing a distribution nobody
had measured.

**Paper and live are not averaged.** Simulated fills and real ones describe
different things, so `--mode` defaults to paper and `both` has to be asked for.

**An idle trader says which kind of idle it is.** Every few minutes it logs
what it has taken and what it passed over, per strategy and gate - or, if it
has seen nothing at all, what it is watching for. handoff.md names this as a
class of bug: correct silence and broken silence are indistinguishable, and
this module produced a day of the second kind while looking like the first.

Declines are tallied per gate too. A gate that never fires is doing nothing and
one that fires constantly is mis-set; neither is visible without the tally,
which is why every `Refusal` carries a machine-readable gate name.

## The level's own record, now published

`structures` computes a level's hold rate on the side price is arriving from
and, until recently, published it nowhere. [strength.md](strength.md) measures
it as the strongest thing a level knows - 59.4% to 92.2% across four buckets
with an **AUC of 0.648**, and the only signal in that study that got *stronger*
when the volatility denominator bug was fixed, against `Level.strength`'s 0.548
for a composite that does not contain it.

Level signals now carry `record_hold` and `record_n`. Unshrunk, with the count
beside it, because a rate with two decisive interactions behind it and one with
ninety are not the same number and must not arrive looking like it - and
because the pooled rate to shrink toward is instrument- and epoch-specific, so
the choice belongs to the consumer.

Nothing gates on it yet. It is published so that something can, and so the
journal starts recording it against outcomes from today rather than from
whenever a strategy is written.

## What this does not claim

No strategy here has been evaluated against its own outcomes. The signal they
all read is measured; the rules for acting on it are not, and the journal is
being collected so that they can be. Until that evaluation runs - the same
progressive-validation discipline `facto.py` uses, against the same baselines -
this is a way of acting on the level model consistently and recording what
happened, which is a different and smaller claim than an edge.
