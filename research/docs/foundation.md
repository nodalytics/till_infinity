# A foundation model beats a straight line on real volatility, and nothing at all on the synthetics

**Kronos-mini, zero-shot and fine-tuned, on `seqlab` folds. Run 2026-09-12/13.**

Kronos is a decoder-only foundation model for candlestick data - a tokenizer
that quantises OHLCV into discrete codes and a transformer that predicts the
next code. `Kronos-mini` is the 4.1M-parameter variant. This page puts it on
Deriv's twenty Volatility indices and on five real markets and scores it against
the baselines every other arm of the sequence study uses.

**The direction half was a null calibration with a strong prior, and it held.**
`research/deriving.md` proves `E[net] = -(c/2) x turnover` for any predictable
position on a martingale; a Volatility index is geometric Brownian motion at a
published constant sigma, so its increments are independent by construction;
`research/rebuilding.md` already found boosted models scoring nothing on these
feeds with `n*` infinite on every arm.

**The volatility half was the open question, and it separated cleanly.**

| | cells | scored rows | Kronos beats the unconditional mean | beats log-HAR | naive beats the mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| **real markets** | 15 | 28,463 | **13 / 15** | 9 / 15 | 3 / 15 |
| the same real markets, phase-randomised | 15 | 28,468 | **0 / 15** | 0 / 15 | 0 / 15 |
| the same real markets, simulated as GBM | 15 | 28,468 | 0 / 15 | 0 / 15 | 0 / 15 |
| **Volatility family** | 52 | 83,966 | **0 / 52** | 0 / 52 | 0 / 52 |
| Volatility, phase-randomised | 52 | 83,966 | 0 / 52 | 0 / 52 | 0 / 52 |
| Volatility, simulated as GBM | 52 | 83,966 | 0 / 52 | 0 / 52 | 0 / 52 |

Kronos-mini forecasts one-bar realised volatility better than a horizontal line
on thirteen of fifteen real-market cells and on **none** of the other 186 cells
in the grid - including the phase surrogates of those same real markets, which
keep the return spectrum exactly and destroy volatility clustering. The thing it
transferred is the thing the synthetics do not have.

And direction is 0.50 everywhere, on 67 feed cells and 112,429 scored rows, with
a family-wise p below 0.2 nowhere in the table.

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
direction hit rate of 0.44 and 0.53 over 120 bars is what a sampler does on a
near-martingale and is not evidence of anything either way.

### The budget, stated

Measured on the lab (`kronosboot.benchmark`, Kronos-mini, batch of 16, **8
threads** - five other agents share the box; the fine-tuning arm ran at 6 while
the two overlapped):

| context | ms per batch of 16 | windows/s |
| ---: | ---: | ---: |
| 64 | 44.2 | 362.1 |
| 128 | 82.1 | 194.8 |
| 256 | 189.3 | 84.5 |
| 512 | 544.8 | 29.4 |

The study runs at **ctx = 128 bars and 64 samples per scored row**, against
Kronos-mini's published context of 2048. That is a budget decision and section
six prices it.

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

Total spend, on a machine with no GPU: the zero-shot grid ran to completion in
**99.5 minutes** on 8 threads - 201 cells, 337,297 scored rows, three timeframes,
three arms - with the fine-tuning arm running concurrently on 6, finishing in
**113.5 minutes** for twenty fits and 375 scored (symbol, fold, arm) rows. The
24 cells absent from 25 x 3 x 3 are not failures: they are the eight Volatility
members that return under 600 bars at 1d, which `seqlab.load` refuses as `Thin`,
times three arms.

## Two: the tokenizer look-ahead, and how it was closed

This is the single most likely way this arm produces a false positive, and the
volatility result above is exactly the shape a look-ahead would take, so it gets
the most scrutiny on the page.

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
   fold, on that fold's train rows alone**, with the last training target capped
   at the fold's purge boundary, and the tokenizer is never trained at all.
   Freezing it turns "the quantiser never saw a test row" from a promise into a
   property of the code.

**And the model is put through the same instrument `seqlab.check_causality`
points at the feature matrix.** A future bar is multiplied by 1.05 (volume by
3.0) and the next-token logits at 24 earlier rows are recomputed:

    poked row 49,980 of Volatility 75 Index 1h, 24 rows checked,
    max logit movement = 0.0 exactly

Not "below tolerance" - identical to the bit. The logits are deterministic, so
this is an exact comparison and not a tolerance on a sampler.

**The strongest evidence is the surrogate arm itself.** A look-ahead in the
normalisation or the tokenizer would fire on *any* series, because it is a
property of the pipeline and not of the data. The phase surrogates of the five
real markets are the same length, the same price level, the same clock, the same
return spectrum and the same standard deviation as the real ones, and they go
through byte-for-byte the same code path. Kronos beats the unconditional mean on
13 of 15 real cells and **0 of 15 surrogate cells**. A leak cannot tell those
apart; volatility clustering can.

### And the mistake was priced, not just avoided

`research/harness/kronosleak.py` runs the same model on the same rows with the
normalisation deliberately contaminated, two ways. **`future`** takes the mean
and standard deviation over `[t-ctx+1 .. t+1]` instead of `[t-ctx+1 .. t]` - the
model still sees only bars up to `t`, but the constants that scale them carry
the bar being predicted. That is the classic off-by-one: it survives a code
review, and it survives a feature-level causality assertion that only inspects
features. **`global`** fits mean and standard deviation over the whole series
before the split, which is what "fit the scaler, then split" does.

