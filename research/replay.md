# What the stop and target are worth, over 49,338 touches

Sixteen live trades across four strategies is about four labels each. That is
not enough to say anything about any of them, and nowhere near enough to fit a
rule that picks a strategy for a regime. So the labels were manufactured
instead: a level strategy is a deterministic function of the call plus a stop
and a target, every resolved touch already records what happened afterwards,
and replaying the rules over them takes the sample from seventeen to tens of
thousands without trading anything.

`research/harness/replay.py`, run against the production journal on
2026-08-27.

## The result

Mean R by regime, with the target held at 1.5x the stop:

| stop | quiet | normal | busy | wild | all |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.5 | +0.905 | +0.928 | +0.871 | +0.870 | **+0.898** |
| 1.0 | +0.824 | +0.824 | +0.732 | +0.748 | **+0.792** |
| 1.5 | +0.523 | +0.418 | +0.347 | +0.344 | +0.427 |
| 2.0 | +0.350 | +0.208 | +0.142 | +0.175 | +0.239 |
| 3.0 | +0.175 | -0.015 | -0.035 | -0.020 | +0.047 |
| 4.0 | +0.063 | -0.039 | -0.048 | -0.036 | -0.004 |
| 5.0 | -0.003 | -0.027 | -0.034 | -0.027 | -0.020 |

(17k quiet, 12k normal, 8k busy, 10k wild.)

**Tighter stops are monotonically better, in every regime.** Going from 1.0 to
3.0 - which production ran for about two hours on 2026-08-27 - costs roughly
three quarters of a unit of mean R.

## Why, and why it does not contradict the excursion measurement

Both measurements are right and the reconciliation is the useful part.

`excursion_vol` has a **median of 0.00**: most touches never go through the
level at all, and 34,123 of the 49,338 resolve as clean rejects. A stop placed
*at the level* is therefore rarely reached, while a modest target often is.
Widening the stop widens the target with it, and the push distribution does not
scale to follow - a 4.5v target is rarely reached where a 0.75v one usually is.

The earlier reading of the same field - p75 1.64v and p90 3.68v on 1m - was not
wrong, it was conditional. Those are the percentiles *of the touches that went
anywhere*, and they were used to argue for a stop that survives them. What that
argument missed is that surviving them costs more in unreached targets than it
saves in avoided stops.

**The replay assumes entry at the level. Production does not.** Entry is a
market order and lands wherever price is when the call arrives, routinely more
than a volatility unit past the level, while `excursion_vol` is measured from
the level. That gap is the actual problem: the stop is anchored to the level,
the entry is not, and the distance between them is noise the trade has to
survive before its thesis is even tested.

## What it changed

* **The stop scaling was reverted.** `TRADING_STOP_HOLD_SCALING` back to 0.
  It was switched on that morning on the strength of the excursion percentiles
  and an argument about square-root-of-time scaling, and this measurement says
  it costs about 0.75R of mean.
* **The pullback matters more than it was given credit for.** Waiting for price
  to come back to the level is what makes the replay's geometry the real one,
  rather than an assumption the live path violates.
* **The chase gate is doing the right job.** It refuses precisely the entries
  the replay cannot model - the ones already past the level.

## Not every instrument suits this model

The same replay, split by instrument, at a 1.0v stop:

| tier | instruments | mean R | rejects |
| --- | --- | ---: | ---: |
| strong | sol +1.06, gbpjpy +0.99, btc +0.99, eurchf +0.84, us100 +0.83, usdcnh +0.82 | +0.8 to +1.1 | 65-81% |
| middling | eurgbp, eth, spx500, gbpusd, usdcad, chfjpy | +0.68 to +0.80 | 60-75% |
| weak | audjpy +0.53, audusd +0.56, nzdusd +0.56, eurusd +0.57, usdjpy +0.60, gold +0.61 | +0.53 to +0.61 | 56-61% |

Roughly a factor of two between the ends, and **the dollar majors are the worst
of it - with gold near the bottom**, which is uncomfortable given gold is the
instrument this has traded most.

The mechanism is in the last column: **reject rate tracks the return almost
exactly.** sol and btc reject 79-81% of touches, nzdusd and usdjpy 56-58%.
Levels hold better on crypto and the crosses than on the majors, which is what
you would expect of the most arbitraged instruments on the book - there, a
level is more often just a price.

Two readings worth keeping:

**The indices tolerate a wide stop and nothing else does.** At a 2.0v stop
spx500 holds +0.442 and us100 +0.377 while everything else collapses toward
zero. That is the one place the stop-widening argument survives, and it
suggests the right stop is per-instrument rather than global.

**This is the level-holding family only.** `fade-to-value` needs the valuation
and `approach-scalp` needs the next level in the book, neither of which is on a
resolution, so this says nothing about either - and `fade-to-value` is first in
the running order.

Not acted on. The instrument is only on a resolution from 2026-08-27, so this
was recovered from the tags of data gathered to answer a different question,
and eight of the weak-tier instruments had been trading for less than a day
when it was measured. It wants confirming prospectively before the instrument
list is cut.

## On regime

Regime separates, and it is a real effect: quiet outperforms wild at every stop
width. It is also **small next to the stop width**, which dominates it by an
order of magnitude. So a regime-aware strategy chooser is a second-order
refinement on top of entry and stop placement, not the lever - and
[edge.md](../docs/edge.md) is the standing caution about reaching for a
dynamic rule before the constant has been got right.

## Two sides at once loses to one, and not because of the parameters

Proposed: open both directions at the level and profit from whichever moves
further. The account is `RETAIL_HEDGING`, so it is possible - on a netting
account the second order would simply close the first - and it was tested over
54,529 resolutions before anything was built.

