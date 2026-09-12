# A foundation model reads the synthetics at the null, and loses to a straight line on their volatility

**Kronos-mini, fine-tuned and zero-shot, on `seqlab` folds. Run 2026-09-12.**

Kronos is a decoder-only foundation model for candlestick data - a tokenizer
that quantises OHLCV into discrete codes and a transformer that predicts the
next code. `Kronos-mini` is the 4.1M-parameter variant. This page puts it on
Deriv's Volatility family and on five real markets and scores it against the
baselines every other arm of the sequence study uses.

**The prior was strong and it held.** `research/deriving.md` proves
`E[net] = -(c/2) x turnover` for any predictable position on a martingale; a
Volatility index is geometric Brownian motion at a published constant sigma, so
its increments are independent by construction; `research/rebuilding.md` already
found boosted models scoring nothing on these feeds with `n*` infinite on every
arm. A model pretrained on real equities and crypto has no mechanism by which it
could predict the sign of the next bar of a synthetic GBM.

So this is a **null calibration with a strong prior**, plus the one question
inside it whose answer was not known: how much of Kronos's pretraining is market
structure that synthetics do not have.

**The four numbers.** Volatility family, 1h, one bar ahead, 13 symbols,
23,865 scored rows, `seqlab` walk-forward folds with a one-bar purge:

| | Kronos-mini | floor | verdict |
| --- | ---: | ---: | --- |
| direction, median AUC | **0.4961** | 0.50 | at the null; largest deviation 2.15 se, family-wise p 0.34 |
| volatility, median srel | **0.6963** | 0.6687 (unconditional mean) | **loses to a horizontal line on 13 of 13** |
| volatility against a *permuted* target | 0.6963 | 0.6959 | carries no information at all |
| next-token entropy, feed against simulated GBM | 3.712 | 3.930 | **can tell them apart, cannot predict either** |

A 4.1M-parameter foundation model pretrained on real markets, handed the raw
candles rather than a feature matrix, sampling its own predictive distribution
64 times per row, does not beat one number computed from the training block. It
is the correct answer for geometric Brownian motion at constant sigma. Nobody in
this folder had measured it.

## One: it runs, and what it cost

Upstream cloned to `~/till_infinity/vendor/Kronos` on the research lab at
`67b630e`, **outside the git tree** - `lab.sh sync` runs `rsync --delete` over
`repo/`, so a checkout in-tree is deleted on the next sync. Nothing from
upstream landed in this repository and `.gitignore` needed no change.

The identifiers were read off the hub rather than remembered, and the pairing
matters: `Kronos-mini` takes `Kronos-Tokenizer-2k`, every larger variant takes
`Kronos-Tokenizer-base`, and the two tokenizers differ only in `group_size`
(5 against 4) so a mismatched pair loads without error.

| | parameters | d_model | layers | s1/s2 bits |
| --- | ---: | ---: | ---: | --- |
| `NeoQuasar/Kronos-mini` | 4,108,032 | 256 | 4 | 10 / 10 |
| `NeoQuasar/Kronos-small` | 24,741,376 | 512 | 8 | 10 / 10 |
| `NeoQuasar/Kronos-Tokenizer-2k` | 3,958,042 | 256 | 4 enc / 4 dec | 10 / 10 |

Both models pull in **0.4 s** and the whole install is under 40MB. There is no
GPU on the lab and none is needed.

### The published example, reproduced before anything was trusted

`examples/prediction_example.py` as published **cannot run**: it reads
`./data/XSHG_5min_600977.csv`, which is not in the repository. The same code
path was run instead on `finetune_csv/data/HK_ali_09988_kline_5min_all.csv`,
real 5-minute Hong Kong equity K-lines that upstream does ship - lookback 400,
`pred_len` 120, `T=1.0`, `top_p=0.9`, `sample_count=1`, on CPU.

| pair | seconds | forecast finite | first-step jump | forecast RV / true RV | MAPE over 120 bars | direction hit |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| mini + Tokenizer-2k | 1.85 | yes | 0.14% | 0.463 | 0.79% | 0.4417 |
| small + Tokenizer-base | 4.88 | yes | 0.16% | 1.512 | 2.50% | 0.5250 |

