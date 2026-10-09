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

## Are production's zones actually too wide? Measured 2026-10-09: no

The 97.6-98.6% coverage quoted above and in
[`level-filters.md`](level-filters.md) was measured **in the research harness**,
where every arm was handed the same nominal 90% band. It is not a measurement
of production's zones, and the two were conflated repeatedly - including in
this document - into "the desk's zones are too wide against a 90% target".

Production does not target 90%. `conformal.COVERAGE` is **0.95**, chosen
because that is what the band already claims: `ZONE_SIGMA` is 2, and a two
sigma Gaussian band is 95.4%.

So the question was put to production directly. 766 published zones over twelve
hours, half-width converted to volatility units through each decision's own
`vol_bps`:

| | half-width, volatility units |
| --- | ---: |
| median, upper side | **0.821** |
| median, lower side | **0.853** |
| mean | 1.38 |
| **measured touch dispersion** (this document) | **0.40** |

**A two sigma band on a 0.40v dispersion is a 0.80v half-width.** The median is
0.82 and 0.85. The zones are doing what the design says they should, and the
earlier claim that they are too wide does not survive contact with them.

Three things the same measurement shows, none of them the thing that was
asked:

| interval | median half-width |
| --- | ---: |
| 1m | 0.889 |
| 5m | 1.086 |
| 3m | 1.112 |
| 15m | 1.208 |
| daily | 2.049 |

* **Width grows with timeframe**, which is expected - fewer touches, so a wider
  posterior - but a daily zone at 2.05v is five times the measured dispersion
  and worth its own look.
* **18.4% of zones sit exactly on the `MIN_ZONE_VOL` floor of 0.35.** For
  roughly one zone in five the filter's own uncertainty is not what sets the
  width at all; a constant is.
* **Median asymmetry between the two sides is +0.000.** The conformal
  calibrator is per-side and exists to find that asymmetry, so at the median it
  is either unsettled or finding none.

### What this means for the change already merged

`TOUCH_NOISE_VOL` moved from a chosen 0.5 to the measured 0.40 in #130, which
narrows the filter's variance and so the zones, by roughly a fifth. **That is
the correction, and it has not reached production yet.**

Which is the argument for changing nothing else now. Adjusting `ZONE_SIGMA` or
the floor in the same window would confound the one change whose size is
already known, and the measurement to run after it deploys is the one above
repeated: if the median half-width lands near 0.65-0.70v and realised coverage
falls to about 95%, the loop is closed and nothing further is needed.

### Why daily zones are five times the dispersion

Asked after the measurement above. Three answers, and only the last is a
question about the model rather than about the measurement.

**First: half of all published zones are not the filter's zone.**
`engine._widen_to_origin` unions the band with the origin box whenever the
level sits in one, so `zone_low` and `zone_high` as published are the filter's
estimate *or* the origin, whichever is wider. Splitting on `in_origin`:

| | n | median half-width |
| --- | ---: | ---: |
| not in an origin - the filter's own zone | 954 | **0.805** |
| in an origin - widened to it | 790 | **1.456** |

Widening nearly doubles it, and it applies to **45% of published zones**. That
is by design, but it means a consumer reading `zone_high` is reading a union of
two objects with different meanings, and any measurement of "how wide is a
zone" has to split on it first. The one above did not, and overstated the
median by about 20%.

**Second: the growth with touch count mostly survives the split, and is
weaker than it looked.** On the filter's own zone, 1m runs 0.67 at no touches
to 1.02 at six or more, 3m runs 0.54 to 0.74. A Kalman update can only shrink
variance, so a level that has been touched more and is wider must have spent
longer accumulating process noise between those touches than the touches
removed. That is the drift constant beating the evidence, which is a real
statement about `DRIFT_VOL_PER_HOUR` and not about the filter.

**Third: daily is not origin widening at all** - no daily zone in the sample
was in an origin - and it does not match the filter's own arithmetic either.
Simulated at a 24-hour touch gap and twenty touches, the model gives a
half-width of **0.372** flat and **0.506** trending. Production's daily median
is **2.05**, four to five times that.

The gap is elapsed time. `predict` grows the variance by
`DRIFT_VOL_PER_HOUR**2 * hours`, and at 0.02 that reaches a variance of 1.0 -
a one-volatility-unit sigma, a two-unit half-width - after about **2,500
hours, or 104 days**. A daily level untested for three months is exactly that,
so the width is the model being internally consistent rather than broken.

**Which turns the question into whether 0.02 is right, and that has never been
measured.** It is a constant chosen per *hour* and applied identically at every
timeframe, so a daily level accumulates twenty-four times the drift variance
per bar that an hourly one does. Whether a level's position really decays that
way is answerable with the same variance-components fit as **I10** - how far
does a level actually move between touches, as a function of the elapsed time
between them - and it is the price-state twin of the question I10 asks about
the slope. Both constants are a tenth-of-the-other guess with no measurement
behind them.

Until that is run, nothing here is a defect. `TOUCH_NOISE_VOL` moving to 0.40
narrows every one of these numbers by about a fifth, and that change is merged
and undeployed, so the measurement to repeat afterwards is this one split by
`in_origin`.
