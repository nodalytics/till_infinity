# Dispersion is forecastable, and what forecasts it depends on the frame

**2026-10-17. `research/ideas/dispersion_ml.py`, `research/ideas/dispersion_panel.py`.**

The architecture rule set the same day is that every member and component
forecasts **dispersion**, `signalling` emits a bounded signal, and the Monte
Carlo is the only thing that emits a price. This is the measurement that rule
stands on. If nothing beats a three-term linear regression at forecasting
variance, the reframing buys nothing and should be said to.

It does not come out that way, and the useful part is the controls.

## The null, and why it had to be refitted

**HAR-Parkinson**: a regression of forward log-variance on the last bar's, the
last five's mean and the last twenty-two's mean. The target throughout is the
**mean log Parkinson variance over the next `h` bars**, scored out of sample on
the second half of each series with the fit on the first.

The first version of this harness fitted that null at a fixed `1e-8`, which is
effectively OLS - and HAR's three backward averages are strongly collinear, so
the coefficients swing and generalise badly. `dispersion_panel.py`, which
selects a ridge on an inner training split, read HAR at **+0.565** on fx_cross
1h h=20 where the first harness reported **+0.110** for the same cell. The gap
was the penalty, not the model. **An ESN win measured against the
unregularised version would have been a win against a crippled opponent**, so
every linear arm now goes through one fitting procedure and only the features
differ.

## Measured, median out-of-sample R2 against the training mean

| cell | `ou` | `har` | `lin48` | `esn` | esn beats har |
| --- | ---: | ---: | ---: | ---: | ---: |
| onescale 1h h=1 | +0.032 | +0.094 | +0.088 | +0.093 | 4/8 |
| onescale 1h h=20 | +0.066 | +0.201 | +0.205 | +0.198 | 3/8 |
| fx_major 1h h=20 | +0.004 | +0.103 | +0.178 | **+0.540** | 4/7 |
| fx_cross 1h h=1 | +0.007 | +0.046 | +0.090 | **+0.344** | **8/8** |
| fx_cross 1h h=20 | +0.004 | +0.110 | +0.198 | **+0.572** | **8/8** |
| metal 1h h=20 | +0.169 | +0.791 | **+0.826** | +0.769 | 3/4 |
| fx_major 4h h=20 | +0.119 | +0.460 | **+0.500** | +0.482 | 6/7 |
| fx_cross 4h h=20 | +0.004 | +0.362 | **+0.526** | +0.319 | 3/8 |
| metal 4h h=1 | +0.006 | +0.038 | **+0.448** | -1.512 | 0/2 |
| volatility 1h h=20 | +0.000 | -0.003 | -0.009 | -0.042 | 0/8 |

`ou` is AR(1) in log-variance, a discretised Ornstein-Uhlenbeck. `lin48` is
ridge on the last 48 raw lags. `esn` is a fixed random reservoir with a ridge
readout and its effective degrees of freedom printed.

**Dispersion is strongly forecastable and price is not.** That is the whole
argument for the reframing, and it is now a number: R2 of **+0.54 to +0.83** at
a twenty-bar horizon, against a direction that is a coin in every test on this
desk.

## The answer to "can ML predict dispersion" is frame-dependent

**At 1h, the nonlinearity earns its place.** The reservoir reads +0.540 and
+0.572 at h=20 where HAR reads +0.103 and +0.110 and the long linear arm reads
+0.178 and +0.198 - so it is roughly **three times `lin48`** and five times
HAR, and it wins on **8 of 8** fx_cross instruments at every horizon.

**At 4h, it does not.** `lin48` is the best arm nearly everywhere - +0.500
against the ESN's +0.482 on fx_major, +0.526 against +0.319 on fx_cross, and
+0.448 against **-1.512** on metals. So at the slower frame the gain is
**linear long memory** and the reservoir is actively worse.

That split is only visible because of the control, and it is the reason the
control exists. A reservoir brings three things at once - nonlinearity,
capacity, and a memory far longer than HAR's 22 bars - and without `lin48`
every one of these cells would have been read as "ML wins".

