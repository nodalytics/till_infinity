# Which features carry the signal

Run: `python research/harness/features.py`, `python research/harness/holds.py`

[edge.md](../docs/edge.md) §6 found that `Features.distance` does not order
neighbours by relevance and left open which features belong in it. This asks
that directly, and the answer turned out to be about the model rather than the
metric.

Baseline throughout is logistic regression over the raw features, walk-forward,
on 1,995 resolved touches — the best model in [models.md](models.md).

## 1. One feature does everything

Dropping each feature in turn and measuring what is lost:

| feature dropped | accuracy without it | cost |
|---|---|---|
| **above** (which side price came from) | 51.3% | **+26.6pp** |
| strength | 77.8% | +0.1pp |
| run_vol | 77.8% | +0.0pp |
| regime | 77.8% | +0.0pp |
| pivot | 77.8% | +0.0pp |
| backcheck | 77.8% | +0.0pp |
| experience | 77.9% | −0.1pp |
| depth_vol | 77.9% | −0.1pp |
| approach_vol | 77.9% | −0.1pp |

All nine features together score 77.8%. Remove `side` and the model falls to
chance. Remove anything else and nothing happens — three of them are worth
*negative* accuracy.

Each feature alone:

| feature | alone |
|---|---|
| **above** | **78.8%** |
| depth_vol | 52.3% |
| regime | 52.1% |
| strength | 51.7% |
| approach_vol | 51.3% |
| backcheck | 50.8% |
| run_vol | 50.6% |
| pivot | 50.6% |
| experience | 50.4% |

**Side alone beats all nine features together**, 78.8% against 77.8%. The other
eight are not weak; they are indistinguishable from noise, and adding them to
side makes the model slightly worse.

This explains [edge.md](../docs/edge.md) §6 completely. `Features.distance` is a
Euclidean distance over eight features that carry no directional signal plus a
side constraint that is applied separately as a hard filter. The metric was
never going to order neighbours by relevance, because there is nothing in it to
order by. The problem was never the cutoff or the metric — **it is the feature
set.**

## 2. Generating features from them does not help

| pipeline | accuracy |
|---|---|
| raw (baseline) | 77.8% |
| + pairwise products, degree 2 | 74.5% |
| + random Fourier basis, 50 components | 76.5% |
| + target mean per feed and interval | 77.7% |

Nothing generated beats the raw features, and the interaction terms are 3.3
points worse. That is what feature generation does to a set with no signal in
it: it manufactures more ways to overfit. Feature *generation* is not the
missing piece while feature *content* is the problem.

## 3. The baseline nobody had measured

If side is doing all the work, then the trivial rule deserves scoring: a touch
from above pushes back up, a touch from below pushes down — **the level holds.**

On identical rows, 2,006 calls paired with the outcome of the touch each one
opened:

| rule | direction right |
|---|---|
| **assume the level holds** | **77.7%** |
| the edge sign — what we publish | 71.1% |
| assume it breaks | 22.3% |

And at every gate:

| \|edge\| at least | n | edge sign | level holds | edge better by |
|---|---|---|---|---|
| 0.00 | 1,993 | 71.1% | 77.7% | −6.6pp |
| 0.08 *(current gate)* | 1,391 | 77.9% | 80.9% | −3.0pp |
| 0.11 | 1,179 | 81.0% | 83.1% | −2.1pp |
| 0.14 | 988 | 82.2% | 84.1% | −1.9pp |
| 0.20 | 595 | 86.7% | 88.2% | −1.5pp |
| 0.30 | 181 | 92.3% | 92.8% | −0.6pp |

**The directional inference never beats the trivial rule, at any threshold.**
It converges toward it as the gate tightens — the two agree on 81.9% of all
calls, 93.2% above 0.11 and 97.8% above 0.20 — so a high-edge call is nearly
always just saying "the level holds", and the residual disagreement is where it
loses.

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
the model, and `edge` is not adding directional skill on top of it.** `edge` is
defined as `probability_up - base_rate_up`, so this is close to saying the
conditional estimate is not beating its own unconditional — which is precisely
the comparison [reactions.py](../till_infinity/structures/reactions.py) says
every probability here should be reported against, and now has been.

