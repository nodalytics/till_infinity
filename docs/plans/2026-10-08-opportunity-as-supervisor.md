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

## The machinery it should be built from

Three bodies of method apply directly, and two of them are already in this
repository with measurements attached.

### A Kalman state, because skill drifts

The quantity a supervisor needs is "how good is this point in the space, *now*"
- latent, observed noisily one trade at a time, and slowly drifting as regimes
change. That is a state-space problem and not a mean.

**And the repo already has the frozen version of it.** The per-strategy reward
floors shrink each strategy's win rate toward the desk's 46.7% with `K = 150`.
That weight, `n / (n + K)`, *is* the steady-state Kalman gain of a random walk
at the right noise ratio - so the shipped floors are a Kalman filter with the
time dimension taken out. Adding the filter back is what lets a strategy's
skill **move** instead of being a single number computed once.

The same discipline the level filter needed applies here. Nine strategies over
a 26-day broker window is not many observations, so the state stays small - a
scalar skill per strategy, pooled toward the desk - rather than a parameter
vector per strategy. Identifiability bites harder here than it does on levels.

### Conformal, because a correction needs an interval

A supervisor that says "your reward should be 1.5, not 1.25" invites a trust it
has not earned. What it should say is "1.5, and here is the interval", and then
**act only when that interval excludes the current value**. That is a veto rule
with a reason, rather than a threshold someone picked.

Two things make conformal the right tool rather than a standard error. R
distributions are heavy-tailed and skewed, so a Gaussian interval is wrong in
exactly the tail that matters - which is the same problem the zone's band had
and the same fix, now with two tails. And it gives the supervisor a **self
audit**: when it said the better point was Y, did the outcome land inside the
interval it quoted? Coverage is a question the duty-cycle control cannot answer
and this one can.

### The portfolio literature, because this is a portfolio problem

`portfoliooptimizationbook.com` covers three of the four directions here
directly: **§3.6 Prior Information: Shrinkage, Factor Models and
Black-Litterman** (with §3.6.1 on shrinkage), **§3.5 Heavy-Tailed ML
Estimators** and §3.5.3 on robust estimators, **§4.2 Kalman Filter** with
§4.2.1 on the state-space model, and **chapter 14, Robust Portfolios**.

The sharpest borrowing is **Black-Litterman**, because it is this exact
pattern: combine a prior with a set of *views*, each weighted by its own
confidence. The strategies are the views. The desk's pooled record is the
prior. "Correct them when they are wrong" is what that machinery does, and it
has been studied for thirty years.

**And the literature predicts the failure mode.** Nine strategies that "read
the same signal, apply the same gates and take the same side" are a
**near-collinear** set of assets. That is precisely the condition under which
naive mean-variance optimisation is known to blow up - it piles weight onto
whichever asset looks marginally best and flips every time the estimate moves.
A naive supervisor would do exactly that: concentrate on one point in the space
and churn.

Shrinkage and robust estimation are not decorations on this problem; they are
the things that were invented to stop it. Ledoit-Wolf gives a closed-form
shrinkage intensity for the covariance, which is the same kind of object as the
`K` just estimated for level shrinkage - a variance ratio, not a tuned
parameter.

### The one thing the book does not cover

Conformal prediction is not in it. That is the one place this repo is ahead of
that literature, because `structures/vol/envelope.py` already runs AgACI with
measurements, and the zone calibrator now runs a two-tailed version.

## Combining them, and the models that only exist once you do

The borrowings above are separable. These are not - each is a thing that
exists only because two of them are put together, which is the reason to write
them down rather than implement the list.

### Black-Litterman with conformal confidence

Black-Litterman's weakest input is `Omega`, the confidence attached to each
view. In practice it is hand-set, or derived from a heuristic nobody defends,
and the output is sensitive to it.

Here it does not have to be guessed. **The conformal interval around a
strategy's edge is a measured confidence**, with a coverage guarantee rather
than an assumption, and it is exactly the object `Omega` wants. That is a real
combination rather than a juxtaposition: the book supplies the framework whose
weakest input this repository already knows how to measure, and conformal
prediction is the one thing the book does not cover.

### A hierarchical skill filter: one desk state, nine offsets

Instead of nine independent skill estimates, one shared state `G_t` for the
desk's own condition and a per-strategy offset loading on it. Identical in
structure to the shared drift factor proposed for levels in
`research/docs/structures-roadmap.md`, and it earns its place for the same
reason: it **pools rather than adding per-object dimensions**.

What it buys is a distinction nothing currently makes. When all nine
deteriorate together that is one fact about the desk, not nine facts about
strategies - and the per-strategy view would read it as nine simultaneous
losses of skill and shrink all nine toward a mean that is itself falling.

### Robust location inside the filter

R distributions are heavy-tailed, so a mean R is a poor estimator of anything,
and one outsized trade moves a Gaussian filter a long way. The book's §3.5 and
§4.2 combine straightforwardly: Student-t observation noise in the skill state.

The same change is open on the level filter, which already dodges the problem
upstream by taking the origin rather than the extreme. **One implementation
would serve both**, and the diagnostic for whether it is needed is already
being collected in the conformal score pools.

### Risk parity, because the flat case is the likely one

The most probable honest result is that the nine points do not separate - 26
days and a few thousand positions may simply not distinguish them.

A picker handles that badly: it chooses whichever looks marginally best and
churns. **Weighting by inverse uncertainty handles it correctly without having
to detect it first** - where the estimates are indistinguishable the weights go
flat on their own, and they concentrate only as evidence actually accumulates.
The method degrades into the null result instead of fighting it, which is worth
more here than a better optimiser.

## A new model: correct the geometry, because only that is falsifiable

The one genuinely new object, and it comes from an asymmetry nobody has named.

**A geometry correction is testable from the tape. A veto is not.** If the
supervisor says "this trade's reward should be 1.5, not 1.25", the
counterfactual is recoverable: same entry, same stop, did price reach 1.5R
before the stop? That is a barrier question this repo answers routinely. If the
supervisor instead says "do not take this trade", the trade is never taken and
the counterfactual is gone forever.

So the supervisor should **not** be modelled as "which strategy is best". It
should model **the value of a correction**, whose label is computable:

    for each trade: delta = proposed geometry - actual geometry
                    regret = R(proposed) - R(actual), from the bars

That is a supervised problem with real labels, scoreable over the whole tape
rather than over the 26-day broker window - because it needs bars, not deals.
It sidesteps the data constraint that bounds everything else here.

And it composes with the conformal work: build the interval around **regret**
rather than around edge, and the decision rule falls out with no threshold to
pick - act only where the regret interval is entirely above zero. A correction
that might be worth nothing is not made.

**Start here.** It is the only part of the idea that can be shown to have
helped without being allowed to act first.

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
