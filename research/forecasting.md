# Forecasting volatility: what beats what, and the trap in the middle

An online nonlinear model was added to `structures/vol/` to forecast the next
bar's realised volatility, on the argument that `har.py` is a straight line over
three lagged magnitudes and cannot express an interaction between magnitude and
candle shape.

**The argument holds and it is not enough.** On a fixed instrument universe
split by time, the learner beats HAR in all eight cells - so a straight line
over three lagged magnitudes does leave something on the table. Both of them
lose to reusing the last realised value in eleven of twelve, so neither has
earned a place in front of the number every threshold divides by.

This page took three attempts to say that, and the two wrong versions are kept
below: each was caused by a defect that made the data look clean, and each was
more believable than the truth.

## The run

`research/harness/volhorizon.py`, 250,000 real bars replayed in time order
across 42 feeds and three timeframes, every forecaster scored on identical bars
by the same symmetric relative error `consensus_vol.Score` already uses.

Three contenders:

* **naive** - the last realised value. What a persistence model collapses to,
  and the floor anything here has to clear.
* **har** - `har.py`, in production, the source of `forecast_ratio`.
* **learned** - `learned.py`, one pooled `HoeffdingTreeRegressor` over 20
  dimensionless features, predicting a log correction to the standing estimate.

| horizon | scored | naive | har | learned |
| --- | --- | --- | --- | --- |
| 1 bar | 247,186 | **0.7984** | 0.7760 | 0.7753 |
| 5 bars | 247,186 | 0.8246 | **0.8387** | 0.8216 |
| 10 bars | 247,186 | 0.8080 | **0.8416** | 0.8283 |
| 20 bars | 247,186 | 0.8034 | **0.8420** | 0.7986 |

## Result 1: the single-bar scoring trap

**Persistence wins at one bar and loses at every horizon past it.**

That is not a fact about persistence being good. One bar's realised volatility
is a very noisy draw around a slowly moving scale, and because volatility
*clusters*, consecutive draws are **correlated noise**. A forecaster that
repeats the last draw scores well by reproducing that noise, and any smoother
estimate is penalised for failing to.

The consequence is a trap with a wide mouth: **any comparison of volatility
forecasters scored on the next single bar will crown `naive`**, and will then
be read as "forecasting volatility does not work here". It nearly was read that
way in this run - the first version of the harness scored only k=1, reported
that the new model lost to persistence, and would have been an entirely
defensible place to stop.

**This is the one thing here that replicates**, and it is worth stating as the
pattern rather than as a threshold. Persistence's margin over HAR, by horizon,
in each window:

| horizon | window 1 | window 2 |
| --- | --- | --- |
| 1 bar | +0.022 | +0.064 |
| 5 bars | -0.014 | +0.034 |
| 10 bars | -0.034 | +0.027 |
| 20 bars | -0.039 | +0.020 |

**Monotonically decreasing in both**, on half a million bars between them. The
windows disagree about *where* it crosses zero - window 1 crosses between one
and five bars, window 2 has not crossed by twenty - and they agree completely
about the direction and about one bar being the worst possible place to look.

So the defensible version of this result is directional: the shorter the
horizon, the more of what is being scored is noise, and the better persistence
looks for reasons that have nothing to do with forecasting. Where the crossover
sits is a property of the period, not of the models.

Nothing downstream wants the next print in any case. A stop is placed for the
next hour; `vol_bps`, the number every threshold in the package divides by, is
itself a smoothed quantity. The horizon that gets measured should be the
horizon that gets used.

## The split-sample test that was not one

Before the results, the thing that nearly invalidated all of them.

The obvious way to check a finding on 250,000 bars is to run it on the next
250,000. That was done, everything reversed - persistence suddenly won at every
horizon - and the reversal was written up as a period effect, with a tidy
observation that sample *size* does not protect against one.

Then the two windows were described rather than assumed:

| | window 1 | window 2 |
| --- | --- | --- |
| span | 2026-01-21 .. 2026-08-17 (7 months) | 2026-08-17 .. 2026-08-24 (**7 days**) |
| feeds | 42 | **364** |
| weighting | 5m/15m/1h roughly even | 5m is 56% of it |
| shape | organic | btc, eth, sol all at *exactly* 19,104 bars |

**They are not two samples of the same thing.** The second window changes the
instrument universe eight-fold, compresses the span thirty-fold, and carries
the fingerprint of a bulk backfill. Comparing forecasters across them compares
two unrelated problems, and "the ranking depends on the window" was a statement
about the query, not about the market.

