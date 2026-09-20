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

## The host exists, and it has no GPU

Measured 2026-09-20 on the `stb` machine (the one that also runs the MT5
terminal the live desk trades through):

| | |
|---|---|
| cores | 64 |
| RAM | 125 GB, 119 GB free |
| disk | 506 GB free |
| GPU | **none** - `lspci` shows only host bridges, no display or compute device |
| already running | ollama (embeddings only: `bge-m3`), redis, mongo, nginx, the MT5 terminal |
| load | 0.02 over the last minute; MT5 uses 7% of one core and 1.2 of its 4 GB |

That settles the question this document opened with, and not the way it
guessed. The blocker was never capacity - it is the **GPU**, and there is not
one.

* **`agents` is comfortable.** It wakes on a timer, so CPU inference on 64
  cores is fast enough, and a small quantised model fits in RAM many times
  over. ollama is already installed, so nothing new has to be operated.
* **`council` is not.** Four voices per signal against hundreds of signals an
  hour needs throughput CPU inference cannot give. That is the consumer whose
  cost scales with market activity, so it is also the only one where this
  would change what is *possible* - and it is the one that needs hardware the
  machine does not have.

The other caution is shared, not technical: a training or inference job that
takes all 64 cores is on the same host as the live desk's terminal. Cap it.

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
