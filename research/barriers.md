# The double-barrier trade: two levels, price between them

Not a prediction problem, and framing it as one was a mistake this document
corrects. [timeframes.md](timeframes.md) found a 1h level breaks **0.6%** of the
time, and the note there said that leaves "almost no information in predicting
it". That is true and irrelevant. **If a level nearly always holds, betting on
the hold is the trade** - the question is not which way price goes but whether
the move it makes pays for the risk of being at the level.

The shape is the **triple-barrier method**: two levels are the horizontal
barriers, the hold is the vertical one, and the label is which barrier price
touches first. That is a far better-posed question than a direction call,
because both outcomes are defined in advance and the vertical barrier stops an
open trade being labelled by whatever happened eventually.

Harness: [`harness/barriers.py`](harness/barriers.py), over 16,045 level calls.

## The setup exists

**Price sits between two origins on 20.3% of level calls** - 3,255 of 16,045.
That is not rare, and it is the precondition for the whole idea.

| interval | calls with both barriers |
| --- | --- |
| 1m | 1,375 |
| 5m | 754 |
| 3m | 482 |
| 15m | 318 |
| 30m | 146 |
| **1h** | **105** |
| 2h | 53 |
| 4h | 17 |

The higher timeframes are thin, which is the same arrival-rate problem
timeframes.md found: 105 setups at 1h against 1,375 at 1m.

## And the corridor is wider than the move

| | |
| --- | --- |
| corridor width, p25 | 1.8v |
| **corridor width, median** | **3.3v** |
| corridor width, p75 | 5.6v |

Against how far a touch that **held** actually travelled:

| interval | n | median | p75 | p90 |
| --- | --- | --- | --- | --- |
| 1m | 44,243 | 1.92v | 2.65v | 3.69v |
| 5m | 12,526 | 2.14v | 3.02v | 4.11v |
| 15m | 5,357 | 1.99v | 2.73v | 3.44v |
| 1h | 1,336 | 1.90v | 2.18v | 2.57v |
| 4h | 157 | 1.57v | 1.88v | 2.52v |

**The median hold travels 1.9v into a 3.3v corridor.** It covers about 58% of
the distance to the opposite barrier. At 1h the p90 move is 2.57v - so even the
best tenth of holds does not reach the far side of a median corridor.

## Measured directly: the far barrier *is* reached

The section above inferred that the far barrier is out of reach, from a median
move of 1.9v against a median corridor of 3.3v. **That inference was wrong**,
and the direct measurement is what says so.

[`harness/reachbarrier.py`](harness/reachbarrier.py) walks the bars forward from
every setup where price is standing at one origin, with a 1.0v stop back through
the entry and a 1,800s vertical barrier, and asks which barrier is hit first.

    1,391 setups: price between two origins and standing at one

    far        597   42.9%     reached the opposite origin
    back       695   50.0%     came back through the entry by 1.0v
    neither     98    7.1%     the vertical barrier expired

    when it reached the far origin: median 82s

**The trade completes as designed 42.9% of the time.** Not the 0% the inference
implied.

### Why the inference was wrong

`push_vol` is recorded **at touch resolution**, and a touch resolves as soon as
price travels `resolve_vol` (1.5v) away from the level. So the 1.9v median is
capped by the resolution rule - it measures how far price went *before the
touch was closed out*, not how far it eventually travelled. Comparing it to a
corridor width was comparing two different quantities.

That is the same class of error as `excursion_vol` against `adverse_vol`, which
cost a day: a field that only exists past a threshold, read as though it were
the whole distribution.

## The economics, with the caveat attached

At a 3.3v median corridor against a 1.0v stop, 42.9% at roughly 3.3:1 is

    0.429 x 3.3  -  0.500 x 1.0  =  +0.92v per setup

before costs. That is strongly positive and it is **not a result yet**, for two
reasons worth stating plainly:

* **the corridor width is from the whole population, not this subset.** The
  3.3v median covers all 3,255 setups; these 1,391 are the ones where price was
  standing at an origin, and their corridors have not been measured separately.
  If they are systematically narrower the arithmetic changes.
* **no costs.** [paying.md](paying.md) puts the cost to cross at 0.048v on gold
  and 5.8v on usdcnh. A 0.92v edge survives the first and is erased many times
  over by the second, so this is an instrument-selection question before it is
  a strategy question.

## The higher timeframes behave differently, and thinly

| interval | n | far | back | neither |
| --- | --- | --- | --- | --- |
| 1m | 605 | 44.1% | 55.2% | 0.7% |
| 3m | 189 | 43.9% | 50.8% | 5.3% |
| 5m | 311 | 46.3% | 49.5% | 4.2% |
| 15m | 142 | 43.0% | 49.3% | 7.7% |
| 30m | 74 | 37.8% | 35.1% | **27.0%** |
| **1h** | 46 | 26.1% | 21.7% | **52.2%** |

**At 1h the vertical barrier decides the trade half the time.** The corridor is
wider in price and the 1,800s hold is not enough to cross it, so the outcome is
neither barrier - which is a flat exit rather than a loss, but it is not the
trade either.

Below 15m the traversal rate is flat at 43-46% and "neither" is negligible, so
the fast end is where this setup resolves cleanly. That cuts against the
original idea of running it on higher timeframes, and the sample at 1h is 46
setups, so it is a hint rather than a finding.

## What that changes, and what it does not

**It does not refute the trade.** A level that holds 99.4% of the time is a real
edge and betting on the hold is the right way to use it.

~~**It refutes the target.**~~ **Withdrawn** - see the direct measurement
above. The far barrier is reached 42.9% of the time, and the reasoning that
said otherwise compared a resolution-capped move against a corridor width.

What the numbers argue for instead:

* **take a fraction of the corridor.** At 60% of it the target sits near the
  median hold move rather than beyond the p90. The far barrier still defines
  the trade; it just stops being the exit.
* **the stop is what makes it pay.** The corridor sets the target and the level
  sets the stop, which is beyond the zone rather than beyond the corridor - so
  a 1.9v move against a stop that is a fraction of that is where the ratio
  comes from, not from the distance to the far side.
* **the vertical barrier is `min_hold` and `max_hold`.** Both are now set:
  300s and 1,800s, from [horizon.md](horizon.md).

## Where this leaves `origin-swing`

The strategy that already implements this - "run from one origin to the other,
entering at whichever price reaches first" - has 350 journalled rows and the
target it aims at is the far barrier. On these numbers that target is beyond
where price usually goes, which is a candidate explanation for why it has
produced so little.

That is a hypothesis rather than a finding: 350 rows is what the strategy
*considered*, and how many became trades and what they did is a separate
question this has not asked.
