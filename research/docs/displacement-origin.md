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

That reads as a two-and-a-half-fold level effect. **It is not, and the
same-side control is what shows it.**

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

**The confound was the direction of approach, and it was carrying almost all of
it.** Price reaches the origin by **retracing** and the mirrored placebo by
**continuing**. So a third arm was added: a band of the same width at the same
distance on the **same** side - approached downward for a demand zone, exactly
as the origin is - but anchored at an unrelated bar instead of a displacement.

| arm | approach | reject | **break** | held |
| --- | --- | ---: | ---: | ---: |
| origin | retracement | 0.778 | **0.082** | 0.918 |
| placebo, mirrored | continuation | 0.394 | **0.231** | 0.769 |
| **elsewhere, same side** | **retracement** | 0.752 | **0.098** | 0.902 |

The claim splits in two, and the parts are very unequal:

- **0.231 to 0.098** is *a retracement of this depth exhausts*. Nothing to do
  with displacement.
- **0.098 to 0.082** is *this level is a displacement origin*. Real - about 2.9
  sigma on 5,300 arrivals an arm, and consistent by direction at 0.082 against
  0.094 on up pushes - and **1.6 percentage points**.

So the correct statement is that a displacement origin breaks about **16% less
often than a matched retracement**, not sixty percent less often than a matched
price. An earlier version of this file said the latter and it was wrong in what
it attributed to the level.

**What survives is arguably the control, not the level.** A retracement to *any*
price at about two and a half typical bars of depth is rejected 75% of the time
and breaks under 10%. That is a property of retracement depth rather than of
levels, and it is far larger and more general than anything the level-specific
work in this repository has found - which makes depth, not identity, the thing
worth a statespace primitive.

## Orderflow, in the only form this data supports

There is no L2 here, so orderflow is tick volume and candle shape. The FVG idea
names the condition itself - *price retraces into this gap **and tick volume
dries up***. Both the origin and the same-side control are measured, because a
volume effect that appears at any arrival is not a level property.

| frame | origin quiet / loud held (AUC) | elsewhere quiet / loud (AUC) | formation volume AUC |
| --- | --- | --- | ---: |
| 1h | 0.941 / 0.895 (0.3883) | 0.916 / 0.888 (0.4260) | **0.5625** |
| 4h | 0.918 / 0.897 (0.4542) | 0.914 / 0.872 (0.4242) | **0.5516** |
| 1d | 0.932 / 0.891 (0.4047) | 0.873 / 0.897 (0.5538) | - |

**A quiet arrival does hold better - and so does a quiet arrival anywhere.** The
control carries the same sign at 1h and 4h, 0.4260 and 0.4242 against the
origin's 0.3883 and 0.4542, and reverses at 1d. So "volume dries up on the
retest" is a property of **arrivals**, not of displacements, and the idea
attributes it to the wrong object.

**What is a level property is the volume on the bar that formed the zone.** It
predicts holding at **0.5516 to 0.5625**, and the control has no formation bar
so there is nothing to explain it away with. A zone formed on heavier volume
holds better. That is the genuine orderflow link in this structure, and it is
worth about six points of AUC.

## How this integrates, and what should not be built

The measurements order themselves by size, and that order is the opposite of
where the apparatus points.

**The large effect is retracement depth, and it deserves the primitive.** A
retracement to *any* price at about two and a half typical bars is rejected 75%
of the time and breaks under 10%. That is general, large, and it is a
**calibration** - `P(reject, break, trap | depth)` - which is exactly the shape
`no-gaussian-band-is-calibrated` says is missing, since the open problem there
is the tail. A depth-to-outcome curve per instrument is a `statespace` module
with a measured job, and nothing in it mentions levels.

**The structures change is one line and it is now measured.**
`drawing/displacement.py` says freshness is deliberately not applied because
*how fast they wear out is a measurement nobody here has made*. It is three
days: fresh zones beat a matched price by two to four points, three-day-old
zones by nothing, fourteen-day-old zones by exactly zero. Expiring a zone at
roughly three days is the change, and it is much shorter than a two-to-four-week
zone implies.

**The origin is a target, not an entry.** Of the arrivals that decide, it is
reached before a mirrored price about four times in five, median seven to nine
bars. `fade-to-origin.md` already found 89-91% of fades stopped out, because a
stop beyond a just-made extreme is close by definition, and a 1.6-point edge in
break rate cannot survive that. For something already in position it is a
reasonable place to expect price to go; as a reason to open one it is not.

**Formation volume belongs on the zone** as an attribute, at six points of AUC
for holding - small, but genuinely about the level rather than about arrivals.

**What should not be built** is anything that treats the origin's *identity* as
the signal. Against the right control that is 1.6 percentage points. The
apparatus around these zones - drawing them, scoring them, filtering them - is
sized for an effect roughly ten times larger than the one that is there.

## Traded, with every filter this session found

`fade-to-origin.md` traded this three ways and found no edge, 89-91% stopped
out, -0.259R on 1d. The measurements above give four filters it did not have -
freshness, a twenty-bar horizon, formation volume, and depth - so the question
is whether they turn it.

Enter at the body edge on arrival within twenty bars, target the push extreme,
hold sixty bars, spread charged on both legs:

| 4h, stop 1 typical bar | n | median R | **uncosted mean R** | win | R:R | median cost | t |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 2,275 | -1.00 | **-0.008** | 0.340 | 1.92 | 0.254 | -0.27 |
| fresh, <= 3 days | 2,144 | -1.00 | -0.007 | 0.341 | 1.90 | 0.259 | -0.22 |
| formed on high volume | 1,138 | -1.00 | -0.033 | 0.341 | 1.90 | 0.272 | -0.80 |
| quiet arrival | 1,138 | -1.00 | +0.005 | 0.348 | 1.90 | 0.341 | +0.12 |
| depth >= 2.5 | 1,096 | -1.00 | -0.049 | 0.271 | 2.51 | 0.261 | -1.01 |
| all three filters | 555 | -1.00 | **+0.027** | 0.360 | 1.86 | 0.396 | +0.45 |

**Uncosted the trade is exactly breakeven, and no filter moves it.** Every
t-statistic is between -1.01 and +0.45. That is a null on traded R quite apart
from costs - which matters, because it means the filters found by measuring
return rates and hold rates **do not transfer to R at all**.

They cannot. The level-specific residual is 1.6 percentage points on the break
rate; the breakeven win rate at an R:R of 1.92 is 34.2% and the observed rate
is 34.0%. A 1.6-point improvement in whether a band holds does not move a
34% win rate into profit.

### The cost is decisive, and the filters make it worse

The spread eats **25% of risk per trade** at a one-bar stop and 15% at two
bars, by the median. And the filters *raise* it - median cost 0.254R becomes
0.396R with all three applied - because selecting fresh, quiet, high-volume
setups selects **tighter bands**, so the risk distance shrinks and the spread
becomes a larger fraction of it. The filters damage the economics by
construction.

An earlier version of this section reported **-0.604R** for the unfiltered
case. That figure was the *mean cost*, 0.596R, inflated by trades where a
narrow band and a small typical bar make `spread / risk` explode; the median
cost is 0.254R. The conclusion was right and the number was not, which is why
both the median and the mean are now printed.

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
