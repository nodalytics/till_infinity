# Levels in one state space: the thesis, implemented correctly

Price goes in; levels come out, each with a position, a drift, an existence
probability, and a prior borrowed from the levels most like it.

**This is not a new direction. It is the one already written down, and what
ships today is a partial implementation of it** - the estimation half built and
the formation half left as geometry. This document is the correction, not a
proposal competing with the current design.

Raised 2026-10-09: *"can the price not be an input to the kalman and the kalman
produces the levels"*, *"the stuffs from drawing folder should be in the state
space"*, *"we can even add the similarity thing to the state space too"*, and
*"that was the intention as first/origin thesis not what we are doing now"*.

**Status: design only.** Nothing here is built. What follows is the gap between
the thesis and the code, the formalism the thesis actually requires, and the
evidence - which argues against doing the work and is placed before the design
for that reason.

## Where the implementation departs from the thesis

[`idea.md`](../idea.md) is explicit about why the filter exists:

> That is why the origin is a Kalman state rather than a line. The filter is
> not decoration; it is what it means to hold an estimate of a quantity you
> cannot observe directly and keep updating it from noisy evidence.

And [`levels.md`](../levels.md) §3:

> Each of those turns is one **noisy observation** of where the level actually
> sits, so a level is a latent state with a mean and a variance.

Both sentences are about a level that **already exists**. Nothing in either
says where the level came from, and in the code it comes from somewhere else
entirely: fifteen modules in `structures/drawing/` - `pips`, `pivots`, `gaps`,
`displacement`, `equals`, `rounds`, `runs`, `sweeps`, `vwap`, `profile`,
`origins`, `origin_points`, `level_range`, `confluence` - that find prices
geometrically and hand the filter a seed.

So the current shape is **geometry, then inference**. A swing cluster decides a
level exists and where it starts; the filter then refines a decision already
made.

**That is the thesis applied to half the problem.** "An estimate of a quantity
you cannot observe directly, updated from noisy evidence" is exactly as true of
*whether a level is there* and *how many there are* as it is of where one sits.
The code treats the first two as known and only the third as inferred, and
nothing in the thesis licenses that division - it is an implementation
convenience that has been in place long enough to read as design.

Three things follow from the split, and each is a real cost:

* **Existence is binary.** `State.FRESH / TESTED / BROKEN / FLIPPED` is a label
  applied by rules. A level either is or is not, and "probably still there" has
  nowhere to live.
* **Association is hand-written.** `dedupe` and `merge` decide which
  observation belongs to which level by distance thresholds. That is the data
  association problem, solved by a constant.
* **Borrowing strength happens outside the model.** The kNN produces
  `neighbours` and `comparable`, and shrinkage pulls a level toward its pool
  with `K = 150` - chosen, then later estimated at **155.3** by
  DerSimonian-Laird. A number the model should infer is a number beside it.

## What the thesis actually requires, precisely

**State space is the thesis; the Kalman filter is one member of the family.**
The thesis is not underspecified here - it says a latent quantity, updated from
noisy evidence - but it does not say *which* filter, and the one in use cannot
express the question being asked of it.

A Kalman has fixed state dimension. "Produce the levels" means the
number of states is itself unknown and changing - levels are born, persist,
break, die - which is a different and well-studied member of the same family.

The formalism is **multi-target tracking over a random finite set**: a PHD or
CPHD filter, or equivalently a Dirichlet-process mixture if the same thing is
posed as nonparametric clustering with an unknown component count.

| today | in one state space |
| --- | --- |
| `pips` clusters swings into a level | measurement density over turning prices |
| `reform` creates a level | **birth process** |
| `State.BROKEN` | **death**, or existence probability decaying |
| `dedupe` / `merge` on a distance | **data association**, probabilistic |
| kNN `neighbours` + `K = 150` shrinkage | **hierarchical prior** over level parameters |
| touch / no touch | measurement vs **clutter** |

The output that does not exist today and would: **a probability that a level is
there at all**, propagating with the same arithmetic as its position and width.
Every consumer that currently reads `state == BROKEN` would read a number.

**And the output stays a level, point or zone.** Nothing here changes what
comes out - a mean that says where and a variance that says how wide, read as a
price when the band is tighter than the tick grid and as a zone when it is not.
The existence probability is a third number beside those two, not a different
kind of object.

## What is already measured, and it is not encouraging

This is the part that decides whether the work is worth doing, so it goes
before the design rather than after it.

