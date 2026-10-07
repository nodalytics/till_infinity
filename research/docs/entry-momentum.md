# Momentum at the entry: the gate is right to be loose, and chasing needs no gate

**Measured 2026-10-07** with [`entry_momentum.py`](../ideas/entry_momentum.py) on 1,557 live
closed trades carrying `pressure_vol`.

Production already refuses a trade when the accumulated run measured by
`structures.cusum` is more than `max_against_vol` **against** it - 1.5
volatility units, live. Two changes were proposed after a chart review of one
day's worst six trades, four of which had entered immediately after a 5-7 unit
displacement:

1. **tighten the against-gate**, because 1.5v scaled by the strategy's horizon
   is a large tolerance
2. **add a "too late" gate**, refusing an entry that chases a run which has
   already happened - momentum *with* the trade, for which nothing exists

Neither survives. The six trades looked like a pattern; 1,557 are not.

## The verdict

| | |
|---|---|
| **Tighten the against-gate?** | **No.** Pooled, a 1.0v limit refuses 390 trades averaging **-0.087R** and takes the book from -933.03 to **+7.41**. On the half the threshold was not chosen on, the same refusal removes 151 trades averaging **-0.018R** - indistinguishable from zero. |
| **Is the threshold even stable?** | **No.** Refusing `against > 0.75v` removes trades averaging **+0.073R** - winners. Refusing `> 1.0v` removes trades averaging **-0.087R**. A 0.16R swing from moving the line 0.25v is a number fitted to the data it was read from. |
| **Add a chasing gate?** | **No, and at 1.5v it is harmful.** `with > 1.5v` would refuse 59 trades averaging **+0.073R**. At every looser setting the refused trades average between -0.040 and -0.007R: nothing. |
| **So what was the chart showing?** | Six losers picked as the day's worst. Selecting the losing trades guarantees they share whatever the losing trades share. |

## The pooled table, which is the trap

| rule | refused | their R | kept R | kept profit |
|---|---|---|---|---|
| nothing refused | 0 | - | -0.001 | -933.03 |
| against > 0.5v | 582 | **+0.066** | -0.041 | -914.98 |
| against > 0.75v | 488 | **+0.073** | -0.034 | -809.00 |
| **against > 1v** | 390 | **-0.087** | +0.028 | **+7.41** |
| against > 1.25v | 282 | -0.082 | +0.017 | -225.44 |
| against > 1.5v | 167 | -0.114 | +0.013 | -377.81 |
| with > 1v | 133 | -0.007 | -0.000 | -896.11 |
| with > 1.5v | 59 | **+0.073** | -0.004 | -1063.24 |

The 1.0v row is the whole loss removed, and it is the only row that does it. A
single cell standing out of eleven, with its neighbours on both sides saying the
opposite, is what a fitted threshold looks like from the inside.

## The split, which is the study

Discovery is everything before 2026-09-20 01:43 UTC, confirmation everything
after. Nothing is chosen on the confirmation half.

| limit | half | refused | their R | kept R | kept 90% interval | kept profit |
|---|---|---|---|---|---|---|
| 0.5 | discovery | 345 | +0.105 | -0.078 | [-0.121, -0.030] | -719.07 |
| 0.5 | confirmation | 237 | +0.011 | -0.010 | [-0.026, +0.008] | -195.91 |
| 0.75 | discovery | 286 | +0.129 | -0.071 | [-0.113, -0.026] | -748.46 |
| 0.75 | confirmation | 202 | -0.006 | -0.003 | [-0.017, +0.012] | -60.54 |
| **1.0** | **discovery** | 239 | **-0.131** | +0.062 | [-0.092, +0.358] | -8.02 |
| **1.0** | **confirmation** | 151 | **-0.018** | -0.001 | [-0.014, +0.012] | +15.43 |
| 1.5 | discovery | 108 | -0.143 | +0.026 | [-0.101, +0.267] | -439.37 |
| 1.5 | confirmation | 59 | -0.061 | +0.001 | [-0.013, +0.013] | +61.56 |

Discovery baseline: n = 778, **+0.003R**, -863.37.
Confirmation baseline: n = 779, **-0.004R**, -69.66.

The refused population's -0.131R becomes -0.018R. The gate finds, on unseen
data, almost exactly nothing.

## Why the pooled figure was so persuasive

The discovery half carries -863.37 of the -933.03 and the confirmation half only
-69.66, while the two halves' **mean R** is +0.003 and -0.004. The desk's signal
has been flat throughout; the first half's damage was large-risk trades, not a
worse read - which is [`what-loses.md`](what-loses.md) again from another angle.

Any rule fitted on everything will therefore find its improvement in the first
half, where the money is, and report it as if it applied to both.

## What this does not say

It does not say momentum at the entry is irrelevant. The top band of momentum
against a trade (**+1.19v and above**: 312 trades, -711.07, **-0.069R**
[-0.130, -0.004]) does exclude zero, and the gate aimed at it is pointed the
right way. What fails is **moving the line**, in either direction, on evidence
that does not survive a split.

The honest reading is that `max_against_vol = 1.5` is defensible where it is,
and that the next proposal to move it should be made from a frozen threshold
tested forward, not from a sweep.
