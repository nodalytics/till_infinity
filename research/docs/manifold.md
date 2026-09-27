# The market state manifold has regions, and they are the clock and the volatility

Measured 2026-09-27 on the lab with [`manifold.py`](../harness/manifold.py) (`PART=follow` for the
second half): the states of [`state-and-memory.md`](state-and-memory.md), for 20 real instruments
and four exact random walks from the Deriv synthetics as the control. The bases are 15m (1h and 4h
above) and 1h (4h and 1d above), about 590,000 moments each, with a horizon of H = 16 bars.

Rules throughout:
- everything is fit on each series' first 60% by time and scored on the last 40%;
- trades are non-overlapping and net of spread, with both halves reported and a common-offset
  null.

## The question

This is the seventh direction of the research program behind the three draft papers:

> Do financial markets exhibit recurring regions in state space with statistically
> distinguishable transition distributions?

**A state** is the fractal embedding: 32 bars of return, range and close location on each of three
timeframes, over the trailing baseline move - 288 numbers. **Regions** are k-means clusters with
K = 8, 32 and 128, fit on 16 principal components of the real training states; the random walks
are assigned to the same regions.

## 1. The cloud is low-dimensional, and so is a random walk's

Intrinsic dimension by TwoNN on 20,000 training states, 15m / 1h:

| | TwoNN dimension | a Gaussian with the same covariance | variance in 16 components |
| --- | ---: | ---: | ---: |
| real markets | 20.1 / 22.8 | 98.2 / 99.2 | 0.23 / 0.22 |
| random walks | **12.3** / **12.3** | 90.9 / 91.3 | 0.24 / 0.22 |
| FX alone | 15.8 / 18.1 | | |
| metals alone | 5.6 / 5.7 | | |
| crypto alone | 6.5 / 8.4 | | |

The states lie on something like a 20-dimensional surface inside 288 dimensions, far below the
Gaussian's 90-99. That sounds like a market manifold, but **the random walks' states lie on a
lower-dimensional one still**. Low dimension is a property of how windows of any price path are
built - consecutive returns, ranges and close locations constrain each other - not a structure
that markets add. What real markets add is spread: volatility regimes, sessions and gaps push
their states over more of the surface.

**Clustering does separate real from random.** k-means inertia against that of a same-covariance
Gaussian (1.0 means no more clustered than a Gaussian):

| K | real, 15m / 1h | random walks |
| --- | --- | --- |
| 8 | 0.958 / 0.968 | 0.999 / 0.996 |
| 32 | 0.892 / 0.907 | 0.989 / 0.996 |
| 128 | 0.860 / 0.858 | 0.978 / 0.980 |

Real states pack 3-14% tighter than a Gaussian; random walks pack 0-2% tighter. Markets do have
regions.

## 2. The regions recur, and they are not instruments - they are the clock

Every region is occupied on the test block. The total-variation distance between each region's
share of the training block and its share of the test block is 0.027-0.046 at 15m and
0.029-0.079 at 1h: **the regions recur**.

Normalised mutual information between region and label, real test block:

| | family | symbol | hour of day |
| --- | --- | --- | --- |
| 15m, K = 8 / 32 / 128 | 0.004 / 0.006 / 0.008 | 0.010 / 0.016 / 0.024 | **0.126 / 0.122 / 0.129** |
| 1h, K = 8 / 32 / 128 | 0.003 / 0.011 / 0.012 | 0.006 / 0.019 / 0.024 | **0.110 / 0.093 / 0.095** |

A region is shared across instruments. What it tracks, four to eighteen times more strongly
than the instrument, is **the hour**. The embedding is normalised by the trailing baseline move, so the
intraday volatility cycle - quiet Asia, the London open, the New York overlap - is what it sees
first.

## 3. The transitions are distinguishable, and they are the clock, volatility and overlap

Region now, then the same series' region 16 or 64 bars later. The information gain of the training
transition matrix over the training occupancy is scored on the test block in bits (first run):

