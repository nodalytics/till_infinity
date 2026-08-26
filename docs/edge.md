# The |edge| gate, measured

`|edge| >= 0.08` decides whether a level call is said out loud. `edge` is
`probability_up - base_rate_up`: how far the conditional sits from the
unconditional, in probability. The number was never derived from anything - not
in the commit that introduced it, not in the docs.

[todo.md](todo.md) has carried "derive it from the journal" for a while, and the
attempt failed for a reason worth repeating: on pre-fix data the direction was
called correctly **99.9% of the time at every level of |edge|**, because
inflated touch counts made a level's history and its next outcome the same move
counted twice. A gate cannot be placed on a measurement that says everything
works.

The counting bugs behind that were fixed on 2026-08-14. This is the experiment
re-run, and it reaches three conclusions, one of which contradicts what todo.md
proposed.

> **Re-measured on 2026-08-16** on **10,483 call-outcome pairs across 14
> instruments**, after the backfill in [todo.md](todo.md) §0d. The original run
> used 1,990 pairs across six. Sections 0 to 3 carry the new numbers; §4's
> rolling-quantile comparison and §5-§6 were **not** re-run and are marked
> where they appear. The headline held: there is a step in |edge| and 0.08 sits
> below it.

## What was run

790,000 stored bars replayed through the engine across 1m, 5m, 15m and 1h on
fourteen instruments, pairing **every call with the outcome of the touch it opened**
- 10,483 pairs. A call claims a direction through the sign of `edge`; the
outcome is the sign of the realised `push_vol`. "Direction" below is how often
those agree; "mean push" is the realised push in volatility units, signed
positive when the call was right.

**Bars only.** Production also drives touches from quotes, and today's evidence
is that the two paths differ in ways that matter - the instant-resolution fix
looked complete on a bars-only replay and was still 42.9% wrong on production
because the quote path had no consensus. Treat everything here as the level
machinery rather than the whole system.

## 0. The blocker is gone

**Direction called correctly 68.8%** of 10,483 decided calls, against 99.9%
before. That is a plausible number rather than a broken one, and it is the
finding that makes the rest of this document possible at all.

## 1. Bigger edge, better call - and the gate is below the step

By decile of |edge|, which is a finer cut than the first reading could support:

| decile | \|edge\| from | n | direction | mean push |
|---|---|---|---|---|
| 1 | 0.0000 | 1,049 | 54.8% | 0.16 |
| 2 | 0.0336 | 1,048 | 60.0% | −0.03 |
| 3 | 0.0666 | 1,046 | 61.5% | −0.02 |
| **4** | **0.0968** | **1,055** | **69.3%** | **0.49** |
| 5 | 0.1262 | 1,052 | 68.8% | 0.43 |
| 6 | 0.1560 | 1,045 | 70.3% | 0.37 |
| 7 | 0.1831 | 1,051 | 73.3% | 0.66 |
| 8 | 0.2148 | 1,046 | 77.3% | 0.96 |
| 9 | 0.2514 | 1,042 | 74.7% | 0.86 |
| 10 | 0.2959 | 1,049 | 77.9% | 1.11 |

**The step survives and it is where it was.** Deciles 1 to 3 - everything below
**0.0968** - sit between 54.8% and 61.5% with a mean push of about zero. Decile
4 jumps to 69.3% and a push of 0.49, and nothing after it goes back.

The first reading put the step at 0.11 on six bands; ten deciles on five times
the data put it at **0.097**. Those are the same finding measured at different
resolutions, and the recommendation that follows from either is identical.

**0.08 is inside the flat region**, on both readings. The band it admits
performs like the bands below it and nothing like the bands above it.

It is also not where it was once thought to be. The earlier note in
[levels.md](levels.md) put it near the 97.7th percentile of its own input, with
2.3% of calls reaching it. The median |edge| is **0.1561**, so 0.08 sits *below
the median* and passes **75.8%** of calls.

### It is not one instrument carrying it

Measured on the 2026-08-15 dataset and **not re-run** in this form. Six of six
instruments, same ordering, none marginal:

| feed | below 0.11 | at or above 0.11 |
|---|---|---|
| us100 | 51.6% (n=223) | 76.3% (n=224) |
| spx500 | 58.4% (n=197) | 74.0% (n=196) |
| btc | 58.6% (n=111) | 84.0% (n=231) |
| eurusd | 61.0% (n=105) | 87.8% (n=230) |
| gbpusd | 63.4% (n=112) | 81.4% (n=172) |
| gold | 48.5% (n=66) | 82.1% (n=123) |

