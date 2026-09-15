# Echo state networks on the Deriv Volatility grid

**2026-09-13. `research/harness/seqesn.py`. The reservoir arm of the
sequence-model study, and the one that owns the 4h-to-1d end of `seqlab.GRID`.**

Why this arm is separate from the recurrent-net arm rather than a variant of it:
the sample collapses across the grid. 1h holds 50,000 bars, 4h about 16,900, 1d
**under 2,800**. A gradient-trained LSTM at 1d has more parameters than samples
and will memorise, so whatever it scores there is a statement about its capacity.
An echo state network puts the entire nonlinearity into a fixed random reservoir
and trains one linear readout by ridge regression, and the effective degrees of
freedom of that readout are `sum_j s_j/(s_j + lambda)` — a number this harness
computes and prints rather than hopes about.

Two things were asked. **Direction is a null calibration**, not a hunt:
`research/deriving.md` proves `E[net] = -(c/2) x turnover` for any predictable
position on a martingale and a Volatility index is GBM at a published constant
sigma, so the target is AUC 0.50 and anything above it is first a bug in this
file. **Magnitude is the open question**: `seqlab.main()` measures naive srel
0.8802 against unconditional-mean srel 0.6691 on Volatility 75 Index at 1h, and a
simulated GBM at the named sigma returns 0.8809/0.6642 — indistinguishable. Can a
reservoir beat the unconditional mean on `logvol` where the last realised value
cannot?

## The answer

**No, on nineteen of twenty constant-sigma members, at every timeframe, and the
same harness finds volatility clustering on real markets at twenty to a hundred
times the size it finds on any of them.**

| | cells | ESN `logvol` r2 | GBM null | shuffled | ESN direction AUC |
| :-- | ---: | ---: | ---: | ---: | ---: |
| Volatility family + Spot Up | 154 | −0.0107 to +0.0015 | −0.0034 to −0.0000 | −0.0072 to −0.0001 | 0.4981 to 0.5064 |
| Real markets (the control) | 40 | **+0.0558 to +0.1140** | −0.0021 to −0.0000 | −0.0008 to −0.0001 | 0.5056 to 0.5295 |

Two things sit alongside that and are the parts worth keeping.

**`Spot Up - Volatility Up Index` is the exception, and it is the one the
prediction named.** It is the only member of the family whose name says the
variance moves, and it is the only one that clears its own null — r2 **+0.0274**
on 41,565 rows at 3m against a GBM null of −0.0000 and a shuffled target of
−0.0000. Every constant-sigma member sits at zero.

**The reservoir buys nothing.** On that same cell a plain ridge on the identical
28 features with no reservoir at all scores **+0.0271** against the ESN's
+0.0274. On BTCUSD at 3m, where the effect is nine times larger, static ridge
+0.2493 against ESN +0.2434 — the static features are *ahead*. Across 154 family
cells the ESN beats the static ridge at 3m/15m by 0.0000 to 0.0002 and loses to
it at every timeframe from 4h down. The recurrence is not paying for itself
anywhere in this study.

---

## What was built

`research/harness/seqesn.py`, on top of `research/harness/seqlab.py` as the only
data, feature and split layer. **Nothing was added to `seqlab.py`** — six other
arms were editing it concurrently and a shared file is the wrong place to race.
The one generator this arm needed that the floor did not have, a GARCH(1,1)
positive control, lives in `seqesn.py`; `gbm_bars`, `surrogate_bars`,
`measured_sigma`, `phase_surrogate`, `shuffle_target`, `walk_forward`, `build`,
`targets`, `tick_size` and `max_of_k` all come from the floor.

* **The reservoir.** `h_t = (1-a) h_{t-1} + a tanh(W_in u_t + b + W h_{t-1})`,
  with `W` sparse at a fixed in-degree of 10 — fixed in-degree rather than fixed
  density, so the cost of one state step does not grow with reservoir size and a
  2,000-unit reservoir is affordable on a 50,000-bar series.
