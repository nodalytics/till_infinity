# Statespace as the structures library: one boundary, everything behind it

Asked for on 2026-10-14, across three statements that are one design:

> we want statespace to be like a lib the engine talks to, gets the result and
> publish it
>
> what goes on or how structures work should all be contained inside statespace
>
> statespace should also find the prices that matter too

This supersedes the framing in `docs/plans/2026-10-14-statespace-into-prod.md`,
which said statespace replaces *the estimator inside* `levels.py` and not
`levels.py`. That was the conservative reading. The instruction is the larger
one: statespace becomes the structures layer, and the engine stops knowing how
any of it works.

## What the engine does today, measured

`engine.py` imports **twenty** modules from `structures` and orchestrates them
itself - `breaks`, `conformal`, `reactions`, `shrinkage`, `cycles`, `levels`,
`rollover`, `spreadquotes`, `zma`, six from `drawing`, six from `learning`, four
from `vol`, and `context`. It is 3,303 lines of deciding what to call in what
order.

The layer behind those imports:

| area | lines | files | has a statespace counterpart? |
| --- | ---: | ---: | --- |
| top-level `structures` | 12,358 | 18 | partly - the estimator, the band, the barriers |
| `vol` | 4,965 | 14 | **no** - the volatility book and the clock |
| `learning` | 4,817 | 18 | partly - and some of it is refuted rather than replaced |
| `drawing` | 3,554 | 15 | **no** - this is where the prices that matter are found |
| `context` | 2,794 | 12 | **no** - sessions, character, releases |
| **total outside statespace** | **28,488** | **77** | |
| `statespace` | 13,966 | 38 | |

**That is the honest size of the instruction**: 28,488 lines across 77 files,
against a library of 13,966 that currently answers a narrower question. Writing
that down first is the point of this document, because every plan that does not
is a plan that discovers it in month two.

## The boundary

One call per `(feed, interval)`, returning everything the engine needs to
publish and nothing about how it was produced.

    reading = statespace.read(feed, interval, bars, state)

`reading` carries the published quantities - where the levels are, what the band
is, the barrier geometry and its probabilities, and whatever the engine
journals - and the engine's job becomes: receive bars, call this, publish the
result, keep the state. **No `structures` import survives in `engine.py` except
this one.**

Two rules make that real rather than cosmetic.

**The engine may not reach inside a reading to recompute anything.** If it needs
a number, the reading carries it. A facade whose consumer still imports
`levels.SECONDS` - which `engine.py:182` does today - is not a facade.

**Statespace owns the orchestration.** "What goes on or how structures work" is
the ordering, the gating, the warm-up and the fallbacks, and that moves inside.
The engine keeps what is genuinely its own: the bus, the journal, scheduling,
publication and risk.

## What has to be built, not moved

Three areas have **no** statespace counterpart, and the third is the one that was
asked for by name.

**The volatility book** (`vol`, 4,965 lines). Statespace drives `Q` from
activity and from the clock and has no estimator of its own that production
could call. `pacing` and `seasonal.Profile` are inputs to a filter, not a
volatility service.

**Session and character context** (`context`, 2,794 lines). `pacing` absorbed
the one piece that was measured - activity - and sessions, releases and
character are untouched.

**Level discovery** (`drawing`, 3,554 lines). This is "the prices that matter",
and statespace models a price rather than finding the prices worth modelling.

### And level discovery has a measured obstacle, which is why it is not easy

The obvious statespace shape for a level is a **mixture**, with each component's
centre a state that the data pulls toward a level. This desk has already tried
that and recorded why it fails: `definitions-cannot-be-states` - a mixture
centre that is a **free** state collapses onto the data, and three members
needed **anchors** before they estimated anything.

So a statespace level finder has to be **anchored**: the centres come from
somewhere outside the likelihood - pivots, round numbers, prior session
extremes, the displacement origin - and the filter estimates their *strength*
and *width* rather than their *position*. That is a different design from "fit a
mixture", and it is the one the evidence allows.

Two more results constrain it. `the level magnet effect` is **refuted** in
`research/docs/`, so a level finder must not assume price is attracted to
levels; and `fade-to-value-targets-the-displacement-origin` records that the 82%
figure is a **target hit rate and not an entry signal**, which is exactly the
distinction a level's published "strength" has to preserve.

## Sequence

Each step is a measurement before it is a deployment, and the first deployment
is a shadow that journals what it would have said.

1. **Define `Reading` and `read()` as a façade over what exists.** No behaviour
   change: it calls today's modules in today's order. The win is that the
   engine's twenty imports become one, and after that every later step is
   invisible to the engine. This is the only step with no measurement, because
   it is a refactor and its test is that the journal is byte-identical.
2. **Swap the estimator behind the façade** for `pooling.Pooled(adapt=True)`,
   scored against `levels.Kalman` on **touch-spaced** observations. Measured
   elsewhere at 5.6x then 2.7x on CRPS, and the production filter is known to
   want a process noise **16,384 times** its constant, so the gap is likely
   large. Shadow first: the zone it implies moves stops.
3. **Move the conformal band into the library** and swap it behind the façade.
   It is measured at PIT 1.5 where no Gaussian band is calibrated and currently
   lives in a research harness.
4. **Wire `pacing`** at the single call site that supplies `drift_per_hour`,
   gated by `behaving.drives_q`, at exponent **1** - measured on the production
   filter, not the 2 the price members want.
5. **`bounding`** against `learning/touches.py` and `learning/breaking.py`, then
   retire those two.
6. **Anchored level discovery**, which is the largest piece and the one with no
   prior art here. It goes last because every step above improves the thing a
   level is measured *with*, and a level finder scored against a mis-set filter
   would be scored against the wrong band.

## What this document is not

It is not an argument that all 28,488 lines should move. `drawing`, `vol` and
`context` are 11,313 lines that **work**, and the case for rewriting them inside
statespace is architectural rather than measured. The case for steps 2 to 5 is
measured. Step 6 is asked for and should be built; steps that are neither
measured nor asked for should wait.

The one thing that should not wait is **step 1**, because it is what makes the
rest cheap: once the engine talks to one boundary, every swap behind it is a
library change rather than a production change.
