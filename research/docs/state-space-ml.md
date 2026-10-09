# Particle and state-space filters as machine-learning features: they add nothing a model cannot read from the bars

Measured 2026-10-09 on the lab with [`statespace_ml.py`](../harness/statespace_ml.py) and
[`statespace_ml_report.py`](../harness/statespace_ml_report.py). The rules were frozen in the
harness before the run.

## Verdict

| question | answer |
|---|---|
| Do the filters' states make a learned model better at direction? | **No.** 66 cells (17 instruments x 4 timeframes). Gradient boosting on bars + filter states + liquidity + higher-timeframe states passes the frozen rule in 6. **In none of the 6 do the filters add the required 0.003 over bars alone:** the gain is -0.005 to +0.002, and the walks' own gains are the same size. |
| What do the 6 passing cells find? | **The short-term reversal again**, from the bars: EURUSD, GBPUSD and XAUUSD at 15m (AUC 0.512-0.515), and BTCUSD at 15m, 1h and 4h (0.534-0.546). The walks score 0.496-0.500. Bars alone score 0.511-0.549 on the same cells. The model's heaviest filter weight is on the Kalman drift, with a negative sign: a reversal. |
| Five bars ahead? | **Nothing beyond the bars.** BTCUSD 15m and 1h reach 0.520 and 0.527 with all blocks, against 0.531 and 0.535 from bars alone. |
| Risk: is the next bar a top-10% move? | **The filter states carry real volatility information, which the bars already hold.** On their own they score 0.56-0.70 on intraday FX (GARCH walk 0.52-0.55). Added to the bars they move AUC by -0.04 to +0.018. The frozen rule flags 7 real-asset cells (GBPUSD 15m, USDCAD 15m, XAUUSD 4h, BTCUSD 4h and 1d, and EURUSD 4h and 1d, where the GARCH walk gains almost as much). About as many cells lose by more. |
| Deriv (V10, V10 (1s), V25, V25 (1s), V75, V15, V15 (1s), Jump 25)? | **Nothing, as for a random walk.** Direction 0.483-0.540. Two intervals exclude 0.5, one on each side: V75 1d above (0.540 on 1,124 bars) and V25 (1s) 4h below (0.483). Neither passes BH. The shock target scores 0.46-0.56 even from bars, because their volatility is fixed by design. The frozen risk rule flags 9 Deriv cells; with nothing to forecast, those are noise. |
| Does anything pay? | **No.** The confident decile of the all-blocks model nets -0.04 to -0.07 bps on the EURUSD and GBPUSD 15m cells and -2.21 / -0.74 bps on BTCUSD 15m / 1h. BTCUSD 4h nets +3.20 bps (t 1.4, 672 trades), which is inside noise. The tail matches the walks. |

## 1. The question

[`state-space-filters.md`](state-space-filters.md) scored each filter's own forecast. A filter
also carries a *state*: how confident it is, which regime it leans to, how much volatility it
believes in, and how surprised it was by the last bar. A learned model might combine those in a
way the filter's own forecast does not. This asks whether it does, and whether that beats the same
model reading the bars directly.

## 2. What was frozen

- **Instruments:** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD, BTCUSD;
  Volatility 75, 10, 10 (1s), 25, 25 (1s), 15, 15 (1s) and Jump 25.
- **Timeframes:** 15m, 1h, 4h and 1d from the broker's bars, as in [`fourier.md`](fourier.md).
- **Walks:** real bars, two flip walks and a GARCH-t walk per cell.
- **Rollover:** FX and gold rows touching 20:00-23:00 UTC, and rows after a gap, are neither
  trained on nor scored.

**Feature blocks**, each known at the close of the bar:

| block | contents |
|---|---|
| bars | the last five returns over EWMA sigma; 5- and 20-bar returns; 20-bar efficiency; log sigma; the candle's close location, range, body and wicks |
| filters | Kalman: drift, log drift variance, standardised innovation. HMM: three regime probabilities (ordered by mean), P(next up). Particle filter (3 regimes x stochastic volatility, Student-t, 1,000 particles): P(next up), posterior log-volatility and its spread, three regime probabilities, effective sample size, predictive sd, log density of the last bar |
| liq | Corwin-Schultz, Abdi-Ranaldo, Roll, Amihud, volume z ([`state-space-filters.md`](state-space-filters.md) §8) |
| htf | the HMM and particle states of the next timeframe up, from higher bars that have closed |

