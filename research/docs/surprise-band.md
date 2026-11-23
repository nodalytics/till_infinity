# The surprise threshold as a band, and why the edge should be at the low end

**Opened 2026-11-21**, on the operator's instruction: *"can the 3sigma be a
range instead of a fixed values, still part of our tests: 1.3 to 3.5 sigma
instead of 3sigma only, add documentation/journal so we can easily traceback
later and see."*

This page is the trail. **Nothing has been measured yet** - it records what was
changed, what the prior evidence says to expect, and what would settle it.

## What a surprise is

`statespace` keeps a running model of where price should be and reports how far
price actually is from it, **in units of its own forecast spread**. That number
is the surprise: a standardised one-step innovation. **3.0 means price arrived
three standard deviations from what the model expected.**

It carries no direction. `surprise.py`: *"it claims no edge of its own... what
it adds is a threshold on it and the geometry around the entry."* So the
threshold is the whole of the rule's contribution, which is why its shape is
worth this much attention.

## What was fixed before, and the asymmetry that made it a bug

The floor and the producer's emission threshold are two different numbers and
they have to agree:

| | |
| --- | --- |
| `proposing.TRIGGER` | what statespace **publishes** a proposal for |
| `SurpriseProfile.least_surprise` | what the rule **accepts** |

A rule floor **above** the producer's trigger throws away work already done.
That happened: at a floor of 3.5 against a trigger of 3.0, *"every proposal in
[3.0, 3.5) was emitted only to be refused here - a band of work done and thrown
away, and a refusal counter that reads as the market being quiet rather than as
two constants in different modules disagreeing."*

A rule floor **below** it is the mirror image and is the new hazard: the
producer publishes nothing underneath its own trigger, so a floor of 1.3 against
a trigger of 3.0 **buys no proposals at all** - it only makes the gate look
open. `_band` clamps to what is published and says so once.

**So the two move together.** Asking for 1.3 at the rule requires
`STATESPACE_TRIGGER=1.3` at the producer.

## Why 3.0 and not 5.0 - already on record

> 3.0 rather than 5.0 because `origin-returns-turn-at-z-one-three` measured
> returns turning at z 1.3 to 1.95 and non-returners reaching 2.2, so z 2.5
> already misses 85-89% of them. The 5-sigma figure came from a bar-level
> anomaly study, not from this service's standardised innovation, and the two
> are not the same scale.

## Why a ceiling, which is the unintuitive half

The same measurement that argues the floor down argues for a ceiling:

| | |
| --- | --- |
| returns turn at | **z 1.3 to 1.95** |
| non-returners reach | **z 2.2** |
| z 2.5 misses | **85-89% of returns** |

Read plainly: **a larger surprise is *less* likely to come back.** If this rule
is a reversion rule, its edge lives at the **low** end of the band and the big
readings are the ones that keep going. A floor of 3.0 therefore sits above
almost every return the earlier study could see, and the current setting may be
selecting against the effect it is trying to trade.

That is a hypothesis with prior support, not a result. It also has an obvious
competing explanation: the low end is where cost bites hardest, because cost in
R is `spread / stop distance` and a quiet bar has a smaller stop.

## What changed in the code

Both ends configurable, **defaults unchanged**, so merging moves nothing:

| setting | default | what it does |
| --- | --- | --- |
| `STATESPACE_TRIGGER` | 3.0 | what statespace publishes a proposal for |
| `TRADING_SURPRISE_MIN` | 3.0 | the rule's floor, clamped up to what is published |
| `TRADING_SURPRISE_MAX` | infinite | the rule's ceiling - new |

A reading above the ceiling is refused under its **own** gate name,
`too-surprising`, rather than pooled with `surprise`. One says the market was
too quiet to pay for a round trip and the other says the move was too large to
be the reversion this rule trades, and pooling them would make the tally
unreadable at exactly the moment a band is being swept.

An inverted or empty band falls back to the defaults with a warning rather than
silently trading nothing, because *"a desk that refuses everything and a desk
with no setups write the same report line"* -
`venue-faults-hide-below-the-strategy`.

## The cost of the lower floor, measured

**Measured 2026-11-21**, after this page first estimated it. The estimate was
"roughly a fifth of bars, so something like a sixteen-fold increase", which was
a Gaussian guess about a quantity whose whole point is that it is not Gaussian.
`research/ideas/surprise_threshold_sweep.py` ran the production fold over the
same feeds and noise as the admission measurement:

| threshold | share of bars | multiple on today's flow |
| --- | --- | --- |
| **1.3** | **29% to 31%** | **21x to 27x** |
| 1.95 | 8.9% to 9.6% | ~8x |
| 2.2 | 5.2% to 5.8% | ~5x |
| 2.5 | 2.9% to 3.5% | ~2.6x |
| 3.0 *(today)* | 1.08% to 1.55% | 1x |
| 3.5 | 0.47% to 0.69% | 0.4x |

So the floor is the expensive decision and it is **worse than the estimate**:
**21x to 27x**, not 16x, and 29% of bars rather than a fifth. On the volatility
indices, whose tails are thinner, the same move is **38x to 41x**.

**Two things follow that the estimate hid.**

First, **the ceiling at 3.5 is very nearly a no-op.** The share landing inside
[1.3, 3.5] is 28.1% to 29.6% against a 1.3 rate of 28.8% to 30.2%: the ceiling
removes about **2% of what the floor admits**. A band of [1.3, 3.5] is
therefore a floor change wearing a band's clothes. If the ceiling is meant to
do work - and `origin-returns-turn-at-z-one-three` says non-returners reach 2.2
- it belongs nearer **2.2**, which would cut 29% to about 23.7% and actually
excludes the readings that study associates with not coming back.

Second, **at 29% of bars the word "surprise" stops describing the thing.** A
1-in-3.4 event is not a dislocation, it is an ordinary bar. Whatever is being
traded at a floor of 1.3 is not the same phenomenon the rule was named for, and
it has to earn its own measurement rather than inherit the 3.0 one's.

The shape is strikingly consistent across feeds - every admitted major, every
index and both volatility indices sit within a percentage point of each other
at 1.3, 1.95 and 2.2 - and they separate only in the far tail. That is a
property of the standardisation, not of the markets, and it means a band chosen
on one feed will transfer to the others.

Each of those proposals costs its own round trip.

Three consequences, in the order they will be felt:

1. **Cost.** Sixteen times the trades at the same cost per trade. The admitted
   feeds run 0.5% to 4.2% of target, so a round trip is roughly 0.01 to 0.08 R
   on a 2R target; sixteen times more of them is a materially larger bill.
2. **CPU.** `statespace/actor.py` records that 207 armed feed-intervals at 1m is
   twelve thousand readings an hour, and tis has two cores shared with the live
   desk. The fold cost does not change - the surprise is computed either way -
   but the proposal, decision and journal path downstream does.
3. **Sample, which is the only upside.** `edge-life.md` puts the trades needed
   to tell a win rate from its geometric baseline at **350 to 800**, and the
   desk currently makes a handful a day. Sixteen times the flow is the
   difference between judging this rule in a quarter and judging it in years.

## What would settle it

**A sweep of the band against cost, with the arms this desk already requires.**
The grid is small - a floor from 1.3 to 3.0 crossed with a ceiling from 2.0 to
infinite - so it is not the 414-cell problem, but it is still a grid and the
real best has to be compared to the **shuffled** best rather than to zero:
`rsi-ma-momentum.md` ran 414 cells whose seven-day leaders had 0 of the top 10
positive the following month, and whose day-shuffled market's best beat the real
market's.

Three readings are needed per cell and only the third is an edge:

1. the **rate** - what share of bars fall in the band, which decides whether a
   cell can ever be measured;
2. the **realised R**, net of that feed's own quoted spread;
3. the **difference from the same cell on a day-shuffled twin**.

And the window is the operator's: **7 days to act, 3 months to judge, 1 year as
the maximum lookback**, with the arithmetic stated - 84 trades in a week against
the 350 to 800 a win rate needs.

## Status

| | |
| --- | --- |
| code | **merged, defaults unchanged** |
| live | **not enabled** - `STATESPACE_TRIGGER`, `TRADING_SURPRISE_MIN` and `TRADING_SURPRISE_MAX` are all unset |
| measured | the **rate** grid above; no realised R yet |

So the desk is still trading the 3.0 floor with no ceiling. Turning the band on
is a decision about proposal volume as much as about edge, and this page exists
so that whoever reads the result later knows what the setting was and why it was
tried.

