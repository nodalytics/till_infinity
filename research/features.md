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