**With a fixed target on both sides**, it loses to the one-sided trade
everywhere:

| stop | target | straddle R | one side R |
| ---: | ---: | ---: | ---: |
| 0.5 | 0.75 | +0.038 | **+0.852** |
| 1.0 | 1.50 | -0.026 | **+0.731** |
| 2.0 | 3.00 | -0.370 | **+0.175** |

**Letting the winner run** - the steelman, and where a straddle should earn its
keep - is far better in absolute terms and still never wins:

| stop | straddle, winner runs | one side, runs |
| ---: | ---: | ---: |
| 0.5 | 8.460 | 8.449 |
| 1.0 | 3.618 | **4.089** |
| 2.0 | 1.334 | **2.002** |

### Why, and why no parameter fixes it

In options a straddle works because the premium is **bounded** and the upside is
**convex** - the most that can be lost is what was paid. With stop orders there
is neither. The losing side's stop is a *certainty* rather than a probability,
so a full 1R is paid on every trade before the winner earns anything, and the
winner is capped by its own target unless it is allowed to run - at which point
it is the one-sided trade with a guaranteed loss attached.

At a 0.5v stop the two draw level, because a stop that tight takes both sides
often enough that the structures converge. It is competitive there by being the
same thing.

### The useful thing that fell out of it

The push distribution, over the same resolutions:

    median 2.24v    p75 3.37v    p90 4.93v    p99 9.55v

**Letting the winner run beats a fixed target by a wide margin.** One side at a
0.5v stop scores **+8.4R** running against **+1.7R** with a 1.5x target on the
same stop. The median push is 2.24v and the targets in use are near 1.3v, so
the model is capping its winners at roughly half the move it expects to
happen - which is a larger lever than the two-sided idea it was found while
disproving.

## One threshold, two distributions, and a one-sided book

Twenty-five trades in, the book was **21 sells to 4 buys**. The signals were
not: over 7,498 published level calls `structures` offered 48.1% up and 51.9%
down. The model is not biased about *what* it says. It is more confident when
it says down.

| direction | n | median claimed probability | passes 0.75 | passes 0.85 |
| --- | ---: | ---: | ---: | ---: |
| up | 3,608 | 0.824 | 79.9% | 38.7% |
| down | 3,890 | **0.880** | **95.9%** | **61.5%** |

A single absolute floor on two distributions that sit in different places
admits the weakest fifth of one direction and the weakest twentieth of the
other. That is the whole mechanism, and it needs no market explanation - the
gate produced the skew on its own.

It also predicts what the outcomes showed: the four buys averaged **-0.69R**
against the sells' -0.09R, which is what happens when one side is admitted
further down its own quality distribution than the other.

### Why a percentile here, having measured three of them losing

`edge.md` found a rolling quantile losing to a matched constant four times out
of four, and a walk-forward adaptive probability floor came out **worse than no
floor at all**. Three nulls is a strong prior against a fourth.

The distinction is the one edge.md draws itself. `edge` was **already
scale-free**, so normalising it per cell destroyed a comparability it had. A
directional probability is *not* comparable across directions - the two groups
demonstrably sit in different places - and a constant that means "the top
fifth" for one means "the top half" for the other. That is the case where a
quantile is the honest form rather than the clever one.

Two properties keep it on the right side of the prior:

* **It cannot see outcomes.** What is tracked is the distribution of what the
  model *says*, never what happened next, so a losing streak cannot tighten it
  and a winning one cannot loosen it. That was precisely the rule that lost to
  having no rule, and there is a test asserting the source contains no
  reference to profit or loss.
* **It can only raise the bar.** The percentile is floored at the absolute
  `min_probability`, so it corrects an asymmetry rather than opening a door
  that was being held shut.

The matched-constant version - two fixed floors, one per direction - is written
down beside it in `floors.by_direction`, because that is the shape the evidence
keeps favouring. The percentile is for when the distributions drift far enough
that a fixed pair stops meaning what it meant.

Deployed at 0.3, which keeps the top 70% of each direction and equalises by
**tightening the over-represented side** rather than loosening the other.

## Edge is a good floor and a bad ranking

Nineteen closed trades, scored against what the gates would have kept. The
sample is small and the story is coherent across three independent cuts, which
is worth more than any one of them.

| group | n | edge | probability | base (directional) | mean R |
| --- | ---: | ---: | ---: | ---: | ---: |
| winners | 6 | 0.240 | 0.838 | 0.579 | +1.48 |
| losers | 13 | **0.276** | 0.816 | 0.549 | -1.00 |

**The winners have the smaller edge.** Sorting by edge puts the losers on top:

| gate | taken | won | mean R | total R |
| --- | ---: | ---: | ---: | ---: |
| everything | 19 | 6 | -0.21 | -4.07 |
| probability >= 0.85 | 9 | 5 | +0.41 | **+3.72** |
| base(dir) >= 0.55 | 11 | 5 | +0.24 | +2.67 |
| base(dir) <= 0.55 | 8 | 1 | -0.84 | **-6.74** |
| edge >= 0.25 | 12 | 3 | -0.48 | -5.74 |
| edge >= 0.30 | 4 | 0 | -1.02 | -4.09 |

### Why this is consistent rather than contradictory

`edge = probability - base_rate`. Wanting a **high conditional** and a **high
baseline** means wanting their *difference* to be small - so a large edge is,
by construction, a large departure from a weak baseline. That is the worse
trade, and it is exactly what an edge ranking selects for.

None of this touches [edge.md](../docs/edge.md), which measured edge as a
**floor**: below roughly 0.10 the mean realised push is zero, located twice at
0.0968 and 0.11 over 10,483 calls. That finding stands and the floor stays.
What this adds is that above the floor, edge does not rank - and edge.md said
as much in its own words, that the accuracy either side of the step "is not a
number to quote".