**Four attempts to make the level filter richer have all returned null:**

| attempt | result | where |
| --- | --- | --- |
| per-level dispersion as a state | precisely measured and tiny - p90/p10 is 1.12x at 1h and 4h | [`level-dispersion.md`](../../research/docs/level-dispersion.md) |
| adaptive observation noise | worse on the median, needs a wider band for its coverage | [`level-filters.md`](../../research/docs/level-filters.md) |
| particle filter on the level | nothing a Gaussian was missing | [`level-filters.md`](../../research/docs/level-filters.md) |
| robust (Huberised) update | identical to the Kalman **to four decimal places** | [`level-filters.md`](../../research/docs/level-filters.md) |

The last line is the one to sit with. A robust update that never fires means
real touch residuals almost never exceed the filter's own spread: **there is no
heavy tail to model.** A PHD filter is a far larger hypothesis class aimed at
the same residuals.

**And similarity has already failed the directional question twice:**

| question | answer | where |
| --- | --- | --- |
| does similarity predict direction? | no - AUC 0.47-0.54 at two embeddings | [`conformal.md`](../../research/docs/conformal.md) |
| does distance order neighbours by agreement about direction? | no - **AUC 0.4921** against 0.5000 shuffled, flat at every horizon traded | [`similarity.md`](../../research/docs/similarity.md) |

**This does not kill part B, and the distinction matters.** Those studies asked
whether similar *windows* predict *direction*. Hierarchical pooling asks
whether similar *levels* behave alike - whether a level's hold rate, wick depth
and drift are drawn from a shared distribution. That is a different quantity on
a different population, and there is one positive datum for it: the shrinkage
constant estimated from the data came back at 155.3 against a hand-picked 150,
which says the pooling the desk already does is roughly correctly sized rather
than arbitrary.

## Phasing, cheapest decisive test first

### Phase 1 - similarity into the state space

Levels keep their own filter; the **prior** becomes hierarchical. Each level's
parameters are drawn from a pool distribution whose hyperparameters are
estimated, replacing the fixed `K`. Formation is untouched.

Contained, reuses the shrinkage work, and answers the separable question: does
sharing strength between levels improve anything measurable?

**The null:** a level's own history against its pool's, with pooling strength
estimated versus fixed at 150 versus zero. Scored on held-out touches, not on
fit. If estimated pooling does not beat `K = 150`, the hierarchy buys nothing
and phase 2's prior has no reason to be better.

### Phase 2 - formation into the state space, offline and in parallel

An RFS filter run **beside** production on the same bars, publishing nothing.
Levels from geometry and levels from the filter are both scored against what
price did, on the same touches, with the same conformal machinery.

**The null, named before the run:** the geometric levels themselves. Not a
random price, not a round number - the thing currently shipping. A state space
that cannot beat `pips` on its own data does not replace it however principled
it is. Secondary: does existence probability predict a break better than
`State`? That is the one output geometry cannot produce and is where the
advantage, if any, should show up first.

### Phase 3 - replace, only on phase 2's evidence

Behind a flag, one feed family at a time.

## What would have to be true for this to pay

Written down so the result is falsifiable rather than arguable:

1. **Touch residuals carry association ambiguity that distance thresholds get
   wrong.** If `dedupe`'s constant already assigns touches the way a
   probabilistic association would, the machinery is exact and pointless.
2. **Existence is genuinely graded.** If `BROKEN` is nearly always obvious in
   hindsight, a probability is decoration.
3. **Levels of a kind behave alike.** If hold rate and wick depth do not pool,
   the hierarchy is a slower way to compute per-level estimates.
4. **Geometry is leaving levels on the table** - prices that mattered and no
   pass drew. `drawing/` encodes measured domain knowledge: displacement body
   thresholds, five imbalance kinds, the rollover trim. A density model must
   rediscover all of it from turning prices alone, which is weaker evidence
   than the swing structure the passes read directly.

(1) through (3) are measurable before anything is built. (4) is the risk, and
it is the one that would make a principled model worse than the hand-written
one it replaces.

## The uncomfortable reading

The thesis also says this, in `idea.md`:

> most of what is built here will earn nothing, and that has to be discoverable
> rather than argued about

Applied here it cuts both ways. The split between formation and estimation is a
departure from the stated design and should be recorded as one. It does not
follow that closing it will earn anything - the evidence above says the filter
has no unexploited room in it, and "the thesis says so" is not a measurement.
Both things are true at once, and the phasing below exists so the second can be
tested before the first is acted on at scale.

