# `ma_pullback` on indices at 1 to 15 minutes, costed at each bar's own spread

**Measured 2026-11-20.** Fifteen index CFDs, 1m to 15m, with H4 and daily
trend filters and a per-instrument cost screen. Harnesses:
[`index_pullback.py`](../ideas/index_pullback.py) and
[`index_trend.py`](../ideas/index_trend.py). Data pulled live from the broker
at 12:25 UTC the same day, so these are current quotes rather than a snapshot.

| question | answer |
|---|---|
| does the rule work below 15m on indices? | **no, and 1-minute is hopeless** - M1 costs **0.3861R a trade** and is gross-negative too; M5 and M15 are **gross-positive** (+0.0844, +0.0495) and net-negative because cost is 0.1527 and 0.0807 |
| does an H4 or daily trend filter help? | **yes, on gross, and it is not enough** - the H4 filter takes gross from **+0.0537 to +0.1228** while keeping **62%** of trades, and its shuffled twin gets *worse*; the daily filter adds nothing on top |
| which conditions worked? | **not a market regime, a cost regime.** Wide range, busy quoting, narrow spread and the US session are four readings of one variable: cost in R |
| is any index cheap enough? | **four of fifteen.** US Tech 100 at **0.0184R**, Wall Street 30 at 0.0365, US SP 500 at 0.0505, Japan 225 at 0.0551, against Swiss 20 at **0.8153R** - a **44-fold** range |

## Why this is worth measuring at all

`ma_pullback` led the 15m leaderboard in
[`rsi-ma-momentum.md`](rsi-ma-momentum.md) at **+0.3171R** over seven days -
and that study then found **0 of its top 10 cells positive in the prior
thirty**, with a day-shuffled market's best cell beating the real market's. So
this is not a fresh hypothesis. What is new is the instrument class and two
measurements the FX work could not make.

**The spread is read per bar, not assumed.** The broker's rate rows carry a
`spread` field in **points** beside the OHLC, so every trade is charged the
spread *that bar actually quoted*. Every earlier cost figure on this desk came
from a median per feed. `spread-column-is-in-points` is why this is worth
saying twice: read as price it once gave EURUSD a 476% round trip.

**`tick_volume` is the only order-flow proxy that exists.** `real_volume` is
**0** on every row, which `no-order-flow-and-no-real-volume` already records:
no DOM, and `tick_volume` counts quotes rather than contracts. It is used as a
measure of quoting activity and never as volume.

## The cost ladder, which decides everything

Four to six indices, 14- and 7-day windows, every `(MA, momentum, reward)` cell
pooled, 1 ATR stop, each trade charged its entry bar's and exit bar's quoted
spread:

| frame | window | trades | gross | **cost** | net | shuffled twin |
|---|---|---:|---:|---:|---:|---:|
| **M1** | 14d | 54,100 | -0.0510 | **0.3861** | **-0.4371** | -0.4320 |
| M1 | 7d | 27,480 | -0.0801 | 0.3381 | -0.4183 | -0.4156 |
| **M5** | 14d | 10,311 | **+0.0844** | 0.1527 | -0.0683 | -0.0415 |
| M5 | 7d | 5,163 | +0.0776 | 0.1387 | -0.0611 | -0.0465 |
| **M15** | 14d | 3,134 | **+0.0495** | **0.0807** | -0.0313 | -0.0530 |

**One minute is not a clock this book can trade.** 0.3861R of cost a trade, and
gross is negative as well, so there is nothing there to pay for. That figure
also settles a disagreement on record: the operator's note put 1-minute FX at
**0.3 to 0.5R** while [`edge_life.py`](../ideas/edge_life.py)'s ladder put a
1 ATR stop at 5m near 0.07R. Both were right about different things - the
operator's figure is a **tight-stop** number and the ladder's is a 1 ATR one,
and the stop is the stronger lever. Here, on indices at M1, 0.3861R is measured
directly.

**M5 and M15 are gross-positive.** That is more than the FX grids found, and
cost accounts for essentially the whole gap: +0.0844 against 0.1527, +0.0495
against 0.0807. The rule finds about five basis points of risk and pays eight.

**M15 is the only frame where real beats its own shuffle** (-0.0313 against
-0.0530). At M1 the two are indistinguishable - both are just paying spread.

## The conditions, and why they are all the same condition

Every reading is taken at the entry bar's close and normalised by its own
trailing 480-bar median, so "loud for this feed lately" rather than an absolute
that drifts. M15, 14 days:

| reading | bands, net R |
|---|---|
| **spread** | cheapest 85 trades **+0.6248** +/- 0.249 · the rest +0.1034 +/- 0.061 |
| volatility | 0.80+ +0.0204 · 1.04+ -0.0213 · 1.21+ **+0.2593** · 1.37+ **+0.2607** |
| quoting | 0.26+ +0.0812 · 0.91+ +0.0626 · 1.26+ +0.1681 · 1.71+ **+0.2082** |
| session | 00-06h +0.0134 · 06-12h -0.0213 · 12-18h +0.0033 · 18-24h -0.1267 |