**Fitting and scoring:**
- The filters are fitted on the first 60% by time and run forward unsmoothed.
- The models are logistic regression and gradient boosting (HistGradientBoosting; early stopping
  on a random 20% of the training rows).
- Both are fitted on the same 60% and scored on the last 40%.

**Pass rules:**
1. **Direction:** gradient boosting on all blocks passes Benjamini-Hochberg (q 0.05) over the 66
   cells, at least 0.005 above its walks.
2. **The filters earn their place** if, on a passing cell, bars + filters beats bars alone by 0.003
   or more, and by more than on the walks.
3. **Risk:** the same comparison on the shock target, against the GARCH walk.

## 3. Direction

Every passing cell, test AUC with walks in brackets:

| instrument | tf | test bars | all blocks [95% CI] | bars | bars + filters | filters alone | filter gain real / walks |
|---|---|---:|---|---|---|---|---|
| EURUSD | 15m | 17,288 | 0.515 [0.507-0.523] (0.496) | 0.512 (0.500) | 0.507 (0.498) | 0.504 (0.502) | -0.005 / -0.002 |
| GBPUSD | 15m | 17,288 | 0.515 [0.505-0.522] (0.500) | 0.513 (0.499) | 0.514 (0.498) | 0.506 (0.501) | +0.001 / -0.000 |
| XAUUSD | 15m | 18,122 | 0.512 [0.504-0.519] (0.499) | 0.511 (0.500) | 0.511 (0.500) | 0.515 (0.501) | +0.001 / -0.000 |
| BTCUSD | 15m | 19,996 | 0.534 [0.526-0.542] (0.500) | 0.530 (0.500) | 0.532 (0.498) | 0.526 (0.497) | +0.002 / -0.002 |
| BTCUSD | 1h | 19,996 | 0.546 [0.539-0.552] (0.499) | 0.547 (0.497) | 0.546 (0.501) | 0.533 (0.501) | -0.001 / +0.004 |
| BTCUSD | 4h | 8,194 | 0.536 [0.525-0.548] (0.497) | 0.549 (0.501) | 0.546 (0.498) | 0.540 (0.499) | -0.003 / -0.004 |

**The filters alone do see the effect** (0.504-0.540), so the states hold the reversal. But the
bars hold it as well or better, and adding the states to the bars changes nothing.

Averaged over all 66 cells, the logistic model's largest filter weight is the Kalman drift
(-0.047, mean |w| 0.067): a drift up means a bar down next. The innovation (+0.020) and the regime
probabilities follow, an order of magnitude smaller.

**Bitcoin's strength was checked for a quote artefact.** [`lagging.md`](lagging.md) found the
broker's BTC quote lags the exchanges. A lagged or smoothed quote would show *positive*
autocorrelation. The test block shows lag-1 autocorrelation of -0.016 (15m), -0.013 (1h) and
-0.007 (4h). The strongest single features point the reversal way: the close's location in its
bar scores 0.447 at 4h, so a close near the high precedes a down bar. It is the reversal measured
on FX in [`fx-reversal.md`](fx-reversal.md), larger on bitcoin, and it sits under a 2.39-bps
spread (section 5).

Everywhere else the all-blocks model scores 0.467-0.540 with walks at 0.480-0.513. The daily
cells and the young V15 series give the widest swings on both sides. The top of the range, V75 1d
at 0.540, rests on 1,124 bars of a published random walk.

## 4. Risk

Next bar a top-10% move, gradient boosting (GARCH walk in brackets), selected cells:

