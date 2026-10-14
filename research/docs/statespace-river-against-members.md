# River beat the members by 3.6x, and 87% of it was a mis-set `Q`

Asked on 2026-10-14: does adding River to the statespace models improve them?

River has been tried here twice and both times on a **classification** target -
`models.md` ran its bagging and forests on level touches, where plain logistic
regression won, and `riverbench.py` ran its boosting and stacking on the
expansion alert. Neither asked it the question the members are scored on, which
is a **one-step predictive density**: held-out log-likelihood, PIT flatness and
CRPS.

The harness is `research/ideas/river_members.py`.

## The handicap, and why it is the fair one

A River regressor returns a point, so to be scored against a filter it needs a
spread. Each one is given an exponentially-weighted mean of its own absolute
residuals, times `sqrt(pi/2)` to turn a mean absolute deviation into a sigma.

That is not a kindness invented here: `family.py` already records that
`selective` reports "a **fitted** spread rather than an inferred one", and it is
in the family on those terms. Both sides see the same information - the last
eight log returns - and both forecast the next log price.

## The answer, and then the diagnosis

| arm | loglike/bar | PIT | **CRPS** |
| --- | ---: | ---: | ---: |
| `Pooled()`, the incumbent | 5.0368 | 37.77 | 0.001598 |
| `Pooled`, residual spread | 4.8332 | 9.08 | 0.000777 |
| **`Pooled`, `Adapting` members** | 5.2852 | **7.89** | **0.000588** |
| **`Pooled`, `Adapting` + residual spread** | **5.3890** | **5.84** | **0.000559** |
| river linear alone | 4.6652 | 18.20 | 0.001141 |
| **river tree alone** | 5.5214 | 8.81 | **0.000441** |
| river forest alone | 5.5216 | 8.64 | 0.000441 |
| `Pooled` + river tree | 5.5352 | 24.38 | 0.000485 |

**River wins outright on the raw comparison** - a Hoeffding adaptive tree at
`0.000441` against the pool's `0.001598` is **3.6 times** better. Taken at face
value that is the largest single improvement anyone has measured on this
question.

It is also almost entirely not about learning.

## The control is what identifies it

The generated feeds are driftless geometric Brownian motion, validated at Hurst
0.50, kurtosis 3.00 and variance ratios 1.000 on 86,411 bars. **There is nothing
to learn there.**

| arm | PIT | CRPS |
| --- | ---: | ---: |
| `Pooled()` | 43.05 | 0.003539 |
| `Pooled`, `Adapting` + residual | **0.53** | 0.002877 |
| river tree alone | 1.24 | 0.002578 |

River beats the pool on a process with no structure, and is **near-perfectly
calibrated** there at a PIT of 1.24 where the pool reads 43.05. A gain that
survives where there is nothing to learn is not a learning gain, and a PIT of
1.0 on the one process the members are *correctly specified for* is the pool
being wrong about its own uncertainty.

## What River actually had was a better-sized `Q`, and the library already fixes it

Two arms separate the causes, and both use machinery that was already here.

**Replacing only the spread** - keep the pool's point forecast, take the spread
from its own residuals - moves PIT from 37.77 to **9.08** and halves CRPS to
`0.000777`. That recovers River's entire *calibration* advantage: 9.08 against
river tree's 8.81 on traded, and 1.12 against 1.24 on the generated feeds.

**Letting each member fit its own process noise** does better and does it
generatively. `adapting.Adapting` drives the exponentially-weighted square of
the standardised innovation toward 1.0 - what its own docstring calls "an
honest filter" - and `family.py` records it at **+848 nats median**. Wrapping
the pool's members in it gives PIT **7.89** and CRPS **0.000588**, beating the
residual patch on every metric, and with both together CRPS reaches
**0.000559** at a PIT of **5.84** - the best-calibrated arm in the study, and
**0.53** on the generated feeds.

So of River's 3.6x, the members recover **87%** of the distance - `0.001598` to
`0.000559` against River's `0.000441` - with no learner, no dependency, and no
loss of the generative structure.

**And adding River to the pool is the arm that fails.** `Pooled + river tree`
reads `0.000485` with a PIT of **24.38** - worse calibrated than the pool's own
`7.89` once its members adapt, and no better on CRPS than river alone. A model
that is better *and* redundant does not improve a precision-weighted pool, and
this one is both.

## What to do, and what not to

**Do not add River.** The remaining gap is 1.27x on CRPS - `0.000441` against
`0.000559` - and the price is a dependency, a point forecast with no state, no
band, no `covariance()` and nothing for `smoothing.py` or `bounding.py` to
consume. That is a poor trade for a quarter of a CRPS unit.

**Do wire `Adapting`.** It is the finding here. It was written, measured at +848
nats, and then used by nothing: `grep` finds it in `__init__`, in `family.py`'s
own prose and in one research harness, and in no production path and no pool.
Measured on this question it is worth **2.7x on CRPS** and takes PIT from 37.77
to 7.89.

**And treat River as the diagnostic it was.** The question "does adding River
improve it" turned out to be worth asking not because the answer is yes but
because a learner with no generative structure beating a family of filters by
3.6x is a statement about the filters. The members' process noise is mis-set -
which is the same conclusion `statespace-activity-on-production-q.md` reached
from the other end, where the production filter's drift pinned at the top of a
grid running to **16,384 times** its constant.

## A defect in the first version of this harness

The first run read River at a PIT of 8.19 against the pool's 25.69 and would
have been reported as a straight win. A filter's `sd` is `sqrt(p00)`, the spread
of the **state**; the quantity being scored is an **observation**, whose
one-step predictive variance is `p00 + R`. Leaving `R` out makes every filter
look over-confident by exactly that term.

A River learner needs no such correction - its spread comes from residuals, and
a residual already contains the measurement noise - so the correction is per arm
rather than global. That asymmetry is a property of what each one reports, and
getting it wrong is what made the first numbers look like a rout.

It also means the PIT figures in `statespace-pooling-exponent.md` are too high
for the same reason, and its **relative** ordering is unaffected, since every
arm there was scored with the same omission.
