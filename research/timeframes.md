# Do higher-timeframe levels hold better?

The desk claim is that a 1h, 4h or 1d level is stronger - more participants saw
it, so more defend it. Nothing here had cut the record that way: every model
pools the intervals, and [similarity.md](similarity.md) found that pooling is
exactly what let a tautology dominate every score in this repository.

Harness: [`harness/htf.py`](harness/htf.py), over 77,956 resolved touches.

## The claim holds, and the mix is what says so

| interval | n | reject | backcheck | trap | **break** |
| --- | --- | --- | --- | --- | --- |
| 1m | 34,755 | 67.1% | 8.7% | 13.7% | **9.6%** |
| 3m | 24,826 | 72.2% | 5.8% | 17.7% | **4.0%** |
| 5m | 11,791 | 69.6% | 7.3% | 16.8% | **5.7%** |
| 15m | 5,188 | 71.0% | 10.1% | 15.5% | **3.2%** |
| 30m | 376 | 69.1% | 21.0% | 9.8% | **0.0%** |
| **1h** | 1,297 | 90.8% | 2.5% | 6.1% | **0.6%** |
| 2h | 39 | 87.2% | 10.3% | 2.6% | **0.0%** |
| 4h | 149 | 85.2% | 4.0% | 6.7% | **2.7%** |

**A 1m level breaks sixteen times more often than a 1h one**, and the decline
is monotonic from 1m to 1h. It survives the check that killed the earlier
findings here: the whole *mix* moved rather than one rate, so this is not a
definition wearing a percentage.

### The first cut of this was wrong and worth recording

Cut by interval *within* the 300-1,800s duration band, four intervals came back
at exactly **100.0% held**. A perfect number is a definition rather than a
finding - that is what [similarity.md](similarity.md) is about - so it was
checked rather than reported. It was small samples in one slice: 108 touches at
30m, 132 at 1h. The full mix above is the honest version.

## What it does not mean

**"Breaks less" is not "is more tradable."** A 1h level breaking 0.6% of the
time is nearly certain to hold, which means there is almost no information in
predicting it. `breaking.py` has nothing to separate there and the break gate
can never fire on a 1h call. A high hold rate and a high *edge* are different
quantities and this is the first.

**The sample falls off a cliff.** 34,755 touches at 1m against 39 at 2h, and 1d
and 1w produced too few to print. The 1h row is trustworthy; nothing slower is.

**One touch per level, at every interval.** 0.9 to 1.0 touches per distinct
level from 1m to 4h. So a "1h level" in this record is not a price defended
repeatedly over days - it is a price touched once and resolved. That is a limit
on what any of this can say about higher-timeframe *structure*, and it applies
to the whole record rather than to this cut.

## Why this matters to the horizon work

The interval a level was **drawn** on and how long its touch took to **resolve**
are different things, and only the second is where the tautology lives. A 1h
level touched and resolved in fifteen seconds is a fast resolution wearing a
slow label - and the median hold at 1h in this record is **two seconds**.

That is why [horizon.md](horizon.md) scores by realised duration and bands
training by interval only. Getting those the same way round would have
reproduced the mistake this document was written to check for.

## The practical blocker, if higher timeframes are to be traded

Not the model - the arrival rate. 1h produces 1,297 touches to 1m's 34,755, so
evidence accumulates about **twenty-seven times slower**. Any per-instrument or
per-band question asked at 1h needs months of collection where the same
question at 1m needs days.

## Requiring agreement, and what that costs — 2026-09-01

The context requirement was opt-in and most strategies opted out.
`confluence-scalp` carried it as a class flag; the rest waited on
`TRADING_SCALP_NEEDS_CONTEXT`, a staged switch. That switch is gone and
`needs_context` now defaults to true for every strategy, guarded so that a
strategy declaring no `context` at all — `council`, which delegates to members
carrying their own — is not refused on agreement it never asked for.

**The gate is thinner than it sounds.** Measured on the 1,876 resolutions
carrying a confluence list, the first sample since the field reached the
outcome context:

| requirement | anchors | passes |
|---|---|---|
| scalps | 15m, 1h, 4h | 91.8% |
| confluence-scalp | 15m, 1h, 4h, 1d | 92.2% |
| momentum-scalp | 15m, 1h | 90.6% |
| swings | 2h, 4h, 1d, 1w | 82.5% |
| origin-swing, narrowed | 4h, 1d | 72.9% |

