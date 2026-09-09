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

## Run on 2026-09-09

14 days of decisive touches - `reject` against `break`, the two outcomes that
say whether the level held. A tally is the paired instrument resolving a touch
of **its own** level within two minutes, which needs no price mapping and no
fitted beta.

**Two minutes, not fifteen.** The first pass used a quarter of an hour and 94%
of EURUSD touches tallied with GBPUSD, so the variable barely varied and the
"untallied" group was whatever happens in the quiet hours. A tally has to be
rare enough to mean something; at two minutes it runs 39-59% on the real pairs.

### Within the hour of day, which is the number that counts

Pooled figures are confounded by the session - touches cluster where everything
else does - so the comparison is made inside each hour and the medians are
reported across hours.

| pair | median gap | hours positive | |
| --- | --- | --- | --- |
| **eurusd / gbpusd** | **+5.6%** | **21 of 24** | both dollar |
| eurusd / usdchf | +3.1% | 16 of 24 | both dollar |
| gold / audjpy | +2.6% | 16 of 22 | *see below* |
| usdcad / usdchf | +2.4% | 17 of 24 | both dollar |
| silver / gold | +2.4% | 15 of 23 | metals |
| silver / eurusd | +2.0% | 15 of 23 | dollar only |
| gbpusd / usdjpy | +1.7% | 18 of 24 | both dollar |
| audusd / nzdusd | +1.7% | 16 of 24 | both dollar |
| gold / silver | +0.9% | 11 of 22 | metals |
| eurusd / eurgbp | +0.3% | 12 of 24 | shared EUR |
| gold / eurusd | +0.0% | 10 of 21 | dollar only |
| gold / usdjpy | -1.1% | 8 of 19 | dollar only |
| **eurusd / audjpy** | **-1.5%** | **6 of 24** | **control** |
| **volatility 25 / 75** | **-0.2%** | **10 of 21** | **control** |

Pooled, `eurusd/gbpusd` runs 95.2% held when tallied against 89.9% when not,
p < 0.002 on 500 permutations.

### Both proper controls are clean, and one "control" was not a control

The synthetic pair is flat (-0.2%, 10 of 21 hours) and EURUSD against AUDJPY is
mildly *negative* (-1.5%, 6 of 24). Those are the two that had to come back
empty and they did.

**`gold/audjpy` fired at +2.6%, and it is not a counter-example - it was
mis-specified.** AUD is a commodity currency and Australia is a major gold
producer; AUD and gold co-move. Listing it as "no shared currency" confused
*currency* with *factor*, and the pair shares a factor even though it shares no
currency. That is a fault in the design, found by the design.

### What it does and does not support

**It supports:** a level is more likely to hold when a paired dollar instrument
is simultaneously at one of its own. The lift is 1.7 to 5.6 points on a base
rate already near 90%, consistent across hours, and it survives both honest
controls.

**It does not support the general claim.** The effect lives in the **dollar
bloc**, which is the most confounded case there is - `peering.md`'s lesson was
that two dollar pairs are one witness seen twice. The test that would separate
"a shared factor at a level" from "the dollar at a level" is the metals, and
**gold/silver returns +0.9% on 11 of 22 hours**, which is a coin flip. If the
mechanism were shared-factor confirmation the metals should show it and they do
not.

So the reading is: **something real, probably about the dollar, and not the
general principle it was proposed as.**

### The dollar composite carries it, and the pair adds nothing

That was the test named as decisive, and it was run the same day.

No dollar index is collected, and building one would mean detecting levels on a
synthetic series with a detector never calibrated for it - introducing a new
object to test a claim about an existing one. The same question is answerable
directly: **count how many dollar pairs are at a level at once.**

The count effect is strong and monotone on every pair in the bloc:

| others at a level | 0 | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- | --- |
| eurusd held | 78% | 86% | 91% | 95% | **96%** |
| gbpusd held | 86% | 89% | 91% | 94% | 95% |
| usdjpy held | 84% | 85% | 92% | 94% | 96% |
| usdchf held | 86% | 91% | 91% | 92% | 97% |
| nzdusd held | 83% | 89% | 91% | 92% | 95% |

And **conditioned on that count, which pair it is stops mattering**:

| eurusd / gbpusd, others at a level | n | tallied | not | gap | p |
| --- | --- | --- | --- | --- | --- |
| 1 | 261 | 91.5% | 84.7% | +6.9% | 0.140 |
| 2 | 470 | 92.5% | 90.1% | +2.3% | 0.285 |
| 3 | 559 | 95.2% | 93.9% | +1.3% | 0.325 |
| 4 | 537 | 95.9% | 95.9% | **-0.0%** | 0.590 |
| 5 | 453 | 95.2% | 96.2% | **-1.1%** | 0.725 |

Median +1.3% across counts, 3 of 5 positive, and no cell reaches significance.
`eurusd/usdchf` and `usdcad/usdchf` are worse - median **-2.5%** and **-0.7%**,
positive in 1 of 5 each.

**So the pairwise result was the count all along.** The +5.6% for
`eurusd/gbpusd` was GBPUSD standing in for "the dollar bloc is at a level", and
once that is known, GBPUSD specifically adds nothing.

### What is actually left, and it is broader than the question asked

The count effect is not confined to the dollar. The metals show the same shape
with the two instruments available - gold 84% held with silver quiet against
89% with silver also at a level; silver 89% against 92%.

So the surviving claim is not about pairs and not about the dollar:

> **The more instruments are simultaneously at a level, the more likely any one
> of them holds.**

That is worth having and it is **not yet a result**, because the obvious
confound has not been removed: more instruments at levels is also a busier
market, and the count was not conditioned on the hour the way the pairwise
comparison was. It could still be volatility wearing a costume.

### What would settle *that*

* **Condition the count on the session**, the way the pairwise test was. If a
  count of four beats a count of one *within the same hour*, it is not the
  clock.
* **Condition on realised volatility**, which is the more likely confound and
  the one the hour only partly proxies.
* **Longer than 14 days**, and a block bootstrap - touches of one level are
  heavily autocorrelated, so every p-value here overstates what is known.
* **The metals with more data.** 1,182 gold touches is thin, and it is the pair
  that carries the interpretation.

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
