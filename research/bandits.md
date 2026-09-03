# Where a bandit fits, and where gymnasium does

Not measured - this is a design note. Nothing here is built, and the
recommendation is that most of it should not be.

## What a bandit is for, precisely

A bandit chooses among arms to maximise reward and learns from what it gets.
The defining constraint is **partial feedback**: it observes the reward of the
arm it *pulled* and never the reward of the arms it did not. Everything a
bandit does - the exploration, the confidence bounds, Thompson sampling's
posterior - exists to handle that missing counterfactual.

Which gives the test for whether a problem is bandit-shaped:

> If you would have learned the outcome anyway, whatever you chose, it is not a
> bandit problem. It is a supervised one, and supervised learning wins.

## The alert gate is *not* bandit-shaped

The obvious idea is arms = {alert, stay quiet}, reward = realised push in the
claimed direction net of cost, context = the level's features. That is a
textbook contextual bandit, and `river.bandit.LinUCBDisjoint` implements it.

It is the wrong tool here, and the reason is a deliberate design decision
already in the code. `Watcher._watch_calls` journals **every** call, acted on
or not:

> Only `actionable` calls become signals - but a dataset containing only the
> calls we acted on is the worst possible sample to learn from. It cannot say
> when holding off was right, because holding off is never in it.

So the counterfactual is observed. A touch resolves whether or not anyone was
told about it, and the outcome is recorded either way. The bandit's entire
machinery would be paying a price - exploration, wider confidence, slower
convergence - to solve a problem this system does not have.

Supervised learning on the full sample is strictly better, which is what
[models.md](models.md) measures and what `facto` already attempts.

**Keep that property in mind if the design ever changes.** If alerting ever
became the thing that generates the label - if we only learned outcomes for
trades actually taken - the problem would become genuinely bandit-shaped
overnight, and this note would invert.

## Where it *is* bandit-shaped: attention, not direction

The genuine partial-feedback problems here are about **spending a budget**, and
there are three:

**1. The agents' analysis budget.** `agents/service.py` caps a window at
`MAX_TRIGGERS = 10` with per-instrument dedup, on a box where the LLM window is
the scarcest resource in the system. Choosing which ten instruments to analyse
is exactly a bandit: the reward of analysing gold is only observed if gold is
analysed. Arms are instruments (or instrument-shape pairs), reward is whether
the finding proved out - which the journal can attach later, since findings are
journalled with `confidence` and paired to outcomes.

This is the one worth building. It is small, the arms are few, and the current
policy - first ten past the gate - is not obviously better than random.

**2. Poll allocation across venues.** The collector has a finite request budget
and fourteen instruments across a dozen venues. Reward is data quality: a venue
that is stale, wide, or missing bars is worth fewer polls. Only the venues
polled are observed, so this is partial feedback. `Detector` already measures
staleness and spread per venue, which is most of the reward signal.

**3. Notification cadence.** Which shapes to send and how often, with reward as
engagement. Genuinely bandit-shaped and genuinely low value - the channel is
quiet by design and the sample would take years.

## Gymnasium's actual role, which is not bandits

The example in river's documentation uses `gymnasium` to *supply* a benchmark
environment (`river_bandits/CandyCaneContest-v0`). It is a source of a problem,
not part of the solution - `river.bandit` policies work on any iterable of
arms and need no gymnasium at all:

```python
policy = bandit.BayesUCB(seed=123)
arm = policy.pull(range(n_arms))
policy.update(arm, reward)
```

That is the whole interface. **Gymnasium would earn its place here for a
different reason: as a standard wrapper around our own replay, so policies can
be compared reproducibly.**

We are most of the way there already. `research/harness/` replays stored bars
through the real `Engine` and pairs every call with the outcome of the touch it
opened. An `Env` would add: `reset()` seeks to a point in the stored history,
`step(action)` advances one bar and returns the reward of the action taken,
`observation` is the current level features. That would let a bandit, an RL
policy and a plain threshold be scored against identical market data with one
harness.

Worth noting honestly:

- **It is a dependency on a 640MB box**, and [news-models.md](news-models.md)
  rejected a 418MB checkpoint on exactly those grounds. Gymnasium itself is
  small, but the reason to add it is convention rather than capability, and the
  same Env could be a plain class with `reset`/`step` and no dependency at all.
- **A simulator is only as good as its fidelity**, and today established twice
  that a bars-only replay disagrees with production - the instant-resolution
  fix looked complete on a replay and was still 42.9% wrong live. An Env built
  on the same replay inherits that gap, and a policy tuned inside it would be
  tuned to the gap.

## Recommendation

1. **Do not use a bandit for the alert gate.** The counterfactual is observed
   by design, which makes it a supervised problem, and supervised wins.
2. **Do consider one for the agents' attention budget** - ten slots, few arms,
   reward already journalled, and the incumbent policy is arbitrary. This is
   the only place the shape genuinely fits.
3. **Do not add gymnasium for bandits.** `river.bandit` needs nothing.
4. **Consider an Env-shaped interface around the replay eventually**, for
   comparing policies reproducibly - but write it as a plain class first and
   add the gymnasium API only if something else wants to consume it. Fidelity
   to production matters more than the interface, and that is the part not yet
   established.

## Strategy selection, asked against this document's own test — 2026-09-02

