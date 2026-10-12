# Prod's directional signal is real and fed downstream at twice its warranted confidence

Asked whether the state-space members would pick similar or better trades than
production. The episode record makes that answerable far more sharply than a
comparison of two opinions, because it carries **both sides of the question
already**: what prod predicted, and what the price then did.

The harness is `research/ideas/episode_replay.py`.

## The data, and how it was taken off a live box

Every `kind=observation, actor=structures` entry in the journal holds prod's
prediction - `probability_up`, `base_rate_up`, `edge`, `actionable`,
`velocity_r` - the realised outcome - `first`, `held_first`, `bars_up_1r`,
`mfe_up_r`, `mae_at_up1_r` - and the geometry - `entry`, `level`, `r_price`,
`r_vol`, `horizon_bars`.

**294,035 episodes** extracted. The journal is a single unindexed `entries`
table at 2.7GB behind an active WAL on the two-core box that runs the live
desk, so the extraction was done read-only with `PRAGMA query_only`, a 2MB
page-cache cap so it could not evict the desk's working set, and the process
at `nice -n 19 ionice -c3`. The container stayed healthy throughout and the
process peaked at 18MB.

**One mistake worth recording, because it is counter-intuitive.** A bounded
read of this table is `ORDER BY rowid DESC LIMIT n` with **no `WHERE`** -
walking the rowid B-tree backwards touches only those pages. Adding
`WHERE kind = 'observation' AND actor = 'structures'` **un-bounds it**: with no
index on `kind`, SQLite must scan the whole 2.7GB to find matches before the
limit can apply. The filtered version wrote zero bytes in 74 seconds; the same
query with the filter moved into Python wrote 19.7MB in two minutes.

So: filter client-side on an unindexed table, and treat a `WHERE` as a full
scan unless an index says otherwise.

## Four arms, and the second is prod's own null

| arm | n | Brier | log loss | vs 0.5 | vs base |
| --- | ---: | ---: | ---: | ---: | ---: |
| **constant 0.5** | 291,699 | **0.25000** | **0.69315** | +0.00000 | +0.00814 |
| prod `probability_up` | 291,699 | 0.25611 | 0.72983 | **-0.00611** | +0.00202 |
| prod `base_rate_up` | 291,699 | 0.25814 | 0.71475 | -0.00814 | +0.00000 |
| **member drift (fitted gain 0)** | 291,699 | **0.25000** | **0.69315** | +0.00000 | +0.00814 |

291,699 of 294,035 episodes resolved to a barrier; the 0.8% that timed out are
**dropped rather than folded in**, because a time-out is a third outcome and
assigning it to either side would bias whichever is commoner. The realised
up-first rate is **0.4947** - a coin, which is what symmetric `+/- 1r` barriers
and gambler's ruin require.

**The member's drift contributes nothing, and the fit says so itself.** The
gain on `velocity_r` was fitted on the training half over a grid from -30 to
+30 and came back at **exactly 0**, which collapses the arm onto the constant
0.5 to five decimal places. That is the cleanest possible version of the null:
not "the drift was unhelpful" but "the optimal weight on the drift is zero".

It is also consistent with what `statespace-directional-edge.md` measured
independently - a confidence-gated drift's best case is 2% of a spread on a
*planted* drift - and this is the same conclusion reached on 291,699 real
episodes by a different route.

**Read alone, the table says prod's directional call is worse than saying "I
do not know"**: Brier 0.25611 against the constant's 0.25000. It does beat
prod's own `base_rate_up`, so it is not merely the marginal - which is how
`hmm.Direction` failed, beating a fair coin by +5.5 nats and its own shuffled
signs by -0.1.

## But the calibration curve says the signal is real

| predicted | n | realised | gap |
| ---: | ---: | ---: | ---: |
| 0.05 | 19,362 | **0.3253** | **+0.2753** |
| 0.15 | 49,449 | 0.3560 | +0.2060 |
| 0.25 | 44,175 | 0.4098 | +0.1598 |
| 0.35 | 27,363 | 0.4451 | +0.0951 |
| 0.45 | 25,490 | 0.4960 | +0.0460 |
| 0.55 | 26,829 | 0.5381 | -0.0119 |
| 0.65 | 39,299 | 0.5833 | -0.0667 |
| 0.75 | 30,479 | 0.6319 | -0.1181 |
| 0.85 | 23,216 | 0.6962 | -0.1538 |
| 0.95 | 6,037 | **0.7777** | **-0.1723** |

**Monotone across all ten buckets, 0.325 to 0.778.** That is a 45-point spread
on 291,699 events and it is not a coin dressed up - it is genuine
discriminative power.

What it is not is a probability. The predictions are **systematically too
extreme**, and a Brier score punishes over-confidence hard enough to turn real
signal into a losing number.

## One coefficient repairs it, fitted out of sample

`k` fitted on the first half by minimising the training Brier, then applied to
the second half and scored there only:

| arm | n | Brier | log loss | AUC |
| --- | ---: | ---: | ---: | ---: |
| constant 0.5 | 145,850 | 0.25000 | 0.69315 | 0.5000 |
| `probability_up`, raw | 145,850 | **0.25841** | 0.73439 | **0.6365** |
| **`probability_up` x 0.47** | 145,850 | **0.23636** | **0.66526** | **0.6365** |

**AUC 0.6365**, and shrinking toward 0.5 by 0.47 turns a losing Brier into one
that beats the constant by **0.01364** and the log loss by **0.0279 nats an
episode**.

**AUC is identical before and after**, which is the consistency check: a
monotone transform cannot change a rank ordering, so the shrinkage altered the
calibration and nothing else. If the AUC had moved, the coefficient would have
been doing something it does not claim to.

## What to do with it

**Shrink `probability_up` toward 0.5 by about half before anything consumes it
as a probability.** Sizing, gating and any expectancy calculation are
currently being handed a number roughly twice as sharp as the data supports.
The coefficient is 0.47, measured on 145,850 episodes the fit never saw.

**And `actionable` does not select the better-calibrated half.** On those
145,934 episodes - exactly 50.0% of the record - the Brier is **0.25650**
against 0.25000 for a coin, and the realised up-rate is 0.4969. So the
over-confidence is uniform across the flag rather than concentrated outside
it, and gating on `actionable` does not make the probability usable.

## What this does not say

**This is signal quality, not traded profit.** The record says which barrier
came first; it does not say what was traded, at what size, or at what cost. An
AUC of 0.6365 on the label is not money: `barrier-geometry-is-irrelevant.md`
proves a barrier trade earns `mu E[tau]` with the geometry cancelling, so the
ordering still has to clear a spread before it pays. That is the next phase and
it needs the broker rather than the journal - `DEFAULT_MAGIC` is 777_701 and
the standing rule is to judge the desk on the broker, not on its own record.

**And the member arm had to be rewritten before it could be believed.** Its
first version scored a Brier of 0.50489 with a log loss of 6.55 - predictions
pinned near 0 and 1 and wrong about half the time, which is a saturating map
rather than an informative signal. It assumed `velocity_r * horizon_bars` was
already a drift in `r` units over the horizon and it is not on that scale.
Reporting that as "the member adds nothing" would have passed off a unit error
as a finding; fitting the gain instead produced the zero that is the real
answer.
