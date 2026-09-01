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

## Corrected: the harness was using the wrong clock

The table below first showed **52.2% "neither" at 1h**, and that was an
artefact of the harness rather than a property of the market. It applied a flat
1,800s vertical barrier to every interval - which is `max_hold`, the ceiling for
a strategy that names no hold of its own. The strategies that actually trade
15m, 30m and 1h all name one:

| strategy | entries | hold for a 1h call |
| --- | --- | --- |
| `origin-swing` | 15m,30m,1h | **21,600s (6h)** |
| `swing-level` | 15m,30m,1h | **21,600s (6h)** |
| `runner`, `fade-to-value`, `approach-scalp` | 15m,30m,1h | **14,400s (4h)** |
| `level-scalp`, `thesis-only`, `sweep-aware`, `snap` | 1m,3m,5m | 1,800s or less |

So a 1h setup in production already gets four to six hours, not thirty minutes.
Re-run with the holds each strategy declares:

    far        627   45.0%
    back       726   52.1%
    neither     41    2.9%

      1m   n=605   far 44.1%   back 55.2%   neither  0.7%
      5m   n=313   far 46.0%   back 49.2%   neither  4.8%
      15m  n=143   far 46.9%   back 52.4%   neither  0.7%
      1h   n= 46   far 54.3%   back 39.1%   neither  6.5%

**1h is the best interval for this setup, not the worst.** 54.3% reach the far
origin against 39.1% stopping out - the only interval where "far" beats "back"
- and the vertical barrier decides 6.5% rather than half. The earlier
conclusion, that higher timeframes time out and the fast end is where this
resolves cleanly, was backwards and was a fact about a constant in the harness.

On 46 setups it is a hint. But it is a hint pointing the way the original idea
pointed, which the artefact had reversed.

## Would a 48-72 hour hold help? No

Measured rather than argued, by running the same walk with 48h on 15m-1h and
72h on 2h-4h:

| | far | back | neither |
| --- | --- | --- | --- |
| production holds (4-6h) | 45.0% | 52.1% | 2.9% |
| 48-72h holds | 45.1% | 52.2% | 2.7% |

**Four setups out of 1,394 change.** The reason is the timing: the median
traversal takes **101 seconds**. A trade that is going to reach the far origin
does it in minutes, and one that has not done so in six hours is not waiting -
it has already hit the stop.

Extending the clock therefore buys nothing measurable and costs three things it
would be wrong to ignore: overnight financing on every night held, weekend gap
exposure on any instrument that closes, and the session gate - which refuses to
*open* a trade whose hold does not fit before its market shuts, so a 48-hour
hold would refuse most FX and index entries outright rather than lengthening
them.

## Where the split falls: 15m is a scalp

The traversal rates put 15m with the fast group rather than with the swings:

| interval | far | back |
| --- | --- | --- |
| 1m | 44.1% | 55.2% |
| 5m | 46.0% | 49.2% |
| **15m** | **46.9%** | **52.4%** |
| 30m | 44.6% | 52.7% |
| **1h** | **54.3%** | **39.1%** |

15m looks like 1m and 5m: "back" beats "far". **1h is the one that is
different** - the only interval where the trade completes more often than it
stops out. So the swings now enter at 30m and above, and 15m has moved to the
scalps.

**30m moved to the scalps too, on the same reading.** It sits with the fast
group at 44.6% far against 52.7% back, so the boundary now falls where the data
puts it rather than where the naming did: the five swing strategies enter on
**1h only**, and everything from 1m to 30m is a scalp.

The swings enter at **1h and above** - 1h, 2h, 4h, 1d, 1w - rather than on 1h
alone. The measurement is about where the *boundary* falls, not about capping
the top: 1h is the fastest interval that separates, and nothing in the table
argues that a 4h or daily level is worse than an hourly one.

Two things about that are worth stating rather than assuming. The swing hold is
4-6 hours whatever the entry interval, so a daily level is traded on a
six-hour horizon - coherent, but it is a fast trade on a slow level rather than
a slow trade. And 1w entries will almost never fire: weekly levels are rare and
`min_hold` plus the session gate bind hardest there.

46 setups at 1h is a thin basis for a boundary, so the thing that would revise
it is more of them - which is what widening the replay past 1h is for.

## One ceiling per style

`max_hold` never governed both. `hold_for` read it only when a strategy named
no hold of its own, so a scalp was capped by a setting and a swing by a
hardcoded `ClassVar` no deployment could reach - and the three call sites that
did pass a ceiling passed the *scalp* one, which is how a swing came to be
governed by a number written for a one-minute thesis.

Two settings now, chosen by the style each strategy already declares:

| | | |
| --- | --- | --- |
| `TRADING_MAX_HOLD_S` | 1,800s | scalps - 1m, 3m, 5m |
| `TRADING_MAX_HOLD_SWING_S` | 21,600s | swings - 15m, 30m, 1h |

Both are **ceilings** rather than defaults: `council` asks for 2,700s as a
scalp and is held to 1,800, where before it simply got what it asked for.
`snap` asks for 120s and keeps it, because a ceiling must not lengthen a trade.

And `hold_for` no longer takes a ceiling argument at all. That is the stronger
fix: a caller cannot hand a swing the scalp ceiling by mistake, and every
caller used to.

## The higher timeframes behave differently, and thinly

| interval | n | far | back | neither |
| --- | --- | --- | --- | --- |
| 1m | 605 | 44.1% | 55.2% | 0.7% |
| 3m | 189 | 43.9% | 50.8% | 5.3% |
| 5m | 311 | 46.3% | 49.5% | 4.2% |
| 15m | 142 | 43.0% | 49.3% | 7.7% |
| 30m | 74 | 37.8% | 35.1% | **27.0%** |
| **1h** | 46 | 26.1% | 21.7% | **52.2%** |

**Withdrawn** - the table above was computed with a flat 1,800s clock that no
higher-timeframe strategy actually uses. See the correction above: with the
holds production declares, 1h is the *best* interval at 54.3% far against 39.1%
back, and "neither" falls to 6.5%.

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