* **The readout.** Ridge on `[HAR(3) | features(28) | state(N)]`, with the four
  models — HAR, static ridge, state-only readout, full ESN — laid out as
  **contiguous slices of one Gram matrix**. That is not tidiness: all four are
  fitted from a single accumulation over the data and are on identical rows by
  construction rather than by a convention someone has to keep.
* **Expanding-window folds** from `seqlab.walk_forward`, the Gram accumulated
  forward through them exactly once and centred analytically at each fold end
  (`G_c = G - n mu mu^T`), so the intercept is always the training block's mean.
* **The penalty ladder is free**, because one eigendecomposition of each block
  Gram serves every penalty and the Gram does not depend on the target. Every
  target and every shuffled control on one reservoir costs one matrix-by-vector
  rather than a second fit — which is why the controls are beside every number
  rather than on a sample of cells.

---

## The five kill conditions, stated before the numbers and checked before them

All five ran in `STAGE=check` before any cell of the grid was scored.

### 1. Causality — CLEAN

`seqlab.check_causality` on Volatility 75 Index at 1h: **49,950 rows checked, no
feature at row `t` moves when a bar after `t` is perturbed.**

### 2. Memory capacity must not exceed the reservoir size — held, worst ratio 0.762

Jaeger's bound `MC <= N` is exact for a linear reservoir driven by iid input, so a
measured `MC` above `N` is an overfitting artefact in the readout. On
29,700–29,825 rows of iid uniform input:

| N | rho | MC in-sample | MC/N | MC out-of-sample | half-life |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 0.50 | 12.617 | 0.505 | 12.579 | 7 |
| 25 | 0.99 | 19.040 | **0.762** | 18.885 | 10 |
| 50 | 0.90 | 29.922 | 0.598 | 29.607 | 15 |
| 50 | 0.99 | 32.757 | 0.655 | 32.128 | 17 |
| 100 | 0.50 | 15.841 | 0.158 | 15.705 | 8 |
| 100 | 0.99 | 47.566 | 0.476 | 46.651 | 24 |

The bound holds everywhere, capacity rises with size and with spectral radius,
and in-sample and out-of-sample agree to within 2% — which is what licenses using
the out-of-sample figure on feeds, where the reservoir is wider than the
training block.

### 3. The echo state property — measured, not assumed

Two trajectories from different random initial states on the same 5,000-step
input, 200 units:

| rho | leak | gap at the 100-step washout | gap at step 5000 | per-step | forgets |
| ---: | ---: | ---: | ---: | ---: | :-- |
| 0.50 | 0.15 | 3.29e-05 | 0.00e+00 | 0.870 | yes |
| 0.90 | 0.05 | 1.34e-01 | 1.11e-16 | 0.993 | yes |
| 0.95 | 0.15 | 1.19e-02 | 1.11e-16 | 0.993 | yes |
| 1.00 | 0.15 | 2.17e-02 | 1.11e-16 | 0.993 | yes |
| 1.20 | 0.05 | 3.55e-01 | 6.82e-12 | 0.995 | yes |
| **1.40** | **0.05** | **6.47e-01** | **6.32e-06** | 0.998 | **no** |
| 1.40 | 1.00 | 2.28e-01 | 1.05e-15 | 0.993 | yes |

Every `rho < 1` configuration forgets; the one that does not is `rho = 1.4` with
`leak = 0.05`, the boundary the sweep was told to cross. **Two caveats recorded
rather than smoothed:** the tanh nonlinearity keeps most `rho > 1` reservoirs
contracting, so the echo state property is not simply `rho < 1` here; and 6 of
the 9 `rho < 1` configurations are still more than 1e-6 apart *at the 100-step
washout*, which is a slow reservoir rather than a broken one. The washout
sensitivity check below is the evidence that this moves no number.

### 4. Direction on a known null — 0.4967 and 0.4979 against a true 0.5000

