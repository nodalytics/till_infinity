# Information flow in market structure: what is novel, and does flow warn of transitions?

Harness: [`research/harness/infoflow.py`](../harness/infoflow.py). Lab runs 2026-09-30, at 1h and 15m.

Other harnesses can import `novelty(y, x, z)` from it: a reusable test of whether a feature adds
information beyond the state production already has.

## The question

Two questions borrowed from information theory and network science. Both were pre-registered in
the harness docstring. The framing is [`findings.md`](findings.md): the desk forecasts risk, not
direction.

1. **Novelty.** How much *new* information does a candidate feature add, beyond the production
   state? This is the conditional mutual information I(Y; X | Z). A feature that repackages what
   Z already says scores zero, however well it correlates with Y on its own.
2. **Directed information networks.** Across the basket, does the direction or concentration of
   information flow change *before* volatility-regime transitions or cross-asset shocks? That
   means incremental AUC over the shock forecaster's own state.

[`comovement.md`](comovement.md), [`crowding.md`](crowding.md) and
[`orderflow.md`](orderflow.md) covered pairs, lead-lag trading, crowding and footprints; this does
not repeat them.

## Method

**Novelty.**
- **Estimator:** plug-in entropies on quantile bins, with Miller-Madow correction. Y and X use 6
  bins; each state variable uses 3.
- **Bias:** the null from shuffling X *within* Z-cells is subtracted. That keeps X's relation to Z
  and breaks only its link to Y given Z.
- **Standard error:** a block jackknife over 10 contiguous stretches per series.
- **Targets Y:**
  - the next bar's |return| in the production unit;
  - a shock (a 4x bar) within the next 4 bars, as `shocks.py`;
  - the next bar's sign.
- **Candidates X:**
  - RSI(14), stochastic %K, Bollinger z, MACD histogram, EMA(9) distance;
  - a ZMA-style 50-bar z;
  - r1, r5 and r20;
  - the bar's range and tick-volume z;
  - bar-based VPIN.
- **State Z:** the volatility regime (lvol), the hour-of-week clock (learned on the first 60%),
  the unit's 500-bar percentile, and the shock count over 100 bars.
- **Families:** FX (10 pairs), metals, crypto, and Deriv as a market. The halves are the first 60%
  and last 40% of each series.
- **Control:** GARCH t(3) walks we generate, run through the same frames.

**Networks.**
- **Panel:** 15 real assets (FX, metals, crypto; the lab has no index CFDs), and 6 Deriv indices as
  their own node set.
- **Windows:** 480 x 1h stepped by 24, and 960 x 15m stepped by 96.
- **Transfer entropy:**
  - on the **sign** of the move (directional information), and on **terciles of |move|**
    (volatility information);
  - each pair against its own shifted-source null;
  - density thresholds pooled over every window's nulls.
- **Other networks:** Granger (a partial correlation) as a baseline, and the correlation network's
  MST length, top eigenvalue share and absorption ratio (Kritzman et al. 2011).
- **Targets:** the next step's basket volatility relative to the window (top decile), and the share
  of assets with a 4x bar (top quintile).
- **Model:** logistic regression on the first 60% of windows, scored on the last 40%. Features are
  the baseline state (lvol, percentile, shock count, recent/window volatility ratio, weekday), with
  and without each network set in levels and 5-window changes.
- **Pass bar:** incremental AUC ≥ 0.01, a block-bootstrap CI above 0 in both halves of the test
  block, and no pass on the controls:
  - factor GARCH walks we generate, cross-correlated with no lead-lag;
  - the real panel with each asset circularly shifted.

## Results

### 1. Novelty

**The state carries what it should.**

| Family | lvol about next \|r\|, given the clock | 100-bar shock count about next \|r\|, given the clock |
|---|---|---|
| FX | 2.9 mbit (t +10.4) | 0.4 mbit (t +3.6) |
| Deriv | 4.3 mbit (t +14.9) | |

**The sign of the next bar.** There are 96 cells per interval, and the walks' largest CMI about the
sign is 0.15 mbit.
- **FX:** close to nothing. EMA(9) distance reads 1.0-1.7 mbit, t 2.8-4.3 in both halves at 1h and
  15m.
- **Crypto 15m is the exception:**
  - RSI, stochastic, Bollinger, EMA, ZMA, r1 and r5 carry 2-4 mbit about the next bar's sign in both
    halves (t 2.5-5.5);
  - the direction is **reversal:** corr(EMA distance, next sign) is -0.05 to -0.08 on BTC, ETH and
    SOL in each half;
  - it is small: an edge of about 0.05 of a bar's volatility, against crypto's cost of about 0.29
    vol per round trip. So it does not trade, which agrees with [`indicators.md`](indicators.md);
  - it is probably last-print bounce on bid-based closes rather than a tradeable reversal.
- **Deriv 15m:** 2.3-4.5 mbit in the first 60% only, with none in the last 40%.

**Magnitude: next |return| and shocks.**
- **Cells with t ≥ 3 in both halves:**
  - 1h: 11 of 96;
  - 15m: 31 of 96.
