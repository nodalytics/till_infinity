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

#: The spread rule this desk's pools are built with, and **the measurement says
#: to leave it alone.** `pool-spread.md` swept all three against three values of
#: `R` on log variance at 15m and 1h, and no rule dominates:
#:
#: * `mixture` - the law of total variance - fixes the published spread at 15m,
#:   taking `var z` from 1.25-1.37 to **1.06-1.13**, and **overshoots at 1h**,
#:   to 0.82-0.95, where its band also breaches the 0.90 ask at 0.117-0.131
#:   against `shrinking`'s 0.107-0.109;
#: * `argmax` is the most consistent on `var z` (1.01-1.03 at 1h, 1.06-1.25 at
#:   15m) and wins CRPS in three of six traded cells, at a band cost of +0.001
#:   to +0.009 over `shrinking`;
#: * `shrinking` has the best band coverage at every frame and class, which is
#:   the one of these three outputs a consumer reads through `covering`.
#:
#: **And the 1h frame makes the choice easier rather than harder.** No rule
#: in the grid holds the band: `shrinking` reads 0.1072-0.1091, `argmax`
#: 0.1099-0.1163 and `mixture` 0.1165-0.1312, against a 0.090-0.110 line. The
#: discrepancy the sweep was chasing is also smaller than it looked - at the
#: shipped `R` the published spread is 1.20-1.24 rather than the 2.99 measured
#: at `R = 0.265`, because the clamp that produced that number does not bind
#: here. See `adapting-strata.md`.
#:
#: So the field exists and the default does not move. The two frames measured
#: disagree, and **neither is a frame this service runs on** - `config.py`
#: folds 1m and 5m, and the lab cache holds neither, so every dispersion
#: measurement on this desk is at 15m or longer. Picking a rule here would be
#: extrapolating across the disagreement rather than resolving it.
#:
#: It is a field rather than a constant because the sweep needs to request one
#: without patching internals, and because `pooling.py`'s own `alpha` and
#: `rule` figures were measured on `shrinking` over **log closes**, not on this
#: subject at all.
SPREAD_RULE = "shrinking"


#: The widest central coverage the published quantiles can serve, for the grid
#: `_quantiles` publishes. It is not a tuning knob: the grid runs 0.05 to 0.95,
#: so the outermost central interval it holds is 0.90, and `Interval` reads the
#: limit off whatever grid it is handed rather than trusting this number.
#:
#: Past it the quantiles have nothing to say. `WINDOW` is 500 and the 0.05 edge
#: therefore has about 25 observations beyond it; a 0.999 band wants the
#: 1-in-1000 residual, which no window of this size contains.
MEASURED = 0.90


@dataclass(frozen=True, slots=True)
class Interval:
    """A band asked for by coverage, and which arm answered.

    Three arms, and the field that names them is the point: a caller acting on
    a far-tail band should be able to see that the shape was assumed rather
    than counted.

    * **`measured`** - straight off the published quantiles, which are the
      member's own standardised residuals and score CRPS 0.9899 against a
      Gaussian's 1.0000. Asymmetric, because they are actual quantiles.
    * **`anchored`** - past the grid's reach, each side's measured edge grown by
      the **ratio** of the fitted t's reach at the asked-for coverage to its
      reach at the edge. The counted part sets the scale and the assumed part
      only sets the shape, which is the division `one-bar-band.md` argues for:
      the defect it found was the **family**, after a tracked sigma, so the
      scale is the half that was already right.
    * **`assumed`** - no quantiles yet, so the fitted t over `spread` alone.
      This is `band_covering`, and it is the weakest of the three.
    """

    low: float
    high: float
    coverage: float
    #: `measured`, `anchored`, or `assumed`.
    source: str
    #: The centre the band was built around: the measured median where there is
    #: one, and the filter's own `value` on `assumed`, where a symmetric t puts
    #: it at the midpoint anyway.
    centre: float
    #: The tail index used, or `nan` where no t was involved.
    dof: float = float("nan")

    @property
    def half(self) -> float:
        """Half the width, for a caller that wants one number."""
        return 0.5 * (self.high - self.low)

    @property
    def skew(self) -> float:
        """How much further the band reaches up than down, in price units.

        Exactly zero on `assumed`, because a t is symmetric by construction.
        On `measured` and `anchored` it is whatever the residuals did, read
        against their own median rather than against the filter's mean.
        """
        return (self.high - self.centre) - (self.centre - self.low)


