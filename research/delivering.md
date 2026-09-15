# Four names for one object, and the two numbers actually claimed about it

Several bodies of work point at the same thing from different directions and
each calls it something else:

| name | the point it marks | what confirms it |
| --- | --- | --- |
| ZigZag pivot | a local extreme | price retracing `theta` |
| FOCuS change point | where the distribution changed | its statistic clearing a bound |
| perceptually important point | whose removal most distorts the series | a distance criterion |
| change in state of delivery | the open of the run that began the prior move | a close beyond it |
| order block origin | the same candle under another name | - |
| this desk's `Level` | a price repeatedly turned at | decisive interactions |
| `structures/cycles.py`'s turn | a leg's extreme | a 2-sigma retracement |

**They are all "the last price at which the market changed its mind", every one
of them is knowable only after a delay, and the claim attached to all of them is
the same**: price comes back to that point and is rejected there. That is one
hypothesis with several detectors, not several hypotheses, and
[`harness/delivering.py`](harness/delivering.py) treats it that way - one
scoring rule, one control, several ways of nominating the level.

Everything is scored from **confirmation**, never from the extreme. Scoring the
first retest from the bar after the extreme is worth 6.5 to 16.7 points of pure
look-ahead, and the slower the detector the more it steals.

## Does price come back and get rejected

Reject and break are the same distance in opposite directions, so neither
outcome is the easier one to reach. The control is matched-random levels: as
many, at random times, at the price prevailing then.

**On the real outright instruments, barely.**

| series | zigzag 1 | zigzag 2 | zigzag 4 | derivative | cisd 5 | **random** |
| --- | --- | --- | --- | --- | --- | --- |
| gold 15m | 0.5065 | 0.5160 | 0.4904 | 0.5242 | 0.4870 | **0.4825** |
| eurusd 15m | 0.4973 | 0.4770 | 0.5234 | 0.5114 | 0.5235 | **0.4923** |
| spx500 1h | 0.5277 | 0.5183 | - | - | - | - |

Two to four points over the control, in both directions, on 5,000 bars per
instrument. **This does not reproduce the 63-65% and the 14-23 point gap
reported elsewhere**, and the disagreement should be read as a disagreement
rather than as a refutation: that work ran seven instruments over a 2012-2025
panel plus an independent 2026 one, where this has five thousand bars and one
window, and the touch and resolve definitions are not the same. What can be said
here is that on this sample the effect is not visible.

**On the constructed spreads, enormously - and partly by construction.**

| series | zigzag 1 | zigzag 2 | focus 2 | derivative | cisd 10 | **random** |
| --- | --- | --- | --- | --- | --- | --- |
| btc BINANCE-COINBASE | 0.9017 | 0.9689 | 0.9219 | 0.7965 | 0.6005 | **0.5052** |
| btc BINANCE-KRAKEN | 0.8998 | 0.9606 | - | 0.7711 | 0.5169 | **0.4443** |

The control shows level *placement* matters - 0.90 against 0.51 is not nothing.
But an extreme of a strongly reverting series is, by construction, a point price
moved away from, so a large part of this restates the reversion that
[`constructing.md`](constructing.md) already measured rather than adding a
property of levels. It is reported because the control is the honest way to see
that, not because 0.97 is a tradeable number.

**The one real-instrument result is CISD on BTC.** Its source publishes no
statistics at all - no win rate, no sample size - while being specific enough to
implement, so this is the first number attached to it here:

| btc @ BINANCE 1m | rejected |
| --- | --- |
| cisd, 3-bar run | 0.5781 |
| cisd, 5-bar run | 0.5784 |
| cisd, 10-bar run | 0.6000 |
| derivative | 0.5409 |
| random control | **0.5087** |

Seven to nine points over the control and monotone in run length, on one
instrument. Interesting; not a finding. It is also implemented from the only
precise parts of a description that leaves the run length, the sweep window and
the expiry undefined, so the parameters are swept rather than chosen and this
tests a family rather than a specification.

