# Plan: promote the quantile forecaster, behind a worst-slice gate

**2026-10-07.** [`conformal.md`](../../research/docs/conformal.md) ends with a
recommendation that has not been built:

> **The next gain is the forecaster, not the corrector:** quantile boosting on
> the volatility features, frozen and retrained by the retraining pipeline like
> the shock model. **It needs a stability gate first.** Its worst slice in
> metals (78.1% at 50 bars) would fail any honest promotion rule, so the gate
> should include a worst-slice floor per family.

This is that work. It is a promotion and a gate, not a research project: the
model is already measured and it already wins.

**Corrected 2026-10-07, after starting it.** This plan was written believing the
forecaster was unbuilt. It is not: `models/envelope_train.py`,
`retrain._envelope_contest` and `run_envelope5/20/50` already train quantile
boosting, score it against the history envelope and the champion, and ship
`envelope_fx15m_{5,20,50}.json`. Reading the code first would have caught that,
and the plan is left standing with this note rather than quietly rewritten.

The two real gaps, both still true:

1. **`ENVELOPE_GATES` is entirely relative** - `beats_empirical`, `vs_champion`,
   `slice_points` are all comparisons. A model badly calibrated *in company*
   clears all three: if the history envelope's worst window is poor too, a
   challenger covering 78% while quoting 90% promotes. There is no floor.
2. **The contest is FX-only** - `_envelope_contest` filters on `ro.is_fx`, and
   `envelope.model_applies` is `interval == "15m" and is_fx(feed)`. So metals
   was never in the contest, which is why its 78.1% could never have been
   caught by it.

So the order below becomes: the absolute floor first (it protects the FX model
that ships today), then the families.

## What is already known

- Quantile boosting on the volatility features has **the lowest pinball of every
  method in all 18 family x horizon cells**, including the AgACI corrector that
  ships today.
- It is **regime-flat**: 91.3 / 90.8 / 91.1 coverage across calm, mid and
  volatile thirds, where every corrector splits 1.07-1.37 calm to 0.73-0.91
  volatile.
- It has **one hole**: 78.1% coverage on metals at 50 bars, quoting 90%. A stop
  sized off that band is wrong a tenth more often than it claims, on one family.
- The forecaster matters more than the corrector - the paper's central claim,
  which held here.
- The best single volatility reading remains **EWMA true range**
  ([`volatility-estimators.md`](../../research/docs/volatility-estimators.md)):
  daily rho 0.316 and 20 of 42 series, beating every OHLC estimator and GARCH on
  GARCH's own quantity.

So the gain is calibration and promotion discipline, not model capacity. **No
new model class is proposed here**, and that is deliberate: on Deriv's named
indices a published formula already beats everything learned
([`deriv-variants.md`](../../research/docs/deriv-variants.md)).

## The shape of the change

### 1. The forecaster, in the retrain pipeline

`till_infinity/models/retrain.py` already runs champion-versus-challenger with
gates fixed before the run, and already ships the shock forecaster that way. The
quantile forecaster joins it as a second contest:

- train on the volatility features the envelope already computes
- quote P10/P50/P90 of log(close[t+N] / close[t]) in volatility units
- hold out the last slice, exactly as `run_shocks` does, so the model that ships
  is the one that was scored
- write `<models dir>/quantiles.json` only when every gate passes

### 2. The gate that does not exist yet

`gate()` today checks AUC against the champion, an AUC band on memoryless walk
controls, and top-decile calibration. None of that constrains a *quantile*
model, and none of it would have caught the metals hole.

Three additions, all per family:

| gate | why |
|---|---|
| **worst-slice coverage floor** | the missing one. P90 coverage over 20 time slices, worst slice must clear a floor. 78.1% is the number that must fail. |
| **pinball against the champion** | the challenger must beat AgACI on the proper score for a quantile, not merely tie. |
| **coverage band at each level** | P10/P50/P90 within a band of their nominal, so a model cannot buy pinball by quoting a band that is wrong in a useful direction. |

**Per family, and promoted per family.** Metals keeps AgACI until it passes;
FX, crypto and Deriv take the forecaster if they clear. A single global verdict
is what lets one family's hole ride in on another's margin.

### 3. What ships

`structures/vol/envelope.py` reads the promoted model where one exists for the
family and falls back to AgACI where it does not. The Deriv law keeps
precedence it already has - it beat both.

## How it will be judged

Fixed before the run, in `GATES`, as the existing ones are:

- worst-slice P90 coverage **>= 85%** per family at every horizon
- pinball **below the champion's** in every horizon for that family
- P10/P50/P90 coverage within **+-3 points** of nominal, pooled
- the walk control still near its nominal coverage, since a walk's envelope is
  a thing we can compute exactly

A family that fails any of these does not promote, and the report says which.

## What this will not do

It will not forecast direction. `conformal.md` found **"P50 is no direction"**
and nothing here changes that - this is a better band, not a better view. The
desk can forecast risk and cannot forecast direction, and this plan is squarely
on the side it can.

It is also worth stating the likely size: AgACI already holds 89.1-89.6% where
it is asked for 90%, so the available gain in coverage is small. The real gain
is the regime flatness - calm periods are currently quoted 1.07-1.37 too wide
and volatile ones 0.73-0.91 too narrow, which is a sizing error in both
directions at once, and the flat 91.3 / 90.8 / 91.1 is what fixes it.

## Order of work

1. the gate and its report, with the metals case as a fixture that must fail
2. the contest in `retrain.py`, reusing `run_shocks`'s hold-out discipline
3. a lab run over the 18 family x horizon cells, reporting every gate
4. the envelope reading the promoted model per family
5. a row in `research/docs/README.md` with what promoted and what did not
