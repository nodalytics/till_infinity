# A crash can be timed and not signed, so the score is a risk switch

Measured 2026-09-23 on real markets only: 14 series at 15m and 1h (8 FX pairs, gold,
BTC/ETH/SOL, US500, NAS100, one venue each), and 9 series of daily bars back to 2007-2016
(OANDA FX, gold and index CFDs, Bitstamp BTC, Coinbase ETH). The prices database carries
no Deriv synthetics; for Boom/Crash see the last section. Every model is fit on the first
60% of each series by time and scored on the last 40%.

| harness | question |
| --- | --- |
| [`spikerisk.py`](../harness/spikerisk.py) | does the volatility state raise the odds of a large bar? |
| [`crashside.py`](../harness/crashside.py) | given a large bar is coming, can anything tell which way? |
| [`crashlab.py`](../harness/crashlab.py) | dedicated crash and rally models on 42 features - technicals, bar shape, borrowed fields |
| [`riskswitch.py`](../harness/riskswitch.py) | what the score is worth on the risk side, with stops taken by wicks |

"Large" is a bar beyond **4x the trailing 500-bar mean |return|** (250 on daily). The
baseline is deliberately slow: normalising by current volatility would define "large"
relative to a regime that is already elevated and hide the lift being asked about.

## The odds of a large bar are very predictable

Four trailing features - short-window volatility over the baseline, the largest recent bar,
the same hour-of-week's volatility in prior weeks, and drawdown - in a logistic regression:

| interval | event within | base rate | AUC | lift in the top 5% | caught by the top 5% |
| --- | --- | ---: | ---: | ---: | ---: |
| 15m | next hour | 6.5% | 0.748 | 4.25x | 21% |
| 1h | next 4 hours | 7.4% | 0.649 | 3.83x | 19% |
| 1d | next week | 6.8% | 0.722 | 4.02x | 20% |

Every family separately, the same shape. The gradient-boosted version on the wide set in
`crashlab.py` reaches **AUC 0.81** at 15m. Short-window volatility carries most of it and
hour-of-week seasonality is the second-best single feature intraday. None of this is
surprising - it is volatility clustering - but its size is what the rest of the page uses.

## And the sign of that bar is not

The crash model and the melt-up model rank **the same bars** (`crashlab.py`, gradient-boosted):

| interval | crash model: AUC on crashes | the same score's AUC on melt-ups |
| --- | ---: | ---: |
| 15m | 0.809 | 0.780 |
| 1h | 0.719 | 0.744 |
| 1d | 0.693 | **0.760** |

On daily bars the crash score predicts melt-ups *better* than crashes. Asked directly - among
windows that do contain a large bar, is the first one down? - a classifier on momentum,
drawdown, downside-semivariance share, the last return and the volatility state scores
**AUC 0.559, 0.567 and 0.566** at 15m, 1h and 1d.

`crashlab.py` threw everything at the sign. Single features ranked by how well they separate
windows holding a large *down* bar from those holding a large *up* one (0.5 = no direction;
above it a high value leans crash, below it leans rally):

| feature | field | 15m | 1h | 1d |
| --- | --- | ---: | ---: | ---: |
| `downshare` - downside share of recent variance | volatility | **0.590** | **0.592** | ~0.5 |
| `wick_skew`, `dnwick` - lower wicks longer than upper | bar shape (OHLC) | - | 0.584, 0.568 | - |
| `zscore20`, `mom20`, `rsi14` | technical | 0.40-0.42 | 0.43-0.44 | - |
| `impulse` - consecutive zigzag legs to new extremes, the mechanical part of an Elliott count | technical | 0.562 | - | - |
| `ac1_trend`, `ac1` - critical slowing down | climate early-warning | - | - | **0.346**, 0.393 (-> rally) |
| `upwick`, `body` | bar shape | - | 0.432 | 0.415, 0.574 |
| permutation entropy, variance ratio, Katz dimension, LPPL curvature, Hawkes intensity | information, fractals, bubble physics, seismology | ~0.5 | ~0.5 | ~0.5 |

