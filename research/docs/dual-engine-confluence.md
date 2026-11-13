# The dual-engine rule is closed: both triggers, on eight years

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
| does **v2's** trigger change the answer? | **no** - it read +0.162R on n 48 and **-0.127R on n 356**, reversing on 7.4x the sample |

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

## v2's attention feature: the first positive arm, and still short of the bar

**Measured 2026-11-12**, same 464 days, same five instruments, same engine. v2 replaces the trigger
and nothing else: v1 asked "is the market unusually volatile", v2 asks "is price unusually far from
an attention-weighted mean" - a softmax-weighted price z-score on {15m, 1H, 4H, 1D}, combined by a
second softmax over the absolute z-scores, gated at the 85th percentile of its last 200 readings.
The pivots, origin candle, cluster, retest, sizing, protection and exits are inherited untouched, so
the only difference from the v1 figures above is the question the gate asks.

| side | n | R/trade | se | sharpe | maxdd | gross $ | gate |
|---|---|---|---|---|---|---|---|
| rule | 48 | **+0.162** | 0.266 | +0.52 | 4.4% | +3,682 | 956/8,974 (10.7%) |
| flip | 38 | **-0.419** | 0.174 | -2.16 | 9.5% | -9,522 | 961/8,971 (10.7%) |

**rule - flip = +0.581R, se 0.318, so +1.83 standard errors.**

This is the first arm in the whole line of work to come back positive with its flip clearly
negative. Every v1 cell either lost, or beat a flip that was losing by about the same amount, or
read positive on single-digit samples. This one reads +0.162R net of costs and exits, against a
reverse that loses 0.419R.

**It does not pass.** The bar was fixed before the run at two standard errors and it reached 1.83.
That is a miss, not a near-pass to be rounded up - and the reason the bar was set there is sitting
in the table above it: **n = 48 is exactly the regime where v1's positives lived before they
reversed.** +0.164 at n 7, +0.368 at n 11, +0.279 at n 13, then -0.257 at n 62 and -0.210 at n 906.
A positive reading at n 48 with a 1.8-sigma flip gap is what the *start* of that sequence looked
like every time.

Three things that are genuinely different this time, and worth saying so the result is not
dismissed as fast as it is adopted:

* the flip is **symmetrically negative**, not negative-by-the-same-amount. At 15m v1 read -0.210
  against -0.219; here it is +0.162 against -0.419, which is the shape a direction has and a cost
  does not;
* the gate fires at **10.7%** against the 15% its percentile implies, so it is selecting, not
  passing everything through;
* the drawdown is **4.4%** against the flip's 9.5% and v1's 43-67%.

### It reversed on eight years

The sample existed - `MT5_MAX_BARS` is 1,000,000 and the run above used 90,000 bars a symbol. The
full depth is **600,000 a symbol, 3,111 days, 3,000,000 bars across the five**. The identical
feature, the identical geometry, 7.4 times the span:

| span | n | rule R | flip R | gap | sigma |
|---|---|---|---|---|---|
| 464 days | 48 | **+0.162** +/-0.266 | -0.419 | +0.581 | +1.83 |
| **3,111 days** | **356** | **-0.127** +/-0.089 | -0.284 | **+0.158** | **+1.25** |

**The rule's own expectancy went positive to negative**, and the gap moved *away* from the bar
rather than toward it. The gate behaved - it fired at 14.7% against the 15% its percentile implies,
closer than the 10.7% on the short sample - so this is not a feature that stopped working, it is a
feature whose apparent edge was the sample.

That completes the sequence the short-sample section predicted it would join:

| n | R/trade |
|---|---|
| 7 | +0.164 |
| 11 | +0.368 |
| 13 | +0.279 |
| **48** | **+0.162** |
| **356** | **-0.127** |
| 906 | -0.210 |

**And the gap could not have paid even taken at face value.** +0.158R is below the **0.2R the exit
stack costs**, measured separately. So the strongest reading available for v2 - treat 1.25 sigma as
real, ignore that the rule itself loses - still describes an entry whose directional content cannot
cover its own management. There is no configuration of this that reaches an account.

One mechanical note for whoever repeats it. `exp(r_i)` is applied to a **raw** return, which on a
5-minute FX bar is order 1e-4, so `exp(r_i) ~ 1 + r_i` and the softmax over returns is very nearly
uniform. The feature is therefore close to a plain 70-bar price z-score, and the attention weighting
is a far weaker effect than the formula's shape suggests. That matches
`only-the-sign-survives-into-a-weighted-sum`, and it means a simpler feature may carry the same
reading - which is worth knowing before anything is built on the softmax specifically.

## What is not closed

**Closed.** It read +1.83 standard errors on n 48 and **-0.127R on n 356** when the span went from
464 days to 3,111. Nothing about the trigger remains open.

v2's other two changes are **untested**: the breakout body ratio moving 0.50 to 0.60, and replacing
v1's decline on a sub-ATR stop with a floor on the risk. Both were deliberately left at v1's values
so the attention feature could be measured alone - three changes at once produce one number that
attributes to none of them. They are the run after the deeper pull, not before it.

The cost figures above are also a **floor**. The spread is modelled at each feed's median, and this
rule enters on a volatility extreme by construction - so it trades into the tail, where FX runs 50-90
points against a 2-3 point median. A rule that selects for movement does not pay the median.
