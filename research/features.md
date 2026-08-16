# Which features carry the signal

Run: `python research/harness/features.py`, `python research/harness/holds.py`

[edge.md](../docs/edge.md) §6 found that `Features.distance` does not order
neighbours by relevance and left open which features belong in it. This asks
that directly, and the answer turned out to be about the model rather than the
metric.

> **Re-measured on 2026-08-16** on **10,484 resolved touches across 14
> instruments**, after the backfill in [todo.md](../docs/todo.md) §0d took the
> store from 455k bars to 1.56M. The original run used 1,995 touches from six
> instruments over days rather than months. **Every headline below reproduced.**
> The absolute accuracies fell by about five points, which is what a harder,
> broader sample should do; the ranking did not move at all.

Baseline throughout is logistic regression over the raw features, walk-forward,
on 10,484 resolved touches — the best model in [models.md](models.md).

## 1. One feature does everything

Dropping each feature in turn and measuring what is lost:

| feature dropped | accuracy without it | cost |
|---|---|---|
| **above** (which side price came from) | 51.9% | **+21.1pp** |
| approach_vol | 73.0% | +0.0pp |
| backcheck | 73.0% | +0.0pp |
| strength | 73.1% | +0.0pp |
| run_vol | 73.1% | +0.0pp |
| regime | 73.1% | +0.0pp |
| pivot | 73.1% | +0.0pp |
| depth_vol | 73.1% | +0.0pp |
| experience | 73.1% | −0.0pp |

All nine features together score 73.1%. Remove `side` and the model falls to
chance. Remove anything else and **nothing happens at all** — on 10,484 touches
every one of the eight costs 0.0 points to the decimal.

Each feature alone:

| feature | alone |
|---|---|
| **above** | **73.0%** |
| regime | 51.2% |
| experience | 51.1% |
| backcheck | 51.1% |
| approach_vol | 51.1% |
| depth_vol | 51.0% |
| strength | 50.8% |
| run_vol | 50.8% |
| pivot | 50.8% |

**Side alone matches all nine features together**, 73.0% against 73.1%. The
other eight are not weak; they are indistinguishable from noise, and on five
times the data they have converged to *exactly* noise — every one of them lands
between 50.8% and 51.2%, where the first reading had them spread from 50.4% to
52.3%. That spread was itself noise, and more data collapsed it.

This explains [edge.md](../docs/edge.md) §6 completely. `Features.distance` is a
Euclidean distance over eight features that carry no directional signal plus a
side constraint that is applied separately as a hard filter. The metric was
never going to order neighbours by relevance, because there is nothing in it to
order by. The problem was never the cutoff or the metric — **it is the feature
set.**

## 2. Generating features from them does not help

| pipeline | accuracy |
|---|---|
| raw (baseline) | 73.1% |
| + pairwise products, degree 2 | 71.3% |
| + random Fourier basis, 50 components | 68.4% |
| + target mean per feed and interval | 73.1% |

Nothing generated beats the raw features, and the interaction terms are 1.8
points worse — the random Fourier basis 4.7. That is what feature generation does to a set with no signal in
it: it manufactures more ways to overfit. Feature *generation* is not the
missing piece while feature *content* is the problem.

## 3. The baseline nobody had measured

If side is doing all the work, then the trivial rule deserves scoring: a touch
from above pushes back up, a touch from below pushes down — **the level holds.**

On identical rows, 10,485 calls paired with the outcome of the touch each one
opened:

| rule | direction right |
|---|---|
| **assume the level holds** | **73.1%** |
| the edge sign — what we publish | 68.8% |
| assume it breaks | 26.9% |

And at every gate:

| \|edge\| at least | n | edge sign | level holds | edge better by |
|---|---|---|---|---|
| 0.00 | 10,483 | 68.8% | 73.1% | −4.3pp |
| 0.08 *(current gate)* | 7,949 | 72.0% | 73.9% | −1.9pp |
| 0.11 | 6,834 | 73.5% | 74.5% | −1.0pp |
| 0.14 | 5,795 | 74.0% | 75.0% | −0.9pp |
| 0.20 | 3,616 | 76.5% | 76.8% | −0.3pp |
| 0.30 | 982 | 77.7% | 77.7% | **+0.0pp** |