`seqlab.gbm_bars` at the named sigma, on a quote lattice, 16,565 scored rows;
`r2` on `logvol` +0.0000 and −0.0000, shuffled target 0.4975 and 0.5001.

### 5. The positive control — the harness finds clustering where there is some

**The condition that makes a negative result mean anything.** A GARCH(1,1) at
`alpha + beta = 0.98`, built at the same per-bar variance as the null above so it
differs from it in exactly one property: the conditional variance moves. 16,565
scored rows.

| reservoir | r2 esn | r2 static | r2 har | r2 naive | r2 shuffled | srel esn | srel mean |
| :-- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N=100 rho 0.9 leak 0.4 in 0.2 | **+0.0361** | +0.0352 | +0.0369 | −0.8566 | −0.0002 | 0.6685 | 0.6911 |
| N=300 rho 0.95 leak 0.15 in 0.2 | +0.0358 | +0.0352 | +0.0369 | −0.8566 | −0.0001 | 0.6685 | 0.6911 |
| N=300 rho 0.9 leak 0.4 in 0.8 | +0.0357 | +0.0352 | +0.0369 | −0.8566 | −0.0003 | 0.6694 | 0.6911 |

The harness resolves real clustering at r2 ≈ +0.036 with the shuffled control at
−0.000. **And the reservoir buys nothing over the static features even here** —
ESN +0.0361, static ridge +0.0352, HAR +0.0369. That is the expected result for a
GARCH, whose conditional variance is a linear function of past squared returns
and therefore exactly what a HAR expresses, and it is the calibration against
which the same finding on the real feeds has to be read.

### Washout sensitivity

On the same null at N=300, washout 25 / 100 / 400 gives r2 −0.0001 / −0.0000 /
−0.0002 and AUC 0.4999 / 0.5010 / 0.4992 over 16,628 / 16,565 / 16,315 rows.

---

## The sensitivity ladder: what this harness would have caught

A null is worth reading only beside its power. The generator is GARCH(1,1) at a
known persistence, at **the row counts the real grid actually has**. `sd(log
sigma)` is the realised spread of the true conditional volatility.

| sd(log sigma) | rows | r2 esn | r2 static | r2 har | r2 shuffled |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.033 | 2,232 | −0.0062 | −0.0060 | −0.0005 | +0.0011 |
| 0.095 | 2,232 | −0.0006 | −0.0066 | +0.0000 | +0.0007 |
| 0.141 | 2,232 | −0.0077 | +0.0009 | +0.0063 | +0.0000 |
| 0.266 | 2,232 | +0.0329 | +0.0315 | +0.0339 | +0.0001 |
| 0.322 | 2,232 | +0.0676 | +0.0753 | +0.0753 | −0.0001 |
| 0.098 | 13,982 | +0.0072 | +0.0061 | +0.0077 | −0.0001 |
| 0.143 | 13,982 | +0.0157 | +0.0150 | +0.0164 | −0.0005 |
| 0.256 | 13,982 | +0.0496 | +0.0469 | +0.0494 | −0.0002 |
| 0.303 | 13,982 | +0.0645 | +0.0596 | +0.0650 | −0.0002 |

**The detection floor**, taken at r2 > 0.005:

| rows (matching) | smallest sd(log sigma) resolved |
| ---: | ---: |
| 2,800 (1d) | 0.27 |
| 8,400 (8h) | 0.10 |
| 16,900 (4h) | 0.098 |
| 50,000 (1h) | ≈0.09–0.13 |

**The 1d end of this grid is nearly blind.** At 2,232 usable rows nothing below
`sd(log sigma) ≈ 0.27` registers, which is more volatility clustering than most
equity indices carry daily. That is a limit on this arm's headline timeframe and
it is stated here rather than left implicit: a flat 1d result does not mean a
Volatility index has constant sigma at 1d, it means 2,800 bars cannot tell. The
1h-and-finer results are the ones carrying weight, and they are also the ones
with the most rows.

---

## The grid: 27 symbols x 8 timeframes, every control beside every number