The forecast is continuous with the last observed close, carries a realised
volatility inside a factor of two of the truth it was not shown, and tracks the
level to under 1% over ten hours of 5-minute bars. **The plumbing works.** The
direction hit rate of 0.44 and 0.53 on 120 bars is what a sampler does on a
near-martingale and is not evidence of anything either way.

### The budget, stated

Measured on the lab (`kronosboot.benchmark`, Kronos-mini, batch of 16, **8
threads** - five other agents share the box):

| context | ms per batch of 16 | windows/s |
| ---: | ---: | ---: |
| 64 | 44.2 | 362.1 |
| 128 | 82.1 | 194.8 |
| 256 | 189.3 | 84.5 |
| 512 | 544.8 | 29.4 |

The study runs at **ctx = 128 bars and 64 samples per scored row**, against
Kronos-mini's published context of 2048. That is a budget decision and it is
priced below.

**Sampling was made free rather than cheap.** Upstream's
`auto_regressive_inference` decodes `S` full-length token sequences per scored
row; at S=64 and ctx=128 that is ~32 GFLOP per row and hours per timeframe on
CPU. The tokenizer's decoder is causal, so positions `0..T-1` are identical
across all `S` candidates: `kronoslib` runs the context once, keeps the keys and
values, and steps the `S` candidates against them with the `S` carried in the
sequence dimension so the cache is never replicated. `kronoslib.verify` proves
the cached path *is* upstream rather than an approximation of it, and it runs
before any score:

| check | max absolute error | signal scale |
| --- | ---: | ---: |
| cached decoder step against `tokenizer.decode` | 3.73e-07 | 4.89 |
| cached decoder context against `tokenizer.decode` | 1.19e-06 | 4.89 |
| `_cond_s2` against `Kronos.decode_s2` | 7.63e-06 | - |

## Two: the tokenizer look-ahead, and how it was closed

This is the single most likely way this arm produces a false positive. It is
handled in code, asserted against the model by an experiment rather than by a
comment, and `research/harness/kronosleak.py` exists to price what the mistake
would have been worth - that last one is written but was not run before the lab
went off the network, and section ten says so.

**The tokenizer cannot leak through its own weights.** `KronosTokenizer`'s
encoder and decoder are stacks of `TransformerBlock`, and
`MultiHeadAttentionWithRoPE.forward` calls
`scaled_dot_product_attention(..., is_causal=True)` - the code at position `t` is
a function of normalised bars `0..t` and nothing later. The quantiser itself is
`BinarySphericalQuantizer`, which is `sign(z)` on an L2-normalised projection:
**no codebook, no fitted centroid, no running statistic**, nothing that could
have been fitted across a split. Its weights come from Kronos's pretraining
corpus, which contains none of this study's rows.

That leaves two places a future bar could enter, and both are closed:

1. **The window normalisation.** `KronosPredictor.predict` z-scores whatever
   frame it is handed. Every window here **ends at the row being scored** and is
   normalised inside itself, which is also upstream's own convention -
   `finetune/dataset.py` z-scores on the lookback part only.
2. **Fine-tuning.** The predictor is refit from the pretrained weights **per
   fold, on that fold's train rows alone**, and the tokenizer is never trained at
   all. Freezing it turns "the quantiser never saw a test row" from a promise
   into a property of the code.

**And the model is put through the same instrument `seqlab.check_causality`
points at the feature matrix.** A future bar is multiplied by 1.05 (volume by
3.0) and the next-token logits at 24 earlier rows are recomputed:

    poked row 49,980 of Volatility 75 Index 1h, 24 rows checked,
    max logit movement = 0.0 exactly

Not "below tolerance" - identical to the bit. The logits are deterministic, so
this is an exact comparison and not a tolerance on a sampler.

## Three: what was scored, and against what

One bar ahead, `horizon=1`, on `seqlab.walk_forward` folds - expanding window,
one-bar purge, never shuffled - so the rows are the rows every other arm of this
study uses. Folds are cut over the rows usable to **both** the baselines and a
128-bar Kronos context, so the warm-up is 128 bars rather than the 22 the
feature matrix alone needs and the fold edges sit correspondingly later.

Scored test rows are capped per cell and decimated uniformly *inside* each fold,
and **the baselines are scored on exactly those rows**. A baseline scored on
more rows than the model is not a baseline.

