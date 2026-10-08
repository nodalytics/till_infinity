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
class Pool(Restorable):
    """One `(feed, interval, side)`'s correctors and the scores they read."""

    #: Recent conformity scores, oldest first, trimmed to `WINDOW`.
    scores: list[float] = field(default_factory=list)
    #: Each corrector's miscoverage level, one per step in `GAMMAS`.
    alphas: list[float] = field(default_factory=lambda: [1.0 - COVERAGE] * len(GAMMAS))
    #: BOA's linearised regret per corrector, and its square.
    regret: list[float] = field(default_factory=lambda: [0.0] * len(GAMMAS))
    regret_sq: list[float] = field(default_factory=lambda: [0.0] * len(GAMMAS))
    #: Resolved touches folded in. The run-in is counted against this.
    seen: int = 0

    def each(self) -> list[float]:
        """What every corrector would quote, in sigmas."""
        return [quantile(self.scores, 1.0 - a) for a in self.alphas]

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

    def sigmas(self, default: float) -> float:
        """The calibrated half-width in sigmas, or `default` during the run-in."""
        if self.seen < SETTLE or not self.scores:
            return default
        quoted = sum(w * q for w, q in zip(self.weights(), self.each(), strict=True))
        return min(max(quoted, MIN_SIGMAS), MAX_SIGMAS)

    def observe(self, score: float, default: float) -> None:
        """Fold in one resolved touch: step every corrector, charge each its loss."""
        quoted = self.sigmas(default)
        each = self.each()
        miss = 1.0 - COVERAGE
        # The interval score's gradient in the half-width: widening always costs
        # one, and failing to cover costs `2 / miss`. Same linearised regret as
        # the envelope charges against pinball.
        grad = 1.0 - (2.0 / miss if score > quoted else 0.0)
        for k, gamma in enumerate(GAMMAS):
            outside = 1.0 if score > each[k] else 0.0
            self.alphas[k] = min(max(self.alphas[k] + gamma * (miss - outside), FLOOR), CEILING)
            loss = grad * (each[k] - quoted)
            self.regret[k] += loss
            self.regret_sq[k] += loss * loss
        self.scores.append(float(score))
        if len(self.scores) > WINDOW:
            # Trimmed by hand; see `WINDOW` for why this is not a deque.
            del self.scores[: len(self.scores) - WINDOW]
        self.seen += 1

    def coverage(self) -> float:
        """What share of the kept scores the current width would have covered.

        Reported rather than used. A calibrator that cannot be asked whether it
        is calibrated is the same kind of claim this module exists to stop.
        """
        if not self.scores:
            return 0.0
        quoted = self.sigmas(float("inf"))
        return sum(1.0 for s in self.scores if s <= quoted) / len(self.scores)


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

    def sigmas(self, feed: str, interval: str, side: str, default: float) -> float:
        """The half-width to use, in sigmas, or `default` during the run-in."""
        return self.pool(feed, interval, side).sigmas(default)

    def observe(self, feed: str, interval: str, side: str, score: float, default: float) -> float:
        """Fold in one resolved touch and return the width that now applies."""
        pool = self.pool(feed, interval, side)
        pool.observe(score, default)
        return pool.sigmas(default)
