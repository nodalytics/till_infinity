# The synthetics are exactly the generators Deriv says they are

Seventy-two percent of what this desk trades is a Deriv synthetic, and a
synthetic is not a market. There is no crowd, no news, no reflexivity. Whatever
structure exists is *generator* structure, and a generator is a fact rather than
an opinion - which makes it categorically different from every null in this
folder. [generated.md](generated.md) established that the synthetics share no
driver with anything, which is what independent generators should look like and
means each one has to be studied on its own terms.

Deriv publishes the terms. The Volatility indices are named for their annualised
volatility. Step Index is documented as a fixed-size fair coin. Boom and Crash
spike at a stated tick rate. Range Break breaks out at a stated cadence.

**All of it is true.** Measured 2026-09-11 on 60 days of one-minute bars (86,411
per series) and 24 hours of ticks, against six real instruments as a positive
control and a return-shuffle of each series as its own null:

| documented property | verdict | measured |
| --- | --- | --- |
| Volatility N Index realises N% annualised | **true** | 12 of 12 within **0.49%**, both halves |
| Step Index is a fixed 0.1 step | **true** | **99.9988%** of ticks are exactly 0.1 |
| Step Index is a fair coin | **true** | p(up) = **0.499734 +- 0.000220** over 5.2M flips |
| Boom/Crash spike once every N ticks | **true** | 268-974 measured against 300-1000 stated |
| Boom/Crash spike arrival is memoryless | **true** | waiting-time CV **0.84-1.10** across all six |
| Range Break 100 breaks twice as often as 200 | **true** | ratio **2.066**, 95% CI [1.86, 2.30] |
| the Boom grind is "nearly deterministic" | **half true** | per *minute* yes, per *tick* CV 0.63-0.68 |
| Jump N Index realises N% annualised | **false** | all five realise **1.32x** the name |

And one property nobody documents, which is the most useful thing here:
**the synthetics have no volatility clustering at all.**

Harnesses: [`genvol.py`](harness/genvol.py), [`genstep.py`](harness/genstep.py),
[`genspike.py`](harness/genspike.py), [`genrange.py`](harness/genrange.py),
[`genstop.py`](harness/genstop.py). Every one states its failure conditions in
its own docstring, before the numbers.

## One: realised volatility is the number in the name

`volatility_75_index` is built to have 75% annualised volatility. These run
24/7/365, so the annualisation factor is `sqrt(365*24*60)` exactly and not an
approximation of one.

| feed | name | 60 days | first 30 | last 30 | ratio | Parkinson/close |
| --- | --- | --- | --- | --- | --- | --- |
| volatility_10_index | 10 | 10.04 | 10.02 | 10.05 | 1.0036 | 0.868 |
| volatility_25_index | 25 | 24.99 | 24.93 | 25.04 | 0.9994 | 0.870 |
| volatility_50_index | 50 | 49.92 | 49.76 | 50.08 | 0.9984 | 0.871 |
| volatility_75_index | 75 | 74.98 | 74.91 | 75.05 | 0.9997 | 0.870 |
| volatility_100_index | 100 | 99.91 | 99.65 | 100.16 | 0.9991 | 0.870 |
| volatility_10_1s_index | 10 | 9.99 | 10.00 | 9.98 | 0.9990 | 0.910 |
| volatility_25_1s_index | 25 | 25.05 | 25.06 | 25.04 | 1.0020 | 0.908 |
| volatility_50_1s_index | 50 | 50.12 | 50.09 | 50.16 | 1.0024 | 0.909 |
| volatility_75_1s_index | 75 | 74.99 | 75.09 | 74.89 | 0.9999 | 0.910 |
| volatility_100_1s_index | 100 | 100.49 | 100.70 | 100.27 | 1.0049 | 0.907 |
| volatility_150_1s_index | 150 | 150.68 | 151.20 | 150.16 | 1.0046 | 0.906 |
| volatility_250_1s_index | 250 | 250.75 | 250.68 | 250.82 | 1.0030 | 0.909 |

**Mean ratio 1.0013, worst deviation 0.49%, and the split sample does not move
it.** Kurtosis is 2.98-3.02 on every one of them: the returns are Gaussian, not
approximately Gaussian.

