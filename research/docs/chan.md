# Ernest Chan's strategies on this desk: stationarity filters, Kalman cointegration, time-series momentum

Harness: [`research/harness/chan.py`](../harness/chan.py). Lab run 2026-09-30.

Built from the methods of Ernest Chan's *Algorithmic Trading: Winning Strategies and Their
Rationale* (2013). The PDF the user linked was not used; it appeared to be an unauthorized copy.

## The question

Chan's book argues for trading mean reversion where a series is stationary and momentum where it
trends. Its core tools are:

- stationarity tests (ADF, Hurst, the variance ratio);
- cointegration with Kalman-filter hedge ratios;
- time-series momentum;
- roll returns;
- Kelly sizing;
- stops for momentum but not for mean reversion.

Several of its ideas were already tested here, and are cited rather than redone:

| idea | doc | result |
|---|---|---|
| pairs and co-movement | `comovement` | failed on the controls |
| mean reversion to a moving average | [`zma-ml.md`](zma-ml.md) | ML adds nothing |
| Bollinger and other lagging triggers | [`indicators.md`](indicators.md), [`stophunt.md`](stophunt.md) | no trigger beats the touch |
| gap strategies | [`gaptrade.md`](gaptrade.md) | the Sunday spread eats the reversal |
| rollover interest | [`carry.md`](carry.md) | the broker keeps the carry |
| news drift | [`surprise.md`](surprise.md) | priced within 3 minutes |
| stop width | [`widestop.md`](widestop.md) | a wider stop is a smaller trade |

This study tests what was left.

## Method

Everything is walk-forward: fitted or chosen on the first 60% by time, scored on the last 40%, with
both halves of the test reported. Costs are COST_V (FX 0.8, metals 0.16, crypto 0.5, Deriv and walks
0.15, in units of a 5-minute sigma). Controls are walks we generate. Deriv is scored as a market.
The pre-registered pass bar is a net Sharpe of at least 0.5 out of sample, positive in both halves,
Benjamini-Hochberg across all 36 tests, and no pass on the walks.

1. **Stationarity as a regime filter.** Production's zone touches come from the saved Engine replay
   (`indicators.py`): 165,629 touch rows over FX, metals, crypto, Deriv and walks, at H = 5 and 20.
   Each is split by the variance ratio VR(8) of the last 200 bars' log closes: **reverting** if
   VR < 0.9, **trending** if VR > 1.1. The Hurst exponent correlates +0.87 to +0.90 with VR, so the
   two tell the same story; a Dickey-Fuller t is recorded too. Chan's claim is that fading should pay
   in the reverting regime and breaking in the trending one.
2. **Stops and mean reversion.** Chan argues stops hurt mean reversion. Fades in the reverting
   regime are run with a 1-vol stop and compared with the same fades held to H = 20.
3. **FX cointegration with a Kalman hedge.** The pairs are AUDUSD/NZDUSD, EURUSD/GBPUSD and
   EURUSD/USDCHF, plus the EURGBP triangle against the synthetic EURUSD/GBPUSD, all at 1h over about
   50k bars. The static spread's Dickey-Fuller t and half-life are measured on the test block. Then
   a Kalman-hedged z-score strategy trades |z| > 1 in and z = 0 out, with every leg's spread charged.
   Chan's δ = 1e-4 is kept. His Ve = 1e-3 was set for dollar prices, so both noises are scaled by the
   training block's residual variance.
4. **Time-series momentum on daily bars.** Positions take the sign of the last L days' return
   (L = 21, 63, 126 and 252), with a 10%-a-year volatility target and a 21-day hold. The universe is
   15 FX pairs, 2 metals, 3 cryptos, 46 Deriv indices and 8 walks. It runs with and without a
   2-sigma stop, and records the crash profile: monthly skew, worst month and drawdown.
5. **Roll-return momentum** needs futures or term-structure data, and the lab has none. It is **not
   testable here**.
6. **Kelly sizing** is applied to the desk's own per-trade edges.

## Results

**1. The regime filter separates nothing.** Net vol units per touch, reverting and trending against
the rest of the touches, with t:

| family | H | share reverting / trending | fade in reverting, vs rest (t) | break in trending, vs rest (t) |
|---|---|---|---|---|
| FX | 5 | 55% / 18% | -0.446, **-0.021** (-0.6) | -0.474, **-0.020** (-0.4) |
| FX | 20 | 55% / 18% | -0.470, **-0.106** (-1.5) | -0.546, **-0.091** (-0.9) |
| metals | 5 | 59% / 14% | -0.044, +0.132 (+1.9) | -0.101, -0.024 (-0.3) |
| metals | 20 | 59% / 14% | -0.049, +0.035 (+0.3) | -0.324, -0.242 (-1.4) |
| crypto | 5 | 51% / 22% | -0.360, -0.094 (-1.6) | -0.192, +0.014 (+0.2) |
| crypto | 20 | 51% / 22% | -0.356, -0.082 (-0.7) | -0.088, +0.144 (+0.9) |
| Deriv | 5 | 44% / 24% | -0.071, +0.022 (+0.8) | -0.092, -0.028 (-0.8) |
| Deriv | 20 | 44% / 24% | -0.022, +0.086 (+1.5) | -0.087, -0.005 (-0.1) |
| walks | 5 | 44% / 22% | -0.067, +0.040 (+1.1) | -0.081, +0.002 (+0.0) |
| walks | 20 | 44% / 22% | -0.084, -0.037 (-0.5) | -0.142, -0.043 (-0.5) |

