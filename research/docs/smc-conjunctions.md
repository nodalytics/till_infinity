# Two SMC frameworks: the primitives are walks, the conjunctions are untestable

**Measured 2026-10-15.** Code: [`smc_battery.py`](../ideas/smc_battery.py).
516 arm-by-cell rows, four timeframe pairs, four instrument groups.

Two published methods arrived as named systems, and under the names they are
the same shape: a higher-timeframe bias, a liquidity event, and a
lower-timeframe entry at a zone.

**EMS** - mark a key level and wait for a clear rejection; find an engulfing
candle in that direction and draw the zone on the candle that got **engulfed**;
drop a few timeframes and require a clean structure inside the zone.

**SLK** - **S**tructure (trend and its shifts on H1 or H4), **L**iquidity
(internal and external range liquidity, order blocks, sweeps of resting stops),
**K**ey levels (bounce zones, timed on 15m or 5m).

## Why a conjunction was worth testing when the parts are closed

The primitives are already measured here and they are carried as the baseline
rather than as candidates: `sweeps.md` found every sweep form "identified
exactly, and predicting nothing"; `bos-predict.md` found the side of a break
unpredictable beyond geometry, at AUC 0.75 on walks as well as markets;
`structure.md` found nothing predicting direction beyond `side`;
`order-block-zones.md` found an 82% return rate and a losing read.

None of them tested the **conjunction**. Three filters that are each worthless
can still select a population that is not, and that is the entire claim both
frameworks make.

## The baseline has to be a walk, and this is why

The trade geometry loses money on a driftless random walk, by a lot. The stop
sits at the engulfing candle's extreme and the entry at the engulfed candle's
edge, so the risk can be a hair wide, both barriers fall inside one bar, and the
conservative reading charges the loss. Measured on a walk with no filter at all:
**−0.598R at a 1R target, hit rate 0.201**. A minimum stop distance removes the
worst of it and leaves the walk at −0.27R.

So a negative expectancy means nothing on its own, and a positive one means
nothing either. The column is `gross − walk`.

## First, a bug that inflated everything, found by asking a fair question

A driftless walk is a **martingale**, so no time-bounded stopping rule can have
positive expectancy on it. The first run of this study reported the
internal-imbalance arm making **+0.432R** on a walk. That is not a pattern in
the walk - it is impossible - so it was a leak, and finding it was worth more
than the study.

`resolve` began the race **on the fill bar**. The fill bar is the one whose
extreme reached the entry, and settling on it uses the same bar's *other*
extreme, which may have happened before the entry touch. A short entered at a
zone high was being booked a winner off a low that came earlier in that bar.

Measured on a walk, where a target of `k`R against a 1R stop must win about
`1 / (k + 1)`:

| | 1R | 2R | 3R |
|---|---:|---:|---:|
| required win rate | 0.500 | 0.333 | 0.250 |
| imbalance, settling on the fill bar | 0.567 | **0.470** | 0.346 |
| imbalance, settling from the next bar | 0.369 | 0.309 | 0.258 |
| all setups, from the next bar | 0.357 | 0.300 | **0.251** |

The last cell is the check: with the lookahead removed, the whole population
lands at 0.251 against a required 0.250. The imbalance filter was the biggest
beneficiary because it selects gap situations, where the fill bar is large and
spans both barriers - the apparent edge was largest exactly where the bug had
most room.

**Every number below is after the fix.** Walk expectancies now span -0.389 to
+0.371 across cells, where they reached +0.57 before it.

## The result: nothing clears its own walk and the multiplicity

| cell | arm | R | n | gross | walk | gap | z |
|---|---|---:|---:|---:|---:|---:|---:|
| 1h/15m fx crosses | CRT | 2 | 2,531 | -0.008 | -0.113 | +0.105 | +3.75 |
| 1h/15m fx crosses | CRT | 3 | 2,522 | +0.101 | -0.030 | +0.131 | +3.64 |
| 4h/15m fx crosses | engulf | 1 | 5,459 | -0.199 | -0.243 | +0.044 | +3.14 |
| 1h/15m fx crosses | CRT | 1 | 2,537 | -0.215 | -0.273 | +0.058 | +3.05 |
| 4h/15m fx crosses | origin body | 1 | 3,450 | -0.187 | -0.237 | +0.050 | +2.94 |

