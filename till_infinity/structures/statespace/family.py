"""The family of state-space filters, and which member has beaten which, where.

**State space is the thesis; the Kalman filter is one member of the family.** The
spec is explicit that the thesis says "a latent quantity, updated from noisy
evidence" and does *not* say which filter - and that the answer is asked **per
state**, not once for the package. So the members live here as modules against
one interface, and "which filter does this state need" becomes a measurement
between two imports rather than an argument about a rewrite.

## The members, and what is already known about each

Status is about this package. The verdict column is production evidence that
already exists, and it is the reason this table is worth more than the list of
names in the spec:

| member | module | status | measured verdict |
| --- | --- | --- | --- |
| white jerk | `linear.py` | written | the incumbent's shape; **beaten** |
| reverting rate | `reverting.py` | written | **wins held out, 0.96 nats/point** |
| generalised Gaussian | `robust.py` | written | the next step; its case is now stronger |
| particle | - | not yet | **levels: machinery for nothing. volatility: wins** |
| HMM | - | not yet | untested as a level filter |
| random finite set | - | not yet | the set layer, Phase 2 - untested |
| Dirichlet-process mixture | - | not yet | the same thing posed as clustering |

The first two names are `dynamax`'s taxonomy rather than mine, and the second one
is a correction worth taking: **`robust.py` is a generalised Gaussian SSM** - a
linear-Gaussian state with a *non-Gaussian emission model* - and not a different
filter. Saying so places it exactly: it is a claim about the measurement, not
about the dynamics, which is why `diagnostics.jarque_bera` on the innovations is
the test of whether it can earn anything and `ljung_box` is not.

**The particle row is the one to read.** `research/docs/level-filters.md` settled
it for levels by running a linearised Kalman arm beside the particle filter: if
the particles only tie the linear arm, the non-Gaussianity is not worth paying
for - and for levels they tied, so the particles were machinery for nothing. The
same test on volatility came out the other way: `research/docs/vol-particle.md`
found `particle` beating the linearised `kalman` arm on all four series, and the
shipped EWMA over-confident by 18-29% at 1h with `z` standard deviations of
1.199 to 1.291 against an honest 1.0.

One filter family, two states, two opposite answers. That is the whole argument
for asking per state, and it is measured rather than asserted.

## A model is three distributions, and that is what decides the member

`nchopin/particles` factors a state-space model into exactly three things, and it
is a better decomposition than a list of matrices:

* **`PX0()`** - where the state starts.
* **`PX(t, x_prev)`** - how it moves.
* **`PY(t, x_prev, x)`** - how it is observed.

**This turns "which member fits this state" from a judgement into a question
about which of the three is wrong**, which is answerable:

| member | `PX0` | `PX` | `PY` |
| --- | --- | --- | --- |
| white jerk (`linear.py`) | Gaussian | linear, **marginally stable** | Gaussian |
| reverting rate (`reverting.py`) | Gaussian | linear, **stable** | Gaussian |
| generalised Gaussian (`robust.py`) | Gaussian | linear | **heavy-tailed** |
| nonlinear Gaussian | Gaussian | **nonlinear** | Gaussian |
| HMM | **discrete** | **discrete** | anything |

The first two rows are the decomposition earning its keep. `reverting.py`
changes `PX` and nothing else - same state dimension question aside, same `PY`,
same `PX0` - so the thing it can fix is autocorrelation in the innovations and
the thing it cannot is their shape. **Both halves of that prediction held**: on
eurusd 4h it took Ljung-Box from 5.96e-27 to 1.22e-04 and left Jarque-Bera
*worse*, 9.18e-89 to 8.83e-183.

That second number is the useful one. The tails did not get worse; they stopped
being hidden. A marginally stable rate absorbs a large move by running away with
it, so the move never appears as an outlier - fix the dynamics and it does.
**Which inverts the order:** `robust.py` is a `PY` change and was the smaller
error while `PX` was wrong, and is the dominant remaining one now that `PX` is
not.

So `robust.py` changes `PY` alone - it is a claim about the measurement and not
about the dynamics, which is why `diagnostics.jarque_bera` on the innovations
tests it and `ljung_box` does not. And I4 is a question about `PX`: an `A` that
varies with something exogenous keeps `PX` linear and belongs in `linear.py`,
while an `A` that varies with the state makes `PX` nonlinear and is a different
member.

The set layer is outside this factoring entirely, and that is the cleanest
statement of why it is a separate phase: a random finite set makes **the number
of states** random, which none of `PX0`, `PX` or `PY` can express.

## The rule for adding a member

A new member arrives with **the cheap arm it has to beat**, not on its own. That
is what made both results above conclusive: the particle filter was not scored
against nothing, it was scored against the linearisation of the same model, so
"is the extra machinery earning anything" had an answer. A member added without
its null can only be argued about.

**And the comparison must be held-out, which is a correctness point rather than
hygiene.** Members do not have the same number of free parameters, and the
in-sample likelihood rewards whichever one has more: a particle filter with a
richer transition will fit a training series better than a Kalman whatever the
truth is. Two comparisons are honest - likelihood on data the parameters were not
fitted on, which is what `research/` already does everywhere, or the **model
evidence**, which integrates the parameters out instead of maximising over them.
`nchopin/particles` reaches evidence through nested sampling and SMC samplers.
This package has neither, and until it does, held-out is the only comparison it
can make.

## Cost is a property of the member, not of the operation

Smoothing is nearly free for one member and the dominant expense for another,
which changes the arithmetic of choosing one:

| member | filtering | smoothing |
| --- | --- | --- |
| linear Gaussian | exact, O(T) | **exact, O(T)** - `smoothing.py` |
| HMM | exact, O(T k^2) | exact, forward-backward |
| particle | O(T N) | **O(T N) to O(T N^2)**, and a literature on making it faster |

`particles` implements FFBS in a standard form, an O(N^2) variant, and faster
variants based on MCMC, pure rejection, or a hybrid of the two - a spread of
schemes that exists because particle smoothing is expensive enough to be worth
three papers. So "the particles tied the linear arm" on levels was not a close
call that could be revisited cheaply: a tie means paying O(N) to O(N^2) for
nothing, on a two-core box.

## Two things a particle member would need and this package has no form of

**An error bar on its own estimation noise.** A particle filter's output is a
Monte Carlo average, so it has a variance that has nothing to do with the
market - run it twice with different seeds and it answers differently. `particles`
carries estimators for exactly this (Chan and Lai 2013, Lee and Whiteley 2018,
Olsson and Douc 2019). Without one, "the particle filter beat the Kalman by 3%"
cannot be distinguished from the particle filter's own noise, which is the shape
of mistake this desk has made before and caught by controls rather than by
arithmetic.

**Sequential parameter learning.** `diagnostics.fit_jerk` is a batch fit: it
re-runs the filter over the whole series for each candidate. The sequential form
updates the parameter posterior as measurements arrive - `particles` has it as
IBIS and SMC^2, with PMMH and Particle Gibbs for the offline Bayesian version -
and it is strictly the more useful shape here, because a level is touched a few
times a week and refitting from scratch each time is the wasteful way to learn
the same thing.

And the nulls that were passed in the volatility study are worth remembering for
what they could not catch: both of them passed, and **neither could have caught
the bug that mattered** - the Kalman arm first reported a negative log-likelihood
of 1.15e17 because `log(r^2)` of a rounded-to-zero FX bar is about -690, and a
Gaussian null never produces one. A passed null is not a correct implementation.

## State count is a separate question from state *stability*, and it was measured

Held out on the same 534 points of eurusd 4h:

| model | held out | per point |
| --- | ---: | ---: |
| two states, reverting rate | **-1009.55** | best |
| three states, two-factor drift | -1083.48 | -0.138 |
| three states, white jerk | -1453.26 | -0.831 |

**Observability was not what decided it**, which is worth saying because it is
the argument I5 reaches for: the condition number of the observability matrix
for price-only measurements at 4h is 2.5 with two states and about 40 with
three, far from the ~1e8 where a state stops being identifiable. A third state
is estimable here. It loses anyway, and the fit declined it - given a slow and a
fast drift component it set the fast one's noise to zero.

So the two axes separate cleanly: **stability is worth about 0.7 nats a point
and the extra state is worth -0.14.** A member proposing more states has to
clear a bar that a member proposing better dynamics did not.

## What is missing, named rather than left out

`dynamax` puts three operations beside each other, and this package has one and a
half of them:

| operation | what it answers | here |
| --- | --- | --- |
| filter | `p(state_t | y up to t)` | `linear.predict` / `update` |
| **smooth** | `p(state_t | y up to T)` | `smoothing.smooth`, any member |
| sample | draw a path from the model | `paths.simulate` |

**The smoother is the real gap, and it is a research gap rather than a live one.**
A desk decision can only use the filter - at the moment a level is touched,
nothing later exists. But every *question about* the filter is asked afterwards,
with all the data in hand, and for those the smoothed estimate is the better one:
where was the level really, given everything that happened next. Scoring a level
against what price did, and fitting `jerk` from touch pairs, are both that kind of
question.

So a smoother belongs here and does not belong in `engine.py`, which is a clean
example of why this package exists: the same model needs two inference modes with
different honesty rules, and only one of them may ever be read live.

The other named absence is **EM**. `fit_jerk` in `diagnostics.py` maximises the
likelihood over one parameter by direct search, which is fine for one and does not
extend: `dynamax.fit_em` fits the whole parameter set, and for a linear-Gaussian
model the M-step for the noise covariances is closed-form. That is the route to
fitting `jerk` **and** `R` together rather than measuring one and searching the
other, and it needs the smoother first, because the E-step is the smoothed
posterior.

## The interface

Deliberately small, and in terms of **time** rather than sample count - the whole
of I6. A member needs `predict`, `update`, and enough readings to be scored:
where the quantity is, how fast it is moving, how sure it is, and where it will
be. Anything a particular member adds - particles, states, existence
probabilities - sits beside that rather than inside it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Filter(Protocol):
    """What every member of the family must do, in time rather than in samples."""

    #: Where the quantity is now, in the subject's units.
    value: float
    #: Its rate of change, per hour. Per hour and not per bar - see `rates.py`.
    rate: float
    #: When the state was last advanced, unix seconds, or None before the first
    #: time it was - a sentinel that is not a valid timestamp.
    at: float | None
    #: Measurements folded in. Not a warm-up gate; the number a score is read
    #: against.
    seen: int

    def predict(self, when: float) -> None:
        """Advance belief to `when`, widening uncertainty by elapsed time."""
        ...

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in one noisy reading. Returns the innovation, which is what every
        scoring question here needs."""
        ...

    def at_time(self, when: float) -> float:
        """Where the quantity will be at `when`, by this member's own belief."""
        ...

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        """The interval it is expected in at `when`."""
        ...

    @property
    def sd(self) -> float:
        """Standard deviation of `value`."""
        ...