Four cells at 1h, 1,485 scored rows each, bootstrap standard error ~0.0147:

| symbol | normalisation | AUC | srel vol | entropy |
| --- | --- | ---: | ---: | ---: |
| Volatility 75 Index | causal | 0.5193 | 0.7118 | 3.587 |
| Volatility 75 Index | future | 0.5249 | 0.7121 | 3.594 |
| Volatility 75 Index | global | 0.5028 | **0.9255** | **1.623** |
| Volatility 100 Index | causal | 0.5029 | 0.6902 | 3.763 |
| Volatility 100 Index | future | 0.5015 | 0.6874 | 3.771 |
| Volatility 100 Index | global | 0.4679 | **0.8725** | **2.452** |
| XAUUSD | causal | 0.4902 | 0.7229 | 3.444 |
| XAUUSD | future | 0.4960 | 0.7215 | 3.456 |
| XAUUSD | global | 0.5181 | 0.7518 | **2.563** |
| EURUSD | causal | 0.5198 | 0.7230 | 3.344 |
| EURUSD | future | 0.5184 | 0.7247 | 3.356 |
| EURUSD | global | 0.4906 | 0.7644 | **2.440** |

**The off-by-one buys nothing.** `future` moves the AUC by +0.0056, −0.0014,
+0.0058 and −0.0014 on the four cells, every one of them inside half a standard
error, and the volatility score by +0.0003, −0.0028, −0.0014 and +0.0017. On a
128-bar window one extra bar barely moves a mean or a standard deviation, and
the return readout is referenced to the model's own reconstruction, so the
contamination has almost nothing to act through.

**This is reported against interest.** The causal discipline in section two was
insurance and not a rescue: on *this* geometry the leak it guards against does
not manufacture an edge, and had the study been sloppy the headline would have
come out the same. The insurance is still worth carrying - the margin shrinks
with the context, and at ctx=8 rather than 128 one contaminated bar is an eighth
of the normalising statistic rather than a hundred-and-twenty-eighth - but this
page cannot claim its result survived a leak it turns out not to have been
exposed to.

**And `global` is not a leak that helps, it is an input that breaks.** Fitting
the scaler across the split costs 0.21 and 0.18 srel on the two synthetics and
collapses the predictive entropy from 3.59 to 1.62 nats: a z-score against a
five-year mean puts a 128-bar window far from zero and hard against the `clip`
of 5, and the model answers a question about a nearly flat line. The classic
mistake degrades this model rather than flattering it, which is worth knowing
because it means a global scaler would have been caught by a *worse* score and
not by a suspiciously good one.

## Three: what was scored, and against what

One bar ahead, `horizon=1`, on `seqlab.walk_forward` folds - expanding window,
one-bar purge, never shuffled - so the rows are the rows every other arm of this
study uses. Folds are cut over the rows usable to **both** the baselines and a
128-bar Kronos context, so the warm-up is 128 bars rather than the 22 the
feature matrix alone needs and the fold edges sit correspondingly later.

Scored test rows are capped at 2,000 per cell and decimated uniformly *inside*
each fold, and **the baselines are scored on exactly those rows**. A baseline
scored on more rows than the model is not a baseline.

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
HAR is given, and it is a scale and not a shape: it cannot create a correlation
that was not there.

Three controls sit beside every headline: **`shuffle`** (targets permuted inside
the test block), **`surrogate`** (phase-randomised returns - the spectrum and
the full linear autocorrelation survive, every nonlinear dependence including
volatility clustering does not), and **`gbm`** (simulated geometric Brownian
motion at the symbol's true `seqlab.NAMED_SIGMA`, or at its measured sigma for a
real market, wearing the real feed's own timestamps so the learned temporal
embeddings cannot separate them).

## Four: direction is the null, on every cell of the grid

**Kronos-mini finds nothing, and the controls say the nothing is the right
nothing.** Feed arm, one bar ahead:

| timeframe | family | cells | scored rows | AUC median | min | max | median \|AUC−0.5\| | median se | on a shuffled target |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1h | Volatility | 20 | 37,055 | 0.4980 | 0.4815 | 0.5337 | 0.0101 | 0.0132 | 0.5002 |
| 1h | Real | 5 | 9,900 | 0.5086 | 0.5008 | 0.5270 | 0.0086 | 0.0127 | 0.4981 |
| 4h | Volatility | 20 | 31,913 | 0.5052 | 0.4784 | 0.5259 | 0.0104 | 0.0139 | 0.4937 |
| 4h | Real | 5 | 9,685 | 0.4988 | 0.4875 | 0.5072 | 0.0033 | 0.0129 | 0.4981 |
| 1d | Volatility | 12 | 14,998 | 0.5046 | 0.4826 | 0.5206 | 0.0083 | 0.0176 | 0.5068 |
| 1d | Real | 5 | 8,878 | 0.5074 | 0.5000 | 0.5233 | 0.0074 | 0.0133 | 0.5028 |

The simulated-GBM arm, where the true answer is exactly 0.50 by construction,
returns 0.5085 / 0.5150 / 0.4957 / 0.5151 / 0.5002 / 0.5042 on the same six
cells. **The feed is not further from the null than a series generated in this
harness at a known sigma.** The phase surrogate returns 0.4920 / 0.4955 /
0.4922 / 0.4979 / 0.4855 / 0.5086.

