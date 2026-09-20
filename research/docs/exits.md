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

## `stale` resolved: the rule works, and there was no leak

Investigated 2026-09-20 after the section above flagged it. Two things in that
flag were wrong.

**`stale` is the desk's own close, not the broker's.** `_stale` in
`trading/service.py` closes a position past its age threshold that has never
gained `risk * stale_move` (0.25R) in our favour. `exit_source: broker` means the
broker *executed* it; the decision was ours. Reading that field as attribution of
cause is what produced "something outside the desk's geometry is closing
positions".

**The -446.01 is the rule limiting a larger loss, not causing one.** Its log line
says "closing flat" while the realised median is -0.259R, which looked like a rule
misdescribing itself into a systematic loss. Against trades that also never gained
0.25R but were not closed stale:

| | n | mean R |
|---|---|---|
| went nowhere, left alone | 370 | **-0.422R** |
| went nowhere, closed stale | 58 | **-0.244R** |
| | | **+0.177R saved per trade** |

137 of the 370 left alone went on to stop out at -1.087R. Closing at -0.24R beats
a 37% chance of -1.09R, and over 58 closes the rule saved about **+10.3R**.

It also fires exactly where intended: `best_r` at the close has median 0.0000 and
a **maximum of 0.0760**, so all 63 were far under the 0.25R threshold and none
were closed while making progress. They are mostly synthetics - crash_500 (15),
volatility_50 (7), boom_1000 (7) - on 5m, held 15-60 minutes.

### `best_r` is not always recorded, and it matters

46 of the peer trades **hit their target while carrying `best_r` < 0.25**, which
cannot happen: a target hit implies at least that much favourable excursion. So
`best_r` is unpopulated for some trades and defaults to zero - `_best` is filled
from observed quotes, so a fast resolution can finish before one lands.

This weakens the peer group rather than the conclusion. The contamination is
trades that *did* move, averaging +0.697R, which pulls the peer mean **up**, so
the rule's +0.177R advantage is if anything understated. But any future analysis
keying on `best_r` needs to treat zero as "unknown" rather than "flat", and the
1,771 maximum noted above is the same field's other fault.

## Per-instrument profit is selection, not skill

Checked 2026-09-20 after the observation that the desk looks "very profitable in
Volatility 100 Index". It does, in the record: 56 closed trades, **+237.69**, 62%
wins, mean R +0.109. Three of the volatility indices are the three most profitable
instruments on the book, which is a striking pattern to see.

It is what looking at twenty instruments produces.

| | |
|---|---|
| `volatility_100_index` | n=56, +237.69, mean R +0.109, **t = +0.81** |
| its rank by mean R among the 20 instruments with 20+ trades | **4th** |
| shuffling which instrument each trade belongs to, the best of 20 reached that P&L | **81.3% of 2,000 runs** |
| ...reached that mean R | **93.3% of runs** |

A result at least this good appears by chance, from the best of twenty, in 93% of
shuffles. The instrument is not an unusual draw; it is a typical one, and its own
t-statistic says so independently.

**`volatility_75_index` deserves a specific warning.** At +716.68 it is the largest
P&L on the book, from **24 trades**, with a mean R of only +0.147 and t = +0.71.
Large money from a small mean R means the money came from position *size* rather
than from better calls, which is the profile most likely to reverse - and 24 trades
is nothing.

This agrees with two measurements taken from other directions. The variance ratios
on 2026-09-19 found the volatility indices to be random walks by construction, and
`impulse-consistency.md` found continuation on them at 49.5% against a 49.4% base
rate. Three independent lines, one answer.

**The general rule this is the fourth instance of today.** Overlapping windows made
the Coinbase premium t = 4.55; bar extremes rather than fills made an inverted boom
signal look like +5.2%; price units rather than relative made every volatility
estimator look like 0.57; and selection across twenty instruments makes one of them
look profitable. Every one of them was a real number in a real record. The control
is what decides, and the control has to be chosen before looking.
