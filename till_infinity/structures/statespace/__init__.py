"""The thesis, implemented as a state space - built beside production, not inside it.

`docs/specs/2026-10-09-levels-in-one-state-space-design.md` is the design. This
package is where it gets written, and it exists as a package rather than as edits
to `levels.py` and `engine.py` for one reason: **the spec's own phasing requires
the new thing to run beside the old one and lose on its own merits before
anything is replaced.** A rewrite spread through the files it is replacing cannot
be scored against them, and cannot be abandoned cheaply if it loses.

## The rule here

**Nothing in this package publishes.** Not a card line, not a journal field, not
a gate. Every module is reachable only from tests and from research harnesses
until a named null has been beaten on held-out data. When something does earn its
way out, it leaves by being called from `engine.py` behind a flag, one feed
family at a time - Phase 3 - and this docstring records the measurement that let
it.

That is not caution for its own sake. `research/docs/pca-residuals.md` returned a
net Sharpe of **-0.97** against an OU control of **+10.47**, and
`research/docs/peering.md` found the synthetic control showing a *larger* effect
than the real assets. The machinery in both cases worked; the hypothesis did not.
A state-space rewrite is a bigger version of the same bet, so it gets the same
discipline.

## Can a state space model a complex adaptive system?

Asked on 2026-10-10 - "the market is a complex adaptive system, it is
non-deterministic in nature; can our statespace algos model it?" - and the
question is sharp enough to answer in parts rather than agree with. These are
the guiding principles for this package, and three of them are already measured
rather than asserted.

**1. Non-determinism is the premise, not the obstacle.** A state space model is
not a deterministic machine with noise bolted on: the state *is* a random
process and the reading *is* a noisy view of it. `jerk` is the rate at which the
truth wanders unpredictably and `R` is how badly a reading sees it. A model that
asserted determinism would be an ODE with no `q` - which is exactly what this
package is not. So "the market is non-deterministic" is an argument for this
machinery and not against it.

**2. Adaptivity is the real challenge, and it is a different one.** A fixed
parameter filter assumes the dynamics it was fitted to still hold. That
assumption is what fails in an adaptive system, and the family is organised
around the specific ways to drop it:

| what adaptivity means | which member answers it |
| --- | --- |
| the regime switches | `hmm` - a discrete state, held out |
| nobody knows how many regimes | `dpm` - unbounded mixture |
| the dynamics depend on the input | `selective` - `B`, `C`, `delta` from it |
| the parameters themselves drift | `I11` - EM or N4SID, refitted |
| the shocks are not Gaussian | `robust`, and **measured**: these fail Jarque-Bera |
| the memory outlasts one decay | `D1` HiPPO, `D4` oscillatory |

**3. The model is of an observable, never of "the market".** This is the
principle that does the most work. Nothing here claims to model a complex
adaptive system; each member claims that *one named quantity* has a
low-dimensional state plus noise, and is scored on that quantity alone. A
**level** is a far better candidate than a price, and for a reason that is about
the market being adaptive rather than in spite of it: a level is a price many
participants have coordinated on, so it is the one thing in an adaptive system
that should be *more* persistent and lower-dimensional than the flow around it.
That is the thesis, and it is why `subjects.py` makes the quantity explicit
before any filter touches it.

**4. These models are known to be misspecified, and the diagnostics are how we
know.** `diagnostics.py` exists to fail: autocorrelated residuals mean the state
equation is wrong, non-normal residuals mean the noise model is. Both have
already fired on real series - the autocorrelation survives and the non-normality
gets worse - and that is recorded rather than tuned away. The honest position is
not "this captures the system". It is **"this beat a named null on held-out data
while still being wrong"**, which is a much smaller claim and the only one the
evidence supports.

**5. What no member here can do**, stated so nobody has to discover it twice:

* **Emergence.** The state is a low-dimensional summary; the interacting agents
  that produce the behaviour are not in it, and cannot be recovered from it.
  Everything they do arrives as `q`.
* **Reflexivity.** Every member assumes the reading is a passive observation. Our
  own orders move the book, and no member represents that.
* **A system with no stable low-dimensional state.** If there is nothing to
  track, no choice of member helps - and this is measurable, not philosophical.
  I5 asked it directly and the answer was bracing: a third state is perfectly
  estimable from price alone and still **loses** 0.138 nats a point, and the fit
  handed a second drift component set its noise to zero rather than use it.
  Given more state, the data declined it.
* **Parameters drifting faster than they can be estimated.** The failure mode
  with no remedy: by the time a window is long enough to fit, the thing has
  changed. The check is parameter stability across refits, and it is not written.

So: **yes for a level, no for the market, and the difference is the whole
design.** The package's job is to find which observables have a state worth
tracking, and the rule below - nothing publishes until it beats a named null -
is what stops that search from becoming a story.

## Every horizon is expressed in time, never in bars

A standing rule for this package, and it is not a style preference - it is the
difference between a parameter that means something and one that means something
different on every series it meets.

**"200 bars" is not a horizon. It is a horizon times a timeframe**: ten hours at
3m and eight months at 1d. A window, a lag, a hazard or a half-life stated in
bars therefore encodes a belief that changes silently when the same code is
pointed at another series - and comparing across timeframes, which this package
does constantly, then compares definitions rather than behaviour.

So horizons here run **from seconds to weeks, in hours**, and the bar count is
derived per series:

* `inputs.Window(hours=...)` and `inputs.LADDER`, which spans `10s` to `4w`.
  `inputs.resolvable` picks the rungs a given series can compute - a 3m series
  resolves `5m` to `3d` and a 1d series resolves `3d` to `4w`, from one ladder
  and with neither a special case.
* **Seconds to weeks, on one ladder, and the range is tested.** `inputs.LADDER`
  runs `10s` to `4w` and a feed fine and long enough resolves all fourteen
  rungs. Which slice a given feed gets is decided by two rules rather than by a
  per-instrument list: at least two bars, or the "window" is one bar's own high
  and low under a name claiming a horizon; and at most a quarter of the series,
  or there are too few independent observations of it. So a 1s feed answers
  seconds to the hour, a 1d feed answers days to the month, and neither is a
  special case. A feed cannot be asked about a horizon it has not observed.
* **A count is right only when the question is about the sequence.** The audit
  on 2026-10-11 found four bar counts in this package and kept two. `LAGS` in
  the Ljung-Box test and `WARMUP` in `paired` are counts because they are about
  the innovation *sequence* and the hull's point count - neither is a horizon.
  `changepoint`'s freshness window and its truncation were horizons wearing
  counts: "the run is at most two readings old" is half an hour at 15m and two
  days at 1d, and a cap of 300 components was justified as the point where the
  geometric tail is negligible, which is true at 1d (300 days against a ten-day
  regime) and false at 15m (three days), so the posterior sat against the cap
  permanently while `run_hours` looked like an estimate rather than a bound.
  Both are durations now, the cap carries `LIVES` expected regimes of time
  within a compute ceiling, and `Changepoint.saturated` publishes when the
  truncation is binding instead of leaving it to be assumed away.
* **`hours` means calendar time everywhere, and `coverage` does the
  conversion.** Both halves of that were wrong somewhere until 2026-10-11:
  `resolvable` counted calendar bars and so admitted rungs a part-time market
  could not build, and `smoothing.lagged` divided by the median spacing alone,
  which reads `hours` as *trading* time - so `lagged(hours=2)` and the `2h` rung
  were different lags on anything that closes. Two meanings of one word is the
  shape to watch for here, not a missing conversion.
* `inputs.coverage`, because a week is seven **calendar** days and how much of
  it a market trades is inferred from its own clock: FX comes back at 0.711
  against 5/7, and the Deriv synthetics at exactly 1.000. A hardcoded five-day
  week shortened every crypto window by two sevenths.
* `changepoint.hazard`, per **hour**. It was per observation at `1/250`, which
  asserts "a change every 12.5 hours" at 3m and "every 250 days" at 1d - the
  same member believing wildly different things about the world depending on
  what it was handed.
* `smoothing.lagged(hours=...)`, `paired.Paired.hours_since_reset`,
  `changepoint.run_hours`, and every rate in `rates.py`.

**Two exceptions, and they are not horizons.** `MAX_RUN` truncates a posterior
and `swarm.COUNT` is a particle count: both are resolutions rather than spans,
and neither says anything about how long something lasts. `changepoint.
run_length` is kept in observations because it is the quantity the recursion is
literally over, and it is documented as not comparable across timeframes with
`run_hours` beside it for anything that crosses one.

This rule is also why irregular sampling is handled rather than assumed away.
Touches arrive when they arrive; a hazard per hour converts to a per-observation
probability from the gap that actually elapsed, and a window in hours spans the
bars that actually fall inside it.

### Why the definition of time is the thing, and not a detail

Everything above is one claim: **how time is defined decides what a measurement
means**, so it is part of the model rather than part of the plumbing. Three
definitions are available and this package uses the first:

* **clock time** - hours, what is used here. Portable across timeframes and
  across instruments, and the only one in which "this level has held for two
  days" is the same sentence on every series.
* **event time** - one unit per observation, which is what a bar count is. Not
  portable: the same number is a different horizon on every series, which is
  the defect this rule exists to prevent.
* **volume or tick time** - one unit per unit traded. The subordination idea,
  and what VPIN's volume buckets are. `D2` proposes it as
  `delta = dt * activity`, and it is not used because a CFD volume is a tick
  count rather than traded size.

**And portability of the window is necessary, not sufficient.** Muhle-Karbe,
Ouazzani Chahdi, Rosenbaum and Szymanski (2026) hit the same problem from the
other side: Hurst exponent estimates for order flow are "strongly scale
dependent... close to 0.5 at high frequencies and increase steadily as the
sampling frequency decreases", and their fix is an *estimator* that accounts for
both components, under which estimates become "remarkably stable across
aggregation scales".

So there are two halves to this and only one is done. A window stated in hours
means the same thing on every series; an **estimator** computed over it may
still answer differently at 15m than at 1d for reasons that have nothing to do
with the market. Every cross-timeframe table in `research/docs/statespace-*.md`
carries that caveat, including the ones whose spans are correctly in hours.

## The models live here too

Not only the improvements. The spec lists the family - Kalman, particle, HMM,
random finite set, Dirichlet-process mixture - and says **which one fits is a
question asked per state**, not once for the package. So the filters themselves
are written here, one module each, against one interface, and the question
"which member of the family does this state need" becomes a measurement between
two modules rather than an argument about a rewrite.

| module | what it is | status |
| --- | --- | --- |
| `rates.py` | a rate per unit time, which every `A` coefficient needs (I6) | written |
| `family.py` | the interface, and which member has beaten which, where | written |
| `linear.py` | the Kalman member: linear-Gaussian, continuous time | written |
| `reverting.py` | a rate that pulls back instead of running away (I3) | **beats `linear`** |
| `robust.py` | the Kalman with a Huber-gated gain - the cheap arm for fat tails | written |
| `subjects.py` | what the state means for a level, an instrument, a relationship | written |
| `diagnostics.py` | fit the parameters by likelihood; test whether the model is right | written |
| `paths.py` | generate a path from the model, so a parameter can be recovered | written |
| `smoothing.py` | where the state really was, given everything that happened next | written |
| `rfs.py` | the set layer: birth, death, association, existence probability | not yet |
| `factor.py` | the family an instrument is measured against (I11) | not yet |

**And the family is the point, not the Kalman.** State space is the thesis; the
Kalman is one member. The spec says which member fits is asked **per state**, and
production already has two opposite answers to that question: a particle filter
was *machinery for nothing* on levels - it tied the linearised arm, so the
non-Gaussianity was not worth paying for - and **won on all four series** for
volatility. `family.py` carries that table, the interface every member
implements, and the null each unwritten member will have to beat. A member
arrives with its cheap arm or it cannot be scored.

**And three subjects, not one.** `linear.py` does not know what it is tracking;
`subjects.py` says what the three numbers mean, and the thesis's claim is that
the answer is the same model each time:

| | the state | a measurement | the band |
| --- | --- | --- | --- |
| level | where the level is | a touch price | the zone |
| instrument | a name against its kind | its deviation from its family | how far is normal |
| relationship | the fair spread of a set | the realised spread | the deviation's spread |

Statistical arbitrage is the third row, not a second system: level becomes
relationship, distance becomes deviation, zone becomes deviation dispersion, and
the slope becomes a drifting hedge ratio - which is the part a static
cointegrating vector cannot express. **N assets, not two**, because the N-k
residual directions *are* the cointegrating space.

If the three turn out to need genuinely different filters, that is a result and
`subjects.py` is where it shows up. Declaring all three now is what stops the
shared filter being quietly specialised to levels before the others arrive, which
is how a general model ends up with a level-shaped hole in it.

`levels.Kalman` stays exactly where it is and keeps running the desk. `linear.py`
is not its replacement until it has beaten it; it is the same model written the
way the spec says it should be - **one `jerk` parameter with units instead of
three separately chosen variances** - so that the difference between the two is
something that can be measured on the same touches.

## What is actually changing, and what is not

The spec is explicit, and it is the opposite of what "rewrite the level filter"
sounds like:

| layer | what it holds | changes? |
| --- | --- | --- |
| per level | `(price, slope, accel)`, its covariance, its zone | **no** |
| the set | how many levels, which measurement is whose, whether each exists | **this is new** |

A random-finite-set filter does not replace a target's state vector. It carries a
*set* of targets, each one a state vector with its own dynamics, and adds a layer
above them. So `levels.Kalman` survives, with the same `F`, the same gains and
the same `trending` / `turning` / `crossed` readings on top. The one addition at
the level itself is **existence probability**, beside the mean and the variance:
three numbers where there are two, not a different kind of object.

What the set layer replaces is geometry:

| today | in one state space |
| --- | --- |
| `pips` clusters swings into a level | measurement density over turning prices |
| `reform` creates a level | birth process |
| `State.BROKEN` | death, or existence probability decaying |
| `dedupe` / `merge` on a distance | data association, probabilistic |
| kNN `neighbours` + `K = 150` shrinkage | hierarchical prior over level parameters |
| touch / no touch | measurement vs clutter |

## Phases, cheapest decisive test first

**Phase 1 - the prior.** Levels keep their own filter; the shrinkage prior
becomes hierarchical, with pooling strength estimated rather than fixed at
`K = 150`. The null is the fixed `K`, scored on held-out touches. If estimated
pooling does not beat it, Phase 2's prior has no reason to be better either.

**Phase 2 - formation, in parallel.** An RFS filter over the same bars,
publishing nothing, scored against **the geometric levels themselves** - not a
random price, not a round number, the thing currently shipping. Secondary and
more interesting: does existence probability predict a break better than `State`?
That is the one output geometry cannot produce, so it is where an advantage
should appear first.

**Phase 3 - replace.** Only on Phase 2's evidence, behind a flag, one feed family
at a time.

## The improvements, which do not wait for any of that

I1-I11 in the spec apply to the **per-level** row, so they are worth doing before
the set question is settled rather than after.

**This table rotted and has been corrected.** Every row below except `I7` was
marked `-` while a module in this package already claimed it - the same failure
as `MISSING["em"]` and the fixed-lag smoother, both of which were listed as
absent while written. A plan whose status column is wrong is worse than no
plan, because the wrong rows are exactly the ones nobody re-reads.
`tests/test_statespace.py` now asserts this column **both ways**: a named module
must exist and mention the item, and a `-` must have no module claiming it.

| item | what it is | here |
| --- | --- | --- |
| **I6** | a rate is per unit time, and a bar is not a unit of time | `rates.py` |
| I5 | observability is the real argument about acceleration | `reverting.py` |
| I9 | two state spaces, and there already are two | `switching.py` |
| I10 | the slope has a volatility, and it is currently a guess | `linear.py` |
| I2 | the state is the memory of the system, and this one leaks | `linear.py` |
| I8 | state, input or output - the question a feature list never asks | `driven.py` |
| I1 | there is no input; `B` and `u` do not exist here | `inputs.py` |
| I3 | a rate that pulls back instead of running away | `reverting.py` |
| I11 | what a subject is, and which ones have provenance | `subjects.py` |
| **I7** | **two barriers from one model instead of three** | `bounding.py` |

**`I7` is now `bounding.py`, and the answer is stronger than the item asked
for.** The desk sets a target, a stop and a time limit as three independent
numbers; `I7` asked for two of them to fall out of one model. In shifted units
`u = up + B` and `d = down + B` the first-passage laws collapse to `P = d/(u+d)`
and `T = u*d`, so **all four of target, stop, win probability and expected
duration are one surface with two degrees of freedom.** Three numbers is not
under-modelled, it is over-specified: the third is redundant or contradictory,
and `bounding.slack` reports which.

It also expresses a constraint three independent numbers cannot. Barriers
cannot sit at negative distance, so `T >= B**2 * max((1-P)/P, P/(1-P))` - a
desired win rate and a desired holding time are **not always jointly
reachable**, and `bounding.feasible` is the check.

The barrier work since - `barriers.conditional_slowdown` and
`research/docs/statespace-triple-barrier.md` - supplied the pieces: the label is
invariant to volatility, the duration is not, and the duration's conditional
correction is derived rather than fitted. That is why `slower` is a caller's
argument in `bounding` and scales only the duration.

**The shift is two numbers, not one.** `P` and `T` follow from optional stopping
and Wald's identity, which need only a mean-zero martingale and a finite
variance - so skew does not touch them. What skew touches is the **overshoot**,
and `SHIFT` is an overshoot correction: a feed that spikes one way overshoots
that barrier badly and the other barely at all. Optional stopping then applies
to the stopped value *including* the overshoot, so the same `P = d/(u+d)` holds
with a different wall on each side, and `bounding.SHIFTS` carries the measured
pairs for `Boom`, `Crash`, `DEX_UP` and `DEX_DOWN`. A Boom index on a symmetric
geometry wins 0.4861 rather than half.

The `Volatility_*` and step families measured symmetric and keep the single
constant, which is recorded so it is not re-derived. The step families are a
genuine price lattice - 149 distinct bar-return magnitudes against 14,000 for a
diffusion - but the grid is **0.0166 of one bar's standard deviation**, so
aligning a barrier to it removes at most 2.8% of the correction.

I4 is still conditional on I5's answer, and I11's own escapes are named in the
spec - it is listed here because `subjects.py` carries the provenance half of
it, not because the whole item is settled.

## What was borrowed, and from where

Two established treatments, taken deliberately rather than reinvented:

**`control.StateSpace`'s timebase** is the clearest statement of I6 available.
It carries `dt` as part of the system: `dt = 0` is continuous time, `dt > 0` is
discrete at that sampling period, and **`dt = True` is discrete with no declared
period**. That third case is exactly what `Engine._slope` and `zma` are - a
discrete system whose sample time is unstated - and having a name for it is worth
more than the argument. `linear.py` is `dt = 0`: continuous, with the
discretisation done at each step from real elapsed time. The library also
discretises by zero-order hold, which is what `tests/test_statespace.py` checks
the hand-written `F` against.

**Statsmodels' state-space machinery** (Chad Fulton's `MLEModel`) supplies the
thing this package was most obviously missing: *the likelihood comes as a
byproduct of the Kalman filter*, so **every parameter is fittable rather than
chosen**. `Gaussian.loglike` accumulates it and `diagnostics.fit_jerk` maximises
it. Two more things came with it - an approximate diffuse initialisation needs a
**burn-in** on the likelihood, because a prior nobody chose should not be allowed
to dominate a fit (`Gaussian.burn`); and the standardised innovations are the
model's own specification test, which is where Ljung-Box and Jarque-Bera in
`diagnostics.py` come from.

Neither library is a dependency. `scipy` is present here only transitively
through `river` and `yfinance` and is not declared, so production code may not
import it; the arithmetic is short either way, and the tests check it against
`scipy` where `scipy` happens to be installed.

**The two notations, because the literature is split.** The spec is written in
control form and the statistics work is written in Durbin-Koopman form. They are
the same model:

| here | control | Durbin-Koopman |
| --- | --- | --- |
| the state | `x` | `alpha` |
| dynamics | `A` | `T` |
| observation | `C` | `Z` |
| process noise | - | `Q`, through `R` |
| measurement noise | - | `H` |

`B` and `u` have no counterpart on purpose: there is no input here, which is I1.

## Migrating out of here

A module leaves when it has beaten its null. Until then the import direction is
one-way: **this package may read `structures`, and `structures` may not read
this.** That is what keeps the whole thing deletable, and `tests/test_statespace.py`
asserts it rather than trusting it.
"""

