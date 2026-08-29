# Do origins hold when price comes back?

An origin is where volatility turned and the impulse that followed **broke
structure**, so the claim is that unfilled interest was left behind. If that is
true, price returning should be turned away, and the claim should weaken with
each visit as the interest is filled.

Harness: [`harness/revisits.py`](harness/revisits.py). 5m bars, six feeds,
origins found with the production detector.

## What counts

Price is *in* the zone when it trades between its low and high. The origin
**held** if price then left in the impulse's direction by 1.0 volatility units
**before** running through the far side by 0.5.

Held is deliberately the harder test. For a driftless walk, the chance of
travelling 1.0 one way before 0.5 the other is about `0.5 / 1.5` = **33%**, so
that is the number to beat rather than 50%.

## The first version was measuring the impulse

Counting from the bar after the turn gave 92.6% on the first visit. The zone is
the bar *at* the turn, so price is still inside it for the bars immediately
after - and what was being scored was the launching impulse itself, which by
construction goes the right way.

The harness now requires price to leave the zone before any return counts.

## What it says

3,412 returns across gold, eurusd, us100, btc, spx500 and ger40:

| visit | n | held | broke |
| --- | --- | --- | --- |
| 1st return | 1,440 | **63.5%** | 36.5% |
| 2nd | 844 | 55.6% | 44.3% |
| 3rd | 445 | 59.8% | 40.0% |
| 4th+ | 683 | 66.6% | 33.2% |

Two readings, and the second is the more interesting.

**Freshness helps, modestly.** The first return holds 63.5% against 55.6% for
the second - the direction the theory predicts, and the same shape as the
earlier trade-outcome finding of 1.136R never-revisited against 0.822R twice.
But it does not decay further: the third and fourth are no worse, and ger40 rose
with every visit.

**Every visit beats the driftless-walk null of 33%** - but see the synthetics
below, which show that null is far too generous and the real margin is much
smaller than it looks.

## What was done with it

`origin-swing` prefers fresh origins through `max_revisits` rather than
demanding them, because discarding everything past the first return would give
up a lot of setups for eight points of hold rate.

## What this does not say

Held is not profit. It says price left the zone the right way by one volatility
unit before losing half of one the other way - which is the shape a trade needs,
not the trade. Nothing here measures a stop, a target, or a cost.


## Is a break of structure just a deviation with a retail name?

A fair suspicion: "break of structure" is desk language, and the statistical
version would be "price moved several standard deviations". If the two select
the same events, one of them is doing no work.

They do not. `MOVE_VOL` is already the distributional test - the impulse must
be three volatility units, which is a magnitude. The break is **structural**: it
must exceed a *particular* prior extreme, which is a location and is
path-dependent. A five-unit move inside a wide range breaks nothing; a
three-unit move through the edge of a tight one breaks structure.

Taking a larger deviation still - 4.5 units - and asking how often it coincides
with a break:

| feed | both | broke only | large only | agreement |
| --- | --- | --- | --- | --- |
| gold | 100 | 53 | 44 | 69.4% |
| eurusd | 87 | 50 | 58 | 60.0% |
| us100 | 82 | 52 | 56 | 59.4% |
| btc | 431 | 223 | 124 | 77.7% |
| ger40 | 59 | 112 | 20 | 74.7% |

Correlated at 59-78% and neither subsumes the other: every feed has moves large
enough to qualify on size that broke nothing, and breaks that happened on
ordinary-sized moves. So the retail term is not a synonym for the statistical
one - it is a second, different condition, and both are kept.

## Origins as a formation

`origin_points.points` offers them as a third formation beside `pips` and
`runs`, producing the same `Point` so nothing downstream can tell which pass
found a level. On 5m bars, from far fewer points than `runs` produces, it draws
a comparable number of levels - the points are structurally distinct prices
rather than clustered run boundaries:

| feed | run points | origin points | run levels | origin levels |
| --- | --- | --- | --- | --- |
| gold | 797 | 165 | 10 | 15 |
| eurusd | 852 | 155 | 6 | 21 |
| us100 | 763 | 150 | 3 | 19 |
| btc | 3,326 | 651 | 6 | 10 |
| ger40 | 1,524 | 171 | 7 | 8 |

**`confirmed` reads `Origin.settled`, not `when`.** An origin does not exist
until its impulse breaks structure, which is several bars after the turn it is
drawn at. Confirming at the turn would draw a level at a price nobody could yet
have known was one - the look-ahead bug that field exists to prevent.

Whether these levels are *respected* more than the other two formations draw is
for the outcome machinery to say, which is the entire reason for offering them
on the same terms rather than choosing here.


## The synthetics say the null was wrong

Deriv's synthetics are generated processes with a published volatility and no
underlying. Nothing economic happens at any price on a Volatility 75 Index, so
there is no reason for an origin to be respected there. That makes them the
cleanest null available - better than arithmetic, because they run the same
detector over the same shape of series.

20,000 5m bars each, straight from the bridge:

| instrument | origins /1000 bars | 1st return | 2nd |
| --- | --- | --- | --- |
| Volatility 10 | 61.4 | 55.3% | 51.9% |
| Volatility 25 | 58.8 | 55.4% | 49.8% |
| Volatility 75 | 57.7 | 55.3% | 53.4% |
| Volatility 100 | 50.2 | 57.9% | 53.0% |
| Step | 61.5 | 59.1% | 53.8% |
| Boom 1000 | 55.2 | 57.8% | 56.0% |
| Crash 1000 | 59.6 | 58.8% | 57.5% |
| **pooled** | | **57.1%** | **53.6%** |

**A process with no structure holds 57% of the time.** So the 33% arithmetic
null was wrong: it assumed a walk starting at a point, and the test actually
starts when price *enters a zone* - from one side, nearer that side's edge,
which biases the geometry towards "held" before any market behaviour is
involved. The measured null is 55-57%.

That changes the reading of the real instruments considerably:

| | 1st return | 2nd | decay |
| --- | --- | --- | --- |
| real instruments | 63.5% | 55.6% | 7.9 points |
| synthetics | 57.1% | 53.6% | 3.5 points |

The first-return edge over the null is about **six points**, not thirty. Real,
and much smaller than the raw number suggested.

**The freshness effect is the sturdier finding.** Real instruments lose 7.9
points between the first and second return; synthetics lose 3.5, and Boom and
Crash barely move at all. A generated process has no interest to fill, so it
has nothing to decay - and the decay showing up mostly where interest exists is
the part of this that behaves like a market rather than like the method.

**Synthetics produce origins at a similar rate** - 50-61 per 1000 bars - which
is worth knowing on its own: the detector is not finding structure that only
exists in real markets, it is finding a shape, and roughly as much of it either
way. What differs is what happens next.