* **direction** - `seqlab.auc` of Kronos's mean sampled log return against
  `targets['direction']`. Floor 0.50.
* **volatility** - `seqlab.srel` of Kronos's mean sampled absolute return
  against `targets['realised']`, which at `horizon=1` is exactly
  `|log(c_{t+1}/c_t)|`. Against the **unconditional mean** of the fold's *train*
  realised volatility, **naive** last-realised (`rv1`, which is `|r_t|`), and
  **log-HAR** over the `seqlab.HAR` triple fitted on the fold's train rows with
  Duan's smearing factor carried back.

**Two readout details that decide whether the numbers mean anything.**

A 20-bit code over six channels is a coarse description of one bar. On a
Volatility 75 1h bar the true move is about 0.8% while the window's own close
dispersion over 128 bars is several percent, so one bar of a GBM's motion is a
*small fraction of a quantisation cell*. Comparing Kronos's decoded next close
against the **observed** close therefore measures reconstruction error, not
forecast error. Every return here is taken against **the tokenizer's own
reconstruction of the current bar**, which the context decode pass produces for
free, so the quantisation bias cancels on both sides. The raw version is carried
beside it as `auc_dir_raw`.

A rank AUC is scale-free; `seqlab.srel` is not. Kronos's mean absolute decoded
return is not on the same units as `|log(c_{t+1}/c_t)|`, so **one scalar per
fold** is fitted on **train rows only** (a median ratio over at most 250
decimated train rows) to put it on scale. That is one fewer free parameter than
HAR is given.

Three controls sit beside every headline: **`shuffle`** (targets permuted inside
the test block), **`surrogate`** (phase-randomised returns - the spectrum and
the full linear autocorrelation survive, every nonlinear dependence including
volatility clustering does not), and **`gbm`** (simulated geometric Brownian
motion at the symbol's true `seqlab.NAMED_SIGMA`, wearing the real feed's own
timestamps so the learned temporal embeddings cannot separate them).

## Four: direction, which is the null calibration

**Kronos-mini finds nothing, and the controls say the nothing is the right
nothing.** Volatility family, 1h, one bar ahead, `seqlab` folds:

| arm | cells | scored rows | AUC median | min | max | median \|AUC−0.5\| | median bootstrap se | shuffled |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| feed | 13 | 23,865 | **0.4961** | 0.4845 | 0.5337 | 0.0101 | 0.0131 | 0.4904 |
| surrogate | 13 | 23,865 | 0.4878 | 0.4662 | 0.5141 | 0.0127 | 0.0132 | 0.5006 |
| gbm | 12 | 22,490 | 0.5124 | 0.4844 | 0.5227 | 0.0136 | 0.0132 | 0.5178 |

The median deviation from 0.50 on the real feed (0.0101) is **smaller** than on
the simulated GBM (0.0136) and smaller than on the phase surrogate (0.0127).
Whatever the model is doing, it does the same amount of it on a series generated
in this harness at a known sigma as on the broker's own.

The per-symbol spread is the part that has to be read with the family-wise
correction in front of it. With thirteen symbols the best of thirteen fair coins
clears 0.53 routinely, and it did:

| family | arm | cells | largest \|AUC−0.5\| in its own se | at | AUC | n | per-test p | family-wise p | n\* |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| Volatility | feed | 13 | 2.15 | Volatility 15 Index | 0.5337 | 1,375 | 0.032 | **0.343** | 4,586 |
| Volatility | surrogate | 13 | 2.77 | Volatility 50 (1s) Index | 0.4662 | 1,980 | 0.006 | 0.070 | 3,964 |
| Volatility | gbm | 12 | 1.43 | Volatility 15 Index | 0.5227 | 1,375 | 0.153 | 0.864 | 10,366 |

The largest deviation on the real feed is 2.15 standard errors, family-wise
**p = 0.34**. The largest deviation anywhere in the table is on the *phase
surrogate* - a series with no nonlinear structure at all by construction - at
2.77 se. **The strongest apparent signal in this study is on the control that
has nothing in it**, which is the cleanest possible statement that the spread is
sampling noise.

`n*` on the best cell is 4,586 rows: to separate an AUC of 0.5337 from 0.50 at
this standard error would need about three times the sample the cell carries, and
that is the honest reading of every number in the column - failure to reject at
the power available, not proof.