Three other pages reached this independently and by other routes, which is as
close to replication as this folder gets: [twins.md](twins.md) puts all twelve
within two standard errors of the advertised figure from tick data,
[cascading.md](cascading.md) finds the twelve *exactly* Brownian at H = 0.50 and
kurtosis 3.00, and [crossing.md](crossing.md) records the same 0.5% in both
halves while looking for something else entirely.

`volatility_200_1s_index` had zero bars in `research.db` and is the only one of
the thirteen not tested.

### The 1s twins are the same law at twice the rate

[generated.md](generated.md) showed V75 and V75(1s) are uncorrelated - independent
draws. This says what they are independent draws *of*: **the same law**. Realised
vol 74.98 against 74.99. Tick rate 0.500/s against 0.995/s, a clean 2:1.

The Parkinson column is the second, unplanned confirmation. A high-low range
estimator equals the close-to-close figure on a continuously sampled diffusion
and falls below it when the bar's extremes are not resolved. The 2-second family
reads **0.870** and the 1-second family **0.909** - the faster tick resolves the
bar's extremes better, in exactly the predicted direction, on every pair. That is
the tick rate showing up in a statistic that was not looking for it.

### Jump indices realise 1.32x their name, and consistently

| feed | name | 60 days | first 30 | last 30 | ratio |
| --- | --- | --- | --- | --- | --- |
| jump_10_index | 10 | 13.27 | 13.24 | 13.30 | **1.3267** |
| jump_25_index | 25 | 32.82 | 33.00 | 32.64 | **1.3128** |
| jump_50_index | 50 | 66.91 | 67.01 | 66.81 | **1.3382** |
| jump_75_index | 75 | 98.96 | 97.60 | 100.29 | **1.3194** |
| jump_100_index | 100 | 131.59 | 130.50 | 132.67 | **1.3159** |

Five instruments, mean 1.3226, range 1.3128-1.3382. A gap that tight across five
separate series is not a measurement error, it is a convention: **the name is the
diffusive volatility and the jumps are extra.** The jump arrives every 22-27
minutes against a documented 20, and the leftover variance
`1.322^2 - 1 = 0.75` of the diffusive variance is the right order for a jump of
that rate and size.

The practical version is simpler: a Jump index is a third more volatile than its
name and the multiplier is stable enough to use.

## Two: there is no volatility clustering, anywhere

This was not on the list of documented properties. It is the one that changes
production code.

Autocorrelation of |1-minute return|, against each series' own shuffle:

| | L1 | L2 | L5 | L10 | L60 | shuffled L1 |
| --- | --- | --- | --- | --- | --- | --- |
| range_break_100_index *(largest of 26)* | +0.0173 | -0.0003 | +0.0004 | +0.0006 | -0.0027 | +0.0031 |
| volatility_75_index | -0.0005 | +0.0009 | -0.0020 | +0.0001 | +0.0009 | +0.0018 |
| boom_500_index | -0.0020 | +0.0036 | -0.0066 | +0.0021 | +0.0039 | -0.0028 |
| **REAL** gold | **+0.2188** | +0.2142 | +0.1687 | +0.1553 | +0.0942 | -0.0009 |
| **REAL** eurusd | **+0.2240** | +0.2156 | +0.1875 | +0.1756 | +0.1203 | -0.0002 |
| **REAL** btc | **+0.3414** | +0.3042 | +0.2567 | +0.2419 | +0.1928 | +0.0003 |
| **REAL** usdjpy | **+0.4529** | +0.3783 | +0.3249 | +0.2997 | +0.1787 | -0.0059 |

**The largest |acf| across all 26 synthetics is 0.017. The smallest across the
six real feeds is 0.219, an order of magnitude larger, and it persists to lag
60.** The shuffle control sits on zero for both, so the estimator is alive.

Variance ratios say the same thing from the other side. Across 26 synthetics at
q=10 the range is **[0.9743, 1.0291]**; across the 26 shuffles it is
**[0.9733, 1.0292]** - indistinguishable, which is what a martingale looks like
when it is read against its own null. The real feeds run 0.889 (btc) to 1.022.

### What that does to the volatility estimate

[volatility.md](volatility.md) found a flat 20-bar mean matching the EWMA
estimator almost everywhere and could not say why. This is why: on a synthetic
they are both estimating a constant, and the constant is published.

Walk-forward, predicting |next 1-minute return| from information before the bar,
on 12 instruments x 2 halves:

| forecast | calibration ratio | MAE vs flat-20 | corr. with next absolute return |
| --- | --- | --- | --- |
| **published constant** | 0.993 - 1.005 | **-2.16%** (better) | undefined - it is constant |
| flat 20-bar mean | 0.9994 - 1.0000 | baseline | -0.015 to +0.007 |
| EWMA, half-life 7 | 0.9999 - 1.0000 | +0.02% | -0.010 to +0.006 |

The constant wins on **all 24 instrument-halves**, by between 1.91% and 2.40%,
mean 2.16%. That consistency is the tell: it is not an edge in forecasting, it is
the *removal of estimation noise* from a quantity that does not move.

And the correlation column is the same result stated as a null. On the six real
feeds the estimators score **0.366 to 0.493**. On all 26 synthetics they score
between **-0.015 and +0.007**. A rolling volatility estimate on a Deriv synthetic
is measuring nothing whatever.

That interval is scattered around zero rather than sitting *on* it, which is the
check this project owes itself: a correlation of exactly 0.0000 would mean a dead
input rather than a null, the way an AUC of exactly 0.5000 did once here. The
estimator is alive, it is computed on 43,000 walk-forward bars per half, and it
carries nothing.

The constant to use, for a bar of `m` minutes on an instrument named `N`:

    E|return| = (N/100) * sqrt(m / 525600) * sqrt(2/pi)

which for `volatility_75_index` at 1m is 8.25 bps, and for a Jump index is the
same formula with `N` multiplied by 1.322.

## Three: Step Index is a fair coin with a fixed step, and that closes it

Deriv's subtitle is the most specific claim on the book - *equal probability of
up/down movement with a fixed step size of 0.1* - and it is the most specific
claim that survives contact with the data.

**86,393 ticks in 86,400 seconds. Zero unchanged ticks. 86,391 moves of exactly
0.1 and one of 0.2** - which is a dropped tick, not a different step.

| | ticks | 60 days of bars |
| --- | --- | --- |
| p(up) | 0.500093 | **0.499734** |
| standard error | 0.001701 | **0.000220** |
| z | +0.05 | -1.21 |
| first half | 0.497893 | 0.499875 |
| second half | 0.502292 | 0.499593 |
| sign acf, lags 1-30 outside +-3/sqrt(n) | **none** | |
| Wald-Wolfowitz runs z | **-1.354** | |

The control earns its place here. The identical measurement on `gold` gives sign
acf at lag 1 of **-0.118** and a runs z of **+91.5** - the bid-ask bounce,
loud and unmistakable. On `eurusd`, acf1 = **-0.400** with eleven lags outside
the band. The detector finds serial dependence where serial dependence exists and
finds none on Step Index.

### And the trade is arithmetic, so there is nothing to optimise

A fixed step and a fair coin make a symmetric barrier trade a gambler's ruin
problem with *exact* probabilities. Target `T` steps, stop `S` steps: the hit
probability is `S/(S+T)` and the gross expectancy is zero. The spread is
**0.1 - exactly one step** - so the whole expectancy is minus the spread.

Replayed with non-overlapping entries, spread charged
([`genstop.py`](harness/genstop.py)):

| stop (spreads) | target | hit rate | theory | net R | theory |
| --- | --- | --- | --- | --- | --- |
| 5 | 1R | 0.5002 / 0.4994 | 0.5000 | -0.1988 / -0.2012 | **-0.200** |
| 5 | 2R | 0.3533 / 0.3517 | 0.3333 | -0.1977 / -0.2023 | **-0.200** |
| 5 | 3R | 0.2729 / 0.2714 | 0.2500 | -0.1967 / -0.2033 | **-0.200** |
| 10 | 1R | 0.5007 / 0.4979 | 0.5000 | -0.0979 / -0.1021 | **-0.100** |
| 25 | 1R | 0.4960 / 0.4960 | 0.5000 | -0.0352 / -0.0448 | **-0.040** |
| 50 | 1R | 0.4872 / 0.4615 | 0.5000 | -0.0123 / -0.0277 | **-0.020** |

Expectancy is `-spread/stop_distance`, exactly, at every geometry and on both
sides. There is no reward-to-risk to tune, no hit rate to improve, and no exit
policy that helps - the eighteen tried in [exiting.md](exiting.md) would all
return the same number here, which is one thing this saves.

### The trap this run walked into, and how the data caught it

The tick sample's `p(up) = 0.500093` fed through the gambler's ruin gives a
100-step barrier a hit probability of 0.5093 against a break-even of 0.5050, and
the harness duly printed **+0.085 net**. It looks like an edge at large k.