## Does the market retrace 86% of the previous leg

**No.** Two independent sources assert that cycles close at about 86% of the
previous leg. Measured between consecutive confirmed ZigZag extremes:

| series | theta | n | median | share in 0.80-0.92 | share > 1 |
| --- | --- | --- | --- | --- | --- |
| **GBM (null)** | 2.0 | 3,965 | **1.020** | **0.0666** | 0.510 |
| OU theta=0.05 | 2.0 | 4,340 | 1.008 | 0.0906 | 0.507 |
| gold 15m | 2.0 | 409 | 0.991 | **0.0709** | 0.496 |
| gold 15m | 4.0 | 145 | 0.981 | 0.0690 | 0.483 |
| spx500 1h | 2.0 | 379 | 0.993 | **0.0739** | 0.493 |
| btc spread 1m | 2.0 | 852 | 1.006 | **0.1984** | 0.512 |

The median retracement is **1.00 on every arm including a random walk**, about
half of all legs exceed the one before them everywhere, and the share landing in
a band around 86% is **the same on gold and on Brownian motion**. The ratio of
consecutive leg lengths is simply a quantity whose median is near one; 86% is
inside its natural spread and is not a market property.

The exception is the constructed spread at `theta = 2`, which puts **19.8%** in
the band against the null's 6.7% - three times as much. But its median is 1.006,
so what is concentrated there is a near-**complete** round trip, not a stop at
0.86, which is what a reverting series does and not what the claim says.

## How much depth is left before the turn

The remaining distance from a bar inside a leg to the turn, in units of the
series' own per-bar standard deviation. Not the leg's length: at a randomly
chosen bar inside a leg about half of it is already spent.

| series | theta | median | mean | p75 | p90 | already spent |
| --- | --- | --- | --- | --- | --- | --- |
| **GBM (null)** | 2.0 | **3.04** | 3.99 | 5.27 | 8.40 | 2.52 |
| gold 15m | 2.0 | **2.87** | 3.84 | 5.08 | 8.53 | 2.24 |
| eurusd 15m | 2.0 | **2.81** | 3.73 | 4.90 | 7.84 | 2.32 |
| spx500 1h | 2.0 | **2.98** | 4.09 | 5.35 | 8.56 | 2.58 |
| btc BINANCE-COINBASE spread | 2.0 | **1.68** | 1.75 | 2.31 | 2.91 | 1.39 |
| GBM (null) | 4.0 | 5.04 | 6.60 | 8.90 | 13.62 | 4.64 |
| gold 15m | 4.0 | 5.22 | 6.71 | 9.26 | 13.58 | 4.66 |

There is an answer and it is uncomfortable: **on real outright instruments it is
what a random walk gives you.** Gold's 2.87 against Brownian motion's 3.04,
eurusd's 2.81, spx500's 2.98 - and at the wider threshold gold's 5.22 against
5.04. The remaining depth is a property of the detector's threshold, not of the
market.

Two things in that table are still useful. **The mean is well above the median
everywhere** (3.84 against 2.87), and p90 is three times the median - so a
target set at the mean is set above where half of all turns happen, and a trail
held for the p90 gives away most of the distribution to catch the tail. And the
**constructed spread is the exception**, at 1.68 against the null's 3.04: on a
reverting series the turn comes much sooner, which is the same finding from a
third direction.

## Does breaking the cycle above mean the trend has changed

The sharpest form of the multi-timeframe question, and better posed than
alignment: agreement between timeframes is weak and continuous, and
[`streaming.md`](streaming.md) measured three versions of it at nothing.
*Invalidation* is discrete - the cycle above has a standing pivot, and price
taking it out is an event with a date.

Measured forward 50 bars in units of the series' own mean absolute return,
against bars matched on how far price had just moved, so "after a break" is not
merely "after a large move".

