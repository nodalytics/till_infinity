# Seventeen of eighteen fractal links draw pictures, and the rolling estimators are not volatility in disguise - they are simply empty

Asked on 2026-11-09: eighteen links to fractal software, and *"document them and
also borrow ideas from fractals we can test as indicators and strategy rules,
entries, exits, etc"*.

Two deliverables, kept separate below: a **survey** of what each link actually
is, and a **measurement** of the estimators worth borrowing. A third section
catalogues the scripts, because a result nobody can re-run is a claim.

| question | verdict |
|---|---|
| **The survey.** How many of the eighteen links are of any use to a trading desk? | **One.** `fractal-analysis` on PyPI (and `yujiading/fractals`, its source repo - the same project counted twice) computes Hurst and Hölder exponents **on a data series**. Three more measure the fractal dimension of **images or 3-D meshes**, ten are **Mandelbrot, Julia, Newton-basin or IFS renderers**, two are tutorials that draw a Koch snowflake, and one uses "fractal" as branding for a text-to-image encoder. Nothing in the list 404s |
| Is the one useful library worth a dependency? | **For its simulator, as a cross-check, in its own venv.** MIT, released 0.3.7 on 2026-01-13, and it is the only item in the list with 2026 activity. But `requires-python >= 3.13` from 0.2.1 and `< 3.11` at 0.2.0 and below, so **on Python 3.12 no version of it installs at all** - twenty-four releases, none matching |
| **Do this repo's estimators agree with it?** | **Yes, in both directions.** This repo's DFA and structure-function exponents recover a planted `H` from the library's Wood-Chan paths at slopes of **0.930** and **0.978** against an ideal 1.0, with biases of +0.031 and -0.017; rescaled range is the weak one at slope **0.727**. Section 3 |
| **Cost.** Which instruments can carry an intraday fractal rule? | **7 of 8 traded.** At the production stop of 3.0 volatility units a 15-minute round trip is **0.046R (XAUUSD) to 0.078R (EURUSD)**, all inside the 0.16R ceiling. **XAGUSD is refused at 0.383R** - 14.4 bps quoted, not 0.8 like the FX legs. Section 4 |
| **Power.** Would the test see a fractal effect if one were there? | **Yes, comfortably.** All seven estimators separate a planted `|H - 0.5|` of **0.20** at `\|z\| > 2` over 24 draws, and all are monotone in `H` across 0.30-0.70. The *rule* is sharper than the estimators: momentum on a planted `H = 0.60` earns **+0.2553R gross** and on `H = 0.40` loses **-0.1385R**, both at more than two standard errors, while `H = 0.50` reads +0.0106R and is not. Section 5 |
| **The signal.** Does a rolling fractal reading forecast volatility or direction? | **Direction: no, to three decimals.** AUC **0.500** on every reading, every arm, pooled and within strata - 40 rows between 0.497 and 0.504. **Volatility: one of seven survives.** The structure-function Hurst reads **0.526 pooled and 0.524 within volatility strata**, on 8 of 8 traded instruments at width 128 and 8 of 8 at 256, where its i.i.d., block, GARCH and walk arms all read **0.50**. Every other estimator collapses to its nulls. Section 6 |
| **The trade.** Does the Hurst regime switch pay? | **No, and it fails before cost.** Over **756 real-arm cells and 2.2M de-overlapped trades** the switch's gross is **-0.0082R against its own coin twin's -0.0071R** - it is not better than a coin at the same duty cycle - and the 2:1 hit rate is **0.3049 against the walk's arithmetic 0.3333**, with the shuffled arm at 0.3212 beating the real series. Net is **-0.0891R** against a cost of **0.0809R**: the loss is the spread. Benjamini-Hochberg over the 756 cells keeps **1 as profitable and 436 as losing**. Section 7 |
| Should anything be built? | **No, with one reading published and not gated.** The structure-function Hurst is the only survivor, it is worth 0.024 of AUC on a *volatility* target where the incumbent trailing standard deviation is worth 0.115, and it was never shown to add anything **on top of** that incumbent. `publish-then-measure-then-gate`: it ships as a named feature or not at all |

---

## 1. The survey

The list contains two unrelated kinds of software that share a word. A
**fractal estimator** takes a data series and returns an exponent; a **fractal
renderer** takes a complex-plane region and returns an image. The second is a
rendering problem with no input data, so it cannot be applied to a price series
at all - there is nothing to apply it to. This distinction is the survey's whole
content, and it is not a quibble about emphasis: a Mandelbrot set is generated
by iterating `z -> z**2 + c` over a grid of starting points, and no step of that
procedure accepts a time series.

Checked 2026-11-09. Every URL below was fetched and resolves; licence, language,
stars and last-push date come from each repository's API record rather than its
rendered page, and the two PyPI facts from the JSON API.

