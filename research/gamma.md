# Option expiry and dealer positioning: a force on price that is not information

**Test one is run and it works.** The calendar half of this idea is measured
below; the positioning half needs a collector that does not exist yet, and the
result here is what justifies building it.

## The idea

Market makers who are short options hedge *with* the move and amplify it; makers
who are long options hedge *against* it and suppress it. Near a strike with large
open interest, and near expiry when gamma is largest, that hedging is a force on
price - and none of it is news. A model that watches the tape and the calendar
sees the move and never sees the cause.

That is a real gap in this desk's inputs. [forecasting.md](forecasting.md)
records that every volatility model here is a function of the past.
[implied.md](implied.md) found the one input that is not, by going outside the
price series to VIX. This is the same move applied to **positioning** rather than
to expectations.

## What could be tested today, and what could not

**Open interest is a snapshot.** Yahoo serves the current option chain and no
history, so "where was the gamma on 14 March 2019" is not answerable from any
free source. The positioning version needs months of forward collection before
it can be measured at all.

**The calendar is free.** Monthly expiry is the third Friday; quarterly expiry -
triple witching - is the third Friday of March, June, September and December.
Those dates are computable and need no data.

So test one measures the half that can be measured, and it is the half that
decides whether the other half is worth building.

## Test one: expiry day is measurably quieter, on all four indices

`research/harness/opex.py`. 25 years, 6,286 sessions. Median absolute daily
return in basis points, by sessions from the mark. `base` is the median over
every day in the same window.

| index | -3d | -1d | **expiry** | +1d | +3d | base | expiry / base |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ^GSPC | 58.2 | 50.2 | **45.5** | 53.8 | 47.5 | 52.6 | **0.865** |
| ^NDX | 70.2 | 72.7 | **65.3** | 84.3 | 67.6 | 70.9 | **0.921** |
| ^DJI | 55.4 | 46.6 | **45.1** | 50.0 | 41.6 | 49.6 | **0.909** |
| ^RUT | 86.1 | 79.9 | **60.8** | 89.6 | 79.7 | 79.2 | **0.768** |

**All four are quieter on expiry day**, by 8% to 23%.

### The placebo says it is the expiry and not the calendar

The same test on the **second** Friday of each month, which shares the weekday
and roughly the month position and has no expiry attached:

| index | placebo day | base | ratio |
| --- | --- | --- | --- |
| ^GSPC | 52.8 | 52.6 | 1.004 |
| ^NDX | 67.9 | 70.9 | 0.958 |
| ^DJI | 49.8 | 49.6 | 1.004 |
| ^RUT | 77.7 | 79.2 | 0.981 |

**Flat on all four.** The effect is on the third Friday and not on Fridays, and
not on the middle of the month.

This is the control doing real work. A 0.87 ratio with no placebo is a number;
a 0.87 against a placebo at 1.00, on four indices that do not share their
constituents, is a finding.

### Quarterly pins harder, which is the mechanism's own prediction

| index | monthly | quarterly |
| --- | --- | --- |
| ^GSPC | 45.5 | **44.4** |
| ^NDX | 65.3 | **60.0** |
| ^DJI | 45.1 | **38.9** |
| ^RUT | 60.8 | **56.2** |

Triple witching expires index futures, index options and stock options together,
so there is more open interest to hedge against. More suppression on all four is
what the story predicts rather than something the story has to explain.

### And it rebounds after, on the two that pin hardest

`+1d` against base: ^NDX **1.19**, ^RUT **1.13**, ^GSPC 1.02, ^DJI 1.01. Pinning
predicts exactly this - the hedges come off and the suppressed move arrives late.
Two of four is weak support, but it is support in the predicted direction rather
than a second effect needing its own explanation.

### The split is where it is weakest

Pre-2018 proposes, post-2018 disposes. Index option volume roughly tripled over
the window, so a positioning story should be **stronger** recently:

| index | pre ratio | post ratio | |
| --- | --- | --- | --- |
| ^GSPC | 0.847 | 0.911 | holds, weaker |
| ^NDX | 0.966 | **0.859** | stronger |
| ^DJI | 0.890 | 1.011 | **gone** |
| ^RUT | 0.692 | 0.823 | holds, weaker |

**Three of four survive; ^DJI does not.** And two of the three weakened, which is
the opposite of what growing option volume would predict. That is the honest
caveat on an otherwise clean result, and it is the reason the next section is
narrow.

## What this is worth

**A sizing input for four equity indices, on one day a month.** Roughly 48
instrument-days a year, on 8% of the book - the same scope
[implied.md](implied.md) found for VIX, for the same reason: this desk is 72%
generated synthetics, and a random number generator has no options market.

Two further limits, both real:

* **Daily bars.** This measures a whole session's absolute return. Whether the
  suppression is spread evenly through the day or lives in a particular hour is
  a different question and needs intraday data.
* **It is variance, not money.** Lower expected volatility should reduce size,
  which is where `scaling.by_regime` already reaches. Nothing here has been
  joined to a P&L.

## Test two, which this result justifies

**Build the collector.** `prices/yahoo.py` already exists and yfinance already
serves `Ticker.option_chain`, so a daily snapshot of strike, open interest,
volume and implied volatility for the four indices is a small job. It has to run
forward - there is no history to backfill - which is exactly why the calendar
test came first.

What it would then answer, and the calendar cannot:

1. **Does price gravitate to the largest open-interest strike** into expiry, more
   than to a random nearby strike? The strike is the control: "price ends near a
   round number" and "price ends near the big strike" are different claims and
   the second is only interesting if it beats the first.
2. **Does the sign of dealer gamma predict the character of the day** - trend
   when dealers are short gamma, mean-revert when long? This is the tradeable
   version and the one worth the wait.
3. **Is the effect in the hours or the day?** Intraday snapshots would say.

## The prior, written before test two

*Recorded now so it cannot be adjusted later, the way
[implied.md](implied.md) did it:*

> Test one worked and that raises the prior, but the scope problem is
> unchanged and the split-sample result is the wrong shape. I expect the
> open-interest version to show pinning toward the largest strike that is real
> and **smaller than the round-number effect it has to beat**, and I expect the
> gamma-sign test to be the one that either justifies all of this or ends it.
> The thing that would change my mind fastest is test two point two showing a
> difference in *character* rather than in magnitude - trend against
> mean-reversion is a statement a level desk could act on, and a slightly
> narrower day is not.