So the settled shape is: **edge as an inert floor at the measured step, with
probability and base rate doing the selecting.**

### A reading that was wrong, and how

The first pass compared `base_rate_up` directly and concluded the losers had
the *lower* base rates. `base_rate_up` is always the **up** rate, and the
sample was fifteen sells against four buys, so the raw average described the
direction mix rather than the levels. Read in the direction actually claimed
it reverses: winners 0.579, losers 0.549. The flip has a test of its own
because the mistake is silent - the number looks perfectly reasonable either
way.

### Adaptive thresholds were tested and lost

Walk-forward, each rule using only trades already closed when it decided:

| rule | taken | won | mean R | total R |
| --- | ---: | ---: | ---: | ---: |
| no floor | 19 | 6 | -0.21 | -4.07 |
| fixed 0.85 | 9 | 5 | +0.41 | +3.72 |
| adaptive +/-0.02 per trade | 14 | 4 | -0.31 | **-4.29** |
| adaptive +/-0.05 | 12 | 4 | -0.19 | -2.28 |
| track winners' median probability | 13 | 5 | +0.05 | +0.59 |

**The step-adaptive rule is worse than no floor at all.** Raising the bar after
a loss and lowering it after a win tightens right after the market punishes you
and loosens right after it rewards you, which is backwards unless outcomes are
serially correlated, and nothing here says they are.

This is the third time this repository has measured a dynamic rule losing to a
constant, for the same reason each time: the dynamic version estimates its
parameter from noisy data and inherits the noise.

### What is actually deployed

`min_probability` at **0.75**, not the 0.85 optimum. 0.85 was chosen by looking
at the outcomes it would be scored on, on nineteen trades, and 0.90 already
reverses the pattern - so it is the optimum of a small sample rather than a
number. 0.75 refuses only the weak tail and cannot be overfitted to nineteen
trades. `min_base_rate` at 0.55. Both off by default in the library: nineteen
trades is a hypothesis, and the code should not assert it.

## Half the stopped trades were right

`research/harness/shadows.py`, run against the production journal and price
store on 2026-08-27. Every losing trade, followed forward through recorded
prices to ask whether the target it was aiming at arrived after the stop.

| when | feed | strategy | verdict | best R |
| --- | --- | --- | --- | ---: |
| 12:51 | gold | - | **would have won** | +25.65 |
| 19:38 | us30 | sweep-aware | **would have won** | +17.50 |
| 03:23 | gold | sweep-aware | **would have won** | +13.74 |
| 23:40 | gold | sweep-aware | **would have won** | +13.05 |
| 02:51 | us100 | sweep-aware | **would have won** | +6.52 |
| 01:54 | gold | sweep-aware | **would have won** | +3.70 |
| 14:42 | gold | approach-scalp | still lost | +1.55 |
| 22:18 | gold | sweep-aware | still lost | +1.38 |
| 06:16 | us30 | sweep-aware | still lost | +0.87 |
| 04:29 | silver | fade-to-value | still lost | +0.37 |
| 18:34 | us100 | fade-to-value | still lost | +0.35 |
| 04:36 | us30 | fade-to-value | still lost | -4.84 |

**Six of twelve stopped trades later reached their target**, and not
marginally - between 3.7R and 25.7R after the stop took them out. Of the six
that did not, four still went positive first, and exactly one was wrong from
the start.

So the direction the level model produces is largely right, and the execution
is giving back money the thesis earned. A stop one volatility unit from a fill
that itself sits up to a unit from the level is not protecting the trade; it is
a tollbooth on the way to being right.

### Why this does not contradict the stop replay above

The replay says tighter stops win. This says our stops are too tight. Both are
measurements and both are correct, because they are measuring stops in
different places: the replay places the stop **at the level**, where the median
excursion is zero and a tight stop is rarely reached, and production places it
at the level while the *entry* lands wherever price was when the call arrived.

The distance between the fill and the level is the noise the trade has to
survive before its thesis is tested, and nothing was measuring it. That is the
same conclusion the stop-scaling reversal reached from the other direction, now
with twelve worked examples rather than an argument.

### The worked case

The us30 short at 19:38 filled at 53519 and stopped at 53525. Fourteen minutes
later price ran to 53529.8 - through the stop - and then dropped to 53439,
**eighty points through the entry**. The thesis was right, the stop was six
points away, and the move needed it to survive eleven.

## The side question, and why the journal could not answer it

Six of seven strategies take their side from the direction the call carries.
That is the half of the signal this repository has measured down to nothing
three separate times: a coin flip below the edge step ([edge.md](../docs/edge.md)
§1), 50.7% on sweep direction over 73,000 ranges (`sweeps.py`), and - flattest
of all - **"assume the level holds" beating the published direction at every
gate except the highest**, recorded on `reactions.MIN_EDGE`.

So a side replay was built before any of it was changed. It reported the
approach side predicting the sign of the push at 92% from above and 95% from
below.

**That would be an extraordinary edge, and it contradicts all three
measurements, which is the reason to check it rather than publish it.**
Decomposed within each outcome:

| outcome | from above | from below |
| --- | ---: | ---: |
| reject | 99.9% up | 0.0% up |
| trap | 100.0% up | 0.0% up |
| break | 0.0% up | 100.0% up |
| backcheck | 100.0% up | 0.0% up |

Zero or one hundred at every one of the eight cells. `push_vol` is signed by
`(outcome, approach side)` **by construction** - a reject from above pushes up
because that is what a reject from above *is*. The 92% is a definition
restated.

