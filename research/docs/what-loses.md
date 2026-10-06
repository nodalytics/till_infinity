# What the losses are: stops set inside the instrument's own noise

**Measured 2026-10-06** with [`loss_anatomy.py`](../ideas/loss_anatomy.py) on the live journal - 1,562 closed trades paired to the
decision that sized them, 36 trading days - after the desk asked plainly what
causes the losses.

The answer is not the direction. It is that a third of the trades are stopped
within minutes, on stops placed inside the ordinary movement of the instrument,
and those trades are the entire net loss.

## The verdict

| | |
|---|---|
| **Where the money goes** | **465 trades closed in under five minutes and lost -1,647** - more than the book's whole net loss of -1,663.61. 463 of the 465 exited at the **broker**, so the stop was hit rather than a decision taken. |
| **Why those trades die** | Stops under **1.5 volatility units**: 171 trades, **-912.70** (55% of the loss), mean **-0.233R**, 65% stopped out. Against stops of 4-5 units: 239 trades, **+337.80**, **+0.217R**, 48% stopped. |
| **Is it the spread?** | Partly. Day-blocked over 36 days: the spread costs **+0.0885R** a trade [+0.0776, +0.1019], realised R is **-0.0208** [-0.0888, +0.0777], and gross is **+0.0677** [+0.0019, +0.1690]. The cost is larger than any edge present. The gross figure only just excludes zero at 90% and should not be read as an edge. |
| **Is there an edge anywhere?** | **No.** 37 cells across strategy, instrument, timeframe, side, holding time and stop width: 12 have a positive mean R and **none survives Benjamini-Hochberg**. Six survive as *losers*. |

## Holding time is the whole story

| hold | n | profit | mean R | 90% interval | gross R |
|---|---|---|---|---|---|
| < 1m | 23 | -296.64 | -0.636 | - | -0.492 |
| **1 - 5m** | **442** | **-1350.47** | **-0.134** | **[-0.211, -0.068]** | -0.031 |
| 5 - 30m | 825 | -266.87 | +0.033 | [-0.072, +0.209] | +0.113 |
| 30m - 2h | 262 | +127.33 | +0.027 | [-0.047, +0.102] | +0.115 |

The 1-5m bucket is the only one whose interval excludes zero, and it is negative
**before costs** as well as after. Everything held longer is positive gross.

## And stop width is why

| stop_vol | n | profit | mean R | won | stopped |
|---|---|---|---|---|---|
| **0 - 1.5** | 171 | **-912.70** | **-0.233** | 35% | **65%** |
| 1.5 - 2 | 71 | -18.17 | +0.026 | 45% | 55% |
| 2 - 2.5 | 159 | -111.56 | -0.071 | 46% | 54% |
| 2.5 - 3 | 227 | +240.61 | +0.052 | 52% | 48% |
| 3 - 3.5 | 466 | -598.52 | -0.049 | 48% | 52% |
| 3.5 - 4 | 144 | -423.17 | -0.112 | 47% | 53% |
| **4 - 5** | 239 | **+337.80** | **+0.217** | 52% | 48% |
| 8+ | 44 | -18.32 | -0.017 | 55% | 45% |

Not monotonic - 3-4 units is worse than 2.5-3 - but the bottom band is in a
class of its own, and the stop-out rate moves with it: 66% against 45-55%
everywhere else.

`settings.md` says why in its own words, about the setting this is testing:

> a stop closer than one unit is *inside the estimate's own noise* and will be
> taken by ordinary movement rather than by the thesis being wrong

The record now says the same thing with 1,562 closes behind it. `min_stop_vol`
is **1.0**, and `settings.md` records that it was set on **the first two live
trades**.

## What a wider stop would and would not fix

**It would not create an edge**, and `settings.md` already says so: on a
driftless walk a wider stop buys win rate and pays for it in R. What it fixes is
paying spread to be stopped by noise.

**And it would not save most of the losers.** Of the trades that lost, **55%
never reached 0.05R in favour at any point**. Those did not need more room; they were simply wrong, and a wider stop
makes the same loss arrive later.

**Tightening would be worse.** Maximum heat on the 683 winners: median 0.059R,
90th percentile 0.558R. A stop at 0.5R would have killed 13% of them, at 0.25R
27%. The current stop is not too wide anywhere.

**This is conditional, not counterfactual.** A trade that got a 1.0-unit stop is
not the same trade as one that got 4 units: the width comes from the signal's own
`risk_vol` and the level's zone, so narrow stops are a *kind of setup*, not a
dial that was turned down. Widening them changes position size and the chance of
survival; it does not turn one population into the other. What the gradient
supports is that the narrow-stop setups are not worth taking on their current
terms - which a floor expresses more honestly than a filter would.

## The cells, and the absence of an edge

37 cells, Benjamini-Hochberg at q = 0.10. Best positive cells, all failing:

| cell | n | profit | mean R | p |
|---|---|---|---|---|
| strategy `thesis-only` | 287 | +209.30 | +0.160 | 0.735 |
| stop width 4.00-150.67 | 309 | +164.47 | +0.142 | 0.750 |
| instrument volatility_100_index | 66 | +257.48 | +0.125 | 0.050 |
| entry tf 1m | 486 | +66.31 | +0.092 | 0.673 |

Surviving as losers: `hold 1-5m`, **`side/buy`** (-0.082R over 666 against
sells +0.025R over 893), `cycle-scalp` (-0.095R over 324), `5m` entries
(-0.092R over 635), stop_vol exactly 3.00 (-0.068R), `volatility_10_1s_index`
(-0.156R).

`thesis-only` is the most interesting thing on the board: the best mean R on the
desk and the *worst* geometry (median reward-to-risk 0.40). Its direction is
fine and its exits are not. Its interval is [-0.120, +0.666], so it could be
anything.

**The buy/sell asymmetry is unexplained.** It survives multiplicity and it is
desk-wide. It may be the instrument mix - Crash and Boom are traded on both
sides and are asymmetric by construction - or it may be real. It is the open
question this study leaves.

## What this suggests

Raise `TRADING_MIN_STOP_VOL` from 1.0 towards 2.5, which is where the record
stops being negative. Expect it to reduce the loss, not to produce a profit: it
removes trades stopped by noise and cannot add direction, and the desk's gross
edge is +0.068R at best with an interval that nearly touches zero.

It is also worth knowing that this is the fourth independent route to the same
place. [`lrc-retest.md`](lrc-retest.md) found "the mean R is the cost of a tight
stop (median 0.78 ATR)" in backtest; [`structural-target.md`](structural-target.md)
found no target can fix it because cost is set by the stop;
[`walks-and-edge.md`](walks-and-edge.md) explains why reward-to-risk alone
cannot pay; and the live record now says it directly.
