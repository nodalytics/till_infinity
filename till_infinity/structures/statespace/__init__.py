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
the set question is settled rather than after. Seven of the eleven need none of
the rewrite. Suggested order, cheapest decisive first:

| item | what it is | here |
| --- | --- | --- |
| **I6** | a rate is per unit time, and a bar is not a unit of time | `rates.py` |
| I5 | observability is the real argument about acceleration | - |
| I9 | two state spaces, and there already are two | - |
| I10 | the slope has a volatility, and it is currently a guess | - |
| I2 | the state is the memory of the system, and this one leaks | - |
| I8 | state, input or output - the question a feature list never asks | - |
| I1 | there is no input; `B` and `u` do not exist here | - |
| I7 | two barriers from one model instead of three | - |

I3, I4 and I11 are not in that order deliberately: I3 and I4 are conditional on
I5's answer, and I11 has already failed twice in the form that was tested - see
the spec, which names the two escapes it has left.

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

from .diagnostics import Residuals, fit_jerk, residuals
from .family import MISSING, PENDING, Filter, members
from .linear import Gaussian
from .paths import Path, hourly, simulate, with_gaps
from .rates import Slope, slope_per_bar, slope_per_hour
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
    "Filter",
    "Gaussian",
    "Path",
    "Residuals",
    "Robust",
    "Slope",
    "Smoothed",
    "Subject",
    "fit_jerk",
    "hourly",
    "members",
    "residuals",
    "simulate",
    "slope_per_bar",
    "slope_per_hour",
    "smooth",
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
