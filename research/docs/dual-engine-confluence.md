# The dual-engine confluence rule is not a cost problem, and not a direction

Run: `python research/ideas/dual_engine_gross.py`, after
`python research/ideas/mt5_catalogue.py` and the same with `--costless`.

**Measured 2026-11-12**, on **464 days** of the broker's own 5-minute bars across EURUSD, GBPUSD,
XAUUSD, USDJPY and AUDUSD, through the same Nautilus engine the desk trades on. The rule came in as
a LEAN algorithm: two signal engines - an attention z-score exhaustion reversal and a choppy-cluster
breakout - both aligned to swing pivots, both entering on a retest, sharing a break-even stop, a 50%
partial at 2R, an ATR trail and a 48-hour time stop.

| question | answer |
|---|---|
| does it have a directional edge? | **no** - at n 906 it reads -0.210R against its own flip at -0.219R, a gap of **+0.009** |
| is the loss the spread? | **no** - removing the spread entirely moves R by **0.006 to 0.008** |
| where does the money go, then? | the **exit geometry**: cost is 0.008R and the loss is 0.21R |
| does more frequency help? | it is reachable and it does not help: 906 trades, -0.210R, **67.4% drawdown** |
| does a longer reward target help? | no - 1.5R to 4.0R moves the trade count by <=5 and R by <=0.2 |
| do several structure timeframes agreeing help? | they almost never agree: 265 signals, two agreed 8 times, three agreed **never** |

## Gross against net

Identical bars, identical signals, the only difference being whether the quotes carry the broker's
recorded spread or none at all.

| structure | arm | side | n | R/trade | se | gross $ | sharpe | maxdd |
|---|---|---|---|---|---|---|---|---|
| 4H | net | rule | 62 | -0.257 | 0.171 | -7,413 | -0.75 | 7.9% |
| 4H | gross | rule | 62 | **-0.251** | 0.171 | -7,278 | -0.73 | 7.8% |
| 1H | net | rule | 280 | -0.363 | 0.091 | -38,746 | -2.53 | 43.0% |
| 1H | gross | rule | 280 | **-0.355** | 0.091 | -38,316 | -2.49 | 42.7% |
| 1H | net | flip | 205 | **+0.068** | 0.114 | +22,532 | +1.08 | 5.2% |
| 15m | net | rule | 906 | -0.210 | 0.062 | -62,636 | -2.73 | **67.4%** |
| 15m | gross | rule | 907 | **-0.202** | 0.062 | -62,114 | -2.69 | 67.1% |
| 15m | net | flip | 640 | -0.219 | 0.061 | -37,844 | -1.52 | 38.6% |
| 1D | net | rule | 7 | +0.164 | 0.512 | +1,555 | +0.50 | 1.4% |

**The spread costs 0.006 to 0.008R a trade.** Less than one percent of a risk unit. Charge nothing at
all and the rule still loses 0.20 to 0.36R. Whatever is wrong with it was never transactional.

That matters because an earlier screen said the opposite. `dual_engine_timeframes.py` priced a 15m
structure at 22-37% of R and concluded the fine arms were unaffordable - but that screen used
**DERIV's** recorded spreads, and the account this desk trades is 4-6x tighter. The conclusion is
retracted in that file. The arms were never unaffordable; they were just losing.

## Where the money actually goes

At the 15m structure the three candidates can be separated, which is the useful part of this run:

* **direction** contributes nothing - rule -0.210 against flip -0.219, a gap of +0.009 on n 906 and
  640, which is a fifth of a standard error;
* **cost** contributes 0.008R;
* **the remaining 0.20R is the exit stack** - break-even at 1R, a half off at 2R, an ATR trail
  after it, and a 48-hour time stop.

A direction-free entry with a symmetric stop and target should read about minus the cost. It reads
twenty-five times the cost, and both arms read it. The break-even stop and the partial cut the right
tail while the full stop stays on the left, which is the shape `a-martingale-cannot-pay` and
`the-walk-is-the-best-calibrated-band` already describe: any positive expectancy on something this
close to a walk has been a measurement error every time, and the exit rules that look like risk
management are a tax when there is no edge for them to protect.

**This is the finding worth keeping.** It is not about this rule. Any entry with no directional
information, run through this exit stack, loses roughly 0.2R a trade on these instruments - and that
is a number to check the next management proposal against rather than a story about one algorithm.

## The flip, which is not a strategy

At the 1H structure, trading the rule's signals **backwards** made +0.068R on 205 trades, +$22,532,
Sharpe +1.08, 5.2% drawdown. That is not a recommendation: the 15m flip loses -0.219R on 640, so the
sign is not stable across structures and the 1H cell is one of many. What it does establish is that
the rule's direction at 1H is not merely absent, it is **wrong** - which is a stronger statement than
"no edge" and is the reason the gap there is -0.430 rather than zero.

## How the sample behaved as it grew

Every positive reading in four weeks of runs on this rule sat on a tiny sample, and every one
reversed when the sample grew:

| n per cell | R/trade |
|---|---|
| 7 | +0.164 |
| 11 | +0.368 |
| 13 | +0.279 |
| 62 | -0.257 |
| 280 | -0.363 |
| 906 | **-0.210** |

The clean control is two arms with the **same** structure timeframe, the **same** geometry and the
**same** cost, differing only in span: 15m execution over 86 days read +0.368R on 11 trades a cell,
1h execution over 321 days read -0.300R on 41. Nothing changed but how long it ran.

This is the shape `Kills` already records for fade-to-value - "+0.120R on 477 trades at 1d, +0.017R
on 985 at 4h and -0.007R on 2,786 at 1h - shrinking as the sample grew and reversing on the
largest". It is the single most reliable signature of a non-edge in this repository.

## What was tried, so it is not re-proposed

* **The specified parameters**, 15m/4H - 7 trades in 86 days on the two named instruments.
* **A twelve-cell grid** over tolerance, attention percentile and risk fraction, on five instruments,
  with the same grid run on the flip. 0 of 12 passed Sharpe > 0.5 with drawdown < 15% and >= 50
  trades; 0 of 12 flip cells passed either. `risk_per_trade` turned out not to be a risk axis at all
  - FX is against the leverage cap at 1%, so raising it to 2% doubles gold and moves nothing else,
  silently reweighting the book toward the one instrument with winning trades.
* **Seven timeframe pairs** x five reward targets. Every cell with n >= 35 negative.
* **Multi-structure confluence**, 1H + 4H + 1D voting k-of-n. The frames fire about 18 times per
  instrument per year, so two agreed within a day eight times in 464 days and three agreed never.
  The union (k=1) gives 190 trades and a rule-minus-flip gap of **+0.000**.
* **Gross against net**, here.

## What is not closed

The **soft** version of the multi-timeframe reading. v2 of the formulation
(`docs/specs/2026-11-12-dual-engine-confluence-v2.md`) replaces the volatility z-score with a
softmax-weighted **price** z-score over four timeframes, which produces a value on every bar rather
than a signal on a few and so never has to agree with itself. That is a different feature and
nothing here measures it. It would need its own null, on the 464-day span, beating its own flip by
more than two standard errors - and it would still face the 0.2R the exit stack costs, which is the
bar any entry has to clear before the management can be blamed on something else.

The cost figures above are also a **floor**. The spread is modelled at each feed's median, and this
rule enters on a volatility extreme by construction - so it trades into the tail, where FX runs 50-90
points against a 2-3 point median. A rule that selects for movement does not pay the median.
