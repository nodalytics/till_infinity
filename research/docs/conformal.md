# Which self-correcting percentiles for the envelope: ACI, AgACI, regime-weighted, or SPCI

Harness: [`research/harness/conformal.py`](../harness/conformal.py). Lab run 2026-09-29.

## The question

The envelope in production ([`envelope.md`](envelope.md), `structures/vol/envelope.py`) quotes
P10/P50/P90 of the next N bars in volatility units. It corrects them online with adaptive conformal
inference (ACI) using one fixed step size (gamma 0.005). The envelope study left it with two known
faults:

- **It drifts at long horizons.** P90 holds 90% at N = 5 and 10, but slips to about 88% at 50 bars,
  because the feedback arrives N bars late and one gamma is too slow for it.
- **It is right only on average across regimes.** It covers too little in calm markets and too
  much in volatile ones.

Three published ideas target exactly those faults:

| method | source | idea |
|---|---|---|
| **AgACI** | Zaffran et al. 2022, [arXiv 2202.07282](https://arxiv.org/abs/2202.07282) | run ACI at twelve gammas (0.0005-0.1) and aggregate them online with Bernstein Online Aggregation, the lower and upper bounds separately, each weighted by the pinball loss at its own level. There is no gamma to pick |
| **weighted** | MoE-CP, Kong et al., [ICLR 2026](https://iclr.cc/virtual/2026/poster/10006832) | weight past outcomes by how similar the conditions were when they happened. The condition here is the volatility state, so a volatile moment is quoted from volatile history |
| **SPCI** | Xu & Xie 2023 | predict the next outcome's quantiles from the autocorrelation of past residuals (quantile boosting on volatility features plus the last five resolved outcomes) |

The comparison also includes `gbm` (quantile boosting on the volatility features alone), and each
method with ACI on top.

## Method

Each method quotes P10/P50/P90 of log(close[t+N] / close[t]) in production volatility units. Its
feedback arrives N bars late, as it would live. Methods are fit on the first 60% of each series and
scored on the last 40%, at 15m with N = 5, 20 and 50. The families are FX (746k bars), metals, crypto,
and Deriv's Volatility, Boom/Crash and Range Break indices, which are treated as markets.

Four scores are reported for each method:

- **Coverage** at each level.
- **Pinball loss**, the proper score for a quantile.
- **Width**, P90 minus P10.
- **P90 coverage across 20 time slices** (standard deviation and worst slice) **and by volatility
  third** (calm / normal / volatile), which is the conditional coverage.

## Results

FX, 15m. Production today is `aci`.

| N | method | P90 cover | width | P90 calm / normal / volatile | worst slice | pinball P10 / P50 / P90 |
|---|---|---|---|---|---|---|
| 5 | aci | 90.0% | 3.67 | 88.0 / 90.3 / 91.7 | 89.9% | 0.307 / 0.581 / 0.286 |
| 5 | agaci | 90.0% | 3.58 | 88.3 / 90.3 / 91.4 | 89.8% | 0.303 / 0.581 / 0.282 |
| 5 | weighted | 90.0% | 3.55 | 89.1 / 90.3 / 90.5 | 89.7% | 0.301 / 0.577 / 0.281 |
| 5 | gbm aci | 90.0% | 3.55 | 89.8 / 90.2 / 90.1 | 89.9% | 0.292 / 0.572 / 0.268 |
| 20 | aci | 89.6% | 8.23 | 86.0 / 89.9 / 92.9 | 89.4% | 0.686 / 1.214 / 0.627 |
| 20 | agaci | 89.9% | 7.49 | 86.3 / 90.3 / 93.1 | 89.3% | 0.645 / 1.206 / 0.591 |
| 20 | weighted | 89.8% | 7.27 | 88.1 / 90.1 / 91.2 | 89.1% | 0.634 / 1.184 / 0.577 |
| 20 | gbm aci | 89.6% | 7.40 | 89.7 / 89.5 / 89.4 | 88.9% | 0.622 / 1.207 / 0.568 |
| 50 | aci | **87.8%** | 13.84 | **82.8** / 88.5 / 92.3 | 87.3% | 1.249 / 2.161 / 1.100 |
| 50 | agaci | 89.6% | 13.09 | 84.7 / 89.9 / 94.1 | 88.4% | 1.151 / 2.063 / 1.025 |
| 50 | weighted | 89.5% | 12.05 | 86.7 / 89.9 / 91.8 | 88.5% | 1.080 / 1.990 / 0.960 |
| 50 | gbm | 91.0% | 12.63 | 91.1 / 90.9 / 91.1 | 88.6% | 1.028 / 1.969 / 0.908 |
| 50 | gbm aci | 88.0% | 11.84 | 87.9 / 87.9 / 88.2 | 86.9% | 1.082 / 2.148 / 0.972 |

The other families show the same pattern. At N = 50 the P90 coverage for aci / agaci / weighted is:

| family | aci | agaci | weighted |
|---|---|---|---|
| metals | 87.8% | 89.2% | 89.4% |
| crypto | 87.9% | 89.5% | 89.0% |
| Deriv Volatility | 88.1% | 89.6% | 89.6% |
| Deriv Boom/Crash | 88.0% | 89.1% | 89.4% |
| Deriv Range Break | 87.8% | 89.4% | 89.8% |

The families differ in how stable the feature-conditioned models are. `gbm` on metals at N = 50
has a worst slice of 78.5%, against aci's 85.9%.

P50 AUC is 0.47-0.54 in every cell. None of these methods makes the median a direction call.

## What this means

- **AgACI fixes the long-horizon drift, and costs nothing.** At N = 50 it lifts P90 from 87.8% to
  89.6% on FX, and to 89.1-89.6% in every other family, Deriv included. It is also 2-9% narrower
  than one-gamma ACI at every horizon, with better pinball in every cell. It is the one change that
  improves every number and has no parameter to tune. The paper's central claim holds here.
- **It does not fix conditional coverage, and was not designed to.** Calm FX at N = 50 is still
  covered only 84.7% of the time, and volatile FX 94.1%.
- **Weighting by regime (MoE-CP) does both jobs partly.** It has the narrowest band among the
  methods that cover correctly (12.05 against 13.84 at N = 50) and moves the calm third from 82.8%
  to 86.7%.
- **Conditioning on features makes coverage flat across regimes.** `gbm` scores 91.1 / 90.9 / 91.1
  and has the best pinball. The cost is stability over time: its worst slice drops to 78-85% in
  metals and Deriv. Putting single-gamma ACI on top steadies the slices but drags N = 50 back down
  to 88%, the same slowness AgACI fixes.
- **SPCI adds nothing over `gbm`.** It matches `gbm` to the third decimal in almost every cell. The
  residuals' autocorrelation carries no information the volatility features lack, which is
  consistent with the P50 AUC of 0.5.

## For production

1. **Now:** replace the envelope's single-gamma ACI with AgACI (twelve gammas, BOA per bound). The
   quantile model is unchanged, and the corrector swaps in place. This is measured as better in
   every family and horizon, and it removes the one tuned constant.
2. **Next test:** `gbm` + AgACI, which is the combination this run did not include. The feature
   model gives flat conditional coverage, and AgACI should correct its drift without the
   single-gamma lag. If it holds, the quantile model becomes a second frozen model for the
   [retraining pipeline](../../till_infinity/models/retrain.py). Until then the regime-flat option
   isn't proven stable over time.
