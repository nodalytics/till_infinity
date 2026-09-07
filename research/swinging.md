# `swing-level`, replayed - the first numbers it has ever had

Measured 2026-09-05 over 17 instruments and 1,099,702 stored bars, on the
redesign committed the same day. The strategy has never opened a trade in
production, so until this run every one of its six parts was a reasoned choice
with nothing behind it.

## What was run

Levels are rebuilt bar by bar through the same `observe_bar` the live path
uses, so a call at time T knows only what had closed by T. Each accepted call
goes through the real `SwingLevel.consider`, and the result is walked forward
until the stop, the target or the 24-hour clock, with break-even at 1.5R and
the 4.0v trail applied in the order the live manager applies them.

Results are in **R**, and the quoted spread is charged as one full round trip
- bought at the ask, sold at the bid - at the median spread on the venue this
desk trades. Gross R is not a result.

| | trades | gross | net | mean net | win rate |
| --- | --- | --- | --- | --- | --- |
| **rejection candle required** | 72 | -2.08R | **-12.46R** | **-0.173** | 34.7% |
| nothing required | 303 | -49.57R | -89.96R | -0.297 | 33.0% |

## The confirmation gate is the most valuable thing in the strategy

It refuses **76%** of what the strategy would otherwise take and moves the
mean from -0.164R to -0.029R gross. That is +0.135R a trade, and it is the
only component here that pays for itself.

This is worth stating plainly because the gate was widened in the same commit
- from 4h alone to 1h/2h/4h coarsest-first - on the argument that a 4h bar
closes six times a day and insisting on it refuses every setup formed in the
last four hours. The widening is what makes 72 trades exist at all.

## Why it lost, before the sweep below: the geometry, not the selection

| exit | n | mean net R |
| --- | --- | --- |
| stop | 35 | -1.130 |
| target | 14 | +1.205 |
| trail | 19 | +0.532 |
| clock | 4 | +0.023 |

At a 34.7% win rate the winners have to average **1.88R** to break even. They
average 1.2R at the target and 0.53R on the trail. **The target is too near
for the hit rate the entry produces**, and that is a statement about the
opposite bound: `target_multiple` 2.5 is a floor, and the bound is usually
nearer than the floor, so the box is what sets the target and the box is not
wide enough relative to a stop placed 1.5× beyond the level.

Two candidates, and they point in opposite directions:

* **The stop is too wide for the box.** `stop_multiple` 1.5 on a level whose
  opposite wall is 1.2 stops away is a trade risking most of what it can win.
* **`at_bound` 0.20 is too generous.** Entering a fifth of the way into the
  range spends a fifth of the target before the trade starts. It was named as
  the number most likely to be wrong, and this is the shape of evidence that
  would convict it.

The trail is a third: 19 trades left at +0.53R against 14 reaching +1.21R
means it is ending winners at less than half the target. 4.0v was set for a
daily-anchored move and has never been measured either.

## The sweep, and the one constant that decided everything

> Read with the section after it. Everything here is measured against the
> **confluence-zone** box, which the next section replaces - and one of the two
> conclusions below does not survive that.

Run 2026-09-07: the three convicted constants swept together inside a single
replay, since rebuilding levels is the expensive half and `consider` is
arithmetic. Eight cells, candle required, net of the spread.

| at_bound | stop | trail | n | net R | mean | win |
| --- | --- | --- | --- | --- | --- | --- |
| 0.10 | **1.0** | 4 | 68 | **+3.70** | **+0.054** | 38.2% |
| 0.10 | **1.0** | 6 | 68 | +2.95 | +0.043 | 30.9% |
| 0.20 | **1.0** | 4 | 75 | +3.14 | +0.042 | 37.3% |
| 0.20 | **1.0** | 6 | 75 | +0.90 | +0.012 | 29.3% |
| 0.20 | 1.5 | 4 | 72 | -12.41 | -0.172 | 34.7% |
| 0.10 | 1.5 | 6 | 66 | -12.21 | -0.185 | 28.8% |
| 0.20 | 1.5 | 6 | 72 | -13.31 | -0.185 | 27.8% |
| 0.10 | 1.5 | 4 | 66 | -12.49 | -0.189 | 34.8% |

**Every cell with a 1.0 stop is profitable and every cell with a 1.5 stop
loses.** The split is clean across both bound settings and both trail
settings, which is the thing worth having from a grid - a direction that
holds, rather than the corner with the best number in it.

