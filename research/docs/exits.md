# Where the money goes, by how the trade ended

Measured 2026-09-20 over 971 closed trades in the journal, 2026-08-26 onward.

Half the desk's trades end by **timing out** rather than by reaching either
barrier, which no analysis here had looked at. This is that look, and it changed
what the problem is twice.

## The hold is not the problem. It is the only positive exit.

| exit | n | profit | median R | median best_r | max best_r |
|---|---|---|---|---|---|
| hold | 483 | **+359.91** | +0.015 | 0.268 | 9.3 |
| **stop** | 226 | **-4,921.80** | -1.020 | 0.000 | **1,771.0** |
| target | 183 | **+3,460.00** | +0.629 | 0.438 | 4.8 |
| stale | 63 | -446.01 | -0.259 | 0.000 | 0.1 |
| unrecorded | 16 | -95.38 | - | - | - |

`exit_source` is `broker` on all but three, so these are the broker's own TP and
SL orders firing rather than the desk closing anything itself.

Two notes on reading the table. **Means over `best_r` are useless** - the maximum
is 1,771, which is the malformed-target fault `policy.py` clips for, so medians
only. And the median `best_r` on a stopped trade is **0.000**: half of stopped
trades never moved in our favour at all, so they were wrong from entry rather
than stopped out of a good position by a tight stop.

## Geometry is not the lever, and this was the second wrong answer

The obvious reading of the totals is that a win pays 0.839R while a loss costs
1.081R at a 46.6% hit rate - realised reward-to-risk 0.78 where 1.15 is needed,
EV -0.186R a trade - so the targets want widening. Per strategy, that is refuted:

| strategy | targets | stops | win rate | win R | loss R | R:R | needs | EV/trade |
|---|---|---|---|---|---|---|---|---|
| thesis-only | 65 | 31 | **67.7%** | 0.50 | 1.15 | 0.44 | 0.48 | **-0.031** |
| inverse | 9 | 6 | 60.0% | 0.58 | 1.02 | 0.56 | 0.67 | -0.063 |
| cycle-scalp | 66 | 75 | 46.8% | 0.98 | 1.13 | 0.87 | 1.14 | -0.139 |
| level-scalp | 7 | 6 | 53.8% | 0.49 | 1.03 | 0.47 | 0.86 | -0.212 |
| **sweep-aware** | 9 | 39 | **18.8%** | **2.52** | 0.98 | **2.56** | 4.33 | **-0.327** |
| confluence-scalp | 3 | 14 | 17.6% | 1.60 | 1.03 | 1.55 | 4.67 | -0.567 |

**A wider target buys reward by selling hit rate, at about the rate that keeps EV
where it was.** The widest-target strategy here is the *furthest* from breakeven
and the narrowest is the closest. Every strategy lands between -0.03 and -0.57R
wherever its barriers sit.

That is exactly what a zero directional edge predicts. With no ability to call
the side, moving a barrier moves you along a fair-odds line and the only thing
that changes is which end of it you pay the costs at. Barrier geometry is a
reparameterisation, not a lever - which is worth stating plainly because "widen
the targets" is the intuitive fix and the data says it does nothing.

## What actually earns: exiting on time, not on a barrier

Hold exits are the only positive category, and for the two strategies with the
widest targets they are where the money is. `sweep-aware` is net positive overall
despite -0.327R a barrier trade, because its 120 hold exits returned +611.80.
`confluence-scalp` is the same shape: +262.10 from 26 hold exits.

Hold exits by strategy, with how far they ever ran:

| strategy | n | mean R | profit | mean best_r | ever +1R |
|---|---|---|---|---|---|
| sweep-aware | 120 | +0.233 | **+611.80** | 0.740 | 18% |
| confluence-scalp | 26 | +0.225 | **+262.10** | 0.891 | **35%** |
| cycle-scalp | 153 | -0.016 | -9.17 | 0.550 | 13% |
| thesis-only | 76 | -0.189 | **-320.34** | 0.345 | 11% |
| inverse | 28 | -0.191 | -137.46 | 0.167 | 0% |

Only 13% of hold exits ever reached +1R and 32% reached +0.5R, so the hold is
mostly cutting trades that genuinely went nowhere - which is the right thing to
do with them. The exception is `confluence-scalp`, where 35% did reach +1R before
timing out, and that is the one place a trail plausibly leaves money behind.

## `stale`: 63 exits, -446.01, and nobody has looked

All 63 closed by the broker, `best_r` median **0.0000** - they never moved in our
favour by any amount - with an adverse excursion median of 0.326R. 25 are
`thesis-only`. Whatever closes these, it is not the desk's own geometry, and they
lose 0.26R each without ever being in profit. Unexplained, and worth a look
before anything else here.

## What this does and does not say

It does not say the desk can be fixed by moving barriers. It says the loss is
distributed across every barrier configuration in use, which is the signature of
the absent direction already measured six other ways today, and that the one
positive exit path is the one that gives up on the trade rather than the one that
aims at something.
