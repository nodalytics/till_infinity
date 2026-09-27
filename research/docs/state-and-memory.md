# State beats memory, and the two together beat neither: the papers' program, measured

Measured 2026-09-27 on the lab with [`program.py`](../harness/program.py): 20 real instruments
(15 FX pairs, XAU, XAG, BTC, ETH, SOL) and four exact random walks from the Deriv synthetics as
the control, at a 15m base (1h and 4h above it) and a 1h base (4h and 1d), about 590,000 moments
per base, horizon H = 16 bars.

Rules throughout:
- everything is fit, remembered or tuned on each series' first 60% by time and scored on the
  last 40%;
- a historical twin is never taken from the same series within H bars of the moment asking, so
  no twin's future overlaps the query's;
- trades are non-overlapping and net of spread, with both halves of the test reported and a
  common-offset null.

## The question

Three draft papers (kept outside the repository) propose one model in three parts:
- **Paper 1:** the current market state - how far, how fast, how directional, how large the
  zone - gives each candidate price zone a probability of being reached.
- **Paper 2:** historical twins - past moments whose multi-timeframe shape matches now - give an
  empirical version of the same probability.
- **Paper 3:** the two combine, and the test is a decomposition. M0 is a baseline, M1 is state
  only, M2 is memory only and M3 is both. If M3 does not beat M1 and M2 on untouched data, the
  combination is not justified.

A follow-up proposed seven research directions. Six are measured here; the seventh, a state
manifold, is not.

**Zones.** Around every moment:
- a grid of levels at +-1, 2, 3, 4, 6 and 8 baseline moves, which is the paper's continuous
  probability field;
- the nearest untaken 50-bar swing high and low (liquidity zones), sized by how many highs or
  lows cluster at them.

"Reached" means a wick touches the level within 16 bars.

**The models:**
- **M0 physics:** the reflection-principle first passage of a random walk, with no fitted
  parameter.
- **M1 state:** gradient boosting on distance, zone kind and size, speed, directional efficiency
  and velocity toward the zone, the volatility ratio and the hour.
- **M2 memory:** the share of the 50 nearest fractal twins (32 bars on each of three timeframes)
  that reached the same distance on the same side.
- **M3 combined:** M1's inputs plus M2's evidence.

## 1. The decomposition: M3 does not beat M1

Test block, real markets (random walks in brackets), P(zone reached within 16 bars):

| | 15m log loss | Brier | AUC | 1h log loss | Brier | AUC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| M0 physics, no fit | 0.5794 (0.5462) | 0.1979 | 0.790 | 0.5634 (0.5457) | 0.1913 | 0.798 |
| **M1 state only** | **0.5301** (0.5328) | **0.1777** | **0.807** | **0.5351** (0.5292) | **0.1796** | **0.805** |
| M2 memory only | 0.5479 (0.5374) | 0.1840 | 0.794 | 0.5469 (0.5373) | 0.1839 | 0.796 |
| M3 combined | 0.5436 (0.5400) | 0.1827 | 0.797 | 0.5466 (0.5375) | 0.1840 | 0.796 |

**State alone is the best model at both bases, and adding memory makes it worse.** Both learned
models beat the formula with no parameters:
- M1 cuts log loss by 0.049 at 15m. It cuts the random walks' by only 0.013, so about 0.036 is
  market structure (volatility clustering and the hour) rather than calibration of a formula to
  bar-sampled wicks.
- M2 gets about 60% of M1's gain (0.032 at 15m, 0.017 at 1h).
- M3 lands between them: adding the twins' evidence to M1's inputs costs 0.014 of log loss at
  15m and 0.012 at 1h. Fifty twins' hit share is a noisy restatement of what distance and
  volatility already say, and the model gives it weight it does not earn out of sample.

By Paper 3's own falsification criterion, "the combined model fails to beat appropriate
baselines on untouched data", **the combination is unsupported**.

Both are honest where it matters most, in the top bin (predicted at least 0.95):

| | 15m predicted / realised (n) | 1h |
| --- | --- | --- |
| M1 | 0.975 / 0.973 (7,865) | 0.977 / 0.978 (8,825) |
| M3 | 0.976 / 0.964 (8,950) | 0.977 / 0.973 (9,267) |

