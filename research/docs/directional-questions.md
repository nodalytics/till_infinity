# Better questions, every feature, an ensemble - and still no directional edge

Measured 2026-09-23 on the same universe as [`crash-timing.md`](crash-timing.md): 14 series
at 15m and 1h, 9 daily series back to 2007-2016 from screened sources. Every model is fit on
the earliest block of each series by time and traded on the latest; entries never overlap;
results are in R (units of the stop) net of an assumed spread unless marked gross; and the
two halves of each test period are reported separately.

The search went from one question to six, from nine features to seventy, and from single
models to a 92-signal ensemble weighted by its own covariance. Three defects were found on
the way, and **every positive result this page produced before they were fixed was one of
them**. What survives is a single weak lead on the short side and a clear finding about the
calendar.

| harness | what it asks |
| --- | --- |
| [`horizons.py`](../harness/horizons.py) | does a stop-and-target race over the next H resolve up or down - long and short models at several horizons |
| [`questions.py`](../harness/questions.py) | six sharper questions, each scored against the rule a trader would try first |
| [`dailylong.py`](../harness/dailylong.py) | the stress test of the daily long lead - rules, regimes, rolling refits |
| [`ensemble.py`](../harness/ensemble.py) | many weak models, their covariance and eigenvalues, six ways to combine them |
| [`bars.py`](../harness/bars.py) | the shared barrier race, resolved on wicks |

## The label: a race over a period, not the next bar

The desk does not trade a bar; it holds from now until H away. So the label is the one a
position actually lives through: barriers at +-1.5 x baseline x sqrt(H), and which is
touched first within H bars. A short model predicts the lower one, a long model the upper.
[`crash-timing.md`](crash-timing.md) had already shown that "a large bar is coming" is a
size label and teaches every model size; this one needs a sign.

`horizons.py`, the top 5% of each side's model, gross R per trade:

| interval | H | short | long |
| --- | --- | --- | --- |
| 15m | 1h | +0.12 +- 0.05 | -0.02 +- 0.05 |
| 15m | 2h | +0.12 +- 0.07 | -0.02 +- 0.07 |
| 1h | 5h | **+0.16 +- 0.05** | -0.05 +- 0.06 |
| 1h | 1h | -0.15 +- 0.03 | -0.13 +- 0.03 |
| 1d | 1d | -0.04 +- 0.03 | -0.14 +- 0.03 |
| 1d | 5d | -0.06 +- 0.08 | +0.06 +- 0.07 |

The one pattern: **intraday short models at 1-5 hours are positive gross in both halves of
the test period, and the matching long models are not.** At 1h/5h it is 2.9 standard errors,
mostly crypto (+0.45) and indices, and the spread assumption costs 0.04-0.07R there. With 24
side-horizon cells, one or two at this level is what chance delivers, so this is a lead to
re-test on the next months of data, not a result.

## Six sharper questions

`horizons.py` asks at every bar, lets market drift leak in, and only knows a 1:1 payoff.
[`questions.py`](../harness/questions.py) removes one of those at a time:

| | question | best net result, any interval | verdict |
| --- | --- | --- | --- |
| Q1 | the current swing travelled S: does it extend 0.5S before giving back 0.5S? | always-continue on daily, +0.001 | **null** - model AUC 0.70-0.73 predicts *whether* it resolves, not which way |
| Q2 | log(A/B) for EURUSD/GBPUSD, AUDUSD/NZDUSD, BTC/ETH, ETH/SOL, US500/NAS100: who wins the race? | daily spread reversion at \|z\| > 2, +0.11 +- 0.06 | **null intraday** - two legs cost 0.17-0.30R; daily reversion is a lead at 2.0 SE |
| Q3 | the race asked only after a reason: a 4x shock, a fresh 50-bar extreme, a breakout, a volatility alarm, a session open | 1h after a 4x up bar, +0.06 | **null** - no event carries a sign at any interval |
| Q4 | +3:-1 and +1:-2 races, long and short, every bar and after reversal events | daily long +3:-1, model top 20%, +0.10 +- 0.04 | **lead** at 2.9 SE; everything intraday negative |
| Q5 | for a long or short intent, does choosing limit vs market per bar pay? | +0.017U on daily shorts | **null** - fill is predictable (AUC 0.57-0.64), the choice is worth nothing |
| Q6 | predict the path's favourable over adverse excursion, trade the extremes | daily, +0.10 +- 0.04 | **lead** at 2.8 SE; Spearman 0.02-0.04 intraday |