## 2026-11-22: the live arm answered two questions in a day

Neither answer came from the grid above. Both came from the arm admitted on the
21st, which is the argument for running controls live.

### One signal, three clocks, three positions

`TRADING_INTERVALS` was `5m,15m,1h,4h`, with `statespace-surprise` scoped to
15m, 1h and 4h. The intent was three timeframes; what the desk actually did was
**take the same trade three times**, because `statespace` publishes one
proposal per feed and every clock's desk consumes it:

```
00:30:17.949  Range Break 200 Index_E270_1h-1  BUY 2.34 @ 73727.5
00:30:18.033  Range Break 200 Index_E270-1     BUY 2.34 @ 73729.5
00:30:18.048  Range Break 200 Index_E270_4h-1  BUY 2.34 @ 73728.5
```

Same feed, same side, **100 milliseconds apart**, and each fill a point worse
than the last. The same shape at 06:15 on Range Break 100 (three sells) and at
08:46 on BTCUSD (three buys). At 08:44 the **entire** open book was nine
positions holding three ideas.

So the multi-clock deploy was not three timeframes of evidence, it was **3x
leverage on one signal plus three spreads**, with the slippage ordered by
arrival. `a-shorter-clock-multiplies-cost-in-r` prices the clock; this is the
other half - a clock that adds no information still adds a round trip.

**Fixed by returning to `TRADING_INTERVALS=5m,15m`** (15m statespace, 5m zones),
on the operator's call: *"it sees the same thing regardless of timeframes and it
is make it enter the same position 3 times except we use the multiple timeframe
as confluence."* The confluence reading is the open design question and it is a
different rule: one entry, conditioned on agreement across spans, rather than
one entry per span. Nothing here measures it.

### Range Break enters after the impulse, by construction

Withdrawn the day after admission, on the operator's observation: *"it enters
after the impulse move."*

It is not a threshold to tune. Range Break ranges and then breaks, once per
range; this rule fires on a bar exceeding the floor in sigma; **on that
generator the only bar that qualifies is the break itself.** The entry is
therefore always after the move, never before it - and raising the floor makes
it fire less often and *later*, which is the wrong direction. The ceiling is the
only knob that refuses an already-extended bar, and per the grid above a
ceiling that does real work sits near **2.2** - but the band is global, one
setting for all 35 feeds, so it cannot be aimed at one of them.

The arm still paid for itself. It was admitted as the **level positive control**
with the expected outcome stated in advance - *"a rule that reads levels should
find something here"* - and what it found instead was where this rule's entry
sits relative to the move. That retires the arm, not the question. `step index`
stays: the tier-1 null is a measurement check, not a level claim, and nothing
about today touches it.

#### What it cost, from the broker's own deals

**Read 2026-11-23 from `/history/deals`, not from the journal.** The structural
argument above was made before any P&L was in hand; this is what the arm
actually cost in the day it ran.

| feed | round trips | net |
| --- | --- | --- |
| Range Break 100 Index | 3 | **-815.49** |
| Range Break 200 Index | 3 | **-336.96** |
| *everything else, 11-20 to 11-23* | 44 | -98.94 |

**-1,152.45 of a -1,251.39 total: 92% of three days' loss, on 12 deals.** The
six Range Break round trips are five of the six worst on the book over that
window.

Two things that number is **not**. It is not a measurement of the rule on this
feed - six round trips decide nothing, and the withdrawal rests on the
construction argument above rather than on this. And it is not all
attributable to the feed: these were taken while the desk ran one desk per
interval, so **each signal was entered three times**.

| signal | entered | closed | the three legs | total |
| --- | --- | --- | --- | --- |
| RB200 long | 00:30 | 00:41 | -109.98, -112.32, -114.66 | -336.96 |
| RB100 short | 06:15 | 08:14 | -274.38, -271.83, -269.28 | -815.49 |

One entry per signal would have cost about **-384**. The duplication added
roughly **-768** on two ideas, which is the separate finding recorded in
[[statespace-is-one-clock]] and fixed by returning `TRADING_INTERVALS` to
`5m,15m`.

**None of this reached the journal.** It holds nine `opened` entries for these
positions and **zero** outcomes, because the desk was not running when they
closed, so every report built on `report.trades` is blind to the worst day on
the book. That is the gap `journal/recovering.py` exists to close.