It is the 86,393-tick sample's noise amplified by 100. The 60-day bar sample -
5.18 million implied flips, standard error 0.000220 - puts the bias at
**-0.000266**, and the bias a 100-step barrier needs is **23 standard errors**
away in the wrong direction. Nothing is there.

The general lesson is the one [forecasting.md](forecasting.md) paid for twice:
a statistic compounded k times needs a sample sized for the compounded quantity,
not the raw one.

## Four: Boom and Crash - the published rate is right, and the arithmetic closes

[spiking.md](spiking.md) measured `boom_500_index` alone and left the family
open, asking whether the grind is near-deterministic and whether the arithmetic
on it pays. Both answers are here, and one of them is not what that page assumed.

### The rate is what the name says, on all six

At tick resolution, with a spike defined as a move exceeding 10x the median
absolute move:

| feed | stated | ticks/spike | ratio | min/spike | waiting-time CV |
| --- | --- | --- | --- | --- | --- |
| boom_300_index | 300 | 267.7 | 0.892 | 4.71 | 1.103 |
| boom_500_index | 500 | 529.4 | 1.059 | 9.04 | 1.070 |
| boom_1000_index | 1000 | 908.3 | 0.908 | 15.30 | 0.844 |
| crash_300_index | 300 | 329.0 | 1.097 | 5.53 | 0.984 |
| crash_500_index | 500 | 507.7 | 1.015 | 8.71 | 1.051 |
| crash_1000_index | 1000 | 973.8 | 0.974 | 16.69 | 0.946 |

All six within 11% of the published rate, which is inside one to two Poisson
standard errors on counts of 86 to 306. **The counts are identical at detection
thresholds of 5x, 10x and 20x** - a rate that does not move with the threshold is
a property of the generator rather than of the detector.

The control settles it. `volatility_75_index` and `volatility_100_index` through
the same detector return 39 and 36 events at 5x and **zero at 10x**, where
boom/crash return 94 to 306 at every threshold. The spike is a separate
mechanism, not a tail.

**The waiting time is memoryless across the whole family** (CV 0.84 to 1.10
against 1.00), which extends spiking.md's single instrument to all six: nothing
can call a spike anywhere in this family.

### The grind is deterministic per minute and not per tick

spiking.md called the grind "nearly deterministic" from the per-minute down-leg
distribution, which sat inside a 0.24 band. At tick resolution it does not:

| feed | grind step | grind step CV | spike median | spike/grind |
| --- | --- | --- | --- | --- |
| boom_300_index | 0.00350 | 0.631 | 0.933 | 266x |
| boom_500_index | 0.00900 | 0.661 | 3.964 | 440x |
| boom_1000_index | 0.01350 | 0.671 | 12.220 | 905x |
| crash_300_index | 0.01600 | 0.675 | 4.762 | 298x |
| crash_500_index | 0.00550 | 0.654 | 2.628 | 478x |
| crash_1000_index | 0.00550 | 0.655 | 4.972 | 904x |

**The grind step has a coefficient of variation of 0.63 to 0.68.** What
spiking.md measured was sixty of those summed into a minute, which concentrates
by `sqrt(60)` to a CV near 0.085. The determinism is the aggregation, not the
generator - and that matters, because it means the grind cannot be relied on
tick by tick, only in expectation over a hold.

### The arithmetic closes, so there is nothing to collect

The question spiking.md posed exactly: does `(1-p)*grind + p*spike` come to zero?

| feed | closure | SE of the tick mean | z |
| --- | --- | --- | --- |
| boom_300_index | +2.486e-04 | 2.776e-04 | **+0.90** |
| boom_500_index | -7.140e-04 | 8.871e-04 | **-0.80** |
| boom_1000_index | +1.022e-03 | 2.079e-03 | **+0.49** |
| crash_300_index | +1.324e-03 | 1.237e-03 | **+1.07** |
| crash_500_index | +6.408e-04 | 5.304e-04 | **+1.21** |
| crash_1000_index | +2.200e-04 | 7.829e-04 | **+0.28** |

All six inside 1.3 standard errors. **The spike pays for the grind exactly.**

