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
