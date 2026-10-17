"""Forward paths: the one place in this package that emits a price.

Asked for on 2026-10-17 - "add monte carlo to statespace, t should look back at
history and create the future paths forward ... we need up to 40 bars forward,
you can use close, ohlc3 prices" - and then the architecture rule that makes it
load-bearing: *every member and component forecasts dispersion, only the Monte
Carlo emits a price, and that price is paired with the signal rather than merged
into it.*

So this module is the translation layer. Dispersion comes in, a distribution
over prices comes out, and nothing here claims a direction.

## Why a distribution and not a point

Because the point forecast is already known to be worthless and the dispersion
forecast is not. Price diffuses at 1.00 to 1.07 times `sqrt(h)`, direction is a
coin in every test on this desk, and a random walk wins the point forecast at
every horizon on 17 to 21 of 39 series. A path distribution asks a question that
has an answer - *how far can price get, how often, and how soon* - and refuses
the one that does not.

The default is therefore **driftless**, and `drift` exists only so that a
caller who has measured one can say so. Zero is not a placeholder here, it is
the measurement.

## Where the step's shape comes from

Not from a Gaussian. `Readout.covering` already composes the member's own
measured residual quantiles with the fitted Student-t past where they reach,
and `research/docs/band-coverage.md` measured that composition holding its
coverage at **1.02 to 1.10** across 0.95 to 0.999 where a Gaussian band of the
same nominal width degrades to **14.80**. This module samples that accessor
directly, which is both the honest shape and the reason the accessor exists.

The sampling identity is exact rather than approximate. `covering(c)` returns
the central interval of coverage `c`, so its upper edge *is* the `(1 + c) / 2`
quantile and its lower edge the `(1 - c) / 2` one. A uniform `u` above a half
therefore maps to `covering(2u - 1).high` and one below to
`covering(1 - 2u).low`, and the draw inherits the measured asymmetry for free.

## Clustering, and the arm that keeps it

Independent draws get the **shape** of one step right and the **dependence**
between steps wrong: volatility clusters, and forty i.i.d. steps cannot
cluster. That matters most for exactly the questions this module is for - the
chance of touching a far level inside forty bars is driven by whether the quiet
and the violent bars arrive together.

Two arms, and the caller chooses:

* `scales = None` - i.i.d. steps. Total dispersion grows as `sqrt(k)`, which is
  the driftless walk, and it is the right default because it assumes nothing.
* `scales = (...)` - a per-step multiple of the one-step spread, which is where
  a dispersion forecast enters. This is the arm the members are being pointed
  at dispersion to feed.

## The limit a caller has to know about: touches are a lower bound

A path of closes cannot touch what it passes through intrabar. A real bar
reaches beyond both of its ends, so **every touch probability from a close-only
path is an underestimate**, and the error grows with how fine the level is.
`reach` is the correction: a multiple of the step's own scale added to each
bar's excursion either side, so a bar can register a touch it closed away from.
It defaults to zero, which is the *conservative* direction and is stated rather
than hidden - a caller who wants calibrated touch rates must set it from
measured bar geometry.

`basis` is `close` or `ohlc3` for the same reason. `ohlc3` is `(high + low +
close) / 3`, a typical price, and its one-step dispersion is **smaller** than
close-to-close because it averages within the bar - so a scale measured on one
basis must not be used on the other. `one-bar-band.md` has the general form of
that mistake: a bar's range systematically exceeds its close-to-close move, so
standardising by the range produces bands that are too wide, which is why
`Span` drives `Q` and does not set the one-bar predictive scale.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

#: Bars forward. Forty because that is what was asked for, and because it is
#: about where a one-bar shape stops being the dominant term and clustering
#: starts to be - which is the thing the `scales` arm exists to carry.
AHEAD = 40

#: Paths drawn. Four thousand puts the standard error of a 1-in-100 probability
#: at about 0.0016, which is fine enough for a barrier question and cheap enough
#: to run per bar in pure Python.
PATHS = 4000

#: The price bases a path can be drawn in. `ohlc3` is the typical price; its
#: one-step dispersion is smaller than `close`'s, so the two are not
#: interchangeable and the field records which one a projection used.
BASES = ("close", "ohlc3")


def basis_price(high: float, low: float, close: float, basis: str = "close") -> float:
    """The price a path is drawn in, from the bar's three used numbers.

    The open is not taken, because neither basis uses it: `ohlc3` is the
    typical price `(H + L + C) / 3` and not the four-price average, and asking
    for an argument that is discarded invites a caller to pass the wrong one.
    """
    if basis == "close":
        return float(close)
    if basis == "ohlc3":
        return (float(high) + float(low) + float(close)) / 3.0
    raise ValueError(f"unknown basis {basis!r}, expected one of {BASES}")


@dataclass(frozen=True, slots=True)
class Projection:
    """A distribution over forward paths, and what it was built from.

    The samples are kept rather than summarised, because every question a
    caller asks of a path distribution is a different reduction of the same
    draws and recomputing them per question would be both slower and
    inconsistent.
    """

    start: float
    ahead: int
    basis: str
    #: How the step shape was drawn, from `Readout.covering`: `measured`,
    #: `anchored` or `assumed`. A caller acting on a far-tail path should be
    #: able to see that the tail's shape was assumed rather than counted.
    source: str
    #: Whether a per-step dispersion forecast was supplied, or the steps were
    #: identically distributed. `False` means the fan is a `sqrt(k)` walk.
    paced: bool
    #: `[step][path]`, the simulated price at each step ahead.
    walks: tuple[tuple[float, ...], ...]
    #: `[step][path]`, the **running** extremes up to and including each step,
    #: with `reach` already applied.
    #:
    #: Running rather than final, and that is the correction this module was
    #: rewritten for. The first version kept only each path's overall high and
    #: low plus the step at which each was last extended, and answered "which
    #: barrier came first" by comparing those two steps - which is not the same
    #: question. It failed its own identity: a driftless race at reward-to-risk
    #: 3 paid 0.3790 where geometry requires 0.2500, and the median time to
    #: touch a two-sigma level read 260 bars. A running extreme is **monotone
    #: in the step**, so the first crossing of any level is a binary search on
    #: it, and that is exact rather than approximate.
    rising: tuple[tuple[float, ...], ...]
    falling: tuple[tuple[float, ...], ...]

    @property
    def paths(self) -> int:
        return len(self.walks[0]) if self.walks else 0

    def _first_up(self, path: int, level: float) -> int:
        """First step whose running high reaches `level`, or -1. Binary search."""
        rows = self.rising
        if rows[-1][path] < level:
            return -1
        low, high = 0, self.ahead - 1
        while low < high:
            middle = (low + high) // 2
            if rows[middle][path] >= level:
                high = middle
            else:
                low = middle + 1
        return low + 1

    def _first_down(self, path: int, level: float) -> int:
        """First step whose running low reaches `level`, or -1. Binary search."""
        rows = self.falling
        if rows[-1][path] > level:
            return -1
        low, high = 0, self.ahead - 1
        while low < high:
            middle = (low + high) // 2
            if rows[middle][path] <= level:
                high = middle
            else:
                low = middle + 1
        return low + 1

    def _sorted(self, step: int | None) -> list[float]:
        at = self.ahead - 1 if step is None else step - 1
        if not 0 <= at < self.ahead:
            raise ValueError(f"step {step} is outside 1..{self.ahead}")
        return sorted(self.walks[at])

    def quantile(self, level: float, step: int | None = None) -> float:
        """The `level` quantile of price at `step` bars ahead, default the last."""
        if not 0.0 < level < 1.0:
            raise ValueError("level must lie strictly inside (0, 1)")
        got = self._sorted(step)
        return got[min(int(level * len(got)), len(got) - 1)]

    def band(self, coverage: float = 0.95, step: int | None = None) -> tuple[float, float]:
        """The central interval of `coverage` at `step` bars ahead."""
        if not 0.0 < coverage < 1.0:
            raise ValueError("coverage must lie strictly inside (0, 1)")
        tail = 0.5 * (1.0 - coverage)
        return self.quantile(tail, step), self.quantile(1.0 - tail, step)

    def fan(self, coverage: float = 0.95) -> tuple[tuple[float, float], ...]:
        """The band at every step, which is the dispersion forecast as a price."""
        return tuple(self.band(coverage, step) for step in range(1, self.ahead + 1))

    def above(self, level: float, step: int | None = None) -> float:
        """Probability the path **ends** above `level`, at `step` bars ahead.

        This is not the touch probability and the difference is the whole
        point: a path can spend thirty bars above a level and close below it.
        """
        got = self._sorted(step)
        return sum(1 for v in got if v > level) / len(got)

    def touches(self, level: float) -> float:
        """Probability the path reaches `level` at any step within the horizon.

        **A lower bound unless `reach` was set.** A close-only path cannot
        touch what it passed through intrabar.
        """
        rows = self.rising if level >= self.start else self.falling
        final = rows[-1]
        if level >= self.start:
            return sum(1 for v in final if v >= level) / self.paths
        return sum(1 for v in final if v <= level) / self.paths

    def when(self, level: float, coverage: float = 0.5) -> float | None:
        """The `coverage` quantile of bars-to-touch, over the paths that touch.

        `None` when too few paths reach it to answer. Conditional on touching,
        which is the only form of the question that has an answer - the paths
        that never arrive have no time to report, and averaging them in as the
        horizon would be inventing data.
        """
        up = level >= self.start
        find = self._first_up if up else self._first_down
        steps = sorted(at for at in (find(p, level) for p in range(self.paths)) if at >= 0)
        if len(steps) < 20:
            return None
        return float(steps[min(int(coverage * len(steps)), len(steps) - 1)])

    def geometry(self, *, stop: float, reward: float, cost: float = 0.0) -> Geometry:
        """Price one stop-and-target pair, long, in units of the stop.

        `stop` and the target are distances from the starting price, `reward` is
        the ratio between them, and `cost` is the round trip in the same units
        as the stop - the number that decides everything, because the gross
        expectancy is zero.

        The undecided paths are marked out at their terminal price rather than
        thrown away. Dropping them is the mistake that makes a long hold look
        free: at a wide target most paths never resolve, and scoring only the
        ones that did is conditioning on the outcome.
        """
        if stop <= 0.0:
            raise ValueError("stop has to be a positive distance")
        if reward <= 0.0:
            raise ValueError("reward has to be positive")
        up = self.start + reward * stop
        down = self.start - stop
        race = self.barrier(up=up, down=down)

        # **Each outcome is settled on the pessimistic side of its barrier.**
        #
        # Crediting a win at exactly the target and charging a loss at exactly
        # the stop understates the losses, because a fat-tailed step overshoots
        # both barriers and the **nearer** one overshoots proportionally more.
        # That bias is enough to invent edge: at `reward = 3` on a driftless
        # projection the gross expectancy read **+0.0701**, and a positive
        # expectancy on a martingale is a bug by this desk's own rule.
        #
        # So a loss is charged at the excursion the path actually reached on
        # the bar that breached the stop, which is at least the stop and is the
        # conservative read of where it would have filled; a win is credited at
        # exactly the target, taking no favourable overshoot. The errors now
        # both point the same way, and that way is against the trade.
        final = self.walks[-1]
        total = 0.0
        for path in range(self.paths):
            at_up = self._first_up(path, up)
            at_down = self._first_down(path, down)
            if at_up >= 0 and (at_down < 0 or at_up < at_down):
                total += reward
            elif at_down >= 0:
                reached = self.falling[at_down - 1][path]
                total -= max(1.0, (self.start - reached) / stop)
            else:
                total += (final[path] - self.start) / stop
        expectancy = total / self.paths
        return Geometry(
            stop=stop,
            target=reward * stop,
            reward=reward,
            wins=race["up"],
            loses=race["down"],
            undecided=race["neither"],
            expectancy=expectancy,
            cost=float(cost),
            # Moving `d` of mass from the stop side to the target side changes
            # the expectancy by `d * (reward + 1)`, so the requirement is the
            # shortfall divided by that.
            edge=(float(cost) - expectancy) / (1.0 + reward),
        )

    def barrier(self, up: float, down: float) -> dict[str, float]:
        """Which of two levels is reached first, over the horizon.

        The quantity a stop and a target are actually a question about, and the
        one a band cannot answer: `band` says where price is at a step, this
        says what happened on the way.
        """
        if not down < self.start < up:
            raise ValueError("the barriers have to straddle the starting price")
        hits = {"up": 0, "down": 0, "neither": 0}
        for path in range(self.paths):
            at_up = self._first_up(path, up)
            at_down = self._first_down(path, down)
            if at_up < 0 and at_down < 0:
                hits["neither"] += 1
            elif at_down < 0:
                hits["up"] += 1
            elif at_up < 0:
                hits["down"] += 1
            else:
                # A tie is one bar reaching both, which a close-only path
                # cannot order. It is charged to `down`, the losing side,
                # because a stop and a target hit in the same bar is a loss on
                # any broker that fills the stop first - and assuming the
                # favourable order is how a backtest invents edge.
                hits["up" if at_up < at_down else "down"] += 1
        return {k: v / self.paths for k, v in hits.items()}


#: Points in the tabulated inverse CDF. The table is built once per projection
#: and sampled by interpolation, because the alternative is calling `covering`
#: per draw - and past the measured grid that runs a Student-t quantile by
#: bisection, which at four thousand paths times forty steps is hundreds of
#: millions of bisection steps. The first version of this module did exactly
#: that and was unusable; this is the fix rather than an optimisation.
#:
#: The table is laid out in **log-odds** rather than linearly so the tails are
#: resolved. A linear grid of this size would put its outermost point at
#: 0.99975 and clip everything past it, which is precisely the part the
#: Student-t is here for.
TABLE = 2001

#: How far into each tail the table reaches, as a probability. Beyond it a draw
#: is clamped to the table's edge, so the simulated tail is the measured and
#: anchored one out to about a one-in-twenty-thousand step and no further.
#: Stated, because a clamp that is not stated is a silent truncation of exactly
#: the thing a path distribution is asked about.
EDGE = 5e-5


@dataclass(frozen=True, slots=True)
class Geometry:
    """What one stop-and-target pair costs, and the edge it would need to pay.

    The last field is the point. A dispersion forecast **cannot** make a
    driftless market pay - the barrier identity *is* the martingale theorem, so
    every geometry has expectancy zero before costs and negative after, and any
    arm reporting otherwise on a walk has a bug rather than an edge. What a
    measured dispersion can do is say **how much directional advantage a given
    geometry would need**, and that number is checkable against the direction
    edge this desk has actually measured, which is about zero.

    So this is not a chooser that finds favourable geometry. It is a chooser
    that prices the requirement, and lets a geometry be rejected for needing
    more than anything available can supply.
    """

    #: Distances from the entry, in price.
    stop: float
    target: float
    #: Reward to risk, `target / stop`.
    reward: float
    #: Where the race ended, from the simulation.
    wins: float
    loses: float
    undecided: float
    #: Expected result in units of the stop, including the undecided paths
    #: marked out at their terminal price. On a martingale this is ~0 before
    #: cost, and that is the assertion rather than the hope.
    expectancy: float
    #: Cost charged, in units of the stop.
    cost: float
    #: Probability mass that would have to move from the stop side to the
    #: target side for `expectancy - cost` to reach zero. **The requirement.**
    #: Negative means the geometry already pays, which on a driftless
    #: projection means the cost was understated.
    edge: float

    @property
    def net(self) -> float:
        """Expectancy after cost, in units of the stop."""
        return self.expectancy - self.cost


def _table(readout, basis_scale: float) -> tuple[tuple[float, ...], str]:
    """The step distribution's inverse CDF, tabulated once, centred on zero.

    Exact at every tabulated point rather than fitted: `covering(c)` is the
    central interval of coverage `c`, so its edges are the `(1 +/- c) / 2`
    quantiles and reading them off returns those quantiles. The measured
    asymmetry comes along without being asked for, and the tail comes from
    whichever arm `covering` says it used.
    """
    centre = readout.covering(0.001).centre
    source = readout.covering(min(1.0 - 2.0 * EDGE, 0.999999)).source
    span = math.log((1.0 - EDGE) / EDGE)
    out = []
    for i in range(TABLE):
        share = i / (TABLE - 1)
        u = 1.0 / (1.0 + math.exp(-(2.0 * share - 1.0) * span))
        if u > 0.5:
            got = readout.covering(min(2.0 * u - 1.0, 0.999999)).high
        elif u < 0.5:
            got = readout.covering(min(1.0 - 2.0 * u, 0.999999)).low
        else:
            got = centre
        out.append((got - centre) * basis_scale)
    return tuple(out), source


def _mean(table: tuple[float, ...]) -> float:
    """The expected step under the sampler, exactly.

    The sampler interpolates `table` linearly between log-odds-spaced points,
    so its expectation is the trapezoid sum of those segments weighted by the
    probability each spans. Computed rather than estimated, because it is
    subtracted below and an estimate would leave a residual drift behind.

    The clamped tails are carried at their edge values, which is what the
    sampler does with them.
    """
    last = len(table) - 1
    span = math.log((1.0 - EDGE) / EDGE)
    at = []
    for i in range(len(table)):
        share = i / last
        at.append(1.0 / (1.0 + math.exp(-(2.0 * share - 1.0) * span)))
    total = table[0] * EDGE + table[last] * EDGE
    for i in range(last):
        total += 0.5 * (table[i] + table[i + 1]) * (at[i + 1] - at[i])
    return total


def _sampler(readout, basis_scale: float, centred: bool = True):
    """A draw from the readout's own one-step distribution, as a step in price.

    `centred` removes the step's own mean, so a projection asked for without a
    drift gets one. **This is not cosmetic.** The step is drawn from the
    member's measured residual grid, and that grid's sampling noise leaves its
    mean a little off its median - on a 4,000-residual Gaussian grid the gap
    measured **+0.0127** of a step. A path compounds it: over forty bars that
    is half a step of invented drift, and over four thousand it was enough to
    push a symmetric barrier race from 0.500 to **0.757**, which is how this
    was found. The measured **shape** - the skew and the tails - is untouched;
    only the location is pinned.
    """
    table, source = _table(readout, basis_scale)
    if centred:
        shift = _mean(table)
        table = tuple(v - shift for v in table)
    last = len(table) - 1
    span = math.log((1.0 - EDGE) / EDGE)

    def draw(rng: random.Random) -> float:
        u = rng.random()
        if u <= EDGE:
            return table[0]
        if u >= 1.0 - EDGE:
            return table[last]
        where = (math.log(u / (1.0 - u)) / span + 1.0) * 0.5 * last
        low = int(where)
        if low >= last:
            return table[last]
        rest = where - low
        return table[low] + rest * (table[low + 1] - table[low])

    return draw, source


def project(
    readout,
    *,
    ahead: int = AHEAD,
    paths: int = PATHS,
    basis: str = "close",
    start: float | None = None,
    scales: tuple[float, ...] | None = None,
    reach: float = 0.0,
    drift: float = 0.0,
    seed: int = 0,
    basis_scale: float = 1.0,
    centred: bool = True,
) -> Projection:
    """Draw `paths` forward paths of `ahead` bars from one readout.

    `scales` is where a dispersion forecast enters: a per-step multiple of the
    one-step spread, as long as `ahead`. `None` leaves the steps identically
    distributed, which is a `sqrt(k)` walk and assumes nothing.

    `basis_scale` rescales the step for a basis whose dispersion differs from
    the one the readout's residuals were measured on - `ohlc3` is narrower than
    `close` because it averages within the bar, and the two must not share a
    scale. It is **not** inferred, because inferring it from the same bars that
    produced the residuals is how a scale error gets laundered into a result.

    `drift` is per step and defaults to zero. On this desk that default is the
    measurement and not a placeholder - and `centred` is what makes it true,
    by removing the drift that sampling noise in the residual grid would
    otherwise contribute. Pass `centred=False` only to see what that noise is
    worth.
    """
    if basis not in BASES:
        raise ValueError(f"unknown basis {basis!r}, expected one of {BASES}")
    if ahead < 1 or paths < 1:
        raise ValueError("ahead and paths both have to be at least one")
    if scales is not None and len(scales) != ahead:
        raise ValueError(f"scales has {len(scales)} entries for {ahead} steps")
    if reach < 0.0:
        raise ValueError("reach cannot be negative")

    begin = float(readout.value if start is None else start)
    draw, source = _sampler(readout, basis_scale, centred)
    rng = random.Random(seed)

    walks: list[list[float]] = [[0.0] * paths for _ in range(ahead)]
    rising: list[list[float]] = [[0.0] * paths for _ in range(ahead)]
    falling: list[list[float]] = [[0.0] * paths for _ in range(ahead)]

    for p in range(paths):
        here = begin
        low = high = begin
        for step in range(ahead):
            move = draw(rng)
            if scales is not None:
                move *= float(scales[step])
            here += move + drift
            # The bar's excursion either side of its close, so a touch can be
            # registered on a bar that closed away from the level.
            span = reach * abs(move) if reach else 0.0
            high = max(high, here + span)
            low = min(low, here - span)
            walks[step][p] = here
            rising[step][p] = high
            falling[step][p] = low

    return Projection(
        start=begin,
        ahead=ahead,
        basis=basis,
        source=source,
        paced=scales is not None,
        walks=tuple(tuple(row) for row in walks),
        rising=tuple(tuple(row) for row in rising),
        falling=tuple(tuple(row) for row in falling),
    )
