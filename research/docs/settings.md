# Settings

Why each number is the number it is.

Moved out of `trading/config.py` on 2026-09-19, which had grown to 1,140
lines of comment against 581 of code - two thirds prose, in the file a
reader opens to find out what a setting *is*. Nothing here is new and
nothing was discarded: each section is the block that stood above the
field it names, and the field keeps its opening paragraph.

Four blocks were **left in the code deliberately**. In each the source
declares a second, undocumented field immediately after the documented
one - `parked_stop_vol` after `max_break_risk`, `min_hold` after
`max_hold_position`, `pullback_min_gain` after `pullback_max_vol`,
`notify_fills` after `notify` - so which field the prose describes is
genuinely ambiguous, and at least one of them (the 79-line block above
`max_break_risk`, which describes a parked entry's stop) appears to sit
above the wrong field already. Moving those would have carried the
mistake into a document that looks authoritative.

## `strategies`

Strategies to run, by registered name. Several may run together; the
per-instrument position limit is what stops two of them doubling a
position rather than any coordination between them.
The two the desk actually runs. `cycle-scalp` is the unified scalp
thesis - 4h bias, 1h structure, fast pullback entry - and `cycle-turn`
is the slower reversion trade that the 4h cycle has to agree with, on a
feed whose 4h record earns a say.

**This is a priority list, and `cycle-turn` is first on purpose.** The
two now overlap on every timeframe from 1m to 15m, and where they
overlap they want opposite things - one a continuation of the cycle,
one a turn against it. The first taker wins, so the order is the
decision about which reading of a shared call the desk acts on, and the
turn is both the rarer and the better-gated of the two: it needs an
agreeing 4h cycle, a second anchor, and 200 scored 4h calls beating 52%
on that feed, where the scalp needs none of those. Listed second it
would see only what the scalp had already declined.

The journal tells their trades apart by magic, which is why every
strategy needs a slot in `MAGIC_ORDER`.

## `intervals`

Timeframes the service will *accept*. Every one a level forms on, by
default - the restriction belongs to the strategy, not to the module.

This started as `1m,5m` on the false grounds that "structures only
builds levels on those two"; `structures.config.INTERVALS` is the
anomaly detector's fast-data set, while levels form on all of
`confluence.TIMEFRAMES`. Six of eight were discarded in silence, and the
first live call to arrive was a 3m EURUSD one that the trader ignored
while the same call was delivered to Telegram.

Narrowing this narrows every strategy at once, which is a blunt
instrument and rarely what is wanted. A strategy that only makes sense
on fast data says so itself, in `Strategy.timeframes`, and the effective
set is the intersection - so this can restrict a strategy but never
widen one past what it claims to handle.

## `min_reward_to_risk`

Minimum reward-to-risk from the *quoted* entry, spread included.

**Off by default, because it was measured and it loses.** Re-verified on
2026-08-27 over 47,676 production touches joined to the signals that
produced them: 0.908R ungated against 0.868R at the 1.2 that used to be
the default, monotonically worse as the floor rises. It refused 40,421
calls of 47,676 to give back 0.047R.

119 closed trades say the same thing from the other end: a 0.8 floor
keeps 78 trades worth -737 and refuses 41 worth +667. The trades with a
near target are the ones that reach it - hit rate falls from 35.7% to
zero as the ratio rises, while the stop rate climbs from 10.7% to 48.5%.
See `research/geometry.md`.

The reasoning for a floor is sound and the measurement disagrees with
it, twice, on two independent samples. A default of 1.2 meant every
fresh deployment applied a gate this repository had already refuted, and
had to know to turn it off.

## `max_spread_risk_fraction`

And the same question against the **risk**, which is the denominator the
damage was measured in.

The gate above scales the permitted spread with the *target*, so a
distant target buys the right to pay more - and a spread that is half the
stop distance is half the stop distance regardless of where the target
is. Measured over 397 closes in `research/winning.md`:

    passes the gate, cheap against risk      292   -0.065R  17% stopped
    passes the gate, EXPENSIVE against risk   49   -0.471R  53% stopped

**49 trades passed the live gate while sitting in the damaging group, for
-502.70.** This is the only finding in that study with a pre-registered
hypothesis - `exiting.md` named the quantity first - a within-feed null
at p<0.001, and 9 of 9 strata agreeing. Every entry *feature* tested
against the same 300-permutation control failed to clear it.

0.16 rather than a rounder number because the discovery half's p80 was
0.2026 and this sits inside it. It refuses about 12% of what reaches it,
and far less than that lately: the expensive population fell from 79% of
closes in late August to 5% of the last seven days, so this is mostly a
guard against the condition returning rather than a fix for today.

## `min_base_rate`

How often the level must hold in the claimed direction, unconditionally.

Separate from `min_probability`, which is the *conditional* - what the
model thinks about this touch. This is the baseline it is measured
against, and the two are not the same question: a level that holds 45%
of the time and is claimed at 80% is a bigger departure than one that
holds 65% and is claimed at 85%, and the first is the worse trade.

Zero disables. Measured over the first nineteen closed trades: the eight
with a directional base under 0.55 produced one winner and -6.74R.

## `probability_percentile`

Where to sit in each direction's *own* distribution of claimed
probability, in [0, 1]. Zero uses `min_probability` alone.

One absolute number produced a one-sided book: over 7,498 calls the two
directions are offered almost evenly - 48% up, 52% down - but down
arrives more confident, median 0.880 against 0.824, so a single floor at
0.75 passed 96% of sells and 80% of buys and the book came out 21 sells
to 4 buys with no rule saying it should.

Off by default, and the reason is worth stating: this repository has
measured dynamic thresholds losing to matched constants three times. The
fixed-pair version is in `floors.by_direction` and is what the evidence
favours; this exists for when the distributions drift far enough that a
fixed pair stops meaning what it meant.

## `parallel`

Let **every** strategy that wants a signal take it, rather than the
first one in the running order.

This multiplies exposure on purpose. Seventeen strategies wanting one
signal is seventeen positions on one idea, and the per-instrument limit
exists to refuse exactly that - so `risk.allows` is re-asked with the
book as it stands after each fill, not as it stood before the first.
The cap is what makes this bounded rather than unbounded, and it is the
reason this is a switch rather than the default.

Agreement sizing is skipped when it is on. Rebuilding a trade from what
several strategies collectively asked for, and *also* letting each of
them take their own, counts the same agreement twice.

## `consensus_min`

How many strategies must want the same side before the trade is rebuilt
from what they collectively asked for. Zero or one disables it.

Agreement does **not** size the trade up. Two strategies on one signal
is one idea found twice, so betting more on it doubles a position on a
single thesis. What agreement buys instead is a better-built trade: the
furthest stop any of them wanted, because being stopped before the move
arrived is the failure measured most this session, and the nearest
target, because unreached targets are what a wide stop costs. Money at
risk is unchanged - a wider stop is re-sized into fewer lots.

## `thesis_stop_vol`

Where `thesis-only` puts its stop, in volatility units.

Far enough that it is a circuit breaker rather than a trade decision.
Over 49,338 resolutions the 90th percentile of excursion past a level is
3.68v on 1m, so 4 sits just beyond the range where a stop decides
anything while still firing before a loss becomes interesting.

**Bounded by the account, not only by the argument.** At 8v the minimum
lot risks more than the risk budget allows on a ten-thousand-unit
account - the refusal reads "25.00 does not cover the minimum 0.01 lot,
which risks 35.70" - so the experiment would simply not have traded. A
wider stop is available on a larger account and is the honest place to
run the full version.

The trade is correspondingly small either way: the same money at risk
spread over a stop four times wider buys a quarter of the lots, which is
the price of giving a trade room.

## `min_edge`

The floor on |edge|, and it has to sit **above** `reactions.MIN_EDGE`
or it is configuration that can never fire - every signal reaching the
bus has already cleared that gate. The first version of this module set
it to 0.08, which is below the 0.10 upstream and therefore did nothing.

0.15 rather than 0.10 because [edge.md](../../docs/edge.md) puts the
step at 0.0968 over ten deciles of 10,483 calls and finds direction
keeps improving above it - its 0.20+ band calls 74.2% and 91.4% correct
across the two halves against 63.3% and 88.0% at 0.11-0.14. Alerting on
a call and staking money on it can reasonably want different margins
over the same step, and this is the margin.

What it is *not* is a rolling quantile of recent edges. That was
measured and lost; see `speeds` for the record.

## `max_hold`

Seconds a scalp may stay open before it is closed regardless. A scalp
that has been open an hour has become a swing trade nobody planned.
A strategy may ask for longer - see `Strategy.hold_seconds` - because
this default is a property of the trade being taken, not of the module.
The longest a **scalp** may be held, in seconds.

Named `max_hold` still, because it is what the environment already sets
and what every scalp has always been capped by. What it never was is a
global ceiling: `hold_for` reads it only when a strategy names no hold
of its own, so a swing's four to six hours was governed by nothing at
all - a hardcoded `ClassVar` with no setting behind it. `max_hold_swing`
is the other half, and both are now real ceilings rather than defaults.

## `max_hold_swing`

The longest a **swing** may be held, in seconds. Six hours.

The value the swing strategies already declare, made settable rather
than raised: measured on 1,394 setups, extending the higher timeframes
from four-to-six hours out to 48-72 changes **four** of them. The median
traversal from one origin to the other takes 101 seconds, so a trade
that is going to work does it in minutes and one that has not in six
hours has already hit its stop.

What extending would cost is not nothing: overnight financing on every
night held, weekend gap exposure on any instrument that closes, and the
session gate refusing to *open* a trade whose hold does not fit before
its market shuts - which on a 48-hour hold is most of the FX and index
book. See research/barriers.md.

## `crowding_share`

How much of its size a position keeps for each open position sharing a
currency leg the same way round. Zero is off, 0.5 halves the second on a
leg and quarters the third.

`exposure.py` already **caps** a leg - it refuses the fourth dollar
trade. This **sizes** for it, which is a different thing: capping stops
the book growing past a limit and sizing stops it arriving there at full
weight. Long EURUSD, GBPUSD and AUDUSD is one dollar trade in three
tickets, and they will be right together and wrong together.

Geometric, because the risk of a shared leg compounds. A hedge is not
penalised: the sign has to match for a leg to count as crowded.

## `regime_band`

The net edge, in volatility units, that earns full size. Zero is off.

research/paying.md measures this per instrument - accuracy times
expected push, less the cost to cross - and the spread is wide: gold at
+0.919v against usdcnh at -4.663v, which currently carry the same risk
fraction. Linear in the edge and capped, which is the conservative end
of the Kelly family: full Kelly on an edge estimated from fifty touches
is a way to be wiped out by an estimation error rather than by a market.
How far `forecast_ratio` may drift from one, in log space, before size
starts falling. Zero is off.

`forecast_ratio` is the **expected change** of the volatility scale -
next bar over last - and not the regime level. The regime level is
`vol_stretch`, it is published on the same call, and it is flat to
within 1.2 points across its quintiles. Do not substitute one for the
other; they correlate at +0.033.

Levels hold 86.4% of the time with the ratio between 1.0 and 1.21, and
about 81.3% at either extreme - measured over 32,362 touches on 14 days,
an inverted U rather than a slope. `scaling.by_regime` is the multiplier;
this is how wide the band of full size is. 0.35 is roughly "the next bar
within three-quarters to one and a half times the size of the last".

**Off until this is joined to money.** The 14-day read holds the shape
the 7-day read found and narrows the tails, so it is less likely to be a
period effect than it was - but held rate is still not profit, and
`research/reachable.md` is the standing reminder that a level holding and
a trade paying are different events. See `research/clustering.md`.

## `stop_overshoot`

What a stop actually costs on an instrument, in R, as `feed=multiple`
pairs. Anything unlisted is 1.0 and unscaled.

A stop placed at 1R should cost 1R. Measured over the whole journal on
2026-09-02, every instrument delivers that - a -1.04R median and -1.09R
worst across ten stops - except Boom 500 Index, which came back at a
-1.25R median, a -1.79R worst, and 60% of its stops past 1.1R. Deriv's
Boom indices move in discrete jumps by construction, and a stop can be
leapfrogged rather than filled.

This is the only sizing input that is about **execution** rather than
about the signal. The others read the market or the book; this reads the
gap between the price this system chose and the price the broker got.

**Revised 2026-09-11: the spike side of Boom and Crash defaults on.**
A replay over 84,701 ticks puts the realised loss on a stop that can only
be gapped over at, for `boom_500` short:

| stop width (spreads) | realised loss | factor |
| --- | --- | --- |
| 5 | -14.96R | 15.0 |
| 10 | -7.81R | 7.8 |
| 25 | -3.44R | 3.4 |
| 50 | -2.02R | 2.0 |

and 93-98% of stopped trades slipping past half an R. That is the shape
that ends an account rather than the shape that costs it a quarter, and
an empty default is the claim that no instrument overshoots - which this
measurement contradicts. `by_slippage` never enlarges, so a default here
can only reduce size; it cannot do harm by being present.

**2.0 is the floor of that table, not the right number.** The multiple
depends on the stop width in use and the table is monotone in it, so 2.0
is the one value that is never an over-correction at any width measured
and is 7.5x too small at five spreads. A deployment that actually trades
these should set `TRADING_STOP_OVERSHOOT` from the row matching its own
stop width - `research/generators.md` gives the rate to compute any row.
Encoding the sizing rule properly means reading the stop distance at size
time rather than a static table, which `overshoot_for` cannot do.

Keyed by side because the two sides are not the same trade: Boom drifts
down and spikes up, so a **sell** has the gapped stop; Crash is the
mirror, so a **buy** does. The grind side measured +0.02R and is left
unscaled.

Held as pairs rather than a dict because `Settings` is slotted and
frozen in spirit - a mapping default is a mutable shared between every
instance that ever forgets to pass one.

## `hold_extends_at`

R in front at which the hold stops applying. Zero keeps the old rule:
the clock closes everything, whatever it is doing.

The hold exists to release capital from a thesis that is not playing
out. It was closing trades that were, which is a different thing: a
position a point in front at the thirty minute mark is closed at market
and the rest of the move happens without us. Observed on gold - out at
4623 on a fall that carried to 4592.

A trade allowed to outlive its hold is **first moved to break even**, so
the extension cannot turn a winner into a loser. That is what makes this
safe to run without the trailing rules in `manage.py` being on.

## `max_chase_vol`

How far past the level a fill may land before the trade is refused.

Entry is a market order, so it lands wherever price is when the call
arrives, and nothing looked at that. The call was measured *at* the
level and the push it predicts is measured from there, so a fill well
past it has already spent part of the move - and the stop, anchored to
the level, ends up sitting close underneath the fill. Both halves of
"stopped out before the move came" meet here.

Only counted when the fill is past the level in the trade's own
direction. Arriving before it is the setup behaving as described.
Zero disables.

## `pullback_fraction`

How far toward the stop's price the entry is moved, as a fraction.

Zero enters at market, which is what every order here has always done.
One waits for the price the stop was going to defend - the far edge of
the level's sweep zone - which is the best fill the setup can offer and
the one it offers least often. A half meets it in the middle.

The trade that gets stopped out today is the one that gets *filled*
tomorrow, and the reward-to-risk improves because the target does not
move with the entry. The cost is the setups that never come back, and it
is a real cost: a strategy that only fills on retracements is a
different strategy, not a cheaper version of this one.

## `stop_hold_scaling`

How much of the square-root-of-time scaling to apply to the stop floor.

`vol_bps` is the volatility of **one bar** of the entry interval, so a
stop at `min_stop_vol` units is sized for one bar - while the trade is
held for many. Volatility grows with the square root of time, which was
measured on our own instruments rather than assumed: observed growth
over sqrt(t) came to 1.04, 1.12 and 0.89 on gold at 5m, 15m and 60m, and
0.99 and 0.98 on the Dow. Thirty one-minute bars therefore carry about
5.5 units of wandering, against an expected push near 1.3.

1.0 applies the scaling in full, 0.0 restores the one-bar stop, and
values between are the honest position while `shadow_window` collects
the evidence: a wider stop cannot create edge - for a driftless walk it
buys win rate and pays for it in R - so what it fixes is paying spread
to be stopped by noise, not the direction being wrong.

Off by default, like every other rule here that changes what gets
traded. A wider stop cannot create edge - it buys win rate and pays for
it in R - so this is enabled to stop paying spread to be taken out by
noise, and `shadow_window` is what says whether that was the problem.

## `min_stop_vol`

The least a stop may sit from the level, in volatility units.

Fair value is a distribution and volatility is its width, so a stop
closer than one unit is *inside the estimate's own noise* and will be
taken by ordinary movement rather than by the thesis being wrong. The
README says exactly this about distance - one unit is noise, three is a
statement - and it applies to the stop before it applies to the entry.

Measured on the first two live trades, both gold, both sells: risk_vol
of 0.53 and 0.61 against volatility units of 0.99 and 1.72. The second
was stopped at 4626.09 on a 1.05-point stop and price then fell to 4615,
which is the direction being right and the stop being inside the noise.

`risk_vol` comes from the level model's own geometry and is frequently
under a unit on young levels, where the zone has no wicks recorded to
widen it either. Flooring here rather than there is deliberate: the model
is describing where the level is invalidated, and this is a statement
about what a *tradable* stop costs.

The size shrinks to keep the risk budget, and a trade that then cannot
make the minimum lot is refused - which is the correct outcome. A stop
inside the noise is not a cheaper trade, it is a worse one.

## `stop_slippage`

How much further than the placed stop a stopped trade actually costs,
as a fraction of the risk distance. Zero sizes as before.

**Measured, not assumed.** Across the stopped trades in the journal the
realised loss is 1.09R against the 1.00R they were sized for, and the
decomposition puts most of it on the way out: entry slippage averages
+0.025R, exit slippage +0.062R. A broker stop is a market order once
triggered, so it fills through the spread and any gap - that half is a
property of stops, not a defect to remove.

What *is* a defect is sizing against the stop we place rather than the
stop we get, which quietly breaches the risk budget on every loss. This
inflates the distance used for sizing so the money lost matches the
money budgeted.

It does not improve returns. Positions get about 8% smaller and losses
land where they were supposed to. The gain is that the risk limits mean
what they say.

## `unconfirmed_size`

How much of normal size a trade takes when momentum is not confirming
it. One is off - every trade takes full size regardless.

`max_against_vol` already refuses an entry while a run is still going
against it, and `require_turn_vol` asks for the turn after a pullback.
Both are yes-or-no. This is the middle: momentum neither running against
the trade nor yet confirming it is a weaker case than momentum turning
with it, and the honest response to a weaker case is a smaller trade
rather than no trade or a full one.

Applied where the trade is otherwise acceptable, so it can only ever
reduce exposure. There is no path here that sizes anything up.

**Unmeasured.** Recorded on every decision as `momentum_scaled` so it
can be scored later; nothing yet says a half-size trade on unconfirmed
momentum beats a full one, and the reasoning that it should is the same
kind of reasoning `reward_to_risk` was defended with for ten days.

## `stale_quote_after`

Seconds without a quote before a feed is treated as a shut market
rather than a refusing broker. Zero is off.

A us30 position could not be closed for twenty minutes through the
index's daily break. The bridge returned a bare 400 with no retcode;
what identified the cause was the quote not having moved in thirty
minutes. `spec.tradable` said True throughout - it reports whether an
instrument is enabled, not whether it is trading.

The two want opposite handling. A shut market means wait. A refused
order means something about that order is wrong and should be loud.

## `target_buffer_vol`

Pull the target this many volatility units short of where it was aimed.

A target sitting exactly on the price everyone else is watching is a
target that fills last. Price stalls *at* a level rather than through
it, so the last fraction of the move is the part most often not given -
and giving it up costs a known, small amount to avoid an unknown,
larger one.

`approach-scalp` has always done this, stopping a quarter unit short of
the level it aims at. This is the same idea for every other target.

Never past the entry: a buffer larger than the move itself would invert
the trade, and a target behind the fill is not a smaller target.

## `entry_pending`

Rest the entry this many volatility units better than the quote.

The trade is worth taking at the level; it is worth more a fraction
nearer it. This holds the order at that price instead of paying the
spread to cross now, and takes it when price comes.

**What a depth costs and buys**, over 72,452 resolved touches against a
median stop of 3.02v:

| depth | fills | risk left | R:R |
| --- | --- | --- | --- |
| 0.25v | 75.0% | 2.77v | 1.09x |
| 0.50v | 49.6% | 2.52v | 1.20x |
| 1.00v | 25.9% | 2.02v | 1.50x |
| 1.50v | 14.6% | 1.52v | 1.99x |
| 2.00v | 7.9% | 1.02v | 2.96x |

Halving the risk costs 85% of the setups. It buys more than the table
shows, because the target is measured from the **fill** while the stop
is anchored to the **level**: a deeper fill shrinks the risk and brings
the target nearer in absolute terms at the same time.

What is not measured is whether a trade filled on a deep wick still
works. The depth distribution says how often price gets there; nothing
here says what it does next, and buying a deeper fall is a different
trade from buying a shallow one.

**Whether the resting price is also left with the broker.**

`entry_edge_vol` alone is a poller's limit order: it watches quotes and
fires at market when price arrives. That misses the fills most worth
having, because a deep wick is brief by construction - at the 1.5v this
shipped on it was the 14.6% tail, and the realised rate was lower still
- and a wick that pierces and recovers between two reads is a fill that
never happened.

With this on, the price is *also* left with the broker as a limit order,
which fills on the terminal's own tick and never blinks. What the broker
cannot do is change its mind, so this system keeps watching and
withdraws the order the moment a gate turns - the market goes wide, the
session shuts, the window expires. Two halves: the broker has the
reflexes and this has the judgement, which is how a person would do it
with a platform in front of them.

Needs `entry_edge_vol` to have somewhere to rest.

## `entry_edge_vol`

Distinct from `pullback_fraction`, which waits for the **sweep edge** -
a retracement that measured 189 signals of 813 reaching the wait and
none of them parking, because by then the fill was already past it. This
rests at a measured depth instead of at a computed edge.

Held here and fired at market when price arrives, rather than sent as a
broker pending order. The bridge has `POST /orders/pending`, and using it
would mean the stop and target live on the terminal between placement
and fill, where nothing here can adjust them.

**Lowered from 1.5 to 0.5 in production on 2026-09-01, and the reason is
the first measurement of what parking actually does.** This shipped on a
predicted 14.6% fill rate taken from the depth distribution. Over the
whole journal 148 trades were taken, 13 of them (8.8%) after a parked
wait, against 496 signals refused because the feed was already parked -
roughly 38 refusals per fill, an upper bound since some would have died
on another gate anyway. The two that closed averaged -19.73 against
-5.31 for the 147 that went straight in, which at n=2 says nothing about
quality; the finding is about frequency.

A parked entry holds its whole feed through the `waiting` gate, so the
cost of a distance price rarely reaches is not a missed fill - it is
every other signal on that instrument, muted. 1.5v was a price the
market did not come back to often enough to be a strategy.

## `style`

Which kind of trading to run: `scalp`, `swing`, `both` or `none`.

A coarser switch than `TRADING_STRATEGIES`, and the two compose - this
filters whatever that list selected. `both` is the default and changes
nothing. `none` runs the service without taking trades, which is a
useful state: signals, estimates and the journal all keep working.

A strategy declares its own `style`. The names do not decide it -
`approach-scalp` and `fade-to-value` both hold forty-five minutes and
are classed as swings.

An unrecognised value runs everything rather than nothing. A typo here
should not silently stop trading, which is what a mis-set base-rate
floor did once already.

## `session_margin`

Refuse a trade whose hold does not fit before its market closes, plus
this much margin, in seconds.

**The other half of a shut market.** `stale_quote_after` catches one
that has already closed. This catches one about to: a position opened at
20:52 on a Friday cannot be closed until Sunday night, and the hold
clock keeps running while the market does not. Wall Street 30's last
Friday bar opens 20:45 and the order the broker refused went at 20:52.

Zero disables it. The gate also stands aside for any instrument whose
hours were not learned, and for those that never close.

## `max_push_vol`

The largest expected push a call may claim, in volatility units. Beyond
this the number is not a forecast, it is a fault.

**Found live.** A brent call arrived with `expected_push_vol` of
**10,229.7**. Measured over 54,547 resolutions the push distribution has
a median of 2.24v and a p99 of 9.55v, so this was four orders of
magnitude past anything the market does. Trading multiplied it into a
target of 3850.308 on an entry of 88.374 - 43 times the price of the
instrument - and the broker refused the order.

The refusal is what made it visible, and that is the uncomfortable part:
had the target been merely large rather than absurd, the order would
have been accepted and the trade would have run to its stop or its clock
with a target it could never reach. Nothing on this side checked.

Set well above p99 rather than close to it. The job is to catch a broken
number, not to second-guess a large one - a genuine 12v push is rare and
real, and refusing it would be this gate exceeding its remit.

## `hold_max_spread`

Defer the hold-clock close while the spread is this multiple of the
trade's own risk distance or wider. Zero closes on the clock regardless.

**Found live.** An aus200 position was quoted `bid 8998 / ask 9051` out
of ASX hours - a 53-point spread against a normal 1 to 2, and against
the trade's own 8.89-point risk. A long is marked at the bid, so it
showed -61 on a 19 budget while its true mid had not even reached the
stop. The hold clock was minutes from closing it at market and turning
that arithmetic into a realised loss.

`max_spread_fraction` already refuses to *enter* on a wide spread.
Nothing protected a position already open when liquidity went away,
which is the harder half - entry can always wait, an open position
cannot.

Measured against the trade's own risk rather than a baseline spread,
because that is self-calibrating: it asks whether crossing the spread
costs a meaningful share of what the trade was willing to lose, which is
the question that matters and needs no history to answer.

Bounded by `max_hold_multiple` like every other extension here, so a
permanently wide instrument cannot hold a position open forever.

## `max_against_vol`

Volatility units the move must have turned back **in the trade's
favour**, after a pullback, before the entry is taken. Zero is off.

How much accumulated momentum against a trade the book tolerates, in
volatility units of one bar. Zero is off; a strategy may state its own.

A property of the deployment rather than of whichever strategies
remembered to ask for it, which is what it was - `sweep-aware` and
`inverse` carried it and nothing else did, for no reason anyone had
written down. Stretched per strategy by `Strategy.horizon`, so 1.5 here
means a real run on a 3m chart and proportionally more on a 4h one.

## `require_turn_vol`

The stricter half of the momentum filter. `max_against_vol` refuses an
entry while a run is still going against it; this requires the turn to
have actually started. One removes the worst entries, the other insists
on the better ones.

**Only applied after a pullback, and that is not a detail.** Momentum at
a level is adverse by construction - price arriving at support is
falling, which is what arriving means - so requiring favourable momentum
on arrival would refuse every support buy this system exists to take.
After the pullback the same measurement means something else entirely:
that the fall has not finished. The pullback is what separates the two
readings, so the requirement rides on it.

## `require_candle`

Require a candlestick rejection at the level before entering. Off by
default.

The record this answers to: an `inverse` buy on gold took its stop at
4591 and then ran to its target at 4604, and it was not alone - 23 of
the first 32 trades were stopped, several of which later reached the
price they were aiming at. The direction was not the thing that was
wrong. The trade was entered because price was *near* a level, while
the level had not finished being tested.

A pattern is a claim about that: the auction reached a price, was
rejected, and closed away from it inside one bar. It is confirmation of
timing, and it costs the entries that never get confirmed - which is a
real cost, not a free filter, and is what running it as a setting rather
than a rewrite is meant to measure.

## `stops_level_margin`

Multiple of the broker's own `stops_level` a stop must clear.

The broker's minimum is not checked when the order is built, it is
checked against the price at the moment the order lands - so a stop that
satisfies it exactly at decision time is refused if the market moves a
point in between. This was 1.1 hard-coded, and a eurgbp buy was refused
with a stop of 0.00022 against a minimum of 0.00020: the margin was
doing its job and 10% of a 20-point floor is two points, which a quiet
cross covers between deciding and sending.

The cost of raising it is a wider stop, which for the same money at
risk buys a smaller position. That is the trade: a slightly smaller
trade against no trade at all.

## `stale_after`

Seconds after which a trade that has gone nowhere is closed flat. Zero
is off.

The median touch resolves in **eighteen seconds** and 84% inside five
minutes, so a position still sitting at its entry well past that is not
the event it was opened for. Holding it does not wait for the thesis; it
waits for noise to reach the stop, which is a losing trade arrived at
slowly. Closing flat costs the spread and keeps the rest.

**Loosened deliberately.** Measured over 119 closed trades this fired
six times for -5.01 at a 50% win rate - it was neither helping nor
hurting much - and it is a risk control from before the structures
models could say much about a level. The hold clock still ends every
trade, so this only governs the window between the two, and a trade that
has not moved yet is not the same as one that will not.

## `reentry_max`

How many times one stopped-out setup may be taken again. Zero is off.

Six of twelve stopped trades later reached the target they were aiming
at, by between 3.7R and 25.7R. That says the level survived being
crossed, which is what a sweep looks like from the outside, and that the
only thing the stop settled was that *this fill* was too early.

What re-arms is the **signal**, not the intent, parked at the level and
put back through every gate on arrival - so a setup that stopped being
worth taking is refused like any other. Bounded because a level that
keeps taking money is not a level worth arguing with.

## `approach_min_reach`

Least acceptable chance of covering the distance within the hold, from
the first-passage model in `structures.timing`.

**A floor against the absurd, not a forecast.** Diffusion is a null
model and markets depart from it - magnet.md measured exactly that - so
this is not the strategy's estimate of anything. It is here to refuse a
level that a driftless walk would rarely reach inside the hold, which is
the case where the target is simply too far away for the time allowed.

0.20 rather than something higher because of where the two gates meet.
On 5m with a 45-minute hold there are nine bars, and a 35% floor caps
the distance at about 3.5v - below `approach_max_vol`, which would make
that ceiling dead configuration that never fires. At 0.20 the reach gate
binds on the slower timeframes and the distance ceiling binds on the
faster ones, and both do something.

