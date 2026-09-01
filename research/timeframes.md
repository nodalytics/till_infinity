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