`downshare` is the only feature pointing at crashes at two intervals, and lower wicks join it
at 1h - selling that got absorbed precedes the next large down bar. The borrowed fields add
nothing intraday; on daily bars the early-warning signals point at **rebounds**, not crashes.
None is strong enough to trade on its own, and [`directional-questions.md`](directional-questions.md)
tried every combination of them.

## Shorting the crash alarm does not pay

The trade the question was really asking about: short when the crash model is in its top 5%,
hold H bars, non-overlapping entries only, gross, in baseline units:

| interval | `crashside.py` (logistic) | `crashlab.py` (boosted) |
| --- | --- | --- |
| 15m (H=4) | +0.36 +- 0.21 | +0.79 +- 0.46 |
| 1h (H=4) | +0.09 +- 0.15 | +0.23 +- 0.32 |
| 1d (H=5) | **-0.77 +- 0.20** | **-0.76 +- 0.46** |

Nothing intraday clears two standard errors, and on daily bars it is **the wrong side**: a
daily crash alarm was followed by a *fall* only 40.9% of the time against 46.4% for every bar.
That is the buy-the-fear effect - the variance risk premium that [`implied.md`](implied.md)
found in VIX. The asymmetric version - short after a volatility alarm with a 3:1 target, so a
crash pays three times - is in `directional-questions.md` and loses at every interval.

## What the score is worth: the risk side

[`riskswitch.py`](../harness/riskswitch.py): a big-move probability, either sign, and what a
position lives through in each fifth of it (U = baseline x sqrt(H); excursions read from the
wicks, not the closes):

| 15m, H=2h | P(4x bar) | E\|end\| | adverse excursion p95 | P(\|end\| > 2U) |
| --- | ---: | ---: | ---: | ---: |
| lowest fifth | 2.1% | 0.60U | 1.62U | 3.1% |
| middle | 6.7% | 1.01U | 2.43U | 9.5% |
| highest fifth | **34.0%** | **1.64U** | **4.77U** | **29.3%** |

A sixteen-fold spread in the probability of a large bar and a threefold spread in the worst
adverse excursion. 1h and 1d have the same shape: 2.4% -> 22.5% and 2.3% -> 19.3%.

### Sizing on it: tails shrink, return mostly does not

Two positions that know nothing about the score - always long, and the sign of the last 20
bars - at size 1 always (`flat`), size 0.5 when the score is above its training 80th
percentile (`halve`), or size proportional to 1 / predicted E|move| (`inverse`):

| | policy | mean | sd | Sharpe/trade | 1% tail | worst | max drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 15m long | flat | +0.043 | 2.19 | +0.020 | -4.05 | -38.3 | 94.9 |
| 15m long | **halve** | +0.050 | 1.95 | **+0.025** | **-2.99** | **-19.2** | **61.4** |
| 1h long | flat | +0.017 | 1.52 | +0.011 | -4.20 | -28.3 | 92.8 |
| 1h long | halve | +0.010 | 1.32 | +0.007 | -3.45 | -28.3 | 92.3 |
| 1d long | flat | +0.071 | 1.43 | +0.050 | -3.69 | -11.0 | 39.0 |
| 1d long | **halve** | +0.063 | 1.24 | +0.051 | **-3.18** | **-8.9** | **32.3** |
| 1d momentum | flat | +0.013 | 1.43 | +0.009 | -3.64 | -8.1 | 68.2 |
| 1d momentum | **inverse** | +0.023 | 1.30 | +0.018 | -3.04 | -8.2 | **54.3** |

**The 1% tail shrinks by 14-26% everywhere** and the worst single outcome halves at 15m.
Sharpe per trade is unchanged or better at 15m and 1d and **worse at 1h**, where the
high-score bars were also the ones that paid - so this is tail insurance at roughly neutral
cost, not free return, and at 1h it has a price.

