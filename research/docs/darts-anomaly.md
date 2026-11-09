# darts' anomaly scores are volatility, their clusters are volatility bins, and a block shuffle reproduces the whole transition matrix

**Measured 2026-11-09 on the lab with
[`dartsad_run.py`](../harness/dartsad_run.py) over
[`dartsad.py`](../harness/dartsad.py), against commit `de363bdc`.** darts
0.41.0 (`u8darts`) and pyod 3.6.7 in a venv of their own. Twenty-four
instruments at 15 minutes - ten FX pairs, XAU, XAG, BTC and ten Deriv feeds -
with 20,000 to 200,000 bars each, scorers fitted on the first 60% by time and
every number read on the last 40%.

The operator's brief, verbatim: *"https://github.com/unit8co/darts / Anomaly
detection, get anomaly scores / Apply clustering to them too, and state
transitions."*

## Verdict

| question | answer |
| --- | --- |
| **darts' own default** | **`window_agg=True` is a look-ahead of `window - 1` bars, and it is the default on every window scorer.** On a 40-bar probe with one spike at bar 20, `KMeansScorer(window=5)` reads 2.40, 4.23, 6.06, 5.95 at bars 16-19 - **a rise of +5.49 before the spike exists**. With `window_agg=False` it reads a flat 0.57 to bar 19 and 9.73 from bar 20. `WassersteinScorer` rises +1.20 against +0.00. Any forward-looking label scored against the default reads its own answer out of the feature |
| **1. do the scores carry anything** | **no window scorer beats the incumbent inside volatility strata.** For a shock in the next 4 bars, pooled FX within-strata AUC: incumbent `lvol` **0.589**, `kmeans10` 0.551 (better on **1 of 10** pairs), `wass10` 0.543 (1 of 10), `iforest10` 0.528 (**0 of 10**), `kmeans1` 0.579 (2 of 10). The one column that does beat it - **`norm` at 0.612, better on 9 of 10** - is `NormScorer`, which has no model in it: it is the L1 size of the current bar |
| **1b. the open regression frame** | **+0.0005 to +0.0455 of out-of-sample R2 on forward log variance, and it shrinks as the baseline improves.** Largest where the baseline is weakest (EURGBP +0.0455 on a base of 0.164) and **negative on the two best baselines** (XAGUSD -0.0059 on 0.757, XAUUSD -0.0058 on 0.660). The shuffled-score control reads -0.0035 to +0.0007, so the gain is real and small - an order of magnitude under the +0.21 to +0.24 that [`changepoint-increment.md`](changepoint-increment.md) measured in the same frame |
| **2. clustering the scores** | **volatility bins with new names.** Mean `trpct` by state is monotone on every real feed (0.38 / 0.70 / 0.94 / 0.86 on EURUSD), NMI against `trpct` deciles is 0.120-0.165 against a shuffled baseline of 0.000-0.004, and the state label's AUC for forward volatility in the top third goes **0.545-0.618 raw to 0.488-0.541 within strata** |
| **3. state transitions** | **significant, and entirely reproduced by a volatility-matched null.** De-overlapped at the scorer window, traded feeds read a stay-share excess of +0.039 to +0.115 at permutation p 0.000. The i.i.d. whole-bar shuffle reads -0.007 to +0.011. **A 200-bar block shuffle reads +0.039 to +0.107 - the same numbers**: AUDUSD +0.039 against +0.039, EURUSD +0.088 against +0.090, GBPUSD +0.088 against +0.090. And quartiles of the incumbent `trpct`, with no darts in them at all, read +0.192 to +0.375 |
| **does a transition precede anything** | **no. 260 (instrument, from, to) cells, 25 with a 90% interval clear of zero against 26.0 expected by chance, 0 survive Benjamini-Hochberg** |
| **the trade** | **no. 234 (instrument, transition, side) barrier races: 4 with a 90% lower bound above zero against 11.7 expected at 5%, and 121 of 234 beat their own random twin against 117 expected by chance.** A coin |
| **power** | the transition test sees a planted volatility regime from a **1.25x** vol ratio and is blind at 1.10x; it sees a persistence of 0.9 and is blind at 0.8. It **never** sees a planted drift regime - ARI -0.000 to +0.000 at every strength to **1.0 sigma a bar**, which is the drift the `Drift Switch` feeds actually carry |
| **why direction is structurally absent** | **an anomaly score is a distance, and a distance has no sign.** Every scorer here returns a norm, so the clustering cannot represent "mostly up"; the planted-drift blindness is not a sample-size result |

**This reduces to a regime/volatility restatement, which the brief named as a
closed family, so it stops here.** The by-product worth keeping is the
`window_agg` leak, which is a defect in a dependency rather than a finding
about markets.

## Why this was not already answered

Three adjacent claims are settled here and this is distinct from all three.

| the closed claim | where | why this is a different sentence |
| --- | --- | --- |
| statespace's filtered log variance, predictive spread, band width and innovation add to the anomaly incumbents | [`statespace-anomaly.md`](statespace-anomaly.md) | those are four published model outputs; these are five unsupervised novelty scores with no forecasting model behind them, and the question here extends past AUC into a state sequence |
| a **Wasserstein drift between consecutive windows** works as a regime gate | [`statespace-regime-gates.md`](statespace-regime-gates.md) | that statistic compares a window with its neighbour and is scored as a tercile gate against random subsets. `WassersteinScorer` compares each window with a *fitted training distribution* and is read here as one component of a clustered state, not as a gate. The refuted form is kept as an arm: `wass10` |
| an AUC on a volatility-shaped target is free | [`candle-screen.md`](candle-screen.md) | not a thing to re-open: it is the reason every table below is printed twice and read only on the second column |