#: Members written in this package, by name. A test asserts each one satisfies
#: `Filter`, so the interface cannot drift away from its implementations without
#: something saying so.
def members() -> dict[str, type]:
    """The family members that exist here. Imported lazily to keep this module
    importable while the rest of the package is still being written."""
    from .linear import Gaussian
    from .reverting import Reverting
    from .robust import Robust

    return {"kalman": Gaussian, "reverting": Reverting, "robust": Robust}


#: Members the spec names that are not written yet, with the null each will have
#: to be scored against when it is. Written down now so that adding one without
#: its null requires deleting a line that says it needs one.
PENDING: dict[str, str] = {
    "particle": (
        "the linearised Kalman arm on the same model - the test that settled this "
        "for levels (tied, so the particles bought nothing) and for volatility "
        "(won on all four series). When it is written: resampling is a choice "
        "(multinomial, residual, stratified, systematic, SSP) and systematic is "
        "what the volatility harness used. Fitting parameters *through* a "
        "particle filter needs a differentiable resampling step - PyDPF, "
        "arXiv:2510.25693 - which costs a PyTorch dependency this desk does not "
        "have, so the practical route stays a grid or a search over the "
        "likelihood the filter already returns"
    ),
    "hmm": (
        "the Kalman on the same series. A discrete state is a different claim "
        "about the world, not a better fit, so the comparison has to be on "
        "held-out likelihood rather than on regimes it can draw"
    ),
    "rfs": (
        "the geometric levels themselves - `pips` on its own data, not a random "
        "price and not a round number. Secondary and more interesting: does "
        "existence probability predict a break better than `State`?"
    ),
    "dpm": "the RFS filter, since it is the same thing posed as clustering",
}

