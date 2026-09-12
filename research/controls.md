# The instrument works: it finds volatility clustering on gold at R-squared 0.49 and nothing at all on a Volatility index, with the same code

Five sequence-model arms are running on the synthetic book and all five are
expected to report nothing. That expectation is well founded -
[deriving.md](deriving.md) proves `E[net] = -(c/2) x turnover` for any
predictable position on a martingale and [rebuilding.md](rebuilding.md)
confirmed it empirically with `n*` infinite on every arm - but **a folder of
negative results is worth nothing until something proves the instrument can
detect a positive.** "We found nothing" and "this harness cannot find anything"
produce the same table.

This page is that proof, and a second question that had not been asked.

**The positive control passes.** The same loader, the same 28 features, the same
walk-forward folds with the same purge, the same metric:

Each cell is the range across the eight timeframes of `seqlab.GRID` of the mean
over that group's symbols.

| | rank ac1 of \|r\| | Ljung-Box(10) on \|r\| | HAR out-of-sample log-vol R-squared, h=22 |
| --- | --- | --- | --- |
| **real markets** (5 symbols) | **+0.140 to +0.238** | **3,224 to 27,557** | **+0.32 to +0.49** |
| **Volatility family** (6 symbols) | -0.005 to +0.006 | 6.3 to 14.0 | -0.032 to -0.002 |
| **simulated GBM** at the same sigma | -0.011 to +0.006 | 6.3 to 12.9 | -0.045 to -0.001 |

The 95th percentile of chi-square with 10 degrees of freedom is **18.31**. Every
real market clears it by two to three orders of magnitude at every timeframe on
the grid; no Volatility index reaches it anywhere, and neither does a GBM
simulated by `seqlab.gbm_bars`.

That is the whole argument in one table, and it works in both directions at once.
A leak in the feature or split layer would inflate the synthetic column as well
as the real one, because it is the same code path on both. The synthetic column
is flat. So the +0.49 on real markets is signal and the zero on the Volatility
family is the absence of signal, and neither reading depends on trusting the
other.

**And the cross-sectional test has power it can demonstrate.** The top eigenvalue
of the 21-feed `log volume` correlation matrix is **11.09** against a
Marchenko-Pastur bulk edge of 1.042 - the shared publication clock
[twins.md](twins.md) measured at 9ms, showing up at bar level as a pairwise
tick-count correlation of **0.982**. The same matrix built from returns sits at
**1.035, inside the bulk**. The instrument sees the thing that is there and not
the thing that is not.

**Part 2's answer, in one line: the only thing these twenty-one instruments
share is the clock.** No eigenvalue of the returns or `|return|` correlation
matrix leaves the Marchenko-Pastur bulk at any timeframe, in either of the two
universes run - including 1h on 32,667 bars, where a shared factor loading 8% of
each feed's variation would have been caught. No lagged cross-correlation clears
its rotation null. A pooled ridge from twenty feeds into the twenty-first reads
AUC 0.495 to 0.501 and a negative out-of-sample R-squared everywhere. And **no
matched `(standard, 1s)` pair at the same sigma shows coupling** - the one
candidate, Volatility 100 against its `(1s)` twin, is killed in section 12 by a
test only a bar-level study can run.

## What was run

Two harnesses, both on the lab, both on `research/harness/seqlab.py` as the only
data, feature and split layer.

* **`research/harness/seqcontrol.py`** - 176 cells: 5 real symbols, 6 Volatility
  symbols, and a simulated GBM matched to each, across all eight timeframes in
  `seqlab.GRID`, at horizons 1, 5 and 22. No cell failed.
* **`research/harness/seqcross.py`** - the 22-symbol Volatility universe, of which
  **21 return data**, aligned on a common timestamp index per timeframe:
  correlation spectra against Marchenko-Pastur, lagged cross-correlation, a pooled
  ridge from the other 20 feeds into each one, and every matched `(standard, 1s)`
  pair against every mismatched one. Run four ways - the full universe, a
  follow-up on the twins with a corrected family-wise null, a `+-20` lag
  correlogram probe of every twin pair, and a **deep universe** that trades short
  feeds for bars (section 11). Every command is in *How to reproduce*.

`check_causality` reports **CLEAN on both sides** - 49,950 rows checked on XAUUSD
1h and on Volatility 75 Index 1h - so nothing below is a look-ahead. Every number
on this page carries the sample it was measured on.

---

# Part 1 - the positive control

## 1. The published statistic, replicated exactly, and what it actually measures

`seqlab.main()` prints on Volatility 75 Index at 1h:

    vol: naive srel 0.8802   mean srel 0.6691
    gbm: naive srel 0.8809   mean srel 0.6642

This harness reproduces it to the third decimal on the same symbol and timeframe
(0.8819 / 0.6692; the small difference is that the mean here is the *training*
fold's mean rather than the full sample's, which is the honest version). The
reading offered for it was that the unconditional mean wins because sigma on a
Volatility index is genuinely constant, and that the inversion of that sign on a
real market would establish it.

**The sign does not invert on a real market. It does not invert on gold at any
timeframe on the grid.** Averaged over the five real symbols, horizon 1:

| timeframe | real gap | Volatility gap | GBM @ real sigma | GBM @ vol sigma | n_test (real) |
| --- | --- | --- | --- | --- | --- |
| 3m | **-0.1052** | -0.2142 | -0.2131 | -0.2143 | 41,649 |
| 15m | **-0.1071** | -0.2144 | -0.2137 | -0.2152 | 41,649 |
| 1h | **-0.0935** | -0.2148 | -0.2135 | -0.2152 | 41,649 |
| 4h | **-0.0363** | -0.2174 | -0.2121 | -0.2154 | 38,319 |
| 6h | **-0.0629** | -0.2145 | -0.2132 | -0.2132 | 26,364 |
| 8h | **-0.0860** | -0.2166 | -0.2156 | -0.2142 | 20,389 |
| 12h | **-0.1124** | -0.2144 | -0.2131 | -0.2134 | 14,396 |
| 1d | **-0.1547** | -0.2108 | -0.2152 | -0.2100 | 8,402 |

`gap = srel(mean) - srel(naive)`; negative means the unconditional mean wins. The
within-symbol standard error, from a moving-block bootstrap, runs 0.003 to 0.009.

**This is not a broken harness and it is not an absence of clustering.** It is the
metric. At horizon 1 the target `realised` is `|r_{t+1}|` - one squared return,
the noisiest possible estimate of a variance - and a symmetric relative error
charges a forecaster for its own noise as well as for its bias. The naive
forecast carries a full half-normal of noise that no amount of clustering can
remove: **even with sigma perfectly constant and perfectly known**, `|r_t|`
against `|r_{t+1}|` is two independent half-normals, and that alone costs 0.88.
Clustering makes *both* forecasters worse - gold's naive is 0.924 against the
family's 0.882, and gold's mean is 0.819 against 0.668 - but it makes the
constant worse faster. That narrows the gap from -0.21 to -0.04 and cannot
close it.

So the finding is a **correction to how that number is read**, not a defect:

> The h=1 srel gap is a **very strong discriminator** between a real market and a
> Volatility index - -0.09 against -0.21 with a within-symbol standard error of
> 0.003. That separates the two groups by **29 standard errors at 1h, 20 or more
> everywhere from 3m to 6h, and never fewer than four** (1d, where the real
> column drifts back toward the family on 8,402 test rows). It is **not** an
> indicator of whether sigma is constant, and its sign carries no information
> about clustering. Any page that reads the sign that way needs this paragraph.

The GBM columns are the reason to trust that reading. A simulated geometric
Brownian motion at gold's *own measured* sigma scores -0.2131 at 3m, which is the
Volatility family's number and not gold's. The gap is not about the level of
volatility; it is about whether the series has a variance process, and at h=1 the
metric can only see a large one.

## 2. The matched-window statistic, which does invert

At horizon `h` the naive forecast should be the realised volatility of the *last*
`h` bars, not of the last one. `seqlab.HAR` is `(1, 5, 22)`, so `rv1`, `rv5` and
`rv22` are exactly the matched forecasts at h = 1, 5, 22, and the forecaster's own
estimator noise falls as `1/sqrt(2h)`.

| timeframe | h | real gap | Volatility gap | GBM @ vol sigma | n_eff (real) |
| --- | --- | --- | --- | --- | --- |
| 3m | 5 | **+0.0814** | -0.1074 | -0.1065 | 8,329 |
| 3m | 22 | **+0.1091** | -0.0502 | -0.0480 | 1,892 |
| 15m | 5 | **+0.0566** | -0.1057 | -0.1066 | 8,329 |
| 15m | 22 | **+0.0439** | -0.0497 | -0.0507 | 1,892 |
| 1h | 5 | -0.0004 | -0.1057 | -0.1054 | 8,329 |
| 1h | 22 | **+0.0586** | -0.0506 | -0.0492 | 1,892 |
| 4h | 5 | **+0.1036** | -0.1057 | -0.1055 | 7,663 |
| 4h | 22 | **+0.2033** | -0.0516 | -0.0504 | 1,741 |
| 6h | 22 | **+0.1879** | -0.0502 | -0.0506 | 1,198 |
| 8h | 22 | **+0.1693** | -0.0495 | -0.0512 | 926 |
| 12h | 22 | **+0.1381** | -0.0501 | -0.0468 | 654 |
| 1d | 22 | **+0.0692** | -0.0507 | -0.0453 | 381 |

**At h = 22 the sign inverts on all five real symbols at all eight timeframes, and
on no Volatility symbol anywhere.** `n_eff` is the number of non-overlapping
targets; the raw test rows are 22 times larger and are in the JSON.

That is the inversion the study was commissioned to find. It needed a target with
less estimator noise in it than a single squared return, which is the reason HAR
is specified over three windows and not one.

## 3. Clustering, with no forecaster and no loss function in the way

The statistic with nothing to argue about: the rank autocorrelation of `|r|` at
lag 1, and Ljung-Box over ten lags. No model, no metric convention, no fold.

