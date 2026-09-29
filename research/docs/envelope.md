# The next-N-bars envelope: percentiles that hold their stated rates, and that production now quotes

Measured 2026-09-29 on the lab with [`envelope.py`](../harness/envelope.py): the lab's broker bars at
15m and 1h for 15 FX pairs, XAU and XAG, BTC, ETH and SOL, and every Deriv synthetic family on the
lab - Volatility, Volatility 1s, Jump, Step, Skew Step, Boom, Crash, DEX, Drift Switch and Range
Break - over N = 5, 10, 20 and 50 bars. Everything is scored on the last 40% of each series by time.
**Shipped** as `structures/vol/envelope.py` (commit `6877c41`).

## The question

What is the distribution of price over the next N bars? The ask was to publish P90 ("bullish
ceiling"), P50 ("consensus median") and P10 ("downside support"). It was also to notice when a
stated percentile has drifted, a "P90" covering like a P80, and to correct it as it goes.

## How it was measured

The target is y = log(close[t+N] / close[t]) in units of the production volatility (`ewma_tr_bps`).
There are three forecasters, each also run under **adaptive conformal inference** (ACI; Gibbs and
Candès 2021):
- **gauss:** a normal with one scale fitted on training;
- **empirical:** the quantiles of the last 2,000 resolved moves;
- **gbm:** gradient-boosted quantile regression on volatility, return and hour features.

For each target level q, ACI moves the level actually read, a, by `a <- a + 0.005 (q - hit)` after
each outcome. Feedback arrives N bars late, as it would live.

The scores:
- **coverage:** the share of outcomes below each quantile;
- **pinball loss:** the proper score for a quantile;
- **width;**
- **stability:** P90 coverage in twenty slices of time;
- **conditional coverage:** in calm, normal and volatile thirds;
- **direction:** the AUC of the P50 for the sign of the move.

## 1. Five bars: calibrated, and the correction does what was asked

FX at 15m (metals, crypto and 1h tell the same story):

| | P10 / P50 / P90 hit | pinball P10 / P90 | width | P90 across time (sd, worst) | P90 calm / normal / volatile |
| --- | --- | --- | --- | --- | --- |
| gauss | 7.3 / 49.5 / 93.2% | 0.306 / 0.287 | 4.26 | 0.6%, 92.4% | 91.8 / 93.5 / 94.3% |
| gauss + ACI | **10.0 / 50.0 / 90.1%** | 0.304 / 0.284 | 3.63 | 0.1%, 90.0% | 88.2 / 90.3 / 91.7% |
| empirical | 10.2 / 50.1 / 90.0% | 0.302 / 0.281 | 3.55 | 0.2%, 89.6% | 88.4 / 90.2 / 91.3% |
| empirical + ACI | **10.0 / 50.0 / 90.0%** | 0.307 / 0.286 | 3.68 | **0.0%, 89.9%** | 88.0 / 90.3 / 91.7% |
| **gbm** | 10.5 / 49.9 / 90.3% | **0.289 / 0.264** | 3.49 | 0.8%, 88.9% | **90.5 / 90.5 / 89.8%** |
| gbm + ACI | 10.1 / 50.0 / 90.0% | 0.291 / 0.267 | 3.55 | 0.1%, 89.9% | 89.8 / 90.2 / 90.0% |

- **A Gaussian band is miscalibrated.** Real moves are fat-tailed and peaked, so its P90 is hit 93%
  of the time. That is exactly the drift the question describes.
- **ACI pins every stated rate** to within 0.1 point in every market, and narrows the Gaussian band by
  15%.
- **Gradient boosting is the best forecaster.** It has the lowest pinball loss, and it is the only one
  whose P90 holds in calm and volatile regimes alike. ACI fixes the average coverage, not the
  split by regime.
- **On random walks every method is calibrated.**

## 2. Horizons and families: where it holds, and how the band grows with N

P90 coverage of the empirical envelope under ACI, the configuration production ships:

| | N = 5 | 10 | 20 | 50 |
| --- | --- | --- | --- | --- |
| every family, 15m and 1h | 90.0-90.1% | 89.9-90.1% | 89.4-89.8% | **87.4-88.3%** |
| worst of twenty time slices | 88.8-89.9% | 88.1-89.9% | 87.2-89.4% | **80.9-87.3%** |

(P10 mirrors it: 10.0% at 5 and 10 bars, 10.2-10.5% at 20, and 11.6-12.4% at 50.)

- **It holds at 5 and 10 bars in all thirteen groups**, synthetics included. At 20 bars it is off by
  about 0.4 of a point. At 50 it slips by two, and some slices by nine. The correction learns N bars
  late, and fifty bars of overlapping outcomes is more lag than a 0.005 step can keep up with.
- **Production quotes N = 5 and 20.** A 50-bar band would need a faster step, or a margin.
- **Gradient boosting has the best pinball loss in 90 of 104 cells.** A plain Gaussian wins the rest,
  which are the exact random walks, where it is the true law.

**Width / √N**, a profile of how the band grows with the horizon (empirical, 15m):

| | N = 5 | 10 | 20 | 50 |
| --- | --- | --- | --- | --- |
| Volatility / Volatility 1s / Step / Skew Step | 1.66 / 1.64 / 1.65 / 1.66 | 1.65 / 1.64 / 1.64 / 1.67 | 1.65 / 1.64 / 1.64 / 1.68 | 1.64 / 1.65 / 1.62 / 1.68 |
| Jump / Boom / Crash | 1.80 / 2.06 / 2.06 | 1.81 / 2.06 / 2.07 | 1.81 / 2.07 / 2.08 | 1.81 / 2.08 / 2.06 |
| **FX / metals / crypto** | 1.59 / 1.58 / 1.55 | 1.59 / 1.65 / 1.59 | 1.63 / 1.75 / 1.68 | **1.71 / 1.85 / 1.75** |
| DEX / Drift Switch / Range Break | 2.38 / 2.17 / 2.86 | 2.43 / 2.20 / 3.17 | 2.47 / 2.22 / 3.27 | 2.48 / 2.22 / 3.35 |

- **The random-walk synthetics are flat.** They scale exactly as √N, as their published generators
  say ([`generators.md`](generators.md)).
- **Real markets widen faster than √N:** by 8% (FX), 17% (metals) and 13% (crypto) from 5 to 50 bars.
  A band scaled on today's volatility understates the long end, because volatility drifts back
  toward its own normal over longer horizons. Range Break widens fastest, which fits its range and
  break structure ([`deriving.md`](deriving.md)).

**P50 direction** (gradient boosting, AUC of the median for the sign of the move) is 0.49-0.51 on
the Volatility, Step, Skew Step, Jump, Boom and Crash indices. It sits above 0.5 only where the
generator is known to have structure: Range Break 0.585, DEX 0.551 and Drift Switch 0.537 at 5 bars
(15m). It is also 0.549 on FX at 15m, falling to 0.515 by 50 bars. None of that has paid its costs in
any earlier test here, so the P50 is a median, not a call.

## What shipped

`structures/vol/envelope.py`, fed on every closed bar per (feed, interval):
- the **empirical** envelope under **ACI** (fully online, no offline training), at N = 5 and 20;
- published as `env5_*` and `env20_*` on every level call's context: the P10 / P50 / P90 prices, each
  one's realised cover, the band width in bps, and the reference price;
- printed on the **level alert and the trade fill card** by one shared `card_lines`, with the
  realised P90 cover beside the quote, plus a compression / expansion line from `tr_percentile`.

It decides nothing. The next step, when it is worth the machinery, is the boosted model, which is
calibrated across regimes where the empirical one is only calibrated on average.
