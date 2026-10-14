# The 82% return to a displacement origin is a statement about distance

Asked on 2026-10-14: *test the displacement origin again to be sure, we can even
create a statespace version for more tests, test across timeframes (4h and
daily included) and assets*, then *test displacement origins with relationships
thing too*.

This desk records an **82% return rate** to the displacement origin with the
lesson already attached - a target hit rate, not an entry signal. It was
measured on one configuration and without a placebo. Both are fixed here.

## It reproduces everywhere, and so does its placebo

The origin is the halfway mark of the displacing body. The placebo is a price
the same distance away on the **opposite** side, reached through the identical
forward walk, and displacements are spaced so no two share a window.

| family | frame | events | return | placebo | diff |
| --- | --- | ---: | ---: | ---: | ---: |
| fx | 15m | 5,649 | 0.887 | 0.854 | +0.033 |
| fx | 1h | 5,909 | 0.868 | 0.866 | +0.001 |
| fx | 4h | 5,730 | 0.862 | 0.858 | +0.005 |
| fx | 1d | 1,308 | 0.863 | 0.866 | -0.003 |
| metal | 4h | 652 | 0.874 | 0.862 | +0.012 |
| metal | 1d | 117 | 0.838 | 0.855 | -0.017 |
| equity | 1h | 203 | 0.857 | 0.847 | +0.010 |
| synthetic | 15m | 3,140 | 0.881 | 0.850 | +0.031 |
| synthetic | 4h | 563 | 0.847 | 0.888 | -0.041 |

The three-candle **fair value gap** form behaves identically - fx 15m +0.021,
1h -0.006, 4h -0.003, 1d +0.008; metal 4h **-0.064**.

Return rates of 0.838 to 0.887, placebos of 0.847 to 0.894, differences from
+0.033 to -0.064 with no consistent sign. The **synthetic** family is the scale
marker: those processes have no displacement mechanism and read +0.031 at 15m,
so that is what noise looks like at this sample size.

## What the rate actually measures

The cross-asset arm makes it unmissable. Taking a **random** bar and asking
whether price returns to *its* halfway mark gives a return rate of about
**0.95**. A displacement bar's origin gives about **0.86**.

A random bar has a small body, so its origin is a few points away and is
reached almost always. A displacement bar has a large body, so its origin is
far away and is reached less often. **The return rate is a decreasing function
of distance and contains no displacement term.** The 82% on record is the
distance, read as a signal.

## Across a relationship it goes the other way, for a reason worth keeping

When one leg of a known relationship displaces, does the other return to its
own origin? The leader supplies only the **timing**; the follower's origin is
the halfway mark of its own contemporaneous bar. Three columns: the follower's
rate on those bars, its placebo, and its rate at bars chosen at **random**.

| leader to follower | frame | events | return | placebo | anywhere |
| --- | --- | ---: | ---: | ---: | ---: |
| EURUSD to GBPUSD | 1h | 510 | 0.914 | 0.880 | **0.956** |
| EURUSD to EURGBP | 1h | 498 | 0.928 | 0.914 | **0.964** |
| XAUUSD to AUDUSD | 4h | 320 | 0.931 | 0.925 | **0.957** |
| XAUUSD to XAGUSD | 1h | 513 | 0.891 | 0.895 | **0.964** |
| USDJPY to EURJPY | 1h | 501 | 0.866 | 0.912 | **0.956** |

**Eighteen of eighteen rows have `anywhere` at or above `return`.** Conditioning
on the leader displacing makes the follower's origin **less** likely to be
reached than a bar picked at random.

And the mechanism confirms the standing result rather than contradicting it.
`relationships-are-contemporaneous` says the covariation is large and
simultaneous while every lagged measure is null - so when the leader displaces,
the follower moves **at the same time**. Its own bar is therefore wider, its
origin further away, and a further price is harder to reach. The relationship is
real; it hurts this statistic precisely because it is contemporaneous.

## So no statespace version

A module publishing displacement origins would publish a function of distance
under a name that implies structure. The measurement to make first is not a
better origin but the one this file reports: **any** level's return rate against
a matched price, which `level_signatures.py` already does and which seventeen
level constructions have already failed.

What *would* be worth a statespace primitive is the distance-to-return curve
itself - the rate at which return probability decays with distance in typical
bars - because that is a calibration a band can be checked against, and
`no-gaussian-band-is-calibrated` says the tail shape is the open problem.