Six reservoirs per cell, each selected **by walk-forward validation on a block
that precedes the test block** — never by the test score and never by GCV, for
the reason in the failures section. Every cell carries its shuffled target, a
phase surrogate and a GBM null at the symbol's own sigma, all on the identical
row set. 154 of 176 family cells scored; 22 skipped, 14 for thin history (12h and
1d on the five symbols whose feed only goes back months) and 8 because
`Spot Up - Volatility Down Index` 404s on all eight timeframes.

### `logvol`, averaged over symbols. r2 = 0 *is* the unconditional mean

| tf | cells | rows | ESN | static ridge | HAR | GBM null | shuffled | ESN AUC | GBM AUC |
| :-- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3m | 21 | 41,565 | +0.0012 | +0.0013 | +0.0007 | −0.0000 | −0.0003 | 0.5004 | 0.4980 |
| 15m | 21 | 35,446 | +0.0015 | +0.0016 | +0.0002 | −0.0005 | −0.0001 | 0.5011 | 0.4977 |
| 1h | 21 | 25,461 | +0.0007 | +0.0005 | +0.0001 | −0.0005 | −0.0009 | 0.5028 | 0.5011 |
| 4h | 21 | 7,516 | −0.0039 | −0.0011 | −0.0009 | −0.0018 | −0.0014 | 0.5008 | 0.4984 |
| 6h | 21 | 4,954 | −0.0047 | −0.0016 | −0.0012 | −0.0034 | −0.0072 | 0.5026 | 0.4918 |
| 8h | 21 | 3,670 | −0.0072 | −0.0050 | −0.0017 | −0.0010 | −0.0023 | 0.4981 | 0.4955 |
| 12h | 16 | 3,092 | −0.0064 | −0.0060 | −0.0017 | −0.0022 | −0.0021 | 0.5026 | 0.5146 |
| 1d | 12 | 1,887 | −0.0107 | −0.0046 | −0.0015 | −0.0033 | −0.0058 | 0.5064 | 0.5052 |

The family average never separates from its own null anywhere. The negative
values from 4h down are the reservoir paying for its parameters at sample sizes
that cannot support them — and note that the ESN is *more* negative than the
static ridge at every one of those rows, which is the same statement as "the
recurrence buys nothing" seen from the cost side.

### The one exception, and it is the one the prediction named

`seqlab.SPOT_UP` holds the two instruments whose names say the variance moves.
One of them answers on the feed; `Spot Up - Volatility Down Index` returns HTTP
404 on all eight timeframes and is absent from this study entirely.

| tf | rows | ESN | static | HAR | naive | shuffled | GBM | surrogate |
| :-- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3m | 41,565 | **+0.0274** | +0.0271 | +0.0161 | −0.9424 | −0.0000 | −0.0000 | −0.0002 |
| 15m | 29,108 | +0.0126 | +0.0129 | +0.0064 | −0.9594 | −0.0000 | −0.0004 | −0.0001 |
| 1h | 7,201 | +0.0191 | +0.0155 | +0.0071 | −0.9548 | −0.0008 | −0.0017 | −0.0003 |
| 4h | 1,725 | +0.0081 | +0.0074 | +0.0017 | −1.0562 | +0.0024 | −0.0068 | −0.0027 |
| 6h | 1,089 | −0.0000 | −0.0028 | −0.0003 | −1.0661 | −0.0013 | −0.0000 | −0.0136 |
| 8h | 723 | −0.0105 | −0.0232 | −0.0056 | −0.9841 | +0.0007 | −0.0009 | −0.0084 |
| 12h | 359 | −0.0105 | −0.0063 | −0.0015 | −0.7876 | −0.0000 | −0.0070 | −0.0000 |

