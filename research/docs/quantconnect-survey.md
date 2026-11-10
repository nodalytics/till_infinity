# Three QuantConnect write-ups and three strategy repositories, screened

**Surveyed 2026-11-10. All three research write-ups report a loss in their own
results table and a win in their own abstract**, none models a cost, none has a
null or a control, and none reports a trade count. Of eleven distinct
mechanisms across the six sources, **seven are already refuted here**, two are
**structurally unmeasurable on this book** - the venue sends no real volume and
quotes no instrument with an opening auction - and two are worth a run. One of
those two is dispatched; the other is listed with the reason it is second.

Two of the six sources also carry a worked example of a defect this desk has
measured, which is worth more than their strategies.

## The write-ups disagree with themselves, in the same direction every time

| source | the abstract | the table |
| --- | --- | --- |
| [momentum on the low-frequency component](https://www.quantconnect.com/research/15374/the-momentum-strategy-based-on-the-low-frequency-component-of-forex-market/p1) | neutral | EURUSD Sharpe **-0.309**, **-3.652%** a year, 23.7% max drawdown; best of six pairs is EURGBP at Sharpe 0.480 on **15 trades** |
| [combining mean reversion and momentum](https://www.quantconnect.com/research/15255/combining-mean-reversion-and-momentum-in-forex-market/p1) | "a fairly stable annual return of **11%**, 0.8 Sharpe Ratio and 11% drawdown" | **-1.938% / -4.008% / -0.958%** a year over three windows, Sharpe **-0.056 / -0.171 / -0.013**, drawdowns 19.7-21.7% |
| [Dual Thrust](https://www.quantconnect.com/research/15258/dual-thrust-trading-algorithm/p1) | "beat the market" | SPY Sharpe **-0.17**, maximum drawdown **41.1%** |

The discrepancy runs one way on all three, so **the prose cannot be used even
as a pointer** - only the tables and the code can. Each sample is also small
enough to be noise on its own terms: 10 to 15 trades per pair in the first,
unreported in the other two.

## The mechanisms, and where each lands

| mechanism | verdict | why |
| --- | --- | --- |
| Hodrick-Prescott trend, `MA(1,2)` of the trend as the signal | **refuted** | direction is closed here - the gate finds a *planted* drift at z **+2.90** and earns 2% of a spread. And the signal is a trailing filter's **endpoint**, which the author concedes "can cause the trend line to change the trend through past data": the shape where `trailing-zscore-fakes-reversion` measured the shuffled twin taking **+0.111 of a +0.137** effect. `lambda` was also set to 100 because the Ravn-Uhlig value made "the curve almost a straight line" - a parameter chosen on the appearance of the picture |
| 3-month momentum plus a standardised reversal, OLS-combined | **shortlisted second** | the per-instrument halves are closed, but the *cross-sectional* form - rank four currencies by predicted return, long the top and short the bottom - is an axis never tested here. `R^2` was 1.4% against the paper's 3.89%, and the regression is fit **once at initialisation** and reused for the whole backtest |
| `range = max(HH-LC, HC-LL)`, trigger at `open +- K * range` | **running** | the trigger distance is **scaled by a measured range**, and the range is this desk's strongest volatility result: the range-vs-close estimator ratio reads 0.648 within strata on FX and 0.667 on 371 of 392 equities. See below |
| Opening Range Breakout on the top 20 by relative volume | **unmeasurable here** | two independent reasons, below |
| OLS log-price spread, then a z-score against *that same fit* | **refuted, and a worked example** | fitting the ratio on the live series gives a null Dickey-Fuller `t` of **-29 from pure noise**; fit on a training half and the null lands at **-3.46**. `PairsTradingAlgo.py` does exactly this - `regr(log x, log y)` and then `mean`/`std` of the fitted spread |
| lagged cross-pair features into logistic regression or an LSTM | **refuted** | relationships here are **contemporaneous**: volatility and tails are large and every lagged measure is null |
| RSI, Bollinger, MACD and stochastic combined with a correlated pair | **refuted** | activation, scale and per-term offset are rank identities, so only the sign survives into a weighted sum |
| MACD of **SPY** used to trade **EURUSD** | **refuted** | a lagged cross-asset measure, as above - and `CurrencyTrading.py` appears to do it by accident rather than by design |
| walk-forward windowing and retraining | **not an edge** | a method, and the promotion ladder already scores a candidate against the backtest that claimed it |
| short a strangle when a CSV-supplied rank exceeds 90 | **out of scope** | this venue quotes no options |
| cross-exchange triangular arbitrage | **out of scope and absent** | advertised in a repository README whose tree contains no such file |

## Why the ORB cannot be measured on this book

The strongest external result in the set is not in these repositories at all:
Zarattini, Barbon and Aziz (2024), *A Profitable Day Trading Strategy For The
U.S. Equity Market*, over 7,000 US stocks from 2016 to 2023, reporting a top-20
"stocks in play" portfolio at net performance above 1,600% and a Sharpe of
2.81. The screen is an opening-range volume at least 100% of the last 14 days
and among the 20 highest relative volumes.

**Neither half of it exists on this venue.**

* **No real volume.** `real_volume` reads 0 across every instrument measured
  here and `tick_volume` counts quote updates rather than contracts, so a
  relative-volume rank cannot be built at all - the same constraint that makes
  VWAP and volume gates unbuildable.
* **No opening auction.** The book is FX, metals, index CFDs and Deriv
  synthetics. FX has no open; the synthetics are real markets *without* an
  auction by construction. The effect the paper attributes to the open is an
  auction phenomenon.

The range-rank the volatility screen already publishes is an activity proxy,
so the *selection* half has an approximation here. The volume half does not,
and the paper attributes the effect to volume - so an ORB run on this book
would be a different study wearing the paper's name.

## What is running

**Dual Thrust, decomposed rather than replicated.** There is no result to
reproduce - SPY at Sharpe -0.17 with a 41.1% drawdown, no costs, no control -
so the run asks the question the rule's *shape* poses:

1. **Is the edge in the side or the distance?** A `side-shuffled` arm fires at
   the identical times at the identical distances with the long/short choice
   randomised. Matching it means the rule carries no directional information.
2. **Is it the range, or any distance of that size?** A `constant-distance`
   arm replaces the measured range with the instrument's median.

With `Range_Break` as the positive control, the Brownian-bridge path arm as the
null - **not** `walk_with_bar_geometry`, which gaps 0.60-0.64 of a range at
every bar against the market's median `|gap|` of 0.0000 on 71-79% of bars, and
on which a rule triggered at `open +- K * range` would fire constantly and fill
at the planted gap - and the two Deriv volatility indices as the independent
placebo pair. `N = 4, K = 0.5` is the pre-registered headline because that is
what was published; the sweep is reported as a multiplicity count.

Cost is priced first. The rule has no stop, so R is undefined and the unit is
the trigger distance `K * range`; the ceiling is 0.16 of risk and the same
spread is **19x dearer at 15m than at 1d**.

## The two defects worth more than the strategies

**A scaler fitted before the split.** `Forex_LSTM_TSCV.py` calls
`scaler.fit(X_data)` and `scaler1.fit(Y_data)` on the whole array and *then*
builds `TimeSeriesSplit(n_splits=2)`. The full sample's minimum and maximum -
including every validation fold's future - are baked into every training fold,
so an honest split sits on top of dishonest preprocessing. The file also
imports `train_test_split` beside `TimeSeriesSplit`, which is usually the tell.

**A README that advertises what the tree does not contain.** One repository's
front page lists `momentum_equity.py`, `mean_reversion_atr.py`,
`portfolio_rebalance.py`, `options_hedge.py` and `triangular_arb.py`; the tree
holds nine files and none of them is any of those. What it does hold is an ORB
script whose `self.high` and `self.low` dictionaries are **never populated** -
so the first scheduled call raises `KeyError` - whose `OnData` is `pass`, and
whose loop calls `SetHoldings(symbol, 1)` for each of twenty symbols, asking
for twenty times the portfolio.

Both belong here for the same reason the kills do: the shape transfers even
where the strategy does not.

## The sources

| source | what it is |
| --- | --- |
| [QuantConnect 15374](https://www.quantconnect.com/research/15374/the-momentum-strategy-based-on-the-low-frequency-component-of-forex-market/p1) | HP-filter momentum, after Harris & Yilmaz (2009), *JBF* 33(9) 1575-1585 |
| [QuantConnect 15255](https://www.quantconnect.com/research/15255/combining-mean-reversion-and-momentum-in-forex-market/p1) | after Serban, *Combining mean reversion and momentum trading strategies in foreign exchange markets* |
| [QuantConnect 15258](https://www.quantconnect.com/research/15258/dual-thrust-trading-algorithm/p1) | Dual Thrust on SPY and unnamed single stocks |
| [ksjagtap/QuantConnect-Trading-Strategies](https://github.com/ksjagtap/QuantConnect-Trading-Strategies) | 121 stars, MIT, last pushed 2018-12-01. Coursework: filenames carry matriculation numbers and a `Group09_Final_Writeup.pdf`. No results reported; the README's whole evaluation guidance is "Evaluate using Cumulative Returns, Maximum drawdown and Sharpe Ratio" |
| [NadirAliOfficial/Quant-Connect-](https://github.com/NadirAliOfficial/Quant-Connect-) | 8 stars, MIT, last pushed 2026-09-21. Client deliverables: an incomplete ORB sketch and two copies of a CSV-fed strangle |
| Zarattini, Barbon & Aziz (2024) | *A Profitable Day Trading Strategy For The U.S. Equity Market*, Swiss Finance Institute. Named here because it is the real source behind the ORB sketch, and because it is the one result in the set with a sample worth the name |