[`anomalies.md`](anomalies.md) is the incumbent this is measured against -
shocks and range blowouts at AUC 0.76-0.81 an hour or more ahead - and its two
carrying features, the 14-bar EWMA of true range over its 500-bar mean (`lvol`)
and that EWMA's percentile in 1,500 bars (`trpct`), are used verbatim so the
comparison is not about a re-derivation.

## The defect found before any result: darts' `window_agg` default

Every window scorer in `darts.ad.scorers` takes `window_agg`, and it defaults
to **`True`**. That spreads each window's score back across every bar the
window touches and averages, so the score at bar `t` is a function of windows
that *start* at `t` and run to `t + window - 1`.

One spike at bar 20, window 5, score at bars 15-24:

| scorer | `window_agg` | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | rise before the spike |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `KMeansScorer` | **True** | 0.57 | 2.40 | 4.23 | 6.06 | 5.95 | 7.78 | 5.95 | 4.12 | 2.29 | 2.40 | **+5.49** |
| `KMeansScorer` | False | 0.57 | 0.57 | 0.57 | 0.57 | 0.57 | 9.73 | 9.73 | 9.73 | 0.00 | 9.73 | +0.00 |
| `WassersteinScorer` | **True** | 0.25 | 0.55 | 0.85 | 1.15 | 1.45 | 1.75 | 1.45 | 1.15 | 0.85 | 0.55 | **+1.20** |
| `WassersteinScorer` | False | 0.25 | 0.25 | 0.25 | 0.25 | 0.25 | 1.75 | 1.75 | 1.75 | 1.75 | 1.75 | +0.00 |

With the default on, a 4x bar four bars ahead is already in the feature. Every
scorer in this study is built with `window_agg=False`, which stamps a window's
score at its **last** bar and makes it a function of bars `t - window + 1 .. t`
and nothing later. `PHASE=leak` reprints the table above.

This is worth more than the market result. It is a dependency whose default
setting silently inverts the leak boundary of any supervised use, and nothing
in the output says so.

## What was run

**Data**, from the lab's own cache, bar counts as served and reported per
instrument because they differ by a factor of ten:

| family | instruments | bars at 15m | test rows |
| --- | --- | --- | --- |
| fx | EURUSD, GBPUSD, AUDUSD, USDCAD, USDJPY | 60,000 (200,000 in the deep pass) | 23,975 |
| fx | NZDUSD, USDCHF, EURJPY, GBPJPY, EURGBP | 20,000 - all the cache holds | 7,975 |
| metal, crypto | XAUUSD, XAGUSD, BTCUSD | 60,000 (200,000 deep) | 23,975 |
| **sigma constant by publication** | Volatility 25, Volatility 75 | 60,000 | 23,975 |
| **anomaly timing published memoryless** | Jump 75, Step Index, Boom 500, Crash 500 | 49,996-60,000 | 19,974-23,975 |
| **positive: a planted drift regime** | Drift Switch 10, 20, 30 | 49,996 | 19,974 |
| **positive: a range by construction** | Range Break 100, 200 | 49,996 | 19,974 |

The Deriv feeds are **real markets scored as served**, which is this desk's
standing rule; each is a control for **one named property only**, and the
property is in the table. [`range-break-100.md`](range-break-100.md) and
[`generators.md`](generators.md) are where those properties were established.

**Five scorers**, all through darts:

| arm | what it computes |
| --- | --- |
| `norm` | `NormScorer(ord=1)` against a zero forecast: the L1 size of the bar. No model in it, and it is here so the incumbent-in-disguise can be seen rather than assumed |
| `kmeans1` | `KMeansScorer(window=1, k=8)`: distance from the bar to its nearest of eight centroids |
| `kmeans10` | `KMeansScorer(window=10, k=8)`: the same over a ten-bar window |
| `wass10` | `WassersteinScorer(window=10)`: Wasserstein distance from the window's values to the training distribution |
| `iforest10` | `PyODScorer(IForest(100), window=10)`. `KNN` was the brief's likelier reading and was dropped: it scores each window against every training point, which is the same quadratic cost as Wasserstein twice over |

**Two feature sets.** `scaled` is `[r/base, range/mean_range, clv]` with `base`
the trailing 500-bar mean absolute return **shifted one bar**, so the
volatility level is divided out and anything found is bar shape. `raw` is
`[r, range]` in log price. The pair exists because a scorer fed raw returns is a
volatility detector with a new name.

**One position, one observation.** State sequences are sampled every 10 bars -
the scorer window - so two consecutive observations share no bar, and the
barrier race refuses any candidate inside an open position. A stride-1
transition matrix would count the same bars ten times and report the overlap as
persistence; [`anchored-states.md`](anchored-states.md) de-overlaps for the same
reason, after a short skip rule with a long forward window gave a direction AUC
of 0.79 that collapsed to 0.51.

**Whether it would have bitten here is measured, not assumed.**
[`anticipating.md`](anticipating.md) checked the same trap at a 4h horizon and
found spaced and overlapped entries differing by **≤0.005 on every feature**, so
"overlap leaks" is not a law. The column that settles it for this study is the
i.i.d. whole-bar shuffle in Q3: it reads -0.007 to +0.011 at stride 10, and a
stride-1 sequence is what that column exists to rule out.

**Three nulls, each through the same clustering on the same bar geometry:** a
whole-bar shuffle (marginals exact, all order gone - the i.i.d. control), a
200-bar block shuffle (volatility clustering survives inside a block, long-range
order does not - the volatility-matched control), and quartiles of `trpct` with
no darts in them at all.

## Q1: the only scorer that beats the incumbent has no model in it

