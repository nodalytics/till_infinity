# What kills a stop, and whether a better entry fixes it

**Measured 2026-11-16.** Five majors, 15m, eight years, ~30,000 coin-sided
races per geometry. The side is a **seeded coin** throughout, so nothing
directional is being claimed and every arm has expectancy exactly zero on a
driftless walk - `1/(1+N)`. A departure is about geometry alone.

## What took the stops

15,555 stop-outs at a 1.0 ATR stop against a 1.0 ATR target:

| | share | later reached target | best after | **holding instead** | killing bar | bars |
|---|---:|---:|---:|---:|---:|---:|
| taken by a **wick** | 51.3% | 80.4% | +5.17R | **-0.59R** | 1.23 ATR | 3 |
| taken by a **body** | 48.7% | 72.2% | +5.22R | **-1.56R** | 1.56 ATR | 3 |
| all | 100% | 76.4% | +5.19R | **-1.06R** | | 3 |

**Half of all stops are taken by a wick** - the bar's extreme reached the stop
and the bar closed back on the right side.

**76.4% of stopped trades later reached their target, and that figure means
nothing.** These are coin-sided entries: it is what price wandering does. It
is also the number most likely to mislead, because "76% of my stopped trades
would have won" is equally true of random ones.

**-1.06R is the figure that means something.** Remove the stop and hold to the
end of the window and the average is slightly *worse* than the -1.00R the stop
paid, so the stop is about fair. The halves disagree sharply though: **-0.59R
after a wick kill against -1.56R after a body kill.** A wick kill costs about
0.41R of unnecessary loss and a body kill saves 0.56R, and at roughly fifty
each they cancel.

## Two ways to answer a wick, and both are arithmetic

**A close-based stop.** Trigger on the close rather than the extreme:

| stop triggers on | hit rate | vs walk | mean R |
|---|---:|---:|---:|
| the extreme | 0.501 | +0.001 | **+0.0024R** |
| the close | **0.587** | **+0.087** | **-0.0064R** |

It buys **8.7 points of hit rate and pays for every one of them**, ending
slightly worse. A close-based stop is a *wider* stop - price may wick through
untouched - while the target still fills on the extreme, so the exit price is
already beyond the stop and each loss exceeds 1R by exactly enough. This is
`fade-to-value`'s lesson in another costume: confirmation there raised the hit
rate from 31% to 48% and dropped reward from 1.88 to 0.94.

**A better entry.** The operator's construction, and a different claim: the
target is the only fixed price, the entry moves `buffer` better and the stop
moves `pad` further out, so `risk = d - buffer + pad` and
`reward = N*d + buffer`. The asymmetry comes from the shift natively rather
than from choosing a reward-to-risk number. What is paid is **fill rate**, and
every figure below is per **signal**, counting an unfilled signal as zero -
an unfilled signal is a forgone trade, not a free option.

| entry offset | R:R | filled | per signal | **day-shuffled** |
|---|---:|---:|---:|---:|
| -0.75 (a stop-entry, chasing) | 0.25 | 63.4% | **-0.1104R** | **-0.1141R** |
| -0.25 | 0.75 | 86.6% | -0.0401R | -0.0382R |
| 0.00 | 1.00 | 99.7% | -0.0107R | |
| +0.25 | 1.25 | 86.8% | +0.0245R | +0.0222R |
| +0.75 (a limit, fading) | 1.75 | 62.9% | **+0.0371R** | **+0.0376R** |

**Monotone and antisymmetric**: fading pays, chasing loses, and the size grows
with the offset. Every cell is exactly zero on a driftless walk - checked at
both extremes - so this looked like short-horizon reversion, which the
candle microscope had independently found.

**The shuffled twin takes 100% of it.** Day-shuffled bars reproduce the ladder
to within 0.004R at every point, and at +0.75 the shuffle is *larger*. Where
`trailing-zscores-fake-reversion` records a twin taking +0.111 of a +0.137
effect, this one takes all of it. So it is a property of the bar process that
needs no cross-day structure, and a reordered market hands over the same
thing - which is another way of saying it carries no information about the
future.

**Caveat on that null**, stated because it bounds the claim: the day shuffle is
weak at this horizon. The entry triggers within 8 bars and the race runs
within 96, so most of the action sits inside a single day, and shuffling whole
days leaves each day's internal sequence intact. The twin taking everything is
decisive about *tradeability* - a reordered series gives the same result - but
it does not identify the mechanism.

## Two bugs found on the way, both of which read as an edge

**The entry bar was never checked for the stop.** The race started at
`filled_at + 1`. At a 0.75 buffer the risk is a quarter of an ATR, well inside
a typical 15m bar, so a limit can fill and be stopped within the same bar -
and the miss grows with the buffer. It produced a clean monotone improvement
to **+0.072R** out of nothing.

**The ambiguous bar resolved as a loss**, which is the conservative choice and
is *not* neutral across geometries: a 1:1 race has its barriers 2 ATR apart
and a typical bar spans that, while a buffered one has them 2.5 apart and
rarely does. Resolving at random instead moved the baseline from -0.0195R to
-0.0107R. That one was not the explanation - the gap widened rather than
closing - but a rule that penalises narrow geometry had to be ruled out before
anything could be read.

## What this leaves

The stop is about fair, the wick half of its kills costs 0.41R and the body
half saves 0.56R, and neither a close-based stop nor a shifted entry changes
that once the arithmetic is accounted for. What remains untested is **sizing**
- a level or a volatility state setting the stop *distance* rather than its
price - which is the one use `levels.py` actually makes of a level and which
no study here has touched.
