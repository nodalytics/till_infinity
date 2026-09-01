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

## What that changes, and what it does not

**It does not refute the trade.** A level that holds 99.4% of the time is a real
edge and betting on the hold is the right way to use it.

**It refutes the target.** Running to the opposite barrier asks for roughly
1.7x the median move, and [geometry.md](geometry.md) already found that far
targets are simply not reached - the reward-to-risk gate was refusing winners
and keeping losers for exactly this reason. The barrier is the right *frame*
and the wrong *target*.

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