**The gap narrows and closes.** On the first reading the trivial rule beat the
edge at every gate including the highest. On five times the data they *tie* at
`|edge| >= 0.30` — 77.7% each on 982 calls. That is the first sign anywhere
that the model has something the trivial rule does not, and it is confined to
the most confident tenth of calls.

It is a tie, not a win, and 982 calls is not many. But it moved in the right
direction with more data, where most things here moved toward noise.

**The directional inference does not beat the trivial rule at any threshold,
and only reaches it at the last one.** It converges toward it as the gate
tightens — the two agree on **89.7%** of all calls and **97.5%** above 0.11 —
so a high-edge call is nearly always just saying "the level holds", and the
residual disagreement is where it loses. Note the agreement itself rose with
more data, from 81.9% to 89.7%: the model has become *more* like the trivial
rule, not less.

### What this does and does not mean

It does **not** mean the gate is worthless. The threshold is on |edge| in both
columns, so both rules are scored on the same selected touches — and
[edge.md](../docs/edge.md) §1 shows mean realised push rising from 0.73 to 1.83
across those same thresholds. **Gating on |edge| selects larger moves.** That is
real value, and it is independent of direction.

It does **not** mean the level model is wrong about everything. Direction is one
of three things it produces; magnitude (`expected_push`) and risk (`risk_vol`,
`reward_to_risk`) are not tested here at all, and the reward-to-risk gate was
only wired up on 2026-08-14.

What it does mean is narrower and still serious: **the per-side base rate is
the model, and `edge` is not adding directional skill on top of it.** That
comparison — "assume the level holds" — is free, and belongs in `facto.Report`
beside the two baselines it already carries.

`edge` is defined as `probability_up - base_rate_up`, so this is close to
saying the conditional estimate is not beating its own unconditional — which is
precisely the comparison
[reactions.py](../till_infinity/structures/reactions.py) says every probability
here should be reported against, and now has been.

## 4. So what *should* be measured at a touch

Everything below was tested after §3, because "the feature set is the problem"
is only useful if it says what would fix it. Scored on **AUC as well as
accuracy**, which corrects a mistake in §1-§3: the base rate is 73%, and
accuracy at a 0.5 threshold is nearly blind to a better ranking at that mix. A
model can order every touch correctly and never cross the boundary. This system
*gates* — it consumes ranking, not accuracy — so AUC is the measure that
matters, and §1's "nothing beyond side" was partly an artefact of asking the
wrong one.

### The level's own record — yes, where there is enough of it

`strength.md` found a level's same-side record separates holds from fails by
+32.8 points, which looked flatly incompatible with §1. It is not: the record
is **not among the features**. `Features` carries `strength`, the composite
that loses to its own best term, and `experience`, a bare count. The record
itself is never handed to the model.

Snapshotted at the moment the touch opens, before its own outcome is folded in:

| features | accuracy | AUC |
|---|---|---|
| side alone | 73.0% | 0.731 |
| **side + the full record** | 73.1% | **0.735** |
| side + up-rate only | 73.0% | 0.734 |
| side + does the record agree | 73.0% | 0.731 |
| the record alone | 65.1% | 0.688 |

and restricted to levels with **three or more** prior same-side touches — 1,942
of 10,335:

| features | accuracy | AUC |
|---|---|---|
| side alone | 76.2% | 0.756 |
| side + the record | 76.1% | **0.760** |

**+0.004 AUC**, where the first reading found +0.024. This is the result that
shrank most on re-measurement, and it is worth being blunt about: the record
was the single positive finding of the original harness, recommendation #1 of
this document, and the reason `up_rate` was added to `Features`. On five times
the data it is a quarter of the size and inside the noise.

The ordering also inverted. On 1,995 touches, adding `up_rate` alone (0.851)
beat adding the full record (0.844), and this document concluded that one
summary beats six. On 10,335 the full record (0.735) edges `up_rate` alone
(0.734). Both differences are a thousandth of AUC — which is the real lesson.
Neither ordering ever meant anything.

### Four things collected and never used — all weak, all in the same direction