*(Every `gbm` figure on this page comes from `seqlab.gbm_bars` as it stood before
a defect in its candle construction was fixed - section ten. For direction the
defect is harmless by construction, since a malformed high is informative about
the sign of its own bar and the target is the next one, and on a GBM those are
independent. The cells are being re-run regardless. Nothing in the feed or
surrogate arms is affected, and the headline is a feed-against-surrogate
comparison.)*

With sixty-seven cells the best of sixty-seven fair coins clears 0.53 routinely,
so every deviation is reported against the family it was drawn from. The largest
deviation on each feed arm, in its own standard errors:

| timeframe | family | cells | max \|z\| | at | AUC | n | per-test p | family-wise p | n\* |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1h | Volatility | 20 | 2.15 | Volatility 15 Index | 0.5337 | 1,375 | 0.032 | 0.476 | 4,586 |
| 1h | Real | 5 | 1.99 | BTCUSD | 0.5270 | 1,980 | 0.047 | 0.214 | 7,719 |
| 4h | Volatility | 20 | 1.99 | Volatility 25 Index | 0.5257 | 1,995 | 0.046 | 0.613 | 7,724 |
| 4h | Real | 5 | 0.97 | GBPUSD | 0.4875 | 1,915 | 0.333 | 0.868 | 31,340 |
| 1d | Volatility | 12 | 1.06 | Volatility 75 Index | 0.5185 | 1,120 | 0.288 | 0.983 | 15,225 |
| 1d | Real | 5 | 1.64 | GBPUSD | 0.5233 | 1,665 | 0.101 | 0.412 | 9,503 |

**Nothing in the direction arm clears a family-wise p of 0.2.** And the single
most significant cell in the entire study is on a control: **Volatility 75 Index
at 1d on the phase surrogate**, AUC 0.4484 at 3.20 standard errors, family-wise
p = 0.016 - a series built to contain nothing but a spectrum. That is what
sampling noise looks like across 201 cells, and it is the reason the `n*` column
is there: 4,586 rows would be needed to separate the best real cell from 0.50 at
its own standard error, against the 1,375 it carries.

## Five: volatility, where the transfer shows up

This is the half that had an open answer.

`seqlab.srel`, median over the symbols in each family, lower is better:

| timeframe | family | arm | Kronos \|r\| | Kronos sd | Kronos range | unconditional mean | naive | log-HAR | Kronos < mean |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1h | Volatility | feed | 0.6943 | 0.6911 | 0.6820 | **0.6661** | 0.8818 | 0.6665 | **0/20** |
| 1h | Volatility | surrogate | 0.7111 | 0.7045 | 0.7037 | 0.6765 | 0.8849 | 0.6765 | 0/20 |
| 1h | Volatility | gbm | 0.6883 | 0.6874 | 0.6774 | 0.6622 | 0.8749 | 0.6623 | 0/20 |
| 1h | **Real** | **feed** | **0.7553** | 0.7535 | 0.7376 | 0.8021 | 0.9109 | 0.7503 | **5/5** |
| 1h | Real | surrogate | 0.6989 | 0.6925 | 0.7069 | 0.6683 | 0.8902 | 0.6680 | **0/5** |
| 1h | Real | gbm | 0.6871 | 0.6859 | 0.6712 | 0.6622 | 0.8749 | 0.6623 | 0/5 |
| 4h | Volatility | feed | 0.6944 | 0.6927 | 0.6795 | **0.6645** | 0.8787 | 0.6647 | **0/20** |
| 4h | **Real** | **feed** | **0.7808** | 0.7821 | 0.7764 | 0.9561 | 0.9606 | 0.8159 | **5/5** |
| 4h | Real | surrogate | 0.7075 | 0.6992 | 0.7111 | 0.6670 | 0.8997 | 0.6668 | **0/5** |
| 4h | Real | gbm | 0.6899 | 0.6874 | 0.6784 | 0.6633 | 0.8802 | 0.6632 | 0/5 |
| 1d | Volatility | feed | 0.7155 | 0.7147 | 0.6938 | **0.6782** | 0.8884 | 0.6785 | **0/12** |
| 1d | **Real** | **feed** | 0.8079 | 0.7969 | 0.8005 | 0.8041 | 0.9797 | 0.8124 | 3/5 |
| 1d | Real | surrogate | 0.7088 | 0.6965 | 0.7150 | 0.6651 | 0.8912 | 0.6661 | **0/5** |
| 1d | Real | gbm | 0.6997 | 0.6945 | 0.6817 | 0.6686 | 0.8869 | 0.6694 | 0/5 |

The `gbm` rows carry the caveat above; the `feed` and `surrogate` rows, which are
what the conclusions rest on, do not. A malformed candle can only *cost* Kronos
accuracy on the `gbm` arm, and its score there is already the losing one, so the
defect cannot be what put those zeros in the last column.

Four things, in order of how much they matter.

**One. On the Volatility family the unconditional mean wins 52 of 52 cells,
against all three Kronos readouts.** A 4.1M-parameter model pretrained on real
markets, handed the raw candles rather than a feature matrix, sampling its own
predictive distribution 64 times per row, does not beat a single number computed
from the training block. That is the correct answer for a constant-sigma process
and it is worth having measured rather than assumed.

