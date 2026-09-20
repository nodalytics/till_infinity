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

## The desk's own stack loses to an EWMA of true range

The race above compared textbook estimators and left out the one that matters. The
desk forecasts volatility through a consensus over GARCH, HAR, a learned
regressor, a stated book and an analogue model, so the comparison that decides
whether to change anything is against **that**, not against ATR.

11,797 recorded level calls, one an hour per instrument so the forward windows do
not overlap, 42 instruments, forecasting the realised range over the next 30
minutes:

| predictor | mean rho | median | wins |
|---|---|---|---|
| **EWMA true range** | **0.322** | **0.557** | **23/42** |
| `forecast_bps` | 0.142 | 0.155 | 3/42 |
| `vol_bps` - what sizing reads | 0.128 | 0.079 | 1/42 |
| `range_bps` | 0.128 | 0.075 | 4/42 |
| `ensemble_bps` | 0.124 | 0.092 | 1/42 |
| `garch_bps` | 0.117 | 0.080 | 0/42 |
| `risk_vol` | -0.026 | -0.023 | 10/42 |

A fourteen-period EWMA of true range forecasts the next half hour about **2.3
times** better than the best of the desk's own figures, and wins on 23 instruments
against 3.

### The caveat that could overturn this

**The desk's estimators may be answering a different question.** `learned.py`
forecasts five bars ahead by construction and GARCH targets the next bar's
variance, so judging them at 30 minutes may be judging them on a horizon they were
never built for. A fair verdict would compare each at its own horizon.

What keeps it relevant anyway is that `vol_bps` is what **sizing reads**, through
`scaling.by_volatility`, and the desk sizes trades it holds for minutes to hours.
Whatever horizon the estimator was built for, 30 minutes is the horizon it is being
used at.

Two smaller notes. EWMA TR's median (0.557) is far above its mean (0.322), so it is
strong on most instruments and poor on a few - the synthetics, whose volatility does
not vary, which `impulse-consistency.md` found the same way. And `risk_vol` is
negative here, which is not damning: it is a risk-to-invalidation measure rather
than a volatility forecast, and it was included only to see whether it carried
volatility information. It does not.

### What to do

Before changing any sizing, re-run this with each estimator at its own horizon -
GARCH at one bar, `learned` at five - because that is the comparison the desk's
own design implies and it is the one test that could reverse this. If EWMA true
range still wins at the horizon sizing actually uses, add it as a feature and let
`scaling.by_volatility` read it, which is a small change with a large measured
difference behind it.

## Resolved: each estimator at its own horizon, and it still loses

The caveat above was the one thing that could have reversed this, so it was tested
rather than argued. Two unfairnesses were removed:

* **Horizon.** A bar means the *call's own interval*, so every estimator was scored
  at one bar ahead - GARCH's horizon - and at five, which is `learned.py`'s
  `HORIZON`, for 1m, 5m, 15m and 1h calls separately.
* **Target quantity.** GARCH forecasts the variance of returns and a true range
  forecasts a range. Both targets were scored: realised range, and realised
  volatility from 1-minute returns.

EWMA true range wins **every cell**:

| call interval | horizon | EWMA TR range/vol | best of the desk's | ratio |
|---|---|---|---|---|
| 1m | 5 bars (5m) | **0.425 / 0.382** | `vol_bps` 0.362 / 0.324 | 1.17x |
| 5m | 1 bar (5m) | **0.373 / 0.331** | `forecast_bps` 0.249 / 0.240 | 1.50x |
| 5m | 5 bars (25m) | **0.330 / 0.382** | `forecast_bps` 0.231 / 0.268 | 1.43x |
| 15m | 1 bar (15m) | **0.336 / 0.356** | `forecast_bps` 0.165 / 0.183 | 2.04x |
| 15m | 5 bars (75m) | **0.281 / 0.344** | `forecast_bps` 0.138 / 0.177 | 2.04x |
| 1h | 1 bar (60m) | 0.192 / 0.065 | `range_bps` 0.097 | 184 obs, thin |

Two details that matter more than the averages. **GARCH loses on its home turf**:
5m calls, one bar ahead, scored against the variance of returns - precisely what it
forecasts - 0.166 against EWMA TR's 0.331. And the gap **widens with the
interval**, from 1.17x at 1m to 2.04x at 15m, which is the opposite of what a
horizon-mismatch explanation would predict.

The 1h row is 184 observations and EWMA TR's score against volatility collapses to
0.065 there, so nothing above should be read as holding at 1h and above.

### What this does not establish

Forecasting the realised range better is not the same as trading better. Sizing to
a better volatility forecast *should* improve risk-adjusted return, but that is an
inference and it has not been measured. The desk's stack also does more than
produce a magnitude - `forecast_ratio` feeds `scaling.by_regime`, which is a
different question from "how far will it move" - so replacing the magnitude input
is not the same as removing the stack.

The change the evidence supports is narrow: make an EWMA of true range available as
a feature and let `scaling.by_volatility` read it in place of `vol_bps`. Everything
else the stack feeds should stay where it is.
