# The opportunity model as a supervisor, not a competitor

**Noted 2026-10-08. Not started.** The desk's idea, recorded while it is fresh.

## The idea

`trading/strategies/opportunity.py` currently trades. The proposal is that it
should mostly **support the other strategies instead** - correct them when they
are wrong, and whatever else a model in its position can usefully do for them -
rather than being a tenth thing competing for the same signal.

## Why its position is the right one

This is not a new capability bolted on. `opportunity.py` already *is* the
parameter space:

> `level-scalp`, `thesis-only`, `snap`, `runner`, `sweep-aware`, `swing-level`,
> `approach-scalp`, `fade-to-value` and `confluence-scalp` read the same
> signal, apply the same gates and take the same side. What separates them is a
> handful of numbers... They are **nine points in one parameter space**.

A model that holds the space every other strategy is a point in can say "you
are at X, and for this signal the measured better point is Y" **without any new
machinery**. Nothing else in the repo is positioned to say that, because
nothing else knows the nine are one.

And the machinery that picks between them is a fixed list in an environment
variable, which was measured doing the choosing: entry counts track queue
position almost perfectly, and the strategy at the front (`thesis-only`, 65
trades) scored **worst** at -0.231R while `level-scalp` at position eight took
two trades and scored +0.097R. That is the gap a supervisor would fill.

## What "support" could concretely mean

Rough, unordered, to be narrowed before anything is built:

* **Correct the geometry.** The clearest precedent already exists: per-strategy
  reward floors, each derived from that strategy's own win rate shrunk toward
  the desk's. That is one model correcting another's risk/reward, done by hand
  and shipped. Doing it continuously, per signal rather than per strategy, is
  the same idea with the hand taken off.
* **Veto or defer.** Where a strategy's vector is far from the measured-best
  point for this signal, say so - as a refusal reason in the journal first,
  long before it is allowed to block anything.
* **Fill the gap.** Trade only where no existing strategy's vector is close to
  the measured-best point, instead of competing where one already is.
* **Arbitrate the queue.** Replace "position in an environment variable" with
  something that has a reason.
* **Attribute.** When several strategies would take the same signal, say which
  point in the space the outcome actually rewarded. The journal cannot
  currently answer that.

## What to check before building any of it

* **Does it have the data?** Per-strategy outcomes come from the broker deal
  history keyed with `strategy_for(DEFAULT_MAGIC, ...)`, not the journal, and
  the endpoint retains about 26 days whatever is asked for. A supervisor that
  learns from outcomes is bounded by that window until something stores more.
* **Is "the measured-best point" identifiable?** The same arithmetic that
  bounds the Kalman state applies: nine points, 26 days and a few thousand
  positions may not separate them. The honest first result may be that the
  space is flat, which is itself worth knowing and is cheap to check.
* **Does a correction beat a duty-cycle control?** Every pause or
  rotation rule tried here has matched random pausing at the same duty cycle.
  A supervisor that vetoes is a pause rule wearing a better hat, and it must
  clear the same bar.
* **What does it cost when it is wrong?** A model that corrects nine others
  concentrates risk that is currently spread across nine independent mistakes.

## Where it must start

As a **reporter**. It writes what it would have corrected into the journal and
changes nothing, for long enough to score its corrections against what actually
happened. Only then does it get to act.

That ordering is not caution for its own sake - it is the only way the question
"would this have helped" gets an answer that is not a backtest of itself.