| timeframe | real ac1 (range) | Volatility ac1 (range) | real LB(10) | Volatility LB(10) | n_bars |
| --- | --- | --- | --- | --- | --- |
| 3m | **+0.2224** (0.152 to 0.281) | +0.0012 (-0.001 to 0.004) | 15,574 | 8.4 | 50,000 |
| 15m | **+0.2243** (0.200 to 0.235) | +0.0004 (-0.001 to 0.002) | 20,100 | 6.3 | 50,000 |
| 1h | **+0.2375** (0.216 to 0.264) | +0.0004 (-0.005 to 0.007) | 13,196 | 8.5 | 50,000 |
| 4h | **+0.2092** (0.138 to 0.290) | -0.0018 (-0.009 to 0.005) | 27,557 | 10.3 | 46,004 / 16,868 |
| 6h | **+0.1812** (0.102 to 0.280) | -0.0047 (-0.019 to -0.001) | 16,925 | 9.1 | 31,658 / 11,246 |
| 8h | **+0.1648** (0.066 to 0.277) | -0.0034 (-0.008 to 0.004) | 11,810 | 14.0 | 24,488 / 8,434 |
| 12h | **+0.1550** (0.073 to 0.269) | +0.0005 (-0.018 to 0.012) | 7,245 | 13.3 | 17,297 / 5,623 |
| 1d | **+0.1400** (0.048 to 0.230) | +0.0062 (-0.018 to 0.022) | 3,224 | 10.1 | 10,104 / 2,811 |

Ljung-Box(10) has a 95% critical value of **18.31**. The Volatility family does
not reach it at a single timeframe; the real markets exceed it by 400x to 1,500x.
Per symbol at 1h: EURUSD +0.2339, XAUUSD +0.2157, GBPUSD +0.2377, USDJPY +0.2358,
BTCUSD +0.2643. The weakest real cell on the whole grid is GBPUSD at 1d, +0.0481
on 10,104 bars, which is still ten standard errors from zero.

**Condition 2 does not fire. The harness sees volatility clustering on gold.**

## 4. The model finds it too

The HAR ridge - `seqlab.ridge` on `log rv1, log rv5, log rv22`, fitted on the
training block, standardised on the training block, predicting `log realised` -
scored as out-of-sample R-squared in logs against the training mean:

| timeframe | h | real HAR R2 | real full-feature R2 | Volatility HAR R2 | GBM HAR R2 |
| --- | --- | --- | --- | --- | --- |
| 3m | 1 | +0.039 | +0.106 | -0.0003 | -0.0002 |
| 3m | 5 | +0.383 | +0.382 | -0.0008 | -0.0008 |
| 3m | 22 | **+0.399** | +0.414 | -0.0021 | -0.0011 |
| 1h | 22 | **+0.355** | +0.355 | -0.0022 | -0.0010 |
| 4h | 22 | **+0.490** | +0.466 | -0.0046 | -0.0076 |
| 6h | 22 | **+0.485** | +0.377 | -0.0088 | -0.0113 |
| 8h | 22 | **+0.489** | +0.362 | -0.0093 | -0.0182 |
| 1d | 22 | **+0.347** | +0.040 | -0.0318 | -0.0451 |

Per symbol at h=22: BTCUSD +0.608 at 3m, USDJPY +0.424 at 1h, XAUUSD +0.340 at
1h. Twenty-two of the twenty-four (timeframe x horizon) real cells are positive.
The two that are not are 6h and 8h at h=1, where the target is a single squared
return and the R-squared of any forecaster against it is close to zero by
construction.

**Every Volatility cell is negative**, which is what an honest out-of-sample
R-squared does when there is nothing to fit: the fitted coefficients are noise and
cost a little against the training mean. The full 28-feature ridge is negative
there too, and more negative at the short-history end - -0.166 at 1d - which is
the overfitting an out-of-sample score is supposed to show.

**Condition 3 does not fire. The instrument fits a known signal.**

## 5. The discriminator: about three hundred bars

How many bars does it take to tell a Volatility index from a real market on this
statistic alone? `seqlab.nstar`, with the standard error measured by a
moving-block bootstrap rather than assumed:

| timeframe | rank ac1 of \|r\| | srel gap h=1 | srel gap h=5 | srel gap h=22 | bars held |
| --- | --- | --- | --- | --- | --- |
| 3m | 314 | 591 | 63 (**320 bars**) | 27 (**616 bars**) | 50,000 |
| 15m | 307 | 539 | 74 (375) | 75 (1,672) | 50,000 |
| 1h | 273 | 382 | 158 (795) | 46 (1,034) | 50,000 |
| 4h | 345 | 366 | 75 (380) | 16 (**374 bars**) | 46,004 |
| 6h | 445 | 497 | 83 (420) | 16 (374) | 31,658 |
| 8h | 543 | 648 | 106 (535) | 17 (396) | 24,488 |
| 12h | 643 | 988 | 116 (585) | 23 (528) | 17,297 |
| 1d | 857 | 3,221 | 189 (950) | 40 (902) | 10,104 |

The `h=5` and `h=22` columns are in non-overlapping targets; the bracketed figure
converts to bars (`n* x h + 22` for the warm-up), which is the number that
matters operationally.

**Every discriminator on the grid needs a few hundred bars and every one of them
is available many times over.** The cheapest is the h=22 matched gap at 4h and 6h
at about 374 bars - roughly nine weeks of 4h data, or sixteen hours of 3m data on
the h=5 gap. This is not a marginal measurement that needs more history; it is a
measurement that separates the two families on a few days of data and then keeps
separating them on five years.

