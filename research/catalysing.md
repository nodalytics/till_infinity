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
