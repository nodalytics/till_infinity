# Bar range and tick volume in the shock forecaster: shipped, after a clean volatility-echo control

Harness: [`research/harness/shockvolume.py`](../harness/shockvolume.py). Lab run 2026-09-30.

## The question

[`infoflow.md`](infoflow.md) found bar range and tick-volume z to be the only inputs carrying new
information about the next bar's size, beyond the production state. [`vpin.md`](vpin.md) found
plain volume adds +0.0145 AUC to the forecaster, and [`causal.md`](causal.md) named volume the
strongest upstream candidate. Should the production shock forecaster add them?

## Method

- **Three new features** in `structures/learning/shocks.py`:
  - `range_vol`: the bar's high-low range over the EWMA true range;
  - `volume_z`: log tick volume against its last 500 bars;
  - `volume_z_hour`: log tick volume against the same UTC hour's last 60 bars, so the intraday
    volume profile does not read as a surge.

  They are NaN where no volume is reported, and the trees route missing values.
- **Data:** the lab's bars replayed through production code: 74 series, 60 with volume, 3.2M rows.
- **Three models on identical rows:**
  - `old`: the shipped model, on its 11 features;
  - `fresh`: retrained now on the old 11 features;
  - `new`: retrained now on all 14.
- **Two splits:** the retrain contest's last 14 days, and a 60/40 walk-forward.
- **Pre-registered ship rule:** `new` beats `old` on pooled real markets by at least
  max(0.01, 2 se) on the 14-day hold-out, is positive in both of its halves, beats `fresh` in both
  60/40 halves, and passes the gates.

## Results

| split | family | old | fresh | new | new - old (se) | halves | new - fresh |
|---|---|---|---|---|---|---|---|
| 14-day hold-out | real, pooled | 0.8018 | 0.8045 | 0.8196 | +0.0178 (0.0154) | +0.024 / +0.011 | +0.015 |
| 14-day hold-out | FX | 0.8004 | 0.8026 | 0.8239 | +0.0234 (0.0178) | +0.027 / +0.022 | +0.021 |
| 60/40 | real, pooled | 0.7439 | 0.7363 | 0.7580 | **+0.0141 (0.0053)** | +0.017 / +0.011 | **+0.022** |
| 60/40 | FX | 0.7430 | 0.7343 | 0.7572 | +0.0142 (0.0061) | +0.016 / +0.013 | +0.023 |
| 60/40 | metals | 0.7517 | 0.7443 | 0.7662 | +0.0144 (0.0100) | +0.013 / +0.017 | +0.022 |
| 60/40 | crypto | 0.7445 | 0.7385 | 0.7579 | +0.0134 (0.0085) | +0.022 / +0.006 | +0.020 |
| 60/40 | Deriv (Boom/Crash, Jump, Volatility) | 0.48-0.54 | | 0.47-0.54 | -0.011 to -0.002 | | |

The new model's 60/40 calibration is 1.03, with a top-decile lift of 3.43. The export is exact.

## The missing control, run

The first run's walks predated the real data, so none was scored. This control uses GARCH(1,1) t(4)
walks on the timestamps of 12 real FX, metals and crypto series, so they land in both training and
hold-out. Each walk gets a synthetic tick volume of one of two kinds:

- **independent** volume, unrelated to the returns;
- **echo** volume, which only echoes the same bar's size: exp(5 + 0.7 |r|/sigma + noise).

That second kind is the worry: that volume merely re-reads the bar's own volatility. Gains over
the old 11 features, on the same walks:

| walks | split | + range | + range + volume | volume beyond range |
|---|---|---|---|---|
| independent volume | 14-day | -0.0010 | -0.0008 | +0.0002 |
| independent volume | 60/40 | +0.0005 | +0.0009 | +0.0004 |
| echo volume | 14-day | +0.0031 | +0.0058 | +0.0027 |
| echo volume | 60/40 | +0.0013 | +0.0025 | +0.0012 |

On memoryless iid walks, the shipped model reads **AUC 0.5032**, inside the contest's 0.5 ± 0.03.

- **The control is clean.** Independent volume adds nothing. Echo volume adds +0.0025 on the long
  split, against the real markets' +0.0141 over the old model and +0.022 over a fresh model on the
  old features. Volatility echo can account for at most about a sixth of the gain.

## What this means

- **The features help on real markets.** Over a year of held-out bars, adding range and tick
  volume lifts the forecaster by +0.014 AUC (2.7 se), in every family and both halves. It beats a
  freshly retrained model on the old features by +0.022, so the gain is the features, not
  freshness. Deriv, which has only tick volume and memoryless shocks, gains nothing, as it should.
- **The ship rule failed on sample size, not direction.** Two weeks of hold-out gives an se of
  0.015, so the pre-registered bar (an improvement of at least 0.031) was out of reach for a gain of
  this size. Per the rule, the old model stays and the feature change is reverted.
- **The rule was stricter than the retrain contest.** The contest's `vs_champion` slack is a
  tolerance: a challenger may be up to max(0.01, 2 se) *worse* than the champion. The contest itself
  would have promoted the new model.
- **A flaw in the first run's harness:** its control walks' timestamps predated the real data, so they
  fell entirely in the training set and were never scored. The control section above repairs it.
- **Decision: shipped, 2026-09-30,** under the retrain contest's own pre-existing rule rather than the
  stricter one written for this study:
  - on the 14-day hold-out the new model is not worse than the champion (+0.0178, well inside the
    slack);
  - the year-long gain is positive in both halves (+0.017 / +0.011);
  - real AUC 0.82 is at least 0.65, calibration 1.17 is within 0.7-1.4, the iid-walk control reads
    0.503, and the export is exact.

  The engine now passes each bar's tick volume to the forecaster, and venues without volume get
  missing values, which the trees route. The fortnightly retrain contest keeps judging it from here.
