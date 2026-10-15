# Two SMC frameworks, decomposed: every filter and every conjunction is a walk

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

## The result: nothing beats its own walk

Across all 516 rows with 300 or more setups, the **largest** `gross − walk`
reaches `z` of **+1.95**, and the next eleven sit between +1.00 and +1.12. With
516 rows that is what chance produces.

| cell | arm | R | n | gross | walk | vs walk | z |
|---|---|---:|---:|---:|---:|---:|---:|
| 4h/15m fx crosses | CRT | 1 | 2,655 | −0.128 | −0.167 | +0.039 | +1.95 |
| 4h/15m fx crosses | key level | 1 | 1,049 | −0.043 | −0.079 | +0.036 | +1.12 |
| 4h/15m metals | key level | 1 | 350 | −0.051 | −0.120 | +0.069 | +1.10 |
| 4h/15m metals | sweep | 1 | 484 | −0.017 | −0.120 | +0.103 | +1.03 |

## The one arm that looked real, and what the walk did to it

**Internal-range liquidity - the three-bar imbalance - is the trap worth
recording.** On 1d/4h fx majors it reads a gross expectancy of **+0.309R at 2R
with a `z` of +4.44**, and +0.336R at 3R. Taken alone that is a strong result on
479 setups.

The same filter on a matched walk returns **+0.432R**.

| | 1R | 2R | 3R |
|---|---:|---:|---:|
| real | +0.065 | +0.309 | +0.336 |
| walk | +0.145 | **+0.432** | +0.409 |
| vs walk | −0.080 | **−0.123** | −0.073 |

Across all 33 imbalance cells, `gross − walk` is **negative in 32**. The filter
produces positive expectancy by **selecting the fill**: requiring a gap means
the trade only triggers if price retraces into the zone, which conditions on a
retracement having happened and then collects the continuation. A walk does
that at least as well.

A `z` of +4.44 against zero and −0.123 against the walk is the same number
read two ways, and only one of them is a claim about markets.

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