Within-strata AUC for a shock in the next 4 bars, pooled by family, with the
count of instruments on which the column beats `lvol`. Raw AUC is in the log and
carries no claim.

| family | feeds | `lvol` | `trpct` | `norm` | `kmeans1` | `kmeans10` | `wass10` | `iforest10` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fx | 10 | 0.589 | 0.520 / 0 | **0.612 / 9** | 0.579 / 2 | 0.551 / 1 | 0.543 / 1 | 0.528 / **0** |
| metal | 2 | 0.603 | 0.526 / 0 | **0.622 / 2** | 0.584 / 0 | 0.581 / 0 | 0.534 / 0 | 0.563 / 0 |
| crypto | 1 | 0.614 | 0.535 / 0 | 0.605 / 0 | 0.574 / 0 | 0.598 / 0 | 0.556 / 0 | 0.595 / 0 |
| **sigma constant** | 2 | 0.428 | 0.484 | 0.516 | 0.519 | 0.496 | 0.534 | 0.501 |
| **memoryless jumps** | 1 | 0.475 | 0.491 | 0.499 | 0.504 | 0.534 | 0.511 | 0.531 |
| **bounded coin** | 1 | 0.476 | 0.532 | 0.548 | 0.512 | 0.493 | 0.483 | 0.505 |
| boom/crash | 2 | 0.535 | 0.508 | 0.506 | 0.504 | 0.518 | 0.521 | 0.522 |
| **range by construction** | 2 | 0.507 | 0.500 | 0.519 | 0.506 | 0.521 | 0.526 | 0.521 |

The range target says the same thing: fx `lvol` 0.577 against `norm` 0.594 on 7
of 10, `kmeans1` 0.571 on 5, `kmeans10` 0.542 on 2, `wass10` 0.540 on 1,
`iforest10` 0.524 on 2.

**Read the `norm` column as what it is.** `NormScorer` against a zero forecast
is `|r|/base + range/mean_range + |clv|` - the current bar's size relative to
the recent scale. It beats a 14-bar EWMA inside percentile strata because the
incumbent is smoothed over fourteen bars and the last bar is not in it. That is
a small, real statement about the incumbent being over-smoothed for this label,
and **it is not a statement about anomaly detection**: there is no model, no
fit, and no window.

**The window scorers are below the incumbent nearly everywhere.** The deliberate
removal of the volatility level helps them slightly - `kmeans10` on fx reads
0.551 on `scaled` against 0.516 on `raw` - and does not change the answer.

**The controls behave.** Every family whose anomaly timing is published
memoryless sits within 0.48-0.55 on every column, which is what makes the table
worth reading. The `sigma constant` row's `lvol` at 0.428 is 137 events on
23,975 rows and is noise, not a reversal.

## Q1b: the regression frame, where the gain is real and an order of magnitude too small

`statespace-anomaly.md` closed the classification frame and left the regression
one open: forecasting the **level** of log variance is where a better filter was
worth +0.21 to +0.24 R2. So: out-of-sample R2 on the mean squared return over
the next 20 bars, baseline `llevel + lvol + trpct + volvol`.

**The level is in the baseline on purpose.** Both incumbents are scale-free - a
ratio and a percentile - and a baseline of those two alone read an R2 of
**0.0221** on EURUSD against 0.3596 with the level. A delta measured against
the scale-free pair would have been a delta against a straw man, and would have
read about three times larger.

| instrument | base R2 | + scores | delta | scores alone | **+ shuffled scores** |
| --- | ---: | ---: | ---: | ---: | ---: |
| EURGBP | 0.1641 | 0.2096 | **+0.0455** | 0.0501 | +0.0001 |
| USDCAD | 0.2168 | 0.2496 | **+0.0328** | 0.0645 | +0.0005 |
| GBPUSD | 0.2498 | 0.2712 | +0.0214 | 0.0651 | -0.0001 |
| USDCHF | 0.1325 | 0.1524 | +0.0199 | 0.0547 | -0.0035 |
| EURUSD | 0.3596 | 0.3721 | +0.0126 | 0.0487 | -0.0003 |
| BTCUSD | 0.4264 | 0.4344 | +0.0081 | 0.1407 | -0.0003 |
| EURJPY / GBPJPY / AUDUSD / USDJPY / NZDUSD | 0.339 / 0.288 / 0.355 / 0.621 / 0.169 | | +0.0066 / +0.0064 / +0.0056 / +0.0036 / +0.0033 | | +0.0007 to -0.0010 |
| **XAUUSD** | **0.6600** | 0.6542 | **-0.0058** | 0.0177 | -0.0000 |
| **XAGUSD** | **0.7574** | 0.7515 | **-0.0059** | 0.0151 | -0.0000 |
| every control feed | -0.005 to 0.113 | | **-0.0015 to +0.0010** | -0.001 to 0.001 | -0.0012 to +0.0003 |

**The shuffled-score column is the one that makes the delta mean anything.**
Five extra regressors always fit better in sample; shuffled through the same
scorers they add -0.0035 to +0.0007 out of sample, so the positive deltas are
not a parameter count.

**And the delta is a function of how bad the baseline is.** It is largest where
the baseline is weakest (EURGBP, base 0.164) and negative on the two strongest
(XAG 0.757, XAU 0.660). That is the signature of a partial substitute rather
than new information, and the ceiling - +0.046 on one 20,000-bar pair - is an
order of magnitude under the +0.21 already measured in this frame from a
changepoint model's predictive scale.

**Caveat, stated rather than buried:** the baseline is four incumbent columns,
not the 48-lag ridge that +0.21 was measured on. A richer incumbent would
absorb more of this, so **+0.046 is an upper bound, not an estimate**.