**Two. On real markets it wins 13 of 15, and the phase surrogate takes it
away.** The surrogate is built from the same feed: same length, same level, same
clock, same return spectrum and standard deviation to machine precision, with
volatility clustering removed and nothing else changed. Kronos's margin over the
mean goes from 13/15 to **0/15** on it. Whatever transferred is a nonlinear
property of the return sequence, which is the definition of volatility
clustering, and it is exactly what a model pretrained on real markets should
have and a constant-sigma GBM should lack.

**Three. It beats log-HAR on 9 of 15 real cells and loses on 6 - and at 1h it
loses on three of five.** Per symbol at 1h: EURUSD 0.7376 against HAR's 0.7616
and GBPUSD 0.7553 against 0.7891 are wins, but BTCUSD 0.7560 against 0.7500,
USDJPY 0.7437 against 0.7318 and XAUUSD 0.7576 against 0.7503 are losses. **At
one hour, on three of five real markets, a foundation model loses to a
three-term linear regression**, and that is reported as the finding it is. At 4h
it wins all five, and at 1d it splits.

*(One HAR cell is broken rather than merely beaten: USDJPY at 1d returns srel
1.6225, which on a metric bounded by 2 means the log fit plus smearing blew up
on a fold. It is left in the table rather than dropped, and it is the reason the
family statistic is a median.)*

**Four. log-HAR collapses onto the mean on every synthetic.** 0.6665 against
0.6661 at 1h, 0.6647 against 0.6645 at 4h, 0.6785 against 0.6782 at 1d - the two
agree to four parts in ten thousand, symbol after symbol, with a maximum gap of
0.0015 across the twenty 1h cells. A HAR regression given three lagged
volatility scales finds that the right coefficients are zero and the right model
is the intercept. On the real feed it separates from the mean immediately
(0.7503 against 0.8021 at 1h). **HAR's gap to the unconditional mean is itself a
generator-identification statistic**, and it is a sharper one than the
naive-versus-mean gap the brief started from.

### Naive against the mean, the statistic this study was asked to extend

`seqlab.main()` found on Volatility 75 1h that the mean (0.6691) beats naive
last-realised (0.8802) and that a simulated GBM behaves identically (0.6642 /
0.8809). Across the whole grid:

| family | arm | cells | naive beats the mean |
| --- | --- | ---: | ---: |
| Volatility | feed | 52 | **0** |
| Volatility | surrogate / gbm | 104 | 0 |
| Real | feed | 15 | **3** |
| Real | surrogate / gbm | 30 | 0 |

Naive never beats the mean on a constant-sigma synthetic, in 156 chances, and
beats it three times in fifteen on real markets. The statistic works, but it is
**weaker than Kronos's**: 3/15 against 13/15 on the same cells. A foundation
model is a more sensitive detector of volatility clustering than the last
realised value is - which is a use for it, and not the use it is sold for.

### Is the gap just the sampler?

Kronos's volatility readout is a mean over 64 draws and carries Monte-Carlo
noise that a closed-form baseline does not, so "loses by 0.028" would be
worthless if the sampler alone cost 0.028. On a constant-sigma GBM the one-bar
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
mean on the Volatility family is +0.028 at 1h, an order of magnitude larger, so
the synthetic result is not an artefact of the sample count - and the real-market
margin (−0.047 at 1h, −0.175 at 4h) is larger still in the other direction. The
table is also a check on the target: a perfect constant forecast of a
half-normal scores 0.6673 and the measured `mean` baseline on the Volatility
feed scores 0.6661, which is what a genuine geometric Brownian motion should
give and another instance of `research/grounding.md` tier 1 holding.

### The surrogate is a control, checked on a process that has something to destroy

The whole real-market claim rests on the surrogate removing volatility
clustering and nothing else, and the Volatility family has no clustering - so on
those feeds a broken control and a working one look identical. It is therefore
checked against a GARCH(1,1) path generated in `kronoslib.check_surrogate`,
where clustering is present by construction, 20,000 bars:

| | acf(r,1) | acf(\|r\|,1) | acf(\|r\|,5) | acf(\|r\|,22) | sd(r) | kurtosis |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GARCH(1,1) path | +0.0077 | **+0.2260** | +0.2134 | +0.1491 | 0.000699 | 5.13 |
| its phase surrogate | +0.0078 | **+0.0063** | −0.0039 | +0.0046 | 0.000699 | 3.04 |

The return autocorrelation and the standard deviation survive; the **return
amplitude spectrum survives to 6.4e-11 relative**; the autocorrelation of `|r|`
- which *is* volatility clustering - goes to zero at every lag, and the
kurtosis falls from 5.13 to Gaussian. The control does what the control claims.

**This arm uses its own surrogate construction, not `seqlab`'s.**
`kronoslib.surrogate_bars` predates `seqlab.surrogate_bars`, which was added to
the shared floor later, and the two rebuild the candle differently: this one
draws dimensionless wick geometry i.i.d. from the real bars' own pool, the
shared one splits each surrogate return into a 24-step Brownian bridge. Both
preserve the return spectrum exactly and destroy the `|r|` autocorrelation, and
both produce well-formed bars, but they are not the same object and a comparison
of surrogate scores *across* arms of this study should not assume they are.

### The shuffle control, on the synthetics