| | real, after 16 / 64 bars | random walks, after 16 / 64 bars |
| --- | --- | --- |
| 15m, K = 8 | 0.767 / 0.284 | 0.216 / 0.023 |
| 15m, K = 32 | 1.340 / 0.473 | 0.517 / -0.043 |
| 15m, K = 128 | 1.759 / 0.419 | 0.351 / -0.599 |
| 1h, K = 8 | 0.722 / 0.466 | 0.178 / 0.035 |
| 1h, K = 32 | 1.226 / 0.614 | 0.401 / -0.110 |
| 1h, K = 128 | 1.675 / 0.560 | 0.090 / -0.648 |

**Transitions out of each region differ, and far more for markets than for random walks.** At 16
bars the random walks gain too, 0.09-0.52 bits. That is mechanical: a state and the state 16 bars
later share most of their higher-timeframe windows. At 64 bars the random walks' gain falls to
zero or below, while real markets keep 0.28-0.61 bits.

What is in those bits: the next region, test log loss in bits (real, lower is better). "Clock" is
the hour of the next moment, known in advance; "vol" is the volatility decile now:

| | occupancy | clock | clock + vol | region | region + clock + vol |
| --- | ---: | ---: | ---: | ---: | ---: |
| 15m, K = 8, after 16 | 2.996 | 2.581 | 2.373 | 2.140 | 1.856 |
| 15m, K = 8, after 64 | 2.963 | 2.581 | 2.461 | 2.593 | 2.290 |
| 15m, K = 32, after 16 | 4.976 | 4.432 | 4.195 | 3.659 | 3.340 |
| 15m, K = 32, after 64 | 4.929 | 4.460 | 4.324 | 4.445 | 4.098 |
| 1h, K = 8, after 16 | 2.989 | 2.605 | 2.423 | 2.126 | 1.945 |
| 1h, K = 8, after 64 | 2.990 | 2.597 | 2.498 | 2.544 | 2.314 |
| 1h, K = 32, after 16 | 4.988 | 4.591 | 4.380 | 3.741 | 3.541 |
| 1h, K = 32, after 64 | 4.991 | 4.618 | 4.482 | 4.418 | 4.188 |

- **After 64 bars, where window overlap has faded:** the clock alone gives 0.37-0.47 bits, and
  volatility adds 0.10-0.14. The region alone gives about as much as the clock plus volatility
  (0.37-0.57 bits), and on top of both it adds 0.17-0.29 bits.
- **After 16 bars** the region adds 0.48-0.86 bits beyond clock and volatility. Much of that is the
  shared-window persistence that the random walks also show.

What the region adds beyond the clock and one volatility decile is what a volatility state across
three timeframes would add, and section 4 shows that size is what it forecasts.

## 4. Distinguishable outcomes: size yes, direction no

Each region's training mean of the move over 16 bars, of its size, and of the asymmetry
P(reach +2 moves) - P(reach -2 moves) was compared with the same means on the test block. The
first three columns give Spearman across regions (train against test); the moment-level columns
use the region's training mean as the forecast:

| real (random walks) | signed move | \|move\| | up-down asymmetry | \|move\| at moment level | beyond vol | direction AUC |
| --- | --- | --- | --- | --- | --- | --- |
| 15m, K = 8 | +0.57 (-0.43) | **+0.90** (+0.29) | +0.83 (-0.36) | +0.113 | +0.072 | 0.508 |
| 15m, K = 32 | -0.05 (-0.14) | **+0.95** (+0.22) | +0.53 (-0.08) | +0.136 | +0.070 | 0.506 |
| 15m, K = 128 | +0.02 (+0.00) | **+0.91** (+0.10) | +0.48 (-0.16) | **+0.150** | **+0.094** | 0.504 |
| 1h, K = 8 | +0.17 (+0.07) | **+0.98** (+0.02) | +0.10 (-0.64) | +0.108 | +0.025 | 0.500 |
| 1h, K = 32 | +0.28 (+0.00) | **+0.94** (+0.18) | +0.31 (-0.07) | +0.117 | +0.028 | 0.501 |
| 1h, K = 128 | -0.10 (-0.31) | **+0.92** (+0.10) | +0.11 (-0.24) | +0.124 | +0.027 | 0.497 |