So the `hold` rule scoring 93.9% is re-deriving the outcome rather than
predicting it, and **no rule for choosing a side can be scored against
`push_vol` at all**. Had the code been written first, a side rule would have
shipped on a tautology and looked like it worked.

The stop replay above is unaffected: it scores on `abs(push) >= target` and
never touches the sign.

### What was added because of it

`Touch.path` - where price actually was at fixed offsets after first contact,
in volatility units, signed. Sampled at 60, 300, 900, 1800 and 3600 seconds,
written once per offset and never revised, and absent rather than zero when no
quote lands on one.

Wall clock rather than bars, so a 1m touch and a 1h touch are comparable at the
same horizon - "which way had it gone after five minutes" means the same thing
on both, where "after five bars" does not. It stops at an hour because that is
`Tracker`'s own horizon, past which a touch is discarded rather than resolved.

The path knows nothing about rejects, traps or breaks. It is the only thing
recorded here that a side rule can honestly be tested against, and it needs a
few days of accumulation before it can be.

## What this cannot say

Spread and slippage are not recorded on a resolution, so this scores the thesis
and not the execution - and the live trades suggest execution is where a good
deal of the loss lives. `approach-scalp` needs the next level in the book and
`fade-to-value` needs the valuation, neither of which is on the resolution, so
only the level-holding family replays.

And one compromise is built into the scoring: when both the stop and the target
were reached, the record cannot say which came first, so it counts as a stop.
That biases every number here downward, which is the direction a bias should
point when the alternative is flattering a rule you are about to trade.

## Does signal strength deserve a gate?

`strength` reaches the Telegram alerts and sits on every recorded touch, which
makes it read like a decision input. It is not one. The gate chain in
`LevelStrategy.quality` runs probability, then edge, then base rate, and never
looks at it; its only route into a trade is as one of the features `facto`
learns from, diluted there with everything else. Whether that omission is a gap
or a correct call is measurable, and `research/harness/strength.py` measures it
against 54,547 resolutions.

**It barely varies.** The median touch scores 0.943 and p75 is 0.987, so 68% of
everything lands in the top bucket. A gate on a feature that is near-constant
refuses almost nothing or almost everything, with little in between.

**Raw, it looks mildly useful** - 0.947 mean R in the top bucket against 0.799
in the one below it, at a 0.5v stop. That reading does not survive a control:

| probability | strength 0.2-0.4 | 0.4-0.6 | 0.6-0.8 | 0.8+ |
| --- | ---: | ---: | ---: | ---: |
| 0.50-0.60 | 1.050 | 1.018 | 1.083 | 0.936 |
| 0.60-0.70 | 1.016 | 1.075 | 0.927 | **0.771** |
| 0.70-0.80 | 0.886 | 0.992 | 1.025 | 0.883 |
| 0.80-1.00 | - | 1.030 | 0.996 | 0.919 |

**Inside a single probability band the relationship inverts.** The strongest
bucket is the *worst* one in four bands out of five. The raw appearance of an
edge is confounding: strength correlates with probability, probability is
already gated, and once it is held fixed what strength adds is negative.

So a `min_strength` floor would refuse the trades that do slightly better and
keep the ones that do slightly worse. **Strength stays out of the gate chain**,
and the reason is now recorded rather than incidental.

The inversion has a plausible mechanism worth stating but not claiming: a
high-strength level is an *obvious* one, obvious levels are crowded, and crowded
levels are what gets swept - which is the premise `sweep-aware` already trades.
This measurement is consistent with that story and does not establish it.

One caveat on the table above. The 0.20-0.40 bucket carries a mean absolute
push of 43v against 2-3v everywhere else, which is not a real feature of that
bucket but a handful of contaminated push values sitting in a small sample.
It does not touch the within-band conclusion, which is computed on R - where
the stop and target bound every trade's contribution - rather than on push.

## Do the probability, base-rate and edge gates separate anything?

Each of them refuses trades and each is defended by an argument rather than a
measurement. `research/harness/gates.py` asks the only question that matters:
do trades above the floor do better than trades below it? A gate that does not
separate is not neutral - it costs every trade it refuses and returns nothing.

Mean R at a 0.5v stop, by decile of each quantity, over the 4,378 resolutions
carrying these fields (8% of 54,547 - the rest predate them, and that is the
main limit on what follows).

| decile | probability | base rate | edge |
| --- | ---: | ---: | ---: |
| 1 (lowest) | 0.978 | 0.913 | 1.024 |
| 5 | 0.978 | 1.021 | 1.041 |
| 9 | 0.957 | **0.848** | 0.904 |
| 10 (highest) | **0.913** | **1.130** | 0.901 |
| spread | 0.090 | 0.283 | 0.153 |

**Probability does not separate outcomes, and slopes slightly the wrong way.**
The lowest decile returns 0.978 and the highest 0.913, across a spread of 0.090
that is indistinguishable from noise. The floor at 0.75 is refusing trades for
a number that does not predict what it is being asked to predict. This is the
second time this has shown up - the strength measurement above found the same
flatness once probability was held fixed, from the other direction.

**Edge is the same, and worse-founded.** 1.024 at the bottom against 0.901 at
the top. Its live floor was already inert, sitting at or below the structures
threshold that produced the number, which the service warns about on every
start.

**Base rate is the one with something in it, and the live floor was in the
wrong place.** The top decile - base rate above 0.563 - returns 1.130 against
roughly 0.95 everywhere else, the only band in any of these columns that
stands out. But the ninth decile, 0.519 to 0.563, is the *worst* cell in the
table at 0.848, and the floor was set at 0.51. It was admitting the single
worst decile and calling that a filter. A base-rate floor is worth having at
0.56 and worth nothing at 0.51.

