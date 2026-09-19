# Small local models

Status: **not built, not measured.** Nothing here exists in the code.

The proposal: run the agent work on small models hosted locally rather than
calling a cloud API.

## What actually calls a model today

Two things, and they have very different shapes:

- **`agents`** wakes on a timer and reasons over the day. Low rate, tolerant of
  latency, and the place where a weaker model shows up as worse judgement
  rather than as a broken desk.
- **`council`** is a strategy - four voices per signal, per round. It is
  currently switched off precisely because that is a model call per voice per
  round against a signal stream running at hundreds an hour. It is the only
  consumer whose cost scales with market activity, and therefore the only one
  where local inference changes what is *possible* rather than only what it
  costs.

That split is the whole decision. If the motivation is the bill, `agents` is
not where the bill comes from. If the motivation is making `council` affordable
enough to leave on, then local inference is not an optimisation - it is the
enabling condition.

## The constraint that decides feasibility

The desk runs on a two-core instance with 2.6 GB given to the container, and it
has been OOM-killed repeatedly at that ceiling - four times on 2026-09-17 and
2026-09-18 alone. There is no room to host a model beside it. So this is not a
change to the trading box; it is either

- the **lab** machine, which already hosts the MT5 terminal and has capacity,
  at the cost of making a lab outage take out reasoning as well as execution
  (it already takes out trading - see the operational notes), or
- a **separate** host, which is a new dependency and a new thing to watch.

Neither is free, and the comparison is against an API call that costs money but
never needs patching, never runs out of disk and never has to be restarted.

## What to measure before committing

1. **Does a small model do the job at all?** Replay a month of `agents` wakes
   against both, and compare the decisions - not the prose. An agent that
   writes a fluent note and reaches a worse conclusion is the failure mode, and
   it is invisible to anything but outcome comparison.
2. **What does `council` cost at full signal rate**, measured rather than
   estimated, so the saving has a number on it.
3. **Latency under load.** `council` sits in the decision path. A local model
   that takes eight seconds per voice makes the strategy unusable regardless of
   the quality of its answers, and the two-core box has no spare capacity to
   absorb that.

## What would falsify it

- Decision quality on replayed `agents` wakes is materially worse.
- The measured API spend is small enough that hosting is the more expensive
  option once operational time is counted.
- No host exists with capacity that does not also create a single point of
  failure the desk already has.
