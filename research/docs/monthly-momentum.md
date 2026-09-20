# Momentum at daily-to-monthly horizons: it is bitcoin

Measured 2026-09-20 on the broker's own daily bars, 42 instruments, 2010-08-22 to
2026-09-19 - 145,485 bars. These were the candidates `directional-edge.md` named as
having the strongest published evidence, at the horizons where cost stops being the
whole story: a month of movement against a 0.3bp spread.

Both forms reduce to holding crypto.

## Time-series momentum

Does an instrument's own past return predict its next? Non-overlapping windows,
**clustered by period** because 22 instruments are nowhere near 22 independent bets.

| lookback | hold | periods | mean | t | annualised |
|---|---|---|---|---|---|
| 1m | 1m | 265 | 0.44% | +2.80 | 5.5% |
| 3m | 1m | 263 | 0.54% | **+3.34** | 6.7% |
| 6m | 1m | 260 | 0.46% | +2.75 | 5.6% |
| 12m | 1m | 254 | 0.45% | +2.87 | 5.5% |

Then the same test with **btc, eth and sol removed** - three of twenty-two:

| lookback | with crypto | without | without, vol-scaled |
|---|---|---|---|
| 1m | +1.10 | **-0.55** | -0.82 |
| 3m | **+3.34** | **+0.44** | +0.55 |
| 12m | **+2.87** | **+0.20** | +0.55 |

Per-instrument contribution makes it plain: **btc +5.72% a month, eth +5.05%, sol
+3.22%**, against gold +0.50% and spx500 +0.26%.

## Cross-sectional momentum

Rank the instruments, buy the top third, sell the bottom third. A dollar-neutral
portfolio gives one return per period, so it needs no clustering - the portfolio is
the cluster.

| variant | mean | t | annualised |
|---|---|---|---|
| equal weight, with crypto | 1.81% | +3.56 | **24.1%** |
| **equal weight, no crypto** | **0.18%** | **+1.00** | **2.2%** |
| vol-scaled, with crypto | 0.56% | +3.09 | 7.0% |
| **vol-scaled, no crypto** | **0.18%** | **+1.20** | **2.2%** |

Crypto sits in the long third in **57% of periods**. Equal weighting also let the
most volatile names run the book - vol-scaling alone cuts 24.1% to 7.0% - but with
crypto gone both weightings give the same nothing.

24% annualised on a dollar-neutral book is hedge-fund-grade, and that implausibility
is the only reason the control was run.

## Gold alone, which is the one instrument worth a longer sample

Gold is the best non-crypto contributor, so it is the natural candidate:

| lookback | hold | months | mean | t | shuffled null |
|---|---|---|---|---|---|
| 1m | 1m | 229 | 0.36% | +1.34 | 20.0% |
| 3m | 1m | 227 | 0.33% | +1.23 | 20.5% |
| 6m | 1m | 224 | 0.43% | +1.61 | 13.5% |
| 3m | 3m | 75 | 2.08% | +2.50 | 1.5% |
| 12m | 1m | 218 | 0.29% | +1.09 | 25.2% |

One cell of eight above |t|=2, where 0.4 is expected. Nothing here.

**And more history would not settle it.** 218 non-overlapping months exist; reaching
2001 gives about 363, which improves a standard error by 1.29x and would turn t=1.3
into about 1.7. Halving a standard error needs four times the data - seventy years.
Longer history is worth having for regime diversity, not for deciding this.

## The lesson, which is the part worth keeping

**Every control applied to the time-series result passed, and the result was still
an artifact.** It survived clustering by period, which is what killed the Coinbase
premium. It worked at *every* lookback from 1 to 12 months, where a data-mined
result usually works at one. It was **absent on the Deriv synthetics**, which is the
strongest control available since those are RNG-generated and no mechanism could
produce momentum in them. And a shuffled null reached its t in **0.0% of 400 runs**.

None of those four can see that three of twenty-two instruments carry the mean. What
caught it was **leave-one-group-out**, and that was only run because a number looked
too large to believe.

So the control that matters is not on the list of controls. Add it: **before
believing a panel result, remove the loudest few members and look again.** The
sixth artifact of the day, and the only one that had already passed everything else.
