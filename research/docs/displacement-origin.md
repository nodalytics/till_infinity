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

## Production's own definition, which is a different object

The test above used a **single large bar** with a mark at its midpoint, which
is the fair-value-gap construction the MT5 idea describes. It is **not** this
desk's displacement, and `drawing/displacement.py` is explicit that the two
disagree: there a move is violent because it is **one-sided** - `PUSH_N` = 2
bars with bodies of at least `PUSH_BODY` = 0.65 of their range, all one colour -
and the level is the **preceding** bar's body edge, that bar having a body
between 0.10 and 0.60 of its range, with the leg travelling at least
`MIN_LEG_VOL` = 1.5 volatility units. "A slow grind of four units over six bars
is an `origin` and is not a displacement."

Re-run with those constants, asserted against the source so the two cannot
drift, and with the return counted as `order-block-zones.md` counts it - the
first bar back in the band, once per zone:

| frame | zones | band | line | placebo | diff |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1h | 6,708 | 0.890 | 0.843 | 0.876 | +0.015 |
| 4h | 5,252 | 0.878 | 0.837 | 0.864 | +0.014 |
| 1d | 1,546 | 0.877 | 0.840 | 0.867 | +0.010 |

The **82%** on record reproduces - 0.877 to 0.890 at 300 bars - and the matched
placebo sits one and a half points under it. So the recorded rate is right and
the level is worth about **+0.014** of it.

## The horizon was the hypothesis, and it was correct

`order-block-zones.md` flagged the objection itself: fifty days is long enough
to wander back to most places. If so, the edge should be **early**:

| horizon | 1h diff | 4h diff | 1d diff |
| ---: | ---: | ---: | ---: |
| 100 bars | **+0.024** | +0.019 | +0.018 |
| 150 bars | +0.020 | +0.019 | +0.010 |
| 250 bars | +0.015 | +0.015 | +0.010 |
| 500 bars | +0.011 | +0.012 | +0.006 |

It is. The gap halves between 100 and 500 bars while both rates rise, so the
window was diluting the measurement rather than making it.

## And the edge is in time, not in probability

A probability saturates - given long enough, both the origin and a matched
price are reached. Order of arrival does not:

| frame | origin first | ties | **of decided** | median bars, origin / placebo | only origin / only placebo |
| --- | ---: | ---: | ---: | --- | --- |
| 1h | 0.317 | 0.615 | **82.3%** | 10 / 13 | 85 / 11 |
| 4h | 0.277 | 0.648 | **78.7%** | 12 / 14 | 75 / 14 |
| 1d | 0.316 | 0.618 | **82.7%** | - | - |

Both are hit on the same bar 61 to 65% of the time, because one bar's range
spans the pair. **Of the cases that decide, the origin arrives first about four
times in five** - and when only one of the two is ever reached, it is the origin
by 85 to 11. Retracement beats continuation at matched distance by roughly 4:1
in order of arrival while the probability gap is a point and a half.

## How fast they wear out, which nobody here had measured

`drawing/displacement.py` says so in its own docstring: freshness is a property
of the moment of trading, and *how fast they wear out is a measurement nobody
here has made*. Conditioned on a zone still being unvisited at a given age, is
it reached in the next five days?

| age | 1h origin / placebo / diff | 4h | 1d |
| --- | --- | --- | --- |
| **fresh** | 0.830 / 0.808 / **+0.022** | 0.621 / 0.591 / **+0.030** | 0.297 / 0.256 / **+0.041** |
| 3 days | 0.377 / 0.376 / **+0.002** | 0.345 / 0.344 / +0.001 | 0.232 / 0.227 / +0.005 |
| 14 days | 0.125 / 0.125 / **0.000** | 0.139 / 0.139 / 0.000 | 0.123 / 0.118 / +0.005 |
| 28 days | 0.000 / 0.000 / 0.000 | 0.103 / 0.095 / +0.008 | 0.080 / 0.080 / -0.000 |

These are from the run with a five-hundred-bar horizon. The wear-out window is
derived from the longest horizon asked for, so a short sweep caps what can be
reached and prints spurious zeroes at fourteen and twenty-eight days - a
parameter interaction worth naming rather than discovering twice.

**The edge lasts about three days.** Fresh, a zone beats a matched price by two
to four points; at three days old by nothing measurable; at fourteen by exactly
zero on two of three frames. It is largest on **daily** bars, not intraday.

That is the desk's freshness rule confirmed with a number on it, and it is a
much shorter number than a two-to-four-week zone implies.

## What the band does on arrival, which is the question the module asked

`drawing/displacement.py` says the open question is whether the **level is
respected** - *"a different question from whether a particular entry made
money, and one none of that work asked"*. A return rate cannot answer it:
arriving says nothing about what happened next.

Classified on arrival with the desk's own taxonomy - `reject` is a move back by
half a typical bar without closing through, `break` a close through, `trap` a
break that closes back inside, `chop` neither inside thirty bars:

| | origin | placebo |
| --- | ---: | ---: |
| reject | 0.763-0.778 | 0.388-0.410 |
| **break** | **0.082-0.093** | **0.213-0.229** |
| trap | 0.138-0.144 | 0.374-0.396 |
| **held** (reject or trap) | **0.907-0.918** | 0.771-0.786 |

Across 1h, 4h and 1d on 5,507, 4,167 and 1,316 arrivals.

**A displacement origin is about two and a half times less likely to be broken
than a matched price at the same distance** - 8.6% against 22%. The level is
respected, and that is the first substantial answer this family has produced.

It also reframes everything above. Price does **not** return to an origin much
more than to any price that far away: the return-rate edge peaks at +0.037 and
decays to +0.011. But **when price gets there, the origin holds** - a thirteen
point difference in the held rate and a two-and-a-half-fold difference in the
break rate.

### Symmetric in direction, which rules out drift

A displacement is up or down, and a sample with net drift revisits demand and
supply zones differently - so an effect living in one direction would read as a
level property when it is a drift property. Split:

| | origin break | origin held | placebo break | placebo held |
| --- | ---: | ---: | ---: | ---: |
| up pushes, demand, 2,893 | **0.082** | 0.918 | 0.249 | 0.750 |
| down pushes, supply, 2,614 | **0.083** | 0.917 | 0.205 | 0.795 |

Identical to three decimals on the origin side, and the return-rate edge at
twenty bars is +0.043 up against +0.039 down. The only asymmetry is in the
**placebo** - continuation breaks 0.249 after an up push and 0.205 after a down
one, a mild long bias in the sample that touches the control arm and not the
level.

### One construction defect, and one confound still open

The first version counted the **arrival bar** itself and read `reject` at
**0.927** against the placebo's 0.375. Price reaches a demand zone by coming
down into it, so that bar's own high is normally already above the zone - the
reject fired on arrival. Excluding it took 0.927 to 0.775. The gap did not
close, but the construction was carrying a fifth of it.

**The confound that remains is the direction of approach.** Price reaches the
origin by **retracing** and the placebo by **continuing**, because the placebo
is mirrored into the push direction. So part of "the origin holds" may be "a
retracement exhausts" rather than anything about this level.

The control that separates them is a placebo at the same distance **on the same
side** - matched retracement depth, not an origin - and it has not been run.
Until it is, this is a large, consistent, well-controlled-for-distance result
with a known alternative explanation, which is a different thing from a
finding.

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