It is real at 3m, 15m, 1h and 4h, and it disappears exactly where the sensitivity
ladder says it must — at 1,089 rows and below, this harness could not see an
effect of that size if it were there. On srel, the scale `seqlab.main()` and
`research/forecasting.md` report: **0.6704 for the ESN against 0.6777 for the
unconditional mean** at 3m, where the naive last-realised-value predictor gets
0.8851 and the simulated GBM at the same sigma gives 0.6723 / 0.6723 for exactly
no gap. Also: HAR gets only +0.0161 where the 28-feature static ridge gets
+0.0271, so most of what is there is not in the three realised volatilities.

### Direction: the null calibration came back null

Averaged over symbols the ESN's AUC runs 0.4981 to 0.5064 against a GBM null of
0.4918 to 0.5146 on the same rows. The largest single AUC in the family, 0.5743,
is **Volatility 90 Index at 8h on 261 rows**, where the naive control on the same
rows scores 0.4080 and the shuffled target 0.5335 — a cell too small to say
anything, and reported here so the family-wise line below is read correctly.

Family-wise: the best real cell is +0.0274 on `logvol` and 0.5743 on direction;
the best of 462 matched null cells is +0.0099 and 0.5554. The `logvol` maximum is
nearly three times its null's; **the direction maximum is not, and should be read
as the noise it is.**

### The positive control that makes the negative result falsifiable

The identical harness, identical features, identical splits, on `seqlab.REAL`.

| tf | cells | rows | ESN | static ridge | HAR | GBM null | shuffled | ESN AUC |
| :-- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3m | 5 | 41,563 | +0.0934 | +0.0916 | +0.0797 | −0.0000 | −0.0001 | 0.5195 |
| 15m | 5 | 41,565 | +0.0829 | +0.0664 | +0.0793 | −0.0000 | −0.0001 | 0.5186 |
| 1h | 5 | 41,565 | **+0.1140** | +0.1004 | +0.0779 | −0.0000 | −0.0002 | 0.5295 |
| 4h | 5 | 32,261 | +0.0863 | +0.0752 | +0.0564 | −0.0006 | −0.0001 | 0.5264 |
| 6h | 5 | 23,135 | +0.0699 | +0.0634 | +0.0369 | −0.0004 | −0.0005 | 0.5139 |
| 8h | 5 | 18,294 | +0.0558 | +0.0634 | +0.0437 | −0.0004 | −0.0003 | 0.5090 |
| 12h | 5 | 13,439 | +0.0594 | −5.3748 | +0.0481 | −0.0008 | −0.0008 | 0.5056 |
| 1d | 5 | 8,581 | +0.1098 | +0.0843 | +0.0592 | −0.0021 | −0.0004 | 0.5067 |

Single cells: BTCUSD at 3m **+0.2434**, BTCUSD at 1h +0.2036, XAUUSD at 15m
+0.1442, EURUSD at 1h +0.0805, GBPUSD at 3m +0.0425. Every GBM null and every
shuffled target on those same rows is within 0.0005 of zero.

**So "the reservoir found nothing on the Volatility family" is a statement about
the family.** The same code on gold, three currency pairs and bitcoin returns
between +0.04 and +0.24, twenty to a hundred times what any constant-sigma
member gives.

Two entries in that table are worth naming rather than hiding. The **−5.3748** is
the static ridge on one 12h cell: 28 collinear features, a short block and a
penalty the validation split chose badly on a fold — it is the same failure mode
as the sweep's blow-ups, surviving in one cell out of 194, and it is why the
ESN's own number is selected the way it is. And the 1d row is *higher* than 8h
and 12h on far fewer rows, which is a five-symbol average and not a trend.

### The readout, which is the interpretable half

Mean absolute correlation of each of the 28 features with `logvol` across the 154
family cells, beside the same quantity on each cell's own GBM null. The
correlation rather than the ridge coefficient is the column to read: these
columns are heavily collinear — `rv1`, `rv5`, `rv22`, `parkinson` and
`garman_klass` are five estimates of one quantity — and a ridge coefficient under
that much collinearity flips sign between a feed and its own null.