## Q2: the clusters are volatility bins

k-means, k=4, on the standardised five-score vector, fitted on the train block,
states relabelled quietest-first.

| instrument | state shares | mean `trpct` by state | NMI vs `trpct` | shuffled | shock AUC raw/strata | **forward vol top third raw/strata** |
| --- | --- | --- | ---: | ---: | --- | --- |
| EURUSD | 0.70 / 0.24 / 0.04 / 0.02 | 0.39 / 0.72 / 0.95 / 0.86 | 0.146 | 0.001 | 0.678 / 0.564 | 0.607 / **0.529** |
| GBPUSD | 0.69 / 0.25 / 0.04 / 0.02 | 0.38 / 0.71 / 0.94 / 0.84 | 0.151 | 0.001 | 0.672 / 0.563 | 0.606 / **0.537** |
| USDCAD | 0.68 / 0.25 / 0.05 / 0.02 | 0.38 / 0.71 / 0.94 / 0.86 | 0.161 | 0.000 | 0.703 / 0.588 | 0.591 / **0.541** |
| USDJPY | 0.69 / 0.24 / 0.05 / 0.02 | 0.38 / 0.66 / 0.91 / 0.79 | 0.128 | 0.002 | 0.657 / 0.575 | 0.578 / **0.508** |
| XAUUSD | 0.71 / 0.22 / 0.03 / 0.04 | 0.38 / 0.70 / 0.78 / 0.92 | 0.131 | 0.001 | 0.665 / 0.588 | 0.548 / **0.491** |
| BTCUSD | 0.72 / 0.22 / 0.05 / 0.00 | 0.37 / 0.70 / 0.92 / 0.89 | 0.144 | 0.001 | 0.680 / 0.588 | 0.588 / **0.509** |
| EURGBP | 0.54 / 0.34 / 0.08 / 0.03 | 0.35 / 0.66 / 0.91 / 0.77 | 0.165 | 0.001 | 0.685 / 0.596 | 0.569 / **0.528** |
| Volatility 25 / 75 | 0.38 / 0.29 / 0.21 / 0.12 | 0.32 / 0.56 / 0.57 / 0.79 | 0.097 | 0.001 | 0.527 / 0.543 | 0.505 / 0.508 |
| Drift Switch 10 / 20 / 30 | ~0.25 / 0.30 / 0.28 / 0.16 | 0.28 / 0.48 / 0.56 / 0.77 | 0.078-0.104 | 0.001 | too rare | 0.506-0.511 / 0.501-0.509 |
| Range Break 100 / 200 | 0.54-0.65 / 0.22-0.28 / 0.07-0.08 / 0.06-0.09 | 0.33-0.36 / 0.65-0.72 / 0.73-0.92 / 0.79-0.90 | **0.193 / 0.202** | 0.001 | 0.507 / 0.502-0.513 | 0.502-0.504 / 0.503-0.506 |

Three readings:

**The shape is one big quiet state and three rare loud ones.** 0.68-0.73 of
bars in state 0 on every real feed. k-means on heavy-tailed scores puts the
extremes in their own tiny clusters, so the transition matrix is mostly the big
state's self-loop, and several of its sixteen cells never reach 60
observations.

**The states are ordered by volatility percentile and know nothing else about
it.** The last column is the decisive one: the state label ranks forward
volatility in the top third at 0.545-0.618 raw and **0.488-0.541 inside deciles
of the volatility percentile it is a copy of.** That is the answer to "are the
clusters volatility bins with new names" and the answer is yes.

**NMI does not say the clusters are *nothing but* volatility - 0.12 to 0.17
against a shuffled 0.00 - and it is the wrong statistic to lean on.** It says
they share information with the volatility decile, and the within-strata AUC
says what the remainder is worth, which is 0.5. Highest NMI in the table is
`Range Break`, at 0.19-0.20, a feed whose range is a construction.

## Q3: the transition matrix is volatility clustering, and the block shuffle says so

De-overlapped at stride 10. `stay` is the share of consecutive disjoint
observations in the same state; `indep` is what the same marginals give, because
a state holding 70% of the bars stays 70% of the time by arithmetic. `p` is a
label permutation holding the marginals exactly. From the deep pass - 200,000
bars and 7,998 observations on the five deep majors, metals and crypto.

| instrument | obs | stay | indep | **excess** | p | i.i.d. shuffle | **block shuffle** | `trpct` quartiles |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSD | 7,998 | 0.593 | 0.478 | **+0.115** | 0.000 | +0.005 | **+0.087** | +0.375 |
| EURUSD | 7,998 | 0.553 | 0.465 | **+0.088** | 0.000 | -0.004 | **+0.090** | +0.268 |
| GBPUSD | 7,998 | 0.548 | 0.459 | **+0.088** | 0.000 | -0.006 | **+0.090** | +0.259 |
| USDCAD | 7,998 | 0.569 | 0.488 | **+0.081** | 0.000 | -0.005 | **+0.069** | +0.260 |
| USDJPY | 7,998 | 0.540 | 0.475 | **+0.065** | 0.000 | -0.002 | **+0.063** | +0.304 |
| XAUUSD | 7,998 | 0.557 | 0.499 | **+0.059** | 0.000 | +0.001 | **+0.062** | +0.269 |
| XAGUSD | 7,998 | 0.519 | 0.472 | **+0.047** | 0.000 | +0.004 | **+0.053** | +0.237 |
| AUDUSD | 7,998 | 0.509 | 0.469 | **+0.039** | 0.000 | -0.001 | **+0.039** | +0.247 |
| GBPJPY / EURJPY / EURGBP / USDCHF | 798 | | | +0.089 / +0.084 / +0.059 / +0.046 | 0.000 | -0.001 to +0.011 | +0.046 to +0.107 | +0.192 to +0.370 |
| NZDUSD | 798 | 0.450 | 0.444 | +0.006 | 0.150 | -0.007 | +0.050 | +0.258 |
| **Volatility 25 / 75** | 7,998 | | | **+0.003 / -0.005** | 0.090 / 0.084 | -0.001 / +0.007 | -0.009 / -0.003 | **+0.115 / +0.131** |
| **Drift Switch 10 / 20 / 30** | 1,998 | | | **-0.013 / -0.007 / -0.009** | 0.068 / 0.406 / 0.442 | -0.004 | -0.006 / -0.004 / +0.009 | +0.130 to +0.136 |
| Jump 75 / Step | 7,998 | | | -0.005 / -0.002 | 0.608 / 0.824 | +0.007 / +0.003 | -0.005 / +0.002 | +0.122 / +0.138 |
| Range Break 100 / 200 | 1,998 | | | +0.011 / +0.005 | 0.532 / 0.424 | -0.001 / +0.000 | -0.007 / +0.011 | +0.121 / +0.139 |

