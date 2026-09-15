# The desk loses because a coin flip pays a spread, and no geometry fixes that

**NET -2,196.44 over 1,244 closed trades**, from the broker's own deal history
rather than the journal. This page is what that number decomposes into.

| | |
| --- | --- |
| win rate | **49.0%** (610W / 633L) |
| average win | +10.65 |
| average loss | **-13.74** |
| gross | +6,498.96 won / -8,695.40 lost |
| commission and swap | -24.03 |

**49.0% is a coin flip.** Six independent studies in this folder said there is no
directional edge and the record agrees. The book loses because the average loss
is **29% larger** than the average win: expectancy is **-1.76 a trade**, and
1,244 trades is -2,190 of the -2,196.

## It is not the synthetics, and that corrects an earlier claim

| book | trades | net | win |
| --- | --- | --- | --- |
| generated | 639 | **-623.47** | 51% |
| real | 605 | **-1,572.97** | 47% |

Both lose and **the real book loses more**. "Stop trading the instruments the
theorem says cannot pay" is still right by theorem and is a quarter of the
problem, not the headline.

## Where it goes: the barriers, not our own exits

| exit | n | net | win | avg win | avg loss | ratio |
| --- | --- | --- | --- | --- | --- | --- |
| stop loss | 591 | **-6,843.05** | 24% | 5.22 | -16.83 | 0.31 |
| take profit | 257 | +4,290.22 | 100% | 16.69 | - | - |
| expert (our own logic) | 369 | **+251.03** | 54% | 6.23 | -5.75 | 1.08 |
| mobile | 29 | +112.92 | 59% | 14.82 | -11.58 | 1.28 |

**The desk's own exit logic is profitable.** The clock and the trail are not the
problem - `expert` exits are net positive at a 1.08 ratio. Everything is lost at
the barriers: **591 stops against 257 targets**, both paying about **17**.

## The reconciliation, which is the finding

Joining the entry order's placed stop and target to the deals that closed the
position, on 728 positions:

```
PLACED target:stop   median 1.00   mean 2.07   p10 0.36   p90 4.95
REALISED             target +15.57, stop -12.03, money ratio 1.29
                     169 targets vs 326 stops = 34.1% hit rate
```

**The median placed geometry is 1.00:1**, and a 1:1 geometry needs a **50% hit
rate** to break even. It gets **34.1%**. A tenth of trades are placed at
**0.36:1** - risking three units to make one.

**And widening the target does not help**, which is the part that closes the
question:

| placed ratio | n | net | win | per trade |
| --- | --- | --- | --- | --- |
| 0.0-1.0 | 364 | -366.19 | 52% | -1.01 |
| 1.0-1.5 | 115 | -170.59 | 49% | -1.48 |
| 1.5-2.5 | 67 | -318.71 | 37% | -4.76 |
| 2.5-4.0 | 75 | -166.64 | 36% | -2.22 |
| 4.0+ | 107 | -191.74 | 34% | -1.79 |

Every band loses. The hit rate falls exactly as fast as the payoff rises - 52% at
1:1 down to 34% beyond 4:1 - which is what `barriers.probability` predicts on a
martingale. **There is no ratio that works, because `deriving.md` says there is
not one.**

## Slicing is real, measured, and not enough

The raw record makes slicing look enormous: 59 sliced positions returned +836.85
at a 4.24 ratio and a 90% win rate, against -3,025.73 at 0.80 for the 1,123
closed whole. **That is the shape a selection effect takes** - a desk that slices
trades already going well produces the same table with the rule doing nothing.

[`slicing.py`](harness/slicing.py) applies the rule to **every** position instead
- same entries, same barriers, same price paths, only the exit rule differing -
over 697 replayable positions in 45 days:

| policy | total | per trade | win | avg win | avg loss |
| --- | --- | --- | --- | --- | --- |
| hold to barrier | -47.28R | **-0.068R** | 25% | 0.81R | -1.00R |
| slice 50% at 1R | -14.21R | **-0.020R** | 34% | 0.67R | -1.00R |

**The rule is worth +0.047R a trade** - better on 85, worse on 42, unchanged on
570, a sign test at about `z = 3.8`. It works exactly as the mechanism predicts:
the win rate rises 25% to 34% while the average win **falls** 0.81R to 0.67R,
because the breakeven stop scratches trades that would have run, and the net of
those two is positive.

So most of the observed gap was selection, and a real effect is left underneath.

**It is still not enough.** Hold-to-barrier bleeds -0.068R a trade, which is
`E[net] = -(c/2) x turnover` measured directly rather than derived. Slicing
removes about 70% of that and leaves a bleed.

## What is actually left

Exit management cannot make a coin flip positive. The remaining levers are all
cost:

1. **Turnover**, which is the multiplier in the theorem.
2. **Spread** - Pepperstone measured 4 to 12 times tighter than peers, and
   nothing has been done with it.
3. **Instrument selection** - refusing the ones where the spread is a large
   fraction of the stop, which `max_spread_risk_fraction` and
   `trading/affordable.py` already express and neither has been tuned against.
