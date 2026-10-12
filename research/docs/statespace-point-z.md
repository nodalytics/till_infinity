# Point Z: the criteria are anti-predictive, on every cell

`statespace-displacement-sequences.md` left this as the last untested item in
the reversal family, and said why: Point Z's depth constraint rests on **the
same 0.86 that measured at 0.99**, so the threshold had to be swept, and *a
lone threshold that works at one value and nowhere else is a fit rather than a
finding*.

Swept, it is worse than a fit. The two structural criteria are **anti-
predictive at up to 7.8 sigma, on all 38 cells, with no exceptions** - and the
same is true on markets whose generator is known, so it is a property of the
definition rather than of any market.

The harness is `research/ideas/point_z.py`.

## The claim

Point Z is where a downtrend reverses, valid only if all three hold:

1. **Three consecutive lower lows** - `Low[t] < Low[t-1] < Low[t-2] < Low[t-3]`,
   "confirming a genuine downtrend, not noise".
2. **At least two buyer interventions** - two local maxima between the first
   and last of those lows, read as failed rally attempts.
3. **A depth constraint** - `Z < 0.86 (H - L) + L`, where `H` and `L` bound
   the previous uptrend, because "a reversal is only valid if the correction
   has exceeded the typical 86% retracement".

The success condition is the claim's own: does the **next peak exceed the
prior high**? That is what "a downtrend reverses into an uptrend" means
structurally, and it is not the same as price being up in twenty bars.

**It is tested on both sides.** The paper states it for a downtrend reversing
up, and the mirror is the same claim turned over - three consecutive higher
highs, two local minima between them, a rise exceeding the prior downtrend.
Running both separates two explanations that look identical on one side: if
the criteria fail because they select for continuation they must fail on both,
and if they fail only on troughs the effect is these series' upward drift.

**And `0.86` is not the depth.** `Z < 0.86 (H - L) + L` puts Point Z below 86%
of the way up the prior move, which is a retracement of **more than 0.14**.
The first version of this harness swept 0.50 to 1.20 and therefore never
tested the value it was replicating - reading the constraint as a depth of
0.86 inverted it, and the grid started three times above the paper's own
threshold. The sweep now covers `0.05` to `1.10`, and the adaptive schemes are
clamped to `[0, 1]`, which is the domain of a retracement fraction.

## Criterion 3 does nothing at all

Median share of candidates whose next peak reclaimed the prior high, by depth
threshold, pooled over instruments, frames and detector spans:

| arm | cells | 0.50 | 0.70 | **0.85** | 1.00 | 1.10 | 1.20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **traded, market** | 32 | 0.31 | 0.31 | **0.31** | 0.31 | 0.30 | 0.28 |
| traded, matched walk | 32 | 0.34 | 0.34 | **0.34** | 0.34 | 0.33 | 0.31 |
| generated, market | 16 | 0.33 | 0.33 | **0.33** | 0.33 | 0.30 | 0.27 |
| generated, matched walk | 16 | 0.35 | 0.35 | **0.35** | 0.35 | 0.31 | 0.28 |

**Flat to two decimal places from 0.50 to 1.00.** And swept over the whole
`[0, 1]` domain - which the corrected run does - it is worse than decoration:
**the paper's own threshold of 0.14 filters nothing at all.**

| traded, median over 48 cells | value |
| --- | ---: |
| no depth filter at all | **0.320** |
| **the paper's threshold, depth > 0.14** | **0.320** |
| the best fixed threshold **in hindsight**, over all of `[0, 1.1]` | **0.320** |

Identical to three decimal places. Almost every candidate already retraces
more than 14% - the earlier displacement work measured the typical retracement
at 0.99 - so the criterion is **vacuous in its own domain** rather than merely
uninformative. There is nothing for a threshold to select. The slight decline past 1.0 is arithmetic rather than
structure - a retracement deeper than the whole prior move leaves the prior
high further away, so reclaiming it is mechanically harder.

**And the market is worse than its own walk at every threshold** - 0.31
against 0.34. The walk is built from the same bar geometry: Gaussian
increments at the series' own standard deviation, with each bar's high-low
reach reused as a fraction of its close, so the detector sees bars of the same
shape and the comparison is of ordering rather than of geometry. Without that
the walk's nodes would be found at a different rate and every count would
differ for the wrong reason.

The sweep deliberately ran past 1.0, because a "retracement" deeper than the
move it retraces is a break rather than a pullback and nothing said the useful
boundary was inside the original range. It was not outside it either.

