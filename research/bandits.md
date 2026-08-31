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