The re-run reaches the same place by a different route: the per-cell table now
covers **36 (feed, interval) cells** and the fixed gate passes between 69.1%
and 84.9% of calls in each, so no single instrument is carrying the effect.

## 2. A rolling quantile is **worse** than a constant

[todo.md](todo.md) proposed making the gate "a rolling quantile of realised
edges rather than a constant - the same instinct as [score.md](score.md)'s
thresholds". **That was wrong, and the measurement is not close.** Each rolling
rule is compared against the constant that lets exactly the same number of
calls through, on the same calls:

| rule | passed | share | direction | mean push |
|---|---|---|---|---|
| no gate | 10,483 | 100% | 68.8% | 0.50 |
| rolling q0.70 | 348 | 17.4% | 82.3% | 1.28 |
| **constant 0.2489** | 349 | 17.4% | **89.6%** | **1.70** |
| rolling q0.80 | 247 | 12.3% | 82.3% | 1.32 |
| **constant 0.2745** | 248 | 12.4% | **91.9%** | **1.86** |
| rolling q0.90 | 146 | 7.3% | 82.6% | 1.33 |
| **constant 0.3128** | 147 | 7.3% | **93.2%** | **1.92** |
| rolling q0.95 | 94 | 4.7% | 87.1% | 1.62 |
| **constant 0.3343** | 95 | 4.7% | **91.5%** | **1.98** |

The constant wins by four to ten points of direction at identical volume, in
all four comparisons.

**Why, and why the instinct was reasonable but misapplied.** score.md's
thresholds are on quantities in instrument-specific units, where a constant
cannot mean the same thing on gold and EURUSD and a quantile is the only
honest form. `edge` is *already* scale-free: it is a difference of two
probabilities, and 0.11 means the same thing everywhere by construction.
Normalising it per cell therefore destroys the comparability it already had -
promoting the best of a weak cell and demoting a genuinely strong call in a
cell that often has strong ones.

There is a practical objection as well: **9 of 24 cells never accumulate the
50 calls the rolling rule needs**, covering 17.8% of all calls. On a fourteen
instrument by seven timeframe grid that fraction would be far larger.

## 3. What is *not* established

Measured on the 2026-08-15 dataset and **not re-run**. The threshold's **level**
does not transport, only its ordering. Splitting the calls in half by time:

| band | train | test |
|---|---|---|
| 0.11 - 0.14 | 63.3% | 88.0% |
| 0.20 + | 74.2% | 91.4% |

Every band is far better in the second half, and the top band holds 163 calls
in the first half against 432 in the second. That is the engine warming up
during the replay - levels accumulating history, base rates settling - not a
market regime. The step at 0.11 appears in **both** halves (54.8% to 63.3% in
the first, 71.4% to 88.0% in the second), so the boundary is real; the absolute
accuracy either side of it is not a number to quote.

Also unmeasured: whether any of this survives the quote path, what it does to
alert volume after `actionable`'s other gates, and whether the reward-to-risk
gate already removes most of what moving the threshold would remove.

## 4. Computing it instead of choosing it

> **Partly re-run.** The rolling-quantile-versus-constant table below is from
> the 2026-08-15 dataset. The re-run measured the rolling rules on their own -
> q0.80 passes 19.3% of calls at 76.9% direction, q0.90 passes 9.6% at 77.8%,
> q0.95 passes 5.2% at 78.0%, against the fixed 0.08 passing 75.8% at 72.0% -
> and roughly 1,985 calls are still warming when they are asked, which is the
> same warm-up problem the original found. The conclusion is unchanged and the
> matched-volume comparison was not repeated.

The rolling quantile failing is an argument against *that* dynamic rule, not
against every one. Three others were tried, each scored against the constant
that passes exactly the same number of calls.

**Evidence-scaled: `|edge| >= z * sqrt(p(1-p)/n)`.** The principled form - a
difference of two probabilities is only meaningful against the uncertainty of
the estimate, so require the conditional to sit a given number of standard
errors from the base rate. It needs no threshold at all, only a confidence
level.

| rule | passed | direction | matched constant |
|---|---|---|---|
| z >= 1.0 | 53.4% | 81.9% | 81.6% |
| z >= 1.5 | 35.3% | 85.9% | 85.0% |
| z >= 2.0 | 22.1% | 88.9% | 87.3% |
| z >= 2.5 | 13.6% | 90.0% | 90.8% |

It edges the constant three times out of four and by under two points. The
reason it cannot do more is worth recording, because it is a fact about the
model rather than about the idea: **the effective evidence count barely
varies.** Across 10,483 calls it runs p25 12.5, median 13.8, p75 15.3. `infer`
borrows a fixed `DEFAULT_K = 12` neighbours, so almost every call has the same
denominator and there is nothing for the scaling to bite on. The idea would
matter if `k` varied with how much similar history actually existed.