## Five: volatility, where the unconditional mean beats everything

This is the interesting half, and it is the half where the foundation model
loses to a straight line - and then loses to a *horizontal* line.

`seqlab.srel`, median over the thirteen Volatility symbols at 1h, 23,865 scored
rows, lower is better:

| arm | Kronos \|r\| | Kronos sd | Kronos range | unconditional mean | naive last-realised | log-HAR | Kronos < mean | naive < mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| feed | 0.6963 | 0.6933 | 0.6820 | **0.6687** | 0.8870 | 0.6691 | **0/13** | **0/13** |
| surrogate | 0.7146 | 0.7066 | 0.7080 | 0.6806 | 0.8862 | 0.6807 | 0/13 | 0/13 |
| gbm | 0.6863 | 0.6874 | 0.6709 | 0.6622 | 0.8749 | 0.6623 | 0/12 | 0/12 |

Three things, in order of how much they matter.

**The unconditional mean wins on 13 of 13 symbols, against all three Kronos
readouts.** A 4.1M-parameter model pretrained on real markets, given the raw
candles rather than a feature matrix, sampling its own predictive distribution
64 times per row, does not beat a single number computed from the training
block. That is the correct answer for a constant-sigma process and it is worth
having measured rather than assumed.

**log-HAR collapses onto the mean.** 0.6691 against 0.6687 - the two agree to
four parts in ten thousand, symbol after symbol. A HAR regression given three
lagged volatility scales finds that the right coefficients are zero and the right
model is the intercept. `research/forecasting.md` records HAR's standing moving
with the instrument mix; on a constant-sigma synthetic it has nowhere to move to.

**Naive loses to the mean on 13 of 13, and that is the generator-identification
statistic.** On a real market volatility clusters and the last realised value
wins. Here the mean beats it by 0.218 on the feed and by 0.213 on a GBM
simulated in this harness - **the same gap, to within a fiftieth**. The
`seqlab.main()` figures for Volatility 75 1h were 0.6691 mean against 0.8802
naive on the feed and 0.6642 against 0.8809 on simulated GBM; this arm's rows
give 0.6706 against 0.8964 on the same symbol. Different rows, same conclusion.

### Is the gap just the sampler?

Kronos's volatility readout is a mean over 64 draws and carries Monte-Carlo
noise that a closed-form baseline does not, so "loses by 0.029" would be
worthless if the sampler alone cost 0.029. On a constant-sigma GBM the one-bar
target is half-normal, so this can be computed exactly rather than bootstrapped
(`kronoslib.mc_floor`, n = 400,000):

| forecast | srel |
| --- | ---: |
| perfect constant, computed in closed form | 0.6673 |
| the same constant, estimated from 16 draws | 0.6790 |
| the same constant, estimated from 32 draws | 0.6733 |
| **the same constant, estimated from 64 draws** | **0.6702** |
| the same constant, estimated from 128 draws | 0.6689 |
| last-realised value | 0.8814 |

**The sampling budget costs 0.0029.** Kronos's median gap to the unconditional
mean across the thirteen cells is **+0.0290**, an order of magnitude larger, so
the ranking is not an artefact of the sample count. The table is also a check on
the target: a perfect constant forecast of a half-normal scores 0.6673 and the
measured `mean` baseline on the feed scores 0.6687, which is what a genuine
geometric Brownian motion should give and another instance of
`research/grounding.md` tier 1 holding.

### The surrogate is a control, checked on a process that has something to destroy

`surrogate_bars` is only a control if volatility clustering does not survive it,
and the Volatility family has no clustering - so on these feeds a broken control
and a working one look identical. It is therefore checked against a GARCH(1,1)
path generated in `kronoslib.check_surrogate`, where clustering is present by
construction, 20,000 bars:

| | acf(r,1) | acf(\|r\|,1) | acf(\|r\|,5) | acf(\|r\|,22) | sd(r) | kurtosis |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GARCH(1,1) path | +0.0077 | **+0.2260** | +0.2134 | +0.1491 | 0.000699 | 5.13 |
| its phase surrogate | +0.0078 | **+0.0063** | −0.0039 | +0.0046 | 0.000699 | 3.04 |