**The i.i.d. shuffle is clean, so the de-overlap works.** -0.007 to +0.011
across twenty-four feeds. A stride-1 sequence would have manufactured
persistence out of window overlap and this column is the proof it did not.

**The block shuffle reproduces the entire effect.** A 200-bar block shuffle
keeps volatility clustering inside a block and destroys every longer-range
relation, and it reads +0.039 to +0.107 against the real +0.039 to +0.115 -
equal on AUDUSD to three decimals, equal on EURUSD and GBPUSD to 0.002, and
*larger* than real on NZDUSD (+0.050 against +0.006). **There is nothing in the
transition matrix that volatility clustering inside a 200-bar block does not
already produce.**

**And the incumbent is a three-to-five times stronger state description of the
same thing.** Quartiles of `trpct` - one rolling percentile, no darts - read
+0.192 to +0.375.

**With one qualification that the constant-sigma rows earn.** On the Volatility
indices, whose sigma is constant by publication, `trpct` quartiles still read
**+0.115 and +0.131 at p 0.000**, because `trpct` is a 1,500-bar rolling rank of
a 14-bar EWMA and a smoothed statistic's quartiles persist on i.i.d. data by
construction. The darts states read +0.003 and -0.005 there. So the honest
comparison is: **the darts states are cleaner - they carry no mechanical
persistence floor - and weaker, and what they do carry is reproduced by a block
shuffle.** Cleaner and weaker is not a reason to build anything.

**The planted-drift control is invisible, at p 0.068 to 0.442 and an excess of
-0.013 to -0.009.** That is not a near miss. See the power section.

### Does any transition precede anything

Forward 10 bars - the next disjoint window - in trailing-mean-absolute-return
units, as each cell's mean **minus the instrument's own unconditional mean over
the same observations**. Without that subtraction the table measures the
sample's drift: the most populous state inherits whichever way the pair went
over the period and reads as a signal.

| arm | cells | 90% interval clear of zero | expected | survive BH at q=0.05 |
| --- | ---: | ---: | ---: | ---: |
| deep, `scaled` | **260** | 25 | 26.0 | **0** |
| 60k, `scaled` | 184 | 21 | 18.4 | **0** |
| 60k, `raw` | 190 | 21 | 19.0 | 2 |

The two BH survivors are both in the `raw` arm, which is not the headline arm:
`GBPJPY 0->1` at n=78 (+0.495, [+0.278, +0.734]) and `Drift Switch Index 10
3->2` at n=84 (+0.391). One is a synthetic feed's cell; the other is 78
observations - under the ~100 where this desk's standing prior is noise - and
**does not appear at all in the `scaled` arm on the same instrument**. Two of
634 cells across three arms, neither replicating, is what multiplicity looks
like.

### Pricing it, before trading it

Cost in R is `round_trip / stop`, set by the stop. A 2xATR(14) stop at 15
minutes. **The bar file's `spread` is in points, not price**, and the point is
not in the file, so it is measured off the quoted price grid.

| instrument | tick | spread, points | round trip | ATR(14) | cost/R | **x4** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| XAUUSD | 0.01 | 12.0 | 0.120 | 8.709 | 0.007 | **0.028** |
| XAGUSD | 0.001 | 8.0 | 0.0080 | 0.2730 | 0.015 | **0.059** |
| USDJPY | 0.001 | 3.0 | 0.0030 | 0.0843 | 0.018 | **0.071** |
| EURUSD | 1e-5 | 2.0 | 0.00002 | 0.000516 | 0.019 | **0.077** |
| AUDUSD / GBPUSD | 1e-5 | 2.0 / 3.0 | | | 0.022 | **0.087 / 0.088** |
| USDCAD / USDCHF / GBPJPY | | 3.0 / 3.0 / 8.0 | | | 0.029-0.037 | 0.118-0.150 |
| BTCUSD | 0.009 | 2424.0 | 21.816 | 186.54 | 0.058 | **0.234** |
| EURGBP / NZDUSD | 1e-5 | 3.0 / 6.0 | | | 0.061 / 0.075 | 0.244 / 0.300 |

**The x4 column is the one a verdict uses.** The bar field is the broker's
quoted spread and carries no commission: [`scalping.md`](scalping.md) read a
0.00011 round trip on EURUSD at 15m from the terminal's own bid/ask against
0.00003 here, and its 2xATR figure for EURUSD is **0.099R** against this page's
0.077R at the x4 margin. The two agree to about 22%, which is the cross-check
that makes either usable.

