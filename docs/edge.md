# The 0.08 gate, measured

`|edge| >= 0.08` decides whether a level call is said out loud. `edge` is
`probability_up - base_rate_up`: how far the conditional sits from the
unconditional, in probability. The number was never derived from anything — not
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

## What was run

200,240 stored bars replayed through the engine across 1m, 5m, 15m and 1h on
six instruments, pairing **every call with the outcome of the touch it opened**
— 2,003 pairs. A call claims a direction through the sign of `edge`; the
outcome is the sign of the realised `push_vol`. "Direction" below is how often
those agree; "mean push" is the realised push in volatility units, signed
positive when the call was right.

**Bars only.** Production also drives touches from quotes, and today's evidence
is that the two paths differ in ways that matter — the instant-resolution fix
looked complete on a bars-only replay and was still 42.9% wrong on production
because the quote path had no consensus. Treat everything here as the level
machinery rather than the whole system.

## 0. The blocker is gone

**Direction called correctly 71.1%** of 1,990 decided calls, against 99.9%
before. That is a plausible number rather than a broken one, and it is the
finding that makes the rest of this document possible at all.

## 1. Bigger edge, better call — and the gate is below the step

| \|edge\| band | n | direction | mean push |
|---|---|---|---|
| 0.00 - 0.06 | 468 | 54.3% | 0.16 |
| 0.06 - 0.08 | 134 | 59.0% | 0.29 |
| **0.08 - 0.11** | **212** | **60.8%** | **0.28** |
| 0.11 - 0.14 | 190 | 75.3% | 0.82 |
| 0.14 - 0.20 | 391 | 75.2% | 0.79 |
| 0.20 + | 595 | 86.7% | 1.37 |

Below roughly 0.11 everything sits between 54% and 61% — a coin flip with a
push near zero. At 0.11 it steps to 75% and a push of 0.82, and the band above
it repeats that almost exactly, which is what a real boundary looks like rather
than one bin of noise.

**0.08 is inside the flat region.** The band it admits, 0.08 to 0.11, performs
like the bands below it and nothing like the bands above it.

It is also no longer where it was thought to be. The earlier note in
[levels.md](levels.md) put it near the 97.7th percentile of its own input, with
2.3% of calls reaching it. On corrected data the median |edge| is **0.1373**, so
0.08 sits *below the median* and passes **69.6%** of calls. The distribution
moved under it when the counting was fixed.

### It is not one instrument carrying it

| feed | below 0.11 | at or above 0.11 |
|---|---|---|
| us100 | 51.6% (n=223) | 76.3% (n=224) |
| spx500 | 58.4% (n=197) | 74.0% (n=196) |
| btc | 58.6% (n=111) | 84.0% (n=231) |
| eurusd | 61.0% (n=105) | 87.8% (n=230) |
| gbpusd | 63.4% (n=112) | 81.4% (n=172) |
| gold | 48.5% (n=66) | 82.1% (n=123) |

Six of six, same ordering, none of them marginal. This is the strongest
evidence here.

## 2. A rolling quantile is **worse** than a constant

[todo.md](todo.md) proposed making the gate "a rolling quantile of realised
edges rather than a constant — the same instinct as [score.md](score.md)'s
thresholds". **That was wrong, and the measurement is not close.** Each rolling
rule is compared against the constant that lets exactly the same number of
calls through, on the same calls:

| rule | passed | share | direction | mean push |
|---|---|---|---|---|
| no gate | 2,003 | 100% | 71.1% | 0.73 |
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
Normalising it per cell therefore destroys the comparability it already had —
promoting the best of a weak cell and demoting a genuinely strong call in a
cell that often has strong ones.

There is a practical objection as well: **9 of 24 cells never accumulate the
50 calls the rolling rule needs**, covering 17.8% of all calls. On a fourteen
instrument by seven timeframe grid that fraction would be far larger.

## 3. What is *not* established

The threshold's **level** does not transport, only its ordering. Splitting the
calls in half by time:

| band | train | test |
|---|---|---|
| 0.11 - 0.14 | 63.3% | 88.0% |
| 0.20 + | 74.2% | 91.4% |

Every band is far better in the second half, and the top band holds 163 calls
in the first half against 432 in the second. That is the engine warming up
during the replay — levels accumulating history, base rates settling — not a
market regime. The step at 0.11 appears in **both** halves (54.8% to 63.3% in
the first, 71.4% to 88.0% in the second), so the boundary is real; the absolute
accuracy either side of it is not a number to quote.

Also unmeasured: whether any of this survives the quote path, what it does to
alert volume after `actionable`'s other gates, and whether the reward-to-risk
gate already removes most of what moving the threshold would remove.

## 4. Computing it instead of choosing it

The rolling quantile failing is an argument against *that* dynamic rule, not
against every one. Three others were tried, each scored against the constant
that passes exactly the same number of calls.

**Evidence-scaled: `|edge| >= z * sqrt(p(1-p)/n)`.** The principled form — a
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
varies.** Across 2,003 calls it runs p25 12.5, median 13.8, p75 15.3. `infer`
borrows a fixed `DEFAULT_K = 12` neighbours, so almost every call has the same
denominator and there is nothing for the scaling to bite on. The idea would
matter if `k` varied with how much similar history actually existed.

**Accuracy-targeting.** Rather than a quantile of edges, take the lowest
|edge| whose *realised* accuracy above it has been clearing a target,
re-estimated from outcomes as they arrive, and — this is the part the rolling
quantile got wrong — kept **global** rather than per instrument.

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
presumably defensible when it was set — [levels.md](levels.md) records it at the
97.7th percentile of its input, passing 2.3% of calls. Today it passes 69.6%
and sits below the median. Nothing changed it; the distribution moved underneath
it when the counting bugs were fixed, and it went stale silently.

An accuracy-targeting rule would have moved with it. That is the argument for
building one, and it is a different argument from the one this file started
with — it is about the threshold not needing an owner, rather than about it
being sharper.

The cost is honest too: it needs outcomes before it can say anything (200 calls
here), it will track a drift whether the drift is real or an artefact, and a
target accuracy is still a number somebody picks — but it is a number with a
meaning, which `0.08` never was.

## What to do

1. **Move the constant from 0.08 to 0.11 now.** It is the change the evidence
   supports most directly and it needs nothing built: the band admitted today
   performs like a coin flip on every one of six instruments.
2. **Then build the accuracy-targeting rule, and expect no accuracy from it.**
   It matched the constant three times out of three at matched volume, so it is
   not an improvement in what gets said — it is an improvement in the threshold
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
   replay, and today twice established that the quote path can overturn one. The
   counter restarts from the 2026-08-14 fixes, same as [todo.md](todo.md) item 4.