- Fading in a reverting regime is never significantly better than fading elsewhere (|t| ≤ 1.9).
- Breaking in a trending regime is never better than breaking elsewhere either.
- Every cell loses after costs.
- The split's effects are the same size as on the walks, where the regimes are noise by
  construction.

**2. Stops neither hurt nor help mean reversion here.** Fades in the reverting regime at H = 20,
held to the horizon against a 1-vol stop:

| family | n | held | 1-vol stop | stop - held (t) |
|---|---|---|---|---|
| FX | 12,208 | -0.470 | -0.430 | +0.040 (+1.0) |
| metals | 3,362 | -0.049 | -0.108 | -0.059 (-0.8) |
| crypto | 4,036 | -0.356 | -0.348 | +0.008 (+0.1) |
| Deriv | 10,532 | -0.022 | -0.045 | -0.023 (-0.6) |
| walks | 10,236 | -0.084 | -0.106 | -0.022 (-0.4) |

Chan's claim isn't supported at this horizon: no difference reaches |t| 1.1.

**3. Only the triangle is stationary, and it can't be traded.** Static spread on the test block:

| case | DF t (5% critical -2.86) | half-life | strategy |
|---|---|---|---|
| AUDUSD / NZDUSD | +0.25 | none (not mean-reverting) | never triggered |
| EURUSD / GBPUSD | -2.16 | 1,476 h | never triggered |
| EURUSD / USDCHF | -3.11 | 693 h (about 29 days) | never triggered |
| EURGBP / (EURUSD/GBPUSD) | -114.07 | 0.45 h | **gross Sharpe +12.41, net -18.53** (halves -17.95 / -19.11), 808 trades |
| walks (4 pairs) | -1.43 to -2.22 | 1,123-3,670 h | never triggered |

- **AUDUSD/NZDUSD and EURUSD/GBPUSD aren't cointegrated out of sample.** EURUSD/USDCHF is, just,
  but with a month-long half-life.
- **The triangle is stationary by arbitrage.** Its residual is the quotes' asynchrony, worth a gross
  Sharpe of 12, but three legs' spreads cost more than it pays. It is BH-significant as a *loser*.
- **Limitation:** the three pairs never reached |z| > 1, because the observation noise was scaled by
  the static spread's variance, which a slowly drifting spread inflates. Their verdict rests on the
  stationarity tests above, which already say there's nothing at a tradeable half-life.

**4. Time-series momentum has no out-of-sample edge the walks don't also show.** Net Sharpe on the
test block, no stop (halves in brackets):

| L (days) | FX (15) | metals (2) | crypto (3) | Deriv (46) | walks (8) |
|---|---|---|---|---|---|
| 21 | -0.42 (-1.13 / +0.29) | +0.17 | +0.10 | -0.09 | **+1.66 (+1.85 / +1.49)** |
| 63 | -0.31 | +0.51 (+0.09 / +0.90) | **+1.10 (+1.23 / +0.98)** | +0.02 | +0.60 |
| 126 | -0.30 | +0.74 (-0.13 / +1.55) | -0.12 | +0.57 (+2.06 / -0.79) | -0.12 |
| 252 | -0.22 | +0.65 (-0.38 / +1.63) | -0.09 | -0.63 | +0.05 |

- **FX loses at every lookback.**
- **Metals are positive at every lookback,** but negative in the first half each time, and there are
  only two instruments.
- **Crypto's L = 63** clears the literal bar (+1.10, both halves positive), on three instruments.
- **But our walks read +1.66 at L = 21,** positive in both halves (t +3.26). Memoryless walks
  producing a Sharpe of 1.7 sets the noise scale for a handful of instruments over about 1,000 test
  days. The crypto and metals readings sit inside that scale.
- **So the pre-registered walk condition fails, and nothing passes.** BH across all 36 tests leaves
  one "pass", the triangle as a loser.
- **Crash profile:** FX momentum's monthly skew is -0.65 to -1.22. Metals are positively skewed
  (+0.96 to +1.22), with drawdowns of 21-38%.
- **Chan's claim that stops help momentum:** the 2-sigma stop moves Sharpe by -0.4 to +0.2 in no
  consistent direction. On the walks it cuts the spurious +1.66 to +1.23.

**5. Kelly sizes the desk at zero.** With per-trade R sd of about 1, f* = mean / variance.
[`triage.md`](triage.md)'s best strategy (`opportunity`, -0.050R) gives f* = -0.05, `thesis-only`
-0.108, and the worst -0.392. Half-Kelly and constant-proportion sizing of a negative edge are both
zero.

## What this means

- **Chan's core idea, stationarity choosing the trade, adds nothing to our zone signals.** The
  variance ratio and Hurst agree with each other, but a "reverting" window doesn't make the fade pay,
  and a "trending" one doesn't make the break pay, beyond what the same split does on walks.
- **FX cross-rate cointegration isn't there at a tradeable speed.** The one truly stationary spread,
  the triangle, is the quotes' own asynchrony, and three legs' spreads cost more than it pays.
- **Time-series momentum is not established.** FX loses. Metals and crypto look positive but no more
  than memoryless walks do on samples this small. Chan's momentum results come from diversified
  futures books over decades, which this data can't replicate.
- **Chan's stop-loss asymmetry doesn't show at these horizons.**
- **Kelly says what [`triage.md`](triage.md) says:** with no positive edge, the right size is zero.

## For production

Nothing. No regime filter, pair trade, momentum overlay or Kelly sizing ships.

Two things are worth revisiting with more data:

- **Metals TSMOM,** positive at every lookback, if more metals or a longer daily history become
  available.
- **Roll-return momentum,** if futures data is ever added.