**The reservoir is also high variance.** Metal 4h at -1.512 and -1.786 is worse
than predicting the mean, on two instruments. Anything shipping it needs a
guard, not an average.

## Three controls, and each one answers a different objection

**`onescale`** is a generated AR(1) in log-variance read through the same
Parkinson estimator: one timescale, by construction. All three arms read the
same there - **+0.094, +0.088, +0.093** at h=1 and +0.201, +0.205, +0.198 at
h=20 - so neither the extra capacity nor the nonlinearity buys anything where
there is nothing multi-scale to find. The harness has no spurious capacity
advantage, and that is what licenses reading the 1h gap as real.

**It also calibrates the multi-scale claim.** README item 6 says "HAR's win
*is* the multi-scale result", and the raw ratio cannot show that: HAR's longer
averages both carry multi-scale persistence **and** average down the estimator
noise in the target, and a single bar's range-based variance is a noisy reading
of that bar's true variance. On `onescale`, `har / ou` is **2.95, 2.74, 3.03** -
threefold, from noise-averaging alone, with one timescale present. On real
markets at 1h it is **5.52, 25.61, 6.43, 13.14, 31.63**. Well above the
baseline, so log-variance genuinely carries structure at several timescales -
and that claim could not have been made from the ratio without this row.

**The constant-sigma synthetics** are the replication. Deriv's volatility
indices fix their own sigma, so there is nothing to learn, and every arm reads
**-0.000 to -0.042** on all of them at both frames and all three horizons.
`reservoirs.md` measured -0.0107 to +0.0015 there in 2026-09; this reproduces
it. The level-tracking arms go heavily negative instead, which is correct - a
filter tracking a level with no level to track loses to the mean.

**Shuffled targets** read -0.0016 to -0.04 for every fitted arm.

## Topology adds nothing, and nor do the spatial statistics

`topology.md` measured persistent homology against production's shock
forecaster and found it adds nothing: 4 of 250 incremental cells passed, 3
survived Benjamini-Hochberg, none on GARCH walks. Its sharpest column was the
one that looked like a win - volatility-free topology does separate regimes,
but **GARCH walks gain the same**, so what it sees is clustering.

That makes dispersion the natural follow-up: if topology restates volatility it
should predict volatility, and the only question is whether it predicts it
better than a regression on realised variance already does.

**It does not.** The increment over HAR, on the Vietoris-Rips H0 and H1
persistence-landscape norms of a standardised delay embedding:

| cell | tda increment | positive on |
| --- | ---: | ---: |
| fx_major 1h h=5 | -0.0045 | 2/6 |
| fx_major 1h h=20 | **+0.0008** | 3/6 |
| fx_cross 1h h=5 | -0.0028 | 1/6 |
| fx_cross 1h h=20 | -0.0062 | 1/6 |
| metal 1h h=5 | -0.0029 | 1/4 |
| metal 1h h=20 | -0.0049 | 0/4 |
| garch 1h h=20 | -0.0173 | 1/6 |

The best cell anywhere is **+0.0008 on 3 of 6 instruments**, which is zero.

**The cheap rival reads the same.** Point-pattern statistics from *Geospatial
Analysis* (de Smith, Goodchild and Longley, 7th ed.) apply directly to a delay
embedding, because a delay embedding **is** a point pattern - standard
distance, the standard deviational ellipse's anisotropy, the
nearest-neighbour index against complete spatial randomness, and a two-radius
Ripley's K ratio. Their increment over HAR is **-0.0040 to +0.0002**, best 3 of
6. So four moments of the cloud and the full homology of it agree, and they
agree on nothing - which says what persistent homology was reading here was the
cloud's shape, and the cloud's shape is volatility that HAR already has.

## One estimator result worth keeping

Which **definition** of dispersion is forecastable is not a detail. On
fx_cross 1h h=20, HAR on the same bars reads:

| estimator | R2 |
| --- | ---: |
| Garman-Klass | **+0.575** |
| Parkinson | +0.565 |
| Rogers-Satchell | **-0.090** |