`OFFSET` on a timestamp ordering is not a split-sample test on a book whose
instrument count changes. The harness now takes `FEEDS` and `HALF` so the
universe can be held fixed and the split made on time, which is what the
sections below use.

## The valid test, and what it says

Ten liquid feeds held fixed - btc, eurusd, gold, spx500, gbpusd, us100, usdjpy,
silver, us30, brent - across 5m, 15m and 1h, 400,000 bars ordered by time and
cut in half. Same universe on both sides; only the period differs.

**first half, 2026-01-21 .. 2026-08-20** (199,000 scored)

| horizon | naive | har | learned |
| --- | --- | --- | --- |
| 1 bar | **0.8639** | 0.7055 | 0.7379 |
| 5 bars | **0.8448** | 0.7298 | 0.7699 |
| 10 bars | **0.8101** | 0.7188 | 0.7808 |
| 20 bars | 0.7842 | 0.7058 | **0.7953** |

**second half, 2026-08-20 .. 2026-09-01** (198,800 scored)

| horizon | naive | har | learned |
| --- | --- | --- | --- |
| 1 bar | **0.8448** | 0.6871 | 0.7706 |
| 5 bars | **0.8504** | 0.7097 | 0.7968 |
| 10 bars | **0.8273** | 0.7015 | 0.7990 |
| 20 bars | **0.8132** | 0.7034 | 0.7967 |

### The learner beats HAR, and this is the one thing that replicates

**Eight cells out of eight**, both halves, every horizon:

| horizon | first half | second half |
| --- | --- | --- |
| 1 bar | +0.032 | +0.084 |
| 5 bars | +0.040 | +0.087 |
| 10 bars | +0.062 | +0.098 |
| 20 bars | +0.090 | +0.093 |

That is the claim the model was built to test - that a straight line over three
lagged magnitudes leaves something on the table - and on a fixed universe split
by time it holds in every cell, with the margin growing as the horizon
lengthens. It is the only result on this page that has survived a test designed
to kill it.

### Nobody beats persistence, and that is the real finding

`naive` wins eleven of the twelve remaining cells. The exception is the learner
at twenty bars in the first half, 0.7953 against 0.7842, and it does not repeat.

But the *shape* repeats exactly. The learner's deficit against persistence:

| horizon | first half | second half |
| --- | --- | --- |
| 1 bar | +0.126 | +0.074 |
| 5 bars | +0.075 | +0.054 |
| 10 bars | +0.029 | +0.028 |
| 20 bars | **-0.011** | +0.017 |

Monotonically shrinking in both, crossing zero in one. Which is the same
directional statement Result 1 makes: **the longer the horizon, the less of the
target is noise, and the worse persistence looks.** Whether it has been
overtaken by twenty bars is a property of the period. Whether it is *being*
overtaken is not.

### HAR's standing is not stable

On the 42-feed sample HAR looked like the best of the three at k>=5. On this
fixed ten-feed universe it is the **worst** of the three in both halves, losing
to persistence by 0.10 to 0.16. An earlier version of this page reported the
first as evidence that HAR "earns its place", then withdrew it on the strength
of the invalid split above. Neither statement was supportable.

What can be said is narrower and more useful: **HAR's rank moves with the
instrument mix, and `learned > har` does not.** A forecaster whose standing
depends on which instruments are in the book is not one to hang a threshold on
- an argument about `forecast_ratio`'s provenance, not about its measured
relationship with level-holding, which stands separately on 32,362 touches.

## R-squared, and why the scoreboard was hiding how bad HAR is

Everything above is scored with `consensus_vol.Score` - one minus a symmetric
relative error - because that is the scoreboard already inside the package. It
is bounded and robust and **not comparable to anything outside this
repository**, which makes "is 0.83 good?" unanswerable.

`research/harness/volmetrics.py` reports the standard set instead, on the same
fixed ten-feed universe split by time. Two R-squareds, because the baseline is
the whole difficulty: `R2_mean` is the textbook one against predicting the
sample mean, and `R2_naive` is against reusing the last realised value, which
goes **negative** for anything worse than persistence.

**first half** (99,976 scored)

