# Three small questions: the week, the drift, and a third leg

The remaining items on the inventory that fit in one harness,
`research/ideas/profile_week.py`. Two have clean answers and the third is a
null that the placebo pair caught.

## 1. A weekly profile adds about 4% of what the daily one does

`seasonal.PERIODS` has defaulted to `(24.0, 168.0)` since it was written, and
`Profile.period` said a week "is the other one worth trying" - so the week was
**written and never measured against a day alone**.

Scored on **Q**, because intraday pattern on this desk lives in volatility
rather than direction, and with each arm given its own best base jerk:

| | flat | day | week | both | **day over flat** | **week on top of day** | mean factor |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| EURUSD | 124744 | 126112 | 124866 | 126188 | **+1368** | +76 | 1.33 |
| GBPUSD | 123841 | 124851 | 123848 | 124832 | **+1010** | -19 | 1.36 |
| USDJPY | 111712 | 112410 | 111737 | 112442 | **+698** | +32 | 1.12 |
| USDCHF | 118290 | 119909 | 118443 | 120037 | **+1620** | +128 | 1.27 |
| USDCAD | 132011 | 133027 | 132213 | 133025 | **+1016** | -3 | 1.24 |
| XAUUSD | 87942 | 89629 | 87962 | 89647 | **+1687** | +18 | 1.21 |
| XAGUSD | 64167 | 65788 | 64398 | 65965 | **+1621** | +177 | 1.16 |
| BTCUSD | 88889 | 88939 | 89055 | 89105 | **+50** | +166 | 1.04 |
| `Volatility_75` | 75277 | 75276 | 75271 | 75270 | **-0.6** | -6.0 | 1.00 |
| `Volatility_25` | 103001 | 103001 | 103000 | 103000 | **-0.0** | -0.3 | 1.00 |

**The day wins on 8 of 8 traded instruments and is null on 2 of 2 placebos**,
median +1192. The week adds a median **+54** on top of it - 4.5% of the daily
effect - positive on 6 of 8 but with two negatives and no cell large. On its
own the week is worth +138 against the day's +1192, so the day carries about
nine tenths of it.

**The decision:** keep `PERIODS = (24.0, 168.0)`. It does not hurt, it may help
a little, and the day is doing the work. The week is not worth a separate
lever or a separate fit.

## 1b. Extending the ladder in both directions: nothing new earns a place

Asked whether `(24, 168)` should be wider at both ends. Each period scored
**on top of** the daily profile at 1h bars, so the column is what it adds to
what already works, with the day's own +1010 for scale:

| period | mechanism | median gain on top of the day |
| --- | --- | ---: |
| 4h | the bar boundary | +1 |
| 8h | session rotation | **-63** |
| 12h | half a day | +58 |
| **24h again** | **duplicate - a control** | **+324** |
| **48h** | **none - a control** | **+399** |
| **100h** | **none - a control** | **-3** |
| 168h | the week | -0 |
| 336h | the fortnight | +7 |
| 672h | four weeks, month end | -8 |
| 2190h | the quarter | +3 |
| 8766h | the year | -45 |

Resolvability is reported rather than assumed - a harmonic needs at least four
samples per cycle and at least eight cycles in the sample, and the year sits
right at the second limit with 8.0 cycles in 2.9 years of hourly data.

**The three control rungs are the result.** A second profile at 24 hours gains
+324 and one at 48 hours gains +399 - *more than any genuinely new period* -
while 100 hours gains -3. The reason is arithmetic: harmonic `j` of a 48-hour
period sits at `48/j` hours, so `j = 2` **is** the day, and a 48h profile is a
daily profile with more harmonics. 100 hours has no harmonic near 24 and gains
nothing.

So **100h is the honest control, 48h is a disguised duplicate**, and against
-3 no new period in the ladder clears it. The two controls were put in to show
what a rung gains from flexibility alone and they did more than that: they
said the gain available here is *harmonics on the day*, not more periods.

One rung is worth noting on its own: **8h, the session rotation, is the only
actively harmful period at -63.** The three-session story is the most
intuitive candidate on the list and it is the one that costs the most.

## 1c. Four harmonics on the day, not three

What the controls pointed at, swept directly - each count against the flat
arm, held out, own best base jerk:

| harmonics | EURUSD | GBPUSD | USDJPY | USDCHF | USDCAD | `Vol_75` | `Vol_25` | **median** |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | +1296 | +999 | +409 | +1590 | +898 | -1 | -0 | +898 |
| 2 | +1367 | +1006 | +690 | +1598 | +995 | -1 | +0 | +995 |
| 3 *shipped* | +1368 | +1010 | +698 | +1620 | +1016 | -1 | -0 | +1010 |
| **4** | **+1451** | **+1055** | **+841** | **+1691** | **+1180** | -1 | -0 | **+1055** |
| 6 | +1457 | +1053 | +863 | +1675 | +1178 | -3 | -0 | +1053 |
| 8 | +1453 | +1040 | +845 | +1661 | +1175 | -3 | -1 | +1040 |
| 12 | +1458 | +1044 | +845 | +1665 | +1184 | -3 | -1 | +1044 |

**It peaks at four and plateaus**, and four is best or tied-best on all five
traded instruments - USDJPY gains +143 over three and USDCAD +164.

The shipped comment said three, "because a session shape has two or three
bumps and the fourth starts fitting single hours". The first half is right and
the second half is wrong: **the placebos stay at -1 to -3 at every count
including twelve.** A count that was fitting single hours would show it there,
where there is no session to fit. So the higher counts are not overfitting -
they have run out of shape to describe, which is a different and more useful
fact.

`PROFILE_HARMONICS` is now 4.