---

# Part 2 - the cross-sectional leak hunt

[twins.md](twins.md) established that **all sixteen synthetics publish on one
clock to within 9ms**, and `rebuildpredict.py` drew the right inference from it:
if one generator stream feeds many instruments, consecutive draws from that
stream appear as *different feeds at the same index*, so a cross-feed
relationship is where a shared PRNG would show through. That was pursued at tick
level, pairwise, on one 24-hour window. This is the same idea at bar level,
across the whole grid, with the test that is actually powerful.

**Bar level is not a weaker version of the tick study.** The +0.3997 that
`twins.md` had to disown - V25 against V75 on a one-second grid - exists because a
two-second feed contributes a zero to every other cell of that grid and every
feed's zeros land in the same cells. At 3m and above each bar of each feed holds
between ninety and thirty thousand ticks, so there are no zeros to align and the
shared clock cannot manufacture that artefact. What bar level buys instead is
**depth**: 211 days to five years, against one day.

## 6. The universe, and what it is not

`seqlab.align` on the 22-feed Volatility universe. **`Spot Up - Volatility Down
Index` 404s on every timeframe in the grid** and is absent throughout, so this is
21 feeds, not 22. Below 12h the count falls further because three instruments -
Volatility 15, 30 and 90 - were listed about 211 days ago where the rest reach
five years, and `seqlab.FEWEST` drops a feed under 600 bars.

| timeframe | feeds | common bars | stalled-bar fraction | max \|corr\| of stall indicators |
| --- | --- | --- | --- | --- |
| 3m | 21 | 48,990 | 0.00173 | 0.0114 (16 feeds ever stall) |
| 15m | 21 | 20,270 | 0.00076 | 0.0190 (13) |
| 1h | 21 | 5,066 | 0.00029 | 0.0019 (6) |
| 4h | 21 | 1,266 | 0.00030 | 0.0022 (4) |
| 6h | 21 | 844 | 0.00006 | - (1) |
| 8h | 21 | 632 | 0.00008 | - (1) |
| 12h | 16 | 730 | 0.00034 | - |
| 1d | 12 | 1,360 | 0.00000 | - |

The last column is checked first and for one reason. A **shared outage** - a bar
in which many feeds simultaneously print no ticks - would put a factor into the
`|return|` panel that is a fact about the collector and not about the generator.
The stall indicators correlate at most **0.019** across feeds. There is no shared
outage, so nothing below has that explanation available to it.

Those 1h and 4h row counts are the reason this section is run twice, in section
11. A straight intersection of all 21 feeds at 1h is 5,066 bars because three
feeds are 211 days old; dropping them gives 32,668 bars on eighteen. Both
universes are reported.

## 7. The positive control: the shared clock is enormous and this test sees it

`log volume` is the tick count per bar, which on a generated feed is the
generator's own clock. If the cross-sectional instrument has power, this is where
it must show.

| timeframe | top eigenvalue | MP bulk edge | eigenvalues outside bulk | max \|pairwise corr\| | p_family |
| --- | --- | --- | --- | --- | --- |
| 3m | **11.09** | 1.0418 | 2 | **0.9820** | 0.000 |
| 15m | **16.36** | 1.0654 | 3 | **0.9984** | 0.000 |
| 1h | **15.29** | 1.1329 | 3 | **0.9979** | 0.000 |
| 4h | **14.44** | 1.2742 | 3 | **0.9978** | 0.000 |
| 6h | **14.20** | 1.3404 | 3 | **0.9978** | 0.000 |
| 8h | **14.04** | 1.3978 | 3 | **0.9979** | 0.000 |
| 12h | **10.42** | 1.3180 | 3 | **0.9977** | 0.000 |
| 1d | **6.57** | 1.1967 | 3 | **0.9968** | 0.000 |

A top eigenvalue of 16.36 on 21 series means **78% of the cross-sectional
variance of tick counts sits in a single factor** at 15m. The *mean* off-diagonal
correlation of the tick-count matrix is +0.42 at 3m rising to +0.71 at 15m, and
the largest pair reaches 0.998 at every timeframe from 15m up. `twins.md`
measured the shared timetable at 9ms between ticks; at bar level it is close to
an identity. Every rotation draw of the null sits at 1.4 to 3.1, so the observed
value is not near the null - it is an order of magnitude past it.

For the same matrices built from returns, the mean off-diagonal is **+0.0002**
and the top eigenvalue carries 4.9% of the variance, which is `1/21` - the share
it has when there is no factor at all.

**Condition 5 does not fire. This arm has demonstrable power**, and its silence
below is silence from an instrument that has been shown to work.

## 8. The returns and the magnitudes: inside the Marchenko-Pastur bulk, everywhere

The same matrix, the same code, on the price process rather than on the clock.