| feature | real | GBM null | real − null |
| :-- | ---: | ---: | ---: |
| spread_rel | 0.0137 | 0.0000 | +0.0137 |
| gap | 0.0115 | 0.0000 | +0.0115 |
| logvolume | 0.0149 | 0.0087 | +0.0061 |
| rv5 | 0.0123 | 0.0089 | +0.0034 |
| har_5_22 | 0.0116 | 0.0083 | +0.0033 |
| vol_of_vol | 0.0142 | 0.0115 | +0.0027 |
| n_distinct | 0.0058 | 0.0035 | +0.0024 |
| frac_zero | 0.0029 | 0.0018 | +0.0011 |

**None of this is a finding and all of it is small** — 0.0137 is a correlation of
one and a third per cent. The two at the top are artefacts of the null rather
than properties of the feed: the simulated null has a constant spread and no
gaps, so `spread_rel` and `gap` are exactly zero there by construction and the
difference is measuring the simulator. `research/rebuilding.md`'s loop is read the
largest feature, *measure it on the feed*, add one term, re-run — and on this
table there is nothing above the noise worth pointing a measurement at.

### The readout's timescales: it never buys long memory, not even where there is signal

The ESN analogue of `groundgru.py`'s Jacobian spectrum, and free of its one
confound. That page found a trained GRU's Jacobian spectrum reports its own
training horizon rather than the process's relaxation time. Here the dynamics are
**not trained**: linearised at `h = 0` the state map is `(1-a)I + aW`, whose
eigenvalues are fixed before any data arrives and give relaxation times
`tau_i = -1/log|mu_i|`. Only the readout is fitted, so projecting its weights onto
that eigenbasis asks a clean question — given a reservoir offering every
timescale from 1 to 49 steps, which does the ridge pay for?

| series | weighted median tau | p90 | reservoir's unweighted median | longest available |
| :-- | ---: | ---: | ---: | ---: |
| Volatility family (typical) | 2.71–3.07 | 6.1–6.7 | 2.96 | 49.31 |
| its own GBM null | 2.71–3.29 | 6.1–6.7 | 2.96 | 49.31 |
| BTCUSD 3m (r2 +0.2434) | 3.04 | 6.72 | 2.96 | 49.31 |
| XAUUSD 15m (r2 +0.1442) | 2.72 | 6.72 | 2.96 | 49.31 |

The readout sits on the middle of what the reservoir offers — 2.96 — on the
family, on the null, **and on the real markets where the effect is two hundred
times larger**. It never reaches for the 49-step modes. That is the same result
the ESN-versus-static-ridge comparison gives, arriving by a second route that
shares no arithmetic with it: whatever `logvol` predictability exists on these
feeds lives inside the window the static features already summarise, and a
state-space memory has nothing further to contribute.

---

## What broke, and why it is on the page rather than edited out

### GCV chose exactly the configurations that explode

The first full sweep — 5,040 cells, 6 symbols x 3 timeframes x 360 reservoir
configurations — selected the ridge penalty by generalised cross-validation, a
training-block criterion that costs nothing once the eigendecomposition exists.
Ranked by mean GCV, the best configuration in the entire sweep was
`N=800, rho=1.4, leak=0.05, input=0.05`, whose **mean out-of-sample R-squared is
−30,545**. The next five by GCV score between −1,026 and −15,349.

Two causes, both properties of reservoirs rather than of this implementation:

1. **Conditioning.** A reservoir at `leak = 0.05` produces a Gram with a
   condition number around 1e17. The directions at the bottom of that spectrum
   carry no training variance, so ridge leaves their weights unconstrained, and
   any test row with a component along them produces a prediction of arbitrary
   size. The fix is **truncation, not a larger penalty**: eigen-directions below
   1e-10 of the leading one are dropped, and the penalty ladder is now stated
   relative to the leading eigenvalue rather than absolutely.
2. **Non-stationarity.** A reservoir without the echo state property — condition
   3 names exactly which — never forgets its initial condition, so its state
   drifts and the test block is drawn from a different distribution than the
   training block. **No training-block criterion can see that.**