- **Most of that is mechanical.** On the GARCH walks, the indicators also "add" shock information
  (RSI, EMA, ZMA, r5, r20 and VPIN at t 2.5-5.3, up to 2.6 mbit). Every candidate that encodes
  recent movement carries volatility the coarse 3-bin state leaves behind. So an indicator
  scoring on shocks is repackaged volatility, not novelty.
- **Two candidates clear the walks by a wide margin, in every real family:**

  | Candidate | Next \|r\| | Shock | Walks |
  |---|---|---|---|
  | **Bar range** | 8-16 mbit, t 3.0-9.2 | 2-10 mbit, t 2.8-9.9 | 1.2 mbit at most on \|r\| |
  | **Tick-volume z** | 6-14 mbit, t 3.0-5.9 | 2.4-9.1 mbit, t 2.5-7.3 | nothing (walk volume is random) |

  - The range is a finer, faster volatility reading than the EWMA unit.
  - Tick volume is information the production shock forecaster **does not use today**
    (`shocks.NAMES` has no volume and no single-bar range).
  - On Deriv, tick volume adds nothing at 1h (0.3-1.0 mbit).
- **VPIN** (bar-based) reaches t 2-5 about shocks, at 1.2-5.0 mbit. The walks show the same
  (2.6 mbit, t 5.3), so it is mechanical here, as in [`lopez-de-prado.md`](lopez-de-prado.md).

### 2. Directed information networks

**Densities against the 5% null, 1h / 15m:**

| | sign-TE | magnitude-TE | Granger |
|---|---|---|---|
| Real panel | **0.050 / 0.050** | **0.088 / 0.112** | 0.099 / 0.116 |
| Shifted panel | 0.050 / 0.048 | 0.049 / 0.053 | 0.051 / 0.047 |
| Factor walks | 0.052 / 0.049 | 0.049 / 0.056 | 0.054 / 0.056 |
| Deriv → Deriv | 0.054 / 0.048 | 0.041 / 0.041 | |
| Deriv → real | 0.047 / 0.051 | 0.040 / 0.048 | |

- **No directional information flows between the assets.** Sign-TE sits exactly at the null in the
  real panel.
- **Volatility information does flow:** magnitude-TE is about 2x the null, and the controls hold at
  5%. So volatility spills over between assets with a lag, but moves do not lead one another.
- **Deriv is disconnected,** among its own indices and towards the real markets, as a
  generator-driven market should be. That is the sanity check, passed.

**Does flow warn of transitions?** Incremental AUC over the baseline, with test-half gains and
95% CIs:

| 1h | Next-step vol jump | Cross-asset shock share |
|---|---|---|
| sign flow | -0.011 (h1 -0.016, h2 -0.008) | +0.029 (h1 +0.023 [-0.024, +0.092], h2 +0.032 [-0.012, +0.073]) |
| magnitude flow | -0.019 | -0.015 (h2 -0.054 [-0.099, -0.018]) |
| correlation topology, incl. absorption ratio | -0.004 | +0.024 (h1 +0.032 [+0.001, +0.083], h2 +0.010 [-0.047, +0.058]) |

- **Baseline AUC** is 0.706 for the volatility jump and 0.552 for the shock share, on 473 test
  windows.
- **Controls:**
  - shifted panel: -0.042 to -0.001;
  - walks: -0.025 to +0.013.
- **15m** has only 133 test windows, and too few events for per-half CIs on the volatility jump.
  The shock share reads -0.155 to +0.005.
- **Nothing passes.** No network set clears 0.01 with a CI above 0 in both halves. The absorption
  ratio's topology set comes closest at 1h, on the shock share, but its second half spans zero.
  With about 24 network tests here, BH and deflation have nothing to deflate.

## What this means

- **The novelty test works, and it is reusable.** It recovers what we already knew: the state
  carries volatility; indicators carry nothing about direction except crypto's 15m bounce. It also
  flags when a "discovery" is repackaged volatility: on walks, every movement-based feature scores
  on shocks. **Future feature studies should run `novelty` against the production state and
  against walks before building a model.**
- **Range and tick volume are the one genuinely new signal.** They add information about the next
  bar's size and about shocks beyond production's state, in every real family and both halves,
  far above the walks. Tick volume in particular is absent from the shock forecaster.
- **Markets share volatility, not direction.** Across 15 FX, metal and crypto series, sign
  information does not flow between assets at 15m or 1h. Magnitude information does, at about
  twice the null.
- **Flow does not warn of transitions any better than the volatility state already does.** Neither
  TE networks nor correlation topology (including the absorption ratio, a known systemic-risk
  gauge) add to the shock forecaster's own state out of sample.

## For production

- **Proposed:** add the last bar's range (in the unit) and tick-volume z as features in
  `shocks.py`, and let the retrain contest judge them against the current model. Both have
  bounded state, and the pipeline's gates already guard the change.
  - The recipe changes, so the fortnightly contest decides.
  - Tick volume is broker-specific: check that production's bars carry it for every family
    before shipping.
- **No network or information-flow monitor.** It adds nothing to the shock forecaster.
- **For research:** `novelty()` is the screen for any new feature.