### Stops: the wick decides, and the score does not

Equal money at risk - a 1U stop at size 1 against a 2U stop at size 0.5 - split by score, and
run two ways: as a **resting stop order**, taken the moment a low touches it and filled at the
level (or at the open if the bar gaps through), and as an **exit on a close** beyond the level.

| 15m long | wick stop: hit | mean | 1% tail | close exit: hit | mean | 1% tail |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1U, low score | 31.5% | +0.050 | -1.00 | 21.6% | +0.069 | -1.99 |
| 1U, **high score** | **59.6%** | -0.018 | -1.00 | 44.6% | -0.035 | **-3.64** |
| 2U half size, high score | 30.2% | -0.017 | -1.00 | 21.9% | -0.016 | -2.23 |

Three things, all of which hold at 1h and 1d:

* **Wicks take stops about 1.4x as often as closes say they should.** A close-based back-test
  of a resting stop understates how often it is hit - 31.5% against 21.6% here, 36.5% against
  25.0% on daily.
* **A close-based exit has no floor.** It fills wherever the close lands, and its 1% tail is
  -2.0 to -3.9R; the resting stop's is -1.0R except on a gap.
* **In a high-score window a 1U stop is hit six times in ten.** Widening to 2U at half size
  halves that for the same money at risk. **But see [`stop-width.md`](stop-width.md), which
  corrects the conclusion drawn here:** across a 402-rule grid on 83 series, wide-and-small
  thins the tail about as much in the calm state as in the hot one, so the score is *not* a
  reason to set stop width by state. Widen in every state, or not at all.

## The leak, and a guard against the next one

The first daily run of this folder used yahoo's daily bars and produced a crash model that
was right 94% of the time. **Yahoo's daily FX bars are not one bar**: where the close sits in
day t's range predicts day t+1's return at **-0.44** on EURUSD=X and JPY=X, against
**+0.002** on OANDA's EURUSD and -0.006 on FX_IDC's; and the yahoo "open" tracks the same
day's close at +0.91. The high, low and open cover a different window from the close, so any
feature built on the bar's shape sees tomorrow. Yahoo's and TVC's cash indices carry a milder
version (+0.62). Every daily number on this page is from sources screened for both.

`spikerisk.load` now refuses any series whose close location predicts the next return beyond
|0.15| - every clean source screened sits within 0.07 - so the next misaligned feed fails at
load rather than producing a result.

## Boom and Crash are the exception, and the answer is already known

The Deriv spike indices are not in this data, and they do not need to be:
[`spiking.md`](spiking.md) and [`generators.md`](generators.md) measured the spike waiting
time as **memoryless** across all six (CV 0.84 to 1.10 against 1.00), so nothing - timing
or sign - can call a spike there, by construction. The only lever on those instruments is
the one the stop table describes: a stop on the spike side fills 10 to 19R past its level
([`generators.md`](generators.md)), so size and side are the whole decision.

## What follows

* **Ship the score as a risk input, not a signal.** Publish P(large bar within H) beside
  `release_vol_multiple` from [`news-volatility.md`](news-volatility.md), which covers the
  scheduled half of the same question, and let sizing and stop width read it. Deciding
  nothing, like `releases.py`.
* **Stop width is not a job for this score** - [`stop-width.md`](stop-width.md). The spike
  switch cuts the tail of an *unstopped* position; once a stop is in place, the stop already
  removes that part of the tail.
* **Back-test stops on wicks.** Anything in this repository that resolves a stop on closes
  understates how often it is hit and misstates what it costs.
* **Do not short on the alarm.** Every version measured is null intraday and wrong-signed on
  daily bars.
* **Not yet measured:** the score against the live book's own trades rather than toy
  positions, and at 1h whether a softer switch than halving keeps the tail benefit without
  the Sharpe cost.
