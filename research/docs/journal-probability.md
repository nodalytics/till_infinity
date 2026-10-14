# `probability_up` measures 0.6566 on the journal's own touches and 0.5092 once they are spaced

Asked on 2026-10-14: *check probability_up on the journalled touches.* The
instruction followed a day in which overlapping windows had already manufactured
one AUC of 0.79 and one family-wise p of 0.015, so the question was whether the
figure this desk quotes for its direction signal had the same problem.

It does. **The AUC of 0.6365 that has been carried as production's direction
number is 0.6566 when reproduced, and 0.5092 once a level's touches are made
non-overlapping.**

## What the journal holds

One table, `entries`, 2,585,129 rows, unindexed - so it is read in rowid-bounded
chunks and filtered in Python, at idle priority, from the host bind-mount rather
than through the container, because the instance has two cores and research has
taken the live desk down before.

503,474 of those rows are touch outcomes carrying both a probability and a
realised push. They are self-contained: `probability_up`, `push_vol`, `outcome`,
`side`, `level`, `interval`, `strength`, `base_rate_up`, `edge`.

## The outcome distribution, which was the other half of the question

| outcome | n | share | up rate |
| --- | ---: | ---: | ---: |
| reject | 338,690 | **67.3%** | 0.500 |
| trap | 78,016 | **15.5%** | 0.462 |
| break | 46,104 | 9.2% | 0.516 |
| backcheck | 35,509 | 7.1% | 0.518 |
| chop | 4,508 | 0.9% | - |

**`trap_rate` is 62.9%.** Of the 124,120 times price got through a level,
78,016 were taken back. `levels.py` says in its own docstring that "a level
where half the breakouts fail is not a level you break out of" - it is
considerably worse than half. The split is nearly symmetric by side (above
68.2% reject, below 66.5%), so it is not a long-short artefact.

By interval the pattern holds from 1m to 5m and then distorts: daily and weekly
report 67.4% reject and 32.5% trap with essentially **no breaks at all**, which
is a labelling question those intervals owe rather than a market fact.

## Two contaminations, and only one of them is arithmetic

**The recorded number is post-hoc.** An outcome entry is written after its touch
resolves and carries the **updated** posterior beside the realised push. Read
straight off it, `probability_up` scores:

| cut | n | AUC |
| --- | ---: | ---: |
| all outcomes | 502,233 | **0.9280** |
| daily | 42,628 | **1.0000** |
| weekly | 15,023 | 0.9999 |
| 1m | 247,221 | 0.8973 |

An AUC of exactly 1.0000 is not a forecast. The calibration curve names the
mechanism: it is a **step**, not a curve - decile 5 says 0.3549 and delivers
0.2546, decile 6 says 0.4917 and delivers 0.6917 - and the jump sits exactly
where counting one up-push carries the posterior across a half. `up_rate` is
pinned at exactly 1.0 on **47.5%** of up pushes and exactly 0.0 on **48.3%** of
down ones.

Joining each outcome to the `decision` or `observation` entry that `parent`
points at does not fix it: **81.6% of those parents carry a `probability_up`
identical to the post-hoc number**, and the 18.4% that differ still score
0.9144.

**And the history is not a sequence of independent touches.** This is the part
arithmetic cannot reach. Solving `p = (2+u)/(4+n)` against `up_rate = u/n`
recovers the touch count exactly, and removing this touch gives 0.9833 - no
better, because removing one touch from an all-up history leaves an all-up
history. The reason it is all-up is spacing:

| interval | consecutive touches of one level within 5 bars | within 40 |
| --- | ---: | ---: |
| 1m | **49.1%** | 76.0% |
| 3m | 55.8% | 79.4% |
| 5m | 52.4% | 78.5% |
| 15m | 60.7% | 81.7% |
| **daily** | **98.7%** | 100.0% |

Median gap 309 seconds, p25 **12 seconds**, p5 **zero**. Eight touches are eight
samples of one move, and all eight record its direction - which is why daily
reads 1.0000.

## The measurement, done properly

Rebuild each level's history from the touch rows, enforce a minimum spacing,
and walk production's own posterior - prior 0.5, weight 4, after three touches -
over earlier spaced touches only:

| spacing | scored | levels | up rate | AUC |
| --- | ---: | ---: | ---: | ---: |
| none | 149,582 | 10,744 | 0.505 | **0.6566** |
| 1 bar | 78,068 | 7,872 | 0.494 | 0.5848 |
| 5 bars | 54,615 | 6,838 | 0.498 | 0.5453 |
| 20 bars | 30,759 | 5,275 | 0.500 | 0.5167 |
| 40 bars | 21,501 | 4,397 | 0.502 | **0.5092** |

The unspaced row reproduces the quoted number. The decay is monotone, and it is
**not** a loss of power: at 21,501 scored touches an AUC of 0.6566 would be
about thirty sigma, and 0.5092 is within about two.

## What this does and does not say

It says the **measurement** was wrong, and that `probability_up` has no
demonstrated predictive power on touches that are not re-samples of one another.
`edge`, which is `probability_up - base_rate_up` and which the desk gates on,
inherits exactly that.

It does **not** say the runtime signal is miscomputed. The live desk forms the
posterior from state it holds at decision time and cannot see a future touch.
What it cannot do is show that the posterior is worth acting on, and the journal
as written cannot be used to check.

## What to change

1. **Journal the pre-touch posterior explicitly**, as its own field, written
   before the outcome is known. One field ends this entire problem.
2. **Space the touches** anywhere a per-level record is accumulated. A level's
   history should count one move once.
3. **Re-derive `MIN_EDGE`** once a real AUC exists. The trap already recorded
   stands: `edge` is measured against a base rate of median 0.4329, so shrinking
   `probability_up` toward 0.5 injects up to 0.1234 of spurious edge.

The one result here that is directly tradeable is not a probability at all: a
62.9% trap rate says the fade is the higher-probability side of a break, and it
is measured on 124,120 journalled attempts.
