# Sequence models on the Volatility family: a null that calibrates and a question that closes

The recurrent arm of the sequence study. Three architectures - LSTM, GRU and a
vanilla tanh RNN - on `seqlab`'s 28 causal features, across the Volatility
family and 8 timeframes, against two targets: **direction**, which is a
calibration, and **`logvol`**, which is the question. Twenty-two symbols were
commissioned; **twenty-one can be pulled** and the missing one is the more
interesting half of the pair that matters.

> **Partial, 2026-09-12.** What is written up here is complete and final: the
> three harness checks, the 384-cell architecture sweep at five folds, the
> family-wise number on its 192 direction cells, the parameter-versus-sample
> decomposition, the correction to `seqlab.gbm_bars`, the validation of the new
> `surrogate_bars` control, and the positive control on the **scoring layer**.
>
> The 2,464-cell grid and the real-market positive control **ran to completion
> in 68.9 minutes** and their `grid.json` and `real.json` are sitting in
> `data/seqnets/` on the research host. They are not written up here because
> **the host has been unreachable for most of the session** - `sshd` refusing
> connections for two hours from 16:51, back briefly, gone again - with six
> agents on it and a load average that peaked at 52. The machine itself never
> rebooted (`up 22:23` when it returned), which is the only reason the detached
> run survived.
>
> **Both will need re-running rather than just fetching**, and that is a
> scientific point rather than an operational one: the `gbm_bars` correction
> below landed *after* that run started, so every `gbm` control cell in those
> two files was scored against the uncorrected null - the one where one bar in
> nine has a high a traded bar could not produce. The command is in
> [Reproducing this page](#reproducing-this-page) and costs about 70 minutes.
>
> Nothing below is provisional and nothing is claimed here about the grid.

**What the sweep already settles.**

* **Direction calibrates.** Over the sweep's 192 direction cells the mean test
  AUC is **0.50251** with a standard deviation of 0.0077, against a momentum
  baseline at 0.50309 on the same rows. Nine cells of 192 clear 0.52 and none
  clears 0.55, which is what a few hundred fair coins do. This is the result the
  arm was built to produce; `research/deriving.md` already proved no other one
  was available. The best cell in the family - **0.5310**, at 1d on 2,325 test
  rows - sits **below the median of the family's own best-of-192 null** (0.5262),
  and `seqlab.max_of_k` over 200,000 replicates puts the family-wise p at
  **0.2047**.
* **Magnitude closes against the net.** Of 48 configurations - 3 architectures x
  4 hidden sizes x 4 sequence lengths - **three have a positive mean test R^2 on
  `logvol` and the largest is +0.0022**. Restricted to cells with fewer
  parameters than training windows, **0 of 52 beat the unconditional mean** and
  the largest R^2 is **-0.00013** across **2,028,292 scored test rows**. On
  those same cells and rows, **HAR on `rv1`/`rv5`/`rv22` beats the net** - srel
  0.7074 against 0.7090, and HAR clears the mean on 4 cells where the net clears
  it on none - and the unconditional mean beats both.
* **The generator-identification statistic reproduces.** `seqlab.main()`
  reported naive srel 0.8802 against the unconditional mean's 0.6691 on
  `Volatility 75 Index` 1h; this harness, on walk-forward test rows with a
  training-block mean, gets **0.8819** and **0.6692** over 41,649 test rows.
  The naive forecaster being *worse than a constant* is not a forecasting
  failure - it is the measurement that sigma is constant, and
  [the section below](#r2_naive-is-not-a-score-it-is-an-autocorrelation-and-that-is-the-whole-finding)
  shows it is exactly a lag-1 autocorrelation of **0.0111**.
* **The scoring layer finds clustering when it is there.** The same code on four
  GARCH(1,1) processes of rising persistence returns `R2_har` of -0.0002,
  +0.0019, +0.0590, +0.1443, and recovers the lag-1 autocorrelation of `log|r|`
  from `R2_naive` to three decimals in all four. A layer that returns zero here
  returns something else on a process that has something.
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

## How the grid is set up

The sweep chose the configuration; the grid was to run it everywhere. This is
what it will do when it runs - the harness is written, the cells are enumerated
and the first 122 of them completed before the host went away.

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
open as well as the sub-path, which is what a traded bar does.

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

**And one correction rather than an addition: `gbm_bars`' extrema.** It is the
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

## The grid - run, not yet readable

21 symbols x 8 timeframes x 3 architectures x 4 variants x 2 targets x 5 folds,
**2,464 cells** after the unavailable and too-thin pairs are dropped, at hidden
32 and sequence length 16. It **completed in 68.9 minutes** and wrote
`data/seqnets/grid.json` on the research host, which has been unreachable since.
Even once it is fetched it will be re-run: the `gbm_bars` correction landed after
it started, so its `gbm` cells were scored against the uncorrected null. The
command is in [Reproducing this page](#reproducing-this-page) and the harness
needs no changes to run it.

What it is for, given the sweep has already answered the central question on
four anchors: **breadth and the controls.** The sweep ran the `real` variant
only. `shuffle`, `surrogate` and `gbm` have never been run against a net on this
family, so the strongest sentence this page can currently make about the
magnitude result is "no configuration beats a constant", not "no configuration
beats a constant by more than its own simulated null does". Those are different
claims and only the first is supported here.

## The positive control on real markets - run, not yet readable

`seqlab.REAL` - XAUUSD, EURUSD, GBPUSD, USDJPY, BTCUSD - through identical
folds, identical features and identical architectures, all 40 (symbol,
timeframe) pairs already in the cache. It ran in the same 68.9 minutes and wrote
`data/seqnets/real.json`. The scoring layer is controlled by the
section above; **the net is not**, and until it is, "a recurrent net finds
nothing on the Volatility family" is a sentence with one leg missing.

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
5. **The research host stopped accepting SSH at 16:51** with six agents on it
   and a load average of **52**, in the middle of the grid and its positive
   control. `Connection refused` rather than a timeout, so the machine answers
   and `sshd` does not. `research/starving.md` is about research load degrading
   the *production* box; this is the same lesson one machine over, and the
   detached-with-`nohup` discipline that page established is the only reason the
   run may still be alive.

## What would change this answer

Written so the next person does not have to guess what this page would accept
as a refutation.

1. **A cell where the net beats `exp(mean logvol)` with `params < n_train`, on a
   constant-sigma member, that the `gbm` control at the same sigma does not
   match.** There are none here. One would mean the feed is not the GBM its name
   claims, which is a finding about the generator and outranks the forecast.
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
4. **A different sigma regime.** These are the constant-sigma members plus one
   of the two whose name says otherwise, and `Spot Up - Volatility Down Index`
   could not be pulled at all. The other families - Boom, Crash, Jump, Step,
   Range Break, Drift Switch, DEX - are a different arm and a different page;
   `seqlab.SYNTHETIC` holds them and none of them is geometric Brownian motion.
5. **The `1s` twins at their own resolution.** Everything here is bar data from
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