| series | cycle | breaks | after break | matched | z |
| --- | --- | --- | --- | --- | --- |
| **GBM (null)** | 3.0 | 1,178 | -0.235 | -0.424 | **+0.52** |
| GBM (null) | 5.0 | 558 | -0.640 | -0.176 | -0.85 |
| GBM (null) | 8.0 | 259 | -0.467 | -0.351 | -0.15 |
| **OU theta=0.05** | 5.0 | 617 | -4.408 | -2.820 | **-5.55** |
| OU theta=0.05 | 8.0 | 290 | -6.008 | -3.292 | **-6.60** |
| gold 15m | 3.0 | 113 | +0.997 | +0.036 | +0.66 |
| gold 15m | 5.0 | 50 | +1.093 | +3.704 | -1.21 |
| gold 15m | 8.0 | 24 | +3.457 | -0.771 | +1.22 |
| eurusd 15m | 3.0 | 91 | -0.311 | -1.551 | +0.80 |
| spx500 1h | 3.0 | 112 | -1.795 | -1.391 | -0.29 |
| btc spread 1m | 3.0 | 118 | -2.300 | -1.954 | -1.06 |

**The controls prove the test works.** Brownian motion sits at zero at every
cycle size, as it must. The OU control reaches `z = -6.60` - after a "break" on
a mean-reverting series price comes straight back, which is exactly right and is
the effect size this test can resolve when there is one.

**The real instruments sit in the noise.** Between `-1.21` and `+1.22`, no
consistent sign, and no ordering in how big the cycle above is. On this data,
breaking the cycle above does not say the trend has changed. BTC at 1m produced
**zero** breaks at every threshold over 6,900 bars - it trends hard enough that
the coarse ZigZag never sets a pivot that gets taken back - which is a limitation
of the sample rather than a result.

## The one thing that did pay

Everything above is negative or inconclusive, and the useful output was a
**feature set**. Four families, and they are what a reversal is described by
wherever it is described: the **extreme** and how far the leg has run; the
**derivatives**, because a first derivative crossing zero says a turning point
and only the second says which kind; the **extremes behind**, whose loss is the
change of character; and **volatility**, the unit the rest are measured in.

Giving all four to `structures/cycles.py`'s turn-depth head, on an identical
series with an identical seed:

| feature set | depth skill |
| --- | --- |
| stretch, slope, alignment, mother, residual, age | 0.0451 |
| **plus curvature, travelled, the two pivots behind, vol stretch** | **0.1894** |

Four times the skill against the same baseline. The head that predicts how much
further price runs before turning is the piece of this that works, and it got
better by being told the things every one of these sources says a reversal is
made of - even though each source's own headline claim did not survive.

## Two harness defects worth recording, both silent

**FOCuS fed raw returns finds nothing, for ever.** `Focus` divides each
observation by a `scale` whose default is 1.0, and applies a Gaussian
statistic. One-minute log returns are about 1e-4, so the statistic is of order
1e-8 and clears no threshold at all. It is also **one-sided** - `up=True` looks
for an increase in the mean and is blind to half the change points there are.
The first run of this harness printed "nothing found" for FOCuS on every arm and
that looked like a property of the data. Scaled by the returns' own standard
deviation and run in both directions, it finds 1,488 change points on the same
series and tracks the other detectors.

**A confirmed ZigZag pivot cannot be broken before the next one confirms.** If
price re-crosses the last pivot before the next confirms, the detector simply
extends that leg and no intervening pivot ever exists. So a window drawn between
consecutive confirmed pivots contains zero break events **by construction**, and
two versions of the cycle-break test found exactly zero breaks on every series
including both controls. The level that can be broken is the one the market has
already moved past - the pivot behind the standing one - which is also why
`Leg.behind` exists in the shipped model.

Both are the shape this folder keeps finding: a measurement that comes back
empty because the thing being measured could not have appeared, not because it
is not there.