The reason is the geometry named above. The target is the opposite bound and
the bound does not move when the stop does, so half a unit of extra stop makes
every win smaller and buys nothing. Measured: **the target pays +1.68R at a
1.0 stop against +1.21R at 1.5**, and the win rate went *up* rather than down,
37.3% against 34.7% - because break-even at 1.5R is reached sooner on a
tighter stop and scratches trades that would otherwise have run to the loss.

`at_bound` 0.10 beats 0.20 at both stops and both trails, but by about a tenth
of what the stop is worth and at the cost of seven trades in sixty-eight. Taken
on the arithmetic - entering a fifth of the way in spends a fifth of the target
before the trade starts - rather than on this table alone.

**This is the conclusion that did not survive.** The next section replaces the
box these fractions are fractions *of*, and 0.20 then wins at every setting.

`trail_vol` 6.0 was worse than 4.0 in three of four pairs. A null, recorded so
it is not rediscovered: the trail is not what was costing this strategy money.

### What the sign is and is not

Mean +0.054R over 68 trades, with an R distribution whose spread is about 1.0,
has a standard error near **0.12**. So the *level* is not distinguishable from
zero, and the strategy after this change is best described as **no longer
losing** rather than winning.

What is distinguishable is the *difference* between the two stop settings,
because it is a paired comparison over nearly the same calls on the same bars:
+0.214R a trade, in the same direction in all four pairs. That is the finding.
The profit is not.

## Origin to origin, which turned out to be the whole strategy

Run 2026-09-07, after the sweep above and prompted by looking at a published
box: `usdcad 1.3493 .. 1.3518`. Twenty-five pips is not a swing range.

The walls were **confluence zones** - prices several timeframes had drawn a
level at. An origin is a different object: the price a violent move *began*
from, so the interest that stopped the last advance is still resting there.
Measured over 4,117 published calls, in bps of price so the two are comparable
however each was scaled:

| interval | n | confluence box | origin box | ratio |
| --- | --- | --- | --- | --- |
| 1m | 1,739 | 563.0bps | 22.7bps | 24.8x |
| 5m | 1,087 | 509.1bps | 33.3bps | 15.3x |
| 15m | 348 | 353.0bps | 63.4bps | 5.6x |
| 1h | 59 | 290.6bps | 56.8bps | 5.1x |
| **4h** | 20 | **385.1bps** | **70.9bps** | **5.4x** |

At the anchor the confluence box is **385bps - 3.85% of price**. A trade held
for twenty-four hours does not traverse that, so its far wall was not a target;
it was open air with a price on it, and `range_position` inside it was a
reading about a range that would never be crossed. The origin box at 71bps is
about a day's range on a major, which is the size the hold implies.

### What it did to the strategy

The same eight-cell sweep, candle required, net of the spread:

| at_bound | stop | trail | n | net R | mean | win |
| --- | --- | --- | --- | --- | --- | --- |
| **0.20** | **1.0** | **4** | **95** | **+28.36** | **+0.299** | **49.5%** |
| 0.20 | 1.0 | 6 | 95 | +24.71 | +0.260 | 45.3% |
| 0.10 | 1.0 | 6 | 83 | +20.21 | +0.244 | 45.8% |
| 0.10 | 1.0 | 4 | 83 | +18.65 | +0.225 | 49.4% |
| 0.20 | 1.5 | 4 | 93 | +18.11 | +0.195 | 51.6% |
| 0.20 | 1.5 | 6 | 93 | +13.06 | +0.140 | 46.2% |
| 0.10 | 1.5 | 4 | 81 | +9.94 | +0.123 | 51.9% |
| 0.10 | 1.5 | 6 | 81 | +9.40 | +0.116 | 46.9% |

**Every cell is profitable**, against four of eight before, and the best cell
goes from +0.054R to **+0.299R a trade over 95 trades**. The win rate moves
from 38.2% to 49.5%: the target is *nearer* now - +1.10R against +1.68R - and
it is reached 35 times in 95 rather than 16 in 68. That is what a reachable
target looks like.

The 1.0 stop survives the change, winning in all four pairs again. The trail is
mixed and stays at 4.0.

### And `at_bound` reversed, which is the lesson

The previous sweep preferred **0.10** at every stop and trail setting. This one
prefers **0.20** at every one of them. Nothing about the bound changed - the
box did, by a factor of five - and a tenth of a 71bps box is not the same
requirement as a tenth of a 385bps one.

