# What `edge` is actually measuring

Run: `python research/harness/prior.py`

`infer` builds a probability from two things and compares it to a third:

    own    = level.stats(side)             # this level's own same-side record
    prior  = memory.prior(features)        # 12 nearest by Features.distance
    p      = w * own + (1 - w) * prior
    edge   = p - memory.base_rate_for(feed, interval)

`edge` is the number the whole system turns on. `MIN_EDGE` gates on it,
`actionable` gates on it, every alert is downstream of it.

**It is largely a re-encoding of which side price arrived from.** Subtract a
baseline that also knows the side and the remainder predicts direction at
**51.8%** with an **AUC of 0.520** - a coin flip. Nothing the level knows about
itself, and nothing its twelve nearest neighbours know, survives that
subtraction.

## 1. The asymmetry

`Memory.neighbours()` filters `touch.features.side is features.side`, so the
kNN prior is **side-conditioned**. `Memory.base_rate_for(feed, interval)` is
not - it is the unconditional up-rate for the series.

So `edge` subtracts a side-blind baseline from a side-aware estimate. Whatever
else it contains, it contains `side`, and [features.md](features.md) §1 has
established twice that `side` is the only feature here that predicts anything.

This was not a deliberate choice anywhere. `base_rate_for` was itself a fix - it
replaced a single pooled rate for the whole system, on the correct reasoning
that "BTC on 15m and GBPUSD on the daily do not share an unconditional drift".
The side half of the same argument was never made.

## 2. What each part is worth

11,056 calls paired with the outcome of the touch each one opened, on 10,484
resolved touches across fourteen instruments. Every baseline is accumulated
**causally**: a call is scored against the rates as they stood when it was
made, never against rates its own outcome helped set.

| variant | probability | baseline | n | direction | AUC |
|---|---|---|---|---|---|
| *assume the level holds* | - | - | 11,056 | **73.2%** | - |
| **current** | own + kNN | blind | 11,054 | 69.0% | 0.730 |
| **side-conditioned base** | own + kNN | side-aware | 11,053 | **51.8%** | **0.520** |
| no kNN | own + side base | side-aware | 8,961 | 66.5% | 0.694 |
| **side base rate only** | side base rate | side-aware | 11,052 | 72.2% | **0.741** |

Three readings, in order of how much they cost:

**The current edge is a worse copy of the trivial rule.** 69.0% against 73.2%,
and the two agree on **89.8%** of calls. It is the same signal with noise added.

**Comparing like with like leaves nothing.** Row three is the whole finding.
When the baseline knows the side too, the level's own record and its twelve
neighbours together predict direction at 51.8% and rank at 0.520. That is not
a weak signal; it is the absence of one.

**The best-ranking variant uses none of the machinery.** A per-(feed, interval,
side) base rate - counting, and nothing else - scores **AUC 0.741**, ahead of
the current composite's 0.730, with no `Memory`, no kNN, no
`Features.distance`, and no level history.

## 3. At the live gate

`MIN_EDGE = 0.10`, moved there on 2026-08-16 from a step in realised outcomes:

| variant | passed | share | direction | vs holds |
|---|---|---|---|---|
| current | 7,656 | 69.2% | 73.2% | −1.5pp |
| side-conditioned base | 4,780 | 43.2% | 51.2% | **−22.3pp** |
| no kNN | 408 | 3.7% | 77.7% | +0.0pp |
| side base rate only | 8,961 | 81.1% | 73.8% | −0.0pp |

The gate is doing real work - it selects larger, cleaner moves, which
[edge.md](../docs/edge.md) §1 established separately. What it is *not* doing is
selecting calls with directional skill, because there is none to select.

## 4. Why this was invisible

Every previous measurement compared the model against something and found it
slightly behind. This one changes what it is compared *against*, and the answer
moves from "slightly behind" to "nothing there".

The clue was in plain sight for three documents: the published edge agrees with
"assume the level holds" **89.8%** of the time. A model that agrees with a
one-line rule nine times in ten is not a model that has learned something else;
it is that rule, restated. [features.md](features.md) §3 recorded the agreement
rising from 81.9% to 89.8% as the sample grew and read it as convergence. It
was identification.

## Recommendations, in order

1. **Redefine `edge` against a side-conditioned base rate.** It is the honest
   comparison and it is four lines: bucket by `(feed, interval, side)` instead
   of `(feed, interval)`. Expect the channel to go nearly silent, because that
   is what the measurement says is warranted - at `MIN_EDGE = 0.10` the honest
   edge passes 43% of calls at 51.2% direction, so **the correct gate on an
   honest edge is one almost nothing clears**.
2. **Do not ship 1 without deciding what the product is.** A system that
   correctly says nothing is not obviously more useful than one that says
   something slightly wrong, and that is a judgement about what the alerts are
   for rather than a measurement. State the choice; do not let it be made by
   whichever definition happens to be in the code.
3. **The side-conditioned base rate is the best directional estimate here** at
   AUC 0.741. If anything is published, publish that - it is calibrated, it is
   free, and it beats the composite that costs a kNN over every stored touch.
4. ~~**`Memory` and `Features.distance` can go**~~ - **withdrawn.** This cited
   `similarity.md`, which found the distance orders neighbours no better than
   random across 13.5M pairs. **That document does not exist and never has**,
   in this tree or anywhere in git history, so the 13.5M-pair figure cannot be
   checked by anyone.

   The claim was tested live instead, and the deletion it recommended would
   have been a mistake. [learning.md](learning.md): a learned distance over the
   same nine features converged on weights all within 0.004 of 1.0 - agreeing
   that *no reweighting improves the ordering* - while the kNN beat a
   one-feature floor by 3.1 points of edge on 1,996 matched touches. Both can
   be true: the metric may order neighbours no better than chance and the
   neighbourhood still carry signal.

   So the k nearest stay. What the missing document got right is narrower than
   what it was cited for.
5. **This does not touch magnitude or risk.** `expected_push`, `risk_vol` and
   `reward_to_risk` are separate claims and are not tested here. The system may
   well be useful for *how far* while having nothing to say about *which way* -
   and [features.md](features.md) §3 has flagged that possibility twice without
   anyone measuring it. That is now the most valuable open question.
