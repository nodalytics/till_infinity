# Sequence models on the Volatility family: a null that calibrates and a question that closes

The recurrent arm of the sequence study. Three architectures - LSTM, GRU and a
vanilla tanh RNN - on `seqlab`'s 28 causal features, across the Volatility
family and 8 timeframes, against two targets: **direction**, which is a
calibration, and **`logvol`**, which is the question. Twenty-two symbols were
commissioned; **twenty-one can be pulled**, and the one that cannot is the
mirror of the one symbol on the page that produced a positive result.

> **Complete, 2026-09-13**, with one confirmation running. Every stage has run:
> the harness checks, the 384-cell architecture sweep, the **2,464-cell grid**
> and the **480-cell positive control on real markets**. The `gbm` control cells
> in the grid and the positive control were scored against the null as it stood
> *before* the `gbm_bars` correction below; a corrected re-run is in flight and
> is a confirmation rather than a fix, for the reason given in
> [the defect section](#a-defect-in-the-null-itself-found-while-validating-the-new-control).
> That re-run also caught a **regression in the shared floor that silently
> deleted every control in the study** - `gbm` and `surrogate` were returning
> zero usable rows on every symbol - which is fixed and has
> [its own section](#the-regression-that-deleted-every-control-in-the-study).
> The numbers reported here predate it and have their controls intact.
>
> The session lost about six hours to the lab refusing SSH. The diagnosis is not
> the one this page first recorded: the machine was healthy throughout and
> serving the live desk - **one egress address was banned, almost certainly by
> fail2ban, after seven agents hammered it for hours.** `lab.sh` now falls back
> to a jump route, which is how the corrected run was launched.

**The findings.**

* **Direction calibrates.** Over 462 real cells and **7,728,858 test rows** the
  mean AUC is **0.50150**. The phase-surrogate control - a series built to have
  no nonlinear structure at all - scores **higher**, at 0.50183. The best cell in
  the family, 0.5801, is on **361 test rows** and lands on the **95th percentile**
  of the best-of-462 null; family-wise **p = 0.0511**, and the best control cell
  in the same sample band is 0.5572. Banded by test-set size, the controls win
  three bands of five. `research/deriving.md` predicted this and it is what came
  back.
* **Magnitude closes against the net.** The net scores **R^2 -0.3139** on the
  feed, **worse than on a permuted target** (-0.2823) and worse than on a
  simulated GBM at the published sigma (-0.2139). It beats the unconditional
  mean on 17 of 462 cells against the shuffled control's 5 of 154. **A HAR
  regression on `rv1`/`rv5`/`rv22` beats it** - srel 0.7094 against 0.7462 - and
  the unconditional mean beats both.
* **There is no volatility clustering in the family to forecast.** Measured as
  `rho = (1 + R2_naive) / 2`, **all twenty-one symbols lie inside [-0.013,
  +0.015]** and eight of them are negative, on blocks of 13,000 to 24,000 rows
  where the standard error of a correlation is 0.007. The family-wide figure is
  **-0.0014**.
* **The positive control passes, twice.** Run through identical code, real
  markets give `rho` of **0.086 to 0.155**, HAR R^2 positive at all eight
  timeframes, and **41 of 46** under-parameterised cells beating the mean against
  **8 of 107** on the synthetics. On direction the net reads **0.51527** on real
  markets (family-wise p = 0.0, best cell BTCUSD 1h at 0.5502 on 41,649 rows)
  against 0.50150 on the synthetics - and the momentum baseline shows why: it is
  **below 0.5 on all five real symbols**, which is bid-ask bounce, not an edge.
* **`Spot Up - Volatility Up Index` is the one symbol whose name comes true.**
  It is the only one of twenty-one with a positive mean HAR R^2, its `rho` runs
  0.039 / 0.019 / 0.023 at 3m / 15m / 1h against its own simulated null's 0.001 /
  -0.004 / 0.005, and all three of its other controls sit at zero. The effect is
  **one percent of variance**, and at 15m the recurrent net scores **-0.1646**
  where HAR scores **+0.0079**. There is a little structure; a straight line
  finds it; the net does not.
* **And a defect in the null every arm scores against.** `seqlab.gbm_bars`
  produced **11.28% of bars with a high below `max(open, close)`** - impossible
  on a traded bar - giving negative wick features where the feed's are bounded
  in [0, 1]. A feed-versus-simulation classifier could have read the answer off
  the sign of one feature on one bar in nine. Corrected.

Every number below names its sample size beside it. The harness is
[`harness/seqnets.py`](harness/seqnets.py); the data, features, splits, metrics
and controls are [`harness/seqlab.py`](harness/seqlab.py) and nothing else.

## Why the direction arm is not a hunt

`research/deriving.md` proves `E[net] = -(c/2) x turnover` for any predictable
position on a martingale. `research/rebuilding.md` confirmed it empirically on
these feeds - boosted models on tick windows, k-tuples and bar OHLC, `n*`
infinite on every arm. A Volatility index is geometric Brownian motion at a
published constant sigma and its increments are independent by construction.

So a direction AUC on this page has exactly one job: **come back at 0.50**. If
it had not, the first hypothesis would have been a leak in `seqnets.py` and the
second a defect in the feed worth chasing for what it says about the generator.
Neither would have been a trade. That ordering is why the controls outnumber the
models on this page four to one.

## The three checks that had to pass before any score was read

Stated as kill conditions in the harness docstring before the first run.

| check | what it catches | result |
| --- | --- | --- |
| `seqlab.check_causality` | a feature at row `t` moving when bar `t+50` is perturbed | **CLEAN**, 49,950 rows checked |
| window alignment | a window ending at `t` containing bar `t+1`, which is what the target reads | **asserted on every call to `windows()`**, not in a test file |
| injected leak | a pipeline that cannot see a signal handed to it directly | **FIRED** - target appended as a 29th feature gives direction AUC **1.0000** and `logvol` R^2 **0.9791** |

The third is the one that makes the rest readable. A null result from a harness
that cannot detect a planted signal is a statement about the harness.

Two further numbers from the same probe, both cross-checks rather than results:
`Volatility 75 Index` at 1h measures an annualised sigma of **0.7460** against
its published **0.75** - a 0.53% gap, in line with `research/grounding.md` tier
1's 0.49% on 12 of 12 - and the usable block is 49,978 rows of 50,000, the 22
lost being the feature warm-up and the horizon tail and nothing else.

## A convention, because this folder has already been burned by one

`research/forecasting.md` was revised twice and retracted two headline claims
because two volatility conventions were being mixed asymmetrically. So, before
any table: **`seqlab.srel` is an error and lower is better.** It is exactly
twice `consensus_vol.Score.error`, whose `accuracy` property is `1 - error` and
*larger* is better - which is the column `forecasting.md`'s table prints. The
conversion between the two pages is

    forecasting.md accuracy = 1 - seqlab.srel / 2

and it is stated here rather than assumed, because the two numbers are on
opposite sign conventions and are within a factor of two of each other, which is
precisely the range in which a mix-up survives a sanity check.

`logvol` is additionally scored by **out-of-sample R^2 against the training
block's unconditional mean**, not by srel. srel on a log-scale quantity is
dominated by the size of `log(1e-4)` and would report two useless forecasters as
nearly identical; R^2 against the mean has one reading and it is the one the
magnitude question asks for - **negative means the model loses to a constant**.
srel is carried beside it, on `realised` rather than on its log, so this page
joins `forecasting.md`'s table rather than replacing it.

## The architecture sweep, and what it already settled

48 configurations - 3 architectures x hidden `(8, 16, 32, 64)` x sequence length
`(8, 16, 32, 64)` - on 4 anchor cells chosen to span the sample cliff, both
targets, 5 walk-forward folds each. **384 cells, 0 failed, 10.7 minutes.**

Anchors and their usable rows: `Volatility 75 Index` 1h (**49,978**),
`Volatility 75 Index` 1d (**2,789**), `Volatility 10 Index` 1h (**49,978**),
`Spot Up - Volatility Up Index` 1h (**8,741**).

**Three of the forty-eight configurations have a positive mean test R^2 on
`logvol`, and the largest is +0.0022.** Selected honestly - on the validation
slice, which is the tail of the training block and was never scored against -
the winner is `gru` at hidden 64, sequence length 32, and its **test** R^2 is
**-0.0026**.

| selected on | config | val | test |
| --- | --- | --- | --- |
| validation (the rule, stated in advance) | `gru` h64 L32 | +0.00591 | **-0.00263** |
| test (**not used**, shown to price the difference) | `lstm` h32 L32 | +0.00248 | +0.00216 |

### The selection bias, measured

Over the 192 `logvol` cells the validation R^2 averages **-0.1126** and the test
R^2 **-0.1401**: a gap of **+0.0274**. Over the 192 direction cells the
validation AUC averages **0.51371** and the test AUC **0.50251**: a gap of
**+0.0112**.

That gap is the whole reason the selection rule was written into the docstring
before the run. **A harness that early-stops on a slice and then reports that
slice reports +0.011 of AUC that is not there**, which is the size of every
marginal edge this desk has ever had to withdraw. It is not a subtle effect and
it is not specific to these data.

### The family-wise number, from the sweep alone

192 direction cells - 4 anchors x 48 configurations - is already a family, and
it is the multiple-testing exposure the grid was going to widen rather than
create. Each cell's null standard error is computed from its own test-set class
counts, `seqlab.max_of_k` is handed 200,000 draws of "the best of 192 nulls",
and the observed best is compared against that.

| | |
| --- | --- |
| best observed AUC | **0.5310** - `Volatility 75 Index` 1d, LSTM h32 L32, **2,325 test rows** |
| per-cell null SE, range over the family | 0.00283 to 0.01198 |
| best-of-192 under the null: median | 0.5262 |
| best-of-192 under the null: 95th percentile | 0.5367 |
| **family-wise p (`seqlab.max_of_k`, 200,000 replicates)** | **0.2047** |
| mean AUC over the family | 0.50251, sd 0.00770 |
| median `seqlab.nstar` | **4.46e6 rows** |

**The best cell in the family sits below the median of what the family's own
nulls produce**, and it is at 1d, on the thinnest sample in the study, in an
overparameterised cell. That is what a search over 192 chances looks like when
there is nothing there. The median `n*` says the separation would need four and
a half million test rows to become a measurement, against the 41,649 the
densest cell has.

### The capacity floor

Hidden 8 is not a small model, it is a broken one:

| hidden | mean `logvol` R^2 (48 cells each) | median |
| --- | --- | --- |
| 8 | **-0.4333** | -0.1008 |
| 16 | -0.0542 | -0.0044 |
| 32 | -0.0560 | -0.0017 |
| 64 | -0.0168 | -0.0013 |

A net that cannot reproduce a constant is not evidence that the constant is
unbeatable, so every pooled figure on this page that compares the net to a
baseline is also given restricted to hidden >= 32.

### The like-for-like srel table, on the four anchors

All four forecasters predict on the log scale and are exponentiated, except
`mean realised`, which is the mean of `realised` itself. Cells are the mean over
the 24 configurations at hidden >= 32. **Lower is better.**

| anchor | test rows | net | exp(mean logvol) | HAR | mean realised | naive |
| --- | --- | --- | --- | --- | --- | --- |
| `Volatility 75 Index` 1h | 41,649 | 0.7054 | 0.7056 | 0.7056 | **0.6692** | 0.8819 |
| `Volatility 75 Index` 1d | 2,325 | 0.7197 | 0.7069 | 0.7080 | **0.6687** | 0.8728 |
| `Volatility 10 Index` 1h | 41,649 | 0.7105 | 0.7081 | 0.7082 | **0.6718** | 0.8879 |
| `Spot Up - Volatility Up Index` 1h | 7,285 | 0.7240 | 0.7142 | 0.7136 | **0.6902** | 0.8950 |

Three things fall out of it.

1. **The 1h figures reproduce `seqlab.main()`.** That run reported naive 0.8802
   against mean 0.6691 on `Volatility 75 Index` 1h; this harness, on
   walk-forward test rows with a *training-block* mean rather than a full-sample
   one, gets **0.8819** and **0.6692**. The generator-identification statistic
   is not an artefact of how the split was cut.
2. **The net lands on the constant, not below it.** At 1h the net and
   `exp(mean logvol)` differ by 0.0002 on 41,649 rows, and HAR is the same
   number again. The net beats `exp(mean logvol)` on **16 of 96** cells at
   hidden >= 32; HAR beats it on 24 of 96.
3. **Predicting the log costs about 0.035 of srel**, which is why
   `exp(mean logvol)` (0.7056) loses to `mean realised` (0.6692). That is the
   lognormal transform, not a modelling failure, and it is the reason the net is
   compared against `exp(mean logvol)` and not against `mean realised`.

## Parameters against samples, which turns out to decide the whole page

The commissioning note asked for one thing to be reported honestly: **an LSTM at
1d has more parameters than it has samples.** It does - and the check, run over
every sweep cell rather than only the 1d ones, says something stronger than was
asked for.

`seqnets.MAX_TRAIN` caps each fold's training block at 12,000 windows, so the
configuration the sweep selected on validation - hidden 64, sequence length 32,
**18,113 parameters** for a GRU and **24,129** for an LSTM - is overparameterised
at *every* cell in this study, not only at the top of the timeframe range. At
`Volatility 75 Index` 1h it trains on 10,927 windows; at 1d, on 1,088.

So the sweep's 192 `logvol` cells were re-cut by the ratio of parameters to
training windows:

| params / training windows | cells | mean R^2 | median R^2 | max R^2 | cells above zero |
| --- | --- | --- | --- | --- | --- |
| under 0.1 | 28 | -0.0772 | -0.00172 | -0.00021 | **0** |
| 0.1 - 0.3 | 44 | -0.1779 | -0.00247 | -0.00013 | **0** |
| 0.3 - 1.0 | 48 | -0.1984 | -0.00811 | +0.00940 | 1 |
| 1.0 - 3.0 | 44 | -0.1479 | -0.00131 | +0.01858 | 11 |
| 3.0 - 10.0 | 20 | -0.0345 | -0.01766 | +0.01384 | 6 |
| over 10 | 8 | -0.0226 | -0.01998 | -0.01291 | **0** |

**Seventeen of the eighteen positive R^2 cells in the sweep have more parameters
than training windows.** Restricted to cells that do not - `params < n_train`,
and hidden >= 16 so the capacity floor is excluded - the count is

> **0 of 52 cells beat the unconditional mean. The largest R^2 is -0.00013.**

On the same 52 cells, over **2,028,292 scored test rows**:

| forecaster | srel (lower is better) | R^2 vs the train-block mean | cells above zero |
| --- | --- | --- | --- |
| the net | 0.7090 | -0.02319 (median -0.00166) | **0 of 52** |
| HAR on `rv1`/`rv5`/`rv22` | **0.7074** | +0.00027 (median -0.00014) | 4 of 52 |
| `exp(mean logvol)` | **0.7074** | 0 by construction | - |
| mean of `realised` | 0.6720 | - | - |
| naive (last realised) | 0.8857 | -0.99025 | 0 of 52 |

**A recurrent net that loses to a straight line is a finding and it is this
one.** HAR beats the net on srel by 0.0016 and is the only forecaster in the
table that clears the unconditional mean at all, on 4 cells of 52 - which is
about what four coins do. The net beats HAR on 15 of 52 cells.

That is the result the rest of this page is a decomposition of. It cannot be
dismissed as a capacity artefact in either direction - the nets that are too
small to reproduce a constant are excluded, and every net that produced a
positive number had more parameters than samples.

## How the grid was run

The sweep chose the configuration; the grid ran it everywhere.

* **Symbols**: `seqlab.VOLATILITY` (20) plus `seqlab.SPOT_UP` (2), of which
  **21 can be pulled** - see [the availability finding](#an-availability-finding-recorded-because-it-changes-what-22-symbols-means).
* **Timeframes**: `seqlab.GRID` - 3m, 15m, 1h, 4h, 6h, 8h, 12h, 1d.
* **Configuration**: hidden **32**, sequence length **16** - **not** the
  geometry the validation slice chose, and the one place this study overrode
  its own selection rule. See
  [Parameters against samples](#parameters-against-samples-which-turns-out-to-decide-the-whole-page):
  the validation winner, hidden 64 and sequence length 32, is overparameterised
  at *every* cell in the grid, and a full grid at a geometry the harness's own
  kill condition 6 calls a memorisation would be reporting nothing. Hidden 32 at
  sequence length 16 is 5,985 parameters for a GRU against 10,927 training
  windows at the dense timeframes. **A capacity rule written down before any
  number was read is allowed to override a selection rule written down before
  any number was read; a score is not**, and the override is recorded on every
  record rather than applied silently. The validation-selected geometry is not
  abandoned - the sweep ran it at five folds on four anchors and its answer,
  test R^2 **-0.0026**, is in the sweep's table above.
* **Architecture is left free** - all three run on the `real` and `gbm`
  variants, so the family the multiple-testing correction has to cover is
  21 x 8 x 3 minus the pairs the feed will not serve - **2,464 cells** - rather
  than 21 x 8. Widening the family is the point: `seqlab.max_of_k` is only
  honest if the architecture axis is inside it.
* **Folds**: 5 walk-forward, expanding, never shuffled, with a purge of
  `horizon` bars between train and test. Early stopping on a validation slice
  taken from the **end** of the training block, with the same purge in front of
  it. Feature scaling fit on training rows only.
* **Controls**: `shuffle` and `surrogate` at the selected architecture,
  `gbm` at all three. `shuffle` and `surrogate` are mechanism controls and are
  not architecture-specific; `gbm` is inside the family because a null that only
  ever ran at one architecture cannot price what searching three does to the
  best score.
* **Threads**: eight cores. `torch.set_num_threads(8)` at module scope and a
  pool of eight worker processes pinned to one thread each - a recurrent net on
  a (256, 32, 28) batch does not scale past one thread, so eight one-thread
  processes finish the grid about six times faster than one eight-thread
  process and use the same eight cores.

### Where the sample runs out, and where it runs out first

The grid is not a rectangle. Several members hold only a few hundred bars at the
top of the timeframe range, and `seqlab.FEWEST` (600) refuses them rather than
reporting a score on them:

| refused | bars |
| --- | --- |
| `Volatility 15 Index` 1d, `Volatility 30 Index` 1d | 211 |
| `Volatility 5 Index` 1d, `Volatility 5 (1s) Index` 1d | 260 |
| `Spot Up - Volatility Up Index` 1d | 365 |
| `Volatility 15 Index` 12h, `Volatility 30 Index` 12h | 423 |
| `Volatility 5 Index` 12h, `Volatility 5 (1s) Index` 12h | 521 |
| `Volatility 15 (1s) Index` 1d, `Volatility 90 (1s) Index` 1d | 589 |

**This is a fact about the feed, not about the study.** The route returns
different depths at different timeframes for different members, and the 1d
column of any table over this family is a different set of symbols from the 1h
column. A pooled figure that does not say so is comparing two samples.

## What was added to `seqlab.py`, and why it belongs there

Two functions, both because an arm needed something the floor lacked and
duplicating it would have made the arms incomparable - which is the failure
`seqlab`'s own docstring was written about.

**`surrogate_bars(bars, rng)`.** `phase_surrogate` returns a *series* and a
sequence model is fed *bars*, and the conversion between the two is where a
surrogate control leaks. The tempting construction - keep the real bars, swap
only the closes - hands the model back `high`, `low`, `parkinson` and
`garman_klass`, which are the volatility signal the control exists to destroy.
So the path is rebuilt the way `gbm_bars` builds one: each surrogate return is
split into 24 pieces that sum to it exactly, a discrete Brownian bridge, so the
high and the low are extrema of a real sub-path. **The intra-bar wiggle is
scaled by the series' unconditional standard deviation and never by a local
one**, because a locally scaled bridge would put the clustering back inside the
bar and quietly restore the thing being removed. Volume and spread are permuted
rather than simulated, which keeps their marginals exactly and destroys their
order; timestamps are kept, so the clock features are real and the control is
strictly harder than one that randomises them too.

**`measured_sigma(bars, interval)`.** `NAMED_SIGMA` covers the twenty
constant-sigma members and nothing else, so `SPOT_UP` and everything in `REAL`
had no parameter to build a `gbm` null at. Measuring it in the floor rather than
once per arm is the point: six arms fitting six slightly different sigmas would
make their nulls incomparable, and the null is the only thing that makes any of
their positives readable. On a named member the two are checkable against each
other - `Volatility 75 Index` 1h measures **0.7460** against a published
**0.75**.

## A defect in the null itself, found while validating the new control

`surrogate_bars` was written to match `gbm_bars`' construction so the two
controls would be comparable by construction. Validating it against a simulated
GARCH series - a process with volatility clustering that is *known* to be there -
turned up something in `gbm_bars` instead.

**11.28% of simulated GBM bars had a high below `max(open, close)`**, and 11.43%
a low above `min(open, close)`. On a traded bar that is impossible. The cause is
that both simulators took the bar's extrema over the 24 intra-bar sub-points
alone, while the open is the *previous* bar's close - so the move from the open
to the first sub-point was outside the bar's own high and low.

What `seqlab.build` does with that:

| feature | simulated, before the fix | a traded bar | after the fix |
| --- | --- | --- | --- |
| `body` | [0.0000, **2.1199**] | [0, 1] | [0.0000, 1.0000] |
| `upper` | [**-0.9104**, 1.0000], 11.28% negative | [0, 1] | [0.0000, 0.9991] |
| `lower` | [**-1.1778**, 1.0000], 11.43% negative | [0, 1] | [0.0000, 0.9994] |

**`gbm` is the null every arm of this study scores against.** A classifier asked
"feed or simulation" could have had the answer from the sign of one feature, on
one bar in nine, for free - and every model reading candle shape was reading a
differently-supported variable on the control than on the feed. Fixed in
`seqlab.gbm_bars` and `seqlab.surrogate_bars` by taking the extrema over the
open as well as the sub-path, which is what a traded bar does. (A third
simulator added to `seqlab` by another arm takes `open` as the first point of
its own sub-path, so it never had the defect.)

**Why the re-run is a confirmation and not a correction.** The grid and the
positive control were scored before the fix, so their `gbm` cells used the
uncorrected bars - and the numbers those cells returned are what a *correct* null
returns: direction AUC **0.49999** over 462 cells, `R2_naive` **-0.9981**, `rho`
**+0.0007**. The defect changes the support of three shape features on simulated
bars; it does not give a volatility forecaster anything to forecast or a
direction classifier anything to classify, and the control did not behave as if
it had. The re-run is running to show that rather than to assert it, and if it
disagrees the disagreement is the finding.

### The surrogate, validated against a process with known clustering

20,000 bars of a GARCH(1,1) at `omega=1e-7, alpha=0.10, beta=0.88`, where
volatility clustering is there by construction, put through both controls:

| series | lag-1 acf of `log\|r\|` | lag-1 acf of `r` | annualised sigma | OHLC valid |
| --- | --- | --- | --- | --- |
| real (GARCH) | **0.1017** | 0.0063 | 0.2060 | yes |
| `surrogate` | **0.0108** | 0.0062 | 0.2060 | yes |
| `gbm` | -0.0010 | 0.0038 | 0.2066 | yes |

and the property that makes it a phase surrogate rather than a reshuffle:

| lag | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| acf of returns, real | 0.0063 | 0.0162 | -0.0158 | -0.0049 | -0.0105 |
| acf of returns, surrogate | 0.0062 | 0.0162 | -0.0157 | -0.0049 | -0.0106 |

**The linear autocorrelation survives to four decimals at every lag and the
clustering is gone**, return variance ratio 1.0000, volume marginal identical by
permutation, and `seqlab.check_causality` is CLEAN on the surrogate bars. That
is exactly the contract the control is supposed to honour, and it is checked
rather than asserted.

**And two corrections rather than additions.** `gbm_bars`' extrema, below, and
a guard in `build` so that an unknown tick size cannot delete every row of every
simulated series - see
[the regression](#the-regression-that-deleted-every-control-in-the-study). Both
are in the shared floor rather than in this arm, and both were found by running
a control against a process whose answer was known.

**`gbm_bars`' extrema.** It is the
section above and it is the most consequential change of the three, because it
is in the null every arm scores against rather than in a control only this arm
uses. No arm's existing numbers are invalidated by it on their face - the wick
features are a small part of a 28-feature matrix - but any arm that ran a
feed-versus-simulation classifier before this date should re-check what its
discriminator was reading.

## An availability finding, recorded because it changes what "22 symbols" means

`seqlab.SPOT_UP` names two instruments and **only one of them can be pulled.**
`Spot Up - Volatility Down Index` returns `HTTP 404 Not Found` on **every one of
the eight timeframes in `seqlab.GRID`**, after four retries each - not the
intermittent 404 that `seqlab.fetch` was written to retry around, but a
consistent one. `Spot Up - Volatility Up Index` pulls normally.

That halves the interesting half of the universe. The two Spot Up members are
the only ones in the family whose **name says the variance moves**, so they are
the only place a volatility forecast could have had anything to forecast, and
the study gets one of the two.

## `r2_naive` is not a score, it is an autocorrelation, and that is the whole finding

This is arithmetic rather than a measurement, and it is set down before the
table it explains.

Let `y = logvol` at `t+1` and let the naive forecaster predict `log(rv1)` at
`t` - the same quantity, one bar earlier, with the same marginal. Write `rho`
for their correlation. Then

    E[(y - naive)^2] = 2 * var(y) * (1 - rho)

so the out-of-sample R^2 against the unconditional mean is

    R2_naive = 1 - 2 * (1 - rho) = 2 * rho - 1

**`r2_naive` is the lag-1 autocorrelation of log realised volatility, rescaled
onto [-1, +1].** Three consequences, and they are what make the table below a
statement about the generator rather than about forecasting:

* On a process with **no** volatility clustering, `rho = 0` and `R2_naive` is
  **exactly -1**.
* On a real market, where clustering is a fact, `rho` is large and positive and
  `R2_naive` is positive.
* A model that only ties the unconditional mean is reporting `rho = 0`, not
  reporting a failure to try.

Over the 192 `logvol` cells of the architecture sweep, `r2_naive` measures
**-0.9778** (median -0.9771, and **0 of 192** above zero). That is
`rho = 0.0111`. On `Volatility 75 Index` at 1h the lag-1 autocorrelation of log
realised volatility is **one percent**, and the recurrent net's job was to find
structure in it.

## The positive control on the scoring layer, and the identity confirmed

A negative result is a statement about the harness until the harness is shown to
find the thing when it is there. The full positive control is
`seqlab.REAL` - gold, the majors, bitcoin - through the same folds and the same
architecture, and it is the `real` stage. But the *scoring layer* can be
controlled without a model at all, and that half is done and does not need the
lab: four GARCH(1,1) processes at `omega = 1e-7` and rising persistence, 40,000
bars each, through `seqlab.build`, `seqlab.targets` and `seqlab.walk_forward`
with the same five folds, scored by the same three baselines.

| process | measured lag-1 acf of `log\|r\|` | `R2_naive` | `rho` implied by `(1 + R2_naive) / 2` | `R2_har` | srel naive | srel mean |
| --- | --- | --- | --- | --- | --- | --- |
| GBM, no clustering | 0.0062 | -0.9876 | **0.0062** | -0.0002 | 0.8789 | 0.6647 |
| GARCH `alpha=.05, beta=.80` | 0.0144 | -0.9740 | **0.0130** | +0.0019 | 0.8755 | 0.6710 |
| GARCH `alpha=.10, beta=.88` | 0.1058 | -0.8051 | **0.0975** | +0.0590 | 0.8617 | 0.6987 |
| GARCH `alpha=.15, beta=.84` | 0.1857 | -0.6208 | **0.1896** | +0.1443 | 0.8639 | 0.7432 |

33,315 test rows per row of the table.

Three things are established by it.

1. **The identity holds empirically.** `rho` recovered from `R2_naive` agrees with
   the directly measured lag-1 autocorrelation of `log|r|` in all four rows -
   0.0062 against 0.0062, 0.1896 against 0.1857. `r2_naive` is an
   autocorrelation and the arithmetic in the section above is not a
   rationalisation of a bad score.
2. **The harness finds clustering when clustering is there.** `R2_har` goes
   -0.0002, +0.0019, +0.0590, +0.1443, monotonically in the persistence of the
   generator. A layer that returns zero on the Volatility family returns
   something else on a process that has something, using the same code.
3. **The Volatility family sits at the no-clustering end.** Its measured
   `R2_naive` of **-0.9778** puts `rho` at **0.0111** - between the pure GBM row
   (0.0062) and the mildest GARCH row (0.0144), and an order of magnitude below
   the row that looks like a real market. And the GBM row's srel pair, **0.8789
   against 0.6647**, is the feed's **0.8819 against 0.6692** to within 0.004 on
   both.

**This does not replace the `real` stage** - it controls the scoring, not the
net, and "an LSTM cannot find clustering on gold" would still be a fact about
this harness that nothing above would catch.

## The grid

**2,464 cells, 0 failed, 57.8 minutes.** 21 symbols x 8 timeframes x 3
architectures x 4 variants x 2 targets x 5 walk-forward folds, at hidden 32 and
sequence length 16. Every headline below carries its three controls on the same
line, which is the point of the table.

### Direction: the null calibration, and it calibrates

| variant | cells | test rows | mean AUC | sd | min | max | cells above 0.52 | momentum baseline |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **real** | 462 | 7,728,858 | **0.50150** | 0.01091 | 0.4465 | 0.5801 | 21 | 0.49940 |
| `shuffle` | 154 | 2,576,286 | 0.49939 | 0.01145 | 0.4370 | 0.5439 | 4 | 0.50010 |
| `surrogate` | 154 | 2,576,142 | **0.50183** | 0.01081 | 0.4662 | 0.5572 | 9 | 0.49842 |
| `gbm` | 462 | 7,728,858 | 0.49999 | 0.00926 | 0.4310 | 0.5525 | 19 | 0.50645 |

**The phase surrogate scores higher than the feed.** 0.50183 against 0.50150,
on a series built to have no nonlinear structure in it at all. So does the
`gbm` control's momentum baseline (0.50645) against the feed's (0.49940). The
four rows are one row.

The family-wise number, over all 462 real cells with each cell's null standard
error computed from its own class counts and `seqlab.max_of_k` given 20,000
draws of the best-of-462:

| | |
| --- | --- |
| best observed AUC | 0.5801 - `Volatility 90 Index` 8h, GRU, **361 test rows**, overparameterised |
| that cell's own null SE | 0.0304 |
| best-of-462 under the null: median | 0.5547 |
| best-of-462 under the null: 95th percentile | **0.5803** |
| **family-wise p** | **0.0511** |
| best control cell | 0.5572 - `Volatility 30 Index` 8h, GRU, `surrogate`, 360 test rows |

**The best cell in 462 lands on the 95th percentile of what 462 nulls produce,
and the control family's best is 0.5572 on a cell of almost exactly the same
size.** That is not an edge, it is what searching 462 cells costs.

The cleanest way to see it is to stop pooling and look at AUC against sample
size. `Volatility 90 Index` is one of the three members listed about 211 days
ago, so it runs from 50,000 bars at 3m to 633 at 8h - the same symbol, the same
generator, the same code:

| timeframe | bars | test rows | AUC, the three architectures |
| --- | --- | --- | --- |
| 3m | 50,000 | 41,649 | 0.5043, 0.5042, 0.5037 |
| 15m | 20,271 | 16,875 | 0.4934, 0.4983, 0.5037 |
| 1h | 5,067 | 4,205 | 0.5018, 0.5045, 0.5114 |
| 4h | 1,267 | 995 | 0.4797, 0.4973, 0.5494 |
| 6h | 845 | 573 | 0.5277, 0.5023, 0.4937 |
| 8h | 633 | 361 | 0.5606, 0.5097, **0.5801** |

**The AUC is a function of how little data the cell has and of nothing else.**
Banding the whole grid by test-set size and comparing the best real cell with
the best control cell in the same band says the same thing five times:

| test rows | real cells | best real AUC | control cells | best control AUC | control 99th pct |
| --- | --- | --- | --- | --- | --- |
| under 600 | 27 | 0.5801 | 45 | 0.5572 | 0.5514 |
| 600 - 1,500 | 51 | 0.5508 | 85 | **0.5525** | 0.5525 |
| 1,500 - 5,000 | 108 | 0.5345 | 180 | 0.5315 | 0.5244 |
| 5,000 - 20,000 | 123 | 0.5147 | 205 | **0.5174** | 0.5122 |
| 20,000 and up | 153 | 0.5073 | 255 | **0.5080** | 0.5056 |

The controls win three of the five bands. **The direction arm is a null and it
came back a null**, which is the result `research/deriving.md` predicted and the
only one this arm was built to be able to report.

### Magnitude: the net loses to the mean, to HAR, and to its own nulls

| variant | cells | test rows | R^2 net | R^2 HAR | R^2 naive | srel net | srel HAR | srel exp(mean logvol) | srel mean realised | srel naive | cells beating the mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **real** | 462 | 7,728,858 | **-0.3139** | -0.0031 | -1.0029 | 0.7462 | 0.7094 | 0.7084 | 0.6696 | 0.8844 | **17 / 462** |
| `shuffle` | 154 | 2,576,286 | -0.2823 | -0.0032 | -1.0149 | 0.7485 | 0.7090 | 0.7082 | 0.6693 | 0.8830 | 5 / 154 |
| `surrogate` | 154 | 2,576,142 | -0.1790 | -0.0036 | -0.9942 | 0.7315 | 0.7106 | 0.7096 | 0.6709 | 0.8844 | 6 / 154 |
| `gbm` | 462 | 7,728,858 | -0.2139 | -0.0034 | -0.9981 | 0.7440 | 0.7146 | 0.7138 | 0.6782 | 0.8998 | 11 / 462 |

Read the `real` row against the `shuffle` row. **The net does worse on the feed
(-0.3139) than on a target that has been permuted (-0.2823)**, and worse than on
a simulated GBM at the symbol's own published sigma (-0.2139). It beats the
unconditional mean on 3.7% of real cells against 3.2% of shuffled ones and 2.4%
of simulated ones. Those are the same number.

`R2_naive` is **-1.0029** on the feed - the value the identity above gives for
`rho = 0` is exactly -1. Measured across 462 cells and 7.7 million test rows,
the lag-1 autocorrelation of log realised volatility on the Volatility family is
**-0.0014**.

By architecture, on the real variant:

| architecture | parameters | direction AUC | `logvol` R^2 | overparameterised cells |
| --- | --- | --- | --- | --- |
| GRU | 5,985 | 0.50306 | -0.28973 | 108 / 154 |
| LSTM | 7,969 | 0.50088 | -0.25138 | 154 / 154 |
| vanilla RNN | 2,017 | 0.50056 | -0.40072 | 93 / 154 |

The vanilla RNN is the worst forecaster and has the fewest parameters; the LSTM
is the best and is overparameterised in every cell it ran. Neither ordering
means anything, because all three are below zero.

### Restricted to cells with fewer parameters than training windows

The comparison kill condition 6 exists to make possible, on the two universes,
with identical code:

| universe | cells | test rows | net R^2 mean | median | max | beats mean | HAR R^2 mean | HAR beats mean | net beats HAR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Volatility family | 107 | 4,103,133 | **-0.03732** | -0.00510 | +0.04217 | **8 / 107** | -0.00006 | 9 / 107 | 17 / 107 |
| real markets | 46 | 1,592,233 | **+0.05756** | +0.07133 | +0.15602 | **41 / 46** | +0.06433 | 45 / 46 | 33 / 46 |

and on direction, same cells:

| universe | net AUC | its `gbm` control | momentum baseline |
| --- | --- | --- | --- |
| Volatility family | 0.50045 | 0.49618 | 0.49983 |
| real markets | **0.51876** | 0.49648 | **0.48094** |

### Every symbol's volatility autocorrelation, measured

`rho = (1 + R2_naive) / 2`, pooled over timeframes and architectures on the real
variant. This is the table the magnitude question reduces to:

| symbol | rho | net R^2 | HAR R^2 | mean usable rows |
| --- | --- | --- | --- | --- |
| `Volatility 15 Index` | +0.0141 | -1.0827 | -0.0157 | 12,991 |
| `Spot Up - Volatility Up Index` | +0.0111 | -0.6686 | **+0.0005** | 14,162 |
| `Volatility 250 (1s) Index` | +0.0107 | -0.4686 | -0.0024 | 19,283 |
| `Volatility 75 (1s) Index` | +0.0035 | -0.0209 | -0.0022 | 23,312 |
| `Volatility 25 Index` | +0.0019 | -0.0218 | -0.0010 | 24,350 |
| `Volatility 50 Index` | +0.0017 | -0.0098 | -0.0023 | 24,350 |
| `Volatility 50 (1s) Index` | +0.0014 | -0.0061 | -0.0020 | 23,312 |
| `Volatility 5 Index` | +0.0006 | -1.5431 | -0.0088 | 14,077 |
| `Volatility 15 (1s) Index` | -0.0019 | -0.3225 | -0.0035 | 17,545 |
| `Volatility 100 (1s) Index` | -0.0023 | -0.0504 | -0.0014 | 23,818 |
| `Volatility 30 (1s) Index` | -0.0023 | -0.2062 | -0.0047 | 17,545 |
| `Volatility 10 Index` | -0.0027 | -0.0219 | -0.0013 | 24,350 |
| `Volatility 100 Index` | -0.0027 | -0.0332 | -0.0020 | 24,350 |
| `Volatility 75 Index` | -0.0029 | -0.0163 | -0.0007 | 24,350 |
| `Volatility 25 (1s) Index` | -0.0034 | -0.0138 | -0.0021 | 23,312 |
| `Volatility 5 (1s) Index` | -0.0075 | -1.5534 | -0.0094 | 14,077 |
| `Volatility 10 (1s) Index` | -0.0078 | -0.1294 | -0.0007 | 23,818 |
| `Volatility 150 (1s) Index` | -0.0079 | -0.4264 | -0.0003 | 19,283 |
| `Volatility 90 Index` | -0.0101 | -0.1539 | -0.0041 | 12,991 |
| `Volatility 30 Index` | -0.0128 | -0.6431 | -0.0064 | 12,991 |
| `Volatility 90 (1s) Index` | -0.0129 | -0.0515 | -0.0025 | 17,545 |

**Every one of the twenty-one is inside [-0.013, +0.015].** On blocks of 13,000
to 24,000 rows the standard error of a correlation is about 0.007, so the whole
column is two standard errors wide and centred on zero. Eight of the twenty-one
are *negative*. There is no volatility clustering in this family to forecast,
and that is the answer to the question this arm was commissioned to ask.

**One column is worth reading on its own.** `Spot Up - Volatility Up Index` is
the **only symbol of twenty-one with a positive mean HAR R^2**. It is also the
only one in the study whose name says the variance moves. The effect is
**+0.0005** of variance explained, and the section below takes it seriously
anyway because a pre-registered prediction that comes true at the fourth decimal
is still a prediction that came true.

### The two cells that separate from their controls at scale

Banding the `logvol` grid by test-set size the way the direction grid was banded:

| test rows | real cells | best real R^2 | control cells | best control R^2 | control 99th pct |
| --- | --- | --- | --- | --- | --- |
| under 5,000 | 186 | **-0.00057** | 248 | +0.00390 | +0.00082 |
| 5,000 - 20,000 | 123 | +0.01183 | 164 | +0.00075 | +0.00043 |
| 20,000 and up | 153 | **+0.04217** | 204 | +0.00018 | -0.00007 |

At the thin end the best real cell is *negative* and the controls win. At the
thick end - where an R^2 means something - two symbols separate from everything
the controls can do, and both are worth naming.

**`Spot Up - Volatility Up Index`**, the one member whose name promises moving
variance:

| timeframe | variant | test rows | R^2 net | R^2 HAR | rho | srel net | srel exp(mean logvol) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3m | **real** | 41,649 | +0.0045 | **+0.0105** | **+0.0387** | **0.7274** | 0.7658 |
| 3m | `gbm` | 41,649 | -0.0018 | -0.0001 | +0.0007 | 0.7078 | 0.7102 |
| 3m | `surrogate` | 41,648 | -0.0043 | -0.0000 | -0.0034 | 0.7092 | 0.7084 |
| 3m | `shuffle` | 41,649 | -0.0049 | -0.0003 | -0.0000 | 0.7132 | 0.7147 |
| 1h | **real** | 7,285 | +0.0065 | **+0.0075** | **+0.0231** | 0.7143 | 0.7143 |
| 1h | `gbm` | 7,285 | -0.0071 | -0.0004 | +0.0049 | 0.7217 | 0.7204 |
| 1h | `surrogate` | 7,284 | -0.0031 | -0.0002 | -0.0037 | 0.7148 | 0.7137 |
| 1h | `shuffle` | 7,285 | -0.0115 | -0.0015 | -0.0230 | 0.7244 | 0.7230 |

**HAR is positive at all four timeframes on this symbol** (+0.0105, +0.0079,
+0.0075, +0.0042) and at none of them on `Volatility 75 Index` (-0.0002, -0.0002,
-0.0001, -0.0003), while every control on the Spot Up cells sits at zero. Its
`rho` runs 0.039 / 0.019 / 0.023 against its own `gbm` null's 0.001 / -0.004 /
0.005.

**So the name is telling the truth and the effect is one percent of variance.**
That is the honest summary: the variance does move, measurably, on the one
member advertised as having a moving variance - and at 15m the recurrent net
scores **-0.1646** where HAR scores **+0.0079**, which is this page's headline in
miniature. There is a little structure, a straight line finds it, and the net
does not.

**`Volatility 250 (1s) Index` at 15m**, the largest `logvol` score in the whole
grid, and **the first hypothesis is a defect in the feed**:

| timeframe | variant | test rows | R^2 net (GRU / LSTM / RNN) | rho | srel exp(mean logvol) |
| --- | --- | --- | --- | --- | --- |
| 3m | real | 41,649 | -0.0004 pooled | +0.0057 | 0.7128 |
| **15m** | **real** | 41,649 | **+0.0208 / +0.0143 / +0.0422** | **+0.0657** | **0.8006** |
| 15m | `gbm` | 41,649 | -0.0014 / -0.0014 / -0.0058 | +0.0007 | 0.7102 |
| 15m | `surrogate` | 41,648 | -0.0014 | +0.0029 | 0.7081 |
| 15m | `shuffle` | 41,649 | **-0.0157** | **-0.0390** | **0.7831** |
| 1h | real | 27,205 | -0.6057 pooled | +0.0009 | 0.7065 |

All three architectures agree and all three controls are at zero, which is what
a real effect looks like. **Two things say it is not one.**

First, `srel exp(mean logvol)` at this cell is **0.8006** where every other cell
in the 462 is near 0.708 - the target's *marginal* is anomalous, not just its
time structure. Second, and decisively, **the `shuffle` control reproduces the
anomaly**: it reads 0.7831 on the same axis and a `rho` of **-0.0390** where a
permuted target must give zero. A control that cannot return zero is telling you
its error bar is not 0.005 but something closer to 0.04 - which is the size of
the effect. The same symbol posts net R^2 of -0.61 and -0.62 at 1h and 4h with
`shuffle` at -1.71 and -1.20, which is the behaviour of a heavy-tailed target,
not of a forecastable one.

The mechanism that would produce all of it is a stretch of repeated quotes:
`rv1` of exactly zero sends `log(rv1)` to the `1e-12` floor, the floor values
cluster in time, and both the autocorrelation and the fat tail follow.
`research/rebuilding.md` found `frac_zero` at AUC 0.686 opening the quote-lattice
question on this same family. **Pre-registered check, not a claim:** count the
zero-return bars on `Volatility 250 (1s) Index` at 15m. If they are a
concentrated run, this cell is a data defect and comes off the table. It is
recorded here rather than dropped because `research/grounding.md`'s rule on this
project is that a learned model has only ever paid as a pointer at a defect.

## The positive control on real markets, and it is the strongest table here

**480 cells, 0 failed.** `seqlab.REAL` - XAUUSD, EURUSD, GBPUSD, USDJPY, BTCUSD -
through identical features, identical folds, identical architectures and
identical scoring, each against a `gbm` control built at its own
`seqlab.measured_sigma`. This is the stage that decides whether everything above
is a statement about the synthetics or a statement about the harness.

### Magnitude

| variant | cells | test rows | R^2 net | R^2 HAR | R^2 naive | srel net | srel HAR | srel exp(mean logvol) | srel naive | cells beating the mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **real markets** | 120 | 3,145,854 | -0.0154 | **+0.0556** | **-0.7734** | 0.7948 | 0.8196 | 0.8257 | 0.9422 | **96 / 120** |
| their `gbm` control | 120 | 3,316,380 | -0.0034 | -0.0002 | -0.9967 | 0.7116 | 0.7122 | 0.7124 | 0.8909 | 4 / 120 |

by timeframe, real markets only:

| timeframe | usable | test rows | rho | R^2 net | R^2 HAR |
| --- | --- | --- | --- | --- | --- |
| 3m | 39,285 | 32,738 | **0.1325** | +0.0541 | +0.0741 |
| 15m | 49,978 | 41,649 | **0.1294** | +0.0916 | +0.0823 |
| 1h | 49,978 | 41,649 | **0.1550** | +0.0988 | +0.0816 |
| 4h | 36,434 | 30,362 | 0.1183 | +0.0182 | +0.0548 |
| 6h | 27,724 | 23,104 | 0.0990 | +0.0054 | +0.0477 |
| 8h | 21,914 | 18,262 | 0.0949 | -0.0703 | +0.0420 |
| 12h | 16,088 | 13,407 | 0.0860 | -0.1973 | +0.0337 |
| 1d | 10,259 | 8,550 | 0.0913 | -0.1240 | +0.0287 |

**`rho` is 0.086 to 0.155 on real markets against -0.013 to +0.015 across the
whole Volatility family** - an order of magnitude, measured by the same line of
code. HAR is positive at all eight timeframes and the net at five of eight. The
`gbm` control built at these symbols' own measured sigmas returns `R2_naive` of
**-0.9967**, i.e. `rho = 0.0017`, which is the Volatility family's number.

Restricted to cells with fewer parameters than training windows, the contrast is
the one already given above: **41 of 46 real-market cells beat the unconditional
mean at a mean R^2 of +0.058, against 8 of 107 at -0.037 on the synthetics.**

The best cells are real forecasts rather than thin-sample noise:

| cell | R^2 net | R^2 HAR | test rows | overparameterised |
| --- | --- | --- | --- | --- |
| BTCUSD 1h LSTM | +0.1648 | +0.1843 | 41,649 | yes |
| BTCUSD 1h GRU | +0.1560 | +0.1843 | 41,649 | **no** |
| XAUUSD 15m RNN | +0.1530 | +0.1261 | 41,649 | **no** |
| XAUUSD 15m LSTM | +0.1520 | +0.1261 | 41,649 | yes |

**And HAR still beats the net on BTCUSD** (+0.1843 against +0.1648) while the net
beats HAR on XAUUSD. Over all 120 cells the net beats HAR on 81. So the
recurrent net is a real forecaster on real data - it just is not reliably a
better one than three lagged magnitudes and an intercept.

### Direction, and the second positive control nobody asked for

| variant | cells | test rows | mean AUC | sd | max | cells above 0.52 | momentum baseline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **real markets** | 120 | 3,145,854 | **0.51527** | 0.01204 | 0.5502 | **34** | **0.48154** |
| their `gbm` control | 120 | 3,316,380 | 0.49740 | 0.00451 | 0.5173 | **0** | 0.50513 |

Family-wise over the 120 real-market cells: best **0.5502** (BTCUSD 1h, GRU,
**41,649 test rows, not overparameterised**, `nstar` 25,391) against a
best-of-120 null whose median is 0.5135 and whose 95th percentile is 0.5213.
**Family-wise p = 0.0.**

The mechanism is visible in the baseline column and it is not an edge:

| symbol | momentum AUC | net AUC | its `gbm` control |
| --- | --- | --- | --- |
| BTCUSD | **0.4681** | 0.5268 | 0.4974 |
| GBPUSD | 0.4866 | 0.5166 | 0.4962 |
| USDJPY | 0.4833 | 0.5144 | 0.4977 |
| EURUSD | 0.4854 | 0.5104 | 0.4972 |
| XAUUSD | 0.4843 | 0.5080 | 0.4985 |

**Momentum is below 0.5 on all five**, which is short-horizon *reversal* - the
bid-ask bounce, a microstructure fact about traded markets and not a trade at
this size. The net finds it; on the synthetics the same baseline reads 0.49983
and the same net reads 0.50045.

**So the direction arm has a positive control too, and it passes.** The harness
detects direction structure on markets that have some and returns 0.5015 on a
family that does not. A null result from a classifier that cannot find
bid-ask bounce would have been a statement about the classifier.

## The regression that deleted every control in the study

Caught on the confirmation re-run, not on the run this page reports, and it is
the most consequential thing on the page for the other five arms.

Between the grid run and the re-run, `seqlab.build` was changed - correctly, and
for a good reason - to compute `spread_rel` through a new `rel_spread`, which
multiplies MetaTrader's integer point count by an inferred `tick_size` instead of
treating it as a price. The old form was meaningless across symbols and the new
one is validated against the `(1s)` twins to half a percent. Nothing about that
is wrong.

`tick_size` infers the quote grid by finding the coarsest decimal grid every
close lies on, and **returns `nan` when no grid fits.** A simulated path emits
full-precision floats, so no decimal grid fits, so it returns `nan` - correctly.
That `nan` then flows into `rel_spread`, into `spread_rel`, and into
`seqlab.usable`, which requires **every** feature to be finite.

> **Every row of every simulated series was dropped.** `gbm` and `surrogate` are
> exactly half of this arm's 2,464 cells, and exactly half of them failed -
> 522 of the first 1,037, as `Thin`, with no error and no traceback.

The symptom is worth stating plainly because it is what the next person will
see: the run does not crash, the log does not complain, and the controls simply
stop existing. An arm that reports its headline numbers without checking its
control count would publish an uncontrolled result and never know.

**The repair is in `build` and deliberately not in `tick_size`.** That function's
`nan` is load-bearing: its own docstring says the failure it exists to prevent is
a cost model that "looks plausible and charges nothing", so handing a cost-aware
arm a finite fallback would reintroduce exactly the bug it was written to kill.
A *feature* is allowed to say "there is no quote grid here"; a *cost* is not. So
`build` substitutes a constant zero column when - and only when - the entire
`spread_rel` column is non-finite, which cannot happen on a real feed because
real closes are quantised by construction.

**The numbers on this page are not affected.** The grid and the positive control
ran before this change, on the older `spread_rel`, and their control counts are
462 / 154 / 154 / 462 with zero failures - which is how the regression was
visible at all: a re-run of the same command produced half the cells. The
confirmation run now in flight carries both the corrected `gbm_bars` and the
corrected `build`, and it also carries the *new* `spread_rel` definition, so if
its real-variant cells move materially from the ones reported here, that
movement is a measurement of what the old spread feature was worth and belongs
on this page rather than in a footnote.

## What fell over

Recorded because this folder keeps its failures.

1. **The validation-selected geometry failed the harness's own capacity rule.**
   Caught by running kill condition 6 over every sweep cell rather than only the
   1d ones, which is what it was written to check. The grid was reconfigured and
   the override recorded; see
   [How the grid is set up](#how-the-grid-is-set-up).
2. **`gbm_bars` was making bars a traded feed cannot make**, on 11.28% of them,
   and it is the null every arm of this study scores against. Caught by
   validating a *different* function against a process with known clustering.
   Fixed.
3. **The first grid attempt ran at the overparameterised geometry for 25 minutes
   before being stopped.** It projected to about four hours and would have
   produced 2,816 cells that kill condition 6 calls memorisations.
4. **`Spot Up - Volatility Down Index` 404s on all eight timeframes**, and the
   first version of `seqnets.warm` recorded that and then let the fan-out
   rediscover it once per cell - **128 cells x 4 retries, about five hundred
   requests to a route that was never going to answer**, against the terminal
   the live desk trades through. The arithmetic was unaffected; the cost was
   borne entirely by a shared resource, which is the kind of defect a result
   table never shows. `warm` now returns the dead pairs and the caller drops
   them: the second attempt enumerated **2,464** cells instead of 2,816.
5. **A change to the shared floor silently deleted every control in the study**,
   and the only reason it was caught is that the same command was run twice and
   the second run produced half the cells. It has its own section above.
6. **The research host refused SSH for about six hours**, in the middle of the
   grid and its positive control, and **this page's first diagnosis of it was
   wrong.** `Connection refused` rather than a timeout was read here as "the
   machine answers and `sshd` does not", i.e. a dead daemon. It was not: the lab
   was healthy throughout and serving the live desk's MT5 tunnel the whole time,
   and **one egress address is filtered at the edge - and it is not
   fail2ban.** That attribution stood here for an hour and is withdrawn: the
   address appears nowhere in `/var/log/fail2ban.log` (470 ban entries, the last
   at 13:08), the only enabled jail has the Debian default **10-minute** bantime,
   which cannot produce a six-hour block, and the machine **rebooted at
   22:04:59** - which clears ephemeral bans - after which the refusal continued
   unchanged. Whatever filters it sits above fail2ban and could not be read
   because `sudo` wants a password. **Twice this outage was explained
   confidently and wrongly**, which is the argument for the jump route rather
   than for a third explanation: it works without anyone being right about the
   cause. The evidence that settles it is
   that port 22 stayed open *from another host*. `lab.sh` now probes direct
   first and falls back to a jump route, which is how the corrected run was
   launched.

   `research/starving.md` is about research load degrading the *production* box.
   This is the same lesson one machine over with a different mechanism - not
   memory, but a rate limiter - and the detached-with-`nohup` discipline that
   page established is the only reason the 68.9-minute run survived an outage
   that outlasted it. **The wrong diagnosis is kept because it was load-bearing
   for an hour**: it is what made the grid look lost when it had already
   finished.

## What would change this answer

Written so the next person does not have to guess what this page would accept
as a refutation.

1. **The `Volatility 250 (1s) Index` 15m cell resolving the other way.** It is
   the largest `logvol` score in the grid, all three architectures agree on it,
   all three controls sit at zero - and its own `shuffle` control returns a
   `rho` of -0.0390 where a permuted target must return zero, which says the
   error bar there is 0.04 and not 0.005. **Count the zero-return bars on that
   symbol at that timeframe.** If they are a concentrated run, the cell is a
   quote-lattice artefact and comes off the table; if they are not, this page
   owes an explanation it does not currently have.
2. **A direction AUC that clears the best control cell across the family.** Not
   a cell above 0.52 - the best of a few hundred fair coins does that routinely,
   which is what `max_of_k` is for - but one above what the same grid's own
   nulls reach.
3. **A horizon longer than one bar.** Everything here is `horizon=1`, and
   `research/forecasting.md`'s central result is that the single-bar comparison
   is a trap with a wide mouth: persistence wins at one bar for reasons that have
   nothing to do with forecasting and loses at every horizon past it. On a
   constant-sigma process there is nothing for a longer horizon to find either,
   but **that is an argument, not a measurement**, and this page has not made it.
   `seqlab.targets` already takes a `horizon`; the grid does not sweep it.
4. **`Spot Up - Volatility Down Index`.** The one symbol in the study that could
   not be pulled is the mirror of the one symbol that produced a positive
   result. If the Down member reproduces the Up member's `rho` of 0.02 to 0.04
   and its positive HAR R^2, the effect is a property of the Spot Up pair rather
   than of one feed, and that is worth having. If it does not, the Up member's
   one percent needs re-examining. **This is the single cheapest open item on
   the page**, and it is blocked on a route that 404s.
5. **A different sigma regime.** These are the constant-sigma members plus one
   of the two whose name says otherwise. The other families - Boom, Crash, Jump, Step,
   Range Break, Drift Switch, DEX - are a different arm and a different page;
   `seqlab.SYNTHETIC` holds them and none of them is geometric Brownian motion.
6. **The `1s` twins at their own resolution.** Everything here is bar data from
   3m up. `research/twins.md` established that a twin pair carries identical
   volatility per second with per-tick variance differing by exactly sqrt(2), so
   the place a sequence model could still have something to see on this family is
   *below* the bottom of this grid, not above it.

## Reproducing this page

Everything here comes out of four commands and two JSON files.

    ./.secrets/lab.sh run research/harness/seqnets.py MODE=probe
    ./.secrets/lab.sh run research/harness/seqnets.py MODE=sweep
    ./.secrets/lab.sh run research/harness/seqnets.py MODE=all

`probe` writes `data/seqnets/probe.json` and is the three checks; `sweep` writes
`sweep.json` and is the 384-cell architecture search; `all` writes `grid.json`
and `real.json` and is the 22-symbol grid followed by its positive control. Every
record carries `symbol`, `interval`, `variant`, `arch`, `hidden`, `seqlen`,
`target`, `bars`, `usable`, `n_train`, `n_train_avail`, `n_test`, `params`,
`epochs`, `overparam` and a `per_fold` list, so any number quoted above can be
recomputed from disk without re-running a model.

To re-run the grid at the geometry the validation slice actually chose, and
spend the four hours it costs:

    ./.secrets/lab.sh run research/harness/seqnets.py MODE=grid HIDDEN=64 SEQLEN=32