What this does not say: these are touch resolutions under a fixed stop-and-
target rule, not the trades this book actually took, and 8% coverage is thin.
It is enough to conclude that two of these three floors are not earning their
refusals; it is not enough to conclude that probability is *anti*-predictive,
and the slight negative slopes should not be traded on.


### Correction, same day: the base-rate result above was on the wrong quantity

The table above buckets **raw `base_rate_up`**. The gate does not compare that
number - `LevelStrategy.quality` uses `base_up` for a buy and `1 - base_up` for
a sell - so a raw 0.60 is a strong buy and a weak sell, and pooling them
measures neither.

Acting on it raised the floor from 0.51 to 0.56, which **refused 99 signals out
of 99** and stopped trading entirely.

Turned to face the trade, the standout decile is not standout, and the column
is not monotonic:

| decile | base rate (facing) | mean R |
| --- | --- | ---: |
| 1 | 0.214-0.381 | 0.900 |
| 2-4 | 0.382-0.480 | ~0.99 |
| 5-7 | 0.480-0.558 | 0.879-0.941 |
| 8-10 | 0.558-0.810 | ~1.00 |

Deciles 2 to 4 sit *below* an even chance and return about 0.99, better than
deciles 5 to 7 above them. A floor in the middle removes good trades and keeps
worse ones, and 0.51 sat exactly there. Spread across all ten deciles is 0.130
on 437 per cell, which is around two standard errors - thin ground for
refusing anything.

So the base-rate floor is off as well, and the honest summary of all three
gates is that none of them earns its refusals.

This is the second time raw versus direction-adjusted `base_rate_up` has
produced a confident, backwards reading here. The adjustment now lives in
`gates._facing` with the reasoning attached.

## Can momentum choose which of the two directional bets to take?

Every scalping strategy here is one of two wagers. `level-scalp` and its
refinements bet the level **holds**; `inverse` bets it **fails**. Nothing chose
between them - `inverse` runs as a control precisely because the choice had
never been made on evidence. The proposal: momentum makes it. Price drifting
into a level is a level being tested; price *running* into one is a move in
progress and more likely to go through.

`research/harness/regime.py` tests it against 54,547 resolutions, using
`approach_vol` - how far price ran on its way in.

| approach (v) | n | break share | R with the level |
| --- | ---: | ---: | ---: |
| 0.00-0.15 | 5,454 | 8.2% | 0.861 |
| 0.78-1.00 | 5,454 | 8.0% | 0.943 |
| 1.61-2.09 | 5,454 | 6.3% | 0.946 |
| 2.09-3.04 | 5,454 | 6.6% | 0.865 |
| 3.04-40.76 | 5,461 | **4.5%** | 0.875 |

**The effect is real and points the other way.** Break share nearly halves
across the range, and it falls monotonically through the top half. A *harder*
run into a level is more likely to be rejected, not less - which is the
opposite of the premise. Read charitably it says a violent approach is
exhaustion, or that the level is where resting interest sits and a fast move
reaches it and bounces; neither reading is established here.

**And the effect is not tradeable as it stands.** R with the level is flat
across every decile - 0.861 to 0.946 with no trend, including in the deciles
where breaks are rarest. The outcome *classes* shift without the money
changing, so even the real relationship does not convert into a better trade
under this stop-and-target rule.

So momentum is not a regime classifier on this evidence, and it does not
select between the two bets. It stays what it was built as: a **timing**
filter, which is a different question and the one the record says was being
got wrong.

### The two bets were never fifty-fifty, which reframes `inverse`

| outcome | share |
| --- | ---: |
| reject | 69.4% |
| trap | 16.7% |
| backcheck | 7.7% |
| break | **5.5%** |

Levels hold about seven times in ten and break about one time in twenty. So
"the level fails" is not the other half of a coin - it is the tail. `inverse`
is therefore not betting on breaks; it is betting the *direction the model
names* is wrong, which is a different claim and one this table cannot settle.

A caveat on all of the above: `approach_vol` is a single-touch measure taken at
the level, where momentum is adverse to the with-level trade by construction.
It is not the accumulator in `structures/cusum.py`, and a momentum measure over
a longer horizon - is this a pullback inside a trend, or a range being tested -
is a different question that this does not answer.

## Pullback inside a trend, or a level inside a range

`regime.py` asked whether momentum *into* a level predicts the level failing,
and found the opposite with no money in it. But that measure is taken over the
approach itself and cannot see the thing the question was about: whether the
market is trending through this area or oscillating inside it. The journal's
own `regime` is no help - it is where *volatility* sits in its recent history,
not direction.

`research/harness/trend.py` builds the missing measure from what is recorded.
Successive `level` prices on one feed trace where price has been, and over a
window of twelve:

    efficiency = |net displacement| / sum of absolute steps

One is a trend, zero is a range. Only resolutions **before** the one being
classified count, which keeps it a prediction rather than a restatement.

| efficiency | n | break share | R with the level |
| --- | ---: | ---: | ---: |
| 0.000-0.000 | 5,414 | 7.8% | 0.876 |
| 0.017-0.096 | 5,414 | 11.3% | 0.807 |
| 0.197-0.329 | 5,414 | 8.6% | 0.843 |
| 0.655-0.985 | 5,414 | 3.2% | 1.049 |
| 0.985-1.000 | 5,417 | **1.4%** | **1.149** |

**The intuition is right and the mechanism is backwards from the obvious one.**
A trend does not run levels over - in the most trending decile only 1.4% of
levels break, against 11.3% in the chop. What a trend does is make the levels
*hold harder and pay more*: 1.149R against 0.807R, a difference of 0.34R
between the extremes.