## Cost, stated plainly

Phase 1 is a contained change to the prior. Phase 2 is a parallel implementation
of the core of this desk, and phase 3 is replacing fifteen modules that encode
years of measurement. This is a quarter of work, against a component that was
dark for **172 minutes today** for unrelated reasons.

The sequencing recommendation is therefore: phase 1 now, phase 2 only if phase 1
pays, and in both cases the null is the system currently shipping.

## Out of scope

* Changing what a level *means*. The thesis - fair value from where volatility
  turned - is unchanged; this is about how the estimate is formed.
* Trading behaviour. Nothing here may change a gate until phase 3.
* The warm. Shortening the restart is urgent and unrelated; it does not wait
  for this.

## Open questions

* Does the RFS filter run inside the 2-core, 2.6 GiB budget, or does it assume
  the Redis split first?
* Does existence probability have a consumer? Every reader of `State` is a
  branch today, and a probability needs a threshold somewhere or it is a number
  nobody acts on - which is [`inert.md`](../../research/docs/inert.md)'s
  failure mode.
* Phase 1 and phase 2 share a hierarchy. Is the pool defined by the drawing
  pass that made the level - and if formation moves into the filter, what
  defines it then?

## Five improvements the control-theory form points at

Read against the standard state-space form - MIT 16.30 Topic #5, which states
it as `ẋ = Ax + Bu`, `y = Cx + Du` - five specific improvements fall out, and
they are more actionable than "use a bigger filter". **Four improve the model
already shipping and need none of the rewrite above**, which makes them the
better place to start.

| | improvement | cost |
| --- | --- | --- |
| **I1** | give the model an **input** `Bu` - regime and volatility act on levels and are applied as side effects | small |
| **I2** | move **leaked state** into the state vector, one quantity at a time | small, separable |
| **I3** | a **mean-reverting slope** instead of a horizon cap on an unstable mode | research first |
| **I4** | an **`A` that depends on regime** - linear time-varying, which the general form already allows | medium |
| **I5** | compute the **observability Gramian** for the third state and set `ACCEL_SIGMAS` from it | small, do first |
| **I6** | every rate **per unit time, not per bar** - the filter complies, the published regression slope does not | small |

### I1. There is no input. `B` and `u` do not exist here

The level model is `ẋ = Ax + w`: dynamics plus process noise, and nothing else.
A state-space model has an **input** term, and things plainly act on a level
from outside it.

**`Engine.regime_changed` is already that input, implemented as a side effect.**
When the drift detector fires, every level on the instrument has its evidence
discounted by a severity. That is an exogenous impulse applied to the state - a
`Bu` - written as a method that reaches in and multiplies things. Volatility is
the same story from the other side: it enters as a scale on the process noise
rather than as an input, so a market that has doubled in volatility is modelled
as a level we are *less sure of* rather than one that is *being moved*.

The cheap version of this is not a rewrite. It is writing down what `u` is -
regime severity, volatility change, session boundary, policy surprise - and
making the impulse part of the state equation, so its effect on the covariance
is derived rather than applied.

### I2. The state is the memory of the system, and this one leaks

The lecture's definition is the useful one:

> Future output depends on past input only through current state. State
> summarises effect of past inputs on future output - like the memory of the
> system.

By that definition a `Level`'s state is not `(price, slope, accel)`. It is also
every `SideStats` counter, the wick EWMA and its sums, `zone_sigmas_up` and
`zone_sigmas_down`, `last_touch`, `broke_at`, `waiting` and the `State` enum.
All of them are memory, all are updated by observations, all change future
output - and **none are in the state vector**.

What that costs is concrete: the parts inside get gains derived from
uncertainty, and the parts outside get hand-chosen constants. `wick_vol` used a
fixed `0.8/0.2` until this was noticed; the side counters decay on a half-life;
the conformal sigmas settle on a count. Each is a filter with its rate picked
rather than derived, which is exactly what `levels.md` §3 says the Kalman exists
to avoid.

**This is the most actionable gap in the list**, because it is separable: any
one of those quantities can be moved into a filtered state on its own and
measured, the way the sweep edge just was.

### I3. The dynamics are marginally stable, and the horizon cap is the patch