**The tick had to be measured properly and the first attempt was wrong.** Taking
the *median* gap between distinct closes reads the typical **move**, not the
grid, on any instrument whose move dwarfs its tick: BTCUSD came back at 0.601
against a true 0.01, which put its round trip at 1,456 and **its cost at 3.9R**.
Volatility 75 read 2.76R the same way. The 1st percentile of positive gaps
recovers 1e-5 on EURUSD, 0.001 on USDJPY, 0.01 on XAUUSD, Jump 75 and
Volatility 75, 0.1 on Step Index and 0.009 on BTCUSD against a true 0.01 - good
to about 10%. The minimum is the other failure: one anomalous gap takes BTCUSD
to 0.001.

### The barrier race from each transition

1:1 at a 2xATR stop, 40-bar cap, barriers on the wicks with **the stop winning a
tie**, entry at the next bar's open, one position at a time. The driftless null
is 0.500 of races won, so gross expectancy is zero before cost by arithmetic.
Net is at the x4 cost. **TWIN** is the same number of entries drawn at random
from the same de-overlapped observations on the same side, which carries the
sample's drift and the duty cycle.

| | cells | positive net | 90% lower bound above zero | expected at 5% | **beat their own twin** | expected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| deep, `scaled` | **234** | 52 | **4** | 11.7 | **121** | 117 |
| 60k, `scaled` | 102 | 13 | 1 | 5.1 | 50 | 51 |
| 60k, `raw` | 114 | 20 | 1 | 5.7 | 57 | 57 |

**Fewer cells clear zero than chance expects, and the twin comparison is a
coin to within four cells of 234.** The best cell in the deep pass is EURUSD
`3->2` short, n=84, +0.204R net against a twin of -0.022R; the second is
EURGBP `1->0` short, n=123, +0.170R against -0.020R. Both are under the ~100-to-
130-trade range where this desk treats the prior as noise, and 4 of 234 is
what 5% of 234 looks like after it has been thinned.

## Power: where the test goes blind

Two-state regimes planted into generated bars, each bar built from fifteen
sub-steps so the high and low are extremes of a real path. **Priced near 2,000
rather than 1.0**, because at a price of one a relative standard deviation and a
price offset are the same number and a scale bug cannot be seen. 60,000 bars
and 2,398 de-overlapped observations - matched to the deep FX cells.

| sweep | parameter | ARI vs truth | stay excess | permutation p | signed gap, in R |
| --- | --- | ---: | ---: | ---: | ---: |
| volatility | 1.00x (**null**) | -0.000 | -0.006 | 0.536 | -0.100 |
| volatility | 1.05x | 0.001 | +0.004 | 0.700 | +0.107 |
| volatility | **1.10x** | 0.007 | +0.004 | **0.688 - blind** | +0.011 |
| volatility | **1.25x** | 0.039 | +0.026 | **0.006 - first seen** | -0.010 |
| volatility | 1.50x | 0.091 | +0.035 | 0.000 | +0.022 |
| volatility | 2.00x | 0.191 | +0.073 | 0.000 | +0.037 |
| volatility | 3.00x | 0.233 | +0.097 | 0.000 | +0.023 |
| **drift** | **0.02 to 1.00 sigma a bar** | **-0.000 to +0.000** | -0.010 to +0.004 | **0.268 to 0.966 - never seen** | -0.146 to +0.057 |
| persistence | stay 0.50 | 0.020 | -0.014 | 0.134 | -0.004 |
| persistence | **stay 0.80** | 0.050 | +0.006 | **0.474 - blind** | +0.053 |
| persistence | **stay 0.90** | 0.075 | +0.044 | **0.000 - first seen** | +0.064 |
| persistence | stay 0.98 / 0.998 | 0.197 / 0.028 | +0.132 / +0.111 | 0.000 | -0.021 / +0.077 |

**The volatility reading has power and the real markets sit inside it.** First
detection at a 1.25x vol ratio; blind at 1.10x. Traded feeds read a stay excess
of +0.039 to +0.115, which brackets planted ratios of roughly 1.5x to 3x - and
the block shuffle reads the same, so that is what the excess *is*.

**The drift reading has no power at any strength tested, and that is structural
rather than statistical.** ARI is -0.000 to +0.000 at every μ to 1.0 sigma a
bar. For scale: a planted drift of 1.0 sigma a bar gives a close-location-vs-
next-return correlation of **0.171**, and the `Drift Switch` feeds read **+0.136,
+0.154 and +0.136** against -0.006 to -0.062 on real markets. So the planted
control carries about the drift this sweep's strongest cell carries, and neither
is visible to the clustering.

**The reason is in the output type.** Every darts scorer returns a *distance* -
a norm of a residual, a distance to a centroid, a Wasserstein distance, an
isolation depth - and a distance has no sign. A state built from a vector of
distances cannot represent "mostly up", so no amount of data makes a direction
appear. This is worth more than the null: it says the brief's third question has
an answer that is not about sample size, and it predicts the `Drift Switch` row
in Q3 before the row is read.

**The signed-gap column's own false-positive rate is nominal.** Two of the
nineteen power cells have a 90% interval clear of zero with nothing planted -
the 1.00x and 1.05x volatility rows - which is 10.5% at a 90% interval. So
Q3b's 25-clear-of-26.0-expected is the test behaving, not the test failing.

A 20,000-bar sweep at 798 observations was run first and agrees: first
volatility detection at 1.25x (p 0.008), drift never detected, persistence first
seen at 0.9.

## The repo's own leak guard refused a positive control, and was right to