`seqlab.shuffle_target` permutes the target inside the test block, so a model
with no information scores the same on the permuted target as on the real one.
Median over the thirteen Volatility cells at 1h measured before the grid
completed:

| forecaster | srel on the real target | on the permuted target | gain from the real target | cells improved |
| --- | ---: | ---: | ---: | ---: |
| Kronos, mean \|r\| over 64 draws | 0.6963 | 0.6959 | **−0.0037** | 3 / 13 |
| naive last-realised | 0.8870 | 0.8859 | **−0.0049** | 5 / 13 |

Both are *negative*: on a Volatility index, knowing the actual next bar helps
neither forecaster more than a permutation would. The unconditional mean is not
merely the best of the three there - it is the only one of the three doing
anything, and what it is doing is reporting a constant.

### One thing the model notices everywhere, and it is not predictability

The next-token entropy of the predictive distribution, median over cells, feed
against the simulated GBM built at that symbol's own sigma:

| timeframe | family | feed | gbm | gap |
| --- | --- | ---: | ---: | ---: |
| 1h | Volatility | 3.700 | 3.925 | +0.224 |
| 1h | Real | 3.450 | 3.943 | +0.493 |
| 4h | Volatility | 3.537 | 3.894 | +0.357 |
| 4h | Real | 3.717 | 3.943 | +0.226 |
| 1d | Volatility | 3.385 | 3.891 | +0.506 |
| 1d | Real | 3.716 | 3.887 | +0.171 |

**This table is suspended pending a re-run and should not be cited.** The `gbm`
column was generated by `seqlab.gbm_bars` before a defect in it was fixed: 11.45%
of its simulated bars carried a high below `max(open, close)`, which is
impossible on a traded bar and out-of-distribution for a model pretrained on
traded markets. The entropy gap above may therefore be measuring malformed
candles rather than the quote lattice, and section ten sets out exactly why this
is the only claim on the page the defect can reach. The reading it *would*
support - that the model can tell a traded feed from its own null while
predicting the direction of neither - is interesting enough to be worth
re-measuring properly rather than defending now.

## Six: what the context budget bought

Kronos-mini's published context is 2048 bars; this study runs at 128. The sweep
below is why, on two cells at 1h, `cap` 600 rows each:

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
error is about 0.024, so every AUC here is inside two standard errors of 0.50
and of each other, and the rows are not identical across context lengths - a
longer context pushes the usable-row warm-up later and moves the fold edges.
What the table does establish is that the wall clock is roughly quadratic in
context (17 / 33 / 62 seconds per thousand rows, then 96 at 512) while nothing
in the score moves beyond its own noise. Worth noting on its own account:
Kronos beats the mean on XAUUSD at **all four** context lengths, on four
independent samples.

**Four times the context for four times the money is a bad trade on a
martingale, and 128 bars is the budget this study spent.** It is a limit of the
run rather than a finding about the model: the real-market volatility margin is
the one place a longer context could still pay, and this page has not looked
there.

## Seven: fine-tuning, and the transfer gap it measures

Fine-tuning is done **per fold, on that fold's train block alone**, from the
pretrained weights, pooled across a domain's symbols; a fresh model each time,
because carrying one across folds would train it on a later fold's test block
through the earlier fold's weights. The tokenizer is never trained. Beside every
fine-tuned model runs a **scratch** arm - the published architecture at the
published initialisation, the same rows, the same 800 steps, the same OneCycle
schedule at upstream's `predictor_learning_rate` of 4e-5 - because
`zero-shot -> fine-tuned` measures what fine-tuning adds and says nothing about
whether the pretrained weights were worth anything.

All three arms are scored on **identical rows**, 1h, five folds, 125 paired
(symbol, fold) cells:

| domain | arm | cells | rows | AUC median | srel median | mean | naive | log-HAR | beats the mean |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| real | zero-shot | 25 | 5,950 | 0.4976 | 0.7315 | 0.8045 | 0.9059 | 0.7596 | 25/25 |
| real | **fine-tuned** | 25 | 5,950 | 0.5143 | **0.7234** | 0.8045 | 0.9059 | 0.7596 | 25/25 |
| real | scratch | 25 | 5,950 | 0.5200 | 0.7870 | 0.8045 | 0.9059 | 0.7596 | 12/25 |
| volatility | zero-shot | 100 | 22,900 | 0.5057 | 0.6966 | 0.6670 | 0.8839 | 0.6671 | 3/100 |
| volatility | **fine-tuned** | 100 | 22,900 | 0.5000 | **0.6957** | 0.6670 | 0.8839 | 0.6671 | 4/100 |
| volatility | scratch | 100 | 22,900 | 0.5027 | 0.7560 | 0.6670 | 0.8839 | 0.6671 | 0/100 |

Paired per (symbol, fold), which is the comparison that matters because the same
rows carry all three arms:

| domain | pairs | Δ AUC, fine − zero | Δ srel, fine − zero | Δ srel, fine − scratch | folds where fine-tuning improved srel |
| --- | ---: | ---: | ---: | ---: | ---: |
| real | 25 | +0.0154 | **−0.0105** | −0.0692 | **22 / 25** |
| volatility | 100 | −0.0048 | **+0.0030** | −0.0577 | **40 / 100** |

**Fine-tuning helps on real markets and does nothing on synthetics.** On gold,
FX and BTC it improves the volatility forecast on 22 of 25 folds for a median
gain of 0.0105; on the Volatility family it improves 40 of 100 - a coin flip -
for a median *loss* of 0.0030.