### The confound this arm nearly reported as a result

The first gridded run had the daily profile **losing** 24 to 213 nats on
traded instruments and **1 nat on each placebo**. That pattern is the tell:
the placebo profiles have no amplitude (`mean factor` exactly 1.00), so they
move Q by nothing and cost nothing, while a profile with real amplitude moved
it a lot and was punished.

`Profile.factor` is a multiplier whose mean over a sample need not be one -
here it is 1.04 to 1.36. With a **fixed** base jerk, switching the clock on
therefore changes the *average* process noise as well as its shape, and the
clocked arm is scored at a different average Q. Giving every arm its own best
base jerk swung the daily profile from **-24 to +1192**, a 1,200-nat swing
from one confound.

The grid had to be widened too: the first version topped out at 1e-1 and the
best jerk sat on an edge in 9 of 10 cells. An edge on the *flat* arm
understates it and inflates the clock's margin, so the grid now runs 1e-9 to
1e1 and the output marks any winner that is still on an edge. None is.

**The reusable rule: when a lever multiplies a parameter, refit that parameter
in every arm.** Otherwise the comparison is between two averages wearing the
costume of two shapes.

### And the clock only lands through `predict`

Before that, an even quieter version: `Driven.update` forwards straight to the
wrapped member, so passing `when` to it makes the member predict internally
and the softness is **never applied**. All four arms came back identical to
0.1 nats - which reads as a clean null and was a wiring bug. `predict(when)`
then `update(value, noise)` with no `when`.

## 2. The session profile does not drift

| | years | median year-to-year `r` | worst pair | peak hour | agreement |
| --- | ---: | ---: | ---: | ---: | ---: |
| EURUSD | 9 | **0.986** | 0.975 | 15:00 | 0.89 |
| GBPUSD | 9 | **0.986** | 0.953 | 15:00 | 0.56 |
| USDCHF | 9 | **0.987** | 0.959 | 14:00 | 0.89 |
| USDCAD | 9 | **0.973** | 0.878 | 15:00 | 0.78 |
| XAGUSD | 9 | **0.966** | 0.782 | 14:00 | 0.89 |
| XAUUSD | 9 | **0.950** | 0.886 | 14:00 | 0.89 |
| USDJPY | 9 | **0.940** | 0.808 | 14:00 | 0.78 |
| BTCUSD | 6 | **0.938** | 0.767 | 15:00 | 0.67 |
| `Volatility_75` | 6 | **0.320** | -0.236 | 6:00 | 0.33 |
| `Volatility_25` | 6 | **-0.475** | -0.866 | 2:00 | 0.17 |

Fitted independently on each calendar year, the hourly shape correlates
**0.94 to 0.99** with the next year's, on every traded instrument, over nine
years. The peak is at 14:00 or 15:00 UTC and is the same hour in 56% to 89% of
years.

**The placebos are what make this readable.** Deriv's volatility indices run
continuously with no sessions and no human clock, so their fitted "profile" is
estimation noise - and it refits to a *different* shape each year, `r = 0.32`
and `-0.48`, with the peak landing at 6:00 and 2:00. A harmonic fit will
always return something; the placebo rows show what "something" looks like
when there is nothing there, and the traded rows are not that.

**The decision:** one fit is enough. The session profile is a fixture, so a
profile fitted on all available history will not go stale, and refitting it
per year buys nothing. This also confirms the 14-15 UTC peak independently of
the fit that first found it.

## 3. A third leg buys degrees of freedom, not information

`Relating` already takes `legs`, so a third instrument costs nothing to try.
Judged the way the pair work established - build the spread with the hedge
ratio **as of the previous reading**, then test it for reversion - rather than
on `Relating`'s own likelihood:

| dependent | leg 1 | leg 2 | one leg `t` | two legs `t` | better by |
| --- | --- | --- | ---: | ---: | ---: |
| USDJPY | XAGUSD | BTCUSD | -45.86 | -123.96 | **+78.10** |
| USDJPY | XAGUSD | **`Volatility_75` (placebo)** | -45.86 | -122.41 | **+76.55** |
| USDJPY | XAGUSD | **`Volatility_25` (placebo)** | -45.86 | -96.13 | **+50.27** |
| USDJPY | XAGUSD | XAUUSD | -45.86 | -94.20 | +48.34 |
| USDJPY | XAGUSD | EURUSD | -45.86 | -45.97 | **+0.11** |

**A volatility index with no economic connection to the yen improves the
spread's reversion by +76.55, between BTCUSD's +78.10 and gold's +48.34.** The
placebo is not a near-miss, it is in the middle of the pack.

**And the inversion gives the mechanism.** The leg that adds *least* is
EURUSD, at +0.11 - the one most related to USDJPY, both being major dollar
pairs. A leg collinear with the one already there adds no freedom; an
independent leg adds freedom and so fits the residual better whatever it
means. **The more unrelated the third leg, the larger the apparent
improvement**, which is the signature of fitting rather than explaining.

So no third leg. This is the second time the independent placebo pair has
caught something that would otherwise have shipped.

### The first version of this arm was worse than wrong

It compared leg counts on `Relating`'s own likelihood, uncentred, with a fixed
`noise = 1e-6`. It reported likelihoods of `-4e8` and the **placebo gaining
the most**, +3.1e8 nats. USDJPY and XAGUSD are not cointegrated *in levels*,
so an uncentred fit carries a non-stationary residual, and against a
measurement noise far below that residual an extra regressor absorbs anything.
It was measuring which third series best soaks up a drift.

`centre=True` - already `Relating`'s default - and a noise scaled from the
dependent leg's own one-step moves fixed it, and the answer changed from
nonsense to a clean null.