That is a pullback inside a trend, and it is the best-evidenced setup this
repository has found. For scale, every direction gate measured the same day
spread 0.09 to 0.15 across its whole range and none of it survived contact
with a control. This is 0.34R, monotonic across the top three deciles.

**It holds inside every interval**, which is what rules out a composition
artefact, and it strengthens as the timeframe slows:

| interval | ranging | trending | difference |
| --- | ---: | ---: | ---: |
| 1m | 0.749 | 0.830 | +0.081 |
| 3m | 0.922 | 1.023 | +0.101 |
| 5m | 0.872 | 1.091 | +0.219 |
| 15m | 0.904 | 1.149 | **+0.245** |

Comparing the top three deciles against the bottom three, which is why these
numbers are smaller than the 0.34R above.

What this does not establish: the window of twelve is a guess, the efficiency
ratio is one measure of trend among several, and this is a fixed
stop-and-target rule on touch resolutions rather than the trades the book
took. It is strong enough to build on and not strong enough to trust blind.

## Re-verifying the `reward_to_risk` gate, and softening its own finding

[magnitude.md](magnitude.md) measured on 2026-08-17 that this gate selects
losing trades out of a winning population, and `docs/todo.md` 0f has said
"remove it" since - "ahead of everything else in this file". It is still live,
at 1.0 in structures and 1.2 in trading, and it is the largest single source of
refusals in production. Before removing a live gate on a ten-day-old replay,
`research/harness/rr_gate.py` re-runs the question on different data by a
different method: production signals joined to production outcomes through the
journal's own parent link, no replay and no reconstruction.

**The first cut looked damning and was measuring the wrong thing.** Mean
|push| by rule:

| rule | n | mean push |
| --- | ---: | ---: |
| no gate | 47,676 | 4.869 |
| RR >= 1.2 (live) | 7,255 | 2.679 |
| what it rejects | 40,421 | 5.263 |

Rejected calls move twice as far as kept ones. But **|push| is distance, not
profit** - it counts a large move *against* the trade as a good outcome, and no
gate should be removed on a number that cannot tell those apart.

**In R, the effect is real, monotonic, and much smaller:**

| rule | n | mean R | mean push |
| --- | ---: | ---: | ---: |
| no gate | 47,676 | **0.908** | 4.869 |
| RR >= 1.0 | 8,583 | 0.886 | 2.645 |
| RR >= 1.2 (live) | 7,255 | **0.868** | 2.679 |
| RR >= 2.0 | 4,420 | 0.834 | 2.875 |

At the live threshold it keeps 0.868R and rejects 0.915R. So the original
direction holds - the gate does select worse trades, and monotonically worse as
the threshold rises - but the magnitude is **0.047R**, the same order as the
direction gates removed the same day and called noise.

**The case for removing it is volume, not quality.** It refuses 85% of calls -
40,421 of 47,676 - to gain nothing, and to lose a twentieth of an R. A filter
that discards six trades in seven has to earn that, and this one is slightly
negative before the cost of the trades never taken.

**The stated mechanism did not reproduce.** magnitude.md attributes the effect
to a high ratio being a small `risk_vol` - a tight stop inside the noise - and
predicts the top decile excursing less. It excurses *more*: 0.960v against
0.812v in the bottom decile. The ratio's distribution is also badly behaved,
the bottom decile being all zeros and the top reaching 12,772, so decile
comparisons on it are weak. The effect is confirmed; the explanation is not.

## Taking the other side when risk exceeds the expected push

The proposal: if a call's `risk_vol` is larger than its `expected_push_vol` it
has negative expectancy as modelled, so trade the opposite side.

The arithmetic never carried the argument - a bad expectancy in one direction
is not a good one in the other, because the push estimate belongs to the
direction the model named. The premise needs the model to be *anti-predictive*
on that subset, which is a fact about the data.
`research/harness/inverting.py` tests it over 47,668 resolutions joined to
their signals.

| subset | n | R with | R against |
| --- | ---: | ---: | ---: |
| risk > expected push | 24,831 | 0.864 | **−0.984** |
| risk <= expected push | 22,837 | 0.955 | −0.990 |
| everything | 47,668 | 0.908 | −0.987 |

**Inverting is dead everywhere, not merely unhelpful.** The against-side loses
essentially a full R in every bucket, and the mechanism is plain: levels reject
69% of the time, so price leaves the level in the direction the model named and
the opposite trade is underwater by that distance immediately. It is stopped
almost always.

**The premise behind the idea is right, though, and the with-side shows it:**

| risk / expected push | n | R with |
| --- | ---: | ---: |
| 0.00-0.00 | 5,958 | 0.998 |
| 0.78-1.04 | 5,958 | 0.967 |
| 1.04-1.31 | 5,958 | **1.017** |
| 1.78-3.39 | 5,958 | 0.793 |
| 3.39+ | 5,962 | **0.693** |

Calls whose risk badly exceeds the expected push do perform worse - 0.693
against ~0.98 - a 0.3R spread, second only to trend context among everything
measured here.

**So the remedy is refusing those trades, not reversing them - and this is the
`reward_to_risk` gate again.** The ratio is exactly `1 / reward_to_risk`, and
the numbers say the gate was set about twice too tight rather than being wrong
in principle. Damage starts near ratio 1.8, which is RR 0.55. The 1.2 floor
that was live corresponds to ratio 0.83 and cut through the best region: the
0.78-1.04 and 1.04-1.31 buckets return 0.967 and 1.017.

That is a correction to the removal recorded above. Taking the floor off was
right for 1.2 and overshot; a floor near 0.5-0.55 refuses the bad tail and
keeps everything 1.2 was discarding.