The penalty is now chosen by walk-forward validation on a block that precedes the
test block. On the pathological configuration the same fitted path scores −0.0000
under walk-forward selection and −7,372 under GCV. All three selectors are
reported side by side on every cell, because which one is used turned out to
matter more than any hyperparameter in the sweep.

### The one-standard-error rule costs most of the power at 1d

The conservative selector — the most-regularised penalty statistically
indistinguishable from the best — is what a prior of "there is nothing here"
argues for, and it was made the headline first. The ladder shows the cost: at
2,232 rows and `sd(log sigma) = 0.32`, obvious clustering, minimum-validation
returns +0.0676 and the one-standard-error rule returns **+0.0029**. It was
demoted to a robustness column. A selector that cannot be shown to have power is
indistinguishable from a harness that always says no.

### Two defects in the simulated controls, one inherited and one new

`seqlab.gbm_bars` was taking each bar's high as the maximum of its 24 sub-points
and leaving the open out, so **11.28% of simulated bars had a high below
`max(open, close)`** — impossible on a traded bar, and a free feed-versus-
simulation discriminator sitting inside the null every arm scores against. Found
and fixed in the shared floor by another arm; this harness's GARCH generator had
copied the same construction and carried the same defect, and was fixed with it.

The second is this arm's own. `seqlab.tick_size` recovers the quote grid as the
coarsest decimal lattice containing every close, and **a continuous float series
lies on no decimal lattice**, so it returns NaN, which propagates through
`rel_spread` into `spread_rel`. Every simulated control therefore came back with
either a zeroed feature or, in the first run against the updated floor, no usable
rows at all. Simulated series are now quantised onto a lattice before use — which
is the right thing independently: the feed quotes on a grid, `frac_zero` and
`n_distinct` are features on the record of having paid twice, and a continuous
null has `frac_zero` exactly 0 and `n_distinct` exactly 1.0 on every row where
the feed has neither.

**One run was discarded whole.** A 216-cell grid completed with the pre-fix
generators and every GBM and surrogate column NaN; rather than patch the table,
the run was thrown away and repeated from scratch on a fresh output directory.
The real-feed columns were identical to four decimal places in both, which is
the check that the discarded run was discarded for the reason stated.

### The first sweep was bandwidth-bound, not arithmetic-bound

The first working fold solver sliced the design inside the target loop —
`phi[test][:, block] - mu[block]`, fancy indexing and therefore a copy — sixteen
copies per fold, each the size of the block. On a 20,000-row series with an
800-unit reservoir that is roughly ten gigabytes of memory traffic per
configuration. The estimated sweep time went to 190 minutes and the machine's
load average to 44. Everything depending only on (block, fold) is now hoisted
above the target loop.

### srel needed a smearing correction, and the parametric one is wrong

`exp(yhat)` is a conditional *geometric* mean while `seqlab.main()` and
`research/forecasting.md` report arithmetic means of realised volatility, so the
raw exponential hands every model a low bias that reads as skill wherever the
residual spread differs between models. The parametric correction
`exp(yhat + s2/2)` is also wrong: it assumes a conditional mean of the log with
Gaussian residuals, which the naive predictor is not, and it inflated naive srel
from 0.88 to **1.16** on a simulated null where `seqlab.main()` measures 0.8809.
What is used is Duan's smearing estimator in ratio form,
`c = mean(rv_train) / mean(exp(yhat_train))`, estimated on the training block and
applied identically to every model. With it the harness reproduces the floor's own
baselines on a simulated GBM: **naive srel 0.8798 against 0.8809, unconditional
mean 0.6589 against 0.6642.**

### The research box

Off the network for roughly three hours mid-study, then up for fifteen minutes
and off again. The MT5 feed this study pulls from is loopback on that same host,
so there was no second route to the data either. Runs now checkpoint every ten
cells and resume from the checkpoint, which is the difference between a study
that finishes and one that restarts.
