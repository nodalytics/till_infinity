# The boundary, built the opposite way round from the way it was specified

`docs/specs/2026-10-14-statespace-as-the-structures-library.md` made the façade
step one, because it is what makes everything after it cheap: once a caller
talks to one boundary, every swap behind it is a library change rather than a
production change. `engine.py` imports **twenty** modules from `structures` and
orchestrates them across 3,303 lines.

The façade is `statespace.Desk` and `statespace.Readout`. A caller holds a
`Desk`, hands it a bar, and gets back what it can publish.

    from till_infinity.structures import statespace

    desk = statespace.Desk()
    out = desk.read(feed, interval, when, close, noise, volume=busy)

## The spec's step one could not be built as written

It said: *a façade over what exists - it calls today's modules in today's order,
no behaviour change, and its test is that the journal is byte-identical.*

**That inverts the dependency.** Statespace imports nothing from its sibling
modules - only `shared` - and that is what makes the package standalone and
deletable, and what `CODEC_UNPERSISTED` depends on. A façade inside statespace
that called `levels` and `reactions` would break it, and the containment is now
asserted by a test that walks every module in the package looking for a
`from ..sibling import`, so it would also fail loudly rather than quietly.

So the direction is reversed. The façade exposes what statespace can answer
**from its own parts**, and a caller keeps calling its existing code for the
rest. That makes the migration incremental by construction: each question
statespace learns to answer moves from the caller's side of the boundary to
ours, and the caller's import list shrinks by one. The byte-identical journal
test does not apply, because nothing is being wrapped - what applies is that
every field published here has a measurement behind it.

## What it answers, and the measurement behind each

| field | from | measured |
| --- | --- | --- |
| `value`, `spread` | `pooling.Pooled(adapt=True)` | 5.6x on CRPS over the best single member, then 2.7x from `Adapting` |
| `quantiles` | empirical quantiles of its own standardised residuals | CRPS 0.9899 against a Gaussian's 1.0000, and PIT 1.5 where no Gaussian band is calibrated |
| `walls`, `barrier()`, `least_horizon()` | `bounding` | optional stopping fixes two of four quantities; measured per-family walls |
| `family`, `absorbs` | `behaving` | 19 classes, no misclassification |
| `paced`, `pace_factor` | `pacing` gated by `behaving.drives_q` | +0.0513 per observation on the production filter, 7 of 8, at exponent **1** |

Three decisions in that table are worth naming, because each is a place the
obvious choice is measurably wrong.

**`spread` is `p00 + R`, not the state's spread.** A filter's `sd` is the
uncertainty in the *state*; what a caller scores is an *observation*, whose
one-step variance adds the measurement noise.
`statespace-river-against-members.md` records what omitting it costs: every
member looks over-confident by exactly that term, which nearly handed a River
tree a 3.6x rout it had not earned. The façade publishes the predictive spread
so no caller has to know to add it.

**The exponent on activity is 1, not 2.** The price members prefer 2 and a
level-tracking filter prefers 1, measured on 7 of 8 instruments, losing at 2. A
caller tracking a level gets the exponent measured on a level.

**And the band is shape-free rather than Gaussian**, because no Gaussian band
here has ever been calibrated, and a *conditional* band - the obvious upgrade -
was measured and **lost**, scoring 1.0009 against the unconditional 0.9899 and
failing its control.

## What it does not answer

**Level discovery**, which is the one asked for by name. `drawing` is 3,554
lines of finding the prices that matter, and statespace models a price rather
than finding the prices worth modelling. The spec records why it is hard rather
than merely unwritten: a mixture whose centres are free states **collapses onto
the data** - `definitions-cannot-be-states` - so a statespace level finder has
to be anchored from outside the likelihood, estimating a level's strength and
width rather than its position.

**The volatility book** (`vol`, 4,965 lines) and **session context**
(`context`, 2,794 lines) are also outside. `pacing` absorbed the one piece of
context that was measured.

## The two rules, and how each is enforced

**A caller may not reach inside to recompute anything.** `Readout` is frozen,
so a consumer that disagrees with the thing that produced it cannot express the
disagreement by editing the result. The spec's concrete test for this is that
`engine.py:182` imports `levels.SECONDS` - a façade whose consumer still does
that is not a façade.

**And `Desk` owns the state.** A caller that holds a member per feed and
interval, and knows which to advance when, is still doing the orchestration.
`Desk` keeps them behind `read`, `forget` and `tracking`.

## What this unblocks

Steps two to five of the spec become library changes. Swapping the estimator,
moving the band in, wiring activity, replacing the barrier probabilities - each
happens behind `read` and none of them is visible to a caller. That was the
whole argument for doing the façade first, and it now holds.

The one thing it does not unblock is step six. Level discovery is not behind
this boundary because statespace cannot answer it yet, and no amount of façade
changes that.
