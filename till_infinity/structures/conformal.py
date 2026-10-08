"""How wide a level's zone should be, calibrated against what touches actually do.

The zone was `ZONE_SIGMA` times the Kalman posterior's standard deviation, and
`levels.py` described that band as "price inside this band is touching the
level in any sense the data can distinguish". That is a **coverage claim**, and
it was stated without a coverage measurement: two sigmas is 95.4% of a Gaussian
and nothing here had checked that touches are Gaussian around a level, or that
the observation noise handed to the filter is the right one. Either being wrong
makes the band confidently the wrong width, in a direction nobody can see.

## Why conformal and not another filter dimension

The obvious alternative is to give the Kalman state a width dimension and let
it evolve. That fails on the observation model rather than on the arithmetic:
**width is not observed.** What is observed is a hit or a miss - did the touch
land inside the band - which is Bernoulli, and `|touch - centre|`, which is
half-normal at best. A linear-Gaussian filter over width would be assuming
exactly the thing the band is supposed to stop assuming.

Adaptive conformal inference assumes none of it. It is distribution-free, it
holds its target coverage in the long run, and it keeps holding under
distribution shift - which is the same failure the volatility-units design
elsewhere in this package is already working around.

## This is the thing the envelope already proved

`vol/envelope.py` runs AgACI (Zaffran et al. 2022) over the volatility
envelope and `research/docs/conformal.md` has the measurements: at 50 bars it
held **89.1-89.6%** across FX, metals, crypto and Deriv against one-step ACI's
87.8-88.1%, while being **2-9% narrower** with better pinball in every cell.
Narrower *and* better calibrated is the exact pair of properties a zone wants.

So this is the same machinery pointed at a different interval, and it is built
the same way on purpose - correctors stepped by Gibbs & Candes' rule,
aggregated by Bernstein Online Aggregation with each corrector charged its
share of the aggregate's loss. The only thing that changes is the loss, because
a zone is an interval and not a quantile: the **interval score** stands in for
pinball, and its gradient has the same linearised form, which is why the
weighting code reads like `envelope._weights` and should.

## What this is not

`research/docs/edge.md` found a rolling quantile losing to a matched constant
**four times out of four**, and a walk-forward adaptive probability floor
coming out worse than no floor at all. Three nulls is a strong prior and this
would be the fourth if it were the same thing.

It is not. Those measured a rolling quantile as an **edge gate** - a statistic
used to predict returns, where normalising per cell destroyed a comparability
the raw number already had. This calibrates an interval's **coverage**, which
is a property of the interval rather than a claim about direction, and the
envelope is the existence proof that it works on this data. Worth stating
plainly because both look like "a quantile over recent history" to anyone
reading quickly.

## Two tails, not one width

The band reaches `q-` below the centre and `q+` above, calibrated separately,
and the first version of this module did not: it scored `|touch - centre|` and
quoted one number both ways.

That was throwing away the sign of the residual, which is information and not
noise. **How far price overshoots a floor and how far it undershoots it are
different quantities.** A level that price routinely spikes through from above
but drifts gently into from below has a long tail one way and a short one the
other, and a single width is wrong on both sides at once - too wide where the
distribution is tight, too narrow where it is not.

One number cannot even hold its coverage there. Forced to a symmetric band, it
must either over-cover the short side or under-cover the long one; the choice
is arithmetic rather than preference.

`COVERAGE` stays a statement about the **band**, so each tail is allowed
`TAIL_MISS` - half the total. Two tails at the full rate would leave twice as
much outside as asked for, which is the easy mistake here.

This is a different axis from the pooling below. The pool is keyed by the side
price **arrived from**; the two tails are the two directions the residual can
point once it has arrived. A level has both: approached from above and from
below, and in each case price can miss the centre either way.

## Why it is pooled, and by what

`CONFIDENT_TOUCHES` is 5 and most levels are sparse, so a per-level corrector
would be calibrating on single digits of feedback and would mostly report its
prior back. Pooling is therefore not an optimisation, it is what makes the
estimate exist at all.

The pool is `(feed, interval, side)`. Side because the whole premise of
`levels.py` is that a price met from below and the same price met from above
are two different objects, and there is no reason their touch dispersion
should match. Feed and interval because a 1m level on a synthetic and a 4h
level on gold have no business sharing a width, and because the score is
already normalised by the level's own sigma, so what is left to pool is exactly
the instrument-and-timeframe-shaped part.

That is the same shrinkage argument `reactions` makes between a level's own
record and kNN over similar levels, applied to the interval instead of the
probability.

## The score is out of sample, which is the whole validity argument

The conformity score is `|touch - centre| / sigma`, measured **before** the
touch is folded into the filter. A score taken after the update would be
scored against a centre that had already moved toward it, which is not a
prediction interval being tested, it is a residual being admired.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .state import Restorable

#: The coverage the band is calibrated to hold.
#:
#: 0.95 because that is what the band already claimed: `ZONE_SIGMA` is two, and
#: two sigmas is 95.4% of the Gaussian the old width assumed. This is the same
#: intent restated in a form that does not need the assumption to be true.
COVERAGE = 0.95

#: What each tail is allowed to miss. Half the total, because a band has two
#: ends and `COVERAGE` is a statement about the band rather than about either
#: side of it.
TAIL_MISS = (1.0 - COVERAGE) / 2.0

#: The correctors' steps, geometrically spaced, as in `envelope.GAMMAS`.
#:
#: Eight rather than the envelope's twelve. Feedback here arrives when a touch
#: *resolves*, which is far sparser than a bar closing, so the fastest steps
#: have less to learn from and the slowest would never move; the ends are kept
#: and the middle thinned.
GAMMAS: tuple[float, ...] = tuple(0.0005 * (0.1 / 0.0005) ** (k / 7) for k in range(8))

#: Scores kept per pool. Enough to resolve a 95% quantile with room to spare -
#: the order statistic needs at least `1 / (1 - COVERAGE)` to exist at all -
#: and bounded because a service that runs for months must not grow a list
#: forever. A plain list trimmed by hand rather than a `deque`: a capped deque
#: has come back from a restore **unbounded** in this codebase before, and the
#: bound is the only thing standing between this and a slow leak.
WINDOW = 400

#: Resolved touches a pool needs before its own width is quoted. Below this it
#: returns the default, which is what the band was before any of this existed.
#:
#: AgACI needs a run-in - the envelope says so and measures it - and a quantile
#: read off twenty scores is noise wearing a number's clothes.
SETTLE = 60

#: How far the calibrated width may travel from the default, in sigmas. A pool
#: fed a pathological stretch must not be able to quote a band so tight that
#: nothing ever touches a level, or so wide that everything does.
MIN_SIGMAS = 0.75
MAX_SIGMAS = 6.0

#: The corrector's level may not leave this range. `alpha` is a miscoverage
#: rate; at either end the quantile it asks for stops existing.
FLOOR, CEILING = 0.005, 0.5


def quantile(scores: list[float], level: float) -> float:
    """The conformal order statistic of `scores` at `level`.

    `ceil((n + 1) * level)` rather than a plain percentile, which is the finite
    sample correction that makes the guarantee hold rather than hold
    asymptotically. Returns the largest score when the index runs past the end,
    which is the honest answer to "the quantile you asked for is beyond what
    these observations can resolve".
    """
    if not scores:
        return 0.0
    ordered = sorted(scores)
    index = math.ceil((len(ordered) + 1) * level) - 1
    return ordered[min(max(index, 0), len(ordered) - 1)]


@dataclass(slots=True)
class Tail(Restorable):
    """One side of the band, and the correctors that set how far it reaches.

    `sign` is `+1` for the reach above the centre and `-1` for below, and it
    is the only thing that differs between them: `sign * score` is how far out
    an observation sits on *this* tail, so every corrector, loss and quantile
    below is written once and read twice.
    """

    sign: float = 1.0
    #: Each corrector's miscoverage level for this tail, one per `GAMMAS`.
    alphas: list[float] = field(default_factory=lambda: [TAIL_MISS] * len(GAMMAS))
    #: BOA's linearised regret per corrector, and its square.
    regret: list[float] = field(default_factory=lambda: [0.0] * len(GAMMAS))
    regret_sq: list[float] = field(default_factory=lambda: [0.0] * len(GAMMAS))

    def each(self, scores: list[float]) -> list[float]:
        """What every corrector would reach, in sigmas. Never negative.

        A tail whose quantile falls on the wrong side of the centre - every
        touch in the window was on the other side - is asking for a negative
        reach, which is not a band, so it floors at zero and the clamp in
        `reach` takes it from there.
        """
        if self.sign > 0:
            return [max(0.0, quantile(scores, 1.0 - a)) for a in self.alphas]
        return [max(0.0, -quantile(scores, a)) for a in self.alphas]

    def weights(self) -> list[float]:
        """Bernstein Online Aggregation's weights, each corrector its own rate.

        The same form as `envelope._weights`, and deliberately so: the two are
        solving the same aggregation problem over the same corrector family.
        """
        log_k = math.log(len(GAMMAS))
        logw = []
        for r, r2 in zip(self.regret, self.regret_sq, strict=True):
            eta = min(0.5, math.sqrt(log_k / (1.0 + r2)))
            logw.append(-eta * r - eta * eta * r2)
        top = max(logw)
        weighted = [math.exp(v - top) for v in logw]
        total = sum(weighted)
        return [v / total for v in weighted]

    def reach(self, scores: list[float], settled: bool, default: float) -> float:
        """How far this side of the band reaches, or `default` during the run-in."""
        if not settled or not scores:
            return default
        quoted = sum(w * q for w, q in zip(self.weights(), self.each(scores), strict=True))
        return min(max(quoted, MIN_SIGMAS), MAX_SIGMAS)

    def observe(self, scores: list[float], score: float, settled: bool, default: float) -> None:
        """Step every corrector on this tail and charge each its share of the loss.

        `scores` is the history **before** `score` joins it, so each corrector
        is scored on the reach it would actually have quoted.
        """
        quoted = self.reach(scores, settled, default)
        each = self.each(scores)
        excess = self.sign * score
        # The interval score's gradient in the half-width: widening always
        # costs one, and failing to cover costs `2 / TAIL_MISS`. Same
        # linearised regret as the envelope charges against pinball.
        grad = 1.0 - (2.0 / TAIL_MISS if excess > quoted else 0.0)
        for k, gamma in enumerate(GAMMAS):
            outside = 1.0 if excess > each[k] else 0.0
            self.alphas[k] = min(
                max(self.alphas[k] + gamma * (TAIL_MISS - outside), FLOOR), CEILING
            )
            loss = grad * (each[k] - quoted)
            self.regret[k] += loss
            self.regret_sq[k] += loss * loss


@dataclass(slots=True)
class Pool(Restorable):
    """One `(feed, interval, side)`'s signed scores and its two tails."""

    #: Recent **signed** conformity scores, oldest first, trimmed to `WINDOW`.
    #: Signed because that is the whole point: how far price overshoots a floor
    #: and how far it undershoots it are different quantities, and the version
    #: of this that took `abs` was averaging them.
    scores: list[float] = field(default_factory=list)
    above: Tail = field(default_factory=lambda: Tail(1.0))
    below: Tail = field(default_factory=lambda: Tail(-1.0))
    #: Resolved touches folded in. The run-in is counted against this.
    seen: int = 0

    @property
    def settled(self) -> bool:
        return self.seen >= SETTLE and bool(self.scores)

    def reach(self, default: float) -> tuple[float, float]:
        """`(down, up)` in sigmas - how far the band reaches on each side."""
        return (
            self.below.reach(self.scores, self.settled, default),
            self.above.reach(self.scores, self.settled, default),
        )

    def observe(self, score: float, default: float) -> None:
        """Fold in one resolved touch, signed, on both tails."""
        settled = self.settled
        self.above.observe(self.scores, score, settled, default)
        self.below.observe(self.scores, score, settled, default)
        self.scores.append(float(score))
        if len(self.scores) > WINDOW:
            # Trimmed by hand; see `WINDOW` for why this is not a deque.
            del self.scores[: len(self.scores) - WINDOW]
        self.seen += 1

    def coverage(self) -> float:
        """What share of the kept scores the current band would have covered.

        Reported rather than used. A calibrator that cannot be asked whether it
        is calibrated is the same kind of claim this module exists to stop.
        """
        if not self.scores:
            return 0.0
        down, up = self.reach(float("inf"))
        return sum(1.0 for s in self.scores if -down <= s <= up) / len(self.scores)

    def skew(self) -> float:
        """How asymmetric the band is: `up - down`, in sigmas.

        Zero says the two tails agree and the `abs` version was losing nothing
        here. It is published so that claim can be checked per instrument
        rather than assumed either way.
        """
        down, up = self.reach(0.0)
        return up - down


@dataclass(slots=True)
class Zones(Restorable):
    """Zone widths for every `(feed, interval, side)` seen so far."""

    pools: dict[str, Pool] = field(default_factory=dict)

    @staticmethod
    def key(feed: str, interval: str, side: str) -> str:
        return f"{feed}\u0000{interval}\u0000{side}"

    def pool(self, feed: str, interval: str, side: str) -> Pool:
        name = self.key(feed, interval, side)
        found = self.pools.get(name)
        if found is None:
            found = self.pools[name] = Pool()
        return found

    def sigmas(self, feed: str, interval: str, side: str, default: float) -> tuple[float, float]:
        """`(down, up)` in sigmas, or `default` on both during the run-in."""
        return self.pool(feed, interval, side).reach(default)

    def observe(
        self, feed: str, interval: str, side: str, score: float, default: float
    ) -> tuple[float, float]:
        """Fold in one resolved **signed** touch and return the band that now applies."""
        pool = self.pool(feed, interval, side)
        pool.observe(score, default)
        return pool.reach(default)
