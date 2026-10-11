# Slope fade, redone in time - and the 1971 EURUSD problem

`research/ideas/slope_fade.py`, rerun on 2026-10-11 after the package rule that
every horizon is a duration. The original counted bars, which made the table
several different experiments at once, and the rerun found something larger than
the result it was checking.

## What changed in the harness

* **Lookbacks and horizons are hours.** They were `(5, 10, 20)` bars with a
  one-to-four week pair bolted on beside them - so "lookback 5" named five
  different estimators across five timeframes, and the weekly pair had to be
  special-cased. Stated as durations the short end and the multi-week end are
  one ladder, and the deduplication that used to be a special case for daily
  bars now happens on every timeframe by construction.
* **The volatility window is `24h`,** not twenty bars, which was five hours at
  15m and twenty days at 1d.
* **`coverage`, not a hardcoded five-day week.** This file still had
  `w * 5 * 24 / bar`, which is wrong on crypto and on the Deriv synthetics -
  they trade seven days - and wrong by a different amount on every instrument
  with its own session. It is inferred from the timestamps now.
* **It uses `inputs.ema`** rather than its own copy.

## The bug the rerun walked straight into

The first run on hours promoted this into the survivor list:

```
usdjpy 15m ema slope look=672h h=168h follow -7.975
  (overlapping t-32.1, INDEPENDENT t-3.1 on n=10)
```

`n = 10`. A mean of **-8.0 volatility units** and a `t` of -3.1 on ten points.

The `independent()` docstring already said this would happen - *"a 4-week
lookback on 15m bars yields about ten independent observations. That is not a
small sample, it is no sample"* - and the survivor gate tested `|t| > 3` and
nothing else. **A docstring stating a limit the code does not apply**, in the
function written to stop exactly this class of error. `LEAST_INDEPENDENT = 30`
applies it now, and cells below it print `n too small` instead of a number.

## The larger finding: the daily FX files start in 1971

With the `n = 10` cells gated out, one result looked real - seven neighbouring
cells, which is the pattern this harness asks for:

```
usdjpy 1d ema slope look=168h h=168h follow +0.137 (INDEPENDENT t+4.1) after cost +0.089
usdjpy 1d slope     look=336h h=168h follow +0.167 (INDEPENDENT t+3.2) after cost +0.118
usdjpy 1d ema slope look=336h h=168h follow +0.163 (INDEPENDENT t+3.7) after cost +0.114
```

Momentum on daily usdjpy at one-to-two week lookbacks, held a week, surviving
costs, consistent across neighbours. Then the arithmetic: `n = 3159` independent
observations at a stride of five daily bars needs about **15,800 daily bars**.

```
EURUSD.1d: 15797 bars  1971-01-03 -> 2026-09-10
USDJPY.1d: 15800 bars  1971-01-03 -> 2026-09-10
XAUUSD.1d:  4843 bars  2011-01-02 -> 2026-09-10
```

**EURUSD did not exist in 1971.** The euro was introduced in 1999, so roughly
twenty-eight of those forty-three years are a vendor's reconstruction - a
chained basket, not the instrument. `USDJPY.1d` starting the same day is the
collapse of Bretton Woods, under capital controls and official intervention that
no longer exist. The `4h` files start in 1977 and have the same problem.

So the harness now filters to **2010 onwards** by default, and prints each
series' date range in its header so this cannot be invisible again. It is a
provenance filter rather than a tuning knob, and `SINCE=0` shows the whole file.

### The cluster was the 1970s

| | survivors | expected by chance |
|---|---|---|
| 1971 onwards | 14 | 6.1 |
| 2010 onwards | **6** | 6.1 |

**Every one of the seven `usdjpy 1d` cells vanished.** What is left is the
chance yield of 2,250 cells, exactly.

The only neighbourhood among the six is four adjacent `gbpusd 1h` cells - `ema
slope` and `ema zscore`, at one-hour and four-hour lookbacks, held four hours -
all agreeing that *following* loses, so fading gains. Gross, the fade earns
0.076 to 0.083 volatility units; gbpusd 1h costs **0.059** of one, so the fade
nets **+0.017 to +0.024** - between a third and four tenths of a spread per
trade, which is inside the error of the cost model itself. At 2,250 cells it is
not something to act on.

## What this changes beyond this harness

Every earlier measurement on `1d` or `4h` FX in this repository inherits the
problem. Nothing is retracted here, because most of the work was on 15m and 1h
and the conclusions were nulls - a null on contaminated data stays a null, since
adding regimes that no longer exist cannot *create* a failure to find an effect.
The direction of the bias runs the other way, and that is the point: this
contamination manufactures findings rather than hiding them, and it manufactured
one.

The reusable lesson is the one that caught it, and it was not a review:

> `n` is a fact about the data. When a sample size implies more history than the
> instrument has, the series is not what its filename says.

Three cheap checks follow from it, all now in the harness: print the date range
of every series beside its bar count; make the independence floor a constant the
code enforces rather than a sentence in a docstring; and read `n` as a claim
about the world before reading the `t` beside it.