**148 scored cells, 58 beyond two standard errors - nearly all of them negative, because costs
are real - and none positive at three with both halves agreeing.** The daily Q4 and Q6
leads are the same trades seen twice (a model preferring bars whose upside path is longer),
which is worth one re-test, not two.

## The defects, which were the only positives

**1. Stops marked at the barrier, not where they filled.** The first `questions.py` resolved
races on closes and booked a stop at exactly -1R and a target at exactly +3R. Closes overshoot
both, and on a +3:-1 bet the stop is crossed three times as often as the target, so the
omission paid the bet. It produced six "survivors" - every +3:-1 bet positive, every +1:-2
negative, which is that bias's fingerprint. Marking exits at the crossing close removed them.

**2. Stops read from closes rather than wicks.** A resting stop is taken by the low that
closes back above it. Every race now resolves in [`bars.py`](../harness/bars.py) on each bar's
high and low, fills at the level (or at the open on a gap), and scores a bar spanning both
levels as the stop. [`crash-timing.md`](crash-timing.md) measures what that changes: stops
are hit about 1.4x as often as closes say.

**3. Yahoo's daily bars leak tomorrow.** With bar-shape features added, the daily long and
short models won **93-94%** of trades at +1.2R. The close location in a yahoo daily FX bar
predicts the next day's return at -0.44; on OANDA it is +0.002. The daily universe moved to
screened sources and `spikerisk.load` now refuses any series that fails the check.
[`crash-timing.md`](crash-timing.md#the-leak-and-a-guard-against-the-next-one) has the numbers.

### The daily long lead died with it

On yahoo data, a gradient-boosted daily long model beat buy-and-hold in 14 of 15 years under a
rolling refit and beat "buy when volatility is high" in 12. It was the strongest result of the
day and it was written up as the one to follow. On clean data ([`dailylong.py`](../harness/dailylong.py)):

| H = 1 day | net R per long | rolling refit beats always-long |
| --- | --- | --- |
| always long | -0.034 +- 0.006 | - |
| model top 5% | **-0.152 +- 0.043** | **2 of 15 years** |
| high volatility top 5% | -0.180 +- 0.036 | - |
| deepest drawdown top 5% | -0.133 +- 0.041 | - |

At 5 and 20 days the model is level with holding (7 of 14 and 6 of 13 years). The earlier
lead was mixing series whose closes are taken at different times, so the cross-asset features
could see across the gap. **The lesson is the same as defect 3: a result that is the best
thing on the page and is concentrated in one data source is a data-source result first.**

## The ensemble: 92 weak views, weighted by their covariance

The desk's framing is that trading is a game of probabilities - several scenarios, each with a
probability, and waiting for enough to line up. [`ensemble.py`](../harness/ensemble.py) builds
that literally. One long and one short model per horizon and per source of information, each
turned into an edge (logit of its probability over its base rate), long minus short:

| family | what it sees |
| --- | --- |
| technical, volatility, bar shape, borrowed fields, calendar, cross-asset, all | the 54 price features, split by origin |
| vix | ^VIX against its 250-day history, its 5-day change, VIX9D/VIX and VIX/VIX3M term structure, VIX over realised S&P volatility - the previous day's close only |
| dollar | a leave-one-out dollar index from the other FX pairs and gold - [`linear-algebra.md`](linear-algebra.md)'s one real factor - and its momentum, signed by exposure |
| flow | order flow inferred from OHLCV: bulk-volume-classified imbalance over 5 and 20 bars, VPIN, accumulation/distribution, signed volume, volume against its history and its hour-of-week, Amihud illiquidity |
| fvg | standing fair value gaps from `training/candles.py`: distance, age and origin wick of the nearest unfilled edge each way, and a gap opened on this bar |
| event models | the same pair trained only after a 4x shock, a fresh extreme, a breakout, a volatility alarm, a session open, or near an unfilled FVG edge - a view on those bars, neutral elsewhere |
| pair spreads | the Q2 models, landing +edge on leg A and -edge on leg B |

Fit on the first 40% of each series, covariance and information coefficients (IC) on the next
20%, traded on the last 40%.

### What the linear algebra says

| | 15m | 1h | 1d |
| --- | ---: | ---: | ---: |
| signals | 69 | 92 | 57 |
| first eigenvalue's share | 7% | 7% | 9% |
| eigenvalues above the Marchenko-Pastur noise edge | 20 | 22 | 15 |
| participation ratio (effective independent views) | 35.8 | 44.9 | 32.5 |
| clusters at \|corr\| > 0.6 | 48 | 68 | 48 |
| best validation IC | +0.055 (vix) | +0.069 (calendar) | +0.071 (vix) |
| IC standard error | 0.024 | 0.019 | 0.025 |

The views are genuinely different - 15 to 22 components carry structure beyond noise and the
signals form 48-68 clusters - so this is not ten copies of one model. And the best validation
ICs are 2.3 to 3.6 standard errors, which is roughly the maximum of 60-90 draws of nothing.

### Six ways to combine them, net R per trade on the test block

| combination | 15m | 1h | 1d |
| --- | ---: | ---: | ---: |
| best single (by validation IC) | -0.126 | -0.006 | -0.045 |
| equal weight | -0.066 | -0.048 | **+0.010** |
| inverse covariance, w ~ S^-1 IC, Ledoit-Wolf shrunk | -0.084 | -0.047 | -0.030 |
| top eigenvectors, weighted by component IC | -0.067 | -0.048 | -0.020 |
| stacked logistic meta-model | -0.094 | -0.041 | -0.044 |
| regime-switched inverse covariance (calm / volatile) | -0.076 | -0.048 | -0.046 |
| *always long / always short* | *-0.074 / -0.109* | *-0.063 / -0.053* | *+0.024 / -0.047* |

(all models, events and pairs included; standard errors 0.012-0.016)

**No combination beats the better of always-long and always-short at any interval.** The
event models and pair spreads each added 20-40 independent views and changed the outcome by
less than a standard error. Markowitz on signals is only as good as the IC vector it inverts,
and an IC of 0.05 measured on 13,000 overlapping bars is mostly noise.

**Waiting for the scenarios to line up never happens.** With 48-68 independent views, 70%
agreement occurred on **0% of test bars** at every interval once the event models joined -
and on the bank alone, where it happened on 1-4% of bars, it did not pay (-0.085, -0.021,
+0.042). Agreement among many independent weak views is rare precisely because they are
independent; when it happens it is not more informed.

### The calendar: the one input that changed outcomes

The news store begins 2026-08-09 - six weeks, shorter than any training block - so it joined as
a gate: on calendar-covered test trades, compare all trades against those whose holding window
contains a high-importance release for the instrument's currencies. Across the 36 combination
rows at 15m and 1h, **trades holding through a release did worse in 32**, by a median 0.19R,
and excluding them changed the row's result by -0.01 to +0.09R. Each row has 8-60 release trades, so no
single cell is significant; the consistency is the finding. It is the direction
[`news-volatility.md`](news-volatility.md) predicts - a release is a volatility event, and a
stop-and-target race with a fixed width is on the wrong side of one.

## What this closes, and what it leaves

* **Directional prediction from bars, their volume, their calendar, VIX, the dollar, pairs,
  gaps and events, individually or combined, does not clear costs on this universe at 15m,
  1h or 1d.** That is a stronger statement than any single null here, because the ensemble
  included every single one.
* **Don't hold a fixed-width position through a scheduled release.** It is the only gate
  that improved every way of combining the models, and it costs nothing to apply.
* **Three leads to re-test on the next months of data, not to trade:** intraday short models
  at 1-5 hours (+0.12 to +0.16R gross, both halves); daily +3:-1 longs from the model's top
  fifth (+0.10R net, 2.9 SE); daily pair-spread reversion at |z| > 2 (+0.11R net, 2.0 SE).
  Each is one of many cells, and each would have to hold out of sample to mean anything.
* **Where the edge is not:** the machinery that finds size - `crash-timing.md`'s
  big-move score, `news-volatility.md`'s calendar, the VIX member - predicts very well. The
  value of this folder's models is in risk and stop width, not in direction.