**One correction before these numbers.** The first run let training moments find their own
twins in the same block. A moment's nearest match is itself or a neighbour a few bars away, whose
future overlaps its own. That run's M3 was worse than M0, with a top bin predicted at 0.969 and
realised at 0.884, and 21% of its fields had a spurious interior peak. Excluding same-series twins
within H bars (as Paper 2's protocol asks) fixed all three. The numbers here are from the fixed
run.

## 6. The probability field has no direction and almost never has a peak

Take the 12 grid probabilities as a field on each side. Two questions:
- **Does its skew (up side minus down side) call direction?**
- **Does it ever have an interior maximum, a level more likely than the nearer ones?** That
  would be a "zone of attraction" rather than distance.

| direction AUC of the skew, real (control) | 15m | 1h |
| --- | --- | --- |
| M0 physics | 0.500 (0.500) | 0.500 (0.500) |
| M1 state | 0.530 (0.496) | 0.505 (0.494) |
| M2 memory | 0.504 (0.497) | 0.504 (0.500) |
| M3 combined | 0.510 (0.496) | 0.506 (0.499) |

Traded (long above the training block's 80th percentile of skew, short below its 20th), real
markets, net per trade in baseline moves:
- **M1:** -0.471 at 15m (z -1.2) and -0.102 at 1h (z +1.2).
- **M3:** -0.420 at 15m (z -0.3) and -0.128 at 1h (z +0.9).

The 15m M1 skew's 0.530 is the most anything in this program says about direction. It is worth
nothing after the spread, and at 1h it is 0.505.

**Interior peaks** appear on 0% of physics fields, as they must, and on 1.24% (15m) and 0.95%
(1h) of M3's. The field is monotone in distance. There is no level that price is "drawn to" more
than the nearer ones.

## 2. Hazard: time to a zone is predictable, and every method agrees

The hazard model is a discrete-time model of P(first touch at bar t | not before). It is gradient
boosting on the M3 inputs plus t, and its cumulative curve gives P(reached within t). Real
markets, log loss:

| within | base rate 15m | physics | twins' own curve | direct model at t | hazard model |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4 bars, 15m | 22.8% | 0.4271 | 0.3992 | **0.3789** | 0.3841 |
| 8 bars, 15m | 32.6% | 0.5175 | 0.4860 | **0.4705** | 0.4729 |
| 16 bars, 15m | 44.2% | 0.5781 | 0.5490 | 0.5423 | **0.5411** |
| 4 bars, 1h | 23.8% | 0.4277 | 0.4010 | **0.3876** | 0.3923 |
| 8 bars, 1h | 34.2% | 0.5106 | 0.4867 | **0.4790** | 0.4801 |
| 16 bars, 1h | 46.3% | 0.5627 | 0.5486 | 0.5459 | **0.5445** |

The one hazard model does as well as three separate direct models, to within 0.006. Physics is
the worst everywhere, and the twins' empirical curve sits between physics and the fitted models.
The hazard model's expected time to the zone, given that it is reached, ranks the realised time at
Spearman **+0.546** (15m) and **+0.553** (1h). The twins' median time scores +0.505 and +0.509,
and distance alone +0.492 and +0.501. **Most of "when" is distance, and the model adds about 0.05
to it.**

## 3. Entropy: a volatility forecast, not a direction

Normalise the 12 grid probabilities (M3) into a distribution over destinations, and take three
measures:
- its Shannon entropy H;
- the change dH since the previous moment;
- the ratio R of the top two probabilities.

Spearman correlation with the size of the move over the next 16 bars, then that correlation
with the residual of |move| after a linear fit on the log volatility ratio ("beyond vol"), then
AUC for an up-move:

| real (control) | 15m: \|move\| | beyond vol | up AUC | 1h: \|move\| | beyond vol | up AUC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| entropy H | **+0.222** (+0.005) | **+0.137** | 0.510 | +0.152 (+0.007) | +0.033 | 0.500 |
| change dH | +0.044 | +0.058 | 0.508 | +0.052 | +0.052 | 0.500 |
| top-two ratio R | -0.073 | -0.039 | 0.497 | -0.052 | +0.002 | 0.501 |
| *volatility ratio alone* | *+0.107* | | | *+0.128* | | |

A flat field, where many destinations are about equally reachable, precedes a large move. At 15m
entropy is a better predictor of move size than the volatility ratio itself, and it keeps +0.137
of rank correlation after the ratio is removed. That is expected: the field is fitted on
speed, efficiency and the volatility ratio together, so its entropy is a learned volatility
index. It is zero on the random walks and it says nothing about which way (0.497-0.510).

## 4. Memory decay: there is none

Twins here come from **all history before the query**, with an H-bar embargo, pooled across
instruments. The 500 most similar are re-weighted by recency with half-lives of 1 week, 1 month,
6 months, 2 years and infinite. The half-life is chosen on the first half of the test period and
reported on the second. Two scores: the Spearman between the twins' weighted |move| and the
realised one ("size"), and the direction AUC ("dir").

Second half of the test period (the report), real markets:

| half-life | 15m size / dir | 1h size / dir |
| --- | --- | --- |
| 1 week | +0.107 / 0.502 | +0.031 / 0.508 |
| 1 month | +0.171 / 0.499 | +0.055 / 0.508 |
| 6 months | +0.221 / 0.502 | +0.110 / 0.509 |
| 2 years | +0.228 / 0.501 | +0.137 / 0.509 |
| **infinite** | **+0.229** / 0.500 | **+0.144** / 0.506 |

**Infinite memory is chosen on the first half and wins on the second.** It wins in calm and
volatile regimes alike at both bases (calm +0.205 and +0.105, volatile +0.232 and +0.128). The
size signal rises monotonically with memory length, and nothing is gained by forgetting. That
fits the long-memory Hurst exponents on |returns| in
[`fractal-twins.md`](fractal-twins.md): old volatility states are as informative as recent ones.
Direction is 0.499-0.516 in every cell, in every regime, at every half-life.

## 5. The impossibility region: calibratable, and no better as a stop

The 95% boundary of adverse excursion over 16 bars (how far price can go against a long or a
short) is estimated three ways, and scored by the share of outcomes past it (target 5%) and its
median width in baseline moves:

| real (control) | 15m long | 15m short | 1h long | 1h short |
| --- | --- | --- | --- | --- |
| twins, 95th percentile | 7.9% (5.8%), 10.66 | 7.3% (6.3%), 10.01 | 7.5% (6.3%), 10.82 | 6.9% (5.9%), 10.44 |
| Gaussian from EWMA sigma | 4.5% (1.5%), 13.04 | 3.5% (1.5%), 13.04 | 4.1% (1.8%), 13.08 | 3.2% (1.5%), 13.08 |
| **quantile gradient boosting** | **6.1%** (2.1%), 11.43 | **5.3%** (2.8%), 10.87 | **6.2%** (3.5%), 11.11 | **5.1%** (3.5%), 11.12 |

- **Twins are too narrow:** 50 neighbours cannot estimate a 95th percentile.
- **The Gaussian is too wide:** 13 moves to achieve what the quantile model does in 11.
- **The quantile model is closest:** within 1.2 points of the target at about 11 moves.

**As a stop it is worth nothing.** Place the stop on the boundary, against a fixed stop of the
same median width, at equal money at risk, and hold for 16 bars:

| | stopped (boundary / fixed) | mean R (boundary / fixed) | worst 1% |
| --- | --- | --- | --- |
| 15m long, quantile | 6.2% / 6.5% | -0.037 / -0.036 | -1.04 / -1.04 |
| 15m short, quantile | 5.4% / 5.9% | -0.036 / -0.035 | -1.04 / -1.04 |
| 1h long, quantile | 6.2% / 7.2% | -0.012 / -0.013 | -1.02 / -1.02 |
| 1h short, quantile | 5.1% / 5.8% | -0.021 / -0.020 | -1.02 / -1.02 |

(the twins' boundary is the same within 0.004R.)

The state-aware boundary is stopped out a little less often and earns the same. That is
[`barrier-geometry-is-irrelevant.md`](barrier-geometry-is-irrelevant.md) again: a better-placed
stop changes the win rate, not the expectancy.

## What this settles

- **Paper 1** holds as a probability model: the current state predicts whether a zone is reached
  better than physics, and calibrated. But the gain is volatility and distance, as in
  [`zone-fill.md`](zone-fill.md), and it has no direction.
- **Paper 2**'s twins carry real information about *size* and *time*, and their memory does not
  decay. As a probability model they lose to the state model, and they have no direction.
- **Paper 3**'s combination fails its own falsification test. M3 does not beat M1 at either base.
- **Entropy** of the field is a strong short-horizon volatility index. It is the one new signal
  here, and like every volatility signal on this desk its use is sizing, next to the spike switch.
- Nothing in the program trades. The best directional reading, the 15m state skew at AUC 0.530,
  loses 0.47 of a baseline move per trade after costs.
