# Structure says where; news says whether anything happens

> **Technicals give the direction, and let you stand in front of it. News gives
> the instrument the move.**

Not two votes on one question - two answers to different ones. A level says
*where* and *which way*, and cannot say whether the market will travel at all.
A catalyst decides which instrument moves today, and does so without reference
to where anyone drew a line.

This is a framing until it is measured. What follows is how to measure it, and
the reason to think it is worth the run.

## The fingerprint, which is already in the book

If structure without a catalyst is a correct position in a market that does not
move, the signature is not a losing trade. It is a trade that **never resolves**
- one that reaches neither the stop nor the target and is closed by the clock.

Measured on 159 closed `thesis-only` trades to 2026-09-09:

| exit | n | share | mean |
| --- | --- | --- | --- |
| target | 54 | 34% | +0.504R |
| stop | 27 | 17% | -1.170R |
| **hold** | **58** | **36%** | **-0.189R** |
| **stale** | **20** | **13%** | **-0.314R** |

**Forty-nine percent expired.** Those 78 trades lost 392 units between them -
not by being wrong, but by holding risk while nothing happened. That is a large
enough share to be the main event rather than a rounding error, and it is
exactly the shape the framing predicts.

It is not *evidence* for the framing. A timeout has other explanations: a hold
too short for the thesis, a target too far, a level that was never going to be
tested. Which is why the experiment below has a control.

## The experiment

The system already collects what this needs. `news` runs a calendar and an RSS
collector into `news.db`, `research/macro.md` and `research/news-models.md`
cover what has been done with it, and every trade is journalled with its feed,
its entry time and its exit kind.

**The question.** Conditioned on a trade being taken, does the presence of a
catalyst near the entry change the *distribution of exit kinds* - specifically,
does the share that expires fall?

**The population.** Every closed trade with an outcome row. No filtering by
strategy: if the effect is real it should show across the book, and if it only
shows on one strategy that is a fact about that strategy.

**The treatment.** A catalyst is a scheduled or published item touching the
trade's own instrument, inside a window ending at the entry. Both halves of
that matter and both are places to get it wrong:

* **Touching the instrument.** A US CPI print is a catalyst for EURUSD and for
  gold; it is not one for a Deriv synthetic, which has no underlying and no
  news. The synthetics are therefore a **built-in control group** - the same
  strategies, the same structure logic, and no catalyst channel that can exist.
  If the effect appears there too, it is not news.
* **Ending at the entry.** Not spanning it. A catalyst that lands *after* entry
  explains a move the trade caught by luck, and counting it is look-ahead of
  the plainest kind. `research/agreeing.md` and `focusing.md` both had to fix
  a version of this and it cost a wrong answer each time.

**The null, and it is not "no news".** Trades cluster in time, and so does
news; both are heaviest when markets are busy. So the control is **matched on
the busyness**, not on the absence of a headline: same instrument, same hour of
day, same realised volatility band, catalyst present against catalyst absent.
Without that, this measures the trading session.

**What would refute it.** The expiry share being the same with and without a
catalyst, once matched. Or the effect appearing on the synthetics, which have
no channel for it.

## Why it is worth running before anything else in this folder

Because it is the only open question here with a **mechanism attached to a
number that is already large**. 392 units of loss sit in trades that expired.
Every other thing measured recently - the agreement count, the zone edge, the
refinement coverage - is a matter of tenths of an R. This is half the book's
trades doing nothing.

And because if it holds, the action is cheap and specific: not a new model, but
a gate that declines to position in front of an instrument with no reason to
move, and a `hold` that is set from when the catalyst is expected rather than
from a constant.

## Run on 2026-09-09, and it cannot be run on this book

Three things stopped it, and the third is the useful one.

### The catalyst source is thinner than it looked

`news.db` has 24,214 articles, and the `symbols` column is **`[]` on every one
of them**. The field exists, is populated on every row, and has never contained
anything - so RSS cannot be attached to an instrument at all. `observations` is
weekly COT, which is not a catalyst.

That leaves the economic calendar: 1,591 `events` tagged by country or
currency, which is enough to say "the dollar had a print in the last two
hours". It is not enough to say a headline was about gold.

### The book barely trades anything with a calendar

Of 203 closed trades over 45 days, **146 are Deriv synthetics** - generated
instruments with no underlying and no news that could reach them. Of the 57
real-instrument trades, only 20 fall on a symbol this harness can map to a
calendar tag, and they split **6 with a catalyst against 14 without**.

Six trades is not a measurement. Matched on instrument and hour of day, **not a
single cell carried both** a catalyst trade and a non-catalyst trade.

### And the placebo fired, which is the part worth keeping

The synthetics were given the **US calendar flag anyway** - a flag for events
that cannot possibly reach a generated index:

| synthetics, US flag | trades | expired |
| --- | --- | --- |
| set | 65 | **58.5%** |
| clear | 81 | **49.4%** |

**A 9.1 point difference on instruments the events cannot touch.** The flag is
a proxy for the active session, and the session is when both trades and events
cluster. Had the real-instrument population been large enough to report, an
effect of that size would have been indistinguishable from the clock - and this
document would have claimed news moved the expiry rate.

That is the control doing its job before the result existed, which is the right
order.

## What it would take to run properly

* **Trade instruments that have a calendar.** This is the binding constraint
  and it is not a data problem. A book that is 72% synthetics cannot test a
  hypothesis about news.
* **Populate `articles.symbols`**, or drop the column. An always-empty field
  that looks like a working join is worse than no field.
* **Keep the placebo.** Any future version needs the synthetic arm reported
  beside the real one, because the session confound is real and is worth 9
  points on its own.

## What the run did settle

**Where the money actually goes**, which is a better question than the one
asked. Over 45 days:

| family | trades | mean | net |
| --- | --- | --- | --- |
| boom | 44 | -0.52R | **-410** |
| volatility indices | 73 | -0.06R | -208 |
| step | 9 | -0.40R | -49 |
| crash | 20 | +0.03R | -17 |
| everything else | 57 | -0.09R | -84 |

**Boom alone is 53% of the losses**, and both directions lose - buy -0.42R over
23 trades, sell -0.63R over 21. [spiking.md](spiking.md) already established
that Boom's spikes are memoryless, gap cv 0.99, and therefore unpredictable.
The book was trading, in size, an instrument this folder had already refuted.

`thesis-only` placed 36 of those 44 Boom trades for -374, and `fade-to-value`
and `confluence-scalp` account for most of the rest of the synthetic damage.
All three were removed on the same day for unrelated reasons, which takes out
the bulk of it - but the reason they cost so much is *what they were trading*,
not only how they sized it.

## What this does not say

* **Not that news predicts direction.** The claim is the opposite - direction
  comes from structure, and the catalyst supplies travel. A version of this
  that starts forecasting the sign of a headline is a different and much harder
  project, and `research/news-models.md` already records what happened the last
  time this repository leaned that way.
* **Not that every move needs a headline.** Flow, positioning and the session
  itself move markets with nothing on the calendar. The claim is about the
  *rate* of going nowhere, not about a necessary condition.
* **Nothing about the synthetics.** Boom, Crash and the volatility indices are
  generated and have no news. If the framing is right, structure alone should
  do *relatively better* there - there is no missing half. That is a second
  testable consequence and a sharp one.
