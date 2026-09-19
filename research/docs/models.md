# Which model predicts which way a touch resolves

Run: `python research/harness/models.py`

The question came up as "would tree models and random forest help us", and then
"what about cosine similarity", and then "what other alternatives to the
radius". They are one question - the level model borrows evidence from similar
past touches through `Memory.neighbours`, and
[edge.md](../docs/edge.md) §6 established that the similarity metric does not
order neighbours by relevance. So: what does?

> **Re-measured on 2026-08-16** on **10,484 resolved touches across 14
> instruments** after the backfill in [todo.md](../docs/todo.md) §0d. The
> original run used 1,994 touches from six. **The winner did not change and
> neither did the argument.** Absolute accuracies fell about five points on the
> harder sample; the ordering is nearly identical and the size and speed
> columns are unchanged in what they say.

Every model below is **walk-forward**. Each touch is predicted before it is
learned and never from itself. 10,484 resolved touches from a replay of the
stored 1m, 5m, 15m and 1h bars across fourteen instruments.

## The table

| model | right | vs random | size | µs/call | labels used |
|---|---|---|---|---|---|
| **logistic regression** | **73.1%** | +23.2pp | **1KB** | 280 | 100% |
| entropy sampler (logistic) | 73.0% | +23.2pp | 5KB | **257** | **63%** |
| adwin bagging | 72.9% | +23.1pp | 4,429KB | 4,477 | 100% |
| hoeffding tree | 72.6% | +22.8pp | 479KB | 488 | 100% |
| extremely fast tree | 72.6% | +22.8pp | 1,297KB | 2,358 | 100% |
| gaussian naive bayes | 72.6% | +22.8pp | 68KB | 1,236 | 100% |
| leveraging bagging | 72.6% | +22.8pp | 25,678KB | 18,056 | 100% |
| hoeffding adaptive tree | 72.5% | +22.7pp | 571KB | 709 | 100% |
| adaptive random forest | 72.3% | +22.5pp | 29,053KB | 6,144 | 100% |
| MLP (16 hidden, thresholded) | 71.4% | +21.6pp | 3KB | 4,920 | 100% |
| mondrian forest | 70.9% | +21.1pp | 25,721KB | 3,395 | 100% |
| manhattan, 12 neighbours | 70.5% | +20.7pp | - | - | - |
| **cosine, 12 neighbours** | **70.3%** | +20.5pp | - | - | - |
| euclidean, 12 neighbours *(current)* | 70.3% | +20.5pp | - | - | - |
| facto (ours, push sign) | 64.3% | +14.5pp | 7KB | 2,032 | 100% |
| SRP | 63.8% | +14.0pp | 13,508KB | 16,002 | 100% |
| *always up* (majority class) | 50.5% | +0.7pp | - | - | - |
| *random 12 neighbours* | 49.8% | 0.0pp | - | - | - |
| farthest 12 neighbours | 49.2% | −0.6pp | - | - | - |

## 1. Trees and forests do not help. A linear model beats all of them.

Logistic regression is the most accurate thing tried, at **1KB and 193µs**.
The adaptive random forest is 1.9 points worse, **3,300 times larger** and 17
times slower. Leveraging bagging is 1.7 points worse at 5MB and 47 times
slower.

On a box with a 640MB container cap that has been OOM-killed five times, a
5MB-per-instrument model is not a marginal cost - fourteen instruments times
seven timeframes would be most of the container for a model that loses.

This is not the usual result and it is worth being clear about why it is
plausible here rather than treating it as a surprise. Trees earn their keep on
non-linear thresholds and high-order interactions. There are nine features,
most of them already scale-free and monotone in their effect, and one of them
(`side`) does nearly all the work. There is not much for a tree to find, and
plenty of room to overfit looking for it.

**And more data did not rescue them.** Five times the sample was the obvious
thing that might have - trees are supposed to be data-hungry - and the gap to
logistic regression is unchanged: 0.5 points to the best tree then, 0.5 points
now. The forests remain 25,000KB against 1KB.