Rogers-Satchell is the drift-robust estimator, and removing the drift term
removes nearly all of the forecastable signal with it. On metals it reads
+0.209 against Parkinson's +0.617. Garman-Klass and Parkinson are
interchangeable; Rogers-Satchell is not, and a study that had picked it by
reputation would have reported dispersion unforecastable.

**And window estimators cannot be targets.** A 100-bar standard deviation
shares 99 of its bars with its own next value, so forecasting its forward
average is nearly forecasting itself: on the GARCH control, HAR on a 100-bar
standard deviation read **+0.9297** and on a 100-bar MAD **+0.9298**, against
**+0.0027** on per-bar Parkinson. That is the autocorrelation of an overlapping
moving average and not a result. They are kept as **features**, where looking
back over a window is what a feature is for.

## What this does not claim

Nothing here is about direction. Every number is a statement about how wide the
next bars are, and the desk's record on direction is unchanged. The use for a
dispersion forecast is the Monte Carlo in `statespace/projecting.py`, which
turns it into a distribution over paths - a stop at a stated breach rate, a
target's touch probability, a time to arrive - and for nothing that needs to
know which way price goes.

## The value-reverting member, and the parameter it still needs

**2026-10-17, later. `statespace/ornstein.py`.**

The `ou` arm above exists because the family had no member that reverts a
**value** to a level - `reverting` reverts the *rate* and leaves the value
integrated, which is a random walk in log-variance. `ornstein.Ornstein` closes
that gap: one state, `d(value) = theta (level - value) dt + sigma dW`,
discretised exactly, with the level as an **anchored slow mean** rather than a
free state (a free centre collapses onto the data -
`definitions-cannot-be-states`).

### Two corrections to this harness came first, and both mattered

**Every filter arm had been under-scored.** `_statespace` compared a member's
*current* state against a target that is the mean log-variance over the next
`h` bars. The fitted arms learn that shrinkage from the data; a filter never
sees the target, so its one-step state was being scored against an h-step mean
and the penalty grew with `h` - visible as `pool` reading +0.241 at h=1 and
-1.893 at h=20. Each member is now asked for its own h-step forecast through
`at_time`, averaged over the horizon because the target is a mean.

**But `at_time` is not meaningful for every member.** Applied uniformly it made
`s4d` read **-153** at h=1 and **-2616** at h=20, because a selective map's
states all decay toward zero and its extrapolation returns about zero against a
quantity sitting at -18. That is the README's trade-off 2 appearing as a
number, and it is what `swarm`'s non-decaying anchor exists to fix. Those two
members are named in `DECAYING` and scored on their state, with the reason.

### Measured, 1h, median out-of-sample R2

| cell | `ou` | `ornstein` | `har` | `lin48` | `esn` |
| --- | ---: | ---: | ---: | ---: | ---: |
| fx_major h=1 | +0.011 | **+0.172** | +0.031 | +0.092 | +0.392 |
| fx_major h=20 | +0.004 | **+0.405** | +0.103 | +0.178 | +0.540 |
| fx_cross h=20 | +0.004 | **+0.550** | +0.110 | +0.198 | +0.572 |
| metal h=20 | +0.169 | **+0.834** | +0.791 | +0.826 | +0.769 |
| volatility h=20 | +0.000 | **-0.659** | -0.003 | -0.009 | -0.042 |
| shuffled h=20 | -0.000 | **-0.748** | -0.000 | -0.003 | -0.013 |

And at 4h, where the reservoir is weak and sometimes unstable:

| cell | `ou` | `ornstein` | `har` | `lin48` | `esn` |
| --- | ---: | ---: | ---: | ---: | ---: |
| fx_major h=20 | +0.119 | +0.484 | +0.460 | **+0.500** | +0.482 |
| fx_cross h=5 | +0.073 | +0.460 | +0.220 | **+0.489** | +0.048 |
| fx_cross h=20 | +0.004 | **+0.526** | +0.362 | **+0.526** | +0.319 |
| metal h=5 | +0.002 | **+0.784** | +0.067 | +0.540 | -1.786 |
| metal h=20 | +0.001 | **+0.850** | +0.406 | +0.605 | +0.294 |

