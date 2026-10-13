# Does the mean exist, and how many trades decide it

Every expectancy this desk has reported is a **sample mean** - `edge/cost` per
trade, nats per span, median gains per instrument - and a sample mean summarises
a distribution only when the distribution has one. Taleb's technical claim is
that for a sufficiently heavy tail it does not, and unlike most of that argument
it is estimable.

The harness is `research/ideas/pnl_concentration.py`.

## The tail index decides which moments exist

For a payoff whose tail falls like `x^-alpha`: above 2 the variance is finite
and a sample mean converges at the usual rate; between 1 and 2 the **variance is
infinite**, so a standard error does not mean what it says; below 1 **the mean
does not exist** and a sample mean is a statement about which extremes landed in
the window.

Hill's estimator reads it off the top `k` order statistics and is notoriously
sensitive to `k`, so `k` is swept and the sweep is printed. An alpha quoted
without its `k` is an opinion.

## The planted arm recovers a known index at every k

| planted | mean | trimmed | top 1% | half | `alpha` at 0.01 / 0.025 / 0.05 / 0.1 |
| --- | ---: | ---: | ---: | ---: | --- |
| gaussian, `alpha` infinite | +0.0023 | +0.0028 | 0.036 | 0.238 | 9.78 / 7.45 / 5.78 / 4.70 |
| student t, `alpha` 3 | -0.0062 | -0.0017 | 0.081 | 0.183 | **2.94 / 2.61 / 2.69 / 2.45** |
| student t, `alpha` 1.5 | +0.1254 | +0.0221 | 0.265 | 0.059 | **1.55 / 1.47 / 1.42 / 1.45** |
| student t, `alpha` 0.8 | **-66.23** | **-0.078** | **0.948** | **0.001** | **0.74 / 0.77 / 0.78 / 0.80** |

A Student-t's tail index *is* its degrees of freedom, and Hill recovers each one.
The last row is what the measure is for: a mean of `-66.2` against a trimmed
mean of `-0.078`, a factor of 850, with 1% of observations carrying 94.8% of the
total.

**It also showed that one of this harness's own columns is too coarse.** The
`alpha = 0.8` row reads `flips = no`, because the sign survived by luck. The
**ratio** of the mean to the 1%-trimmed mean is the informative number and
`flips` is not, which is why the ratio was added.

## Raw returns sit at the inverse-cubic law

| | `alpha` at 0.025 to 0.1 | kurtosis | top 1% | half |
| --- | --- | ---: | ---: | ---: |
| traded, 8 instruments | **2.39 to 3.45** | 12.5 to 36.2 | 0.070 to 0.086 | 0.17 to 0.19 |
| generated, 6 instruments | 3.23 to 10.28 | 3.0 to 6.0 | 0.036 to 0.058 | 0.22 to 0.28 |

`alpha` near 3 is the textbook result for financial returns, and it says the
mean and the variance exist. The `Volatility_100_1s_Index` reads `10.28` at
`k = 0.01` against the Gaussian planted row's `9.78`, which is the control
working.

### And it corrects a statistic reported elsewhere

`alpha < 4` means **the fourth moment does not exist**, and
`statespace-relationship-screen.md` and others quote "traded return kurtosis
20.07 against the synthetics' 3.19" as the fat-tail confirmation. Kurtosis is a
fourth moment, so on a series with `alpha` near 3 it has **no population value**
- the 20.07 is a property of the sample, which is why it ranges 12.5 to 36.2
across instruments here.

The **ordering** is robust and the conclusion stands. It is better stated as
`alpha` of 2.4 to 3.4 against 3.2 to 10.3, which is a quantity that exists.

`ratio` and `flips` are not readable in this arm: a raw return mean is
approximately zero by construction, so the ratio divides a near-zero by a
near-zero. The columns to read here are `alpha`, `top 1%` and `half`.

## Barrier payoffs are Mediocristan, because the geometry truncates the tail

| pooled | mean | trimmed | **ratio** | top 1% | half | kurtosis | `alpha` 0.025 to 0.1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| traded, n = 6,472 | -0.0646 | -0.0582 | **1.1** | 0.035 | 0.385 | **2.7** | **3.44 / 3.09 / 3.33** |
| generated, n = 4,854 | -0.2024 | -0.1934 | **1.0** | 0.019 | 0.406 | 1.3 | 9.52 / 8.71 / 8.39 |

**This is the answer to the question that prompted the audit.** The expectancies
this desk reports are computed on barrier trades, and a barrier payoff is
**bounded by the barrier plus its overshoot**. So even on a return series with
`alpha` near 3, the payoff has `alpha` above 3, a kurtosis of **2.7** - below
Gaussian - and a mean that moves 10% when the largest 1% of trades is removed.

The stop is what removes the problem. A strategy with a stop cannot be
Extremistan in its payoff however heavy the underlying is, which is a reason to
have one that has nothing to do with risk tolerance.

## What is fragile is a per-instrument mean

`USDCAD` flips: a mean of `-0.0355` becomes `+0.0030` when 1% of its 809 trades
are removed, a ratio of 12.0. So a per-instrument expectancy on roughly 800
trades is not safe, and the pooled figure on 6,472 is.

That is a sample-size statement rather than a tail statement, and it sets a
floor: **an expectancy quoted per instrument needs its trimmed mean beside it**,
and the session's pooled numbers do not.

## What to use

* **Quote `alpha`, not kurtosis**, on anything with a tail. Kurtosis has no
  population value at `alpha` below 4 and ranges by a factor of three across
  instruments here for that reason.
* **Sweep `k`** and print the sweep. Hill at one `k` is an opinion.
* **Read the ratio, not the sign flip.** A planted `alpha` of 0.8 reads 850 on
  the ratio and `no` on the flip.
* **The session's pooled expectancies are safe**: `alpha` above 3, ratio 1.1.
  The per-instrument ones are not, and one of eight flips.

## Related

* [Synthetics are a poor tail control](statespace-relationship-screen.md) - the
  kurtosis comparison this corrects to an `alpha` comparison
* [Convexity](statespace-conformal-band.md) - the barrier payoffs this audits,
  and the measurement whose baseline is still unexplained