`spikerisk.load` refuses a series whose close location predicts the next return
above 0.15 - the defect that made a yahoo daily FX model look like a 94% winner.
**It refused `Drift Switch Index 20` at +0.154**, while passing `Drift Switch
Index 10` and `30` at +0.136, which would have silently dropped a third of the
positive control.

That is the guard working on a genuinely predictable generator, not a misaligned
bar: on a planted drift regime the close really does sit near the bar's high
while the drift is up, and the next return really is positive. A planted drift
of 1.0 sigma a bar reproduces the reading at 0.171 while a planted *volatility*
regime of 2.0x reads under 0.03. The override is scoped to that one family, the
reason is recorded on `dartsad_run.ALLOW_CLV`, and
`test_clv_corr_separates_a_planted_drift_from_a_planted_volatility_regime` pins
the mechanism so the override cannot quietly become a habit.

**Nobody should "fix" that data.** The number is the control's signature.

## What this closes, and what it does not

**Closed.** darts' anomaly scorers as a source of a tradeable or gating signal
on this desk's bars, at 15 minutes, on these twenty-four feeds. The three
questions in the brief are answered: the scores restate volatility, the clusters
are volatility bins, and the transition matrix is reproduced by a
volatility-matched block shuffle while being three to five times weaker than one
rolling percentile's quartiles. No transition precedes anything that survives
Benjamini-Hochberg, and no traded cell beats its own random twin more often than
a coin.

**Not closed.**

* **A signed state.** Everything here is built from distances, and the
  planted-drift blindness is a property of that choice. A state built from a
  *signed* statistic - darts' `score_from_prediction` against a real forecasting
  model, keeping the residual's sign - is a different object and this page says
  nothing about it. The null to beat is written: the clustering must separate the
  `Drift Switch` feeds, which carry a drift of about 1 sigma a bar and a
  close-location correlation of +0.14.
* **The regression frame at a real incumbent.** +0.046 of R2 is an upper bound
  measured against four columns. `lin48 + scores` against `lin48` on forward log
  variance is one arm on
  [`changepoint-increment.md`](changepoint-increment.md)'s harness, and it is
  the only version of Q1b worth running.
* **`norm`'s one-bar increment.** The L1 size of the last bar beats a 14-bar
  EWMA within percentile strata on 9 of 10 FX pairs for shocks and 7 of 10 for
  range blowouts. That is a statement about `anomalies.py`'s incumbent being
  over-smoothed, it has nothing to do with darts, and it has not been measured
  in R.
* **Other clocks.** 15 minutes only. The prior art halves between 15m and 1h and
  cost multiplies as the clock shortens, so neither direction is free.
* **`KNN` as the PyOD model**, which the brief's "et al." probably meant. It was
  dropped for cost, not for any result.

## Scripts, and how to run them

Four files were added. Each carries its own invocation, its leak boundary and
its gates in its module docstring, which is the authority; this section says
what each is for, how to read its output, and what it needs on disk.

### [`research/harness/dartsad.py`](../harness/dartsad.py)

**What it measures.** Nothing on its own: it is the arithmetic every number
above rests on - causal bar geometry, the de-overlap stride, transition counts
and their independence baseline, the Mann-Whitney and within-strata AUCs, the
out-of-sample R2, the barrier race, the day-block bootstrap,
Benjamini-Hochberg, the planted two-state regime, the quoted tick size and the
close-location statistic. It imports nothing but numpy and pandas **on
purpose**, so the suite can exercise it in the repo's own venv.

**How to run it.** Not run directly; `tests/test_dartsad.py` is what exercises
it.

```sh
uv run pytest tests/test_dartsad.py -q
```

**How to read the output.** The docstrings on `geometry`, `log_level`,
`clv_corr`, `deoverlap`, `stay_share`, `race`, `tick_size` and `plant` each name
the defect they prevent with the number attached.

**Data.** None.

### [`research/harness/dartsad_run.py`](../harness/dartsad_run.py)

**What it measures.** All three questions. `PHASE=score` fits darts' scorers per
instrument and writes one npz a cell, with the two shuffled nulls scored through
the same scorers; `PHASE=report` prints Q0 and Q1 to Q3d from those files;
`PHASE=power` runs the planted-regime sweep; `PHASE=leak` prints the
`window_agg` probe.

**How to run it.** Through the launcher, never `lab.sh run`:

```sh
./.secrets/lab.sh sync
./.secrets/lab.sh exec '$HOME/till_infinity/repo/research/harness/dartsad_lab.sh \
    score BARS=60000 INTERVALS=15m FEATSETS=scaled,raw WORKERS=16'
./.secrets/lab.sh exec '$HOME/till_infinity/repo/research/harness/dartsad_lab.sh report'
./.secrets/lab.sh exec '$HOME/till_infinity/repo/research/harness/dartsad_lab.sh power POWER_BARS=60000 WORKERS=12'
./.secrets/lab.sh exec '$HOME/till_infinity/repo/research/harness/dartsad_lab.sh leak'
```

The deep pass is the same script with the quadratic scorer dropped, which is
what makes 200,000 bars reachable:

```sh
./.secrets/lab.sh exec 'DARTSAD_TAG=deep $HOME/till_infinity/repo/research/harness/dartsad_lab.sh \
    score BARS=200000 INTERVALS=15m FEATSETS=scaled SCORERS=norm,kmeans1,kmeans10,iforest10 \
    WORKERS=8 DARTSAD_OUT=/home/<lab-user>/till_infinity/out/dartsad_deep'
```

`report` must be given the same `SCORERS` as the `score` that wrote the files,
or it asks an npz for a column it does not hold.

