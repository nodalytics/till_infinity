"""One boundary: a caller hands over a bar and gets back what it can publish.

`docs/specs/2026-10-14-statespace-as-the-structures-library.md` asks for
statespace to be the thing the engine talks to - *"gets the result and publish
it"* - with how it works contained inside. `engine.py` imports **twenty**
modules from `structures` and orchestrates them across 3,303 lines; this is the
shape that replaces those twenty imports with one.

## It composes statespace's own parts, which is the opposite of what the spec said

The spec's step one was a façade that "calls today's modules in today's order".
**That cannot be built here**, and the reason is the rule this package was
written under: statespace imports nothing from its sibling modules, only from
`shared`. A façade inside statespace that called `levels` and `reactions` would
invert the dependency and make the package neither standalone nor deletable -
`tests` asserts the containment, so it would also fail.

So the direction is the other way round. This exposes what statespace can
answer **from its own measured parts**, and a caller keeps calling its existing
code for the rest. That makes the migration incremental by construction: every
question statespace learns to answer moves from the caller's side of this
boundary to ours, and the caller's import list shrinks by one each time.

## What it answers today, and what it does not

**Answers**, each with a measurement behind it rather than a hope:

* **where the quantity is and how unsure we are** - `pooling.Pooled` with
  `adapt=True`, measured at 5.6x on CRPS over the best single member and 2.7x
  again from letting each member fit its own process noise;
* **a calibrated interval** - the empirical quantiles of its own standardised
  residuals, which `statespace-conditional-quantiles.md` measured at CRPS
  0.9899 against a Gaussian's 1.0000 and which beat a conditional band;
* **the barrier geometry** - `bounding`, where optional stopping fixes two of
  the four quantities once two are chosen, with the measured per-family walls;
* **whether activity should be driving any of it** - `behaving.drives_q`, from
  a table covering nineteen market classes with no misclassification.

**Does not answer, and a caller must still do these itself**: level discovery -
`drawing` is 3,554 lines of finding the prices that matter and statespace models
a price rather than finding the prices worth modelling - the volatility book,
and session context. The spec says why level discovery is the hard one: a
mixture whose centres are free states **collapses onto the data**, so a
statespace level finder has to be anchored from outside the likelihood.

## The two rules that make this a boundary rather than a decoration

**A caller may not reach inside to recompute anything.** If it needs a number,
`Readout` carries it. The spec's test for this is concrete: a façade whose
consumer still imports `levels.SECONDS` - which `engine.py:182` does - is not a
façade.

**And `Desk` owns the state.** A caller that has to hold a member per feed and
interval, and know which to advance when, is still doing the orchestration.
`Desk` keeps them, so the caller holds one object.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from .behaving import classify, drives_q, traits_for
from .bounding import feasible, least_horizon, shifts_for
from .pacing import Pace
from .pooling import Pooled
from .tails import coverage as _coverage
from .tails import dof_for
from .tails import reach as _reach

#: Standardised residuals kept for the interval. Long enough for a 5% tail to
#: have observations behind it, which `statespace-conditional-quantiles.md`
#: uses for the same reason.
WINDOW = 500

#: Residuals before an interval is offered at all. Below this the quantiles are
#: noise wearing a band's authority.
LEAST = 200

#: The activity exponent on `Q`. **1.0 and not 2.0**: the price members prefer
#: 2, and `statespace-activity-on-production-q.md` measured a level-tracking
#: filter preferring **1** on 7 of 8 instruments and losing at 2. A caller
#: tracking a level gets the exponent measured on a level.
EXPONENT = 1.0


@dataclass(frozen=True, slots=True)
class Readout:
    """Everything statespace can say about one bar, and nothing about how.

    Frozen, because a caller that can mutate a result is a caller that can
    disagree with the thing that produced it.
    """

    feed: str
    interval: str
    at: float

    #: Where the quantity is, and the one-step spread of the **next
    #: observation** - the state's uncertainty plus the measurement noise.
    #:
    #: **Not the state spread.** `statespace-river-against-members.md` records
    #: what that costs: scoring a filter's `sd` as a predictive spread leaves
    #: out `R` and makes every member look over-confident by exactly that
    #: term, which nearly handed a River tree a rout it had not earned.
    value: float
    spread: float

    #: `(level, value)` pairs, ascending, ready for `diagnostics.crps` and for
    #: a caller that wants a band rather than a sigma. Empty while warming.
    quantiles: tuple[tuple[float, float], ...] = ()

    #: The market class and what it was measured to do, or `None` for a class
    #: that was never measured - which is the honest answer rather than a
    #: plausible default.
    family: str = "unknown"
    absorbs: bool | None = None

    #: Whether activity is driving `Q` for this feed, and the factor it
    #: applied. `False` on a feed whose tick count its generator fixes.
    paced: bool = False
    pace_factor: float = 1.0

    #: The measured `(up, down)` barrier walls for this feed's family.
    walls: tuple[float, float] = (0.0, 0.0)

    #: Observations folded in. The number a score is read against, not a
    #: warm-up gate.
    seen: int = 0

    @property
    def warm(self) -> bool:
        """Whether the interval is offered. A caller should check this."""
        return bool(self.quantiles)

    def band(self, sigmas: float = 2.0) -> tuple[float, float]:
        """A symmetric band, for a caller that wants one number either side."""
        reach = sigmas * math.sqrt(max(self.spread, 0.0))
        return self.value - reach, self.value + reach

    def band_covering(self, coverage: float = 0.95) -> tuple[float, float]:
        """A band asked for by **coverage** rather than by sigmas.

        `band(sigmas)` is a Gaussian coverage claim - two sigmas means 95.4%
        only if the residuals are Gaussian, and `one-bar-band.md` measured that
        they are not: at one bar they are Student-t with 3 to 5 degrees of
        freedom, beating a Gaussian on both PIT flatness and CRPS on 64 of 64
        out-of-sample feed-frames.

        The correction is **not uniform**. Near 95% this and `band(2.0)` agree
        to a fraction of a percent, so nothing already reading a two-sigma band
        was wrong. Past that they separate fast, and at 99.9% the Gaussian is
        nearly half too narrow.

        Prefer `quantiles` in the body, where they are measured rather than
        assumed. Use this in the **far tail**, which they cannot reach: there
        are `WINDOW` of them, sized by its own comment for a 5% tail, and a
        99.9% band wants the 1-in-1000 residual.
        """
        reach = _reach(coverage, dof_for(self.interval)) * math.sqrt(max(self.spread, 0.0))
        return self.value - reach, self.value + reach

    def covers(self, sigmas: float = 2.0) -> float:
        """What `band(sigmas)` actually covers on this interval's measured tail.

        The diagnostic reading of the same fact. A three-sigma band is not
        99.73% of anything here - on a tail index of 4 it is breached about
        five times as often as that label promises.
        """
        return _coverage(sigmas, dof_for(self.interval))

    def barrier(self, probability: float, horizon: float) -> dict[str, float] | None:
        """The barrier geometry for this feed, or `None` if it is infeasible.

        Delegated rather than re-derived: optional stopping leaves two degrees
        of freedom in four quantities, so a caller choosing all four is
        choosing a contradiction, and `least_horizon` is what says which
        combinations are not even reachable.
        """
        if not feasible(probability, horizon, feed=self.feed):
            return None
        from .bounding import solve

        got = solve(probability=probability, horizon=horizon, feed=self.feed)
        return dict(got) if isinstance(got, dict) else None

    def least_horizon(self, probability: float) -> float:
        """The smallest horizon this probability admits, for this feed."""
        return least_horizon(probability, feed=self.feed)


@dataclass(slots=True)
class Desk:
    """The state a caller would otherwise have to keep itself.

    One per process. Holds a member and an activity estimator per feed and
    interval, so a caller holds this and nothing else.
    """

    exponent: float = EXPONENT
    window: int = WINDOW
    _members: dict[tuple[str, str], Pooled] = field(default_factory=dict)
    _paces: dict[tuple[str, str], Pace] = field(default_factory=dict)
    _residuals: dict[tuple[str, str], deque] = field(default_factory=dict)

    def forget(self, feed: str = "", interval: str = "") -> int:
        """Drop state. Everything, or one feed, or one feed and interval."""
        keys = [
            key
            for key in list(self._members)
            if (not feed or key[0] == feed) and (not interval or key[1] == interval)
        ]
        for key in keys:
            self._members.pop(key, None)
            self._paces.pop(key, None)
            self._residuals.pop(key, None)
        return len(keys)

    @property
    def tracking(self) -> int:
        return len(self._members)

    def read(
        self,
        feed: str,
        interval: str,
        when: float,
        value: float,
        noise: float,
        volume: float = 0.0,
    ) -> Readout:
        """Fold one observation in and return what can be published.

        `noise` is the measurement **variance**, which is what every member in
        this package takes - named rather than inferred, because a caller
        passing a standard deviation here would under-state it by its own
        square and nothing would complain.

        `volume` drives `Q` where the feed's class says activity carries
        anything. Zero, or a feed whose generator fixes its tick count, leaves
        the mechanism inert - which `pacing.Pace` does by itself, without being
        told.
        """
        key = (feed, interval)
        member = self._members.get(key)
        if member is None:
            member = self._members[key] = Pooled()
            self._paces[key] = Pace(exponent=self.exponent)
            self._residuals[key] = deque(maxlen=self.window)

        pace, kept = self._paces[key], self._residuals[key]
        paced = drives_q(feed)
        factor = 1.0
        if paced and volume > 0:
            pace.update(float(volume))
            factor = pace.factor(float(volume))

        # The driver enters as `1 + gain * u`, which is the contract
        # `driven.Driven` publishes and the form that makes `gain = 0` the
        # control arm rather than a special case.
        member.predict(float(when), factor - 1.0)
        spread = float(member.variance) + max(float(noise), 0.0)
        before = float(member.value)
        if spread > 0:
            kept.append((float(value) - before) / math.sqrt(spread))
        member.update(float(value), float(noise), float(when))

        traits = traits_for(feed)
        return Readout(
            feed=feed,
            interval=interval,
            at=float(when),
            value=float(member.value),
            spread=float(member.variance) + max(float(noise), 0.0),
            quantiles=self._quantiles(key, member, noise),
            family=classify(feed),
            absorbs=None if traits is None else traits.absorbs,
            paced=bool(paced and volume > 0),
            pace_factor=factor,
            walls=shifts_for(feed),
            seen=int(member.seen),
        )

    def _quantiles(self, key, member, noise: float) -> tuple[tuple[float, float], ...]:
        """The shape-free interval: empirical quantiles of its own residuals.

        Shape-free rather than Gaussian because no Gaussian band on this desk
        has ever been calibrated - PIT flatness 18 to 461 - and the empirical
        one reaches 1.5 while also scoring better on CRPS, 0.9899 against
        1.0000.
        """
        kept = self._residuals[key]
        if len(kept) < LEAST:
            return ()
        got = sorted(kept)
        sd = math.sqrt(max(float(member.variance) + max(float(noise), 0.0), 0.0))
        out = []
        for i in range(1, 20):
            level = i / 20.0
            at = min(int(level * len(got)), len(got) - 1)
            out.append((level, float(member.value) + sd * got[at]))
        return tuple(out)
