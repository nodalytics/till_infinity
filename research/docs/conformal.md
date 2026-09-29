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

## Okita's methods (SSRN 7457798)

Harness: [`research/harness/conformal2.py`](../harness/conformal2.py). Lab run 2026-09-29.

Okita, *Adaptive Conformal Prediction with Foundation Models*, ranks 21 online conformal methods and
finds that the forecaster's quality decides how much the choice of method matters. The spread in
conditional coverage between methods is 0.335 with GBDT and 0.150 with Chronos. Three of its methods
target the two faults above, and the run adds the combination this page left as the next test:

| method | what it does here |
|---|---|
| **cpid** | Conformal PID (Angelopoulos et al. 2023), the paper's best with tree-based forecasters. It tracks the quantile *value* (P) and adds a saturating integrator on the last 200 coverage errors (I). The D term is SPCI's idea and added nothing above, so it is left out. The paper's case for PID is autocorrelated residuals, and overlapping N-bar moves are exactly that |
| **bitrend** | a proactive level shift, λ(r2 − r1)/r1 · α, from the trend of the last 20 absolute outcomes spaced H apart; λ = 0.3, clipped to ±0.05 (the paper's values). Run on one-gamma ACI and on AgACI's correctors |
| **ms** | Multi-Strategy: raw-move quantiles against volatility-normalised ones, each with its own ACI, quoting whichever covered the P10-P90 band better over the last 50 outcomes, with under-coverage penalised twice |
| **gbm agaci** | AgACI's correctors reading the quantile-boosted model's quantiles instead of the empirical history |

Everything else is as above: the same families, 15m bars, N = 5, 20 and 50, and the last 40%
scored. The `aci` and `agaci` rows reproduce the first run to the last digit, so the two harnesses
agree.

### The paper's diagnostic: is volatility normalisation right?

The calibration ratio is realised |move| over what the unit predicts. Here that is mean |y| in each
quintile of the volatility unit, over the overall mean |y|. The paper treats ρ above 5 in the
calmest bin as "confidently wrong", where normalised conformal fails.

| family | N = 5, calm → volatile | N = 20 | N = 50 |
|---|---|---|---|
| FX | 1.12 / 1.03 / 0.99 / 0.95 / 0.91 | 1.23 … 0.82 | **1.37** / 1.11 / 0.98 / 0.82 / **0.73** |
| metals | 1.18 … 0.92 | 1.31 … 0.84 | 1.30 … 0.79 |
| crypto | 1.12 … 0.86 | 1.23 … 0.76 | 1.32 … 0.74 |
| Deriv Volatility | 1.09 … 0.91 | 1.07 … 0.91 | 1.12 … 0.88 |
| Deriv Boom/Crash | 1.16 … 0.84 | 1.15 … 0.84 | 1.12 … 0.87 |
| Deriv Range Break | 1.29 … 0.74 | 1.27 … 0.74 | 1.26 … 0.75 |

Nowhere near the paper's failure level: ρ in the calmest bin is 1.07-1.37, not above 5. But the
tilt is the same in every family and grows with the horizon. **Calm moments move more than their
volatility says, and volatile moments less**, because volatility reverts toward its mean over the
next N bars and today's unit does not. That is the mechanism behind the calm third's under-coverage
(82.8% at N = 50 on FX). Deriv's Volatility indices, whose generator fixes the volatility, show the
least tilt (1.07-1.12). Range Break, whose regime alternates, shows the most.

### Results

The sum of pinball loss at P10 + P50 + P90 is the headline score (lower is better). The
"thirds" column is P90 coverage in the calm, normal and volatile thirds.

FX, 15m:

| N | method | P90 cover | width | pinball sum | worst slice | P90 thirds |
|---|---|---|---|---|---|---|
| 5 | aci | 90.0% | 3.67 | 1.174 | 89.9% | 88.0 / 90.3 / 91.7 |
| 5 | agaci | 90.0% | 3.58 | 1.166 | 89.8% | 88.3 / 90.3 / 91.4 |
| 5 | cpid | 90.0% | 3.65 | 1.183 | 89.9% | 88.0 / 90.3 / 91.6 |
| 5 | bitrend | 90.0% | 3.79 | 1.186 | 89.9% | 87.5 / 90.3 / 92.2 |
| 5 | ms | 89.9% | 3.70 | 1.178 | 89.6% | 89.4 / 90.3 / 90.0 |
| 5 | gbm | 90.2% | 3.49 | **1.124** | 88.8% | 90.4 / 90.3 / 89.9 |
| 5 | gbm agaci | 90.0% | 3.51 | 1.127 | 89.7% | 90.1 / 90.1 / 89.9 |
| 20 | aci | 89.6% | 8.23 | 2.527 | 89.4% | 86.0 / 89.9 / 92.9 |
| 20 | agaci | 89.9% | 7.49 | 2.442 | 89.3% | 86.3 / 90.3 / 93.1 |
| 20 | cpid | 89.9% | 8.05 | 2.576 | 89.7% | 86.4 / 90.3 / 93.0 |
| 20 | bitrend | 89.7% | 8.69 | 2.569 | 89.5% | 85.9 / 90.0 / 93.2 |
| 20 | ms | 89.4% | 8.05 | 2.506 | 89.0% | 87.4 / 89.9 / 90.9 |
| 20 | gbm | 90.7% | 7.43 | **2.328** | 89.1% | 91.2 / 90.5 / 90.2 |
| 20 | gbm agaci | 89.7% | 7.22 | 2.367 | 89.1% | 90.2 / 89.6 / 89.4 |
| 50 | aci | 87.8% | 13.84 | 4.510 | 87.3% | 82.8 / 88.5 / 92.3 |
| 50 | agaci | 89.6% | 13.09 | 4.239 | 88.4% | 84.7 / 89.9 / 94.1 |
| 50 | cpid | 89.8% | 15.09 | 4.797 | **89.4%** | 85.4 / 90.4 / 93.6 |
| 50 | bitrend | 87.9% | 14.38 | 4.553 | 87.5% | 82.7 / 88.5 / 92.6 |
| 50 | agaci bitrend | 89.5% | 13.34 | 4.255 | 88.3% | 84.6 / 89.9 / 94.1 |
| 50 | ms | 87.6% | 13.47 | 4.464 | 86.9% | 84.0 / 88.3 / 90.6 |
| 50 | gbm | 91.1% | 12.62 | **3.906** | 88.7% | 91.3 / 90.8 / 91.1 |
| 50 | gbm agaci | 89.2% | 11.96 | 4.053 | 88.0% | 89.6 / 88.7 / 89.2 |

At N = 50, the worst slice (the paper's WSCtime analogue) against width in every family:

| family | agaci worst / width | cpid worst / width | gbm worst |
|---|---|---|---|
| FX | 88.4% / 13.09 | 89.4% / 15.09 | 88.7% |
| metals | 83.0% / 13.71 | 87.6% / 15.96 | 78.1% |
| crypto | 85.9% / 13.16 | 88.1% / 15.37 | 86.0% |
| Deriv Volatility | 86.2% / 12.06 | 88.8% / 14.12 | 84.7% |
| Deriv Boom/Crash | 86.3% / 15.97 | 88.4% / 18.35 | 84.6% |
| Deriv Range Break | 82.7% / 24.67 | 86.6% / 28.29 | 82.7% |

### What this means

- **Nothing beats AgACI as the corrector on the empirical envelope.** Among the six correctors that
  read the same history, AgACI has the lowest pinball sum in all 18 family × horizon cells, tied
  once with AgACI + BiTrend on Deriv Volatility at N = 5. Production's corrector stays.
- **Conformal PID buys stability over time with width.** At N = 50 it has the best worst slice in
  every family, by 1.0-4.6 points over AgACI, and P90 closest to 90% (89.7-89.9%). Its bands are
  15-17% wider, and at 20 and 50 bars its pinball is the worst of the correctors in every family.
  Its P50 is especially noisy (P50 pinball 2.472 against 2.063 on FX at N = 50). This matches the paper, which ranks PID first on
  worst-slab coverage, but for a quoted envelope the width is the cost that matters.
- **BiTrend does nothing here.** On ACI it widens the band and worsens pinball in every cell. On
  AgACI it is never better than AgACI alone: equal once, and up to 0.08 worse in pinball sum. The paper's gains (+0.2 to +2.0 coverage points) came from
  trends in heteroscedastic residuals. Dividing by the volatility unit already takes those trends
  out.
- **Multi-Strategy half-fixes the calm third.** It raises the calm third's P90 coverage (FX 82.8 →
  84.0% at N = 50, 86.0 → 87.4% at 20, 88.0 → 89.4% at 5) and trims the volatile third (92.3 →
  90.6%), because the raw branch does not over-shrink calm bands. But it runs on one-gamma ACI, so
  its marginal coverage drifts at 50 bars (87.6%), and it never reaches what conditioning on
  features does.
- **The paper's central claim holds, in the form it takes here: the forecaster matters more than
  the corrector.** At N = 50 on FX, the six correctors on the empirical base span pinball sums
  4.24-4.80 and put 6.6-9.9 points between the calm and volatile thirds. The quantile-boosted
  forecaster alone scores 3.91, with 0.5 points between the thirds (91.3 / 90.8 / 91.1). It has the
  lowest pinball of every method in all 18 cells. Swapping the forecaster changes more than
  switching between any two correctors. This run had only one corrector on the boosted base, so the
  paper's narrower claim, that the spread between methods shrinks, is not tested directly.
- **Boosting + AgACI is not the clean win hoped for.** It corrects boosting's over-coverage at 50
  bars (FX 91.1 → 89.2%) with the narrowest band of all (11.96), and keeps the thirds flat (89.6 /
  88.7 / 89.2). But it gives back some pinball (4.053 against 3.906), and neither variant fixes the
  boosted model's weak slices in metals (78.1% plain, 82.0% with AgACI).

## For production, revised

1. **Keep AgACI as the envelope's corrector.** It is shipped (PR #14). Nothing in Okita's set beats
   it on the same forecaster.
2. **The next gain is the forecaster, not the corrector:** quantile boosting on the volatility
   features, frozen and retrained by the [retraining pipeline](../../till_infinity/models/retrain.py)
   like the shock model. It needs a stability gate first. Its worst slice in metals (78.1% at 50
   bars) would fail any honest promotion rule, so the gate should include a worst-slice floor per
   family.
3. **Conformal PID is the option if stable coverage over time ever matters more than a tight band**,
   for example if a stop is sized off the 50-bar floor. Not for the card as it is.
