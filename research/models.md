# Which model predicts which way a touch resolves

Run: `python research/harness/models.py`

The question came up as "would tree models and random forest help us", and then
"what about cosine similarity", and then "what other alternatives to the
radius". They are one question — the level model borrows evidence from similar
past touches through `Memory.neighbours`, and
[edge.md](../docs/edge.md) §6 established that the similarity metric does not
order neighbours by relevance. So: what does?

Every model below is **walk-forward**. Each touch is predicted before it is
learned and never from itself. 1,994 resolved touches from a replay of the
stored 1m, 5m, 15m and 1h bars across six instruments.

## The table

| model | right | vs random | size | µs/call | labels used |
|---|---|---|---|---|---|
| **logistic regression** | **77.9%** | +27.2pp | **1KB** | **193** | 100% |
| entropy sampler (logistic) | 77.6% | +27.0pp | 5KB | 176 | **69%** |
| leveraging bagging | 76.2% | +25.6pp | 5,044KB | 9,068 | 100% |
| adaptive random forest | 76.0% | +25.3pp | 3,341KB | 3,330 | 100% |
| MLP (16 hidden, thresholded) | 75.8% | +25.1pp | 3KB | 3,198 | 100% |
| hoeffding adaptive tree | 75.1% | +24.4pp | 146KB | 342 | 100% |
| adwin bagging | 75.1% | +24.4pp | 1,453KB | 2,625 | 100% |
| gaussian naive bayes | 74.6% | +23.9pp | 68KB | 834 | 100% |
| hoeffding tree | 74.0% | +23.4pp | 138KB | 286 | 100% |
| extremely fast tree | 73.8% | +23.1pp | 615KB | 1,239 | 100% |
| manhattan, 12 neighbours | 72.9% | +22.3pp | — | — | — |
| euclidean, 12 neighbours *(current)* | 72.8% | +22.2pp | — | — | — |
| **cosine, 12 neighbours** | **72.6%** | +21.9pp | — | — | — |
| mondrian forest | 70.5% | +19.8pp | 5,440KB | 1,647 | 100% |
| SRP | 53.1% | +2.5pp | 2,776KB | 8,214 | 100% |
| *always up* (majority class) | 51.2% | +0.5pp | — | — | — |
| *random 12 neighbours* | 50.7% | 0.0pp | — | — | — |
| farthest 12 neighbours | 47.0% | −3.7pp | — | — | — |

## 1. Trees and forests do not help. A linear model beats all of them.

Logistic regression is the most accurate thing tried, at **1KB and 193µs**.
The adaptive random forest is 1.9 points worse, **3,300 times larger** and 17
times slower. Leveraging bagging is 1.7 points worse at 5MB and 47 times
slower.

On a box with a 640MB container cap that has been OOM-killed five times, a
5MB-per-instrument model is not a marginal cost — fourteen instruments times
seven timeframes would be most of the container for a model that loses.

This is not the usual result and it is worth being clear about why it is
plausible here rather than treating it as a surprise. Trees earn their keep on
non-linear thresholds and high-order interactions. There are nine features,
most of them already scale-free and monotone in their effect, and one of them
(`side`) does nearly all the work. There is not much for a tree to find, and
with 1,994 examples there is plenty of room to overfit looking for it.

**SRP at 53.1% is not a finding about SRP**, which is a strong algorithm
elsewhere — it is a warning that these ensembles have hyperparameters this
experiment did not tune. Read the table as "the expensive models did not win
out of the box", not as "the expensive models cannot win".

## 2. Cosine similarity does not help either, and no metric does

Cosine (72.6%), euclidean (72.8%) and manhattan (72.9%) are within 0.3 points
of one another and all of them are **below every fitted model**. Swapping the
metric is not the fix.

Cosine is a poor fit here for a specific reason: it measures the *angle*
between feature vectors and discards magnitude. For features like
`approach_vol`, `depth_vol` and `run_vol`, magnitude is the information — how
fast price came in, how deep it pushed — so normalising it away throws out
what the feature is for.

The two nulls frame the whole table. `random 12` gets **50.7%** and `farthest
12` gets **47.0%**, against 72.8% for the nearest twelve. So the neighbour
vote *is* informative — it is 22 points above random — and the earlier finding
stands unchanged: **the ranking within it is not.** Nearest beats random by a
lot; nearest beats other metrics by nothing.

## 3. What actually carries the signal: side

An earlier version of this experiment had a bug worth recording, because the
corrected numbers are the finding. `side` was one-hot encoded with
`str(Side.ABOVE).endswith("ABOVE")`, and `str(Side.ABOVE)` is `"above"` in
lower case — so the flag was constant and **every model ran blind to which
side price arrived from**.

Blind, the entire table sat between 49.6% and 52.1%. Nothing predicted
anything. With `side` restored, everything jumps to 70-78%.

That is the single largest effect measured anywhere in this project so far, and
it is already in the design: `Features.distance` returns infinity across sides,
so the kNN never mixes them, and `SideStats` keeps per-side records. The
lesson is not "add side" — it is there — but that **side is doing most of the
work that the rest of the feature set is credited with.**

It also explains the earlier claim in [edge.md](../docs/edge.md) §6 that the
*farthest* twelve neighbours predicted best at 75.4%. That measurement drew
from a same-side pool, because it used the real `Features.distance` with its
infinite cross-side distance. Pooled across sides, farthest-12 is **47.0%** —
below random. The "farthest is best" reading was an artefact of the pooling and
is withdrawn; the "nearest ≈ random" conclusion it sat beside is unaffected,
since both arms shared the same pool.

## 4. The one genuinely useful new tool: active learning

`river.active.EntropySampler` wraps a classifier and decides which samples are
worth learning from — high prediction entropy means the model is uncertain,
which means the label is informative.

It scored **77.6% while learning from 69% of the touches**, against 77.9% for
the same classifier learning from all of them. Three tenths of a point for
nearly a third fewer updates.

That is the wrong shape for the alert gate — the gate wants calls the model is
*confident* about, and this selects the ones it is unsure of — but it is the
right shape for two things this project actually has:

- **Bounded memory.** `Memory` holds 4,000 touches. If a third of them teach
  the model nothing, the same budget could hold a third more of the ones that
  do.
- **Bounded compute.** The box is one process on two cores, and today a
  backfill starving the consumer took the pipeline down for four hours. Fewer
  learning updates is a real saving.

## What to do

1. **Do not adopt trees or forests.** Logistic regression is more accurate,
   3,300 times smaller and 17 times faster. Revisit only with tuned
   hyperparameters and a reason to expect an interaction the linear model
   cannot express.
2. **Do not swap the similarity metric.** Cosine, manhattan and euclidean are
   within 0.3 points; the metric is not where the problem is.
3. **Do consider replacing the kNN prior with a fitted model.** Logistic
   regression beats the twelve-neighbour vote by 5.1 points at 1KB, and it
   gives coefficients — which would answer the open question in
   [edge.md](../docs/edge.md) §6 about which features belong in the distance at
   all. This is the one change here worth building.
4. **Do try `EntropySampler` around whatever is fitted**, for the memory and
   compute rather than the accuracy.
5. **Remember what the binding constraint is.** All of this is measured on
   1,994 replayed touches from six instruments on bars only. Production
   outcomes became trustworthy on 2026-08-14 and the `fit` gate is still shut.
   A better model class on data we have only just stopped mismeasuring is not
   the top of the list — [todo.md](../docs/todo.md) §0c is.