**Accuracy-targeting.** Rather than a quantile of edges, take the lowest
|edge| whose *realised* accuracy above it has been clearing a target,
re-estimated from outcomes as they arrive, and - this is the part the rolling
quantile got wrong - kept **global** rather than per instrument.

Over the whole replay this looked like a clear win: +4.4, +5.1 and +3.6 points
over the matched constant at targets of 70%, 75% and 80%.

**It is not a win.** Scored on the second half alone, where the warm-up is
mostly done, against a constant matched to its own volume:

| rule | passed | direction | push |
|---|---|---|---|
| adaptive, target 70% | 831 | 87.9% | 1.39 |
| constant 0.07, same volume | 832 | 87.9% | 1.35 |
| adaptive, target 75% | 673 | 90.3% | 1.47 |
| constant 0.13, same volume | 674 | 90.2% | 1.47 |
| adaptive, target 80% | 516 | 91.0% | 1.56 |
| constant 0.18, same volume | 517 | 90.7% | 1.51 |

Equal, three times. The earlier advantage was the rule riding the warm-up
drift that §3 describes: its chosen threshold fell from **0.26 to 0.06** across
the replay as the engine's accuracy rose. A constant cannot do that, so over a
period containing a trend the adaptive rule looks better while being no better
per call.

### So what is it actually worth

Not accuracy. **Maintenance.**

A constant is exactly as good as the adaptive rule *provided somebody keeps
re-deriving it*, and the evidence that nobody does is this document. `0.08` was
presumably defensible when it was set - [levels.md](levels.md) records it at the
97.7th percentile of its input, passing 2.3% of calls. Today it passes 69.6%
and sits below the median. Nothing changed it; the distribution moved underneath
it when the counting bugs were fixed, and it went stale silently.

An accuracy-targeting rule would have moved with it. That is the argument for
building one, and it is a different argument from the one this file started
with - it is about the threshold not needing an owner, rather than about it
being sharper.

The cost is honest too: it needs outcomes before it can say anything (200 calls
here), it will track a drift whether the drift is real or an artefact, and a
target accuracy is still a number somebody picks - but it is a number with a
meaning, which `0.08` never was.

## What to do

1. ~~**Move the constant from 0.08 to about 0.10.**~~ **Done on 2026-08-16**,
   as `reactions.MIN_EDGE`. It was the change the evidence supported most
   directly and it needed nothing built. The first reading put the step at 0.11
   on six bands over 1,990 calls; ten deciles over 10,483 put it at **0.0968**,
   and everything below runs 54.8% to 61.5% with a mean push of zero. 0.10 is
   the round number between them, and both readings agree on the only load-
   bearing point - that 0.08 was below the step.

   Two things changed besides the value. It is a **named constant** rather than
   a bare literal inside `actionable`, which is how it went unexamined for
   months; and `research/harness/edge_gate.py` now **imports** it rather than
   carrying its own copy, so the harness cannot quietly measure a threshold the
   service has stopped using.
2. **Then build the accuracy-targeting rule, and expect no accuracy from it.**
   It matched the constant three times out of three at matched volume, so it is
   not an improvement in what gets said - it is an improvement in the threshold
   not going stale, which this document is the evidence for. Global, never per
   instrument, and parameterised by a target accuracy rather than a quantile.
3. **Do not build the rolling quantile**, and record why, because the instinct
   will recur. It is right for anything in volatility units, which is most of
   this project, and wrong here precisely because `edge` is already a
   probability.
4. **Leave the evidence-scaled form alone until `k` varies.** `z * sqrt(p(1-p)/n)`
   is the principled shape and it has nothing to work with while `infer` borrows
   a fixed twelve neighbours: the effective count runs 12.5 to 15.3 across the
   quartiles. Worth revisiting if the kNN ever takes as many neighbours as it
   genuinely has, not before.
5. **Re-derive on production before treating any of this as settled.** Bars-only
   replay, and 2026-08-14 twice established that the quote path can overturn a
   bars-only result. The counter restarts from those fixes, same as
   [todo.md](todo.md) item 4.
6. **The step is the one finding here that has now survived a fivefold sample.**
   Direction fell from 71.1% to 68.8% overall and the absolute accuracies moved
   throughout, but the shape - flat below the step, better above it, never
   reverting - did not. Prefer it to any number in this document that has been
   measured once.

## 5. Evidence scaling, in full

The gate asks whether an edge is big enough to act on. `edge` is
`probability_up - base_rate_up`: the gap between what this level does when
touched from this side and what price does anyway. A gap of 0.11 means the
level shifts the odds by eleven points.

