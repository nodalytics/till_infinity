# Calibrating `Paired`'s threshold, and why the calibration does not transfer

`learning/focus.py` sets `THRESHOLD = 12.0` and says so plainly: "chosen to be
conservative rather than fitted". `statespace-stat-arb-and-volume.md` lists
the gap as a debt - "`Paired`'s threshold is still uncalibrated against a
stationary stream, which `focus.py` names as the right measurement and skips".

This is that measurement. It has three parts and the third is the one that
matters.

## 1. On a stationary stream, the threshold is enormously conservative

The detector is fed i.i.d. standard normal, which is the right null rather
than a convenient one: `Paired` feeds it `last_standardised`, and under a
correctly specified member that series is standard normal **by construction**.

Average run length to a false alarm, in observations:

| threshold | measured ARL-0 | med/mean | censored | days at 1h | pair, days |
| --- | --- | --- | --- | --- | --- |
| 4.0 | 170 | 0.73 | 0.00 | 7 | 4 |
| 6.0 | 894 | 0.68 | 0.00 | 37 | 19 |
| 8.0 | 5,122 | 0.72 | 0.00 | 213 | 107 |
| 10.0 | 36,997 | 0.71 | 0.00 | 1,542 | 771 |
| **12.0 shipped** | **216,788** | 1.15 | 0.40 | 9,033 | 4,516 |
| 14.0 | 1,898,244 | 1.06 | 0.90 | 79,094 | 39,547 |
| 16.0 | 11,328,277 | 1.01 | 0.98 | 472,012 | 236,006 |

The pair column halves the interval, because `Paired` runs an up instance and
a down instance and either can alarm.

**The censored rows are estimated, not measured, and the note says which.**
Forty percent of runs at the shipped threshold reach the 200,000 cap without
alarming, so a raw mean is bounded by the cap. A CUSUM run length on a
stationary stream is close to exponential, so the fraction that fired gives
the mean: `mean = -cap / ln(1 - fired)`. The assumption is **checked** -
`med/mean` is 0.693 for an exponential and the uncensored rows come in at 0.68
to 0.73 - and it is checkable only where there is no censoring, so the rows at
14 and above rest on extrapolation and should be read as "beyond measurement"
rather than as numbers.

## 2. The delay it buys, and the trade-off is extremely one-sided

Observations to detect a real shift in the mean of the standardised stream:

| threshold | 0.25 sigma | 0.5 sigma | 1.0 sigma | 2.0 sigma |
| --- | --- | --- | --- | --- |
| 4.0 | 50.0 | 19.8 | 7.3 | 2.6 |
| 8.0 | 186.2 | 55.3 | 15.9 | 4.6 |
| **12.0** | **328.9** | **85.6** | **22.4** | **6.3** |
| 14.0 | 399.1 | 104.6 | 27.6 | 7.5 |
| 16.0 | 476.8 | 120.8 | 30.1 | 8.3 |

**The false-alarm interval grows exponentially in the threshold and the delay
grows linearly.** Going from 12 to 14 multiplies the quiet by 8.8 and the
one-sigma delay by 1.23. So there is no optimum in this range: on a stationary
stream, higher is strictly better, and the shipped 12 is if anything *not*
conservative enough on this criterion.

Which would be the end of it, except that no real series is stationary.

## 3. The calibration does not transfer, and nothing rescales it into place

A walk on real data, its standardised residuals fed to the detector, alarms
counted and the detector reset each time. Observations per alarm:

| EURUSD | 4 | 6 | 8 | 10 | 12 | 14 |
| --- | --- | --- | --- | --- | --- | --- |
| **i.i.d. floor** | 170 | 894 | 5,122 | 36,997 | **216,788** | 1,898,244 |
| as fed by `Paired` | 217 | 394 | 649 | 980 | **1,389** | 1,851 |
| rescaled by a constant | 80 | 142 | 217 | 286 | 394 | 485 |
| rescaled by a trailing spread | 78 | 149 | 226 | 318 | 463 | 543 |

**At the shipped threshold a real series alarms every 1,389 observations where
the theory says 216,788 - a factor of 156.** XAUUSD gives 1,428 and BTCUSD
1,389, so it is not one instrument. At threshold 14 the factor is 1,025.

So the practical reading of the shipped threshold is **58 days at 1h, or 29
days for the pair** - conservative, but not the twenty-five years the
stationary table implies.

### The control that locates the cause

`Volatility_75_Index` is a constant-volatility process, and on it the
calibration transfers almost exactly once the scale is right:

| `Volatility_75_Index` | 4 | 6 | 8 | 10 |
| --- | --- | --- | --- | --- |
| i.i.d. floor | 170 | 894 | 5,122 | 36,997 |
| trailing spread | **150** | **793** | **4,166** | **49,990** |

So the estimator is correct and the theory is right. What breaks it is the
**traded** series, and the difference between those and `Volatility_75_Index`
is volatility clustering.

### Two repairs tried, both fail

* **A constant rescale.** The residuals' standard deviation is 0.71 rather
  than 1.0 - the member's predictive spread is about forty percent too wide,
  which is the same fact as the walk over-covering at one sigma in
  `statespace-backtest.md`. Dividing by it makes things **worse**, 394 against
  1,389, because scaling the residuals up makes the CUSUM cross sooner. The
  under-dispersion had been protecting the detector by accident.
* **A trailing scale**, which is what `focus.update`'s own `scale` argument
  exists for - its docstring says "volatility moves and a detector calibrated
  to last week's is measuring the wrong thing this week". It gives 463, which
  is no better than the constant.

**Neither works because the problem is not the scale.** It is the conditional
shape: a CUSUM on the mean of a stream with clustered, fat-tailed deviations
accumulates faster than on an independent one, however the stream is
normalised. This is the third place in this package the same wall has been hit
- conditioning on volatility made the three-sigma band *worse* in
`statespace-fractals.md`, and the members' bands under-cover at two sigma
after conditioning in `statespace-backtest.md`. A variance model sets a scale
and these are questions about a shape.

## What to do

* **Keep 12, and quote 1,389 observations rather than 216,788.** The shipped
  value is defensible; the number to put beside it is the measured one.
* **Calibrate on the series, not on the theory.** The per-instrument numbers
  above are what a desk should use, and they are cheap to recompute for any
  new instrument.
* **Do not reach for a trailing scale here.** It is the natural fix, the
  module anticipates it, and it does not work - measured.
* **If a stated false-alarm rate is ever a requirement**, the honest route is
  a threshold chosen per instrument from its own residual stream, which is
  what the third table is.

The harness is `research/ideas/paired_threshold.py`. The stationary arm is
parallel across the lab's cores, because one run at the shipped threshold
takes about sixty thousand observations and the nine thresholds at four
hundred runs would be three hours serially.