A limit on the mirror scoring: it ignores ordering. A touch that ran 2v against
before going 3v in favour scores the same as one that did the reverse, and
those are different trades - one is stopped and one is not. It is optimistic
about both sides equally, which keeps the comparison fair without either
number being a P&L.

### The three-way rule, scored as a policy

Push above risk take the model's side, push below risk take the other, push
about equal stay out. Scored over the same 47,668 resolutions, against the
alternatives it should be compared with. **Total R rather than mean, because a
policy that trades less can win on the mean and still make less money.**

| policy | trades | mean R | total R |
| --- | ---: | ---: | ---: |
| always with the model | 47,668 | 0.908 | **43,284** |
| the three-way rule as proposed | 42,756 | −0.056 | **−2,402** |
| with, skip when risk > push | 22,836 | 0.955 | 21,818 |
| with, skip only the bad tail (RR<0.55) | 35,893 | **0.963** | 34,550 |
| with, skip the ambiguous band only | 42,756 | 0.896 | 38,290 |

**The three-way rule turns a winning population into a losing one** - +43,284R
becomes −2,402R. Half its trades are inversions and each loses about a full R,
which swamps whatever the selection gains.

**And no filter beats taking everything.** The bad-tail filter has the best
mean R of any policy here, 0.963 against 0.908, and still makes less in total
because it declines a quarter of the trades. That reverses the recommendation
recorded above: a floor at 0.55 is defensible on trade quality and costs money
on the account, and this book is signal-constrained rather than slot-
constrained - it took 40 trades in a day against a `max_positions` that never
binds. Filtering only pays when the slots are scarce.

### The number that should worry us more than any of this

Every row above is positive. The with-the-model trade returns **+0.908R** at a
0.5v stop across 47,668 resolutions, and the live account is losing roughly
0.5R per trade. The replay's edge has never once been realised.

That gap is execution - the 1.09R stop cost, the spread, and the distance
between a 0.5v/0.75v rule on paper and what the strategies actually place - and
it is larger than every gate, filter and side-selection question on this page
put together. No amount of choosing better calls fixes it.

## Locating the execution gap

The replay says +0.908R per touch; the live account loses roughly 0.5R per
trade. `research/harness/settings_grid.py` takes that apart.

**First, the quoted number was for a trade we do not place.** Every positive
figure in this file was measured at a 0.5v stop and 0.75v target. Production
places a median **1.05v stop and 2.53v target** - twice the stop and three
times the target. Scored at what we actually place:

| stop \ target | 0.75v | 1.50v | 2.53v | 5.00v |
| --- | ---: | ---: | ---: | ---: |
| 0.50v | 0.902 | **1.785** | 1.567 | 0.445 |
| 1.00v | 0.340 | 0.781 | 0.672 | 0.111 |
| **1.05v (live)** | 0.313 | 0.734 | **0.630** | 0.096 |
| 2.00v | 0.127 | 0.346 | 0.290 | 0.004 |

So the honest replay figure for our configuration is **+0.630R**, not +0.908R.
Quoting the tighter pair as evidence for the wider one was wrong and is
corrected everywhere above by this section.

**Second, the hold is not the explanation.** 97.7% of touches resolve inside
`max_hold` and 99% inside the scalper hold, so trades being cut off before
they resolve accounts for almost nothing. Only `snap`, at 120 seconds, misses
a real share - 28%.

**Third, what remains.** +0.630R against roughly −0.5R realised is still a gap
of over 1R, and the candidates in order of size are: the gate stack that
selected those 40 trades - `reward_to_risk` at 1.2 selects worse calls, and
probability, edge and base rate were measured flat - plus a 1.09R stop cost,
the spread, and a 40-trade sample whose error bars are wide. **The
configuration that produced those trades no longer exists**, which makes the
gap real but not currently measurable against anything.

### The parameter finding, and why it is not a free 2.8x

The grid's best cell is a **0.5v stop with a 1.5v target at +1.785R**, against
+0.630R for what we place. That is the largest single number on this page.

It cannot be taken at face value, and the reason is in this repository
already. `min_stop_vol` exists because a stop inside one volatility unit sits
inside the width of the estimate it protects and is taken by ordinary
movement - with two live trades cited for it. Both things are true because
they measure from different places: **the replay measures from the level, and
we do not enter at the level.** A 0.5v stop from the level is a real stop; a
0.5v stop from a fill already 0.3v past it is 0.2v of room and dies to noise.

So the tighter stop is worth what the entry is worth. With
`pullback_fraction` at 1.0 the entry waits for the level, which is exactly the
condition under which the grid's number applies - and that is the argument for
tightening, rather than the grid alone.

## Is momentum predictable, the way volatility is?

The question decides how much apparatus momentum deserves. Volatility being
persistent is why `garch`, `har`, `ranges` and `consensus_vol` exist. If
direction persisted the same way it would warrant the same treatment - its own
estimators, its own ensemble, arguably its own service. If not, momentum can
only be a filter on a thesis that comes from elsewhere, which is what it is.

Same test for both, over 53,753 resolutions in 56 feed/interval series:
lag-1 autocorrelation.

| measure | series | mean rho | share > 0 |
| --- | ---: | ---: | ---: |
| \|push\| (volatility) | 56 | **+0.159** | 77% |
| level change (momentum) | 55 | **−0.239** | 5% |
| its sign only | 55 | −0.013 | 42% |

**Volatility clusters here as it does everywhere**: +0.159, positive in 77% of
series. That is the persistence the volatility estimators are built on, and it
is real on our own instruments.

**Direction does not persist. It reverses.** The level-to-level change comes
in at −0.239 and is negative in 95% of series - a move one way is followed by
a move back. Strip the magnitude and the sign alone is −0.013, indistinguishable
from a coin.

