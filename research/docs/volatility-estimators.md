# Which volatility estimator to size from

Measured 2026-09-20 on the broker's own bars: 145,485 daily bars back to
**2010-08-22** and 208,369 4h bars back to 2023, across 42 instruments. Ranked by
Spearman against the realised forward range - next week from daily, next day from
4h - on non-overlapping windows.

This matters because **sizing to a volatility forecast is the only use that has
survived a day of measurement.** Direction is absent by every test in
`banded-labels.md`, `first-passage.md` and `impulse-consistency.md`, so which
estimator feeds the size is the live question.

## The answer: EWMA true range, by a small consistent margin

| estimator | daily rho | wins | 4h rho | wins |
|---|---|---|---|---|
| **EWMA TR (Wilder)** | **0.316** | **20/42** | **0.264** | **20/42** |
| ATR(14) | 0.304 | 2/42 | 0.249 | 1/42 |
| ATR(28) | 0.304 | 2/42 | 0.252 | 4/42 |
| median TR(14) | 0.300 | 1/42 | 0.238 | 0/42 |
| Yang-Zhang | 0.298 | 0/42 | 0.244 | 0/42 |
| Garman-Klass | 0.297 | 1/42 | 0.244 | 1/42 |
| ATR(7) | 0.296 | 5/42 | 0.247 | 5/42 |
| Parkinson | 0.296 | 0/42 | 0.241 | 0/42 |
| Rogers-Satchell | 0.294 | 1/42 | 0.240 | 4/42 |
| realised vol (close-to-close) | 0.258 | 2/42 | 0.203 | 0/42 |
| structural range | 0.182 | 2/42 | 0.147 | 3/42 |
| structural range x its move | 0.180 | 2/42 | 0.166 | 1/42 |
| last bar's TR | 0.176 | 4/42 | 0.166 | 3/42 |

EWMA true range - Wilder's smoothing, `alpha = 1/14` - tops both timeframes and
wins on 20 of 42 instruments against ATR(14)'s 2. The margin in mean rho is 0.012,
which is small; the same ordering on sixteen years of daily and three of 4h is what
makes it worth acting on. It loses on 22 of 42, so this is a preference rather than
a dominance.

## Close-to-close is the only clear loser among the standard estimators

`realised vol` is worse than every range-based measure on both timeframes, which is
the literature's actual claim - a bar's high and low carry information its close
discards - confirmed here rather than assumed.

The OHLC estimators are **equivalent to ATR, not better**: Yang-Zhang 0.298,
Garman-Klass 0.297, Parkinson 0.296 against ATR(14)'s 0.304. Their published
5-8x efficiency is about estimating the variance of a diffusion, and the quantity
that matters for sizing is the forward *range*, which ATR already measures
directly. Worth knowing that they add nothing here, since `directional-edge.md`
listed them as the highest-value untried volatility work.

### A units artifact that nearly produced the opposite finding

The first run put the OHLC estimators at rho 0.21 against ATR's 0.57, which would
have been reported as "the range estimators are useless". It was the units: ATR is
in price and Parkinson is dimensionless, while the target was a price range, so on
an instrument whose level moved tenfold over sixteen years the price-unit
estimators tracked that for free. Dividing the price-unit ones by the close - and
the target too - collapsed every rho from about 0.57 to about 0.30 and reordered
the bottom half of the table. **The absolute numbers in the first run measured
price drift, not forecasting skill.**

## The structural range is last, and so is the weighted version

The operator's barrier definition - the distance from where supply turned price
down to where demand turned it up - is the worst of the candidates on both
timeframes, below even the last bar's true range on daily. Weighting it by the
movement those turns generated does not help: 0.180 and 0.166.

That is the third independent null on it:

* `docs/magnet.md`: price reaches a daily swing level **less** often than an
  arbitrary price the same distance away, 0.441 against 0.491 over 28,725
  observations, and more confirmation makes it slightly worse.
* `exits.md`: barrier geometry is a reparameterisation - a wider target buys
  reward by selling hit rate at about the rate that keeps EV where it was.
* Here: as a volatility estimate it is beaten by every standard alternative.

The structure is real and visible; what it is not is *informative* about where
price will go or how far it will travel.

## What to do with this

Replace the simple mean in the desk's true-range averaging with Wilder smoothing
wherever a volatility estimate feeds a size. That is the whole change, and its
value is 0.012 of rank correlation - real, cheap, and not a fix for anything
larger.

Caveats: rank correlation only, so this says which estimator orders the future
better and not how to map it to a lot size. Instruments are not independent of one
another. And the lookback of 14 was fixed across every estimator rather than tuned
per estimator, which would favour whichever suits 14 best.
