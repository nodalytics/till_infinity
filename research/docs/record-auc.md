# Two studies, two hold rates: 0.648 and 0.5056 are not in conflict

**Measured 2026-10-15.** Code: [`record_auc.py`](../ideas/record_auc.py).
115,000 scored interactions across twelve configurations.

Two documents report a level's own same-side record against its next
interaction and disagree by 0.14 of AUC:

* [`strength.md`](strength.md) — the same-side record at **0.648**, against
  `Level.strength`'s 0.548. `reactions.py` cites that comparison in the
  docstring of `Inference.record_hold`, which it publishes so something
  downstream can rank on it.
* [`statespace-conditional-holds.md`](statespace-conditional-holds.md) —
  **0.5056**, with every Brier arm worse than predicting the pooled base rate,
  concluding the hold rate carries nothing.

Both are live claims about a published field, so the gap is worth closing.

## Three mechanisms that could have produced it, and none of them did

Each was measured on reconstructed levels, as a 2 x 2 x 2: disjoint or
overlapping races, pooled or stratified within `(feed, interval)`, real levels
or distance-matched placebos.

| frame | races | arm | scored | tie-aware | ties | no-tie | stratified |
|---|---|---|---:|---:|---:|---:|---:|
| 1h | disjoint | real | 19,346 | 0.5021 | 0.007 | 0.5021 | 0.4983 |
| 1h | disjoint | fake | 19,154 | 0.4977 | 0.008 | 0.4978 | 0.4959 |
| 1h | overlapping | real | 45,229 | 0.5048 | 0.003 | 0.5048 | 0.5016 |
| 1h | overlapping | fake | 44,682 | 0.5031 | 0.003 | 0.5030 | 0.5009 |
| 4h | disjoint | real | 16,433 | 0.5047 | 0.008 | 0.5047 | 0.5034 |
| 4h | overlapping | real | 40,646 | 0.5104 | 0.003 | 0.5104 | 0.5091 |

**Ties — worth 0.0000.** The shrunk record over five or more touches takes many
distinct values, so only 0.3% to 0.8% of comparisons tie and the tie-aware and
naive figures agree to four decimals. This was the leading suspect because
`conditional_holds.py` documents its own AUC as reading **1.0000** for a
constant arm, and the estimator here reproduces that defect exactly on a
constant score while reading 0.5000 correctly — so the instrument is right, and
on this data the mistake it guards against is worth nothing.

**Stratification — worth 0.004.** Per-feed mean hold rates span only 0.466 to
0.508, so there is almost nothing for a pooled AUC to order on. Worth checking
because the same confound was worth +0.112 of MSE on push in
[`level-shrinkage.md`](level-shrinkage.md), and worth saying that it was not
worth it here.

**Overlap — worth 0.003.** Letting races overlap more than doubles the scored
count, from 19,346 to 45,229, and moves the AUC from 0.5021 to 0.5048. Worth
checking because `prod-probability-up-needs-halving` found a 0.6365 that became
0.5092 de-overlapped, which is the right order of magnitude for this gap.

All twelve configurations land between **0.4977 and 0.5104**, and the placebo
tracks the real arm within 0.003 in every one.

## What the difference actually is

`strength.md` says it, in its own section headed "the asymmetry hiding inside
it": across its main run, 4,950 decisive interactions were 3,987 rejects, 18
back checks, 933 traps and **12 breaks**. Its outcome is not "did the level
hold" in the trading sense — it is **did price get through the level at all**,
with a trap counted as getting through and coming back, at a base rate near
**81%**, ranked within `(feed, interval)` on the production book.

The symmetric race both the other study and this one settle is a different
event: price travels one median bar range back the way it came before one
through, at a base rate near **49%**, on levels reconstructed from 100-bar
extremes.

**So the two numbers answer different questions and neither refutes the other.**
0.648 is the ordering power of a level's record over *whether price gets through
at all*, on a strongly imbalanced outcome. 0.5021 is its ordering power over a
*balanced race*, and it is zero to within the placebo in every configuration.

## What to change

Nothing computational. Two cross-references, because each document is correct
and each is quotable out of context: the 0.648 is not a general statement that a
level's record predicts, and the 0.5056 is not a general statement that it does
not. The event definition travels with the number or the number is misleading.

The question this leaves genuinely open is whether the record orders the
**production** outcome once that outcome is read on current code and current
levels, which needs the live book rather than a reconstruction — `strength.md`'s
own corrected-code check run is 2,864 interactions, and it is the only arm there
not subject to its volatility-denominator caveat.