def _rate_sd(member) -> float:
    """The drift's standard deviation, from the members that carry one.

    `Pooled` combines `value` and its variance but not the rate's, so this
    takes the weighted mean of the members that expose `p11` and falls back to
    zero for a pool of members that do not. Zero means "not stated" rather
    than "certain", which is why `side_z` is omitted when it is.
    """
    parts: list[float] = []
    for one in getattr(member, "members", ()):
        inner = getattr(one, "_member", one)
        variance = getattr(inner, "p11", None)
        if isinstance(variance, int | float) and variance > 0:
            parts.append(float(variance))
    return math.sqrt(sum(parts) / len(parts)) if parts else 0.0


def _drift(member, name: str) -> float:
    """One named member's own drift per hour, or zero if it is not pooled.

    Zero means "this member is not in the pool" rather than "no drift", which
    is why the payload omits the field when the pool does not carry it.
    """
    names = tuple(getattr(member, "names", ()))
    if name not in names:
        return 0.0
    inner = getattr(member, "members", ())[names.index(name)]
    return float(getattr(getattr(inner, "_member", inner), "rate", 0.0))


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

    #: The **standardised one-step innovation**: how far this observation fell
    #: from where the filter said it would, in units of the spread the filter
    #: expected. Signed, scale-free, and zero before the first prediction.
    #:
    #: It is published because `read` already computes it - the quantile band
    #: is built from exactly these - and because a caller cannot reconstruct
    #: it from the rest of this object. `(value - this.value) / this.spread`
    #: is **not** it: `value` is the state *after* the observation was folded
    #: in, so that residual has already been pulled toward the price it is
    #: measuring, and `spread` is the spread of the **next** observation
    #: rather than the one this bar was scored against. The difference is an
    #: attenuation of unknown size, which is the kind of error that reads as a
    #: weak signal rather than as a bug.
    surprise: float = 0.0

    #: Observations folded in. The number a score is read against, not a
    #: warm-up gate.
    seen: int = 0

    #: **How `spread` was combined, and whether it can be trusted.** Both are
    #: published because `spread` is not comparable across either of them, and
    #: a consumer recording it has no other way to know which one it got.
    #:
    #: `pool-spread.md` measured the three rules differing by 0.2 to 0.4 on
    #: the variance of the standardised innovation at the same `R`, so a
    #: series of recorded spreads spanning a rule change is two series. And
    #: `adapting-strata.md` measured every member pinned against its lever's
    #: stop while the pool published a spread three times too small at
    #: `R = 0.265` - a bar recorded in that state carries a number that should
    #: not be joined to an outcome, which is a per-bar fact rather than a
    #: per-deploy one. At the shipped `R = 0.670` the clamp does not bind, so
    #: this is expected to stay false and is here for when it does not.
    spread_rule: str = ""
    spread_saturated: bool = False

    #: The filtered drift per hour, and its own standard deviation. Published
    #: **together** because the first without the second is a direction with
    #: no significance, and direction at the level is measured closed on this
    #: desk: 0.50 across 112,429 rows, 16 of 17 bias kinds null, and a gate
    #: that finds a *planted* drift at z +2.90 still earning 2% of a spread.
    #:
    #: `rate_sd` comes from the members that carry a rate covariance, which is
    #: also where `observability.md` measured what a scalar observation can
    #: say about a drift: `sd(rate)` runs 0.0010 per hour over 500 bars at 1h
    #: and 1.44 over 60 bars at 1m. A consumer reading `rate` without
    #: `rate_sd` at the short end is reading noise.
    rate: float = 0.0
    rate_sd: float = 0.0

    #: **Two structural drifts that disagree by construction**, so a consumer
    #: can see which structure the pool is reading rather than a blended
    #: number. `drift_free` is the momentum member's unconstrained drift per
    #: hour; `drift_revert` is the mean-reverting member's pull toward its own
    #: level, which is negative when the quantity is above where it reverts to.
    #:
    #: They are published rather than combined because the pool's `rate` is
    #: already the blend and the blend hides the disagreement. `inputs.py`'s
    #: own docstring records the relevant warning: in `slope_fade.py` the two
    #: signals that survived the overlap correction were built on the slope and
    #: **the raw slope itself did not**.
    drift_free: float = 0.0
    drift_revert: float = 0.0

    #: **The slope's own volatility, realised rather than assumed.** The
    #: valuation this package describes is two estimates with two dispersions -
    #: where the quantity is and which way it is going, each with a width - and
    #: until now only the first had one. `rate_sd` is the *estimation*
    #: uncertainty of the drift; this is how much the drift has actually
    #: **moved**, as the root of an exponentially weighted mean of its squared
    #: changes per hour.
    #:
    #: Publishing both makes a guess checkable. `linear.jerk` is the model's
    #: *assumed* slope volatility and its own comment says it "has not been
    #: measured for any subject yet"; `observability.md` then measured the
    #: state it drives at **0.17 to 0.56 of its own posterior sd** on every
    #: class - never distinguishable from zero - with the matching loop running
    #: it to its clamp. A reader comparing `rate_vol` against the jerk the
    #: member is carrying can see the gap rather than trust it.
    rate_vol: float = 0.0

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

    @property
    def widest(self) -> float:
        """The widest central coverage `quantiles` can serve, off the grid itself.

        Zero while warming. For the grid `_quantiles` publishes this is
        `MEASURED`, but it is derived rather than assumed so that a caller who
        builds a `Readout` with a coarser or finer grid gets the right limit.
        """
        if not self.quantiles:
            return 0.0
        levels = [level for level, _ in self.quantiles]
        inner = max(levels[0], 1.0 - levels[-1])
        # Rounded because the levels are floats: a grid at 0.05 steps gives
        # 0.8999999999999999 here, and asking for 0.90 would then fall to the
        # anchored arm for no reason a caller could see.
        return max(0.0, round(1.0 - 2.0 * inner, 9))

    def _at(self, level: float) -> float:
        """The published quantile at `level`, linear between the grid's points."""
        points = self.quantiles
        if level <= points[0][0]:
            return points[0][1]
        if level >= points[-1][0]:
            return points[-1][1]
        for i in range(1, len(points)):
            if level <= points[i][0]:
                (lo, left), (hi, right) = points[i - 1], points[i]
                share = (level - lo) / (hi - lo) if hi > lo else 0.0
                return left + share * (right - left)
        return points[-1][1]

    def covering(self, coverage: float = 0.95) -> Interval:
        """A band asked for by coverage, from the best arm that can reach it.

        **This is the accessor to use.** `quantiles` and `band_covering` are
        both here and neither is right everywhere: the quantiles are measured
        but stop at their grid, and the t reaches anywhere but assumes its
        shape. Leaving a caller to pick meant a caller had to know that a
        2-sigma band is about right and a 4-sigma band is breached eighty-eight
        times more often than its Gaussian label claims. That is not a choice
        worth delegating, so it is made here once.

        The seam is at `widest`, read off the grid. Below it the answer is
        measured; above it the measured edge is grown by the t's own ratio, so
        the two agree exactly at the seam and there is no step.
        """
        if not 0.0 < coverage < 1.0:
            raise ValueError("coverage must lie strictly inside (0, 1)")
        dof = dof_for(self.interval)
        if not self.quantiles:
            low, high = self.band_covering(coverage)
            return Interval(low, high, coverage, "assumed", self.value, dof)
        if coverage <= self.widest:
            return Interval(
                self._at(0.5 * (1.0 - coverage)),
                self._at(0.5 * (1.0 + coverage)),
                coverage,
                "measured",
                self._at(0.5),
                float("nan"),
            )
        edge = self.widest
        grew = _reach(coverage, dof) / _reach(edge, dof)
        # Anchored on the measured **median** rather than on `value`. Both are
        # estimates of the same centre and the median is the one the band is
        # made of, so using it means the two sides cannot invert - the grid
        # ascends and 0.5 sits inside it - and the measured asymmetry survives
        # into the tail. Growing about the midpoint would have destroyed that
        # asymmetry by definition, and growing about `value` would impose the
        # filter's centre on quantiles that already carry their own.
        centre = self._at(0.5)
        down = centre - self._at(0.5 * (1.0 - edge))
        up = self._at(0.5 * (1.0 + edge)) - centre
        return Interval(
            centre - down * grew,
            centre + up * grew,
            coverage,
            "anchored",
            centre,
            dof,
        )

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
    #: The spread rule this desk's pools use. **Not `pooling.RULE`**, and the
    #: difference is measured: see `SPREAD_RULE`.
    rule: str = SPREAD_RULE
    #: Upper clamp on each member's process-noise lever. `None` takes
    #: `adapting.MOST`, which `adapting-strata.md` measured **binding on every
    #: traded instrument** - see `Pooled.most`. Reachable so the value can be
    #: set once it is known, and left alone until then.
    clamp: float | None = None
    _members: dict[tuple[str, str], Pooled] = field(default_factory=dict)
    _paces: dict[tuple[str, str], Pace] = field(default_factory=dict)
    _residuals: dict[tuple[str, str], deque] = field(default_factory=dict)
    #: key -> (last drift, exponentially weighted mean of its squared change).
    _drifts: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)

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
            self._drifts.pop(key, None)
        return len(keys)

    @property
    def tracking(self) -> int:
        return len(self._members)

    def _rate_vol(self, key: tuple[str, str], rate: float) -> float:
        """Root of the exponentially weighted mean square change in the drift.

        The memory is the residual window's, so the slope's volatility and the
        band's quantiles are estimated over the same history - a reader
        comparing them is then comparing like with like.
        """
        if not math.isfinite(rate):
            return 0.0
        last, mean = self._drifts.get(key, (rate, 0.0))
        step = rate - last
        decay = 1.0 - 1.0 / max(float(self.window), 2.0)
        mean = decay * mean + (1.0 - decay) * step * step
        self._drifts[key] = (rate, mean)
        return math.sqrt(max(mean, 0.0))

    @property
    def saturated(self) -> dict[tuple[str, str], tuple[str, ...]]:
        """Feed-intervals with at least one member against its lever's stop.

        **Published because it was invisible.** A matching loop pinned at its
        clamp still returns a number for every bar, so a desk whose every
        member had run out of process noise - and whose published spread was
        three times too small for it, at `R = 0.265` - logged nothing out of
        the ordinary. `adapting-strata.md` had to go looking, and then found
        the shipped `R = 0.670` does not reach the clamp at all.
        `Watcher.report` carries the count so the next time it happens the
        service says so, whatever the size.
        """
        return {
            key: names
            for key, member in self._members.items()
            if (names := getattr(member, "saturated", ()))
        }

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
            member = self._members[key] = Pooled(rule=self.rule, most=self.clamp)
            self._paces[key] = Pace(exponent=self.exponent)
            self._residuals[key] = deque(maxlen=self.window)

        pace, kept = self._paces[key], self._residuals[key]
        surprise = 0.0
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
            surprise = (float(value) - before) / math.sqrt(spread)
            kept.append(surprise)
        member.update(float(value), float(noise), float(when))

        traits = traits_for(feed)
        return Readout(
            feed=feed,
            interval=interval,
            at=float(when),
            value=float(member.value),
            spread=float(member.variance) + max(float(noise), 0.0),
            quantiles=self._quantiles(key, member, noise),
            spread_rule=self.rule,
            spread_saturated=bool(getattr(member, "saturated", ())),
            rate=float(getattr(member, "rate", 0.0)),
            rate_sd=_rate_sd(member),
            drift_free=_drift(member, "kalman"),
            drift_revert=_drift(member, "reverting"),
            rate_vol=self._rate_vol(key, float(getattr(member, "rate", 0.0))),
            family=classify(feed),
            absorbs=None if traits is None else traits.absorbs,
            paced=bool(paced and volume > 0),
            pace_factor=factor,
            walls=shifts_for(feed),
            surprise=float(surprise),
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