**How to read the output.** Every AUC is `raw/within-strata` and **the second
number is the verdict**: a column that moves only the first restates the
volatility the incumbent already holds. In Q1's family block each cell is
`mean/beat`, where `beat` counts the instruments on which the column beats
`lvol` within strata. Q2's verdict is the last pair - the state label's AUC for
forward volatility within strata. Q3's verdict is `excess` read against the
three columns beside it: `shuf` is the i.i.d. control, `block` the
volatility-matched one, `trpct` the incumbent with no darts in it. Q3d's verdict
is `net R` against `twin net`, with `90% low` above zero; the three summary
counts under it are the whole trade answer.

**Data.** `data/seqlab` (the broker's 15m and 1h bars) and `data/syn` (the rest
of the Deriv families at 15m, including both positive controls), on the lab.
Both are written by [`seqcache.py`](../harness/seqcache.py) from the terminal.
Bar counts differ by symbol by a factor of ten, which is why the study prints
`n` per instrument. Rebuild with `./.secrets/lab.sh run
research/harness/seqcache.py`, which skips what is already on disk. Nothing in
this study pulls bars.

### [`research/harness/dartsad_lab.sh`](../harness/dartsad_lab.sh)

**What it does.** Launches one phase detached with
`OMP/OPENBLAS/MKL_NUM_THREADS=1`, writes a `.flag` when the phase ends, and
refuses to start if the darts venv is missing. The one-thread setting is not
tidiness: sklearn's own threading drove this box's load average to 658 on 64
cores once already. `DARTSAD_TAG` suffixes the log so a second grid does not
overwrite the first's.

**How to run it.** As above. The venv it needs is built once, and is **not** the
repo venv - `u8darts` brings its own numpy 2.5 and pandas 3.1 majors:

```sh
/usr/bin/python3.12 -m venv $HOME/till_infinity/.venv-darts
$HOME/till_infinity/.venv-darts/bin/pip install u8darts pyod
```

**How to read the output.** One line, the log path, then
`./.secrets/lab.sh exec 'tail -200 $HOME/till_infinity/logs/dartsad_report.log'`.
A missing log means `lab.sh run`'s whitespace-splitting on environment
arguments, which is the reason this launcher exists at all.

**Data.** None of its own.

### [`tests/test_dartsad.py`](../../tests/test_dartsad.py)

**What it protects.** Seventeen tests over the arithmetic in `dartsad.py`, each
docstring saying what breaks without it rather than restating its assertion.
Five pair a null with a control, because a harness that could only return nulls
would have produced this same page:

| test | the null it shows | the control that shows it is not refusing everything |
| --- | --- | --- |
| `..._label_permutation_null_passes_an_order_free_sequence_and_rejects_a_chain` | an order-free sequence with the same marginals is not rejected | a sticky chain from the same alphabet is rejected at p = 0.000 |
| `..._within_strata_auc_collapses_when_the_score_is_the_stratifier` | a function of the stratum reads 0.5 inside the strata | an independent score keeps its AUC above 0.6 in both columns |
| `..._persistence_is_read_against_its_own_marginals_not_against_a_half` | an unbalanced order-free sequence reads an excess near zero | a sticky one reads above +0.2 |
| `..._plant_puts_in_the_regime_the_power_curve_claims_to_look_for` | at `lam = 1.0` the two states are indistinguishable | at `lam = 2.0` the volatility ratio is 1.7-2.3 |
| `..._clv_corr_separates_a_planted_drift_from_a_planted_volatility_regime` | a volatility-only regime reads under 0.03 | a 1-sigma drift regime reads above 0.12, which is what the real feed reads |

The rest pin the leak boundary (`..._no_feature_row_moves_when_a_later_bar_changes`,
`..._the_scale_a_bar_is_divided_by_excludes_the_bar_itself`,
`..._a_forward_label_ignores_bars_beyond_its_own_window`), the de-overlap
stride, the race (one position at a time, the stop winning a tie, and sitting on
the driftless 0.500 over 5,000+ races on a walk), the out-of-sample R2 refusing
noise columns, the tick estimator against the sparse-grid case that read 3.9R,
NMI, and BH's step-up boundary.

**How to run it.**

```sh
uv run pytest tests/test_dartsad.py -q
```

**How to read the output.** A failure names the behaviour.
`test_the_barrier_race_sits_on_the_driftless_null_for_a_walk` failing means
every conditioned R in Q3d is measured against the wrong baseline, and is the
one to read first.

**Data.** None: every fixture comes from `dartsad.plant`.

### The suite

Measured on the lab from inside the synced tree, against `de363bdc`:

```sh
cd $HOME/till_infinity/repo && $HOME/till_infinity/.venv/bin/python -m pytest tests -q
```

Baseline on `de363bdc` with this branch's test file ignored: **3023 passed, 7
skipped, 12 deselected.** With it: **3040 passed, 7 skipped, 12 deselected** -
the seventeen tests added here, and nothing else moved.

The baseline is 3023 and not the 3022 this branch was briefed with, because
`main` moved from `f4348955` to `de363bdc` (#348) while the study ran and that
commit added one test. The branch is rebased onto `de363bdc`, and both counts
above are from the same tree, measured by running the suite twice - once with
`--ignore=tests/test_dartsad.py` - rather than by subtracting.

## The practical limit, recorded because it shaped the grid

`WassersteinScorer` compares every window against every stored training value,
so its cost is the product of the two. Measured: 3.5s at 5,000 bars, **62.3s at
20,000**, and the full 36,000-bar training block would put one instrument at
about nine minutes a pass with three passes a cell. The reference is an
empirical distribution, so it is fitted on the last 10,000 bars of the train
block - 10,000 draws rather than an approximation of something larger - and the
deep pass drops the scorer entirely. That is why there are two grids rather than
one, and why `KNN` is not among the PyOD models.
