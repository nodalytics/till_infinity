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

#: Seconds in each human period a horizon can be stated in. **Time here is a
#: duration and not a count of bars**, which is the same discipline `rates.py`
#: states for a rate - *per hour and not per bar* - and for the same reason: a
#: forty-step horizon means forty minutes on one feed and forty hours on
#: another, and a desk reasons in the second kind.
#:
#: `project` therefore takes `step` in seconds and `Projection` keeps it, so a
#: horizon can be asked for as `for_duration(days=2)` and read back as one.
PERIODS: dict[str, float] = {
    "seconds": 1.0,
    "minutes": 60.0,
    "hours": 3_600.0,
    "days": 86_400.0,
    "weeks": 604_800.0,
}

#: One bar of the interval a readout came from, in seconds, for the intervals
#: this desk trades. A projection needs the step's **duration**, and an
#: interval name is how every other part of the package says it.
STEPS: dict[str, float] = {
    "1m": 60.0,
    "5m": 300.0,
    "15m": 900.0,
    "30m": 1_800.0,
    "1h": 3_600.0,
    "4h": 14_400.0,
    "1d": 86_400.0,
}


def seconds(**periods: float) -> float:
    """A duration in seconds from human periods: `seconds(hours=6, minutes=30)`."""
    total = 0.0
    for name, count in periods.items():
        if name not in PERIODS:
            raise ValueError(f"unknown period {name!r}, expected one of {sorted(PERIODS)}")
        total += float(count) * PERIODS[name]
    if total <= 0.0:
        raise ValueError("a duration has to be positive")
    return total


def steps_for(step: float, **periods: float) -> int:
    """How many steps of `step` seconds cover a duration given in human periods.

    Rounded up, because a horizon that stops just short of the period asked for
    is a horizon that answers a different question.
    """
    if step <= 0.0:
        raise ValueError("a step has to be a positive number of seconds")
    return max(1, math.ceil(seconds(**periods) / step))


#: Bars forward. Forty because that is what was asked for, and because it is
#: about where a one-bar shape stops being the dominant term and clustering
#: starts to be - which is the thing the `scales` arm exists to carry.
AHEAD = 40

#: Paths drawn. Four thousand puts the standard error of a 1-in-100 probability
#: at about 0.0016, which is fine enough for a barrier question and cheap enough
#: to run per bar in pure Python.
PATHS = 4000