| model | R2_mean | R2_naive | MAE | RMSE | corr |
| --- | --- | --- | --- | --- | --- |
| naive | 0.7339 | 0.0000 | 0.3014 | 0.7287 | 0.8669 |
| learned | 0.4769 | **-0.9659** | 0.6029 | 1.0217 | 0.7251 |
| har | 0.1924 | **-2.0355** | 0.4968 | 1.2695 | 0.6611 |
| facto | -23.12 | -89.67 | 2.4869 | 6.9384 | **0.0037** |

**second half** (99,975 scored)

| model | R2_mean | R2_naive | MAE | RMSE | corr |
| --- | --- | --- | --- | --- | --- |
| naive | 0.6876 | 0.0000 | 0.4763 | 0.9561 | 0.8439 |
| learned | 0.5409 | **-0.4696** | 0.6569 | 1.1590 | 0.7710 |
| har | -0.5343 | **-3.9109** | 0.6923 | 2.1187 | 0.5911 |
| facto | -29.03 | -95.11 | 4.2913 | 9.3728 | 0.0065 |

Three things the relative-error score was not showing.

**HAR is far worse than it looked.** At one bar the two metrics disagree
completely: 0.776 against naive's 0.798 reads as nearly a tie, while
`R2_naive = -2.04` says *three times* the squared error, and -3.91 in the
second half. R-squared punishes large errors quadratically, so this is HAR's
**tail** - the same tail that produced a published `ratio` of 1.3e11 and forced
`RATIO_CAP` into existence. In the second half its `R2_mean` is negative:
worse than predicting a constant.

**The learner's margin over HAR is the stable result, again.** Half the squared
error in the first window, a quarter of it in the second. That is the same
ordering the relative-error scoreboard found, arrived at independently and
much more starkly.

**No AUC.** AUC ranks a classifier; this is a regression onto a positive
continuous quantity with no threshold to sweep. It becomes the right tool only
if these models are asked a direction question - "will the next bar be livelier
than this one" - which is a different model, not a different metric.

## Factorisation machines: three attempts, no signal

`learning/facto.py` models pairwise feature interactions through latent
factors, which is a better-motivated test of the interaction claim than a tree:
the tree was hoped to *discover* the magnitude-shape interaction by splitting,
and an FM represents it directly.

It never worked:

| attempt | correlation | R2_naive |
| --- | --- | --- |
| bare `FMRegressor`, as `facto.Model` ships it | diverged, non-finite | - |
| scaled, SGD, L2 on the latents, gradient clip 10 | 0.0037 | -89.7 |
| and the scaler pre-warmed 2,000 rows before the FM learns | 0.0152 | -166.5 |

A correlation of 0.015 is **no model**, not a weak one - a bad forecaster still
correlates with its target. Each attempt had a real mechanism behind it: an FM
multiplies its latent factors, so unscaled inputs compound where a tree simply
re-splits, and the second fix addressed learning through a cold scaler.

Stopped at three. Searching configurations until one wins is the failure this
page already documents twice, and it applies to the person writing it.

What this does **not** say is that interactions are absent - the tree's margin
over HAR is evidence they are not. It says an FM does not find them here.

## The bug that looked exactly like a result

Worth writing down, because it is the reason to distrust a null before
publishing one. A first attempt at training on the forward average appeared to
make the model *worse at every horizon* - a clean, plausible, entirely
believable result, with a ready explanation about variance-reduction splitting
that smoothed the signal away along with the noise.

It was a **variable shadowing bug**. The queue loop was written

    for row, unit, total, count in seen.waiting:

inside a method whose parameter is also called `row`, so every row appended to
the queue afterwards was the last one pulled off it. The model learned a
near-constant mapping, and its tree finished 3,000 observations with **one node
and no branches** - a single leaf returning a constant.

Nothing about that looks like a bug from the outside. It looks like a model
that does not work, it arrives with numbers, and the numbers are consistent
across horizons. What caught it was a test asserting the *mechanism* rather
than the score - that two bars of identical magnitude and opposite shape get
different forecasts - which failed with the two predictions **exactly equal**,
a thing no amount of genuine underperformance produces.

The lesson is about test design, not about trees: a test that asserts "the
model is good" cannot distinguish a weak model from a broken one, and a test
that asserts "the model responds to this input" can.

**Kept, off by default** (`STRUCTURES_VOL_LEARNER`, `config.vol_learner`). A
measured null is worth more than an absence: the code, the harness and this
page are what let someone revisit it with a calendar feed rather than rebuild
it from scratch. On, it costs about 0.2% of one core and 1.2MB.