| # | link | what it actually is | kind | licence | last activity | use to a desk |
|---|---|---|---|---|---|---|
| 1 | [wanglab-georgetown/fractal](https://github.com/wanglab-georgetown/fractal) | box-counting dimension of an `(n, 2)` array of **2-D points**, with an exact algorithm and scaling-range detection; Rényi q-dimensions and a Takens correlation dimension | point-set analysis | Apache-2.0 | 2024-12-20, 3 commits, 10 stars | **No.** A one-paper artefact (Cui and Wang 2024, *Results in Engineering*) for animal-behaviour tracks. A price series is a 1-D graph, not a point cloud, and the box count it needs is twenty lines |
| 2 | [rbaravalle/imfractal](https://github.com/rbaravalle/imfractal) | multifractal spectra of **images and 3-D volumes** - Hölder-exponent singularity spectrum, sandbox method - as classifier features | image analysis | BSD 3-clause (non-verbatim `COPYING`) | 2018-02-15, **Python 2.7 only** | **No.** Abandoned eight years, Python 2, and the input is an image |
| 3 | [fractal-analysis (PyPI)](https://pypi.org/project/fractal-analysis/) | **the one series tool.** IR and QV Hurst/Hölder estimators (Bardet and Surgailis 2013); FBM and MBM hypothesis testers (Balcerek and Burnecki 2020); Wood-Chan and DPW simulators | estimator on a series | MIT | **0.3.7, 2026-01-13** | **Yes, carefully.** Used here as an independent cross-check (section 3). `requires-python >= 3.13`; its own venv, never the desk's |
| 4 | [yujiading/fractals](https://github.com/yujiading/fractals) | the source repository of #3 - **the same project**, with tests and CI | estimator on a series | MIT | 2026-01-21, 56 commits, **0 stars** | as #3. Zero stars on the only genuinely useful item in the list |
| 5 | [comp-comb/StereoFractAnalyzer](https://github.com/comp-comb/StereoFractAnalyzer) | box-counting dimension of **STL meshes** and 2-D images, with voxel grids and z-contours | mesh/image analysis | MIT | 2024-04-03, pip `StereoFractAnalyzer` 1.0.0 | **No.** 3-D surfaces. Depends on `open3d` for a number this repo computes from a window |
| 6 | [mariodosreis/fractal](https://github.com/mariodosreis/fractal) | an **R** package that computes the Mandelbrot set for `image()` and plots the logistic map | renderer | MIT per `DESCRIPTION` (the `LICENSE` file is the R year/holder stub) | 2025-03-18, not on CRAN | **No.** A renderer whose name collides with the real estimators |
| 7 | [MarkSeufert/FractalRendererCpp](https://github.com/MarkSeufert/FractalRendererCpp) | interactive C++/OpenGL viewer for Mandelbrot, Julia and Burning Ship | renderer | **none stated** | 2021-04-30; the author's own topics include `wip-do-not-use` | **No**, and unusable anyway: no licence |
| 8 | [4031651/fractals](https://github.com/4031651/fractals) | TypeScript generator of IFS and L-system **point sets** for canvas drawing (a Barnsley fern) | renderer | MIT | 2020-11-04, 3 commits | **No.** Picture geometry |
| 9 | [abdulfatir/fractal-library](https://github.com/abdulfatir/fractal-library) | Java, Julia and Mandelbrot sets, IFS and a **Newton-Raphson fractal**; a one-sentence README and no usage example | renderer | MIT | **2014-07-10**, 3 commits in one day, 0 stars | **No.** Dead twelve years; a Newton fractal is the basin map of a root-finder |
| 10 | [txtatech/frac-crawl](https://github.com/txtatech/frac-crawl) | encodes **text** as coloured square images with a ledger and a JSON coordinate lattice | other - not fractal analysis | **no `LICENSE` file**; MIT asserted in README prose | 2023-07-17 | **No.** No estimator and no escape-time fractal; "fractal" is branding |
| 11 | [crapp/geomandel](https://github.com/crapp/geomandel) | C++ command-line escape-time renderer - Mandelbrot, Julia, Tricorn, Burning Ship - with image or CSV output | renderer | **GPL-3.0** | 2021-02-14, 45 stars (the most-starred item) | **No.** The best-engineered renderer here, and copyleft |
| 12 | [justinlubin/fractastic](https://github.com/justinlubin/fractastic) | C escape-time renderer of `z**d + c`, pixels to stdout | renderer | MIT | 2016-06-17, one week of work | **No** |
| 13 | [practical-engineer.ai, "Exploring Fractals with Python"](https://practical-engineer.ai/exploring-fractals-with-python-understanding-the-beauty-of-chaos/) | tutorial: `turtle` Sierpinski and Koch, a numpy Mandelbrot, a zoom video, six Julia plots | tutorial | n/a | 2023-06-17 | **No.** Drawing only. **Same source as #14** - the post is that repo's article |
| 14 | [PatrickKalkman/python-fractals](https://github.com/PatrickKalkman/python-fractals)| the example code for #13; `julia.py` renders Julia sets | renderer | MIT | 2023-06-18, 5 commits, 0 stars | **No.** Counted twice with #13 |
| 15 | [medium.com/@bekelet, "Fractals Using Python And Matplotlib"](https://medium.com/@bekelet/fractals-using-python-and-matplotlib-library-e264b858de23) | tutorial drawing a Koch snowflake and a Sierpinski triangle in matplotlib rather than `turtle` | tutorial | n/a | **page exists; Medium returns 403 to fetchers**, so the body was not read and the summary is from the search index - said here rather than implied | **No.** Drawing only |
| 16 | [wdeleon/fractPY](https://github.com/wdeleon/fractPY) | a **GPU benchmark** whose workload is Julia-set generation | renderer | **AGPL-3.0** | 2021-07-15, 4 commits in one day, 0 stars | **No.** The most restrictive licence in the list |
| 17 | [asinghgaba/fractpy](https://github.com/asinghgaba/fractpy) | **Newton fractals**: give it a polynomial as a string, get the root-basin plot | renderer | MIT | 2022-02-02, pip `fractpy` 0.0.4, readthedocs | **No.** The best-packaged renderer here - Sphinx docs, tests, CI - and it plots which root Newton's method converges to |
| 18 | [Fergus-OH/FractalPy](https://github.com/Fergus-OH/FractalPy) | Mandelbrot and Julia images and videos, numba-accelerated | renderer | MIT | 2023-01-23, pip `fractalpy` 0.1.1 | **No**, and **pinned to `>=3.10,<3.11`**, so it will not install on a current interpreter |

### What the survey settles

* **Seventeen of eighteen cannot be applied to a price series**, and not because
  they are low quality - #11 and #17 are well built. They solve a different
  problem. A renderer's input is a region of the complex plane; there is no
  argument to pass a price series to.
* **Three name collisions** are worth recording so a future reader does not pick
  the wrong one: `fractpy` (#16, an AGPL GPU benchmark), `fractpy` (#17, Newton
  basins) and `FractalPy` (#18, Mandelbrot video) are three unrelated projects,
  and `fractal`/`fractals` is both the estimator (#3, #4) and two renderers
  (#6, #8).
* **Licence hazards:** #7 and #10 have no licence file at all, #11 is GPL-3.0 and
  #16 is AGPL-3.0. None of these would be vendored into a public repository
  without a decision.
* **Only #3/#4 is alive.** Every other item's last activity is 2018 to 2025, and
  nine of them had fewer than six commits in total.
* **The estimators a desk would want are a day of work, not a dependency.**
  Higuchi's dimension, box counting on a graph, DFA, rescaled range and a
  structure-function exponent are each a log-log slope over a handful of scales;
  `research/harness/fractalest.py` is all five, vectorised over a rolling
  window, in 300 lines. What a library buys is an **independent implementation
  to disagree with**, which is section 3, and a **published generator** - and
  that is the part of #3 worth having.

---

## 2. The claim, and the ones it is distinct from

Most of the fractal family is already measured here, and most of it is closed.
This study would be a waste if it re-derived any of it:

| already measured | where | the answer |
|---|---|---|
| a Hurst exponent on the **level** | `inputs.py`, for years | 0.489 to 0.506 - a walk to three decimals, every instrument |
| DFA on **`|returns|`** | [fractal-twins.md](fractal-twins.md) | 0.67 to 0.84 against a walk's 0.528: volatility has long memory |
| the **multifractality** of returns | [statespace-fractals.md](statespace-fractals.md) | `lambda**2` of 0.076 traded against 0.001-0.010 on every control |
| a **ladder on log-volatility** | [statespace-fractals.md](statespace-fractals.md) | **+191 to +547 nats, 7 of 7 traded, 5 of 5 controls against** - and it then **fails its gate**: a 24-bar trailing standard deviation gives a narrower band at equal coverage, 1.933 against 1.999 |
| the **adverse excursion's** scaling exponent | [excursion-scaling.md](excursion-scaling.md) | fails all four pre-registered criteria; every real deviation from 0.5 is smaller than its own surrogate's |
| expansion from compression | [fractal-twins.md](fractal-twins.md) | AUC 0.73, already live as the spike switch |
| **levels, ranges and shapes** from topology | [topology.md](topology.md) | all null, all restatements of volatility |
| a swing sequence's multifractality | [statespace-fractals.md](statespace-fractals.md) | closed by an argument: a swing is a *sum*, and summing destroys multifractality |

Every row there is an **unconditional** statement - one exponent per instrument,
fitted over the whole series, reported as a property of the process. None asks
the question a desk asks. So the claim here, written as a sentence those studies
could not have tested:

> **A fractal estimator read on a trailing window, at a moment, carries
> information about the next few hours' direction, volatility or barrier race
> that survives holding trailing volatility fixed.**

and the specific folklore that makes the estimators interesting at all:

> **The sign of a momentum edge flips with the rolling Hurst exponent** - trade
> continuation when `H > 0.5`, reversion when `H < 0.5`.

The second is directional, and
[direction-is-closed](statespace-directional-edge.md) records the direction gate
finding a *planted* drift at z +2.90 while earning 2% of a spread. It is carried
anyway, for two reasons the method requires: it is the claim the fractal
literature actually makes, and it is a claim about a **conditional sign flip**
rather than an unconditional edge, which nothing above tests. The refuted
unconditional version is kept as the `base-always` arm in every cell, so if the
switch beats its null and the plain rule does not, that is evidence the
reframing was real.

### The expected answer, written before the run

`topology.md` found levels, ranges and shapes all null and all volatility
restatements. [candle-screen.md](candle-screen.md) prices the trap: AUC
**0.8052** on a Deriv volatility index, which holds its volatility constant by
construction so the true answer is 0.5, collapsing to **0.5250 within volatility
strata**. A fractal dimension is a volatility-structure statistic, so the
expected result is that every reading is a volatility restatement and the
**within-strata column is empty**. That is the valued outcome, and the verdict is
read from that column rather than from the pooled one.

**That prediction was half wrong, and the half that was wrong is the more useful
one.** The within-strata column is indeed empty for six of seven readings. But
they are *not* volatility restatements: the rank correlation between a fractal
reading and trailing volatility came back **-0.090 to +0.056**, against 0.633
for the trailing standard deviation with itself. Normalising each window by its
own amplitude and range - which is what `fractalest.py` does, and the reason it
does it - worked. So the right sentence is not "a fractal dimension is
volatility with a fractal's name on it" but **"a fractal dimension is a genuine
shape statistic of a price window, and a price window's shape carries almost
nothing"**. Left here as written rather than quietly updated, because a
prediction that was recorded and then missed is worth more than one edited to
match.

---

## 3. The cross-check against the library

Run with [`fractal_crosscheck.py`](../harness/fractal_crosscheck.py): 16,384
points, 8 draws, window 256. Both crossings, because an estimator written here,
nulled against a generator written here, read back by its author, is
self-confirming - a sign error shared between the two is invisible.

**A. This repo's estimators on the library's Wood-Chan paths.** `slope` is
`d(reading)/dH` over the ladder: 1.0 is a calibrated estimator, 0.0 a blind one.

| planted `H` | `dfa` | `rs` | `struct` |
|---|---|---|---|
| 0.30 | 0.3586 | 0.4283 | 0.2952 |
| 0.40 | 0.4456 | 0.5005 | 0.3896 |
| 0.50 | 0.5392 | 0.5754 | 0.4921 |
| 0.60 | 0.6320 | 0.6490 | 0.5921 |
| 0.70 | 0.7305 | 0.7174 | 0.6830 |
| **bias at 0.70** | **+0.0305** | **+0.0174** | **-0.0170** |
| **slope over the ladder** | **0.9303** | **0.7267** | **0.9782** |

**DFA and the structure-function exponent are calibrated against a generator
nobody here wrote** - slopes of 0.930 and 0.978, biases inside ±0.031. So the
nulls below are nulls of a working estimator and not of a broken one.

**Rescaled range is the weak member at slope 0.727**, which is the small-sample
upward bias the Anis-Lloyd correction exists for, visible here as compression
rather than as an offset: it over-reads low `H` and under-reads high `H`. It is
kept in the panel and its readings are discounted accordingly.

## 4. Cost, which is where most intraday ideas end

At the production stop - `Intent.stop_vol` has a median of **3.0** volatility
units - and the spread the terminal quoted on 2026-11-05. Cost in R is
`cost_px / risk` and is set by the stop, not the hold.

| instrument | bars | median vol | quoted | round trip in R | % of a 2R target | clears 0.16R |
|---|---|---|---|---|---|---|
| EURUSD | 294,499 | 0.00034 | 0.80 bps | 0.078 | 3.9% | yes |
| GBPUSD | 294,524 | 0.00039 | 0.84 | 0.071 | 3.6% | yes |
| USDJPY | 294,522 | 0.00038 | 0.78 | 0.069 | 3.5% | yes |
| AUDUSD | 294,533 | 0.00050 | 0.99 | 0.066 | 3.3% | yes |
| USDCAD | 294,517 | 0.00032 | 0.75 | 0.077 | 3.9% | yes |
| XAUUSD | 276,423 | 0.00066 | 0.91 | **0.046** | 2.3% | yes |
| **XAGUSD** | 278,207 | 0.00126 | **14.43** | **0.383** | 19.1% | **NO** |
| BTCUSD | 259,486 | 0.00203 | 4.40 | 0.072 | 3.6% | yes |
| Volatility 75 Index | 275,053 | 0.00396 | 0.40 | 0.003 | 0.2% | yes |
| Volatility 25 Index | 275,053 | 0.00133 | 1.35 | 0.034 | 1.7% | yes |
| Step Index | 260,917 | 0.00034 | 0.12 | 0.011 | 0.6% | yes |
| Jump 75 Index | 198,530 | 0.00507 | 1.17 | 0.008 | 0.4% | yes |

Two things to carry forward.

* **A 15-minute FX trade at a 3.0-unit stop is affordable**, at 3.3-3.9% of a
  2R target. This does **not** contradict [scalping.md](scalping.md)'s "FX is
  arithmetically dead at every clock from 1m to 15m": that study priced a
  **1xATR** stop, and cost in R is set by the stop. A three-times-wider stop is
  a three-times-cheaper trade in R. The geometry decides affordability, which is
  the whole content of `a-shorter-clock-multiplies-cost-in-r`.
* **XAGUSD is refused, and it was the instrument most likely to be mistaken for
  a result.** Its quoted spread is eighteen times EURUSD's. It is carried below
  only to show what a cell that should not have been measured looks like: its
  best switch cell reads **-0.1678R**, which is its spread and nothing else.
* **The six Deriv controls without a quoted spread are run gross**, and said so
  rather than priced off a guess. A result priced off an invented spread is the
  one result that looks like a measurement and is not.

## 5. Power: the test is not blind

[`fractal_rules.py`](../harness/fractal_rules.py) `PART=power`. A planted
fractional Brownian motion, 24 independent draws of 40,000 bars per exponent,
bars built from 20 aggregated path steps so a bar's high and low are the path's
own extremes, and each plant rescaled to a per-bar volatility of 4e-4 so the
series sits where FX sits.

Readings at width 128, mean over draws:

| planted `H` | higuchi | boxdim | dfa_ret | dfa_abs | rs | mf_hurst | mf_curv |
|---|---|---|---|---|---|---|---|
| 0.30 | 1.708 | 1.459 | 0.384 | 0.579 | 0.444 | 0.292 | 0.0100 |
| 0.40 | 1.593 | 1.384 | 0.476 | 0.555 | 0.525 | 0.400 | 0.0155 |
| **0.50** | **1.498** | **1.323** | **0.555** | **0.559** | **0.582** | **0.493** | **0.0213** |
| 0.60 | 1.398 | 1.262 | 0.646 | 0.576 | 0.660 | 0.597 | 0.0226 |
| 0.70 | 1.307 | 1.218 | 0.748 | 0.611 | 0.718 | 0.679 | 0.0259 |
| **separates from** | **0.20** | **0.20** | **0.20** | **0.20** | **0.20** | **0.20** | **0.20** |

* **Every estimator is monotone in `H` and separates `|H - 0.5| = 0.20` at
  `|z| > 2`.** The test is not blind, and the resolution is the same at all three
  widths.
* **Higuchi reads 1.498 at `H = 0.5`** against the textbook 1.5 for a walk, which
  is the one estimator here with an absolute anchor and it lands on it.
* **`dfa_ret` reads 0.555 and `rs` 0.582 at a true 0.5.** Both are biased
  **upward by 0.055 and 0.082** at this window length. This is why a textbook
  `H = 0.5` is not the null for any of these and why every reading below is
  judged against the same estimator run over a shuffle of the same series.

The rule's power, on the same plants, **gross** - a plant has no quoted spread
and inventing one would be the error that looks like a measurement. `*` marks a
mean more than two standard errors from zero:

| planted `H` | switch @128 | momentum always @128 |
|---|---|---|
| 0.30 | -0.2068* | -0.2377* |
| 0.40 | -0.0894* | -0.1385* |
| **0.50** | **+0.0033** | **+0.0106** |
| 0.60 | +0.1041* | +0.2545* |
| 0.65 | +0.1243* | +0.4013* |
| 0.70 | +0.2639* | +0.5915* |

**The rule resolves a planted exponent far more sharply than the estimators do.**
A persistence of `H = 0.60` is worth **+0.2553R a trade** to plain momentum -
three times the largest round trip in the cost table - and `H = 0.40` costs
0.1385R. At `H = 0.50` both arms are indistinguishable from zero, which is the
control that makes the rest of the column readable.

So **if these markets had a tradable Hurst exponent at 15 minutes, this harness
would have found it**, and the size it would have found is two to five times the
spread. That is the sentence the null in section 7 rests on.

One caveat, stated rather than buried: the **switch earns less than
always-momentum on every persistent plant** (+0.104 against +0.255 at `H = 0.60`).
A tercile split on a *globally* persistent series puts a third of its trades on
the reversion side by construction. The switch is built for an `H` that varies
in time, so this is the right behaviour on the wrong plant - and it means the
switch arm's power is the weaker of the two. The `base-always` arm is carried
through section 7 for exactly that reason.

## 6. The signal: direction is flat, and one of seven readings survives

[`fractal_rules.py`](../harness/fractal_rules.py) `PART=signal`. 8 traded
instruments and 10 Deriv controls at 15m, three widths, five arms, outcome
horizon 12 bars, **de-overlapped so no two outcomes share a bar**, volatility
quintiles fitted on the first half and scored on the rest.

Median over the 8 traded instruments. `vol` is the AUC for "is the next 12 bars'
realised move above the median", `dir` for "is it up", and `rank vs vol` is the
rank correlation between the reading and trailing volatility:

| arm | reading | vol pooled | **vol strata** | dir pooled | **dir strata** | rank vs vol |
|---|---|---|---|---|---|---|
| real | higuchi | 0.472 | 0.490 | 0.500 | 0.500 | -0.064 |
| real | boxdim | 0.476 | 0.494 | 0.501 | 0.500 | -0.090 |
| real | dfa_ret | 0.511 | 0.504 | 0.500 | 0.499 | 0.056 |
| real | dfa_abs | 0.488 | 0.481 | 0.499 | 0.499 | 0.005 |
| real | rs | 0.518 | 0.504 | 0.500 | 0.500 | 0.054 |
| **real** | **mf_hurst** | **0.526** | **0.524** | 0.500 | 0.500 | 0.034 |
| real | mf_curv | 0.506 | 0.496 | 0.500 | 0.500 | 0.033 |
| *real* | *trailing* | *0.724* | *0.615* | *0.502* | *0.499* | *0.633* |
| bar-shuffle | mf_hurst | 0.501 | 0.501 | 0.500 | 0.500 | -0.059 |
| block | mf_hurst | 0.484 | 0.495 | 0.499 | 0.500 | -0.070 |
| garch | mf_hurst | 0.498 | 0.499 | 0.499 | 0.499 | -0.061 |
| walk | mf_hurst | 0.500 | 0.500 | 0.503 | 0.504 | -0.041 |
| bar-shuffle | trailing | 0.503 | 0.503 | 0.500 | 0.500 | 0.258 |

**Direction is flat to three decimals.** Across all 40 arm-by-reading rows the
directional AUC sits between **0.497 and 0.504**, pooled and within strata,
real and null alike. There is no cell to chase. This is `direction-is-closed`
again, now through seven fractal estimators and three window lengths.

**The expected finding did not happen, and the real one is more interesting.**
The prior written before the run was that these would be volatility
restatements. They are not: the rank correlation between a fractal reading and
trailing volatility is **-0.090 to +0.056**, while `trailing` is 0.633 with
itself. Normalising each window by its own range and amplitude did what it was
supposed to do - these are genuinely shape statistics, nearly orthogonal to the
volatility level. **They are not volatility wearing a fractal's name; they are
simply empty.** Six of the seven collapse onto their own nulls once volatility
is held fixed.

**The one survivor is the structure-function Hurst.** `mf_hurst` reads 0.526
pooled and **0.524 within volatility strata**, where its i.i.d. bar-shuffle,
day-block shuffle, GARCH surrogate and Gaussian walk arms read 0.501, 0.495,
0.499 and 0.500. Per instrument, within strata:

| width | EURUSD | GBPUSD | USDJPY | AUDUSD | USDCAD | XAUUSD | XAGUSD | BTCUSD | agreeing |
|---|---|---|---|---|---|---|---|---|---|
| 64 | 0.449 | 0.437 | 0.516 | 0.508 | 0.465 | 0.490 | 0.494 | 0.493 | **2 of 8** |
| **128** | 0.535 | 0.524 | 0.548 | 0.532 | 0.547 | 0.531 | 0.531 | 0.543 | **8 of 8** |
| **256** | 0.534 | 0.524 | 0.547 | 0.521 | 0.531 | 0.525 | 0.521 | 0.539 | **8 of 8** |

and all ten Deriv controls read 0.479-0.521 at every width, including both
constant-volatility indices at 0.488-0.502 - a control that **must** come back
empty, coming back empty.

Three things keep this honest:

1. **It is a gating condition on the reach, not a free parameter.** At width 64
   the reading is null or inverted (2 of 8); at 128 and 256 it is 8 of 8. A
   claim that only holds past a window length is still a claim, and the window
   is observable, so this is reported as the condition it is -
   `a-regime-split-is-information-not-a-verdict`.
2. **It is small, and the incumbent is five times larger.** 0.024 of AUC against
   `trailing`'s 0.115 within the same strata, on the same target, in the same
   cells.
3. **It was never measured incrementally, which is the real limit.** Five
   volatility quintiles hold the volatility *level* roughly fixed; they do not
   prove this reading adds anything to a model that already has `trailing`. The
   honest next step is incremental AUC over the incumbent, and until that is run
   this is a reading worth **publishing as a feature and scoring on the record**,
   not a reading worth gating on. `publish-then-measure-then-gate` is the order
   and `fit-on-the-edge-not-the-raw-score` is why the AUC alone is not enough:
   fitted weights once beat hand-tuned ones 0.604 to 0.556 on AUC while **losing
   on edge, +0.002 against +0.019**.

Also worth recording, because it is a clean negative on a positive stylized
fact: **`mf_curv`, the rolling multifractality, is null.** The *global*
`lambda**2` is one of this desk's strongest cross-sectional facts - 0.076 traded
against 0.001-0.010 on controls ([statespace-fractals.md](statespace-fractals.md)).
Measured on a trailing window as a conditional reading it is 0.506 pooled and
0.496 within strata, with every null on 0.50. A stylized fact about a process is
not a signal about a moment.

## 7. The trade: the Hurst switch loses before it pays for the spread

[`fractal_rules.py`](../harness/fractal_rules.py) `PART=trade`. Entry at the
close, stop 3.0 volatility units, target **2x** the stop so a driftless walk
reaches it first exactly `1/3` of the time, marked out at 96 bars, **one
position at a time**, net of the quoted round trip. **9,072 cells**, of which
756 are the real arm's switch, over **2.2 million de-overlapped trades**.

| variant | arm | cells | trades | gross R | cost R | net R | 2:1 win rate |
|---|---|---|---|---|---|---|---|
| **switch** | real | 504 | 2,204,346 | **-0.0082** | 0.0809 | **-0.0891** | **0.3049** |
| switch | bar-shuffle | 504 | 2,769,527 | -0.0046 | 0.0662 | -0.0709 | 0.3212 |
| switch | block | 504 | 2,259,868 | -0.0044 | 0.0948 | -0.0992 | 0.3014 |
| inverted | real | 504 | 2,203,589 | -0.0074 | 0.0809 | -0.0883 | 0.3051 |
| **twin (a coin, same duty cycle)** | real | 504 | 2,444,898 | **-0.0071** | 0.0780 | -0.0851 | 0.3035 |
| base-always | real | 504 | 2,536,464 | -0.0142 | 0.0779 | -0.0921 | 0.3014 |

**The switch does not beat a coin, and it fails gross.** Its gross is -0.0082R
against the coin twin's **-0.0071R** at the same duty cycle on the same
instruments: the switch is *worse* than random sides, by less than its own
spread. There is no version of this where the cost is the problem - `net` is
-0.0891R against a cost of 0.0809R, so the whole loss is the spread plus a gross
that is already negative.

**Inverting the switch does not help**, at -0.0074R, which is the signature of a
reading that carries no sign: a rule with a real but backwards signal inverts to
a positive.

**The hit rate is below the arithmetic null and below its own shuffle.** 0.3049
against `1/(1+2) = 0.3333`, with the bar-shuffled arm at 0.3212 - closer to the
arithmetic value than the real series is. A 2:1 barrier race on these markets is
slightly *harder* than on a shuffle of their own bars, which is the fat tail and
the clustering doing what `no-gaussian-band-is-calibrated` describes, and it is
the opposite of what a tradable persistence would produce.

Per instrument, each row the **best of ~94 cells** for that instrument, with the
same cell's twin and shuffled arms beside it:

| instrument | reading | width | rule | n | net R | se | win | twin | shuffled |
|---|---|---|---|---|---|---|---|---|---|
| EURUSD | mf_curv | 128 | donch | 3,742 | -0.0200 | 0.0222 | 0.3239 | -0.0810 | -0.0814 |
| GBPUSD | higuchi | 128 | donch | 3,916 | -0.0362 | 0.0219 | 0.3220 | -0.0230 | -0.0645 |
| USDJPY | boxdim | 64 | mom1 | 5,052 | -0.0213 | 0.0201 | 0.3205 | -0.0570 | -0.0387 |
| AUDUSD | dfa_ret | 128 | donch | 4,293 | -0.0381 | 0.0205 | 0.3252 | -0.0802 | -0.0828 |
| USDCAD | rs | 128 | donch | 4,027 | -0.0441 | 0.0215 | 0.3223 | -0.1004 | -0.0526 |
| **XAUUSD** | boxdim | 256 | donch | 3,817 | **+0.0308** | 0.0240 | 0.3314 | -0.0460 | -0.0262 |
| *XAGUSD (refused on cost)* | dfa_ret | 64 | rev1 | 4,372 | -0.1678 | 0.0219 | 0.3175 | -0.2014 | -0.1725 |
| BTCUSD | rs | 256 | rev1 | 4,299 | -0.0299 | 0.0216 | 0.3133 | -0.0517 | -0.0898 |

**Seven of the eight traded instruments cannot find a positive cell even when
allowed to pick their best of ninety-four.** The one that can, XAUUSD at
+0.0308R, is +1.28 standard errors on a cell selected from ninety-four - which is
what the best of ninety-four looks like on a zero-mean surface.

**Benjamini-Hochberg over all 756 real-arm switch cells keeps 1 as profitable and
436 as losing.** 91 cells are nominally positive. This is the shape this desk
sees every time: a large nominally-positive count, one survivor, and hundreds of
survivors on the losing side.

**The four Deriv controls with a quoted spread read positive** - Jump 75 Index
+0.0547R, Volatility 75 +0.0265R, Step Index +0.0204R, Volatility 25 +0.0132R -
and that is not a finding, it is the cost table. Their round trips are 0.003 to
0.034R against FX's 0.066-0.078, so a gross wobble that FX pays away survives on
them. Their gross arms sit on zero like everything else. **A positive net on a
near-free instrument is a measurement of the spread, not of an edge** - which is
the mirror of why XAGUSD was refused.

### The volatility split, reported as a condition rather than a verdict

| volatility quintile of the entry bar | trades | net R |
|---|---|---|
| 1 (quietest) | 280,900 | -0.1588 |
| 2 | 332,567 | -0.1080 |
| 3 | 398,777 | -0.0933 |
| 4 | 492,249 | -0.0912 |
| 5 (busiest) | 699,853 | **-0.0481** |

Monotone, and **it is arithmetic rather than information.** The stop is 3.0
volatility units, so the risk in price grows with volatility while the spread
does not: cost in R falls as volatility rises. Every quintile is negative and the
best is still -0.0481R. There is no band to gate into - which is the useful form
of this answer, because a monotone net against volatility is exactly what an
idea looks like shortly before someone proposes trading only the top quintile.

---

## 8. The scripts, and how to run them

Each module's docstring leads with its own invocation line and states what would
make its comparison a lie; this section is the index, not a copy.

| script | what it measures or protects |
|---|---|
| [`research/harness/fractalest.py`](../harness/fractalest.py) | the estimators themselves: Higuchi dimension, box counting on the price graph, DFA, rescaled range, the structure-function exponent and its curvature, plus an exact Davies-Harte fractional Brownian motion and the bar builder that gives a generated bar the path's own high and low. Every function takes a strided `(windows, width)` panel whose **last column is the bar the reading is for**, so there is no look-ahead |
| [`research/harness/fractal_rules.py`](../harness/fractal_rules.py) | the study: the cost screen, the power curve, the signal measurement pooled and within volatility strata, and the barrier-race trade with its duty-cycle twin and shuffled arms |
| [`research/harness/fractal_crosscheck.py`](../harness/fractal_crosscheck.py) | whether this repo's estimators and generator agree with `fractal-analysis`'s, in **both** directions, so that neither is confirming itself |
| [`tests/test_fractal_estimators.py`](../../tests/test_fractal_estimators.py) | that each estimator can still separate the shapes it is supposed to separate - a line from a walk from noise, a planted exponent from its neighbour, a monofractal from a cascade - and that it is blind to amplitude, aligned across chunk boundaries, and silent rather than inventive on a window that never moved |

### Running them

The study, on the lab, detached. `PART` is one of `cost`, `power`, `signal`,
`trade` or `all`:

```sh
./.secrets/lab.sh sync
./.secrets/lab.sh exec 'cd $HOME/till_infinity && nohup env OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PART=all WORKERS=14 \
    SEQLAB=$HOME/till_infinity/data/seqlab SYN=$HOME/till_infinity/data/syn \
    PYTHONPATH=$HOME/till_infinity/repo \
    $HOME/till_infinity/.venv/bin/python -u \
    repo/research/harness/fractal_rules.py > logs/fractal_rules.log 2>&1 &'
./.secrets/lab.sh log fractal_rules
```

The cross-check needs **its own venv**, because `fractal-analysis` requires
Python 3.13 and the lab's default interpreter for scripts is not it:

```sh
./.secrets/lab.sh exec '$HOME/.local/bin/uv venv --python 3.13 $HOME/till_infinity/.venv-fractal'
./.secrets/lab.sh exec '$HOME/.local/bin/uv pip install \
    --python $HOME/till_infinity/.venv-fractal/bin/python fractal-analysis'
./.secrets/lab.sh exec 'cd $HOME/till_infinity && PYTHONPATH=$HOME/till_infinity/repo \
    $HOME/till_infinity/.venv-fractal/bin/python -W ignore -u \
    repo/research/harness/fractal_crosscheck.py'
```

The tests run with the suite, locally or on the lab, and take under a second:

```sh
uv run pytest tests/test_fractal_estimators.py -q
```

**The suite, for a reviewer who was not in the room.** Run on the lab from inside
the synced tree, `$HOME/till_infinity/.venv/bin/python -m pytest tests -q`:

| | passed | skipped | deselected |
|---|---|---|---|
| this branch's tree **without** `test_fractal_estimators.py` | **3,035** | 7 | 12 |
| `test_fractal_estimators.py` alone | **21** | 0 | 0 |
| **this branch, whole suite** | **3,056** | 7 | 12 |

3,035 + 21 = 3,056, so every added test is accounted for and nothing else moved.
**The baseline is 3,035 and not the 3,022 quoted to me**, because the tree this
ran in was copied from the main checkout after another session had already added
thirteen tests of its own; the difference is not this branch's and the
without-my-file row is the number to compare against.

**Two notes on getting code onto the lab**, both of which cost a run here.
`lab.sh exec 'cat > file'` **does not forward stdin**: all three files arrived
**empty**, with the md5 of an empty file, and `lab.sh run` would have printed
"launched" over them. And `lab.sh sync` is `rsync --delete`, so any *other*
session's sync removes a file pushed by hand - which is what happened on the
second attempt, with the run dying on `No such file or directory`. Files are
therefore pushed base64-encoded inside the command string and **verified by md5
against the local copy** before anything is launched, into a private
`repo-fractal` tree that a sync does not touch.

### How to read the output, and what the gates are

* **A. Cost** - one row per instrument. The verdict column is `clears 0.16R`;
  anything reading `NO` is refused unmeasured rather than measured and reported
  as a loss. Cost in R is `cost_px / risk` and `risk = 3.0 x` the trailing
  volatility estimate, so it is set by the stop and not the hold.
* **B. Power** - per width, the estimator's reading against the planted `H`, then
  the smallest `|H - 0.5|` it separates at `|z| > 2`. **The reading column must
  be monotone in `H`**; if it is not, the generator is wrong, not the estimator
  (it was, once - see below). The last table is the rule's gross R on the same
  plants, and a `*` marks a mean more than two standard errors from zero.
* **C. The signal** - `pooled -> within strata`. **The second number is the
  verdict.** The arm table beneath it is the same statistic for the shuffled,
  block-shuffled, GARCH and walk arms: a real reading that its own `bar-shuffle`
  twin matches is the estimator's bias, not the market.
* **D. The trade** - the per-instrument row carries the best switch cell **and
  the same cell's twin and shuffled arms**, which is the comparison that
  matters; a switch beating zero while matching its twin has bought a lower duty
  cycle. Then the Benjamini-Hochberg count over every real-arm cell, the pooled
  `gross / cost / net` decomposition, and net by volatility quintile.

### The data, and how to rebuild it

All of it is on the lab and none of it is in the repository.

| what | where | how to rebuild |
|---|---|---|
| 8 traded instruments at 15m, 198,530-294,533 bars | `$HOME/till_infinity/data/seqlab/<SYMBOL>.15m.npz` | `./.secrets/lab.sh run research/harness/seqcache.py`, which is resumable and skips what is on disk |
| 10 Deriv synthetic controls at 15m, 49,996 bars each | `$HOME/till_infinity/data/syn/<Name>.15m.npz` | the same cache, from `seqlab.SYNTHETIC` |
| the planted fractional Brownian motions | generated in-process from a `sha256` seed per cell | nothing to rebuild; `fractalest.fbm` is exact and `seeded()` makes a cell reproducible. **Not `hash()`**, which is salted per process and has broken four harnesses here |

Each `.npz` carries `time, open, high, low, close, volume, spread`. **`spread` is
a count of the broker's points, not a price**, and this study does not use it:
costs are charged at the spread the terminal *quoted* on 2026-11-05, because the
stored column reads 3.3-8.3x below it on FX and 6.5x above it on
`Volatility 75 Index`.

---

## 9. The bugs this found in itself

Recorded because a study that drops its own off-by-one is worth less than one
that reports it, and because two of these would have produced a publishable
wrong answer.

1. **A floored moment made the multifractal reading a unit artefact.**
   `structure_scaling` takes `mean |increment|**q`. On a log-price series whose
   15-minute increments are 4e-4 the `q = 4` moment is **2.6e-14**, below the
   1e-12 floor guarding the logarithm - so the floor, not the market, set the
   answer. The same planted series read a curvature of **0.019** on a wide
   amplitude and **0.188** on a realistic one, and real FX sits on the clamped
   side, so every market reading would have been the clamp. Fixed by normalising
   each window by its own one-step scale, which is free: dividing a window by a
   constant shifts `log S_q(s)` by `-q log c` at every `s`, so the slope in
   `log s` cannot move. **Caught by a scale-invariance test, not by inspection** -
   the number looked perfectly reasonable.
2. **The plant was on the wrong scale and it looked like estimator breakdown.**
   A fractional Brownian path grows as `N**H`, so a fixed multiplier that suited
   `H = 0.30` put the log price across a span of 137 at `H = 0.70`. Every window
   was then a near-deterministic ramp and the estimators said so faithfully:
   Higuchi read **1.01 at H = 0.65 and 0.58 at 0.70** - the dimension of a
   straight line - after falling monotonically from 1.71 to 1.38 across `H` of
   0.30 to 0.60. Read as an estimator property this is "the estimators break down
   above 0.6"; it was the generator. Fixed by rescaling the increments to a fixed
   per-bar volatility, which leaves `H` alone.
3. **Higuchi's dimension was exactly 1.0 too low**, from a missing factor of `k`
   in the normalisation: a line read 0.0, a walk 0.495 and white noise 0.998.
   Every value was plausible for a quantity whose whole range is 1 to 2. Only the
   three textbook anchors - 1 for a line, 1.5 for a walk, 2 for noise - catch it.
4. **The chunked reading loop returned one extra window per chunk.** A
   294,499-bar feed produced 36,809 readings for 36,805 window ends. It fits in
   one chunk on any short series, so it passed every local test and died on the
   lab as an `IndexError` four chunks in - not as a wrong number, which is the
   only lucky part.
5. **Rescaled range returned all-NaN at the shortest window.** At `width // 4` a
   64-bar window affords only the scales {8, 16}, and two points fit a line
   exactly, so the function returned NaN for every window and printed a `nan`
   column in the power table with no error raised.