Sixty days of one-minute log returns agree. Of thirteen feeds tested, **twelve
have |z| below 2 in both halves and in the pooled figure**, and nine are below 1
throughout. The thirteenth is `boom_300_index` at a pooled **-2.52**, halves
-1.89 and -1.67. Thirteen independent draws produce a |z| past 2.52 about 14% of
the time, neither half of this one clears 1.9, and the direction it points -
Boom drifting down, the grind winning - is the direction that the tick-level
closure above rules out at +0.90 SE. It is not a finding; it is the largest
number in a table of thirteen.

And at trade level, the non-overlapping replay in `genstop.py` covers 192 cells -
eight instruments, four stop widths, three targets, both sides - and **not one
reaches z = 2, let alone with both halves of the day agreeing.** The largest
expectancy anywhere is `crash_500` long at a 50-spread stop and a 3R target:
**+0.274R on 87 trades, z = +1.04**, from +0.086 in the first half to +0.457 in
the second. The next five look the same - a hundred-odd trades, z near 1, halves
that disagree by a factor of four.

## Five: Range Break breaks at the stated relative rate, and it cannot be traded

Range Break 100 and 200 are documented as breaking out after 100 and 200
range-bound periods. Whatever "a range-bound period" means operationally, the two
indices are a control for each other: **RB100 must break twice as often as
RB200**.

The break is not a threshold choice on these series. Like Step Index, they tick
once a second and move exactly one unit - 99.98% and 99.99% of ticks - so a move
larger than one unit is a different event, and a one-minute bar cannot span more
than sixty units by stepping. Counting bars whose range exceeds 66:

| feed | breaks in 60 days | minutes per break | waiting-time CV |
| --- | --- | --- | --- |
| range_break_100_index | 998 | 86.6 | **1.003** |
| range_break_200_index | 483 | 178.9 | **1.075** |

**Ratio 2.066, 95% CI [1.856, 2.300], against a documented 2.000.** The 24 hours
of tick data give 2.857 on counts of 20 and 7, which is the same answer with an
interval wide enough to contain almost anything - the bar sample is the one to
read.

**And the break arrival is memoryless too** (CV 1.003 and 1.075), so it is the
Boom spike again: a known rate, an uncallable time.

Two trades were tested on it and neither survives:

* **Does the break carry?** Signed move after a break, spread charged, split by
  half: RB100 at 60 minutes reads +3.50 pooled (z +0.91) from +1.20 and +5.74;
  RB200 reads +9.75 (z +1.40) from **-9.23 and +27.22**. Nothing is stable.
* **Can the range be faded?** Mean move after a new 60-tick extreme, both legs
  signed as profit: RB100 gives +0.114 gross at 10 ticks against a spread of
  **1.000** - 11% of the cost of the trade - and the same series' own shuffle
  gives **+0.298**, larger than the real thing.

The zigzag "bounces per break" measurement in `genrange.py` is reported in the
harness and is **not** reported here as a result. It is detector-dependent -
2.005, 1.870 and 1.772 for RB100 at three thresholds - and it orders RB100 above
RB200, which is backwards from what the documentation implies. It is measuring my
bounce definition, not Deriv's.

## Six: the one finding that costs money today

On `boom_500_index`, **84,506 of its 84,701 tick-to-tick moves are down and 162
are up - and 160 of those 162 up-moves are spikes.** The same holds across the
family: **96.7% to 100%** of adverse-direction moves are spikes.

Boom's price is monotone decreasing except where it jumps. So a stop above a
Boom short can never be *walked* to. It is only ever *jumped* over, and the fill
lands wherever the spike lands.

Non-overlapping entries on 24 hours of ticks, target 1R, spread charged, all
rows at a stop of **five spreads** - the width with the largest non-overlapping
sample. "Walked" and "jumped" say which side the *stop* sits on, not which way
the trade leans.

