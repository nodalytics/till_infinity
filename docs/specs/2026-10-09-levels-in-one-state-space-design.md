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

**It is not a Kalman filter**, and this is the one place the origin thesis is
genuinely underspecified rather than merely unimplemented. A Kalman has fixed state dimension. "Produce the
levels" means the number of states is unknown and changes - levels are born,
persist, break, die - and that is a different and well-studied problem.

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