The case not considered above, because the problem had not been measured yet:
**which strategy should own a signal.** Nine of them race, `on_signal` returns
on the first that gets through, and `TRADING_STRATEGIES` is a fixed priority
list. Entry counts track queue position almost perfectly, and the strategy at
the front scores worst on a common stream (see
[failing.md](failing.md)). So the incumbent policy is not merely arbitrary in
the way the agents' ten slots are — it is *measurably* mis-ordered.

That looks like a bandit: arms are strategies, reward is realised R, context is
the signal's features. `river.model_selection.BanditClassifier` and
`river.bandit.BayesUCB` are both installed — river 0.25.0 is already a
dependency, and `LinUCBDisjoint` gives the contextual version.

**Apply the test at the top of this document and it fails.**

> If you would have learned the outcome anyway, whatever you chose, it is not a
> bandit problem.

`_also_wanted` asks **every other strategy what it would have done** with each
signal and journals the answer, and `TRADING_EVALUATE_ALL` is on. 1,757 of
those shadow intents carry an entry, a stop and a target, and scoring them
against 1m bars ranks all nine on identical signals. The counterfactual is
observed, by a mechanism built for exactly this, whose docstring calls it *"the
only honest way to rank them"*.

So the exploration a bandit pays for buys nothing here. Confidence bounds and
Thompson sampling exist to price an unobserved arm; every arm is observed.

### What to use instead

**Full-information expert weighting** — Hedge, or exponential weights — is the
algorithm for choosing among experts whose losses are *all* observed each
round. It is the same family as Exp3 with the exploration term removed, because
that term solves the problem we do not have. In practice this is close to
"score each strategy on a decayed window of its shadow record and take the
argmax", which needs no new dependency at all.

The contextual version is the same: with full feedback, contextual selection is
a per-context supervised ranking, not `LinUCBDisjoint`. And it is needed — the
ranking already differs sharply by instrument family, so one global arm choice
would average boom, gold and the volatility indices together.

`BanditClassifier` answers a different question again — which *model* predicts
best — and the counterfactual there is observed too, for the reason
[the alert gate section](#the-alert-gate-is-not-bandit-shaped) gives. Same
verdict.

### The one genuinely partial-feedback hole, and it is fixable

`_also_wanted` runs **only after some strategy has got through**. If every
strategy refuses a signal, no shadow record is written and no arm is scored on
it. So the record is conditioned on at least one strategy having wanted the
trade, which is precisely the sampling bias `_watch_calls` was built to avoid
on the alerting side.

That is a real gap and it is not a reason to reach for a bandit — it is a
reason to close the gap. The cost is stated in `_also_wanted`'s own docstring:
*"one arithmetic pass per strategy per signal"*. Evaluating every strategy on
every signal, including the ones nobody took, would make the record complete
and the ranking unbiased, and would remove the last argument for partial
feedback here.

### Recommendation, added to the four above

5. **Do not use a bandit to pick strategies.** `evaluate_all` observes the
   counterfactual; use decayed full-information weighting over the shadow
   record instead.
6. **Do run `_also_wanted` on refused signals too**, so the ranking is not
   conditioned on someone having wanted the trade.
7. **Do replace the fixed priority list with something that reads that
   ranking.** This is the change with a measured case behind it: the list is
   currently mis-ordered, and no amount of algorithm choice matters next to
   the fact that position is doing the selecting.

## Is any of this reinforcement learning? — 2026-09-03

Asked directly, and the honest answer is no.

A multi-armed bandit is usually classed as a **degenerate case** of
reinforcement learning: one state, no transitions, reward arriving immediately.
So if this desk were running a bandit, "a very restricted form of RL" would be
fair.

**It is not running a bandit.** Two learners exist and neither is one:

* `trading/policy.py` is **full-information exponential weighting**. Every arm
  reports on every signal through the untaken record, so there is no unobserved
  counterfactual for exploration to buy.
* `structures/breaking.py` is **online logistic regression**, updated once per
  resolved touch, predict-then-update.

Both are **online supervised learning**. The three things that would make it RL
are all absent:

1. **The labels arrive whether or not we act.** A touch resolves, a zone is
   broken or held, and the record is written either way. In RL the environment
   only reveals the consequence of the action taken.
2. **Nothing chooses actions to shape a future state.** A trade does not move
   the market, and the next signal does not depend on the last decision except
   through capacity - which is a constraint, not a transition function.
3. **There is no credit assignment across time.** Every reward is attributed to
   the single decision that produced it. No discounting, no bootstrapping, no
   value function.

So the accurate description is **"online learning, updated per resolution"**,
which is unusual enough to be worth saying plainly and is not RL. Calling it
reinforcement learning would be a claim the code does not support, and the cost
of that claim is not cosmetic: it invites reaching for RL machinery -
replay buffers, discounting, exploration schedules - to solve problems this
system does not have, while the problems it does have are ordinary supervised
ones about labels, leakage and sample size.

**Where RL would genuinely begin.** If position slots, margin or the daily loss
limit were modelled as *state* that a decision changes, then choosing a trade
now would alter what is available later, and the sequence would matter. That is
a real framing - it is the knapsack this desk already half-has, with
`max_positions` refusing 1,270 signals - and it is a different project from
anything built here.