Read together: the *size* of the next move is forecastable, its *direction*
is not, and what little structure direction has runs against continuation. So
momentum here is mean-reverting at the level-to-level horizon, which is the
same thing the level model already trades - and it is an argument against
building momentum forecasting, not for it.

### The first version of this measured a variable against itself

It used the sign of `push_vol` for direction and found rho **+0.303** - momentum
apparently twice as persistent as volatility. `push_vol` is signed by the
outcome together with the approach side, which is an identity, and consecutive
touches on one level usually share an approach side. The autocorrelation was a
property of the encoding.

That trap is documented earlier in this file and was still walked into. It is
worth stating the general form: **any series whose sign is assigned by the
outcome will autocorrelate whenever the assignment does.** Successive `level`
prices carry no such assignment, which is why they are the series used.

## Can hold time be estimated?

`stop_hold_scaling` widens the stop by the square root of the hold, because
`vol_bps` is one bar of the entry interval and a trade held for many wanders
further than one. It uses the strategy's **configured** hold - 1800 seconds for
the scalpers, 120 for `snap` - which is a constant chosen by hand. The trade
does not care what was configured; it cares how long *this* touch takes.

`research/harness/holding.py`, over 38,244 resolutions in 36 series:

| | |
| --- | ---: |
| p25 | 4s |
| p50 | 61s |
| p75 | 241s |
| p90 | 651s |
| p99 | 3,593s |
| **p25 to p90** | **163x** |

**It varies enormously, so a constant cannot be right for more than a slice of
trades.** And unlike direction, it persists:

| series | lag-1 rho | positive in |
| --- | ---: | ---: |
| raw seconds | +0.173 | 83% |
| log seconds | **+0.269** | 86% |

Measured on the log as well as the raw, because the distribution is
long-tailed enough that a single 3,500-second touch dominates a covariance.

**So hold time behaves like volatility, not like direction.** Set the three
side by side:

| quantity | varies | persists | worth estimating |
| --- | --- | --- | --- |
| volatility | yes | +0.159 | yes, and it has five estimators |
| **hold time** | **163x** | **+0.269** | **yes, and it has none** |
| direction | yes | −0.013 | no |

That is the case for estimating it: the same two properties that justify the
volatility apparatus, on a quantity currently served by a hand-picked
constant - and one that `stop_hold_scaling` already multiplies into every stop
it widens.

A caveat on the structural breakdown. Many outcome rows carry an empty `feed`,
so the per-feed medians pool instruments together and the 2,353x range across
series is not trustworthy. Interval clearly matters; how much is a separate
question this sample cannot answer cleanly.

## Scoring the estimators, and one result that reversed

Everything built on 2026-08-27 records rather than decides. This is the check
that has to pass before any of it is allowed to size or gate.

### The live board, 90 closed trades

| feature | n | R below the median | R above | gap |
| --- | ---: | ---: | ---: | ---: |
| `efficiency` | 45 | −0.405 | −0.153 | **+0.251** |
| `origin_distance_vol` | 42 | −0.035 | −0.335 | **−0.299** |
| `in_origin` | 42 | −0.259 | −0.111 | +0.149 |
| `expected_hold_s` | 43 | −0.227 | −0.127 | +0.100 |
| `probability` | 90 | −0.387 | −0.326 | +0.061 |
| `strength` | 90 | −0.323 | −0.390 | −0.066 |
| `pressure_vol` | 37 | −0.174 | −0.212 | −0.038 |

`probability` and `strength` are noise here, which is the third independent
method to say so.

### The origin result did not survive a larger sample

Origin proximity looked like the strongest thing on the board. A conventional
test of a 0.3R gap at this scatter needs about 180 trades a side; there were
21. Rather than wait weeks, `research/harness/origin_replay.py` runs the origin
model over the resolution history - 49,619 touches with enough prior levels,
each scored against only the origins that existed before it.

| | n | mean R |
| --- | ---: | ---: |
| within 0.5 of an origin | 23,711 | **0.809** |
| further away | 25,908 | **0.975** |
| inside a zone | 39,049 | 0.860 |
| outside every zone | 10,570 | 1.028 |

**It reverses.** Proximity is worse, not better, on a sample a thousand times
larger. The live gap was about one standard error and should not have been
read as a signal - which is what recording before wiring is for.

### Freshness is the part that holds

| | n | mean R |
| --- | ---: | ---: |
| origin never revisited | 10,597 | **1.136** |
| revisited twice or more | 35,279 | **0.822** |

An origin price has not already worked through is worth **+0.31R** over one it
has, on ten thousand samples a side. The claim an origin makes is *unfilled
interest*, and the data says the unfilled half carries it - not the interest
half, and not the distance to it.

Two limits before acting even on that. The replay has no bars, so it cannot
use the last-opposing-bar zone and falls back to the whole leg: **79% of levels
land inside a zone**, which barely discriminates, and production's bar-based
zone is a much narrower thing than this measures. And `vol_bps` is not on a
structures outcome, so distance is in median-step units and the far tail holds
degenerate values where that denominator collapses.

## The stop overrun is partly a width problem

35 stopped trades, mean overrun **+0.056R** past the placed stop.

| | n | overrun |
| --- | ---: | ---: |
| stops narrower than 1.67v | 17 | **+0.083R** |
| wider | 18 | **+0.030R** |

Slippage is a distance in price, so it is a smaller share of a wider stop. That
makes `stop_hold_scaling` a fix for the overrun as well as for being stopped by
noise - it was enabled for the second reason and is helping the first.

The other hypothesis could not be tested, and the reason is good news: **34 of
35 stops already sit beyond the level's sweep band**. `_anchored_stop` places
them outside the zone by design, so resting in the crowd barely happens.