| feed | side | stop is | n | stop hit | mean slippage | p90 | max | frac > 0.5R | realised loss |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| boom_300_index | long | walked | 3,089 | 90.8% | +0.030R | +0.06 | +0.14 | 0.000 | -1.030R |
| boom_300_index | **short** | **jumped** | 3,089 | 9.2% | **+9.93R** | +19.91 | +36.21 | **0.979** | **-10.93R** |
| boom_500_index | long | walked | 2,478 | 94.0% | +0.021R | +0.05 | +0.10 | 0.000 | -1.021R |
| boom_500_index | **short** | **jumped** | 2,478 | 5.9% | **+13.96R** | +28.70 | +40.24 | **0.973** | **-14.96R** |
| boom_1000_index | long | walked | 1,754 | 94.8% | +0.014R | +0.03 | +0.07 | 0.000 | -1.014R |
| boom_1000_index | **short** | **jumped** | 1,754 | 5.2% | **+18.81R** | +41.25 | +59.57 | **0.934** | **-19.81R** |
| crash_500_index | short | walked | 2,504 | 93.9% | +0.020R | +0.04 | +0.11 | 0.000 | -1.020R |
| crash_500_index | **long** | **jumped** | 2,504 | 6.1% | **+13.09R** | +24.64 | +44.69 | **0.980** | **-14.09R** |
| crash_1000_index | **long** | **jumped** | 1,725 | 4.6% | **+19.09R** | +37.54 | +62.91 | **0.950** | **-20.09R** |
| volatility_75_index | either | - | 435 | 49.7% | +0.061R | +0.14 | +0.29 | **0.000** | -1.061R |
| step_index | either | - | 2,435 | 50.0% | +0.200R | +0.20 | +0.20 | **0.000** | -1.200R |

**A stop on the spike side of Boom or Crash fills 10 to 19 R past where it was
placed.** On the grind side of the same instrument, at the same width, it fills
at +0.02R. The asymmetry is a factor of six hundred.

The controls are what make it readable. `volatility_75_index` has no spike
mechanism and its stops fill at +0.061R with **not one trade in 435** slipping
more than half an R. Step Index is the deterministic case: a fixed-increment walk
crosses a level by **at most one increment**, so the loss is bounded at
`stop + 0.1` whatever the stop is, and every trade in the replay lands exactly
there. (Exactly one step rather than something between zero and one step is a
float-boundary effect in the crossing test; the *bound* is the real content.)

Widening the stop shrinks the multiple but never the problem:

| stop width (spreads) | boom_500 short, mean slippage | realised loss | n |
| --- | --- | --- | --- |
| 5 | +13.96R | -14.96R | 2,478 |
| 10 | +6.81R | -7.81R | 1,277 |
| 25 | +2.44R | -3.44R | 528 |
| 50 | +1.02R | -2.02R | 248 |

Even at fifty spreads the realised loss is **twice** the planned one.

### What this changes, and how it would be sized

Every position on this book is sized off its stop distance.
[stops.md](stops.md) reads stops as the whole loss and
[giveback.md](giveback.md) prices the trail against the stop, and both treat the
stop distance as the risk. **On the spike side of six instruments it is not.**

Concretely, for a short on Boom or a long on Crash:

* the risk per unit is not `D`, it is `D * (1 + mean_slip)` - on `boom_500`
  a factor of **2.0 at a 50-spread stop, 3.4 at 25, 7.8 at 10 and 15.0 at 5**;
* so a position sized for -1R at a ten-spread stop is carrying **7.8R** of
  actual tail;
* and the tail is not rare conditional on being stopped - **93% to 98%** of
  stopped trades slip past half an R.

The sizing rule that follows is arithmetic, not a model: **divide the size on the
spike side by the measured slippage multiple for the stop width in use**, or do
not take the spike side at all. The multiple is a published-rate consequence
(spike size over stop distance), so it can be computed for any stop width without
re-running anything.

This is also the honest resolution of the Boom asymmetry in
[instruments.md](instruments.md). That page withdrew "Boom loses because of the
spike" on the grounds that the R-multiples did not show it. They would not:
**the recorded R on a gapped stop is the planned R, not the realised one.** The
instrument was not mis-measured, the risk denominator was.

### The same effect, reached from the other end

[convexity.md](convexity.md) arrived at this from a replay rather than from
ticks, and it is worth reading the two together because neither could have found
the other's half. That page measured an apparent Boom/Crash asymmetry of 0.04R
with no stop, 0.32R with a flat stop and **0.94R with a half-width stop**, and
inferred from the scaling - monotone in the spike size, absent on every symmetric
feed - that the stop is being filled at a price no spike ever offered.

This page measures that fill directly. **The inference was right and the size of
it is +9.9R to +19.1R at a five-spread stop.** Between them the two results say
the same thing twice: an R-multiple on the spike side of Boom or Crash is a
number about the risk rule, not about the instrument, and any replay that caps
the loss at the stop is reporting a phantom.

## The failure conditions, as they were written before the run

Each harness names its own kill conditions in its docstring, before any number
was seen. Here is the ledger.