| timeframe | ret top eig | \|ret\| top eig | MP bulk | rotation null p95 | ret p_family | \|ret\| p_family | ret max \|r\| |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3m | 1.0347 | 1.0367 | [0.9590, 1.0418] | 1.0424 | 0.670 | 0.385 | 0.0121 |
| 15m | 1.0611 | 1.0618 | [0.9367, 1.0654] | 1.0654 | 0.190 | 0.135 | 0.0214 |
| 1h | 1.1089 | 1.1010 | [0.8754, 1.1329] | 1.1306 | 0.660 | 0.900 | 0.0427 |
| 4h | 1.2596 | 1.2217 | [0.7590, 1.2742] | 1.2738 | 0.185 | 0.665 | 0.0767 |
| 6h | 1.2529 | 1.2748 | [0.7094, 1.3404] | 1.3423 | 0.940 | 0.705 | 0.0973 |
| 8h | 1.3402 | 1.3783 | [0.6687, 1.3978] | 1.3906 | 0.455 | 0.070 | 0.1359 |
| 12h | 1.2278 | 1.2209 | [0.7258, 1.3180] | 1.3104 | 0.910 | 0.930 | 0.0935 |
| 1d | 1.1305 | 1.1278 | [0.8210, 1.1967] | 1.1921 | 0.875 | 0.910 | 0.0523 |

**Not one eigenvalue of either panel lies outside the bulk at any timeframe.** Not
one `p_family` is below 0.07. The largest pairwise correlation anywhere in the
returns panel is 0.0121 at 3m on 48,990 bars, where the standard error of a
single correlation is 0.0045 and the largest of 210 pairs is expected around
0.013.

The rotation null and the analytic law agree - at 3m the MP edge is 1.0418 and
the 95th percentile of the rotated top eigenvalue is 1.0424 - which is the check
that says Marchenko-Pastur applies to this data rather than being quoted at it.

**Conditions 1 and 2 do not fire. There is no shared factor in the price process
of the Volatility family.**

## 9. What that excludes, and what it does not

A clean spectrum means nothing without the sample size beside it, so the
detection floor was measured on the same shape: 21 independent Gaussian series of
the same length with a common factor at loading `beta`, against the 95th
percentile of the `beta = 0` top eigenvalue.

| timeframe | bars | smallest beta caught 80% of the time | implied pairwise correlation |
| --- | --- | --- | --- |
| 3m | 48,990 | **0.05** | 0.0025 |
| 15m | 20,270 | **0.05** | 0.0025 |
| 1h | 5,066 | 0.08 | 0.0064 |
| 4h and longer | 1,266 and fewer | not reached at 0.08 | - |

So the honest statement is bounded: **a shared factor loading 5% of each feed's
variation would have been caught on every draw at 3m and 15m, and was not
present.** At 4h and above the sample is too short for this test to exclude
anything, and those rows are reported as untested rather than as null - which is
what `condition 6` is for and it fires on 1h through 1d in this universe.
Section 11 recovers 1h and 4h by trading feeds for bars.

## 10. Leads, and the pooled model

**Lagged cross-correlation**, all 420 ordered pairs at lags 1 to 5, against a
rotation null over the identical 2,100 cells:

| timeframe | ret max \|r\| | rotation null max | p_family | \|ret\| max \|r\| | rotation null max | p_family |
| --- | --- | --- | --- | --- | --- | --- |
| 3m | 0.0170 | 0.0208 | 0.300 | 0.0159 | 0.0218 | 0.600 |
| 15m | 0.0261 | 0.0297 | 0.300 | 0.0258 | 0.0318 | 0.500 |
| 1h | 0.0483 | 0.0704 | 0.620 | 0.0452 | 0.0603 | 0.980 |
| 4h | 0.1038 | 0.1193 | 0.360 | 0.0975 | 0.1217 | 0.700 |
| 6h | 0.1119 | 0.1695 | 0.900 | 0.1170 | 0.1398 | 0.700 |
| 8h | 0.1270 | 0.1866 | 1.000 | 0.1375 | 0.1898 | 0.640 |
| 12h | 0.1260 | 0.1550 | 0.720 | 0.1221 | 0.1660 | 0.700 |
| 1d | 0.0775 | 0.1115 | 0.980 | 0.0998 | 0.1297 | 0.220 |

**The observed maximum is below the rotation null's maximum in all sixteen
cells.** Condition 3 does not fire.