With **516 rows**, the largest `|z|` expected under the null is about 3.2, so a
peak of 3.75 is at the edge of what multiplicity produces by itself. Two things
make it worth a line rather than a dismissal: the three CRT rows are one cell at
three targets, agreeing in sign and rough size, and **every one of the top eight
rows is an FX cross or major with a 15m confirming frame** - a coherent corner
rather than scatter. Against that, they are nested rather than independent
confirmations, and none is positive in absolute terms at 1R or 2R.

**The honest reading is that no primitive here survives.** The one corner worth
a pre-registered out-of-sample test is Candle Range Theory on FX crosses with a
15m entry; every other primitive sits inside its own walk. The conjunctions are
a separate matter and the section below is about them.

## Three encodings the walk and the overlap table rejected first

**An engulf is not a displacement origin**, which is worth stating because both
are described as marking where the move began. Engulfing bars carry 1.42 times
the median range with a body of only 0.408 of it, against 0.499 for bars
generally, and 0.151 clear the 0.65 body share the desk's push test requires
against 0.314 of all bars. An engulf selects a **wide, wick-heavy** bar; a
displacement selects a **body-dominant** one.

**A structure shift and a sweep cannot be the same bar.** A shift closes beyond
the range and a sweep closes back inside it, so on one frame their Jaccard
overlap is **0.016** and the first SLK encoding fired on 1 of 622 walk setups.
Both frameworks establish the bias on the higher frame and wait for the
liquidity event below - top-down is not decoration, it is what makes the
conjunction satisfiable at all.

**Two of the named primitives are largely one event.** A range engulf already
takes out the prior bar's high, so Candle Range Theory is satisfied on 0.706 of
engulfing bars by construction, and over a twenty-bar window a structure shift
in the trade direction occurs on 0.741 - with a Jaccard of 0.552 between them.
Key levels and external sweeps overlap at 0.418, because a sweep is a poke past
a prior extreme and a key level **is** a prior extreme.

## The conjunctions are not measurable, which is not the same as null

**This is the correction that matters most, and a census is what found it.**
The first version of this table printed only rows reaching 200 setups in a
cell, so the arms the study exists for produced **no rows at all** and the table
silently contained primitives while the document claimed to have tested the
conjunctions. Every arm's setup count is now printed whether or not it scores.

Across all sixteen cells, from 18,855 engulfing setups and 3,226 that also had
a key-level rejection:

| arm | setups, all cells |
|---|---:|
| engulf | 18,855 |
| engulf + key level | 3,226 |
| **EMS** (engulf + level + structure) | **29** |
| **SLK** (bias + level + structure) | **3** |
| everything | 3 |

The binding constraint is the lower-frame structure filter - a sweep inside the
zone followed by a break of structure - and it needs a long lower-frame window
to have any chance of occurring. It fires only where the frame ratio is 16:1
(4h signal, 15m confirm) and essentially never at 4:1 or 6:1, which is a
property of the window rather than of the market.

Two further things had to be fixed before even that was visible. The signal
frame is now **clipped to the span the lower frame covers**: `LIMIT` bars of 4h
reach back about eighteen years where `LIMIT` bars of 15m reach back one and a
half, so most signal bars had no lower frame at all and `structure` was false by
default rather than by measurement. And structure is evaluated over the
**retrace**, from the engulfing bar to the bar that fills, rather than inside
the signal bar's own span, because the method says to drop timeframes while
waiting for the entry.

**So the honest statement is narrower than the title of the first draft.** The
primitives are measured on thousands of setups each and every one sits inside
its own walk. The conjunctions - the actual claim both frameworks make - are
**untested**, because on the overlapping history available they fire between
three and twenty-nine times. Testing them needs lower-frame history long enough
to cover the signal frame, which this cache does not have; the alternative is
loosening the definitions until they fire, which would be inventing a method
rather than testing one.

## What this does not test

**The engulf itself.** Every setup in this harness is generated at an engulfing
bar, so the sampling frame already contains it and `engulf + X` is identical to
`X` in every row. What is measured is which filters help *within* engulfing
bars. Testing whether the engulf adds anything needs a non-engulf control
population, which this does not have.

**Discretion.** These are published as discretionary methods with chart
judgement about what counts as "clean" structure. A mechanical encoding is the
only testable version and it is not the same object. What the measurement can
say is that the mechanical version has no edge over the geometry it is built
from, on four timeframe pairs and four instrument groups.