(the volatility ratio alone ranks |move| at +0.106 at 15m and +0.126 at 1h)

- **Size is a stable property of a region.** Each region's mean |move| ranks the same on the test
  block as on training at +0.90 to +0.98, against at most +0.29 for the random walks. As a
  forecast it beats the volatility ratio at 15m (+0.150 against +0.106) and keeps +0.07 to +0.09
  beyond it. At 1h it is at or just below the ratio (+0.108 to +0.124 against +0.126).
- **Direction is not a property of any region.** The signed move does not hold its ranking across
  regions once there are more than eight, and the moment-level AUC is 0.497-0.508. **No region, at
  any K, has a training drift with |t| > 3.** Trading each region's training drift (top and bottom
  20%) loses at every K: -0.32 to -0.49 at 15m and -0.11 to -0.13 at 1h, with z between -1.3 and
  +1.5.

**The one directional residue is at 15m, and it does not pay.** The asymmetry of reaching +2 before
-2 keeps its ranking across regions at +0.48 to +0.83. It is concentrated in a few regions that
lean down: training -0.130 and -0.093, test -0.207 and -0.115 at K = 32. It correlates with
directional efficiency at -0.08 to -0.12, so it is the intrabar mean reversion that
[`physics.md`](physics.md) measured in FX, seen from the state side. Traded with symmetric ±2
barriers resolved on wicks (a bar reaching both counts as the stop), long in the training block's
top 20% of region asymmetry and short in its bottom 20%:

| | gross win rate | net per trade | halves | z vs shifted null |
| --- | --- | --- | --- | --- |
| 15m, K = 8 | 53.6% | -0.257 +- 0.017 | -0.267 / -0.249 | **+2.5** |
| 15m, K = 32 | 51.9% | -0.327 +- 0.018 | -0.323 / -0.330 | +1.1 |
| 1h, K = 8 | 48.3% | -0.269 +- 0.018 | -0.231 / -0.313 | -1.0 |
| 1h, K = 32 | 48.4% | -0.267 +- 0.019 | -0.213 / -0.324 | -0.8 |
| *reference: fade velocity, 15m / 1h* | *49.0% / 50.0%* | *-0.438 / -0.199* | | *-0.6 / +1.5* |

At 15m with K = 8 the lean is real, and the only cell here to clear the null at z > 2. It wins
53.6% of symmetric bets against the random walks' 50.6%, and loses 0.26 of a baseline move per
trade after a spread it cannot cover. It is gone at K = 32 and at 1h. This is the same finding as
[`barrier-geometry-is-irrelevant.md`](barrier-geometry-is-irrelevant.md) and the OU spring: a
restoring force that is real and smaller than the spread.

## What this settles

- **Yes, markets have recurring regions in state space with distinguishable transitions.** Real
  states cluster where random walks do not, the regions recur out of sample, and region-to-region
  transitions carry 0.3-0.6 bits at 64 bars where the random walks carry none.
- **The regions are the intraday clock and multi-timeframe volatility.** The hour explains 4-18
  times more of a region than the instrument does. The clock and a volatility decile account for
  about half of the transition information at 16 bars and two thirds at 64, and each region's |move| is stable at +0.90 to
  +0.98 across the split.
- **The low dimension is not a market property.** A random walk's states have a lower intrinsic
  dimension (12) than the market's (20-23).
- **No region has a direction.** No training drift reaches |t| > 3, the signed move does not
  replicate, and every trade on a region loses. The 15m asymmetry clears its null and loses 0.26
  per trade to the spread.
- **Use:** a region's |move| is a volatility forecast slightly better than the volatility ratio at
  15m, which is the use every positive on this desk has had - sizing.