| stated in | condition that would have killed it | outcome |
| --- | --- | --- |
| `genvol.py` | realised/nominal moves more than a few percent between halves | **survived** - largest half-to-half move is 0.69% (v150 1s) |
| `genvol.py` | realised/nominal does not order with the name | **survived** - 12 of 12 within 0.49% |
| `genvol.py` | synthetics cluster like the real controls | **survived** - 0.017 against 0.219 |
| `genvol.py` | a statistic lands on *exactly* its null | **survived** - nothing is exactly 0.0000 or exactly 1.0000 |
| `genstep.py` | tick differences are not concentrated on one magnitude | **survived** - 99.9988% on one value |
| `genstep.py` | up-fraction inside 3 SE of 0.5 in both halves, and no sign acf outside the band | **the edge died, as expected** - both hold |
| `genstep.py` | the control shows no bid-ask bounce | **survived** - gold acf1 -0.118, runs z +91.5 |
| `genspike.py` | measured rates do not order 300 < 500 < 1000 | **survived** - 268, 529, 908 and 329, 508, 974 |
| `genspike.py` | grind step CV above 0.2 at tick resolution | **failed** - it is 0.63-0.68, so spiking.md's "nearly deterministic" is an aggregation effect |
| `genspike.py` | mean per-bar return within 2 SE of zero in both halves | **the drift died, as expected** - 13 of 13 feeds |
| `genrange.py` | RB100/RB200 break-rate ratio far from 2 at every threshold | **survived** - 2.066 on bars, CI [1.86, 2.30] |
| `genrange.py` | the fade is smaller than the spread | **the fade died** - 11% of the spread, and below its own shuffle |
| `genstop.py` | mean slippage on stopped trades near zero | **failed loudly** - +9.9R to +19.1R on the spike side |
| `genstop.py` | the control slips too, so the fill rule is wrong | **survived** - v75 slips +0.061R, no trade past 0.5R |

Two conditions fired. One - the grind CV - corrects a claim this folder already
published. The other - the stop slippage - is the finding.

## What none of this says

**It does not find a directional edge, and there is none to find.** Every
generator here is a martingale at every horizon tested, verified four ways -
variance ratios indistinguishable from each series' own shuffle, tick-level
closure within 1.3 SE on all six spike indices, 60-day drift inside 2 SE in both
halves on all thirteen feeds, and 192 replayed barrier cells with not one
survivor. The published parameters describe a fair game and the venue is
running the generator it describes.

**The cost is the whole game and it is exactly known.** Step Index and Range
Break cross for exactly one step. Boom and Crash cross for **5.7 to 11.0 grind
ticks**, so a grind trade must be held six to eleven seconds before it has paid
for itself - and holding longer adds nothing, because the arithmetic closes. The
Jump and Volatility families cross for 2.0 and 2.6-2.8 median moves.

**Sixty days and one venue.** If Deriv re-parameterised a generator we would not
see it from this sample, and the whole page is a statement about the feed
`research.db` collected, not about the instruments in principle. The Volatility
family's 0.5% agreement is tight enough that a drift in the parameter would show
up quickly, which is the cheap monitor this suggests.

**Twenty-four hours of ticks, sixty days of bars.** The slippage result rests on
tick data covering one day; the entries are non-overlapping but they still
resolve on 86 to 306 distinct spikes per instrument. The *mechanism* is not
statistical - all adverse ticks are spikes - so the direction of the result is
safe, but the multiples would move on a longer sample.

**The Range Break bounce count is not measured.** Only the relative break rate
is, and the absolute "100 bounces" claim needs Deriv's definition of a bounce
rather than mine.

**`prices.db` on the lab is corrupt and was not touched.** Everything here is
`research.db`: `bars` at 86,411 one-minute rows per synthetic over 60 days, and
`ticks` at 24 hours with bid and ask, which is where every spread in this
document comes from.

## Seven: the pipeline, as a hypothesis - and which stage is actually soft

**This section is a hypothesis under test, not a measurement, and it is placed
after the findings deliberately so it cannot be read as one.** It was put
forward from the desk on 2026-09-12 and it reframes what is worth attacking.

The proposal is that a Deriv synthetic is not one object but a **chain**:

    CSPRNG -> uniform u -> inverse-normal Phi^-1(u) -> price recursion -> quantise to the quote grid -> publish

The value of the decomposition is that it separates one hopeless target from
three soft ones, and until it was written down this folder had been treating the
generator as a single box.