## What the exercise fixed on the way

* **`span_rel` was missing.** The feature set described the current bar's
  *shape* - body fraction, wick fractions - but never its *size*. The realised
  history in `r1`/`r5`/`r22` lags by one bar, so at the moment the row is built
  the bar in front of it has not been appended. The model could see whether the
  bar was a wick or a body and not whether it was large, which is most of the
  signal. A test caught it, and only because the synthetic series was built so
  that magnitude was the thing that mattered.
* **A per-series model is unaffordable here.** Benchmarked in the container:
  `AMFRegressor` is 46MB per model, the cheapest tree 1.2MB. At ~424 series
  that is 19GB and 525MB respectively, on a two-core box with about 1.1GB free.
  One pooled model over dimensionless features is 1.2MB total - and it is the
  better statistics anyway, since a new instrument arrives warm.
* **`forecast_ratio` was documented as the wrong quantity** in four places.
  See [clustering.md](clustering.md); it is the correction that made Result 2
  legible.

## Two additions, both unmeasured as of this writing

Built and deployed to collect, gating nothing, so the head-to-head decides.

**A joint anomaly score, as a feature.** Every existing reading is univariate:
`vol_stretch` asks whether the scale is unusual, `focus_nats` whether the mean
moved, the rolling quantiles whether this reading is high for this instrument.
None can say a *combination* is unusual while each part of it is ordinary.
`HalfSpaceTrees` over the whole feature row can, which is the case
`learning/anomaly.py` already makes for cross-venue quotes and which had never
been pointed at volatility.

Emitted as the score's **percentile** rather than the score. HST is
uncalibrated - measured here, p10 and p90 landed at 0.70 and 0.83 on random
rows - and a feature confined to a tenth of its range is one a tree can barely
split on, with the band drifting as the market changes. Ranking against its own
recent output fixes both, the way `QuantileFilter` does for the venue detector.

**A similarity-weighted estimator** (`analogue.py`). Everything else here
weights the past by *recency* - a half-life is literally how fast to forget -
and none of it can say "that bar three weeks ago looked like this one, and here
is what followed". Weighting by relevance instead is the one part of an
attention layer worth having, and the only part that fits: a transformer is
batch-trained and this box rejected a 46MB-per-model forest.

Its real risk is stated where it lives: with twenty features and a few thousand
rows, "nearest" in twenty dimensions degenerates into "arbitrary". The distance
therefore runs over **six** features carrying scale and shape, and deliberately
excludes the ones identifying *which* series and *when* - those help a tree
that can split on them, and in a distance they would put a 5m bar and a 4h bar
far apart by construction, defeating the pooling the design rests on.

The honest prior for both is that they lose to persistence, like everything
else on this page.

## What would actually change the answer

Not a better model. Every input in this package is a function of the price
series, so all of it is **reactive** - it reports that volatility arrived,
never that it is coming. Lead time has to come from outside the series:

1. **The clock.** `sessions.Clock.volatility` already computes each
   instrument's volatility by hour of day as a share of its own daily mean, is
   published on every call, and was read by no volatility model. Genuinely
   forward-looking, and free. Now wired in as `hour_share`.
2. **Arrival rate.** Quote intensity against this series' own normal. Flow
   arrives before price travels, and every tick is already on the bus.
3. **An economic calendar.** The largest missing input and there is none at
   all. Scheduled events are known days ahead with exact timestamps. Caveat
   that bites here: the book is 72% synthetics, which have no calendar, so this
   buys the ~28% that is a real market.
4. **Cross-instrument spillover.** 53 instruments on one bus, and volatility
   propagates across correlated ones with a lag. Note the earlier
   cross-instrument result failed its control - but that was about *levels
   tallying*, a different claim, and it needs its own control rather than
   inheriting that verdict in either direction.
5. **Implied volatility.** The canonical answer, forward-looking by
   construction, and out of reach without an options source.
6. **The news feed**, which exists and is broken: `articles.symbols` is `[]` on
   all 24,214 rows, so nothing joins to an instrument.

Items 1, 2 and 4 are *features*, not models - which is the one argument for
keeping the learner. `garch.py` has nowhere to put "there is a rate decision in
forty minutes"; a learner does.

And the standing caveat: lead time on volatility is not lead time on direction.
Knowing a large move is coming says to size down, widen, or stay out of a level
trade. It never says which way.
