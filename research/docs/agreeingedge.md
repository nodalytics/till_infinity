# Does momentum-scalp's rule work?

`momentum-scalp` keeps three exponential averages of the signed edge of calls
arriving for each instrument - half-lives of 3, 12 and 48 calls - and takes a
call only when **all three agree** with the direction it states. It buys a
filter against calls fighting their own context, and it costs the turn, which
it misses by construction.

**It has never traded.** 109 of its 110 refusals in a week are `warmup: the
speeds have not seen enough calls yet`, because `Speeds` was built in
`__init__` and saved nowhere - so every deploy reset the per-feed counter, and
48 calls on one instrument never accumulated between two deploys. That is fixed
separately; whether the rule is any good is this.

## Replayed on 14 days of decisive touches

31,672 touches with a direction and an edge, fed to the real `Speeds` in time
order exactly as the strategy would see them - every call feeds the averages,
taken or not, which is what stops the lines agreeing with themselves.

| | touches | level held |
| --- | --- | --- |
| **would take** | 5,062 | **86.3%** |
| would refuse | 13,925 | 84.1% |
| **gap** | | **+2.2%** |

Permutation p = 0.000 over 1,000 draws. It takes about a quarter to a third of
what it sees.

## It survives the check that killed the last one

`in_origin` looked like a finding at -1.9% pooled and **reversed sign** once
conditioned on the interval, which is how a mixing artefact announces itself.
This does not:

| interval | takes | held | refuses | held | gap |
| --- | --- | --- | --- | --- | --- |
| 1m | 2,164 | 81.9% | 6,526 | 80.7% | **+1.1%** |
| 3m | 1,013 | 86.0% | 2,810 | 82.6% | **+3.4%** |
| 5m | 1,219 | 88.8% | 3,173 | 87.0% | **+1.8%** |
| 15m | 375 | 94.1% | 800 | 93.8% | **+0.4%** |
| 30m | 141 | 99.3% | 358 | 98.3% | **+1.0%** |
| 1h | 91 | 100.0% | 167 | 100.0% | 0.0% |

**Positive in every band**, and largest where the strategy actually trades.
That is a different object from the pooled-only effects this folder has
refuted three times.

## What it does not establish

* **Held rate is not profit.** `reachable.md` is the standing reminder: a level
  holding and a trade paying are different events, and this book's problem has
  been geometry rather than direction.
* **+2.2 points on a base of 84%** is a small edge. It is consistent, which is
  worth more than it is large, but it is not going to rescue a book.
* **The p-value overstates what is known.** Touches of one level are heavily
  autocorrelated, so 1,000 permutations over exchangeable touches is optimistic
  - the same caution `agreeing.md` had to apply to itself.
* **Only 59.9% of touches were warm enough to judge**, in a *continuous* replay
  with no restarts at all. Even with the state persisted, a feed needs 48 calls
  before this strategy has an opinion, and the slower instruments will take a
  long time to get there.

## What to do

Leave it in the list and let it trade now that the warmup can complete. It is
the only strategy on the book whose rule has been checked against the stream it
runs on and come back positive across every timeframe - which is more than is
known about any of the others, including the ones currently making money.

Then judge it on its own outcomes rather than on this, because held rate is not
what pays.