So the first sweep was measuring **the container, not the parameter**. That is
worth stating as a rule rather than an anecdote: a constant expressed as a
fraction of something else is only meaningful while that something else holds
still, and this one was fitted three commits before the thing it divides by was
replaced. `stop_multiple`, which is a fraction of the level's own volatility
rather than of the box, survived the change untouched.

### What this is, and is not

+0.299R over 95 trades with an R spread near 1.0 is a standard error of about
**0.10**, so this is the first number in the whole exercise that separates from
zero. Two honest qualifications:

* The eight cells are in-sample. The **structural** change is not - drawing the
  box from origins was decided on the 385-vs-71bps measurement above, before
  any of these trades were scored, and it lifted all eight cells rather than
  one.
* Everything in [what this run cannot see](#what-this-run-cannot-see) still
  applies, in particular that the momentum half of the confirmation gate is
  tick-fed and unreachable from bars.

## The fine-derived band, replayed - and it is worth more than the localization was

`research/localising.md` re-derived the origin's band from the 1m bar at the
refined transition and found it **2.6x narrower** than the coarse bar's range
while catching 94.8% of the same returns and holding about as often. The stop
on an origin trade sits beyond the band, so that was an argument about money
that only this harness could settle.

Same eight cells, same instruments, same everything but the walls:

| at_bound | stop | trail | coarse band | fine band |
| --- | --- | --- | --- | --- |
| **0.20** | **1.0** | **4** | +0.349R (100) | **+0.576R (71)** |
| 0.20 | 1.0 | 6 | +0.322R (100) | +0.566R (71) |
| 0.20 | 1.5 | 4 | +0.259R (97) | +0.454R (67) |
| 0.20 | 1.5 | 6 | +0.218R (97) | +0.412R (67) |
| 0.10 | 1.0 | 4 | +0.220R (90) | +0.365R (49) |
| 0.10 | 1.0 | 6 | +0.252R (90) | +0.360R (49) |
| 0.10 | 1.5 | 4 | +0.149R (86) | +0.189R (46) |
| 0.10 | 1.5 | 6 | +0.150R (86) | +0.182R (46) |

**The fine band wins in all eight.** The best cell goes from +0.349R to
**+0.576R a trade**, a 65% improvement, on a win rate that rises from 49.0% to
54.9%. Total R rises from +34.85 to +40.90 *on 29 fewer trades*, which is the
shape the band argument predicted: a narrower band is a tighter stop, so the
same evidence is bought at a third of the risk and fewer calls qualify.

At 71 trades with an R spread near 1.1 the standard error is about 0.13, so
+0.576 is roughly four standard errors from zero - and the eight cells all
moving the same way is the part that makes it more than one lucky corner.

### The gap between this and what production can do

This run assumes the **whole 1m history is on hand**. Production holds a
rolling `Series` of 500 bars, so 1m covers about eight hours - enough to refine
a 4h origin formed this morning and not one formed last week. Since
`origins_bracketing` takes the two origins nearest price, and those can be of
any age, most walls in production would keep their coarse band.

So the table above is an **upper bound, not a forecast**. The deployable
number is the mixed case - refine what is coverable, keep the coarse band
otherwise - and it was measured rather than guessed:

| band | best cell | trades |
| --- | --- | --- |
| coarse, what runs today | +0.349R | 100 |
| **window, deployable as-is** | **+0.349R** | **100** |
| fine, whole 1m history | +0.576R | 71 |

**The window row is the coarse row, to the cent, in every cell.** Not
approximately: identically. Every origin that set a wall in this replay was
older than eight hours, so nothing was refined and the run reproduced the
baseline exactly.

That is the useful form of the answer. The improvement is real, large and
**entirely inaccessible** to the current architecture - so the thing to build
is not the refinement, which is already written and tested as
`origins.refine`, but the means of keeping its result.

Two ways to close it, of very different sizes:

* **Grow the 1m window** until it covers the origin lookback. The 4h series
  reaches back 500 bars, so this is 120,000 one-minute bars per feed against a
  container holding 500. Not affordable, and not close.
* **Persist origins with their bands**, so a refinement computed once at
  formation - when the 1m evidence for that bar *is* in the window - survives
  to be used weeks later.

**The second is built.** `Origins.remember` merges a fresh detection into a
kept set, refining anything new at the moment it first appears, and
`Engine._remember_origins` holds one of those per feed and timeframe. The
engine is already persisted whole, so the dict rides along and a band refined
today is still there in a month.

Identity is `(when, launched)` - the bar the turn happened on and which way the
impulse went - rather than price, because the refinement *moves* the price and
keying on it would make every refined origin look like a new one. The set is
bounded at 200 per feed and timeframe, oldest dropped first.

Two things that had to be got right and were nearly not:

* `Engine.series` **creates** the entry it is asked for, and `touch_source`
  picks the finest interval that has one. Asking it for the 1m series to refine
  against silently moved the touch check onto a series that had never received
  a bar. Three tests caught it; production would have stopped touching levels.
* The engine is persisted whole and is **not** a `Restorable` dataclass, so
  nothing fills in a new attribute on a restore from an older save. The first
  call after the deploy would have raised inside the `try` that swallows it,
  and every origin feature would have gone quietly missing.

### And production said where, within the hour

`Origin.refined` was added so the question had an answer, and the structures
save logs the tally. Three cycles in:

```
20:08  20 origin(s) kept across 13 series, 0 refined (0%)
20:13  4786 origin(s) kept across 390 series, 200 refined (4%)
20:18  6835 origin(s) kept across 553 series, 287 refined (4%)
```

Persistence works and the refinement fires. Then the breakdown that matters,
because the swing box takes its walls from **4h**:

| interval | kept | refined | share |
| --- | --- | --- | --- |
| 1m | 1,681 | 83 | 5% |
| 3m | 1,408 | 84 | 6% |
| 5m | 1,851 | 97 | 5% |
| 15m | 570 | 13 | 2% |
| 30m | 195 | 7 | 4% |
| 1h | 180 | 2 | 1% |
| 2h | 26 | 0 | 0% |
| **4h** | **924** | **1** | **0%** |

**One 4h origin in 924.** The 4% is carried almost entirely by 1m, 3m and 5m -
intervals whose bars are minutes long, so the live 1m window covers them
trivially and none of which sets a swing wall.

The reason is structural and was in `Origin.settled` all along: an origin does
not exist until its impulse **breaks structure**, which is `MOVE_BARS` bars
after the turn. On 4h that is hours to days later, and the 1m window holds
eight hours - so by the time a 4h origin is first seen, the minutes inside its
turn bar are long gone. Persisting origins moved the refinement from "computed
and thrown away" to "computed once and kept", and on 4h there was never a
moment when it could be computed at all.

So the +0.576R is still out of reach, and the reason has moved rather than
gone: it is no longer the storage, it is **when the refinement is attempted**.

### What would actually reach it

Capture the fine transition **when the coarse bar closes**, not when an origin
is detected. Every 4h bar has its 1m minutes available at the moment it closes;
that is the only moment they are guaranteed to be there, and it is hours or
days before anything asks whether that bar was an origin.

Concretely: one float per bar on `Series` - the extreme fine close inside it -
computed on append and carried in the same rolling window as `closes` and
`highs`. `refine` then reads a stored number instead of scanning a 1m series
that has moved on. The cost is one float per bar per series; the change is to a
persisted dataclass, so it needs the schema note the last one got.

**Built.** `Series.fine_low` and `Series.fine_high` carry the extreme fine
closes of each bar, captured by `Engine._capture_fine` every time that bar
arrives - not only when it is new, because a bar arrives repeatedly while it
forms and only the last of those calls has the whole bar behind it.
`origins.extremes_in` finds them and refuses partial cover; `origins.refine`
now takes the two numbers rather than a series, so the refinement is a lookup
against a bar that kept its own minutes instead of a scan of a window that has
moved on.

Both new deques carry the same guard `opens` already needed: a `Series`
restored from before they existed has empty deques beside full ones, and
appending blindly would pair every bar with another bar's minutes from then
on.

### Two failures found by watching it rather than by reasoning about it

Both were invisible in the tests and obvious in the production state.

**The deques never started.** Every other late-added field on `Series` is
guarded by "exactly one behind the closes", which a *restored* Series never
is - it has 500 closes and none of the new field, so the test would not have
been true once and the field would have stayed empty for the life of the
process. Checked against the live state: 1 series aligned, 3,053 short. Now
padded with `nan`, which says "unknown" about the bars that predate the field
because that is what is true of them.

**The capture targeted the bar still forming.** `note_fine` wrote to the end
of the deque, and the end is the bar in progress - its span runs into the
future, so no finer series can ever cover it and `extremes_in` correctly
refused every time. The live state said so exactly:

| interval | bars paired | captured |
| --- | --- | --- |
| 3m | 60 | 3.3% |
| 5m | 46 | 8.7% |
| 15m | 35 | 8.6% |
| 30m | 31 | 3.2% |
| **1h and coarser** | 2,119 | **0.0%** |

The fine intervals scored a few percent only because a short bar is often
already closed by the time the collector re-reports it. On 4h the newest bar
is the forming one for four hours, and by the time it closes the next one has
started - so it was never once offered while it was complete.

A bar is complete exactly when the next one starts, so the capture now targets
the **last two** bars by timestamp rather than the end of the deque: the one
before the end, which has certainly closed, and the end itself, which will
fail until it has.

### Verified without waiting for a boundary

A 4h bar completes every four hours, so watching the refined share for the
answer costs most of a day. The question can be asked directly instead: take
the bar the next one has already closed and ask `extremes_in` whether the live
1m series covers it - exactly what the capture will do at the boundary, with
no clock in the way.

| | 1h | 2h | 4h |
| --- | --- | --- | --- |
| would capture now | 37 | 36 | **33** |
| not covered | 264 | 256 | 266 |
| no 1m series at all | 19 | 18 | 19 |

**The chain works.** A tenth of 4h series would capture on the next boundary,
which is the first time any of this has been true at 4h.

And the binding constraint is now named rather than suspected. Every "not
covered" carries its reason:

```
us100  4h  1m covers 5.2h, needs 4.0h   <- would capture
spx500 4h  1m covers 3.5h, needs 4.0h
eurusd 4h  1m covers 2.8h, needs 4.0h
btc    4h  1m covers 2.8h, needs 4.0h
```

The 1m window is 500 bars - 8.3 hours when full - and it is not full, because
the process restarted. As it fills, 4h coverage should rise from a tenth
toward most feeds. That is a prediction with a date on it rather than a hope,
and the same query answers it.

What will never capture is 1d and 1w: a day needs 24 hours of minutes against
a window holding eight. Nothing that sets a swing wall is drawn there, so it
is a limit rather than a problem - but it should be stated before someone
reads a zero as a fault.

The refined share **at 4h** remains the number that closes this out, and it was
1 in 1,315.

## The spread

**0.144R a trade**, 10.37R over the 72. Not the dominant term - the swing stop
is wide enough that the spread is about a seventh of it - which is worth
recording because `research/catalogue.md`'s 2.267v for FX is a scalping
number, and reading it as a swing number would condemn the wrong thing.

Per instrument the median spread on our venue runs 0.56bps (us30) to 13.56bps
(sol), with the synthetics at 3.71bps.

## By instrument, and why the split is not a result

gbpusd +9.64R over 16 trades and spx500 -6.42R over 9 is the largest split in
the table, and with fewer than twenty trades either side it is what a coin
does. **No instrument here has enough trades to rank.** The one thing worth
taking from the split is that FX, metals and indices all *produce* trades,
which the synthetics did not: `volatility_75_index` replayed 5,658 bars and
generated **zero** - it has too little stored history for 4h zones to form.

## What this run cannot see

* **The momentum half of the confirmation.** It is fed from the quote stream
  and a bar replay has no ticks, so the live gate - momentum **or** candle -
  is bracketed by the two rows above rather than measured. The live strategy
  should sit between -0.173 and -0.297 mean R, nearer the first.
* **Touch resolution is 5m, not 1m.** 1m and 3m were left out of the extract,
  and the engine runs its touch check on the finest interval it is given.
* **Bar order inside a bar.** A bar spanning both barriers is scored as the
  loss. Bar data cannot say which came first, and assuming the win is how a
  backtest lies.
* **One position per instrument, none across them.** 1,085 candidates were
  refused for a trade already being open, so the live book - which can hold
  several instruments at once - takes a different sample than this.
* **35% of each series is warm-up** and produces no trades.

## What it does not claim

That the strategy is dead. 72 trades over 25-73 days is a small sample, the
selection half is measurably working, and the losing half is the exit
geometry - which is three constants, all of them unmeasured, all of them
changeable without touching the idea.

That order was: the target first, `at_bound` second, the trail third. The
sweep answered it differently and better - the term that fails the arithmetic
is the **stop**, not the target, because the two are the same ratio seen from
opposite ends and the stop is the half this strategy controls. `stop_multiple`
is now 1.0, `at_bound` 0.10, `trail_vol` unchanged at 4.0.
