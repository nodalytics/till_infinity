# The boosted-quantile envelope, run as production would run it

Harness: [`research/harness/gbmenvelope.py`](../harness/gbmenvelope.py), run by
[`gbmenvelope.sh`](../harness/gbmenvelope.sh). Lab run 2026-09-29, 15m, N = 5, 20 and 50.

## The question

[`conformal.md`](conformal.md) (Okita's section) found quantile boosting the best forecaster of the
envelope. It had the lowest pinball in all 18 family x horizon cells, and its coverage was flat
across volatility regimes. With AgACI on top it still had weak worst slices in metals (78-82%). That
was one 60/40 fit, which is not how production would run it.

Production would freeze the models and retrain them every 14 days (`models/retrain.py`). So: run
that way, is it better than production's envelope, can its weak slices be fixed, and what would it
cost to ship?

## Method

- **Cadence:** every 14 days, the quantile models are refit on every move resolved before that day,
  then quote the next 14 days through AgACI, which reads between the model's quantile levels.
  Quantile crossing is fixed by sorting.
- **Baseline:** production's envelope, the last 1,000 resolved moves corrected by AgACI
  (`structures/vol/envelope.py`), on the same rows.
- **Scored:** the last 40% of each family's time span.
- **Families:** FX (14 pairs), metals, crypto, and Deriv's families that are not quoted from a
  published law: Boom/Crash, Range Break, DEX and Drift Switch, as markets. Volatility, Jump and
  Step quote their law in production ([`deriv-variants.md`](deriv-variants.md)) and are left out.
- **Controls:** iid t(3) walks and GARCH(1,1) walks, generated here.

The variants, one per fix:

| variant | what it is |
|---|---|
| pooled | one model set for every market family |
| fam | one model set per family (fix a) |
| resid | per family, with the empirical q10/q50/q90 as inputs, so it adjusts the known base (fix b) |
| recent | per family, trained on the last 365 days only (fix c) |
| fam5 | per family, 5 quantile levels instead of 9 (the size test) |
| gated | the selected variant in a 14-day window only while its worst window over the previous ~90 days kept within 1 point of production's P90; production's quotes otherwise (fix e) |

Quantile crossing before the sort (fix d) was 0.0-0.7% of rows for every variant except `resid`,
which reached 1.3-6.7%. Sorting handles it.

The variant was selected on the first half of the scored period. `recent` was lowest relative to
production at every horizon (0.9852 / 0.9781 / 0.9544), with `fam` within 0.001 of it.

## Results

**Pinball relative to production, `recent`** (every interval from a day bootstrap excludes zero):

| family | N = 5 | N = 20 | N = 50 |
|---|---|---|---|
| FX | **-3.4%** | **-4.2%** | **-6.6%** |
| metals | -2.1% | -2.3% | -4.6% |
| crypto | -1.5% | -2.6% | -4.5% |
| Boom/Crash | -0.7% | -1.9% | -4.4% |
| Range Break | -1.5% | -1.9% | -4.2% |
| DEX | -0.8% | -2.0% | -4.6% |
| Drift Switch | -1.0% | -1.7% | -3.7% |
| **walks, iid t(3)** | **-0.7%** | **-1.8%** | **-3.9%** |
| **walks, GARCH** | -0.5% | -1.9% | -4.9% |

**Conditional coverage is where it differs most.** P90 by calm / normal / volatile third, FX at
N = 50:
- production 84.5 / 89.7 / 93.8;
- `recent` 88.9 / 88.7 / 89.3.

It is the same everywhere: production under-covers calm and over-covers volatile markets, and the
boosted envelope is flat.

**The pass bar, ungated `recent` and `gated`:**

| family | N = 5 | N = 20 | N = 50 |
|---|---|---|---|
| FX | pass / pass | pass / pass | pass / pass |
| metals | pass / pass | worst slice 84.4 vs 87.6 / pass | unstable, 14-day low 77.1 vs 80.8 / pass |
| crypto | pass / pass | worst slice 86.6 vs 88.0 / pass | fails both (gated worst slice 84.6 vs 86.2) |
| Boom/Crash | pass / pass | pass / pass | pass / pass |
| Range Break | pass / pass | worst slice 84.0 vs 87.1 / pass | pass / pass |
| DEX | pass / pass | unstable, 84.5 vs 86.9 / pass | unstable, 80.9 vs 83.1 / pass |
| Drift Switch | pass / pass | pass / pass | pass / pass |

The gate keeps the slices safe by falling back to production in some windows, which gives up part
of the gain. For example, FX `gated` pinball is -3.0 / -3.7 / -6.2% (the boosted model is used in
86% of windows), but metals N = 50 falls to -1.7% (35% of windows) and crypto N = 50 to -1.5%.

**The fixes:**
- **(a) per family beats pooled everywhere.** Pooled also wrecks Range Break's coverage: P10/P90
  13.3% / 86.8% at N = 20, 15.2% / 85.9% at N = 50.
- **(b) residual on the empirical envelope** is no better than `fam` and crosses up to 6.7% of rows.
- **(c) the last year only** is level with all history, marginally ahead.
- **(e) the gate** is what clears the metals and DEX slices.
- **None of the fixes lifts the metals N = 50 worst 14-day window** above production's by itself.
  It sits at 77-78% against production's 80.8%.

**Size and speed** (`PART=size`, one family x one horizon, FX, pure Python):

| configuration | JSON | per bar | 3 horizons x 7 families |
|---|---|---|---|
| 9 levels, 120 iterations | 1.03 MB | 761 us | 21.7 MB |
| 5 levels, 120 iterations | 0.55 MB | 294 us | 11.5 MB |
| 5 levels, 60 iterations | 0.33 MB | 141 us | 6.9 MB |

The export matches sklearn exactly. `fam5` gives up 0.2-0.7 points of the pinball gain against
`fam`, for half the size.

## What this means

- **The pre-registered bar fails on its walk condition.** The boosted envelope beats production on
  our own memoryless walks by 0.7% at N = 5 and 1.8% at N = 20, and by 3.9-4.9% at N = 50, where a
  tie was the bar. There is no information to forecast on those walks. So most of the gain is
  **mechanical**: production measures moves in a noisy live volatility unit (the EWMA of true
  range), and the model's volatility-state features let it correct that noise. It is the same
  mechanism [`deriv-variants.md`](deriv-variants.md) found for the published law.
- **It is still a real improvement to the quote, just not market skill.** The walks carry the same
  noisy unit production faces live, and the features are strictly causal. What the bar was meant to
  catch, fitting noise or a leak, is not what happened.
- **FX is the one family with a clear market component on top.** Its gain over the walks is about
  3, 2.5 and 2 points at N = 5, 20 and 50, and it passes the slice and stability conditions ungated
  at every horizon.
- **Everywhere else, the gain is the walks' gain.** Deriv's four families sit within a point of the
  walks at every horizon. Metals and crypto add little and need the gate to keep their slices,
  which then costs most of the gain at N = 50. Crypto N = 50 fails even gated.
- **The regime-flat coverage is the part a card reader would notice.** A P90 that holds 89% in calm
  and in volatile markets, instead of 84.5% and 93.8%.

## For production

Not built; this is the proposal.

1. **Ship it for FX, per family, `recent`, at 5 levels:** 0.33-0.55 MB per horizon, 1.0-1.7 MB for
   FX's three horizons.
2. **Treat the others as optional.** Their gain is real but mechanical, and a cheaper route to the
   same correction may exist, for example conditioning the empirical envelope on the volatility
   state (untested). If they ship, ship them behind the gate, and not crypto at N = 50.
3. **The build:**
   - **Trees:** `shared/frozen.py` `Trees` is classifier-only (a logistic of the raw sum). It needs
     an identity link for regression, one field in the spec and one branch in `predict`.
   - **Envelope:** reads the model's quantiles at its levels and feeds them to AgACI in place of the
     empirical history. The empirical envelope stays as the fallback when no model is loaded, and
     for families without one.
   - **Retrain:** a fourth contest in `models/retrain.py`, per family and horizon, with the gates
     above: pinball better than production's with a day-bootstrap interval below zero; worst slice
     within 1 point; no 14-day window more than 2 points under production's worst.
   - **Training:** must replay bars through the production `Ranges` and `Envelope` classes, as
     `shocks_train.py` does, so the unit and the features match serving exactly.