#: Reward-to-risk multiples a plan considers, asked for on 2026-10-17 as
#: "1:2RR, 1:3RR, to 1:20RR", then "to even 1:56RR". Integers to ten, then
#: widening steps, because the spacing that matters is multiplicative and 19
#: against 20 is not a different trade.
#:
#: **Most of this grid is unreachable at most horizons, and that is the useful
#: part.** A 1:56 target is fifty-six stop-distances away, and a driftless walk
#: covers a distance `d` in time about `d**2` - so reaching 56 takes roughly
#: **784 times** as long as reaching 2. That is a statement about the horizon
#: rather than the geometry, and `plan`'s `settle` guard answers it by refusing
#: the multiples that do not resolve. A grid pruned to the reachable ones would
#: hide the constraint that matters.
REWARDS: tuple[float, ...] = (
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    7.0,
    8.0,
    9.0,
    10.0,
    12.0,
    14.0,
    16.0,
    20.0,
    24.0,
    28.0,
    32.0,
    40.0,
    48.0,
    56.0,
)

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
    #: Seconds in one step - the **duration** of a bar, not a count. Kept so a
    #: horizon can be read back in human periods rather than in bars, which is
    #: the discipline `rates.py` already states: per hour, never per bar.
    step: float = 3_600.0

    @property
    def paths(self) -> int:
        return len(self.walks[0]) if self.walks else 0

    @property
    def spans(self) -> float:
        """The horizon as a duration in seconds."""
        return self.ahead * self.step

    def over(self, period: str = "hours") -> float:
        """The horizon in a human period: `got.over("days")`."""
        if period not in PERIODS:
            raise ValueError(f"unknown period {period!r}, expected one of {sorted(PERIODS)}")
        return self.spans / PERIODS[period]

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

    def worth(self, cost: float, multiple: float = 3.0) -> tuple[bool, float]:
        """**The dispersion gate**: is there enough movement coming to clear cost?

        The one entry condition this desk has measurement behind. Direction is
        a coin in every test, so nothing about *which way* can gate a trade -
        but how far price can travel is forecastable, R2 up to 0.85 and a
        high-dispersion classifier at AUC 0.90 surviving strata. And cost is
        not small: `exotic-spreads-are-a-whole-bar-range` measured round trips
        of **0.40 to 0.97 of a bar's range**, which ends most ideas on its own.

        So the gate compares the expected absolute excursion over the horizon
        against `cost`, both in price, and asks for `multiple` times cover.
        Returns the verdict and the ratio, because a bare boolean hides how
        close the call was.

        It cannot make a trade profitable. It can stop one whose entire
        forecast movement is smaller than the spread, which is a different and
        achievable thing.
        """
        if cost < 0.0:
            raise ValueError("cost cannot be negative")
        reach = 0.0
        for high, low in zip(self.rising[-1], self.falling[-1], strict=True):
            reach += max(high - self.start, self.start - low)
        expected = reach / self.paths
        if cost <= 0.0:
            return True, float("inf")
        return expected >= multiple * cost, expected / cost

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
        payoffs: list[float] = []
        for path in range(self.paths):
            at_up = self._first_up(path, up)
            at_down = self._first_down(path, down)
            if at_up >= 0 and (at_down < 0 or at_up < at_down):
                payoffs.append(reward)
            elif at_down >= 0:
                reached = self.falling[at_down - 1][path]
                payoffs.append(-max(1.0, (self.start - reached) / stop))
            else:
                payoffs.append((final[path] - self.start) / stop)
        expectancy = sum(payoffs) / len(payoffs)
        spread = (
            sum((v - expectancy) ** 2 for v in payoffs) / (len(payoffs) - 1)
            if len(payoffs) > 1
            else 0.0
        )
        error = math.sqrt(spread / len(payoffs)) if payoffs else float("inf")
        return Geometry(
            stop=stop,
            target=reward * stop,
            reward=reward,
            wins=race["up"],
            loses=race["down"],
            undecided=race["neither"],
            expectancy=expectancy,
            error=error,
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
    #: **The standard error of `expectancy`**, from the spread of the per-path
    #: payoffs. Carried because without it the expectancy is unreadable: at a
    #: stop far out relative to the paths' own dispersion, `E[R]` divides a
    #: price-scale error by a large number, and 4,000 paths over 1,200 bars put
    #: this at about **0.02**. A driftless projection was read as paying
    #: **+0.05** before this field existed, which is 2.5 of these - noise, and
    #: it looked like edge. Anything inside a couple of standard errors of zero
    #: is the martingale and nothing else.
    error: float
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

    @property
    def separated(self) -> float:
        """How many standard errors the gross expectancy is from zero.

        Below about two, the projection has not distinguished this geometry
        from a driftless walk, which is the **expected** answer rather than a
        disappointing one.
        """
        return self.expectancy / self.error if self.error > 0 else float("nan")


@dataclass(frozen=True, slots=True)
class Plan:
    """A trade with its three prices, and what it would need to pay.

    Asked for on 2026-10-17 - "our statespace trade should have sl, entry, tp".
    This is where that composes, and the emission rule says why it is here:
    `signalling` supplies the **side** as a bounded signal, this module supplies
    the **prices**, and they are paired rather than merged.

    **It does not claim the trade is good, and it cannot.** The barrier identity
    is the martingale theorem: at reward-to-risk `r` a driftless race pays
    `1 / (1 + r)`, so every geometry has expectancy zero before cost and
    negative after. What this reports is `edge` - the directional advantage the
    geometry would need to break even - which is a number a caller can hold
    against the direction edge this desk has actually measured, and that is
    about zero. A plan is a priced requirement, not a recommendation.
    """

    #: `+1` long, `-1` short. Taken from the signal, never decided here.
    side: int
    entry: float
    stop: float
    target: float
    #: Target distance over stop distance.
    reward: float
    #: The share of simulated paths that reach the stop inside the horizon -
    #: **measured on the paths**, not a Gaussian label. `band-coverage.md`
    #: measured the difference: a nominal 0.999 Gaussian band is breached
    #: 14.80 times more often than it claims, where the accessor these paths
    #: are drawn from holds 1.02 to 1.10.
    stopped: float
    #: The share that reach the target first, and the share that resolve neither
    #: way inside the horizon.
    hit: float
    undecided: float
    #: Expected result in units of the stop, and the edge needed to break even.
    expectancy: float
    #: The standard error of `expectancy`. See `Geometry.error` - a geometry
    #: inside a couple of these of zero is the martingale, which is what every
    #: geometry on a driftless projection should be.
    error: float
    edge: float
    cost: float
    #: How the step's shape was drawn: `measured`, `anchored` or `assumed`.
    source: str

    @property
    def risk(self) -> float:
        """Stop distance in price. Always positive."""
        return abs(self.entry - self.stop)

    @property
    def net(self) -> float:
        return self.expectancy - self.cost


def _solve_stop(got: Projection, side: int, breach: float) -> float:
    """The stop distance whose **simulated** breach rate is `breach`.

    Solved on the drawn paths rather than taken from a one-step band, and the
    difference is the whole point: a trade lasts many bars, so what matters is
    how often the *path* reaches the stop over the hold, not how often one bar
    would. Bisection over the distance, which is cheap because `touches` is a
    scan of running extremes that are already computed.
    """
    span = max(abs(got.rising[-1][0] - got.start), abs(got.start - got.falling[-1][0]), 1e-12)
    low, high = 1e-9, 8.0 * span + 1e-9
    for _ in range(40):
        middle = 0.5 * (low + high)
        level = got.start - side * middle
        if got.touches(level) > breach:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def plan(
    got: Projection,
    *,
    side: int,
    breach: float = 0.25,
    rewards: tuple[float, ...] = REWARDS,
    cost: float = 0.0,
    settle: float = 0.50,
    delivers: float = 0.50,
) -> Plan | None:
    """Choose a stop and a target from a drawn projection, and price them.

    `side` comes from the signal - `Signal.side`, or `Layer.settled` - and a
    side of zero returns `None`, because no trade is the correct output of a
    neutral signal rather than a coin flip dressed as one.

    `breach` is the share of paths allowed to reach the stop inside the
    horizon, and the stop is **solved** for it on the paths. `rewards` is the
    grid of target multiples considered, and the one chosen is the one needing
    the **least edge** - not the one with the best expectancy, because every
    expectancy here is zero before cost and the ranking by required edge is the
    only ranking that means anything.

    **`breach` and `settle` are coupled, and the ceiling is not obvious.** With
    the stop solved for a breach rate `b`, the share of paths that resolve
    cannot exceed about `b + 1 / (1 + reward)`: the losers are `b` by
    construction and the winners are bounded by the barrier identity. So at
    `breach = 0.40` and `reward = 2` the most that can ever resolve is about
    0.73, and measured it is **0.507** - and crucially that does **not improve
    with the horizon**, because solving the stop for a breach rate at a longer
    horizon moves the stop out as `sqrt(t)` and rescales the whole geometry.
    A longer hold buys nothing here; a **tighter stop** does. The first default
    pair asked for 0.70 at `breach = 0.40` and was therefore infeasible, which
    read as "no reachable target" at every horizon tried.

    `settle` is the share of paths that must **resolve** - reach the stop or the
    target inside the horizon - and it exists because required edge alone is
    gameable. `edge` is `(cost - expectancy) / (1 + reward)`, so a wider target
    shrinks the denominator while paths that never resolve contribute almost
    nothing to the numerator: ranking by edge alone picked the widest multiple
    on the grid every time, with a target reached by **0.0%** of paths and 75 to
    90% expiring undecided. A target the hold cannot deliver is not a trade, and
    a criterion that prefers one is measuring the horizon rather than the
    geometry. Nothing is returned when no multiple resolves often enough, which
    is the honest answer: at that stop distance, over that horizon, there is no
    reachable target.
    """
    if side not in (1, -1):
        if side == 0:
            return None
        raise ValueError(f"side has to be +1, -1 or 0, not {side}")
    if not 0.0 < breach < 1.0:
        raise ValueError("breach has to lie strictly inside (0, 1)")
    if not rewards:
        raise ValueError("there has to be at least one reward multiple")
    if not 0.0 < settle <= 1.0:
        raise ValueError("settle has to lie inside (0, 1]")
    if not 0.0 < delivers <= 1.0:
        raise ValueError("delivers has to lie inside (0, 1]")

    risk = _solve_stop(got, side, breach)
    if risk <= 0.0:
        return None

    best: tuple[float, Geometry] | None = None
    for reward in rewards:
        # `geometry` is written long-only, so a short is priced on the mirrored
        # distances rather than by a second code path that could disagree.
        priced = got.geometry(stop=risk, reward=reward, cost=cost)
        if 1.0 - priced.undecided < settle:
            continue
        # **And the target has to be delivered, not merely resolved.** A
        # resolution requirement alone is satisfied by *losses*: at a 60%
        # breach the race resolves 60% of the time with the target never
        # reached, so the grid picked 1:56 with a win rate of **0.000**. The
        # barrier identity says a reward of `r` should win `1 / (1 + r)` of
        # resolved races, so this asks the horizon to deliver at least
        # `delivers` of that - which is a statement about the hold being long
        # enough for the target, and the only version of reachability that
        # cannot be met by stopping out.
        if priced.wins < delivers / (1.0 + reward):
            continue
        if best is None or priced.edge < best[1].edge:
            best = (reward, priced)
    if best is None:
        return None
    reward, priced = best

    stop = got.start - side * risk
    target = got.start + side * reward * risk
    stopped = got.touches(stop)
    return Plan(
        side=side,
        entry=got.start,
        stop=stop,
        target=target,
        reward=reward,
        stopped=stopped,
        hit=priced.wins,
        undecided=priced.undecided,
        expectancy=priced.expectancy,
        error=priced.error,
        edge=priced.edge,
        cost=float(cost),
        source=got.source,
    )


@dataclass(frozen=True, slots=True)
class Resting:
    """A limit entry: what it does to the reward, and what it costs to wait.

    Asked for on 2026-10-17 - *"if you shift the entry the RR increases, so
    test it too"* - and the first half of that is arithmetic rather than a
    claim: move the entry `e` toward the stop and the risk becomes `risk - e`
    while the reward becomes `reward + e`, so the ratio rises without anything
    being predicted. At half the original risk the ratio doubles.

    **The second half is where it is paid for, and there are two charges.**

    *The fill.* A limit that is never reached is a trade that never happens, so
    the unconditional expectancy carries `1 - filled` paths at exactly zero. A
    better price bought by not trading is not a better price.

    *The selection.* The paths that fill a long are the paths that **fell
    first**. Conditioning on the fill therefore conditions on having moved
    against the trade, and the race that follows starts from a population that
    is not the one the unconditional geometry was priced on. This is the same
    shape as `a-return-rate-is-geometry`: the arrival is the selection.

    Both are measured here rather than argued, and `expectancy` is the
    **unconditional** one - over every path, filled or not - because that is
    the only number a desk can spend.
    """

    #: Distances from the original price, in price.
    offset: float
    entry: float
    stop: float
    target: float
    #: The ratio **as placed**, which is `(reward + offset) / (risk - offset)`.
    reward: float
    #: Share of paths that reached the entry inside `within` steps.
    filled: float
    #: Of the filled paths, the share that reached the target first and the stop
    #: first. These are conditional on the fill, which is the point.
    hit: float
    lost: float
    #: Expectancy over **all** paths, unfilled ones contributing zero, in units
    #: of the placed risk - and its standard error.
    expectancy: float
    error: float
    #: The same for the filled paths only, so the selection effect is visible as
    #: the difference between the two.
    conditional: float
    cost: float

    @property
    def net(self) -> float:
        return self.expectancy - self.cost * self.filled

    @property
    def edge(self) -> float:
        """Probability mass that would have to move to break even, net of cost."""
        return (self.cost * self.filled - self.expectancy) / (1.0 + self.reward)


def resting(
    got: Projection,
    *,
    side: int,
    offset: float,
    risk: float,
    reward: float,
    within: int | None = None,
    cost: float = 0.0,
) -> Resting:
    """Price a limit entry `offset` better than the current price.

    `risk` and `reward` describe the geometry **from the original price**; the
    placed stop stays where it was and the placed target too, so shifting the
    entry moves it between them and the ratio rises. `within` is how many steps
    the order rests before it is abandoned, defaulting to a quarter of the
    horizon.

    The race is run **from the fill step**, path by path, because a race from
    the start would be the wrong population: it would price a trade that was
    entered at a price it had not reached yet.
    """
    if side not in (1, -1):
        raise ValueError(f"side has to be +1 or -1, not {side}")
    if risk <= 0.0 or reward <= 0.0:
        raise ValueError("risk and reward both have to be positive")
    if not 0.0 <= offset < risk:
        raise ValueError(f"offset {offset} has to sit inside the risk {risk}")
    wait = got.ahead // 4 if within is None else int(within)
    if wait < 1:
        raise ValueError("within has to be at least one step")

    entry = got.start - side * offset
    stop = got.start - side * risk
    target = got.start + side * reward * risk
    placed = risk - offset
    ratio = (reward * risk + offset) / placed

    payoffs: list[float] = []
    hit = lost = filled = 0
    for path in range(got.paths):
        at = -1
        for step in range(got.ahead):
            reach = got.falling[step][path] if side > 0 else got.rising[step][path]
            if (reach <= entry) if side > 0 else (reach >= entry):
                at = step
                break
        if at < 0 or at >= wait:
            payoffs.append(0.0)
            continue
        filled += 1
        # Race from the fill, scanning forward - the running extremes are
        # measured from step zero and cannot answer a question that starts
        # part-way along.
        done = 0.0
        for step in range(at + 1, got.ahead):
            here = got.walks[step][path]
            if (here >= target) if side > 0 else (here <= target):
                done = ratio
                hit += 1
                break
            if (here <= stop) if side > 0 else (here >= stop):
                # Charged at the price reached, which is at or beyond the stop.
                done = -max(1.0, abs(here - entry) / placed)
                lost += 1
                break
        else:
            done = side * (got.walks[-1][path] - entry) / placed
        payoffs.append(done)

    mean = sum(payoffs) / len(payoffs) if payoffs else 0.0
    spread = sum((v - mean) ** 2 for v in payoffs) / (len(payoffs) - 1) if len(payoffs) > 1 else 0.0
    inner = [v for v in payoffs if v != 0.0]
    return Resting(
        offset=offset,
        entry=entry,
        stop=stop,
        target=target,
        reward=ratio,
        filled=filled / got.paths,
        hit=hit / filled if filled else 0.0,
        lost=lost / filled if filled else 0.0,
        expectancy=mean,
        error=math.sqrt(spread / len(payoffs)) if payoffs else float("inf"),
        conditional=sum(inner) / len(inner) if inner else 0.0,
        cost=float(cost),
    )


#: Two-sided 95% normal deviate, for the sample-size arithmetic below.
_Z = 1.959964


def _trials(rate: float, edge: float) -> float:
    """Trades needed to tell `rate + edge` from `rate` at 95%, two-sided.

    `z**2 p (1 - p) / edge**2`, the ordinary binomial sample size. It is here
    rather than left to a caller because the reward-to-risk choice is usually
    argued without it: the edge a geometry **requires** falls as the reward
    rises, and the sample needed to **establish** it is rarely small, so a
    comparison that quotes one and not the other is half an answer.
    """
    if edge <= 0.0 or not 0.0 < rate < 1.0:
        return float("inf")
    return _Z * _Z * rate * (1.0 - rate) / (edge * edge)


@dataclass(frozen=True, slots=True)
class Trade:
    """Everything needed to place a trade, and everything needed to refuse it.

    Asked for on 2026-10-17: *"bring everything together under one output so we
    can use it to trade and test trades"*, with success defined as **a high win
    rate at a high reward-to-risk**.

    **Those two are not independent, and the field that says so is `geometric`.**
    On a driftless market the chance of reaching the target first is exactly
    `1 / (1 + reward)`: 33% at 1:2, 25% at 1:3, 9% at 1:10, 4.8% at 1:20. So a
    high win rate *at* a high reward is not a setup to be searched for among
    entry rules - it is **directional edge**, by a different name, and the
    search for one is the search for the other.

    This object therefore prints `win_rate` and `geometric` side by side. Their
    difference is the only quantity that can be an edge, and `edge_needed` is
    how much of it the geometry requires to cover cost. A setup is interesting
    exactly when `win_rate - geometric` exceeds `edge_needed`, measured out of
    sample, and never because the reward is large.
    """

    side: int
    entry: float
    stop: float
    target: float
    reward: float
    #: Wins as a share of **resolved** trades, which is what a trader means by
    #: a win rate - and the only version comparable to `geometric`.
    #:
    #: The unconditional share is a different number and reading the two
    #: against each other is an error this field exists to prevent: with half
    #: the paths unresolved, an unconditional 0.085 sat beside a geometric
    #: 0.250 and looked like a catastrophic edge when it was a mismatch of
    #: denominators.
    win_rate: float
    #: `1 / (1 + reward)`, what a driftless market owes **among resolved
    #: trades**. `win_rate` sits near it by construction; a *realised* rate
    #: above it is the only edge there is.
    geometric: float
    #: Share of paths that reached neither barrier inside the horizon. A win
    #: rate conditional on resolution is only as meaningful as this is small.
    undecided: float
    #: Probability mass the geometry needs, net of cost, to break even.
    edge_needed: float
    #: Expected movement over the horizon divided by cost. Below the gate's
    #: multiple there is no trade whatever the signal says.
    cover: float
    #: **Trades needed to tell this setup's win rate from the geometric one**,
    #: at the edge it requires, two-sided at 95%.
    #:
    #: This is the answer to *"one setup has good reward and a poor win rate,
    #: another the reverse - so which?"*. They are the same trade: both sit on
    #: the zero-expectancy curve, and only `win_rate - geometric` moves off it.
    #: Cost breaks the tie in favour of **high reward**, because the spread is
    #: a fixed charge per trade while the edge required broadly falls as the
    #: reward rises - 0.0419 at 1:2 against 0.0148 at 1:48, measured.
    #:
    #: **A tidier claim than that does not survive measurement.** The arithmetic
    #: suggests the sample should grow as `(1 + r)`, since `edge ~ c / (1 + r)`
    #: makes `n ~ z**2 (1 + r) / c**2`. Measured, it does not: 486, 812, 431 and
    #: 349 trades at 1:2, 1:3, 1:7 and 1:48. The required edge is not exactly
    #: `c / (1 + r)` because the undecided paths and the conservative loss
    #: settlement both enter it, so the two effects do not cancel cleanly.
    #:
    #: What the numbers do say is more useful than the theory: **every geometry
    #: here needs several hundred trades** - 350 to 800 - before its win rate
    #: can be told from the geometric one. That constraint is indifferent to
    #: the reward chosen, and it is the one that usually binds.
    trials: float
    #: Signal strength that produced the side, in 0..1.
    strength: float
    taken: bool
    #: Why it was refused, or `taken`. A gate that cannot say why it refused is
    #: a gate nobody can debug.
    why: str

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)