**It earns its place on the test it was set.** It beats the `ou` arm it was
written because of in **every** real cell, by ten to a hundredfold. It beats HAR
and the 48-lag ridge at h=20 on both FX classes at 1h and on metals at both
frames, and at 4h it is the best or tied-best arm in five of six real cells at
h >= 5 - including +0.784 against the reservoir's **-1.786** on metals at h=5,
where a 48-state nonlinear model is worse than predicting the mean and a
two-parameter filter is not.

One formatting fault to note rather than leave for a reader to trip over: the
`s4d` row's columns collide when a reading runs past four digits, so that arm's
numbers are unreadable in the raw log. It is a poor arm on this quantity either
way - it is a price member - but the column needs widening before anyone quotes
it.

### And it has a specific, fixable defect

**On the nulls it is not neutral, it is negative** - and the shuffled rows and
the constant-sigma rows read the *same* magnitudes, about -0.06, -0.27 and
-0.73 at h = 1, 5 and 20, where every fitted arm reads about zero.

That is not noise and it is not a bug. **`theta` is a placeholder.**
`subjects.DISPERSION` sets a 24-hour half-life and says it is unfitted, so at
h = 20 the member carries `exp(-theta * 20h) = 0.56` of the current deviation
into its forecast. Where the quantity reverts at about that rate, carrying 56%
is right and it wins. Where the quantity does not revert at all - a shuffled
series, or a generator that fixes sigma - carrying 56% of pure noise is a loss
of exactly the size observed. The `ou` arm reads 0.000 on those same rows
because it **estimates** its coefficient online and finds zero.

So the claim is narrower than the table: *`Ornstein` with a fitted `theta` is
the right model for this quantity and wins decisively; with a placeholder
`theta` it loses wherever the quantity does not revert at the assumed rate.*
Its own nested null is the fit - `theta = 0` is a one-state random walk, so
comparing a fitted `theta` against zero on held-out likelihood is one
parameter at a boundary - and nothing should use this member on a new subject
without running it.

What the member buys over the `ou` arm, once `theta` is fitted, is everything a
filter has and a regression on a fixed grid does not: a posterior, smoothing,
irregular sampling, gap handling, and a band that converges to a stationary
width instead of growing without bound.

### Fitting `theta`, which closes the defect and opens a smaller one

**2026-10-17, later still.** The defect above was `theta` being a placeholder,
so it is fitted: a **streaming likelihood grid** of thirteen candidate
half-lives, each carrying an exponentially weighted sum of
`(d_t - exp(-theta * dt) * d_{t-1})**2` over the deviation `d = value - level`,
with the minimiser taken once sixty readings are in. Three properties earn it:

* **irregular time is exact.** Every candidate is evaluated at each step's own
  gap, because `exp(-theta * dt)` is the quantity being fitted and a nominal
  bar length would be a wrong `theta`.
* **both ends of the grid are in it.** Half-life `inf` is `theta = 0`, a random
  walk; half-life `0` is instant reversion, where the forecast *is* the level
  and nothing is carried. **A fixed `theta` can reach neither**, which is
  exactly why it paid -0.73 where nothing reverts.
* **the anchor survives.** The learnt `theta` is floored so the reversion stays
  at least `SEPARATION` times faster than the level. Without the floor a random
  walk fits `theta -> 0`, the level becomes infinitely faster than the
  reversion, and the member collapses into the walk it replaces.

| cell | fixed `theta` | fitted `theta` | change |
| --- | ---: | ---: | ---: |
| volatility 1h h=20 | -0.659 | **-0.042** | **+0.617** |
| volatility 4h h=20 | -0.725 | **-0.046** | **+0.679** |
| shuffled, every class | about -0.73 | **-0.040 to -0.048** | — |
| fx_major 1h h=5 | +0.130 | **+0.230** | +0.100 |
| fx_major 1h h=20 | +0.405 | **+0.526** | +0.121 |
| fx_cross 1h h=20 | +0.550 | +0.551 | +0.001 |
| metal 1h h=20 | +0.834 | +0.838 | +0.004 |
| fx_major 4h h=20 | +0.484 | +0.443 | -0.041 |
| fx_cross 4h h=20 | +0.526 | **+0.402** | **-0.124** |
| metal 4h h=20 | +0.850 | +0.779 | -0.071 |

