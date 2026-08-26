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

Eight. Seven are arithmetic over the measured signal and claim no edge of
their own; the eighth is a panel of agents that reasons its own way to an
answer. Every one reads the same
measured `LEVEL` signal `structures` publishes; they differ in which calls they
act on and where they put the stop and target. Adding a strategy is a claim
that a *subset* of those calls behaves differently - which the journal can
settle - not a new indicator.

```bash
uv run till-infinity trading strategies
TRADING_STRATEGIES=sweep-aware,fade-to-value,approach-scalp,level-scalp
```

| strategy | takes | stop | target |
|---|---|---|---|
| `level-scalp` | every actionable call | beyond the level | the expected push |
| `confluence-scalp` | only calls another timeframe agrees on | 1.5× wider | the expected push |
| `momentum-scalp` | only calls agreeing with three speeds of recent edge | beyond the level | the expected push |
| `approach-scalp` | a call confirming direction toward another level | beyond the level | the next level, short of it |
| `swing-level` | a 4h/1d/1w level, triggered as low as 15m | beyond the level, 1.5x | the expected push |
| `sweep-aware` | the plain call, unless the stop is in front of liquidity | beyond the zone | the expected push |
| `fade-to-value` | the distance from spot to the best-evidenced level | beyond the triggering level | short of fair value |
| `council` | whatever four agents agree on, or nothing | as the panel proposes, clamped | as the panel proposes, clamped |

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