At M5 the same shape is sharper: the cheapest spread quartile reads **+0.2038**
against **-0.0930** for the rest, the loudest volatility quartile is the only
positive one, and **06-12h UTC is the worst session block at -0.1596** - the
European hours before the US open, when these CFDs quote widest relative to
their range.

**So "the conditions that worked" is one condition.** Wide range, busy quoting
and a narrow spread are three ways of saying the same thing: the stop distance
is large relative to what the venue charges, so cost in R falls. None of them is
a market regime in the sense a rule could be gated on.

**And the cheap-spread cells should not be believed.** Selecting on a low
spread selects on quiet moments, `n` is 85 to 407, and that is exactly the
self-selected band that failed verification twice in
[`rsi-ma-momentum.md`](rsi-ma-momentum.md).

## The H4 and daily trend filter

Fifteen indices at M15, 14 days. A filter reads **only closed** higher-frame
bars: the broker stamps a rate row at the bar's **open**, so an H4 row stamped
12:00 is not knowable until 16:00, and `trend_of` returns close times for that
reason. Using the open stamp would read four hours of the future on exactly the
four hours the filter is meant to be agnostic about -
`open-gap-filters-are-lookahead` is the same error costed at +0.50R a trade.

| arm | trades | net | **gross** | cost | shuffled twin | kept |
|---|---:|---:|---:|---:|---:|---:|
| none | 6,772 | -0.2605 | +0.0537 | 0.3143 | -0.2543 | 100% |
| **H4** | 4,168 | -0.1895 | **+0.1228** | 0.3123 | -0.3146 | **62%** |
| D1 | 3,460 | -0.2318 | +0.0804 | 0.3122 | -0.3357 | 51% |
| both | 3,057 | -0.2192 | +0.1021 | 0.3213 | -0.3903 | 45% |

**The H4 filter more than doubles the gross edge while keeping 62% of the
sample**, and the shuffled twins get *worse* under it (-0.2543 to -0.3146), so
the lift is not mechanical. That is the rare outcome for a confluence arm here:
`reactive-zones.md` records a multi-timeframe confluence whose sample went to
zero, and a filter that keeps 5% of trades on a 0.05R edge has bought nothing
measurable.

**H4 alone beats H4 and daily together.** The daily filter adds no gross and
costs 11% of the sample.

**And cost is untouched at ~0.31R by every arm.** Doubling a 0.05R edge to
0.12R against 0.31R of cost is still a loss. The filter improves the half of
the problem that was not broken.

## The cost screen: eleven of fifteen indices are untradeable with this rule

| index | **cost R** | net, H4+D1, 14d | net, H4+D1, 7d |
|---|---:|---:|---:|
| **US Tech 100** | **0.0184** | +0.1560 | +0.3291 |
| Wall Street 30 | 0.0365 | +0.0098 | +0.1889 |
| US SP 500 | 0.0505 | +0.0763 | +0.2947 |
| Japan 225 | 0.0551 | +0.1162 | +0.1782 |
| Germany 40 | 0.1087 | +0.0083 | +0.2130 |
| US Small Cap 2000 | 0.1108 | +0.0636 | +0.2758 |
| UK 100 | 0.2150 | +0.1263 | +0.4630 |
| Australia 200 | 0.2964 | -0.0946 | +0.1058 |
| Europe 50 | 0.4194 | -0.3140 | +0.2277 |
| US Mid Cap 400 | 0.5817 | -0.6721 | -0.5812 |
| Hong Kong 50 | 0.5875 | -0.5312 | -0.4107 |
| France 40 | 0.7343 | -0.9224 | -1.2423 |
| **Swiss 20** | **0.8153** | -0.7807 | -0.7881 |

**US Tech 100 charges 0.0184R** - seventeen times less than Swiss 20, and a
third of what EURUSD costs at 15m. The pooled -0.21R above is produced almost
entirely by the six dearest feeds; Swiss 20, France 40, Hong Kong 50 and US Mid
Cap 400 cannot be traded by any rule whose edge is under 0.5R.

**This ranking is the durable result on this page.** It is read from quoted
spreads over thousands of bars, it is stable between the two windows, and it
separates four feeds worth testing from eleven worth discarding.
`cost-screen-the-book-you-have` is the standing instruction and this is it
applied to the index book.

## What is not established

**The returns.** Every figure above is 14 or 7 days. That window is an order
statistic: [`rsi-ma-momentum.md`](rsi-ma-momentum.md) measured a 414-cell grid
whose seven-day leaders read +0.24 to +0.32R, where 0 of the top 10 was
positive in the following month and a shuffled market's best beat the real
market's. The 7-day column in the table above being uniformly rosier than the
14-day one is that effect visible in one page.

What would settle it is the H4-filtered rule on the four cheap feeds over the
**2.5 years of M15** now pulled for them, with the discovery and confirmation
halves separated. That run is the open item.