The return autocorrelation and the standard deviation survive; the **return
amplitude spectrum survives to 6.4e-11 relative**; the autocorrelation of `|r|`
- which *is* volatility clustering - goes to zero at every lag, and the
kurtosis falls from 5.13 to Gaussian. The control does what the control claims.

### The shuffle control says the volatility forecast carries nothing at all

`seqlab.shuffle_target` permutes the target inside the test block, so a model
with no information scores the same on the permuted target as on the real one.
Median over the same thirteen Volatility cells at 1h:

| forecaster | srel on the real target | srel on the permuted target | gain from the real target | cells where the real target scored better |
| --- | ---: | ---: | ---: | ---: |
| Kronos, mean \|r\| over 64 draws | 0.6963 | 0.6959 | **−0.0037** | 3 / 13 |
| naive last-realised | 0.8870 | 0.8859 | **−0.0049** | 5 / 13 |

Both are *negative*: knowing the actual next bar helps neither forecaster more
than a permutation would, and both lose the coin flip on which cells improve.
**Kronos's volatility forecast and the last realised value carry the same amount
of information about the next bar's realised volatility on a Volatility index,
and that amount is zero.** The unconditional mean is not merely the best of the
three - it is the only one of the three that is doing anything, and what it is
doing is reporting a constant.

### One thing the model does notice, and it is not direction

The next-token entropy of the predictive distribution, median over cells:

| arm | entropy (nats, 1024-way s1 head) |
| --- | ---: |
| real feed | **3.712** |
| phase surrogate | 3.925 |
| simulated GBM at the named sigma | 3.930 |

The model is measurably **more confident on the broker's feed than on a
geometric Brownian motion simulated at the same sigma** - 0.22 nats, consistent
across cells. That is a real difference between the feed and its own null, and
the most likely cause is not predictability: the feed is quantised to a quote
lattice while `seqlab.gbm_bars` is continuous, and `research/quantising.md` is an
entire page about what that lattice does to estimators. The confidence buys
nothing - the same cells score AUC 0.4961. **A foundation model can tell these
two processes apart and still cannot predict either.**

## Six: what the context budget bought

Kronos-mini's published context is 2048 bars; this study runs at 128. The
sweep below is why, on two cells at 1h, `cap` 600 rows each:

| cell | ctx | scored rows | AUC | Kronos srel | unconditional mean srel | seconds per 1,000 rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Volatility 75 Index | 64 | 595 | 0.4751 | 0.6784 | 0.6407 | 17 |
| Volatility 75 Index | 128 | 595 | 0.5451 | 0.7335 | 0.7020 | 33 |
| Volatility 75 Index | 256 | 595 | 0.5099 | 0.7217 | 0.6680 | 62 |
| XAUUSD | 64 | 595 | 0.4979 | 0.7455 | 0.8016 | 13 |
| XAUUSD | 128 | 595 | 0.4839 | 0.7442 | 0.7535 | 21 |
| XAUUSD | 256 | 595 | 0.5121 | 0.7670 | 0.7903 | 41 |
| XAUUSD | 512 | 600 | 0.4589 | 0.7555 | 0.8151 | 96 |

**Read the cost column, not the score column.** At 600 rows the AUC standard
error is about 0.024, so every AUC here is inside two standard errors of 0.50 and
of each other, and the rows are not identical across context lengths - a longer
context pushes the usable-row warm-up later and moves the fold edges. What the
table does establish is that the wall clock is roughly quadratic in context
(17 / 33 / 62 seconds per thousand rows, then 96 at 512) while nothing in the
score moves beyond its own noise, on a process where nothing should.

**Four times the context for four times the money, on a martingale, is a bad
trade, and 128 bars is the budget this study spent.** That is a statement about
what was affordable on eight CPU threads and it should be read as a limit of the
run rather than as a finding about the model: a longer context is where a result
could still be hiding, and this page has not looked there.

## Seven: fine-tuning, and where it is not defensible

Fine-tuning is done **per fold, on that fold's train block alone**, from the
pretrained weights, pooled across a domain's symbols; a fresh model each time,
because carrying one across folds would train it on a later fold's test block
through the earlier fold's weights. The tokenizer is never trained. Beside every
fine-tuned model runs a **scratch** arm - the published architecture at the
published initialisation, the same rows, the same steps, the same schedule -
because `zero-shot -> fine-tuned` measures what fine-tuning adds and says nothing
about whether the pretrained weights were worth anything.