#: Inference modes the family should offer and this package does not yet. Keyed
#: the way `dynamax` keys them, with what each unlocks rather than what it is.
MISSING: dict[str, str] = {
    "fixed-lag smoother": (
        "`smoothing.smooth` smooths a finished series, so its latency is the "
        "length of the series - fine for a study and useless live. The fixed-lag "
        "form bounds latency by the lag instead and is the only version a desk "
        "could read, though it still may not: a smoothed estimate at the moment "
        "of a touch uses bars that have not happened"
    ),
    "on-line smoothing": (
        "updates the smoothed estimate as measurements arrive instead of needing "
        "the series to end. Between `smoothing.smooth` and the fixed-lag form in "
        "usefulness, and the one that would make a smoothed reading available "
        "without a horizon to wait for"
    ),
    "monte carlo variance": (
        "an error bar on a particle filter's own estimation noise - Chan and Lai "
        "2013, Lee and Whiteley 2018, Olsson and Douc 2019. Needed before any "
        "particle result can be believed: run the filter twice with different "
        "seeds and it answers differently, and nothing here would tell that from "
        "a real difference"
    ),
    "sequential parameter learning": (
        "IBIS or SMC^2: update the parameter posterior as measurements arrive, "
        "rather than re-running the filter over the whole series per candidate "
        "the way `fit_jerk` does. A level is touched a few times a week, so "
        "refitting from scratch each time is the wasteful way to learn it"
    ),
    "evidence": (
        "integrate the parameters out instead of maximising over them, so "
        "members with different parameter counts can be compared directly. "
        "Nested sampling or an SMC sampler. Until then, held-out likelihood is "
        "the only honest comparison this package can make"
    ),
    "em": (
        "fits the whole parameter set rather than one parameter by search, with "
        "a closed-form M-step for the noise covariances. Needs the smoother "
        "first: the E-step is the smoothed posterior"
    ),
}