**A gap is only meaningful against how confidently it was measured.** Take a
base rate of 50%. A level touched four times went up three: p = 0.75, edge =
+0.25, a huge number - and three-of-four from a fair coin happens 31% of the
time, so nothing has been measured. A level touched four hundred times went up
240: p = 0.60, edge = +0.10, less than half the size, and essentially
impossible by chance.

A fixed threshold gets this backwards. `|edge| >= 0.11` passes the meaningless
0.25 and rejects the solid 0.10. It is worse than neutral, because small
samples *produce* extreme edges: the noisiest estimates are the ones most
likely to clear a fixed bar.

Evidence scaling asks instead how far the gap is in units of its own noise:

    standard error = sqrt( p(1-p) / n )
    gate:            |edge| >= z * standard error

`sqrt(p(1-p)/n)` is how much a proportion estimated from `n` observations
wobbles by chance, so dividing by it turns "eleven points" into "this many
standard errors from the base rate" - the question a significance test asks.
`z` is then a confidence level with a meaning rather than a number somebody
picked.

The effect is a threshold that **moves per call**: at n = 4 it demands an
enormous edge, at n = 400 a small one. Measured here, `z = 1.5` ranged from
**0.072 to 0.750** across calls - the same rule asking for a ten-fold different
edge depending on the evidence behind it.

Two honest caveats. `prior` already shrinks `p` toward the kNN estimate with
`PRIOR_WEIGHT`, so some of this protection exists, which is part of why raw
|edge| does as well as it does. And the standard-error formula assumes
independent observations, which touches at one level are not.

## 6. Why it has nothing to work with, which turned out to be the real finding

§4 recorded that the effective evidence count barely varies - 12.5 / 13.8 /
15.3 across the quartiles - because `Memory.neighbours` returns `scored[:k]`,
the k nearest touches *regardless of distance*. The obvious repair is a
similarity radius: take neighbours within a cutoff, so the count means "how
much comparable history exists".

**The cutoff was measured before being built, and the measurement says do not
build it.**

For every resolved touch, every earlier resolved touch is a candidate
neighbour; agreement is whether the two went the same way. If `Features.distance`
ordered neighbours by relevance, near pairs would agree more than far ones.

| distance | pairs | agreement |
|---|---|---|
| 0.0 - 0.5 | 34,814 | 62.5% |
| 0.5 - 1.0 | 188,319 | 63.5% |
| 1.0 - 1.5 | 259,165 | 64.7% |
| 1.5 - 2.0 | 180,828 | 66.1% |
| 2.0 - 3.0 | 188,021 | 65.1% |
| 3.0 + | 144,890 | 68.8% |

Agreement **rises** with distance, and it survives every control - within one
(feed, interval), across cells, and restricted to pairs more than a day apart,
which removes the market-direction dependence that makes any two nearby touches
agree. Four cuts, same direction each time.

The starkest form, taking twelve neighbours four different ways and voting:

| neighbours used | direction called right |
|---|---|
| nearest 12 | 72.9% |
| nearest 12, `1/(1+d)` weighted - what `prior` does | 73.8% |
| **random 12** | **72.7%** |
| farthest 12 | 75.4% |

**The nearest twelve are no better than twelve at random.** The 0.2 points
between them is the robust part; "farthest is best" is a weaker claim on
overlapping samples and probably the same subpopulation effect seen above.

### What this means, and what it does not

It does *not* mean the kNN prior is useless. Twelve neighbours vote the
direction correctly 73% of the time against a 51% base rate, which is a large
effect. It means **the similarity is not what is doing the work.** A pooled
vote of recent touches captures the market's prevailing direction - the same
dependence that makes any two touches agree 57-62% even a day apart - and
`Features.distance` adds nothing on top of it.

So three things follow:

1. **Do not build the similarity radius.** It would restrict the pool to
   neighbours carrying no advantage, and the resulting count would measure
   proximity in a metric that does not predict - which is not the evidence
   count §5 needs.
2. **The `1/(1+d)` weighting in `prior` is not earning its place.** It gains
   0.9 points over unweighted-nearest and still loses to farthest. It is not
   harmful enough to rush a change, but it should not be described as
   borrowing from *similar* touches.
3. **`Inference.neighbours` is not an evidence count** and the alert's
   "+12 similar" is decorative. Whatever is fixed, that wording should go.

The repair is the metric, not the cutoff: which features belong in
`Features.distance`, and with what weights, is an empirical question nobody has
asked. [strength.md](strength.md) reached the same shape of conclusion from a
different direction - the level's own record predicts, and the derived
quantities layered on top of it mostly do not.
