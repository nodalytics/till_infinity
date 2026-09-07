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
