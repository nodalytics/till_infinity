# Do levels differ in how tightly price touches them, or only pools?

**Measured 2026-10-08.** Code:
[`level_dispersion.py`](../ideas/level_dispersion.py).

The conformal calibrator estimates `q` per `(feed, interval, side)` - how many
sigmas that **pool** needs - and the pools say the instrument's volatility
systematically overstates touch dispersion: 97.6-98.6% coverage against a 90%
target ([`level-filters.md`](level-filters.md)).

That is a pool-wide correction. The question here is whether **levels differ
from each other** beyond it, because that decides whether a per-level width can
exist at all. It was asked as "volatility should be a Kalman state" and is the
defensible version of it: volatility is a property of the instrument, but *how
dispersed this level's touches are relative to the instrument's volatility* is
a property of the level.

**Answer: real, precisely measured, and too small to build on at 1h and 4h.**

## The result

22,402 levels of five or more touches:

| iv | levels | median dispersion | `tau` | `tau` / its error | **p90 / p10** |
|---|---:|---:|---:|---:|---:|
| 1d | 3,042 | 0.3996 v | 0.0965 | 39.0 | **1.28x** |
| 4h | 6,533 | 0.4077 v | 0.0449 | 57.1 | **1.12x** |
| 1h | 12,826 | 0.4135 v | 0.0429 | 80.1 | **1.12x** |

At 1h and 4h a loose level is **12% looser** than a tight one. Against a pool
correction that is already pulling the band from 2.0 sigmas toward what 90%
coverage actually needs, 12% does not pay for a per-level estimator, the state
to carry it, or the shrinkage needed to stop it overfitting.

**`tau / error` is 39 to 80**, so this is not "too noisy to tell". It is
precisely measured and small, which is the more useful kind of negative: the
effect exists and does not matter.

## The incidental agreement, which is the better finding

**Median dispersion is 0.40 volatility units on every timeframe** - 0.3996,
0.4077, 0.4135 - and the filter's observation noise is set at **0.5v**.

So the assumed noise is about 25% wider than what touches actually do. That is
the same overstatement the conformal pools found from the **coverage** side,
reached independently and by a different route: one measures how often the band
contains the next touch, the other measures how far touches sit from the
centre, and both say `0.5v` is too loose.

Two measurements agreeing is worth more than either, and it points at a
constant rather than a model.

## Where a per-level width would earn its place

**1d, and only 1d.** It is the one timeframe with a real effect at 1.28x, and
it is also the one with the fewest levels and the longest gaps between touches.
If this is ever built it should be built there and nowhere else - which is a
different proposal from the general feature that was asked about.

## What nearly happened, and the method note worth keeping

The first version of this estimator used the asymptotic sampling variance of a
log standard deviation, `1 / (2 * (n - 1))`.

On a synthetic pool of **identical** levels at six touches each, it reported
`tau = 0.114` - "a loose level is 1.34x a tight one" - for levels that were the
same by construction. At `n = 6` the true variance of `log s` is **0.1226**
against that approximation's 0.100, and the missing 0.023 comes back out
looking exactly like between-level spread.

Had it run on real data first it would have reported 1.3x to 1.5x everywhere
and read as a finding. The exact variance is `trigamma((n - 1) / 2) / 4`, and
with it the null returns **0.000** while a true spread of 0.2 and 0.5 is
recovered at 0.211 and 0.505.

**It was caught by running the case where the answer must be nothing**, before
running the case where it might be something. That is the second time in a day:
the regret model's uniformly-positive cells were the same shape. In both the
broken version looked *more* interesting than the fixed one, which is the
whole reason the null case has to come first.