def trade(
    got: Projection,
    *,
    side: int,
    strength: float = 1.0,
    cost: float = 0.0,
    breach: float = 0.40,
    cover: float = 3.0,
    deadband: float = 0.0,
    **plans,
) -> Trade:
    """Compose a signal, the dispersion gate and the geometry into one answer.

    The three rings of the architecture meeting at one call: `signalling`
    supplies `side` and `strength`, `worth` is the dispersion gate, and `plan`
    prices the three prices and the edge they demand.

    Always returns a `Trade`. A refusal is an answer with `taken=False` and a
    `why`, not a `None` a caller can forget to check.
    """
    passed, ratio = got.worth(cost, cover)
    blank = {
        "entry": got.start,
        "stop": got.start,
        "target": got.start,
        "reward": 0.0,
        "win_rate": 0.0,
        "geometric": 0.0,
        "undecided": 1.0,
        "edge_needed": float("inf"),
        "cover": ratio,
        "trials": float("inf"),
        "strength": float(strength),
        "taken": False,
    }
    if side not in (1, -1) or abs(float(strength)) <= deadband:
        return Trade(side=0, why="no signal", **blank)
    if not passed:
        return Trade(side=side, why="dispersion below cost", **blank)

    made = plan(got, side=side, breach=breach, cost=cost, **plans)
    if made is None:
        # Say what the best achievable resolution was, because "no reachable
        # target" on its own is not debuggable - the caller cannot tell whether
        # to loosen `settle`, tighten the stop or lengthen the hold, and the
        # answer is usually the stop.
        risk = _solve_stop(got, side, breach)
        best, where = 0.0, 0.0
        for reward in plans.get("rewards", REWARDS):
            priced = got.geometry(stop=risk, reward=reward, cost=cost)
            # Report the best **delivery** - wins as a share of what the
            # barrier identity owes - because that is the constraint that
            # usually binds, and a resolution figure would point at the stop.
            share = priced.wins * (1.0 + reward)
            if share > best:
                best, where = share, reward
        return Trade(
            side=side,
            why=f"target undeliverable (best {best:.0%} of 1:{where:g}'s own rate)",
            **blank,
        )

    lost = 1.0 - made.hit - made.undecided
    return Trade(
        side=side,
        entry=made.entry,
        stop=made.stop,
        target=made.target,
        reward=made.reward,
        win_rate=made.hit / (made.hit + lost) if (made.hit + lost) > 0 else 0.0,
        geometric=1.0 / (1.0 + made.reward),
        undecided=made.undecided,
        edge_needed=made.edge,
        cover=ratio,
        trials=_trials(1.0 / (1.0 + made.reward), made.edge),
        strength=float(strength),
        taken=True,
        why="taken",
    )


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
    step: float | None = None,
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

    # The step's duration, taken from the readout's own interval when the
    # caller does not name one - because an interval is how the rest of the
    # package says how long a bar is, and guessing an hour was how a 1m
    # projection would silently have spanned forty hours.
    span = float(
        STEPS.get(getattr(readout, "interval", ""), PERIODS["hours"]) if step is None else step
    )
    if span <= 0.0:
        raise ValueError("step has to be a positive number of seconds")
    begin = float(readout.value if start is None else start)
    draw, source = _sampler(readout, basis_scale, centred)
    rng = random.Random(seed)

    walks: list[list[float]] = [[0.0] * paths for _ in range(ahead)]
    rising: list[list[float]] = [[0.0] * paths for _ in range(ahead)]
    falling: list[list[float]] = [[0.0] * paths for _ in range(ahead)]

    for p in range(paths):
        here = begin
        low = high = begin
        for k in range(ahead):
            move = draw(rng)
            if scales is not None:
                move *= float(scales[k])
            here += move + drift
            # The bar's excursion either side of its close, so a touch can be
            # registered on a bar that closed away from the level.
            edge = reach * abs(move) if reach else 0.0
            high = max(high, here + edge)
            low = min(low, here - edge)
            walks[k][p] = here
            rising[k][p] = high
            falling[k][p] = low

    return Projection(
        start=begin,
        ahead=ahead,
        basis=basis,
        source=source,
        step=span,
        paced=scales is not None,
        walks=tuple(tuple(row) for row in walks),
        rising=tuple(tuple(row) for row in rising),
        falling=tuple(tuple(row) for row in falling),
    )