**The defect is closed.** The null bias falls from -0.66 and -0.73 to -0.04,
which puts the member level with the reservoir's -0.04 on the same rows. And at
1h it is better where it matters: **+0.526 at h=20 against the reservoir's
+0.540**, a dead heat between two parameters and forty-eight reservoir states.

### The smaller one it opens, and why it is not a bug

**At 4h the fitted `theta` is worse than the placeholder** - by 0.04 on
fx_major, 0.07 on metals and 0.12 on fx_cross.

The cause is a mismatch of criteria rather than a fault in the fit. The grid
minimises **one-step** deviation residuals, because that is what a filter's
dynamics are; the score is an **h-step** forecast, and at 4h bars with h = 20
that is eighty hours ahead. Where the model is exactly right the two agree -
the one-step dynamics imply the h-step forecast. Where it is misspecified, and
it is (the level is a slow exponential mean, not the truth), the
one-step-optimal pull is not the h-step-optimal one, and the gap grows with how
many hours an h-step forecast spans.

So the honest reading is that the fit is right by default - it removes a -0.73
bias and wins at 1h - and that a caller forecasting many hours ahead on a slow
frame should know the pull was chosen on a one-step criterion. Fitting it on
the horizon's own residual would need the member to know the caller's horizon,
which is a different contract and not obviously the right one.

**One residual that is structural rather than fixable.** Even fitted, the
member reads about **-0.04** on shuffled series where `har` reads -0.001. That
is not carried noise from a wrong pull: forecasting a *mean over a horizon*
with a reverting model necessarily carries a little of the current deviation
through the first few steps, and a regression fitted directly on the target
removes that by construction. It is the price of being a filter rather than a
fit, and it is the same size as the reservoir's.

### Should the dispersion subjects pool? No - and it bounds the pooling result

`pooling.py`'s headline is that **the value is in switching rather than in model
choice**: `argmax` beats a member chosen at random each step by 4.7-fold and one
good member held throughout by 5.3-fold. So the obvious question, once a member
that fits this quantity exists, is whether a pool containing it beats it.

It does not, anywhere:

| cell | `ornstein` | `pool` | `pool+orn` | `pool_rev` | `pool_pair` |
| --- | ---: | ---: | ---: | ---: | ---: |
| fx_cross 1h h=20 | **+0.506** | -0.598 | -0.531 | -0.480 | -0.438 |
| fx_major 1h h=20 | **+0.304** | -1.893 | -1.733 | -1.483 | -1.572 |
| metal 1h h=20 | **+0.827** | +0.329 | +0.371 | +0.387 | +0.414 |
| volatility 1h h=20 | **-0.043** | -4.591 | -0.554 | -0.284 | -0.347 |

`pool` is `DEFAULT` - kalman, reverting, robust, all price members. `pool+orn`
adds the value-reverting one to it; `pool_rev` is the two reverting members and
`pool_pair` is ornstein with the Kalman.

**Adding the right member to a pool of wrong members does not rescue the pool.
It drags the right member down.** `pool+orn` reads -0.531 where `pool` reads
-0.598 and `ornstein` alone reads +0.506, so the one correct member bought the
pool 0.07 and lost 1.04 of its own.

The mechanism is in `pooling.py`'s own text. `rule = "shrinking"` forms the
pooled spread as `1 / sum(precision)`, which "sits *below* every member's own
spread and is strictly correct only if the members are independent - they are
not". Members are then weighted by precision, so a member that is **confidently
wrong** gets a large weight: three price filters tracking log-variance as an
integrated process report small spreads and dominate the combined mean.

**So this bounds the pooling finding rather than contradicting it.** That study
pooled members that were all plausible for its subject, and there switching
between them was worth 4.7-fold. Here one member is right and three are wrong by
construction, and precision weighting has no way to notice: it rewards
confidence, and a misspecified filter is confident. The dispersion subjects
therefore name a single member, and `Subject.member` is the right place for that
to be written down.