Train and validation loss are both evaluated **in eval mode on fixed window
sets with the sampler reseeded identically**. That is not fussiness:
`Kronos.forward` draws `s1` to condition the `s2` head when teacher forcing is
off, and `DependencyAwareLayer` masks causally in train mode and not in eval
mode, so a training-mode loss and an eval-mode loss are different numbers and
their difference is not an overfitting measure.

### At 1h there is nothing to overfit

Volatility family, 1h, fold 0: twenty symbols, **632,877 usable rows**, batch 16,
lr 4e-5 (upstream's `predictor_learning_rate`), OneCycle, 800 steps:

| step | fine-tuned train | fine-tuned val | gap | scratch train | scratch val | gap |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 3.5115 | 3.4797 | −0.0318 | 7.1449 | 7.1586 | +0.0136 |
| 100 | 3.1117 | 3.0991 | −0.0126 | 4.8489 | 4.8405 | −0.0084 |
| 200 | 3.0122 | 3.0028 | −0.0094 | 3.9211 | 3.9057 | −0.0154 |
| 300 | 2.9681 | 2.9609 | −0.0072 | 3.5247 | 3.5055 | −0.0192 |
| 400 | 2.9449 | 2.9391 | −0.0057 | | | |
| 500 | 2.9323 | 2.9268 | −0.0055 | | | |
| 600 | 2.9260 | 2.9212 | −0.0048 | | | |
| 700 | 2.9236 | 2.9189 | −0.0047 | | | |
| 799 | 2.9233 | 2.9187 | −0.0046 | | | |

**Validation tracks training to four decimal places for 800 steps.** The gap is
*negative* throughout - the held-out tail is marginally easier than the training
part, which is a property of the split and not of the model - and it closes by
0.027 over the whole run, 3.4e-5 per step. At 632,877 rows against 4.1M
parameters there is nothing here to overfit, and an early stop never fires.

Two things are worth reading off the loss levels themselves. The pretrained
model starts at **3.51 nats** where random initialisation starts at **7.15**
(2 x ln 1024 / 2 = 6.93 is the uniform floor for the two 1024-way heads), so
Kronos's pretraining on real equities and crypto is worth about **3.6 nats per
bar on a synthetic GBM it has never seen** before a single gradient step. And
800 steps of fine-tuning buys **0.59 nats** on top of that.

### At 1d it overfits, quickly, and the curve says so

A Volatility symbol holds under 2,900 bars at 1d. A 128-bar context slides one
bar at a time, so those are overlapping views of roughly twenty independent
context-lengths of history per symbol, against 4.1M parameters. From the 1d
fit (two symbols pooled, batch 8, 40 steps - a smaller budget than the 1h run,
so read the *slopes* and not the levels):

| fold | gap at step 0 | gap at step 20 | gap at step 39 | growth |
| ---: | ---: | ---: | ---: | ---: |
| 1 | +0.2528 | +0.2916 | +0.2991 | **+0.046** |
| 2 | +0.2621 | +0.3028 | +0.3107 | **+0.049** |
| 3 | +0.2623 | +0.2995 | +0.3045 | **+0.042** |

The *level* of the gap is distribution shift - the validation tail is a later,
different stretch of tape and is already 0.26 nats harder before any gradient
step. **The growth is the overfitting**, and it is 1.2e-3 per step against
3.4e-5 per step at 1h: thirty-five times faster, in the first forty steps, on a
budget a twentieth the size.

**Fine-tuning a 4.1M-parameter model at 1d on this book is not defensible and
this page does not claim a 1d fine-tuned number means anything.** It is run and
reported because the honest way to say so is to show the validation curve
turning up.

## Eight: the kill conditions, and which of them fired

Written into `research/harness/kronos.py` before any number was read.

| # | condition | fired? | evidence |
| ---: | --- | --- | --- |
| 1 | void if the cached decoder is not reproducing upstream | **no** | 3.73e-07 max absolute error against `tokenizer.decode` on a signal of scale 4.89; 7.63e-06 against `Kronos.decode_s2` |
| 2 | void if a future bar moves the model's logits | **no** | 0.0 exactly, 24 rows, poked row 49,980 |
| 3 | arm void if the simulated GBM does not land at 0.50 | **no** | gbm median AUC 0.5124 against a median bootstrap se of 0.0132 - 0.94 se; largest deviation anywhere in the gbm arm 1.43 se, family-wise p 0.864 |
| 4 | a direction result that survives on the surrogate is a leak | **did not arise** | nothing survived on the feed to test |
| 5 | a volatility result that beats the mean on a constant-sigma member is a units artefact | **did not arise** | Kronos loses to the mean on 13 of 13 |
| 6 | a cell with fewer than 400 scored rows is not pooled | **no cells excluded at 1h** | the smallest 1h cell carries 1,375 rows |

## Nine: the files

| file | what it is |
| --- | --- |
| `research/harness/kronosboot.py` | vendors upstream outside the git tree, pulls the weights, reproduces the published example, benchmarks the CPU cost. `kronos.py` is not readable without it having passed. |
| `research/harness/kronoslib.py` | the plumbing: the frozen pair, the causal window builder, the cached decoder that makes 64 samples cost what 1 costs, `verify`, `check_causality`, `check_surrogate`, `mc_floor`, the three baselines |
| `research/harness/kronos.py` | the zero-shot study - the grid, the arms, the controls, the family aggregates |
| `research/harness/kronosfine.py` | the fine-tuned and scratch arms, per fold, with the train/validation curves |
| `research/harness/kronosleak.py` | prices the look-ahead this study avoided, by running the same model with the normalisation deliberately contaminated |

Results land in `~/till_infinity/results/` as `kronos_zero.jsonl`,
`kronos_fine.jsonl`, `kronos_curves.jsonl`, `kronos_sweep.json`,
`kronos_leak.json` and `kronosboot.json`. Everything runs through
`./.secrets/lab.sh run`; nothing in this arm ever executed on the production
instance.

## Ten: what is not here, and why

**The research lab dropped off the network part way through the grid** - SSH
refused, host unreachable by ICMP, for over three hours. The jobs themselves did
not die: they were detached with `nohup`, and a window in which the connection
came back long enough to run `wc` showed **201 cells in `kronos_zero.jsonl` and
375 rows in `kronos_fine.jsonl`** - the grid and the fine-tuning arm had both
kept going without a client attached. The connection dropped again before any of
it could be copied off. What follows is therefore a statement about what has been
*retrieved*, not about what was *measured*; the rest is on the lab's disk and the
tables below can be filled in by copying two files.

| deliverable | measured on the lab | retrieved |
| --- | --- | --- |
| zero-shot grid, 1h + 4h + 1d | 201 of 225 cells | **38 cells** - 13 Volatility symbols at 1h, all three arms, which is every table above |
| zero-shot, `seqlab.REAL` | included in the 201 | **none** - the grid runs the Volatility family first |
| zero-shot, 3m / 15m / 6h / 8h / 12h | not started - the lowest priority of `seqlab.GRID` | - |
| fine-tuned and scratch **curves** | running | **one fold of Volatility 1h** - section seven |
| fine-tuned and scratch **scores** | 375 rows | **none** |
| `kronosleak`, the price of the look-ahead | not started | - |

**The real-market half of the transfer question is therefore open**, and it is
the half that could have gone either way. What exists is fragments from the
smoke runs and the context sweep, on samples of 150-600 rows where the AUC
standard error is 0.02-0.04, and they do not agree with each other: XAUUSD 1h at
`cap` 150 puts Kronos behind the unconditional mean (0.7635 against 0.7459) and
the four context-sweep cells at `cap` 600 put it ahead at every context length
(0.7442/0.7535, 0.7455/0.8016, 0.7670/0.7903, 0.7555/0.8151). **Four hundred
rows cannot separate those and this page does not pretend otherwise.** Re-running
`kronos.py TFS=1h` resumes exactly where it stopped and finishes the real cells
first, since the Volatility family is already on disk.

### What would change the answer, in the order worth trying

1. **The real-market cells**, which is the commissioned contrast and the only
   part of this page whose result was not predictable from `research/deriving.md`.
2. **Context 2048.** Kronos-mini's published context is sixteen times what this
   ran at. On a martingale that is a bad trade, but the volatility arm on real
   markets is where a long context could earn its keep, and the cost table says
   what it would cost.
3. **`Kronos-base` or `Kronos-large`.** 102M and 499M parameters against 4.1M.
   `kronosboot` already loads and reproduces `small`; the readout in `kronoslib`
   is size-agnostic. If a foundation model is going to find volatility structure
   on gold that a straight line misses, mini is the least likely variant to do it.
4. **Fine-tuning the tokenizer per fold.** Deliberately not done here, because a
   refitted quantiser is the most likely source of a false positive in this arm
   and freezing it makes the no-leak claim a property of the code. It is still
   the obvious next experiment, provided it is refit per fold on train rows and
   `check_causality` is re-run against it.
5. **Horizons beyond one bar.** `research/forecasting.md` records that "every
   volatility forecaster scored on the next single bar will crown naive"; this
   page scores only `horizon=1`, and naive lost anyway, which on a constant-sigma
   process is the expected direction but does not generalise to k > 1.

## Appendix: every Volatility cell at 1h, feed arm

`sigma` is the instrument's published annualised volatility, verified to within
0.49% on 12 of 12 by `research/grounding.md` tier 1, so the simulated null beside
each of these was built at the true parameter rather than a fitted one.

| symbol | sigma | n | AUC | se | AUC on a shuffled target | entropy | Kronos srel | mean | naive | log-HAR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Volatility 10 (1s) Index | 0.10 | 1,980 | 0.4912 | 0.0131 | 0.5022 | 3.81 | 0.7057 | 0.6830 | 0.8748 | 0.6830 |
| Volatility 10 Index | 0.10 | 1,980 | 0.5035 | 0.0128 | 0.4904 | 3.72 | 0.6885 | 0.6670 | 0.9174 | 0.6663 |
| Volatility 15 (1s) Index | 0.15 | 1,950 | 0.4899 | 0.0140 | 0.4854 | 3.71 | 0.7084 | 0.6817 | 0.8892 | 0.6817 |
| Volatility 15 Index | 0.15 | 1,375 | 0.5337 | 0.0157 | 0.4867 | 3.74 | 0.7389 | 0.7118 | 0.8870 | 0.7117 |
| Volatility 25 (1s) Index | 0.25 | 1,980 | 0.5055 | 0.0129 | 0.5073 | 3.65 | 0.6907 | 0.6501 | 0.8795 | 0.6502 |
| Volatility 25 Index | 0.25 | 1,980 | 0.5200 | 0.0128 | 0.4982 | 3.71 | 0.6921 | 0.6601 | 0.8781 | 0.6598 |
| Volatility 30 (1s) Index | 0.30 | 1,950 | 0.4845 | 0.0131 | 0.4853 | 3.69 | 0.6963 | 0.6620 | 0.8815 | 0.6628 |
| Volatility 30 Index | 0.30 | 1,375 | 0.4943 | 0.0165 | 0.4769 | 3.54 | 0.7175 | 0.6861 | 0.8774 | 0.6860 |
| Volatility 50 (1s) Index | 0.50 | 1,980 | 0.4961 | 0.0133 | 0.4827 | 3.64 | 0.6867 | 0.6656 | 0.8885 | 0.6655 |
| Volatility 50 Index | 0.50 | 1,980 | 0.4877 | 0.0122 | 0.5098 | 3.72 | 0.7150 | 0.6687 | 0.9035 | 0.6691 |
| Volatility 75 (1s) Index | 0.75 | 1,980 | 0.5102 | 0.0134 | 0.5088 | 3.73 | 0.6846 | 0.6556 | 0.8496 | 0.6560 |
| Volatility 75 Index | 0.75 | 1,980 | 0.5082 | 0.0129 | 0.5071 | 3.60 | 0.7015 | 0.6706 | 0.8964 | 0.6704 |
| Volatility 90 Index | 0.90 | 1,375 | 0.4863 | 0.0166 | 0.4839 | 3.43 | 0.6909 | 0.6733 | 0.9176 | 0.6718 |

Seven of the twenty Volatility members are missing from this table: the grid runs
in `seqlab.VOLATILITY` order and the lab went off the network part way through
`Volatility 90 (1s) Index`. `kronos.py` skips any cell already in the `jsonl`,
so re-running it continues from here rather than repeating any of it.