## Criteria 1 and 2 make it worse, everywhere

Every candidate trough against the subset that satisfies both structural
criteria, with random selection of the same size as the duty-cycle control:

| | frame | span | all | all reclaimed | strict | **strict reclaimed** | random | **z** |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| USDCHF | 4h | 3 | 3713 | 0.494 | 382 | **0.306** | 0.495 | **-7.80** |
| XAGUSD | 4h | 3 | 1819 | 0.488 | 176 | **0.267** | 0.489 | **-6.52** |
| XAGUSD | 1h | 3 | 3649 | 0.505 | 301 | **0.322** | 0.501 | **-6.26** |
| ETHUSD | 1h | 3 | 3988 | 0.471 | 261 | **0.295** | 0.471 | **-6.00** |
| USDJPY | 4h | 3 | 3562 | 0.489 | 291 | **0.333** | 0.490 | **-5.67** |
| BTCUSD | 1h | 3 | 4015 | 0.465 | 291 | **0.306** | 0.466 | **-5.70** |
| XAUUSD | 1h | 3 | 3682 | 0.506 | 257 | **0.362** | 0.506 | **-4.77** |
| ETHUSD | 4h | 8 | 643 | 0.459 | 26 | **0.192** | 0.465 | **-2.77** |

**`z` is negative on all 38 cells**, from -1.16 to -7.80. Any trough reclaims
the prior high about 48% of the time; a trough that satisfies Point Z's
structural criteria does so about 31% of the time; a random subset of the same
size gives 48%, so it is not the duty cycle.

### The mechanism, and it is the paper's own reasoning run backwards

Criterion 1 is a *definition of a strong downtrend*. The paper says so - it is
there to confirm "a genuine downtrend, not noise" - and that reading is
correct. What does not follow is the next step: that a confirmed downtrend is
therefore **more** likely to reverse. The criteria select for trend
continuation and then bet on reversal.

There is a second, purely arithmetic contribution. Selecting a trough at the
end of a monotone run of lower troughs selects a trough whose prior high is
*far away by construction*, and a far-away high is harder to reclaim. That is
the same failure mode the rest of this family had, named in
`statespace-displacement-sequences.md`: these quantities are **arithmetic
rearrangements of an alternating sequence produced by a thresholded detector**,
and such a sequence has strong structure of its own.

### The generated markets settle which it is

| | frame | span | all reclaimed | strict reclaimed | z |
| --- | --- | ---: | ---: | ---: | ---: |
| `Step_Index` | 1h | 3 | 0.487 | 0.321 | **-7.59** |
| `Volatility_75_Index` | 1h | 3 | 0.488 | 0.346 | **-6.97** |
| `Volatility_25_Index` | 1h | 3 | 0.504 | 0.349 | **-6.95** |
| `Drift_Switch_Index_20` | 1h | 3 | 0.495 | 0.332 | **-6.29** |

`Volatility_*` has no structure to find and `Step_Index` is a near-constant
step, and both lose as much as any traded market. So the effect is **not a
market property** - it is what the definition does to any series the detector
is run over. `Drift_Switch_Index_20`, which has a genuinely switching drift,
loses just the same, so it is not reading drift either.

## One thing the harness measures that is not an edge

The `move` column - trough to next peak - is **positive by construction**: a
peak that follows a trough is higher than the trough. So the 4.7 to 7.0
spreads it reports for the metals and crypto are the size of an up-leg that
was identified after the fact, not a tradeable edge, and the healthy-looking
numbers there mean nothing. Only `reclaimed` carries information, and it is
the column that is negative.

Said here because the column is in the output and would otherwise read as a
result.

## What is left of the reversal family

Nothing. This was the last untested item, and it joins the rest:

| claim | reduced to |
| --- | --- |
| displacement ratios | the pivot detector's own alternation |
| the symmetry index | the arithmetic of a ratio of consecutive terms |
| the level magnet | volatility clustering |
| signed peak-to-peak distance | matched a random walk's spread |
| higher-high-with-higher-low | +0.151 against a walk's +0.158 |
| **Point Z's three criteria** | **selecting for continuation, then betting on reversal** |

The reusable part is the instruction already written at the end of the
displacement work and now paid for a sixth time: **null the next one against a
walk run through the same detector before reasoning about it.** The walk has to
go through the *same* detector with the *same* bar geometry, or the comparison
is of two different pipelines rather than of two different orderings.