| instrument | tf | bars | bars + filters | filters alone | all |
|---|---|---|---|---|---|
| EURUSD | 15m | 0.803 (0.681) | 0.806 (0.682) | 0.645 (0.533) | 0.805 |
| GBPUSD | 15m | 0.775 (0.682) | 0.781 (0.682) | 0.664 (0.546) | 0.779 |
| USDCAD | 15m | 0.808 (0.681) | 0.813 (0.682) | 0.700 (0.540) | 0.816 |
| USDJPY | 15m | 0.810 (0.682) | 0.809 (0.679) | 0.612 (0.535) | 0.808 |
| BTCUSD | 4h | 0.698 (0.680) | 0.710 (0.682) | 0.609 (0.545) | 0.710 |
| BTCUSD | 1d | 0.689 (0.581) | 0.706 (0.581) | 0.645 (0.475) | 0.745 |
| V75 | 1h | 0.491 (0.683) | 0.499 (0.682) | 0.512 (0.531) | 0.503 |

- **The particle filter's posterior volatility is a real risk signal.** On their own the filter
  states score 0.56-0.70 on intraday FX, well above the GARCH walk.
- **It is a second reading of what the bars already say.** The bars include log EWMA sigma and the
  candle's range, which hold the same information, and the bars already score 0.69-0.81.
- **Across the 36 real-asset cells the filter gain ranges -0.041 to +0.018.** The frozen rule
  (gain of 0.003 or more, above the GARCH walk's gain) flags seven: GBPUSD 15m +0.006, USDCAD 15m
  +0.005, XAUUSD 4h +0.003, BTCUSD 4h +0.012, BTCUSD 1d +0.018, and EURUSD 4h and 1d, where the
  GARCH walk gains almost as much (+0.005 / +0.004). It loses by more than that in several daily
  cells (USDCAD 1d -0.041, NZDUSD 1d -0.031, AUDUSD 1d -0.026).
- **On Deriv the shock target is a coin even from bars** (0.46-0.56), as it must be when the
  generator fixes sigma.
- The production shock forecaster ([`shockvolume.md`](shockvolume.md)) gets more from range and
  tick volume than any filter state adds here.

## 5. Trades and the tail

Confident decile of the all-blocks direction model, held one bar, net of one quoted spread:

| instrument | tf | n | gross bps (t) | net bps | P(>=4R) / P(>=10R) (walks) |
|---|---|---:|---|---|---|
| EURUSD | 15m | 1,787 | +0.13 (+1.3) | -0.04 | 0.200 / 0.076 (0.19-0.22 / 0.08-0.09) |
| GBPUSD | 15m | 1,504 | +0.15 (+1.3) | -0.07 | 0.192 / 0.066 (0.18-0.23 / 0.08) |
| XAUUSD | 15m | 1,741 | -0.79 (-1.6) | -1.11 | 0.171 / 0.080 (0.20-0.25 / 0.07-0.10) |
| BTCUSD | 15m | 2,714 | +0.18 (+0.4) | -2.21 | 0.198 / 0.089 (0.20-0.22 / 0.08) |
| BTCUSD | 1h | 2,373 | +1.65 (+1.5) | -0.74 | 0.195 / 0.078 (0.19-0.20 / 0.08-0.09) |
| BTCUSD | 4h | 672 | +5.59 (+1.4) | +3.20 | 0.206 / 0.075 (0.21-0.23 / 0.09-0.10) |

- **A better AUC does not make a better confident decile.** Gradient boosting's most confident
  calls gross less than the simple filters' did in [`fx-reversal.md`](fx-reversal.md). The extra
  AUC is spread thinly over many bars and not concentrated where the model is surest.
- **None of the passing cells pays** with any significance.
- **The tail matches the walks** in every passing cell.

## 6. Caveats, and what the run caught

- **Five cells failed on the first pass** with NaN reaching the logistic model. They passed when
  run alone. A feature with very large finite values overflows the scaler's variance. Features
  are now clipped to a bounded range before scaling, and the five cells (four Deriv, one V10 walk)
  were re-run and merged.
- **The filters are fitted on the same 60% the models train on.** Their states on the training
  rows are in-sample for the filter parameters (a dozen numbers). The test rows are out of sample
  for both.
- **The quantum density-matrix filter was left out.** It matched the HMM in
  [`state-space-filters.md`](state-space-filters.md) and costs most of the compute.
- **The bitcoin reversal is the strongest direction effect measured on these bars** (bars alone
  0.547 at 1h). It still has no frozen confirmation of its own; the BTC rows here and in
  [`fourier.md`](fourier.md) are the same test block. Fresh coins are the test.