That is the opposite of the naive reading of the transfer question, and the more
interesting answer. The naive reading was that a synthetic lacks the structure
Kronos was pretrained on, so fine-tuning should have *more* to teach it there.
What actually happens is that **fine-tuning can only buy structure that exists**:
on a constant-sigma GBM there is nothing to adapt toward, so 800 steps of
gradient descent on half a million windows move the test score by less than the
Monte-Carlo noise floor. The gap between the two domains - 0.0135 in srel, and
22/25 against 40/100 - **is** the measure of how much of Kronos's pretraining is
market structure the synthetics lack.

**Pretraining is worth a great deal, in both domains.** Fine-tuned beats scratch
by 0.069 on real markets and 0.058 on synthetics, on identical rows and an
identical compute budget, and scratch beats the unconditional mean on 0 of 100
synthetic folds against zero-shot's 3. In nats per bar:

| | first train loss | last train loss (800 steps) |
| --- | ---: | ---: |
| pretrained, Volatility | 3.51 | 2.89 |
| random initialisation, Volatility | 7.15 | 3.19 |
| pretrained, real | 3.03 | 2.68 |
| random initialisation, real | 7.15 | 3.24 |

The uniform floor for two 1024-way heads is ln 1024 = 6.93. **Kronos's
pretraining on real equities and crypto is worth 3.6 nats per bar on a synthetic
GBM it has never seen and 4.1 on a real market, before a single gradient
step**, and 800 steps of
fine-tuning buys 0.6 more. Compute-matched random initialisation closes most but
not all of the gap - it ends 0.30 nats behind on synthetics and 0.56 nats behind
on real markets - and the scratch arm is still improving when the budget runs
out, so that is a lower bound on what scratch could reach, not a converged
comparison.

### The curves, and where fine-tuning is not defensible

Train and validation loss are both evaluated **in eval mode on fixed window sets
with the sampler reseeded identically**. That is not fussiness: `Kronos.forward`
draws `s1` to condition the `s2` head when teacher forcing is off, and
`DependencyAwareLayer` masks causally in train mode and not in eval mode, so a
training-mode loss and an eval-mode loss are different numbers and their
difference is not an overfitting measure.

At 1h there is nothing to overfit. Validation follows training through all five
folds, and the final train-to-validation gap is small and **signed both ways**:

| fold | train windows | fine-tuned final gap | scratch final gap |
| ---: | ---: | ---: | ---: |
| 0 | 92,577 | −0.0046 | −0.0198 |
| 1 | 187,509 | +0.0183 | +0.0127 |
| 2 | 282,444 | −0.0569 | −0.0441 |
| 3 | 377,373 | +0.0130 | +0.0372 |
| 4 | 472,298 | +0.1270 | +0.1604 |

Fold 4's gap is the largest and it is **larger for the scratch model than for
the fine-tuned one**, which is the signature of a distribution shift between the
training block and its held-out tail rather than of a model memorising: a model
with 4.1M parameters and 472,298 training windows is not the thing that changed
between folds 0 and 4.

**At 1d it is a different story and the honest answer is that it should not be
done.** A Volatility symbol holds under 2,900 bars at 1d; a 128-bar context
slides one bar at a time, so those are overlapping views of roughly twenty
independent context-lengths of history per symbol. From the 1d fits (two symbols
pooled, batch 8, 40 steps - a far smaller budget than the 1h run, so read the
*slopes* and not the levels):

| fold | gap at step 0 | at step 20 | at step 39 | growth |
| ---: | ---: | ---: | ---: | ---: |
| 1 | +0.2528 | +0.2916 | +0.2991 | **+0.046** |
| 2 | +0.2621 | +0.3028 | +0.3107 | **+0.049** |
| 3 | +0.2623 | +0.2995 | +0.3045 | **+0.042** |

The *level* of the gap is distribution shift - the validation tail is already
0.26 nats harder before any gradient step. **The growth is the overfitting**,
and it is 1.2e-3 per step against 3.4e-5 per step at 1h: thirty-five times
faster, in the first forty steps, on a budget a twentieth the size.
**Fine-tuning a 4.1M-parameter model at 1d on this book is not defensible and no
1d fine-tuned number is claimed on this page.**

## Eight: where the sample makes a cell meaningless

`seqlab.GRID` runs from 3m to 1d and the sample falls off a cliff across it. At
1d, **eight of the twenty Volatility members do not appear at all**: Volatility
5, 5 (1s), 15, 15 (1s), 30, 30 (1s), 90 and 90 (1s) return 211 to 589 bars,
below `seqlab.FEWEST`, and `seqlab.load` raises `Thin` rather than scoring them.
The twelve that survive carry a median bootstrap standard error of 0.0176
against 0.0132 at 1h - a third wider - and that is why the 1d family-wise p
values are the loosest in the table (0.983 on the Volatility feed).

No cell in the grid fell below the 400-row floor that would have excluded it
from a pooled statistic; the smallest of the 201 is 889 rows (Volatility 15
Index at 4h), and the grid carries 337,297 scored rows in total. The timeframes
not run at all are 3m, 15m, 6h, 8h and 12h, the lowest priority of `seqlab.GRID`.

## Nine: the kill conditions, and which of them fired

Written into `research/harness/kronos.py` before any number was read.