With `F = [[1, carry], [0, 1]]` both eigenvalues are at 1 - a double
integrator. The lecture's stability test is `Re λ(A) ≤ 0` **with every
eigenvalue on the boundary having a Jordan block of order one**, and a repeated
eigenvalue at 1 does not satisfy it. The position variance grows without bound
under extrapolation, which is not a bug but is worth naming as what it is.

`SLOPE_HORIZON_HOURS = 24` exists because of this: past a day the level is
forced horizontal and only its uncertainty grows. That is a cap on an unstable
mode, chosen by judgement. Adding acceleration makes it a triple integrator and
`ACCEL_HORIZON_HOURS = 6` is the same patch one order up.

Naming it does not fix it, but it does say what a fix would look like: a
mean-reverting slope - `F[1][1] < 1` - is stable, has a stationary variance,
and needs no horizon constant at all. Whether a level's drift actually reverts
is measurable.

### I4. `A` should change with the operating point, and this one never does

The lecture linearises about an equilibrium and is explicit that the result is
local: the aircraft example derives a different `A` for each flight condition,
and the nonlinear-spring example gives `A₀` and `A₁` at two equilibria of the
same system.

This desk uses one `A` for every instrument, every timeframe and every regime -
and it *has* a regime classifier whose output is already published as a
feature. The analogue of "trim condition" is sitting there unused by the
dynamics. An `A` that depends on regime is a linear time-varying model, which
the lecture's general form already covers (`A(t)`, `B(t)`), and it is a smaller
step than the random-finite-set rewrite above.

### I5. Observability is the real argument about acceleration

Only price is measured: `C = [1, 0, 0]`. Slope and acceleration are never
observed, only inferred. For a constant-acceleration model with position-only
measurement the pair `(A, C)` is observable **in principle** - but observability
is a matter of degree, and the observability Gramian over irregular, sparse
touches is badly conditioned for the third state.

That is a better justification for `ACCEL_SIGMAS = 4.0` than the judgement
currently written beside it, and it is computable: the Gramian over a level's
actual touch times says how much evidence the data can carry about the third
state at all. **If it says "almost none", the gate is not conservative, it is a
polite way of switching the state off** - and that is worth knowing before the
feature is trusted.

### I6. A rate is per unit time, and a bar is not a unit of time

The state-space form is written in `t`. `ẋ` is a derivative with respect to
time, and every coefficient in `A` carries units of inverse time - which is
why the lecture's `A(t)` is a function of `t` and not of sample number.

**The level filter already honours this.** `slope` is price units per *hour*,
`predict` works in `elapsed_hours`, and `var_slope` grows with elapsed hours -
so a level untouched across a weekend and one untouched for an hour are handled
by the same arithmetic rather than by the same number of missing bars.

**The regression slope published beside it does not.** `Engine._slope`
regresses close against the bar **index**:

```
rise = sum((i - middle) * x for i, x in enumerate(window))
# Price per bar -> basis points per bar -> volatility units per bar.
```

So does `zma`'s. Both treat the sample number as the independent variable,
which is only equivalent to time when bars arrive uniformly - and on this desk
they do not:

* sessions close, so an index step can be a minute or three days;
* venues drop out, and the collector logs `wrote 12 bars and announced 8` often
  enough that the gap is routine rather than exotic;
* the synthetics run continuously and the real instruments do not, so a
  per-bar rate is not comparable between them even at the same interval.

A per-bar rate silently changes meaning across every one of those. The fix is
mechanical - regress against the bar's timestamp rather than its position, and
publish the result per hour - and it makes the two slopes in the feature set
the same kind of quantity, which they currently are not.

**It also matters for anything that reads both.** `slope` and `level_slope_vol`
sit in the same decision context; one is per bar and one is per hour, and
nothing in the names says so.

### Where these sit against the phases above

Nothing in I1-I5 argues for the random-finite-set rewrite. I1, I2 and I4
improve the model already here; I5 is a test of something that shipped on
2026-10-09. They are individually measurable, which the rewrite is not, and
none of them needs agreement about formation first.

**Suggested order, ahead of phase 1:** I6, then I5, then I2, then I1. I6 goes
first because it is mechanical, it is wrong today rather than merely absent,
and it makes two published features comparable that currently are not. I3 is a research
question - does a level's drift revert - and belongs with the turning-point
study in [`ideas.md`](../../research/docs/ideas.md). I4 is the largest and
should wait for I1, because a regime-dependent `A` and a regime input are two
answers to the same observation and only one is needed.