**SRP moved from 53.1% to 63.8%**, which is the largest change in the table and
still last but one among real models. That confirms the original reading: it
was never a finding about SRP but a warning that these ensembles have
hyperparameters this experiment did not tune, and a tenfold sample fixed some
of it. Read the table as "the expensive models did not win out of the box", not
as "the expensive models cannot win".

**`facto` at 64.3% is ours**, scored on the sign of the push it regresses
rather than on a direction it was built to predict, so it is at a disadvantage
here by construction - but it is 8.8 points behind a 1KB logistic regression
and it is the model `structures fit` produces.

## 2. Cosine similarity does not help either, and no metric does

Cosine (72.6%), euclidean (72.8%) and manhattan (72.9%) are within 0.3 points
of one another and all of them are **below every fitted model**. Swapping the
metric is not the fix.

Cosine is a poor fit here for a specific reason: it measures the *angle*
between feature vectors and discards magnitude. For features like
`approach_vol`, `depth_vol` and `run_vol`, magnitude is the information - how
fast price came in, how deep it pushed - so normalising it away throws out
what the feature is for.

The two nulls frame the whole table. `random 12` gets **50.7%** and `farthest
12` gets **47.0%**, against 72.8% for the nearest twelve. So the neighbour
vote *is* informative - it is 22 points above random - and the earlier finding
stands unchanged: **the ranking within it is not.** Nearest beats random by a
lot; nearest beats other metrics by nothing.

## 3. What actually carries the signal: side

An earlier version of this experiment had a bug worth recording, because the
corrected numbers are the finding. `side` was one-hot encoded with
`str(Side.ABOVE).endswith("ABOVE")`, and `str(Side.ABOVE)` is `"above"` in
lower case - so the flag was constant and **every model ran blind to which
side price arrived from**.

Blind, the entire table sat between 49.6% and 52.1%. Nothing predicted
anything. With `side` restored, everything jumps to 70-78%.

That is the single largest effect measured anywhere in this project so far, and
it is already in the design: `Features.distance` returns infinity across sides,
so the kNN never mixes them, and `SideStats` keeps per-side records. The
lesson is not "add side" - it is there - but that **side is doing most of the
work that the rest of the feature set is credited with.**

It also explains the earlier claim in [edge.md](../docs/edge.md) §6 that the
*farthest* twelve neighbours predicted best at 75.4%. That measurement drew
from a same-side pool, because it used the real `Features.distance` with its
infinite cross-side distance. Pooled across sides, farthest-12 is **47.0%** -
below random. The "farthest is best" reading was an artefact of the pooling and
is withdrawn; the "nearest ≈ random" conclusion it sat beside is unaffected,
since both arms shared the same pool.

## 4. The one genuinely useful new tool: active learning

`river.active.EntropySampler` wraps a classifier and decides which samples are
worth learning from - high prediction entropy means the model is uncertain,
which means the label is informative.

It scored **73.0% while learning from 63% of the touches**, against 73.1% for
the same classifier learning from all of them. **One tenth of a point for 37%
fewer updates** - and on the larger sample it declines *more* labels than
before (63% against 69%) for a smaller loss. That is the right direction on
both axes.

That is the wrong shape for the alert gate - the gate wants calls the model is
*confident* about, and this selects the ones it is unsure of - but it is the
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
   gives coefficients - which would answer the open question in
   [edge.md](../docs/edge.md) §6 about which features belong in the distance at
   all. This is the one change here worth building.
4. **Do try `EntropySampler` around whatever is fitted**, for the memory and
   compute rather than the accuracy.
5. **Remember what the binding constraint is.** All of this is measured on
   10,484 replayed touches from fourteen instruments **on bars only** - no book,
   no order flow. That is now a decent sample and it did not change the answer,
   which strengthens rather than weakens the conclusion: the ceiling here is
   not the model class and it is not the sample size. It is what a bar can say.
   [features.md](features.md) §4 reaches the same place from the feature side.