| # | condition | fired? | evidence |
| ---: | --- | --- | --- |
| 1 | void if the cached decoder is not reproducing upstream | **no** | 3.73e-07 max absolute error against `tokenizer.decode` on a signal of scale 4.89; 7.63e-06 against `Kronos.decode_s2` |
| 2 | void if a future bar moves the model's logits | **no** | 0.0 exactly, 24 rows, poked row 49,980 |
| 3 | arm void if the simulated GBM does not land at 0.50 | **no** | gbm medians 0.4957 to 0.5151 across six family-timeframe cells, against median standard errors of 0.013 to 0.018 |
| 4 | a direction result that survives on the surrogate is a leak | **did not arise** | nothing survived on any feed to test |
| 5 | a volatility result that beats the mean on a constant-sigma member is a units artefact | **no - and this was the one that mattered** | 0 of 52 Volatility feed cells beat the mean, so the readout's single fitted scale is not manufacturing a win where none exists; the 13 of 15 on real markets therefore cannot be dismissed as the same artefact |
| 6 | a cell with fewer than 400 scored rows is not pooled | **no cells excluded** | smallest of the 201 cells is 889 rows (Volatility 15 Index at 4h) |

## Ten: what is not here, and why

The research lab stopped answering SSH from this machine for roughly six hours
mid-run. **One egress address is filtered at the edge and the cause is
unidentified** - the box stayed healthy throughout, answering on port 22 from
the Mumbai instance the whole time, so `lab.sh` now tries direct and falls back
to a jump through it. No cause is named here because none has been established;
an earlier attribution to `fail2ban` was withdrawn when the address turned out
to appear nowhere in its log and the refusal survived a reboot.

The jobs themselves did not die: they were detached with `nohup` and kept
running without a client attached, which is why the grid and the fine-tuning arm
are complete above. What the outage did cost:

| deliverable | state |
| --- | --- |
| `kronosleak`, the price of the look-ahead | **run after the box came back** - section two carries it |
| zero-shot at 3m / 15m / 6h / 8h / 12h | not started - the lowest priority of `seqlab.GRID` |
| fine-tuning at 4h | not run; 1h is the transfer number and 1d is reported only as the overfitting demonstration |
| `Kronos-base` / `Kronos-large` | not run |

### A defect in the shared simulator, and which of these numbers it touched

`seqlab.gbm_bars` took each simulated bar's high as the maximum of its 24
intra-bar sub-points, and its open as the *previous* bar's close - which is not
one of them. Re-measured here on 200,000 simulated bars rather than taken on
report: **11.45% of them had a high below `max(open, close)`** and 11.50% a low
above `min(open, close)`, which is impossible on a traded bar, and `seqlab.build`
turns those into an `upper` down to −1.19, a `lower` down to −1.14 and a `body`
up to 2.07, against a feed whose three are confined to [0, 1] by construction.

It was found by `seqnets.py` and fixed in `seqlab` at 04:26 on 2026-09-13; this
study's grid ran between 15:40 and 17:20 on 2026-09-12, so **the `gbm` arm of
the original grid ran on the defective version** and Kronos was fed roughly one
impossible candle in nine on it. Those 67 cells were archived as
`kronos_zero_gbmdefect.jsonl` and re-run on the corrected simulator.

Stated before the re-run rather than after, this is what it can and cannot have
touched:

* **The `feed` arm is untouched.** Those are the broker's own bars.
* **The `surrogate` arm is untouched.** It is built by `kronoslib.surrogate_bars`,
  which is this arm's own construction and clamps `high` to at least
  `max(open, close)` and `low` to at most `min(open, close)`;
  `kronoslib.check_surrogate` asserts `bars_well_formed` and it passes.
* **The baselines on the `gbm` arm are untouched.** `mean`, `naive` and `HAR` are
  all built from `rv1/rv5/rv22`, which are close-to-close only and never read a
  high or a low.
* **The headline does not rest on the `gbm` arm.** "Kronos beats the
  unconditional mean on 13 of 15 real cells and 0 of 15 of their phase
  surrogates" is a `feed`-against-`surrogate` comparison, and both are
  well-formed.
* **What could be affected is the entropy comparison.** An impossible candle is
  out-of-distribution for a model pretrained on traded markets, so "the model is
  more confident on a traded feed than on a simulated GBM" could be reading
  malformed candles rather than the quote lattice. That claim is the one thing
  on this page the defect can reach. **The 67 `gbm` cells are being re-run on the
  corrected simulator and the entropy claim is suspended until they land**; the
  defective cells are archived as `kronos_zero_gbmdefect.jsonl` so the two can be
  differenced rather than merely replaced.
* **The direction null on the `gbm` arm is safe by construction.** A high below
  the open is informative about the sign of *that* bar's return, and the target
  is the *next* bar's; on a GBM those are independent, so the defect cannot
  manufacture a predictive AUC.

### What would change the answer, in the order worth trying

1. **Run `kronosleak`.** It is the one check on this page argued rather than
   measured, and the volatility result is exactly the shape a normalisation
   look-ahead would take. The surrogate arm is strong evidence against a leak -
   a leak cannot distinguish a feed from its own phase surrogate - but a direct
   price is better than a strong argument.
