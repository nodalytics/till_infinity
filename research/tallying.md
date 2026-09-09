# One level, two instruments

The engine draws levels per instrument and per timeframe, and
[agreeing.md](agreeing.md) established that a change point confirmed across
*timeframes* is a different object from one seen on a single clock - +7.92v a
day out against -1.24v, at a matched realised move.

The proposal here is the same question across *instruments*. If EURUSD has a
level and GBPUSD has one at the corresponding price, is that pair worth more
than either alone?

**Not run yet.** This is the design, written before the harness, and most of it
is about the two ways it will be wrong.

## What "the corresponding price" even means

This is the hard part and it is not a detail. EURUSD at 1.0850 and GBPUSD at
1.2700 are not comparable numbers, so a "level in the same place" needs a
mapping, and every candidate mapping is a modelling choice that can manufacture
the result:

* **The shared factor.** Both are dollar crosses, so a dollar move puts a level
  in both. Expressing each as a distance from its own recent price in
  **volatility units** makes them comparable, which is the unit this repository
  already uses for exactly this reason.
* **The cross itself.** EURGBP is the ratio, and it is collected. A level on
  EURGBP is a statement about EUR against GBP that neither dollar pair makes
  alone, and it is the honest place to look for agreement between them.
* **Correlation-implied.** Map a GBPUSD price to its EURUSD equivalent through
  a fitted beta. Flexible, and it puts a fitted parameter inside the definition
  of the thing being tested, which is how a null gets defeated by its own
  construction.

**Start with the second.** It needs no fitting and it has a real economic
meaning: agreement between two dollar pairs is either the dollar moving - in
which case EURGBP says nothing and the "agreement" is one event counted twice -
or it is genuinely both currencies, which EURGBP will show. That distinction is
the whole experiment.

## The confound, and it has already killed one of these

[peering.md](peering.md) ran the cross-instrument version of the change-point
question and it **failed its control**: Deriv's synthetics, which share no
factor at all, produced a *larger* apparent effect than real assets that share
the dollar. The lesson transfers exactly.

**EURUSD and GBPUSD are not two witnesses. They are substantially one witness
seen twice**, because both are largely a dollar trade. A test that finds
"agreement predicts" without separating the dollar from the pair has found that
the dollar moves two dollar pairs, which nobody doubts and nobody can trade.

So the design needs:

* **A same-factor control.** Compare agreement between two dollar pairs against
  agreement between pairs sharing *no* currency - EURUSD and AUDJPY, say. If
  the effect is about the shared factor it should be much weaker there.
* **The synthetic control again**, because it costs one extra run and it is the
  only thing in `peering.md` that settled anything.
* **A permutation test, not one shuffled draw** - [focusing.md](focusing.md)
  shows what a single draw is worth.

## What would be measured

Not "do the levels line up" - they will, often, for arithmetic reasons. The
outcome has to be what the level *does*:

**Conditioned on a touch, does the reaction differ when the corresponding level
exists on the paired instrument?** The engine already records every touch and
its resolution, and `reactions` already scores what happens next. The question
is whether the held rate and the excursion distribution shift.

The population is **touches, not trades**. Trades are too few and are filtered
by every gate in `trading`; touches are what the level model actually claims
something about, and there are tens of thousands of them.

## Why this might be worth more than it looks

Because it is the one idea in this folder that could raise the **quality of a
level** rather than the precision of its price. Everything measured recently -
the refinement, `origin_confirmed`, the change count - locates a level better.
None of it says a level is more likely to hold.

And because the strongest form is cheap: if agreement across instruments means
anything, it should show in the **base rate of a touch holding**, which needs
no trading, no costs and no execution assumptions.

## Where it goes if it works

The same place `change_up_tf` went: onto the call as a feature, journalled,
gating nothing, until the outcome record says whether a confirmed level behaves
differently from an unconfirmed one. That is the order this repository got
wrong with `reward_to_risk` and right with `strength` and `drawn_by_n`.

## The book is small on purpose, and that shapes this

Four levels a human marked were checked against the engine's own state on
2026-09-09. **All four were there**, within 1.4 to 6.6 basis points:

| marked | nearest in the book | gap |
| --- | --- | --- |
| spx500 7624.30 | 7625.33 (5m) | +1.4bps |
| gold 4441.03 (30m) | 4438.11 (30m) | -6.6bps |
| gold 4441.03 | 4440.33 (1m) | -1.6bps |
| usdjpy 152.746 | 152.664 (1d) | -5.4bps |
| btc 77621.21 | 77669.41 (4h) | +6.2bps |

An earlier pass called two of these misses. That pass queried levels that had
**produced journal entries**, which is a record of what got published, not of
what is held - and it is a badly biased sample of it, weighted to whichever
timeframes generate calls. The book is the source; the journal is not.

**What is true is that the book is deliberately small.** 3,451 (feed, interval)
sets holding **1 to 15 levels each** - about twelve thousand in total.
`Engine.prune` drops an untouched level more than `KEEP_VOL` (8.0) volatility
units from price, on the argument that a level price is nowhere near is only
crowding the set.

Two consequences for this experiment, and the second is the awkward one:

* **It is a near-price working set, not a historical map.** Asking whether the
  book holds a given price is only meaningful while price is near it, and a
  level drops out and is redrawn as price travels.
* **Agreement across instruments is therefore conditioned on both being near
  their level at once.** That is not a bug - it is when the question matters -
  but it thins the population sharply, and any harness needs to count how many
  paired observations actually exist before it promises a measurement.
