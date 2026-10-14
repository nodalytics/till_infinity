# A level that holds rather than breaks is predictable; a trap is not

Asked on 2026-10-14: *what we need from statespace is a level and a direction*,
then *can we predict a break failure*, *can we predict traps*, and *can we
predict our outcomes too*.

Measured on the production journal - 353,287 touch outcomes after
de-overlapping - using only what is known **at** the touch. Three exclusions
matter and each was a near miss:

- `seconds` is the resolution **duration**, not a feature. It reads an AUC of
  0.0446 to 0.0583 for trap against break, which looks like the find of the day
  until you notice a trap returns quickly while a break is only confirmed after
  the trap window elapses. It encodes the answer.
- `excursion_vol`, `adverse_vol` and `push_vol` are measured from the move the
  outcome produced.
- `probability_up` and `up_rate` are post-hoc - see `journal-probability.md`.

## The pooled trap rate is a mixture, and the mixture is broken

The first reading of this said 62.9% of breaks fail, and de-overlapping left it
at 57.8% - a plateau rather than a walk to the null, which is the signature of a
real effect. Split by interval it is not one:

| interval | failure rate | n |
| --- | ---: | ---: |
| 1m | **0.4814** | 52,923 |
| 3m | 0.5893 | 17,911 |
| 5m | 0.5835 | 16,304 |
| 15m | 0.6963 | 4,567 |
| 30m | 0.8191 | 1,432 |
| 1h | 0.9494 | 415 |
| daily | **1.0000** | 8,512 |
| weekly | **1.0000** | 2,696 |

Daily and weekly record **no confirmed breaks at all**. That is a degenerate
label, not a market fact, and with 1h and 30m it drags the pooled figure up. At
1m, the largest arm, **breaks succeed slightly more often than they fail**. So
there is no universal fade, and the 48-sigma pooled claim was Simpson's.

The labelling at 30m and above owes an explanation before anything is built on
those intervals.

## What is predictable, within interval

One-vs-rest, de-overlapped, decision-time features only:

| outcome | base rate | predictor | 1m | 3m | 5m |
| --- | ---: | --- | ---: | ---: | ---: |
| backcheck | 7-10% | `confluence_n` | 0.5618 | 0.5960 | **0.6140** |
| backcheck | | `strength` | 0.5350 | 0.5565 | 0.5568 |
| break | 11-14% | `strength` | 0.4474 | 0.4499 | 0.4569 |
| break | | `experience` | 0.4465 | 0.4452 | 0.4552 |
| chop | 0.8-1.5% | `approach_vol` | 0.4167 | 0.3594 | **0.3531** |
| reject | 63-64% | - | 0.4832-0.5236 | | |
| trap | 13-16% | - | 0.4599-0.5441 | | |

**A strong, experienced level resists being broken.** Both readings sit below
0.5 on all three intervals, which is the same information as "a trap is more
likely at a strong level" seen from the other side - 0.4474 for break against
0.5687 for trap on the same events. Consistent across 179,066, 58,971 and
56,752 touches.

**Confluence predicts a backcheck**, and it is the strongest clean signal in the
journal at 0.6140, rising monotonically with interval. A price several
timeframes agree on gets revisited.

**A trap is not predictable.** Nothing reaches 0.05 from chance except
`approach_vol` at 3m and 5m, and that reading is on the **opposite** side of 0.5
at 1m. A sign that flips between intervals is noise.

**`reject` is not predictable either**, which matters because it is 64% of all
touches: the common case is the one nothing foresees.

## So what statespace can publish

Not a direction. A **level, with the probability that it holds rather than
breaks**, driven by `strength` and `experience`; and a **backcheck
probability**, driven by `confluence_n`. Both are measured, both replicate
across three intervals and 295,000 touches, and both are modest - an AUC of
0.55 to 0.61 moves a 12% base rate by a few points, not into a trade on its own.

What it cannot publish is a trap probability or a direction, and the pooled
trap rate should not be used at all until the 30m-and-above labelling is
explained.

## The one-field change that makes the rest checkable

`reactions.Touch` now carries `probability_up_before`, captured in `_close`
**before** `level.record` counts the touch into the level. The field defaults to
zero so an existing state file restores unchanged - the codec defaults whatever
a mapping is missing - and it is journalled beside `probability_up`.

That single field ends the measurement problem permanently: every future
direction claim from the journal can be scored on the number as it stood before
the touch it is being scored against, instead of on a posterior that has
already counted it.
