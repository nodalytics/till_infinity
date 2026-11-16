# Everything in ATR units, and two models that learn nothing

**Measured 2026-11-15.** Five majors, 15m bars, 2018-11 to 2026-11, 988,607
rows. A ridge regression and gradient-boosted trees on eighteen
ATR-normalised features, predicting the forward 16-bar move in ATR.

## The normaliser

Every feature is divided by the bar's own ATR and the target is a move in ATR,
so one model sees five instruments and eight years without the loud ones
drowning the quiet. That is justified by measurement rather than taste -
[`reactive-zones.md`](reactive-zones.md) finds ATR is **twice the mean
close-to-close move in every instrument-frame cell tested**, and that the shape
of its distribution is stable across years while its level doubles.

Eighteen features, all known at the bar's close: body, range and both wicks
over ATR; where in its range the bar closed; net displacement at 1, 4, 16 and
96 bars; path-over-net roughness at each reach; distance to the trailing
96-bar high and low; the ATR regime quantile; ATR(30) over ATR(480); and the
hour as a sine and a cosine.

## The result: nothing, in two disjoint windows with opposite signs

| | test 2024-11 to 2026-11 | test 2022-11 to 2024-11 |
|---|---:|---:|
| ridge, edge | +0.0111 | +0.0069 |
| ridge, its own shuffled floor | -0.0025 +/- 0.0099 | **+0.0144 +/- 0.0104** |
| gradient boosting, edge | **+0.0385** | **-0.0237** |
| boosting, its own shuffled floor | +0.0013 +/- 0.0158 | +0.0103 +/- 0.0169 |
| ridge AUC / boosting AUC | 0.4928 / 0.5087 | 0.4912 / 0.4945 |

On the recent window boosting sits about **2.3 standard deviations** above its
floor; on the earlier one it is **1.4 below** it, with four of five instruments
negative. Ridge is below its own floor on the earlier window. AUC is 0.49 to
0.51 throughout, which is no ranking ability at any point.

**In sample, boosting reads +0.3106 and +0.3976** against out-of-sample
figures of +0.0385 and -0.0237. It memorises three quarters of a million rows
and generalises none of it.

## What the first run called skill was gold's drift

Each instrument's unconditional forward move, over the training years:

| EURUSD | GBPUSD | GOLD | USDJPY | AUDUSD |
|---:|---:|---:|---:|---:|
| -0.0251 | -0.0072 | **+0.0879** | **+0.0524** | -0.0163 |

Gold's forward 16-bar move averaged nearly a tenth of an ATR. Before that was
removed, the shuffled-target floor read **+0.0220 ATR** - a model trained on
noise, scoring positive, because being long gold paid over the window. With
the drift taken out **using the training period's mean only**, the floor falls
to -0.0025 +/- 0.0099.

That is the whole reason the floor is drawn at all, and the reason it is drawn
**eight times**: one permutation is one draw, and the test rows are nowhere
near independent - the targets overlap by sixteen bars and cluster in days, so
243,798 rows carry the information of perhaps 2,500.

## Where it goes blind

A drift of known size planted on a fixed random direction in feature space,
added to train and test alike:

| planted | ridge edge | recovered | boosting edge | recovered |
|---:|---:|---:|---:|---:|
| 0.000 | +0.0111 | - | +0.0385 | - |
| 0.020 | +0.0125 | **7%** | +0.0383 | **0%** |
| 0.050 | +0.0284 | **35%** | +0.0477 | 18% |

**AUC does not move at all** - 0.492 and 0.507 at every plant size - which is
its own lesson about reporting AUC on a continuous target.

So the null has a size attached: **this harness cannot see an effect of 0.02
ATR and recovers about a third of 0.05.** Against a floor whose spread is
0.010 to 0.016, detection needs something around **0.05 to 0.10 ATR**.

For scale, the median 15m spread on these instruments is **0.011 to 0.041
ATR**. The smallest effect this experiment could detect is therefore about the
size of the spread, and anything smaller is both invisible here and marginal
after costs. A directional edge below that is not excluded by this run - it is
beneath its resolution.

## What this closes, and what it does not

**Closed:** that bar geometry expressed in ATR units carries directional
information a standard regressor or a gradient-boosted tree can find at this
horizon. Two disjoint windows, opposite signs, no ranking ability, and a
complete failure to generalise from 745,000 training rows. That is consistent
with `direction-is-closed-not-just-null`, reached independently through a
different representation.

**Not closed:** the normaliser itself, which did its job - one model spanning
five instruments and eight years, and the drift decomposition above is only
legible because everything was in the same units. What it equalises is scale,
and there is no directional signal underneath for it to expose.

**Not attempted:** volatility as a *target* rather than a feature. The regime
work in [`reactive-zones.md`](reactive-zones.md) measures real day-horizon
persistence - log-ATR autocorrelation of 0.68 to 0.88 at five days against
-0.03 to +0.12 shuffled - and this desk already forecasts risk better than it
forecasts direction. A model predicting ATR rather than return would be asking
the question this data answers.
