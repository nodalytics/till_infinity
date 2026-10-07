# What each normalisation leak is worth, in fabricated skill

**Measured 2026-10-07**, 4h only. Asked for after this session was fooled once
already: the first online run reported an IC of **+0.30** against an honest
+0.0047, because it learned from each bar before that bar's label existed. One
line, a hundredfold inflation. The question is which of the ordinary
normalisation mistakes do the same, and by how much.

Code: [`zscore_leak.py`](../ideas/zscore_leak.py). Same 218,440 4h bars, same
sixteen instruments, same model, same target. The pipelines differ **only** in
where their statistics come from.

| pipeline | what leaks |
|---|---|
| `honest` | nothing. Rolling z-scores, target over the ATR at the bar, split by date with the boundary purged |
| `scaler` | features standardised with the whole dataset's mean and variance - `fit_transform` on everything before splitting |
| `z_full` | the z-scores computed against the **full sample's** mean and standard deviation instead of a rolling window |
| `atr_full` | the target divided by the sample's mean ATR instead of the ATR at the bar |
| `clip_full` | features winsorised at the full sample's 1st and 99th percentiles |
| `random_split` | honest features, test rows drawn at **random** instead of by date |
| `everything` | all of them - the pipeline that looks reasonable in a notebook |

## The signed move, where there was nothing to inflate

| pipeline | IC | vs honest | decile spread |
|---|---:|---:|---:|
| `honest` | +0.0045 | - | +0.056 |
| `scaler` | +0.0045 | **x1.0** | +0.056 |
| `z_full` | -0.0046 | x-1.0 | +0.040 |
| `atr_full` | +0.0084 | x1.8 | +0.038 |
| `clip_full` | +0.0034 | x0.7 | +0.044 |
| **`random_split`** | **+0.0127** | **x2.8** | **+0.115** |
| **`everything`** | **+0.0227** | **x5.0** | **+0.190** |

## The magnitude, where there is a real result to flatter

| pipeline | IC | vs honest | decile spread | vs honest |
|---|---:|---:|---:|---:|
| `honest` | +0.0786 | - | +0.256 | - |
| `scaler` | +0.0786 | **x1.0** | +0.256 | x1.0 |
| `z_full` | +0.0685 | x0.9 | +0.240 | x0.9 |
| **`atr_full`** | +0.1038 | x1.3 | **+0.711** | **x2.8** |
| `clip_full` | +0.0777 | x1.0 | +0.263 | x1.0 |
| `random_split` | +0.0944 | x1.2 | +0.317 | x1.2 |
| **`everything`** | **+0.2654** | **x3.4** | **+1.146** | **x4.5** |

## Four things worth keeping

**1. The most-warned-about leak does nothing.** Standardising features on the
whole dataset - the `fit_transform` before the split that every tutorial flags -
changes the result by **exactly zero**, to four decimals, on both targets. A
gradient-boosted tree splits on order, and a global affine rescaling does not
change the order of anything. The warning is real for linear and
distance-based models and is **noise for the model actually in use here**.

**2. Random splitting is the worst single leak on direction** - 2.8x the IC and
twice the spread. Nothing about the features changed; the target is a 3-bar
forward move, so a random split puts the same move on both sides of it. Any
forward-looking label makes a random split a leak, and the overlap does not have
to be large to matter.

**3. Full-sample ATR normalisation is the worst single leak on magnitude** - 2.8x
the spread. Dividing the target by a constant per-instrument ATR instead of the
ATR *at the bar* leaves the volatility regime inside the target, and volatility
clusters, so the model predicts the regime instead of the move. The honest
version has the ATR in the denominator precisely to take that away.

This one is the trap specific to the result this desk cares about. The real
magnitude model's decile spread is **0.256**; the leaky pipeline claims **1.146**
for the same model on the same bars. A magnitude result with a spread above
roughly 1 ATR is the signature of this mistake, not of a better model.

**4. They multiply.** `everything` is 5x the IC on the signed target and 4.5x the
spread on magnitude - more than any single leak, and more than their sum. The
signed `everything` row reports IC +0.0227 with a +0.19 decile spread, which
reads as a modest, plausible, entirely fabricated edge. That is the dangerous
shape: not an absurd number anybody would question, but a believable one.

## The standing rule

Every statistic that touches a feature or a target has to come from bars at or
before the bar it describes, and the split has to be by date with the horizon
purged. Where that is impractical, the honest and leaky versions should be run
side by side and both reported - it costs one function, and this file is what the
difference looks like.

See also [`zscore-ml.md`](zscore-ml.md) for the label-timing leak in the online
run, which was larger than every pipeline leak here put together.
