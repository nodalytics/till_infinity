# The slow strategies are starved by the queue, not by the supply

`swing-level` has **never traded in 45 days**, and `research/swinging.md`
measures it at **+0.576R a trade** - the best number in this folder. `ride` has
never traded either. The obvious explanation was supply: 87% of published calls
are 5m or faster, and these strategies only accept 15m and 30m.

**That explanation is wrong**, and the shadow record says so.

## What the queue actually does

`TRADING_STRATEGIES` is a priority list and the **first taker wins**, so a
strategy only ever sees what everyone ahead of it refused. Over 7 days, of 232
slow (15m/30m) call-moments:

| strategy | wants it | gets it first |
| --- | --- | --- |
| runner | 91 | **91** |
| sweep-aware | 97 | 46 |
| approach-scalp | 45 | 8 |
| **swing-level** | **76** | **13** |
| origin-swing | 3 | 1 |
| opportunity | 141 | 27 |
| **ride** | **100** | **0** |

**swing-level wanted 76 slow calls and got 13. Sixty-three went to something
ahead of it.** `ride` wanted 100 and got none at all.

There is no shortage of slow calls. There are 232 in a week and the strategies
that want them are fourth and seventh in line.

## And the competition is one-sided

The same table on the 425 fast (1m/3m/5m) call-moments:

| strategy | wants it | gets it first |
| --- | --- | --- |
| sweep-aware | 258 | 258 |
| opportunity | 71 | 20 |
| **swing-level** | **0** | 0 |
| **ride** | **0** | 0 |
| runner | 0 | 0 |

**The slow strategies want none of the fast calls.** They cannot take anything
from `sweep-aware` because they refuse everything it lives on.

That makes the ordering question one-sided: promoting a slow-only strategy
costs the fast ones **nothing**, because there is no call they both want. The
current order charges swing-level for a competition it is not in.

## The principle this suggests

**Most selective first.** A strategy that accepts a narrow slice cannot steal
anything from a broad one, so putting it early is free; putting it late means
it is served only from what the broad ones left, which for a narrow strategy is
mostly nothing.

The present order does the opposite. `runner` and `sweep-aware` are the two
broadest and they are first and second.

## What is actually at stake

The four strategies competing for slow calls, by what is known about them:

| strategy | closes | net | what is known |
| --- | --- | --- | --- |
| runner | 47 | **-250.90** | 40.4% won, **70.2% expired** |
| swing-level | **0** | - | **+0.576R** in replay, all eight cells |
| ride | **0** | - | nothing |
| origin-swing | 1 | -24.80 | nothing |

**`runner` is first in the queue, takes every slow call it wants, and is the
book's second-largest loser.** `swing-level` is fourth, has the best measured
result in the repository, and has never been given a trade.

## The caution

`swinging.md`'s +0.576R is a **replay**, on origins with a refined band, and a
replay is not a live record - this repository has watched several replayed
edges fail to survive contact. Promoting it is not a claim that it works; it is
a claim that it should be *allowed to find out*, which it currently cannot.

Two of the four have no record at all, so any reordering here is choosing
between an instrument that is measured-and-losing and instruments that are
unmeasured. That is a judgement rather than a calculation, and it should be
made as one.