The reason is the depth of the flow. The median call has **eight of ten
timeframes agreeing**, and 5m appears on 1,796 of 1,876:

```
timeframes agreeing: 2:73  3:106  4:84  5:145  6:142  7:278  8:307  9:513  10:228
```

A level that nearly everything agrees on cannot separate much, which is the
same thing [strength.md](strength.md) found scoring confluence depth at AUC
0.476 and 0.452 — below the 0.5 that means no information. So this is not a
filter that is expected to earn its keep on selection. It removes the ~8% of
calls that no slower timeframe sees at all, and it makes the requirement
uniform, which is worth having in itself: the old arrangement meant
`level-scalp` and `confluence-scalp` differed on two axes at once and neither
comparison was answerable.

**origin-swing is the one real narrowing.** Its anchors drop from
(2h, 4h, 1d, 1w) to (4h, 1d), taking ten points off what it will look at. The
trade is the space between two origins, and an origin worth running to is not
one that 2h agrees about — 2h sits close enough to a 1h entry bar that
agreement there is nearly the same measurement twice. 1w is dropped from the
other end: it is rare enough that requiring it would amount to requiring 4h and
1d anyway. This strategy has never traded, so the narrowing costs nothing
observed and is a claim about what it should wait for, not a measured
improvement.

## Parked entries do not fill — 2026-09-01

Not a timeframe finding, but it surfaced while asking why the desk had gone
24.5 hours without a trade, and it interacts with everything above: a parked
entry blocks its whole feed while it waits.

`entry_edge_vol = 1.5` parks an entry a volatility unit and a half better than
the market. It shipped on a predicted 14.6% fill rate, never checked. Over the
whole journal:

| | |
|---|---|
| trades taken | 148 |
| taken after a parked wait | 13 (8.8%) |
| signals refused because the feed was already parked | 496 |

Roughly 38 signals refused per parked entry that eventually filled — an upper
bound, since some would have died on another gate. And the trades parking buys
are not better: two closed, −19.73 each against −5.31 for the 147 that went
straight in. n=2 settles nothing about quality; it is the finding about
frequency.

### The cause was not the distance — 2026-09-01, later

`entry_edge_vol` was lowered 1.5 → 0.5 on the reading above, that the resting
price was simply not reached. That reading was wrong, and the next hour of
logs said so: nine rests placed, **zero filled, zero expired, five withdrawn
and every one of them for spread**. Parking at 0.5v raised the rest *rate*
about eightfold — nine in 65 minutes against three in 5.5 hours — and changed
the fill count not at all.

`_turned_against` decided each withdrawal with this:

```python
risk = abs(held.trigger - tick.entry(held.side))
if risk > 0 and spread > risk * self.settings.max_spread_fraction:
```

`risk` is not the trade's risk. It is the distance price still has to travel
to reach the resting price, and it collapses to nothing as price arrives —
which is the event the order is waiting for. The threshold collapses with it,
so any spread at all clears the bar. `_turned_against` runs *before* the
arrival check in `_arrived`, so the withdrawal won the race with the fill
every time.

**A resting entry could not fill through this path.** The 8.8% that ever
arrived "after waiting" are most likely the ones that jumped the gap between
two polls and were never observed near their trigger — which is also why that
number sat close enough to the 14.6% predicted from the depth distribution to
look like a plausible fill rate.

Two things kept it hidden. The local was named `risk`, so the line reads as
the trade's risk against its spread — the same shape as the correct test at
`risk.py:187`, which divides by `intent.reward`. And the test fixture arrived
*exactly* on the trigger, where the gap is 0.0 and `risk > 0` skipped the
guard entirely. Real ticks overshoot.

Fixed by measuring the spread against the target, the same quantity the
entry-time refusal uses, and skipping it when there is no broker order to take
back. `entry_edge_vol` stays at 0.5 — not because 0.5 was shown to be right,
but because the number that would decide it has never once been observed.

**The general shape, again.** This is the same defect as the eleven feeds
polled by nothing and `STRUCTURES_FORMATION` inert for its whole life:
computed correctly, applied to the wrong quantity, and never contradicted
because what it broke produced silence rather than an error.