## What to do

1. **Score every future directional claim against "the level holds."** It is
   free, it is 77.7%, and nothing has beaten it. It belongs in `facto.Report`
   next to the baseline and levels-model comparisons already there.
2. **Do not spend effort on the distance metric or on feature generation.**
   Both were measured and neither is where the problem is.
3. **The open question is feature content**: what would predict direction
   *beyond* the side. Nothing currently collected does. That is a question
   about what to measure at a touch, not about how to model what is already
   measured — and it should be answered before any more modelling work.
4. **Re-run on production once the quote path is included.** Bars-only replay,
   1,995 touches, six instruments. The direction of these results is stark
   enough to act on; the exact figures are not settled.

## 4. So what *should* be measured at a touch

Everything below was tested after §3, because "the feature set is the problem"
is only useful if it says what would fix it. Scored on **AUC as well as
accuracy**, which corrects a mistake in §1-§3: the base rate is 78%, and
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
| side alone | 78.5% | 0.847 |
| side + up-rate only | 78.2% | **0.851** |
| side + the full record | 77.2% | 0.844 |
| the record alone | 72.9% | 0.817 |

and restricted to levels with **three or more** prior same-side touches — 541
of 1,609:

| features | accuracy | AUC |
|---|---|---|
| side alone | 87.0% | 0.874 |
| side + the record | 86.2% | **0.898** |

**+0.024 AUC where the history exists**, and nothing where it does not. Note
also that one summary beats six: adding `up_rate` alone (0.851) beats adding
all six record features (0.844), which is what correlated features do to a
small sample.

### Four things collected and never used — all weak, all in the same direction

| candidate | AUC with side | held-rate change, within cell | cells positive |
|---|---|---|---|
| side alone | 0.852 | — | — |
| + volume, against the series' own average | 0.851 | +2.3pp | 9/13 |
| + momentum, 20 bars in volatility units | 0.850 | +3.5pp | 9/13 |
| + cross-venue disagreement at the touch | 0.849 | +3.1pp | 11/13 |
| + headroom to the next level | 0.850 | +0.0pp | 7/13 |
| + session (Asia/London/overlap/US) | 0.853 | — | — |
| + all four | 0.850 | — | — |

**Not one of them moves AUC.** Three of them move the held rate by two to three
points within a cell, consistently in sign — 9, 9 and 11 cells out of 13 — but
that is far too small for a linear model to exploit on 150 touches per cell.

The within-cell control matters and is why the pooled numbers are not quoted:
cross-venue disagreement looked like a **+22.9 point** effect pooled (66.4% →
89.3% across terciles) and collapses to +3.1pp within cells. The pooled version
was measuring which instrument it was — venue gaps run 3.46 volatility units on
spx500 against 0.05 on gold — not what the venues were doing.

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

- **2,000 touches is small.** A three-point effect needs on the order of a
  thousand per arm to establish; there are about 150 per cell. Consistency of
  sign across 9-11 of 13 cells is suggestive on its own, and these candidates
  deserve re-testing on production volume rather than dismissal.
- **Only direction was tested.** Magnitude and risk are separate claims. A
  feature that says nothing about which way price goes may still say how far,
  and `expected_push` is what the reward-to-risk gate actually consumes.

## Recommendations, in order

1. **Add the level's own same-side up-rate to `Features`.** One number, already
   computed, already point-in-time safe, +0.024 AUC where history exists. It is
   the only tested change with a positive result.
2. **Score every directional claim against "assume the level holds"** (§3), and
   report AUC beside accuracy. `facto.Report` compares against two baselines
   already; these are the two it is missing.
3. **Do not add volume, session, momentum or headroom yet** — measured, and
   none of them moves the ranking. Re-test on production volume before closing
   the question.
4. **Treat order flow as a collection question.** It is the one thing not
   derivable from what is already stored, and three separate documents have now
   arrived at it from different directions.