| candidate | AUC with side | held-rate change, within cell | cells positive |
|---|---|---|---|
| side alone | 0.731 | — | — |
| + volume, against the series' own average | 0.733 | −2.1pp | 14/36 |
| + momentum, 20 bars in volatility units | 0.734 | +0.3pp | 18/36 |
| + headroom to the next level | 0.732 | +0.3pp | 18/36 |
| + cross-venue disagreement at the touch | 0.734 | +0.8pp | 20/36 |
| + session (Asia/London/overlap/US) | 0.735 | — | — |
| **+ all four** | **0.738** | — | — |

**This section changed direction, and the way it changed is the finding.**

On 1,995 touches every candidate *lost* AUC and all four together lost it, but
three of them moved the held rate within cells by two to three points with
consistent sign — 9, 9 and 11 cells out of 13 — which this document called
"suggestive" and recommended re-testing rather than dismissing.

On 10,361 touches it is exactly the other way round. Each candidate now adds a
few thousandths of AUC and all four together add **+0.007**, while the
within-cell sign consistency has **collapsed to coin flips**: 14 of 36, 18 of
36, 18 of 36, 20 of 36, with median changes of −2.1pp to +0.8pp.

The consistency was noise. Thirteen cells with about 150 touches each was never
enough to read a sign from, the caveat below said so, and the caveat was right.

**The AUC gain is not established either.** It has not been tested for
significance, and the directly comparable measurement is
[cycles.md](cycles.md) §4: a gain of +0.0041 there had a 95% interval of
−0.0008 to +0.0085 once resampled by instrument. +0.007 is the same order.
Treat it as unmeasured, not as small-but-real.

The within-cell control still matters and is why the pooled numbers are not
quoted: cross-venue disagreement looked like a **+22.9 point** effect pooled
and collapses within cells. The pooled version was measuring which instrument
it was — venue gaps run 3.46 volatility units on spx500 against 0.05 on gold —
not what the venues were doing.

### What that leaves

**The missing information is probably not another function of price.** Six
candidates were tested and every one is derived from OHLC and the level's own
history; they all say the same small thing, which is what you would expect if
they are all views of one weak signal.

The class of information genuinely absent is **order flow** — the book, and
what was absorbed at the level rather than what price did afterwards.
[absorption.md](../docs/absorption.md) already named it: its null is "on the
proxy only", because there is no book to measure against. That is a collection
problem, not a modelling one, and it is the honest answer to what should be
measured at a touch.

Two caveats worth keeping, because they cut the other way:

- ~~**2,000 touches is small.**~~ **Resolved.** They were re-tested on 10,361
  touches across 36 cells, and the sign consistency vanished. This caveat was
  correct to withhold judgement and the judgement is now in: the effect it was
  protecting was not there.
- **Only direction was tested.** Magnitude and risk are separate claims. A
  feature that says nothing about which way price goes may still say how far,
  and `expected_push` is what the reward-to-risk gate actually consumes.

## Recommendations, in order

1. ~~**Add the level's own same-side up-rate to `Features`.**~~ **Done, and it
   is worth less than it looked.** `up_rate` was added on the strength of
   +0.024 AUC where history exists. Re-measured, that is **+0.004**. It is not
   worth removing — it is one number, already computed and point-in-time safe —
   but it should not be cited as a positive result any more, and nothing should
   be built on the assumption that the level's record carries weight.
2. **Score every directional claim against "assume the level holds"** (§3), and
   report AUC beside accuracy. Still the most useful thing in this document.
   The trivial rule beats the published edge at every gate except the highest,
   where they now tie at 77.7%.
3. **Stop re-testing the four candidates.** The reason to keep them open was
   within-cell sign consistency on 13 cells; on 36 cells that is gone. They are
   worth a few thousandths of AUC each, unestablished, and the question has had
   two goes.
4. **Treat order flow as a collection question.** It is the one thing not
   derivable from what is already stored, and it is now the *only* open lead:
   five documents have arrived at it from different directions, and a tenfold
   sample moved none of the alternatives.
5. **Note what a tenfold sample did and did not do.** It did not rescue any
   weak feature, any generated feature, or any expensive model. What it changed
   was two questions that were previously unanswerable for want of range —
   [turns.md](turns.md) and, marginally, [cycles.md](cycles.md). More rows help
   questions about *range*; they do not help questions about *content*.
