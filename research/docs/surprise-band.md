# The surprise threshold as a band, and why the edge should be at the low end

**Opened 2026-11-21**, on the operator's instruction: *"can the 3sigma be a
range instead of a fixed values, still part of our tests: 1.3 to 3.5 sigma
instead of 3sigma only, add documentation/journal so we can easily traceback
later and see."*

This page is the trail. **Nothing has been measured yet** - it records what was
changed, what the prior evidence says to expect, and what would settle it.

## What a surprise is

`statespace` keeps a running model of where price should be and reports how far
price actually is from it, **in units of its own forecast spread**. That number
is the surprise: a standardised one-step innovation. **3.0 means price arrived
three standard deviations from what the model expected.**

It carries no direction. `surprise.py`: *"it claims no edge of its own... what
it adds is a threshold on it and the geometry around the entry."* So the
threshold is the whole of the rule's contribution, which is why its shape is
worth this much attention.

## What was fixed before, and the asymmetry that made it a bug

The floor and the producer's emission threshold are two different numbers and
they have to agree:

| | |
| --- | --- |
| `proposing.TRIGGER` | what statespace **publishes** a proposal for |
| `SurpriseProfile.least_surprise` | what the rule **accepts** |

A rule floor **above** the producer's trigger throws away work already done.
That happened: at a floor of 3.5 against a trigger of 3.0, *"every proposal in
[3.0, 3.5) was emitted only to be refused here - a band of work done and thrown
away, and a refusal counter that reads as the market being quiet rather than as
two constants in different modules disagreeing."*

A rule floor **below** it is the mirror image and is the new hazard: the
producer publishes nothing underneath its own trigger, so a floor of 1.3 against
a trigger of 3.0 **buys no proposals at all** - it only makes the gate look
open. `_band` clamps to what is published and says so once.

**So the two move together.** Asking for 1.3 at the rule requires
`STATESPACE_TRIGGER=1.3` at the producer.

## Why 3.0 and not 5.0 - already on record

> 3.0 rather than 5.0 because `origin-returns-turn-at-z-one-three` measured
> returns turning at z 1.3 to 1.95 and non-returners reaching 2.2, so z 2.5
> already misses 85-89% of them. The 5-sigma figure came from a bar-level
> anomaly study, not from this service's standardised innovation, and the two
> are not the same scale.

## Why a ceiling, which is the unintuitive half

The same measurement that argues the floor down argues for a ceiling:

| | |
| --- | --- |
| returns turn at | **z 1.3 to 1.95** |
| non-returners reach | **z 2.2** |
| z 2.5 misses | **85-89% of returns** |

Read plainly: **a larger surprise is *less* likely to come back.** If this rule
is a reversion rule, its edge lives at the **low** end of the band and the big
readings are the ones that keep going. A floor of 3.0 therefore sits above
almost every return the earlier study could see, and the current setting may be
selecting against the effect it is trying to trade.

That is a hypothesis with prior support, not a result. It also has an obvious
competing explanation: the low end is where cost bites hardest, because cost in
R is `spread / stop distance` and a quiet bar has a smaller stop.

## What changed in the code

Both ends configurable, **defaults unchanged**, so merging moves nothing:

| setting | default | what it does |
| --- | --- | --- |
| `STATESPACE_TRIGGER` | 3.0 | what statespace publishes a proposal for |
| `TRADING_SURPRISE_MIN` | 3.0 | the rule's floor, clamped up to what is published |
| `TRADING_SURPRISE_MAX` | infinite | the rule's ceiling - new |

A reading above the ceiling is refused under its **own** gate name,
`too-surprising`, rather than pooled with `surprise`. One says the market was
too quiet to pay for a round trip and the other says the move was too large to
be the reversion this rule trades, and pooling them would make the tally
unreadable at exactly the moment a band is being swept.

An inverted or empty band falls back to the defaults with a warning rather than
silently trading nothing, because *"a desk that refuses everything and a desk
with no setups write the same report line"* -
`venue-faults-hide-below-the-strategy`.

## The cost of the lower floor, which is the thing to watch

At 3.0 the trigger fires on about **1.2%** of 15m bars across the admitted
feeds. A standardised innovation reaches 1.3 on roughly a fifth of them, so
**1.3 is something like a sixteen-fold increase in proposals** - each costing
its own round trip.

Three consequences, in the order they will be felt:

1. **Cost.** Sixteen times the trades at the same cost per trade. The admitted
   feeds run 0.5% to 4.2% of target, so a round trip is roughly 0.01 to 0.08 R
   on a 2R target; sixteen times more of them is a materially larger bill.
2. **CPU.** `statespace/actor.py` records that 207 armed feed-intervals at 1m is
   twelve thousand readings an hour, and tis has two cores shared with the live
   desk. The fold cost does not change - the surprise is computed either way -
   but the proposal, decision and journal path downstream does.
3. **Sample, which is the only upside.** `edge-life.md` puts the trades needed
   to tell a win rate from its geometric baseline at **350 to 800**, and the
   desk currently makes a handful a day. Sixteen times the flow is the
   difference between judging this rule in a quarter and judging it in years.

## What would settle it

**A sweep of the band against cost, with the arms this desk already requires.**
The grid is small - a floor from 1.3 to 3.0 crossed with a ceiling from 2.0 to
infinite - so it is not the 414-cell problem, but it is still a grid and the
real best has to be compared to the **shuffled** best rather than to zero:
`rsi-ma-momentum.md` ran 414 cells whose seven-day leaders had 0 of the top 10
positive the following month, and whose day-shuffled market's best beat the real
market's.

Three readings are needed per cell and only the third is an edge:

1. the **rate** - what share of bars fall in the band, which decides whether a
   cell can ever be measured;
2. the **realised R**, net of that feed's own quoted spread;
3. the **difference from the same cell on a day-shuffled twin**.

And the window is the operator's: **7 days to act, 3 months to judge, 1 year as
the maximum lookback**, with the arithmetic stated - 84 trades in a week against
the 350 to 800 a win rate needs.

## Status

| | |
| --- | --- |
| code | **merged, defaults unchanged** |
| live | **not enabled** - `STATESPACE_TRIGGER`, `TRADING_SURPRISE_MIN` and `TRADING_SURPRISE_MAX` are all unset |
| measured | **nothing** |

So the desk is still trading the 3.0 floor with no ceiling. Turning the band on
is a decision about proposal volume as much as about edge, and this page exists
so that whoever reads the result later knows what the setting was and why it was
tried.