| stage | what is known | how hard |
| --- | --- | --- |
| the source | `rebuildpredict.py` attacked it three ways - k-tuple spectral tests, MT19937 untempering, truncated-LCG lattice reduction - and found nothing | cryptographic; effectively closed |
| the inverse-normal | **never examined** | deterministic, finite precision |
| the recursion | **never identified**; two standard conventions differ by `sigma^2 T / 2` | deterministic |
| the quantiser | partly read already: `frac_zero` at AUC 0.686 opened the quote-lattice question and `n_distinct` exposed first a float-precision artefact and then a real defect in the published grind specification | visible in every tick |

**Everything after the source is deterministic.** That is the whole point. A
regulated venue's RNG is not going to fall over, and this folder has already
spent a study confirming it. But a deterministic, finite-precision stage is a
different class of target, and two consequences follow that are worth stating
plainly:

**The recursion has a free convention and nobody here knows which one runs.**
`S * exp(-sigma^2/2 dt + sigma dW)` makes **price** a martingale and its median
drift down; `S * exp(sigma dW)` makes **log price** a martingale and its price
drift up. Both are standard, both ship in real systems, and the difference is
`sigma^2 T / 2`. `till_infinity/structures/vol/projection.py` now carries both
and scores each by the probability integral transform on every closed bar, so
the answer accumulates from a structure the desk was going to run anyway. It is
slow: the conventions differ by **0.4% of one standard deviation at 1h** and
about 2% at 1d, so against the `1/sqrt(12 n)` standard error of a mean PIT it
needs of order **50,000 settled observations**. `Calibration.resolved` reports
whether that bar has been cleared rather than naming a winner early.

**If the inverse-normal is a lookup table or limited precision, the set of
achievable increments is finite and enumerable.** That is the sharpest testable
consequence on this page and it is the one that would genuinely matter. **It is
also the easiest place on this page to produce a spectacular false positive**,
because quote quantisation *alone* makes observed price differences discrete -
so the null is "discrete because the grid is discrete", not "continuous", and a
test that does not carry that null will report a crack that is not there. The
question has to be asked of the *implied pre-quantisation* increment, and any
detector has to be shown to stay silent on a simulator built with a proper
continuous inverse-normal before it is pointed at Deriv.

Two further questions fall straight out of the chain and neither has been asked:

* **Does quantisation error accumulate?** If the generator keeps a
  full-precision internal price and rounds only for display, successive rounding
  residuals are independent. If it feeds the *rounded* price back into the
  recursion, they random-walk and the published path drifts from the ideal one.
  The residual sequence decides it, and either answer is a fact about the
  architecture.
* **How many bits of the underlying uniform survive to the published quote?**
  This is what decides whether the state-recovery attacks in `rebuildpredict.py`
  were unsuccessful or **impossible**, and those are different sentences. If a
  tick carries under 32 bits, the MT19937 attack cannot be run at all, and
  saying so is worth more than another null result.

The investigation lives in [pipeline.md](pipeline.md). Nothing in this section
has been measured yet, and when it is, whatever survives its controls moves up
into the numbered findings above and whatever does not gets written down here as
refuted.

## What is worth doing next

1. **Replace the volatility estimator with the published constant on the 72% of
   the book that is generated.** It is better calibrated, it costs 2.16% less
   error, it needs no warm-up, and it cannot misread a regime that does not
   exist. The formula is in section two and the Jump multiplier is 1.322.
2. **Apply the slippage multiple to sizing on the spike side of Boom and Crash,
   or stop taking that side.** This is the only item here that changes a
   position's risk rather than its denominator.
3. **Stop optimising barriers, exits and reward-to-risk on synthetics.** The
   expectancy is `-spread/stop` and it does not depend on the geometry. Whatever
   is worth doing on this book is in entry timing on the real instruments, or in
   cost, and not here.
4. **Monitor the realised-to-nominal ratio as a venue check.** A generator whose
   realised volatility leaves the 0.995-1.005 band it has held for 60 days is
   telling us something changed, and that is a cheap alarm on 26 feeds.
5. **Identify the middle of the pipeline** - section seven. The source is
   closed and the quantiser is half-read, but the inverse-normal and the
   recursion have never been looked at, and both are deterministic. The drift
   convention is already accumulating live behind `STRUCTURES_PROJECTION`; the
   increment-atom question needs a detector validated against a simulator with
   known ground truth before it is worth running on real data at all.