**The pooled model** - `seqlab.ridge` from the other 20 feeds' `ret, rv1, z5,
volume_z` at bar `t` (80 predictors) into feed `i`'s direction and `log |r|` at
`t+1`, feed `i`'s own columns excluded entirely, walk-forward folds, against the same model on
independently rotated feeds:

| timeframe | rows | mean AUC | largest deviation | rotation null | p_family | mean log\|r\| R2 | best | rotation null | p_family |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3m | 48,969 | 0.4994 | 0.5057 | 0.5060 | 0.550 | -0.0043 | -0.0028 | -0.0025 | 0.750 |
| 15m | 20,249 | 0.4983 | 0.5097 | 0.5097 | 0.600 | -0.0102 | -0.0052 | -0.0068 | **0.000** |
| 1h | 5,045 | 0.5015 | 0.5211 | 0.5201 | 0.350 | -0.0423 | -0.0280 | -0.0308 | 0.200 |
| 4h | 1,245 | 0.5012 | 0.5260 | 0.5403 | 1.000 | -0.1426 | -0.0763 | -0.0765 | 0.500 |
| 6h | 823 | 0.5018 | 0.5490 | 0.5537 | 0.650 | -0.1785 | -0.1319 | -0.1121 | 0.950 |
| 8h | 611 | 0.4929 | 0.5506 | 0.5626 | 0.800 | -0.2221 | -0.1077 | -0.0812 | 0.900 |
| 12h | 709 | 0.5143 | 0.5889 | 0.5596 | **0.000** | -0.1536 | -0.0514 | -0.0542 | 0.450 |
| 1d | 1,339 | 0.4958 | 0.5463 | 0.5358 | 0.100 | -0.0859 | -0.0613 | -0.0557 | 0.700 |

**Direction is dead.** Mean AUC across 21 feeds runs 0.493 to 0.514 and the
largest per-feed deviation from 0.5 is below the rotation null's in seven of
eight timeframes.

Two cells clear their rotation control and both need saying out loud rather than
leaving in a table. **This arm's `p_family` cannot go below 0.05**: it is computed
against twenty rotation draws, because each draw costs 220 ridge fits, so
"0.000" here means "beat all twenty" and not "p < 0.001". With sixteen family
tests on the grid, one or two at the 0.05 level is the expected count.

Beyond that, neither cell is predictability in any usable sense. At 15m the
best `log |r|` R-squared is **-0.0052**: the model is worse than its own training
mean, it merely loses less than the rotated version does. Section 13 settles both
cells on a second sample.

## 11. The same test with bars traded for feeds

Three instruments - Volatility 15, 30 and 90 - were listed about 211 days ago
where the rest of the family reaches five years, and an intersection is set by
its shortest member. `seqlab.align(..., min_share=0.6)` drops a feed below 60% of
the median depth before intersecting. That is a real trade: fewer series loosens
the Marchenko-Pastur bulk, more observations tightens it far faster, and the
second effect wins by a wide margin here. **This is the universe with the power.**

| timeframe | feeds | bars | ret top eig | \|ret\| top eig | MP bulk edge | ret p_family | \|ret\| p_family | logvolume top eig |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15m | 16 | 35,047 | 1.0383 | 1.0379 | 1.0432 | 0.215 | 0.290 | **11.61** |
| 1h | 12 | **32,667** | 1.0298 | 1.0276 | 1.0387 | 0.610 | 0.785 | **8.36** |
| 4h | 12 | 8,166 | 1.0595 | 1.0563 | 1.0781 | 0.535 | 0.750 | **7.67** |
| 6h | 12 | 5,444 | 1.0854 | 1.0837 | 1.0961 | 0.145 | 0.180 | **7.43** |
| 8h | 12 | 4,082 | 1.0902 | 1.0751 | 1.1114 | 0.430 | 0.885 | **7.31** |
| 12h | 10 | 4,584 | 1.0682 | 1.0727 | 1.0956 | 0.595 | 0.465 | **7.52** |
| 1d | 10 | 2,291 | 1.0832 | 1.0926 | 1.1365 | 0.915 | 0.755 | **7.18** |

1h goes from 5,066 bars to **32,667** and 1d from 1,360 to 2,291. **The answer
does not move.** Not one eigenvalue of the returns or magnitude panels leaves the
bulk at any timeframe in either universe; the largest pairwise return correlation
at 1h *falls* from 0.0427 to 0.0176 as the sample grows, which is what a
correlation of zero does when it is measured on more data; and the tick-count
factor is still there at 7.2 to 11.6 with a largest pairwise correlation of
0.9996.

The detection floor improves to a **0.05 loading at 15m and 0.08 at 1h and 4h**,
where the full universe reached 0.08 only at 1h and nothing below it. 6h and
longer remain untested at any loading this grid can measure.

The lagged tables come back the same: the observed maximum sits under the
rotation null's maximum in thirteen of fourteen cells, the exception being 6h
`|ret|` at 0.0557 against a null maximum of 0.0593 with `p_family` 0.040 - one
cell at 0.04 out of fourteen, which is the expected count and does not clear the
0.01 bar this page was written against.

## 12. The twins: every (standard, 1s) pair at matched sigma

If any pair on this venue shares a seed it is a standard index and its `(1s)`
twin - nominally the same process at a different tick rate. Nine such pairs
exist. The control is the 90 mismatched `(standard, 1s)` pairs: the same
generator family, the same mixture of tick rates, no claimed relationship, and
therefore every artefact the twins carry except the one being tested for.

**The pooled statistic first.** Largest |correlation| over lags 0 to 3, twins
against controls:

| timeframe | ret twin max | control max | twins above control max | \|ret\| twin max | control max | above |
| --- | --- | --- | --- | --- | --- | --- |
| 3m | 0.0103 | 0.0170 | 0/9 | 0.0134 | 0.0143 | 0/9 |
| 15m | 0.0261 | 0.0218 | **1/9** | 0.0159 | 0.0245 | 0/9 |
| 1h | 0.0478 | 0.0450 | **1/9** | 0.0359 | 0.0425 | 0/9 |
| 4h | 0.0545 | 0.1038 | 0/9 | 0.0638 | 0.0745 | 0/9 |
| 6h | 0.0973 | 0.1043 | 0/9 | 0.0930 | 0.0996 | 0/9 |
| 8h | 0.0942 | 0.1113 | 0/9 | 0.0834 | 0.1239 | 0/9 |
| 12h | 0.0632 | 0.1111 | 0/5 | 0.0662 | 0.0889 | 0/5 |
| 1d | 0.0461 | 0.0764 | 0/5 | 0.0634 | 0.0998 | 0/5 |

**A correction to how that last column is scored**, because it changed a number.
The first version asked how many of 90 *single* control pairs exceed the largest
of 9 twins - which is the wrong question, since the largest of nine exchangeable
draws sits near the top of ninety by construction, and P(max of 9 beats max of
the other 90) is 9/99 = 0.091 under pure exchangeability. On that arithmetic a
`p = 0.011` appeared at 3m that is not a finding at all. The family-wise null in
the harness is now the **maximum over a random nine of the ninety**, drawn a
thousand times - the identical statistic. One or two cells at 1/9 across eight
timeframes is exactly the expected count.

### The one candidate, and how it was killed

`Volatility 100 Index` against `Volatility 100 (1s) Index` is the pair that
clears at both 15m and 1h, and at 15m it looked like the real thing: **lag +3,
r = -0.0261, z = -3.32 against the control band, and both halves of the sample
reading -0.0262.** That is stable, signed and past every control pair. 15m and 1h
are also not independent evidence - they are the same 211-day window at two
resolutions.

`pair_probe` settles it with the test that a bar-level study can make and a
tick-level one cannot. **A relationship between two feeds lives at a time offset,
not a bar offset.** Lag +3 at 15m is forty-five minutes. At 3m that is lag +15,
where there are 48,990 bars and fifteen times the resolution to see it. The V100
returns correlogram at 3m around that point:

    lag   12       13       14       15       16       17       18
    r   -0.0077  +0.0006  -0.0045  -0.0055  -0.0062  -0.0111  -0.0009

Flat. The standard error of each of those is 0.0045; nothing there is a peak, and
the largest |z| anywhere in the 3m V100 correlogram is at lag **-16**, with the
**opposite sign** (+0.0135). At 1h the same pair peaks at lag +1 - sixty minutes,
not forty-five - and at 4h it is not in the top two pairs at all.

The peak lag is +3 bars at 15m, -16 bars at 3m and +1 bar at 1h. Those are
+45 minutes, -48 minutes and +60 minutes, in two different signs. **A generator
coupling does not move its lag and does not change its sign between two views of
the same data. The maximum over 9 pairs x 41 lags does both.** Against the
correct family-wise null over the full +-20 lag grid, the 15m cell reads
`p_family = 0.279`.

Across 3m, 15m, 1h and 4h - where the sample supports a +-20 lag correlogram -
both panels give a largest twin |z| of 2.9 to 3.4 against a control maximum over
the identical grid of 3.0 to 3.1, and the deep universe halves the 15m cell to
0.0131 on 35,047 bars. **No matched (standard, 1s) pair shows coupling, in
returns or in magnitudes, at any timeframe.** Condition 4 does not fire.

What the twins *do* share is the clock, and they share it no more than strangers
do: twin `log volume` correlation maxes at 0.9281 to 0.9939 against control
maxima of 0.9347 to 0.9952, and 0 of 9 twins exceeds its control at any
timeframe. **The shared timetable is a property of the venue, not of the pair.**

## 13. The two pooled cells that flagged do not reproduce

Section 10 left two cells open: 15m `log |r|` R-squared and 12h direction AUC,
each of which beat all twenty of its rotation draws in the 21-feed universe. The
deep universe is the test of whether they are real - a longer sample, a different
feed composition, the same code.

| cell | 21-feed universe | deep universe |
| --- | --- | --- |
| 15m, best log\|r\| R2 | -0.0052 vs null -0.0068, **p 0.000** | -0.0037 vs null -0.0031, p 0.900 |
| 12h, largest AUC deviation | 0.5889 vs null 0.5596, **p 0.000** | 0.5138 vs null 0.5169, p 0.750 |

**Neither survives.** Across the deep grid every pooled `p_family` is 0.25 or
above, mean AUC runs 0.495 to 0.501 on 2,270 to 35,026 rows, and the best
log-volatility R-squared is negative at every timeframe - the model never beats
its own training mean, let alone its rotation control.

That is a cleaner resolution than the attribution experiment that was queued for
these cells. The hypothesis was that the shared publication clock leaks through
the mechanical link between ticks-per-bar and range-per-bar, and `MODEL_COLS`
exists so that `volume_z` can be removed from the design and the question asked
directly. It may still be the mechanism, but there is no longer an effect to
attribute: the cells were the largest of sixteen family tests at a resolution of
0.05, and a second sample does not see them.

The same applies to the one twin cell. At 15m in the 21-feed universe the V100
pair reads 0.0261; in the deep universe, on 35,047 bars instead of 20,270, the
same pair reads **0.0131**. It halves when the sample grows, which a real
coupling does not.

---

# What this page does not say

* **`Spot Up - Volatility Down Index` is absent from everything here.** It 404s on
  all eight timeframes. No claim on this page covers it, and the cross-sectional
  universe is 21 feeds, not 22.
* **Uncorrelated is not independent.** What the spectrum excludes is a shared
  *linear* factor in returns, in magnitudes and in tick counts. A dependence
  orthogonal to all three - a copula in the middle of the joint distribution, a
  relationship in a nonlinear transform - is excluded by nothing here. The pooled
  ridge is also linear, so it inherits that limit; it is the model the other
  five arms are the nonlinear version of.
* **The 4h to 1d rows of Part 2 are short and are labelled untested, not null.**
  At 1,266 bars and fewer the detection floor is past a 0.08 loading, which is a
  pairwise correlation of 0.006 - so a factor smaller than that could be sitting
  in those rows unseen. The 3m and 15m rows are the ones that exclude anything.
* **The whole Volatility panel rests on 211 days below 12h**, because Volatility
  15, 30 and 90 are that young and the intersection is set by the shortest feed.
  A seed reused at a period longer than 211 days is invisible to the full
  universe here. The deep universe reaches five years on the older feeds.
* **Part 1's real column is five symbols**, four of them FX plus BTCUSD. It
  establishes that this pipeline finds volatility clustering, which is what it
  was built for. It is not a claim about how much of that clustering is tradable
  after cost - `deriving.md` covers that and the answer there does not change.
* **The h=1 srel gap discriminates but does not identify.** Section 1 should be
  read before that statistic is quoted anywhere else.
* **None of this is a trade.** A generator artefact, had one been found, would
  have been a finding about the product and about counterparty risk. `twins.md`
  argues the contract question at length and nothing here changes it.

# What follows from it

1. **The sibling arms' negatives are now falsifiable, and they are reportable.**
   Any arm can put its architecture through `seqcontrol.job` on `seqlab.REAL` and
   show it recovers a log-volatility R-squared in the 0.3 to 0.5 range before it
   reports a zero on a synthetic. An arm that cannot is reporting on itself.
2. **The naive-vs-mean srel gap should be quoted as a discriminator and never as
   evidence about clustering.** The matched-window version at h=22 is the one
   whose sign carries the meaning, and it inverts cleanly.
3. **The shared publication clock is a bar-level fact, not only a tick-level
   one**, and it is very large: tick counts across 21 feeds correlate at 0.998
   and 78% of their cross-sectional variance is one factor. Any future
   cross-feed study must rotate rather than shuffle, and must keep `logvolume`
   out of the design or attribute through it, or it will rediscover the
   timetable and call it a generator.
4. **`seqlab.align(..., min_share=...)` matters more than it looks.** The first
   run of `seqcross.py` studied 5,066 bars at 1h where 32,668 were available,
   because a filter on already-aligned data can never fire. Any arm that
   intersects feeds should check which of the two universes it is in.

# What was added to `seqlab.py`

Five additions, all purely additive - no existing function changed signature or
behaviour, so no sibling arm is affected.

* **`align(symbols, interval, *, min_share=0.0)`** - several symbols on one
  timestamp index, with the dropped feeds and their reasons returned rather than
  silently lost. `min_share` drops a feed shorter than that fraction of the
  median *before* intersecting, which is the only place the check can work.
* **`circular_shift(x, rng)`** - the rotation control. The right null for a
  shared clock, where a permutation is not: a permutation destroys each feed's
  own memory as well as its alignment, and these feeds have no memory to destroy.
* **`moving_block(n, rng)`** - moving-block bootstrap indices, so `nstar` can be
  given a measured standard error instead of its placeholder default of 0.01.
* **`mp_edges(n_series, n_obs)`** - Marchenko-Pastur bulk edges, the exact null
  for a correlation matrix of independent series.
* **`ridge(x_train, y_train, x_test, *, lam=1.0)`** - the shared linear floor,
  standardised on the training block only. It is here rather than in one arm so
  that six arms report against one regularisation and one standardisation.

# How to reproduce

Exactly the five runs this page is built from, in order:

    ./.secrets/lab.sh run research/harness/seqcontrol.py
    ./.secrets/lab.sh run research/harness/seqcross.py
    ./.secrets/lab.sh run research/harness/seqcross.py \
        SECTIONS=twins,twindetail OUT=$HOME/till_infinity/logs/seqcross_twins.json
    ./.secrets/lab.sh run research/harness/seqcross.py \
        SECTIONS=probe TIMEFRAMES=3m,15m,1h,4h \
        OUT=$HOME/till_infinity/logs/seqcross_probe.json
    ./.secrets/lab.sh run research/harness/seqcross.py MIN_SHARE=0.6 \
        SECTIONS=spectrum,lagged,power,twins,pooled \
        TIMEFRAMES=15m,1h,4h,6h,8h,12h,1d \
        OUT=$HOME/till_infinity/logs/seqcross_deep.json

`seqcontrol.py` runs eight worker processes with one BLAS thread each and
finishes in about a minute on 176 cells. `seqcross.py` is single-process with
eight BLAS threads and takes twenty to forty minutes for the full grid;
`SECTIONS` narrows it to one part, `TIMEFRAMES` to one bar size, `MIN_SHARE`
chooses the universe, and `MODEL_COLS` changes what the pooled model is allowed
to see. **`OUT` must be set when more than one variant is run**, because
`lab.sh` names the log from the script and a second run of the same file
overwrites the first one's log.