## The mirror: both sides fail, equally

The claim is stated for a downtrend and applies to both. Tested on both, with
`z` the strict subset's distance from random selection of the same size:

| | cells | median `z` | worst cell |
| --- | ---: | ---: | ---: |
| traded, trough (the paper's case) | 48 | **-5.23** | -2.35 |
| traded, **peak (the mirror)** | 48 | **-4.63** | -0.55 |
| generated, trough | 24 | -5.11 | -1.08 |
| generated, peak | 23 | -4.73 | -1.46 |

**143 cells, every one negative.** The symmetry is the point: an effect that
appeared only on troughs would be these series' upward drift, and one that
appears equally on both is the **definition**. Testing the mirror made the
result stronger, not weaker.

### And the Bill Williams fractal is the worst detector

| detector reach | cells | median `z` |
| ---: | ---: | ---: |
| **span 2 - the literal Bill Williams fractal** | 32 | **-6.42** |
| span 3 | 32 | -5.36 |
| span 8 | 32 | -3.50 |

A fractal is an extreme with two lower highs on each side, which is exactly
`span = 2`, so the question of whether the detector choice was what killed
this is answered rather than assumed: the finest detector is the most
anti-predictive, and the effect weakens monotonically as the detector
coarsens. That gradient is itself diagnostic - it scales with **how many nodes
the detector produces**, which is a property of the detector, not the market.

## A self-correcting threshold cannot rescue it

The static sweep rules out any *fixed* cut-point, because the hit rate is flat
across the grid, but not one that **moves**. Three ways it could move, all
strictly causal and all clamped to `[0, 1]`:

| traded, median over 48 cells | hit rate |
| --- | ---: |
| no filter | 0.320 |
| the paper's 0.14 | 0.320 |
| best fixed, in hindsight | 0.320 |
| **`feedback`** - the paper's own loop, raise after a failure and lower after a success | **0.320** |
| **`volatility`** - the cut scaled by recent realised range | **0.320** |
| **`bandit`** - upper-confidence-bound over eight depth bands, learning which depth wins | **0.300** |

A rolling quantile is deliberately **not** among them: a quantile tracks how
deep retracements currently are, which is a statement about the depth
distribution and not about which depths work.

`feedback` and `volatility` come out identical to no filter because 0.14
already takes everything, so there is nothing for them to move away from.
**`bandit` is the only scheme that genuinely learns, and what it learns is
instructive**: it converges on the **lowest** depth band, `0.00-0.14` - that
is, on taking every candidate - which is the direction opposite to the claim.
It still scores below no-filter, because the candidates it spent exploring
were not free.

So the answer to "the 0.86 is meant to be dynamic" is that a dynamic version
is measurable, was measured, and has nothing to be dynamic about.

## Fractals: the one gradient, and the walk has it too

If a reversal pattern reads anything, it should read **anti-persistence**.
`H < 0.5` means a move is more likely undone than continued, which is the
regime the pattern wants. Local `H` by aggregated variance over the 128 bars
ending at each candidate - causal, nothing after it - split into terciles:

| | cells | median low-`H` minus high-`H` hit rate | share positive |
| --- | ---: | ---: | ---: |
| market | 40 | **+0.054** | 0.82 |
| **matched walk** | 40 | **+0.040** | **0.95** |

The gradient is real: reversals do work about five points better in the
lowest-`H` third. **And the walk reproduces three quarters of it with a higher
share positive** - 0.95 against 0.82 - on a process whose `H` is 0.5 by
construction, so every bit of its measured variation is estimation noise.

The mechanism is the same arithmetic for the fourth time in this harness. A
short window's estimated `H` is low precisely when that window happened to
mean-revert, and a window that mean-reverted left its prior high **close by**,
so reclaiming it is mechanically easier. The gate is reading the target's
distance, not the market's memory.

## What the two corrections changed

Both were right and both made the result sharper rather than softer.

- **Testing the mirror** turned a one-sided null into a symmetric one, which
  promotes the explanation from "a directional bias in these series" to "a
  property of the definition".
- **Reading the threshold correctly** turned "flat across the range I swept"
  into "**vacuous in its own domain**" - and exposed that my first sweep began
  at 0.50 when the value under test was 0.14.

Neither changed the verdict, and that is worth stating plainly: a claim that
survives neither its own threshold, nor a learned one, nor its mirror, nor a
finer detector, nor conditioning on persistence, has been given five chances.