from __future__ import annotations

from .adapting import Adapting
from .bounding import binding, feasible, least_horizon, slack, solve
from .diagnostics import Residuals, fit_jerk, residuals
from .facade import Desk, Readout
from .family import MISSING, PENDING, Filter, members
from .landau import Landau
from .linear import Gaussian
from .paths import Path, hourly, simulate, with_gaps
from .rates import Slope, slope_per_bar, slope_per_hour
from .reverting import Reverting
from .robust import Robust
from .smoothing import Smoothed, smooth
from .subjects import INSTRUMENT, LEVEL, RELATION, SUBJECTS, Subject

__all__ = [
    "INSTRUMENT",
    "LEVEL",
    "MISSING",
    "PENDING",
    "RELATION",
    "SUBJECTS",
    "Adapting",
    "Desk",
    "Filter",
    "Gaussian",
    "Landau",
    "Path",
    "Readout",
    "Residuals",
    "Reverting",
    "Robust",
    "Slope",
    "Smoothed",
    "Subject",
    "binding",
    "feasible",
    "fit_jerk",
    "hourly",
    "least_horizon",
    "members",
    "residuals",
    "simulate",
    "slack",
    "slope_per_bar",
    "slope_per_hour",
    "smooth",
    "solve",
    "with_gaps",
]

#: **This package is not persisted, and says so where the walk can see it.**
#:
#: `shared.codec.registry()` builds the state file's schema by walking every
#: module under `structures` and collecting every dataclass it finds - by
#: discovery, not by import. So this package landed in production's persistence
#: fingerprint the moment it existed, and adding a field here would have been a
#: schema change on a 128MB state file that none of it is in.
#:
#: `tests/test_structures.py` caught it by requiring every slotted dataclass
#: under `structures` to subclass `Restorable`. Satisfying that would have
#: declared these classes persistable, which is false: nothing here is saved,
#: and the whole point of the package is to be deletable.
#:
#: See `shared.codec.UNPERSISTED`.
CODEC_UNPERSISTED = True