2. **`Kronos-base` or `Kronos-large`**, 102M and 499M parameters against 4.1M.
   `kronosboot` already loads and reproduces `small`; the readout in `kronoslib`
   is size-agnostic. The real-market volatility margin is the live result, and
   mini is the least likely variant to maximise it - and at 1h it still loses to
   a three-term linear regression on three of five markets, which a larger
   variant might not.
3. **Context 2048.** Sixteen times what this ran at. On a martingale that is a
   bad trade, but the four-of-four XAUUSD wins across the context sweep say the
   real-market volatility arm is where a long context could earn its keep.
4. **Fine-tuning the tokenizer per fold.** Deliberately not done, because a
   refitted quantiser is the most likely source of a false positive here and
   freezing it makes the no-leak claim a property of the code. It is still the
   obvious next experiment, provided it is refit per fold on train rows and
   `check_causality` is re-run against it.
5. **Horizons beyond one bar.** `research/forecasting.md` records that "every
   volatility forecaster scored on the next single bar will crown naive"; this
   page scores only `horizon=1`, and naive lost anyway - which on a
   constant-sigma process is the expected direction but does not generalise to
   k > 1, and the real-market cells are where it might not.

## Eleven: the files

| file | what it is |
| --- | --- |
| `research/harness/kronosboot.py` | vendors upstream outside the git tree, pulls the weights, reproduces the published example, benchmarks the CPU cost. `kronos.py` is not readable without it having passed. |
| `research/harness/kronoslib.py` | the plumbing: the frozen pair, the causal window builder, the cached decoder that makes 64 samples cost what 1 costs, `verify`, `check_causality`, `check_surrogate`, `mc_floor`, the three baselines |
| `research/harness/kronos.py` | the zero-shot study - the grid, the arms, the controls, the family aggregates |
| `research/harness/kronosfine.py` | the fine-tuned and scratch arms, per fold, with the train/validation curves |
| `research/harness/kronosleak.py` | prices the look-ahead this study avoided, by running the same model with the normalisation deliberately contaminated. **Not yet run.** |

Results land in `~/till_infinity/results/` as `kronos_zero.jsonl` (201 cells),
`kronos_fine.jsonl` (375 rows), `kronos_curves.jsonl` (20 fits),
`kronos_sweep.json` and `kronosboot.json`. Everything runs through
`./.secrets/lab.sh run`; nothing in this arm ever executed on the production
instance.

## Appendix: the fifteen real-market feed cells

| timeframe | symbol | n | AUC | se | entropy | Kronos | mean | naive | log-HAR | beats mean | beats HAR |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1h | BTCUSD | 1,980 | 0.5270 | 0.0136 | 3.36 | 0.7560 | 0.8926 | 0.8914 | 0.7500 | yes | no |
| 1h | EURUSD | 1,980 | 0.5008 | 0.0127 | 3.36 | 0.7376 | 0.8021 | 0.9109 | 0.7616 | yes | yes |
| 1h | GBPUSD | 1,980 | 0.5086 | 0.0121 | 3.45 | 0.7553 | 0.8361 | 0.9189 | 0.7891 | yes | yes |
| 1h | USDJPY | 1,980 | 0.5011 | 0.0126 | 3.47 | 0.7437 | 0.7709 | 0.9015 | 0.7318 | yes | no |
| 1h | XAUUSD | 1,980 | 0.5100 | 0.0129 | 3.46 | 0.7576 | 0.7759 | 0.9202 | 0.7503 | yes | no |
| 4h | BTCUSD | 1,935 | 0.4967 | 0.0143 | 3.50 | 0.7931 | 0.9993 | 0.9529 | 0.8230 | yes | yes |
| 4h | EURUSD | 1,980 | 0.5013 | 0.0130 | 3.72 | 0.7777 | 0.9561 | 0.9730 | 0.8019 | yes | yes |
| 4h | GBPUSD | 1,915 | 0.4875 | 0.0129 | 3.70 | 0.7863 | 0.8542 | 0.9347 | 0.8207 | yes | yes |
| 4h | USDJPY | 1,980 | 0.4988 | 0.0126 | 3.72 | 0.7779 | 0.9738 | 0.9606 | 0.8125 | yes | yes |
| 4h | XAUUSD | 1,875 | 0.5072 | 0.0129 | 3.72 | 0.7808 | 0.8434 | 0.9680 | 0.8159 | yes | yes |
| 1d | BTCUSD | 1,515 | 0.5215 | 0.0135 | 3.42 | 0.8113 | 0.9071 | 0.9697 | 0.8208 | yes | yes |
| 1d | EURUSD | 1,868 | 0.5020 | 0.0126 | 3.72 | 0.8079 | 0.8031 | 0.9797 | 0.7977 | no | no |
| 1d | GBPUSD | 1,665 | 0.5233 | 0.0142 | 3.79 | 0.8007 | 0.8041 | 1.0092 | 0.7931 | yes | no |
| 1d | USDJPY | 1,865 | 0.5000 | 0.0132 | 3.63 | 0.8043 | 0.7860 | 0.9466 | 1.6225 | no | yes |
| 1d | XAUUSD | 1,965 | 0.5074 | 0.0133 | 3.82 | 0.8136 | 0.8429 | 0.9910 | 0.8124 | yes | no |

Every AUC in the column is inside two standard errors of 0.50. The volatility
columns are where the model is doing something, and the `mean` column is the
number it has to beat - which on these fifteen cells, unlike the other 186 in
the grid, it usually does.
