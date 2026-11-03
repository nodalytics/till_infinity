"""Levels: where price has turned, under whichever definition you want.

Three ways of answering one question, grouped because the question is one and
the three disagree in ways worth being able to compare.

* **`Levels`** - a level as a **latent state observed noisily**. Price turned
  somewhere near it a dozen times, never at exactly the same place, and each
  turn is one noisy measurement of where the level actually sits. The
  posterior variance *is* the zone, so the width comes from the same
  arithmetic as the centre and no smoothing constant is chosen anywhere. The
  estimator is selectable: `Kalman`, `Particle` or `Mean`.
* **`BjorgumLevels`** - ATR-banded zones at confirmed pivots, with role
  flipping, separate-visit counting and merging, faithful to the TradingView
  script. This is the one with the measurements behind it.
* **`Pips`** - Perceptually Important Points: the `count` turns that carry the
  shape, found by repeatedly keeping whichever point sits furthest from the
  line joining the points already kept.

## Three definitions of "a turn", on purpose

They are not redundant and the difference is what you parameterise.

A **pivot** (`trend.pivots`, which `Levels` uses, and `BjorgumLevels`' own
`left`/`right` scan) is a *local* extreme: nothing higher within reach either
side, so the count is whatever the market produced. A **PIP** is *globally*
most important within its window: ask for `count` and get the `count` that
carry the shape - on a quiet window pivots find few and PIPs still find
`count`, on a violent one pivots find many and PIPs still find `count`.

So PIPs suit a fixed-size skeleton - a structure sequence to label HH/LH/HL/LL,
or a comparable number of levels per instrument - and pivots suit "did price
turn here".

## Everything is in volatility units

A 20bp push is enormous in a quiet hour and noise in a violent one, so raw
distances would make a level's history incomparable with its own past the
moment the regime changed. Distances, zone widths and the touch noise all
divide by the current unit, which is what lets a level learned in January mean
something in June and lets gold and EURUSD share one model.

## What the desk has measured, which is mostly a warning

**Levels are not magnets** - `magnet.md` says so directly, and `topology.md`
concluded that levels, ranges and shapes all restate volatility. An 82% return
rate to a displacement origin is matched by a distance-matched placebo on every
class, and a random walk reads 0.825: a return rate is **geometry**. A level
finding at p 0.015 turned out to be anchor overlap, with the no-level control
passing as the tell.

**But zones do hold, and that is the cleanest level result here.** Base break
rate on Bjorgum zones, same construction, same code: real instruments 33.9% /
37.7% / 37.3% at 15m / 1h / 4h, against a synthetic control at 81.3% / 85.0% /
80.5%. Real zones hold about two thirds of the time; on a generated process
with no structure to find, a fifth. That gap is the argument for levels.

What a level estimator is good for, then, is two things: **a target** - fade to
value loses on the entry and not on the target, and the origin picks a
*distance* - and **a shared reference**, since a magnet is not a price that
attracts but a price many participants compute the same way. `Range_Break` is
the positive control for anything built here.

## Displacement origins and gaps are levels too

Folded in here rather than kept apart, because they answer the same question
with a different primitive and the repo's own table says so: an **order block**,
a **displacement origin**, a **supply/demand zone** and this desk's **Level**
are the same object under four names - "the last price at which the market
changed its mind" - and the claim attached to all of them is identical.

* **`Displacement`** finds the impulsive leg and names the `Origin` it came
  from, to the rule the desk specified: `PUSH_MIN` impulsive candles each with
  a body `PUSH_BODY` of its range, a chain that may step over `CHAIN_GAP`
  ordinary candles, and every pause inside the chain a zone of its own.
* **`Gaps`** tracks fair value gaps causally - opened when they form, closed
  when price trades back in - because a list holding only *unfilled* gaps is
  lookahead the moment it is read as of a time before the fill was known,
  which this desk measured at +0.50R a trade.
* **`displacement()`, `features()`, `Imbalance`** are the batch readings over
  a window, kept because their features are published and measured.

None of this takes ticks and none of it needs to: the impulsive-candle test is
`body / range >= 0.70`, which needs an open, high, low and close, and a tick is
one price. **Nautilus aggregates bars from ticks** - `BarAggregation` has
`TICK`, `VOLUME` and `VALUE` plus the `_IMBALANCE` and `_RUNS` variants and
`RENKO` - so subscribing to `EURUSD.SIM-100-TICK-LAST-INTERNAL` runs every
detector here on tick-built candles unchanged. One caution before reaching for
a volume clock: **a clock has to pass an i.i.d. control**, and range time
looked best on 8 of 8 markets while inventing clustering at 5.3x on a process
specified to have none.
"""

from __future__ import annotations

import itertools
import math
import random
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from till_infinity.utils.state import Restorable

from . import grouping
from .bars import NANOS, Reading, bar_input, check_feed, check_scale
from .candles import Bar as Ohlc
from .trend import REACH, Pivot, pivots

# ==========================================================================
# the level book
# ==========================================================================

ZONE_SIGMA = 2.0

#: How much a single touch is believed, in volatility units - the filter's `R`.
#:
#: **0.40, measured, not chosen.** `level-dispersion.md` fitted how tightly
#: each level's touches actually cluster over **22,402 levels of five or more
#: touches**, and the median is 0.40 volatility units on 1h, 4h and 1d alike -
#: the agreement across timeframes being the reason to trust it rather than a
#: per-timeframe number. The conformal pools reached the same place from the
#: other end: a 0.5 noise gave 97.6-98.6% realised coverage against a 90%
#: target, which is a band built from an overstated noise.
#:
#: Being too wide is not cosmetic. `R` is the denominator of the gain, so an
#: inflated one shrinks `variance / (variance + R)` on every touch and the
#: level **learns more slowly than its evidence justifies**.
TOUCH_NOISE_VOL = 0.40

#: How fast a level is allowed to wander, in volatility units per hour. Levels
#: do drift, slowly, as the market repositions around them.
DRIFT_VOL_PER_HOUR = 0.02

#: How many of its own standard deviations a slope must clear before anything
#: may use it. **The whole guard against drawing a trendline through noise**: a
#: constant-velocity filter will happily fit a slope to three scattered
#: touches, and three rather than two because a level that walks away from
#: where price actually turns costs more than one that is slow.
SLOPE_SIGMAS = 3.0

#: Levels closer together than this, in volatility units, are one level. The
#: centre moves as touches are folded in, so the same structure arrives at
#: slightly different prices over an hour and would otherwise accumulate as a
#: dozen neighbours.
MERGE_VOL = 0.35

#: Drop a level with no touch in this many **bars**.
#:
#: **Bars and not hours, and that is a correction.** The retired level book
#: forgot after 6 hours, which was right for what fed it - a stream of
#: published level calls, arriving many per hour. An indicator is fed bars, and
#: pivots are sparse in bars: at `REACH` 3 a turn arrives every few bars, so 6
#: hours on an hourly chart forgets every level before it is touched twice. It
#: emptied the book on a visible shelf, which is what prompted the change. The
#: 6 hours is on the record in `docs/trading.md`; 500 is not measured anywhere,
#: it is the round number that is long enough in bars on every interval.
#:
#: In bars it is interval-independent, which is the property that matters: a
#: level on a daily chart needs weeks and one on a 1-minute chart needs hours,
#: and both are 500 bars.
FORGET_BARS = 500


@dataclass(frozen=True, slots=True)
class Sided:
    """One parameter that may differ for resistance and support, as a tilt.

    `tilt` is the ratio of the resistance side to the support side. The two
    sides are `shared * sqrt(tilt)` and `shared / sqrt(tilt)`, so the
    **geometric mean is `shared` whatever the tilt** and switching asymmetry on
    cannot change the average.

    That is the whole reason this is a tilt rather than two numbers.
    `refit-the-parameter-a-lever-multiplies` is the recorded failure: a
    multiplier whose mean was not 1 changed the average the lever multiplied,
    and refitting it reversed a +1192 result to -24. Two free numbers would
    have made "is the book better per side" a test of "is the book better on
    average", which is a different question with a different answer.

    A `tilt` of 1 returns `shared` on both sides **exactly**, not to within
    floating point: `tests/test_levels_sided.py` asserts the identity on the
    whole book, because an asymmetry capability whose neutral setting is not
    neutral silently reparameterises every existing deployment.
    """

    shared: float
    tilt: float = 1.0

    def __post_init__(self) -> None:
        if self.shared <= 0:
            raise ValueError(f"shared={self.shared} is not a usable parameter value")
        if self.tilt <= 0:
            raise ValueError(
                f"tilt={self.tilt} is not a ratio. A tilt is resistance over "
                f"support and must be positive; 1 means no asymmetry."
            )

    @classmethod
    def of(cls, value: Sided | float | int) -> Sided:
        """Accept a `Sided`, or a bare number meaning the same on both sides."""
        return value if isinstance(value, Sided) else cls(float(value), 1.0)

    @property
    def symmetric(self) -> bool:
        return self.tilt == 1.0

    def for_side(self, side: int) -> float:
        """`side` +1 for resistance (a pivot high), -1 for support, 0 neither.

        The pivot's own side, not the level's position relative to price. A
        pivot high is price met from below and a pivot low is price met from
        above, and `Level` already keeps those counts apart for the same
        reason: they are two different observations, not one object seen twice.

        **0 returns `shared`**, so a `Level` built without a side gets the
        neutral value rather than whichever branch an `if side > 0` happens to
        fall through to - which would have handed every sideless level the
        support parameter and made the default quietly asymmetric.
        """
        if self.tilt == 1.0 or side == 0:
            return self.shared
        root = math.sqrt(self.tilt)
        return self.shared * root if side > 0 else self.shared / root

    def __str__(self) -> str:
        return f"{self.shared:g}" if self.symmetric else f"{self.shared:g}@{self.tilt:g}"


class Clock(StrEnum):
    """Which clock a horizon is measured on."""

    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    #: Bars handled, which is the only one that does not count a market being
    #: shut as time passing.
    BARS = "bars"


#: Seconds per unit, for the wall-clock options.
PER_UNIT: dict[Clock, float] = {
    Clock.SECONDS: 1.0,
    Clock.MINUTES: 60.0,
    Clock.HOURS: 3_600.0,
}


@dataclass(frozen=True, slots=True)
class Forget:
    """How long a level survives with no touch, on a clock of your choosing.

    **The clocks are not interchangeable and the difference is the weekend.** A
    wall-clock horizon counts a closed market as time passing, so a level
    touched on Friday afternoon is 60-odd hours old on Monday morning without a
    single bar having printed - an hours-based rule throws it away for having
    been quiet during a period in which nothing could have touched it. Bars
    cannot do that, which is why `Clock.BARS` is the default.

    The wall-clock options are here because they are right when the horizon is
    genuinely about elapsed time - a news embargo, a session boundary, a level
    whose relevance decays because the world moved on rather than because the
    chart did.
    """

    amount: float
    clock: Clock = Clock.BARS

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(
                f"amount={self.amount} forgets every level immediately, which "
                f"empties the book on every bar. Use a positive horizon, or a "
                f"very large one to keep everything."
            )

    @classmethod
    def of(cls, value: Forget | float | int) -> Forget:
        """Accept a `Forget`, or a bare number meaning that many bars."""
        return value if isinstance(value, Forget) else cls(float(value), Clock.BARS)

    def stale(self, *, idle_seconds: float, idle_bars: int) -> bool:
        """Has a level gone quiet for longer than this horizon?"""
        if self.clock is Clock.BARS:
            return idle_bars > self.amount
        return idle_seconds > self.amount * PER_UNIT[self.clock]

    def __str__(self) -> str:
        return f"{self.amount:g} {self.clock}"


#: Levels kept. A book, not a history.
KEEP = 24

#: Particles per level for the particle estimator. Enough that the effective
#: sample size survives a few resamples, few enough to run per level per touch.
PARTICLES = 256


class Kind(StrEnum):
    """Which estimator a level uses. Selected per `Levels` instance."""

    #: A 1D Kalman filter with a slope it has to earn. The desk's measured
    #: default, and the only one with published constants behind it.
    KALMAN = "kalman"
    #: A particle filter. Carries a non-Gaussian and possibly multimodal
    #: posterior, which is the honest shape when touches cluster in two places.
    PARTICLE = "particle"
    #: A running mean with the standard error of the mean as its spread. The
    #: baseline that says whether the filtering is doing anything.
    MEAN = "mean"


@runtime_checkable
class Estimator(Protocol):
    """What a level's location estimator has to answer.

    Deliberately small. Everything above this - clustering, merging,
    forgetting, which side price came from - is the same whichever estimator is
    chosen, so a comparison between them is a comparison of the estimator and
    not of two different books.
    """

    count: int
    updated: float

    def observe(self, price: float, noise: float, when: float) -> float:
        """Fold in one touch. Returns how far the level moved, as a fraction of
        the residual - the gain, which *is* the answer to "how much did this
        touch move it"."""
        ...

    def at(self, when: float) -> float:
        """Where the level is at `when`."""
        ...

    def sigma_at(self, when: float) -> float:
        """How unsure we are about `at(when)`."""
        ...


@dataclass(slots=True)
class Kalman:
    """A slowly drifting price with a slope it has to earn.

    The state is `(price, slope)` - constant velocity rather than a random
    walk - because a rising floor met four times is four observations of a
    line, and a filter whose only story is "it drifts somewhere" has to be
    dragged to each new touch by its gain.

    **The slope terms enter `variance` only once `trending`**, so a level that
    never earns a slope follows exactly the variance path of the plain 1D
    filter and quotes exactly the band it would have quoted. That is not
    tidiness: the first version of this let the `F P F'` terms through ungated
    and widened every zone in the book, including levels with no slope at all,
    and it showed up as a published feature going near-constant rather than as
    anything that looked like a filter change.
    """

    mean: float = 0.0
    variance: float = 1.0
    slope: float = 0.0
    var_slope: float = 0.0
    covariance: float = 0.0
    #: Volatility units per hour the price state may wander.
    drift: float = DRIFT_VOL_PER_HOUR
    count: int = 0
    updated: float = 0.0
    #: Latched, never cleared: a level that earned a trend and then flattened
    #: is precisely the case `earned_slope` is for.
    earned_slope: bool = False

    @property
    def sigma(self) -> float:
        return math.sqrt(max(self.variance, 0.0))

    @property
    def trending(self) -> bool:
        """Has the slope cleared its own posterior?"""
        spread = math.sqrt(max(self.var_slope, 0.0))
        return spread > 0.0 and abs(self.slope) >= SLOPE_SIGMAS * spread

    def predict(self, when: float, unit: float) -> None:
        """Carry the state forward to `when`, widening as it goes."""
        hours = max(0.0, (when - self.updated) / 3_600.0)
        if hours <= 0.0:
            return
        carry = self._carry(hours)
        if self.trending:
            self.mean += self.slope * carry
            self.variance += 2.0 * carry * self.covariance + carry * carry * self.var_slope
            self.covariance += carry * self.var_slope
        wander = self.drift * max(unit, 0.0) * hours
        self.variance += wander * wander
        self.var_slope += (wander * 0.1) ** 2
        self.updated = when

    def observe(self, price: float, noise: float, when: float) -> float:
        """Fold in one touch. Returns the gain applied to the price."""
        if self.count == 0:
            self.mean, self.variance = price, max(noise, 1e-12)
            self.count, self.updated = 1, when
            return 1.0
        noise = max(noise, 1e-12)
        innovation = self.variance + noise
        gain = self.variance / innovation
        slope_gain = self.covariance / innovation
        residual = price - self.mean
        self.mean += gain * residual
        self.slope += slope_gain * residual
        prior_covariance = self.covariance
        # P <- (I - K H) P with H = [1, 0]. The old covariance is needed for
        # the slope row, so it is read before it moves.
        self.variance *= 1.0 - gain
        self.covariance *= 1.0 - gain
        self.var_slope = max(0.0, self.var_slope - slope_gain * prior_covariance)
        self.count += 1
        self.updated = max(self.updated, when)
        if self.trending:
            self.earned_slope = True
        return gain

    def _carry(self, hours: float) -> float:
        """Hours the slope is carried for. Zero while it has not earned one."""
        return hours if self.trending else 0.0

    def at(self, when: float) -> float:
        return self.mean + self.slope * self._carry((when - self.updated) / 3_600.0)

    def sigma_at(self, when: float) -> float:
        carry = self._carry((when - self.updated) / 3_600.0)
        spread = self.variance + 2.0 * carry * self.covariance + carry * carry * self.var_slope
        return math.sqrt(max(spread, 0.0))


@dataclass(slots=True)
class Particle:
    """A cloud of candidate locations, reweighted by each touch.

    What this buys over the Kalman is the shape of the posterior. Touches that
    cluster in two places - a level that moved, or two levels the clusterer
    merged by mistake - give a **bimodal** posterior, and a Kalman answers that
    with a mean between the two humps and a wide variance, which is a price
    nothing ever turned at. `spread` here is the weighted standard deviation,
    so it widens the same way, but `modes` says whether the mean means anything.

    The cost is that it is stochastic. `seed` is part of the state so a run is
    reproducible, because a level book that differs between two runs over the
    same bars cannot be debugged.
    """

    particles: list[float] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    drift: float = DRIFT_VOL_PER_HOUR
    size: int = PARTICLES
    seed: int = 0
    count: int = 0
    updated: float = 0.0
    _rng: random.Random | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._rng is None:
            self._rng = random.Random(self.seed)

    @property
    def mean(self) -> float:
        if not self.particles:
            return 0.0
        return sum(p * w for p, w in zip(self.particles, self.weights, strict=True))

    @property
    def sigma(self) -> float:
        if len(self.particles) < 2:
            return 0.0
        mu = self.mean
        var = sum(w * (p - mu) ** 2 for p, w in zip(self.particles, self.weights, strict=True))
        return math.sqrt(max(var, 0.0))

    @property
    def effective(self) -> float:
        """Effective sample size: 1 / sum of squared weights.

        Reported because it is the particle filter's own health check. A cloud
        collapsed onto one particle has an effective size of 1 and a spread of
        0, which reads as total certainty and is the opposite of the truth.
        """
        total = sum(w * w for w in self.weights)
        return (1.0 / total) if total > 0 else 0.0

    def predict(self, when: float, unit: float) -> None:
        hours = max(0.0, (when - self.updated) / 3_600.0)
        if hours <= 0.0 or not self.particles:
            return
        wander = self.drift * max(unit, 0.0) * hours
        rng = self._rng or random.Random(self.seed)
        self.particles = [p + rng.gauss(0.0, wander) for p in self.particles]
        self.updated = when

    def observe(self, price: float, noise: float, when: float) -> float:
        noise = max(noise, 1e-12)
        rng = self._rng or random.Random(self.seed)
        if self.count == 0:
            sd = math.sqrt(noise)
            self.particles = [rng.gauss(price, sd) for _ in range(self.size)]
            self.weights = [1.0 / self.size] * self.size
            self.count, self.updated = 1, when
            return 1.0
        before = self.mean
        # Gaussian likelihood, in logs, so a far-off touch does not underflow
        # the whole cloud to zero and leave nothing to normalise.
        logs = [
            math.log(max(w, 1e-300)) - 0.5 * ((price - p) ** 2) / noise
            for p, w in zip(self.particles, self.weights, strict=True)
        ]
        top = max(logs)
        raw = [math.exp(x - top) for x in logs]
        total = sum(raw)
        self.weights = [r / total for r in raw] if total > 0 else [1.0 / self.size] * self.size
        if self.effective < self.size / 2.0:
            self._resample(rng)
        self.count += 1
        self.updated = max(self.updated, when)
        residual = price - before
        return 0.0 if residual == 0.0 else (self.mean - before) / residual

    def _resample(self, rng: random.Random) -> None:
        """Systematic resampling: one uniform draw, evenly spaced thereafter.

        Lower variance than drawing `size` independent uniforms, and it cannot
        fail to pick a heavy particle - which multinomial resampling can, with
        a probability small enough to be a bug found months later.
        """
        step = 1.0 / self.size
        mark = rng.uniform(0.0, step)
        taken: list[float] = []
        cumulative = 0.0
        index = 0
        for _ in range(self.size):
            while cumulative + self.weights[index] < mark and index < self.size - 1:
                cumulative += self.weights[index]
                index += 1
            taken.append(self.particles[index])
            mark += step
        self.particles = taken
        self.weights = [step] * self.size

    def modes(self, unit: float) -> int:
        """How many clusters the cloud falls into, at `MERGE_VOL` resolution.

        More than one says the mean is between two humps and is a price nothing
        turned at - which is the case a Kalman cannot report at all.
        """
        if not self.particles or unit <= 0.0:
            return 0
        gap = MERGE_VOL * unit
        ordered = sorted(self.particles)
        count = 1
        for a, b in itertools.pairwise(ordered):
            if b - a > gap:
                count += 1
        return count

    # `when` is unused: the cloud is already at the latest time, because
    # `predict` moves the particles rather than carrying a slope. Kept in the
    # signature because `Estimator` is one interface and a caller must not
    # have to know which estimator it holds.
    def at(self, when: float) -> float:  # noqa: ARG002
        return self.mean

    def sigma_at(self, when: float) -> float:  # noqa: ARG002
        return self.sigma


@dataclass(slots=True)
class Mean:
    """A running mean, with the standard error of the mean as its spread.

    **Its band is not a zone, and must not be used as one.** The standard error
    shrinks as `1/sqrt(n)`, so twenty touches give a band twenty times tighter
    than the touches themselves scatter - on the two-shelf case it quotes
    0.155 volatility units against the Kalman's 1.055, figures recorded here
    and written up nowhere in `research/docs`, and price would
    almost never be inside it. The two answer different questions: this is *how
    well do we know the mean*, the Kalman's posterior is *where might the level
    be*. Only the second is a zone.

    The baseline, and it is here to be beaten. If the Kalman's gain scheduling
    and the particle cloud's shape buy nothing over this, that is worth knowing
    before either is trusted - and the desk's own history says to expect it:
    the walk is the best-calibrated band this repository has found, and members
    lose exactly the spread on direction.
    """

    total: float = 0.0
    total_sq: float = 0.0
    count: int = 0
    updated: float = 0.0

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else 0.0

    @property
    def sigma(self) -> float:
        """Standard error of the mean, which is the band around the estimate."""
        if self.count < 2:
            return 0.0
        mu = self.mean
        var = max(0.0, self.total_sq / self.count - mu * mu)
        return math.sqrt(var / self.count)

    # `unit` and `noise` are unused: a running mean has no drift to widen for
    # and weights every observation equally, which is exactly the baseline this
    # class is here to be. Ignoring them *is* the difference from the Kalman.
    def predict(self, when: float, unit: float) -> None:  # noqa: ARG002
        self.updated = max(self.updated, when)

    def observe(self, price: float, noise: float, when: float) -> float:  # noqa: ARG002
        before = self.mean if self.count else price
        self.total += price
        self.total_sq += price * price
        self.count += 1
        self.updated = max(self.updated, when)
        residual = price - before
        return 1.0 if self.count == 1 or residual == 0.0 else (self.mean - before) / residual

    def at(self, when: float) -> float:  # noqa: ARG002
        return self.mean

    def sigma_at(self, when: float) -> float:  # noqa: ARG002
        return self.sigma


#: The estimators, selectable by name. Adding one here is enough to make it
#: available to `Levels` and to a discovery sweep.
ESTIMATORS: dict[Kind, type] = {
    Kind.KALMAN: Kalman,
    Kind.PARTICLE: Particle,
    Kind.MEAN: Mean,
}


@dataclass(slots=True)
class Level:
    """One level: where it is, how wide, and what it has seen from each side.

    The side counts are kept apart because **the same price met from below and
    met from above are two different objects** - one is a ceiling being tested,
    the other a floor. Pooling them answers "does the level hold", which is not
    the question; the question is "given price arrived from this side, which
    way does it get pushed".
    """

    estimator: object
    #: Touches from below (price rose into it) and from above.
    from_below: int = 0
    from_above: int = 0
    #: The pivot side that first formed it: +1 resistance, -1 support, 0 if
    #: unset. Kept because a per-side parameter has to be applied to something
    #: stable, and a level's position relative to price is not - it flips as
    #: price moves, which would change a level's parameters under it.
    side: int = 0
    #: Unix seconds of the first and last touch.
    first: float = 0.0
    last: float = 0.0
    #: The bar count at the last touch, for forgetting. Bars rather than
    #: seconds so a weekend is not mistaken for a level going quiet.
    last_bar: int = 0

    @property
    def price(self) -> float:
        return self.estimator.at(self.estimator.updated)

    @property
    def touches(self) -> int:
        return int(self.estimator.count)

    def at(self, when: float) -> float:
        return self.estimator.at(when)

    def zone(self, when: float) -> tuple[float, float]:
        """The band, low first: `ZONE_SIGMA` of the posterior either side.

        This is the whole point of the latent-state framing - the width is the
        same arithmetic as the centre, not a parameter.
        """
        here = self.estimator.at(when)
        reach = ZONE_SIGMA * self.estimator.sigma_at(when)
        return here - reach, here + reach

    def holds(self, price: float, when: float) -> bool:
        low, high = self.zone(when)
        return low <= price <= high

    def age(self, now: float) -> float:
        """Hours since the last touch."""
        return max(0.0, (now - self.last) / 3_600.0)


class Levels(Indicator):
    """A book of levels, built from confirmed pivots, under a chosen estimator.

    Registered with `Actor.register_indicator_for_bars` or the identical method
    on `Strategy`.

    **Touches are confirmed pivots, not bar closes near a price.** A level is a
    price *price turned at*, and a turn is only knowable after it is confirmed -
    `trend.pivots` is reused for exactly that reason, so this book and the
    trendlines are built from the same causal primitive rather than from two
    definitions of a turn that can disagree.
    """

    def __init__(
        self,
        *,
        kind: Kind | str = Kind.KALMAN,
        reach: Sided | int = REACH,
        merge_vol: Sided | float = MERGE_VOL,
        touch_noise_vol: Sided | float = TOUCH_NOISE_VOL,
        forget: Forget | float | int = FORGET_BARS,
        keep: int = KEEP,
        #: Merge by bounded clustering rather than the chaining greedy pass.
        #: Off, because every measured level on this desk was read off the
        #: chaining version - see `_merge`.
        bounded: bool = False,
        span: int = 240,
        seed: int = 0,
        source: Reading = Reading.CLOSE,
        unit: float = 0.0,
        unit_from: Reading | None = Reading.RANGE,
        unit_span: int = 0,
    ) -> None:
        check_scale(type(self).__name__, source, unit, unit_from)
        self.kind = Kind(kind)
        self.reach = Sided.of(reach)
        self.merge_vol = Sided.of(merge_vol)
        self.touch_noise_vol = Sided.of(touch_noise_vol)
        widest = max(self.reach_for(1), self.reach_for(-1))
        if span < 2 * widest + 1:
            raise ValueError(
                f"span={span} cannot hold a pivot at reach={widest}: a "
                f"confirmation needs {2 * widest + 1} bars, so no touch would "
                f"ever be seen and the book would stay empty."
            )
        super().__init__(
            [
                self.kind,
                str(self.reach),
                str(self.merge_vol),
                str(self.touch_noise_vol),
                keep,
                str(Forget.of(forget)),
                "bounded" if bounded else "greedy",
            ]
        )
        self.forget = Forget.of(forget)
        self.keep = int(keep)
        self.bounded = bool(bounded)
        self.span = int(span)
        self.seed = int(seed)
        self.source = source
        self.unit = float(unit)
        self.unit_from = unit_from
        self.unit_span = int(unit_span)
        self._bar_prev: float | None = None
        self._bar_scale = 0.0
        self._window: deque[tuple[float, float, float]] = deque(maxlen=self.span)
        #: Keyed on `(when, side)`, not `when`. With a per-side reach the two
        #: sides confirm on different bars, so a time-only key lets a pivot
        #: high folded at reach 3 suppress the pivot low at the same bar that
        #: only confirms at reach 5 - the level would be silently absent.
        self._seen: set[tuple[float, int]] = set()
        self.levels: list[Level] = []
        self.price = 0.0
        self.when = 0.0
        self.bars_seen = 0
        self.dropped = 0

    # ------------------------------------------------------------- the engine

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. `ts_event` is the bar's close."""
        _, scale = bar_input(self, bar)
        self.price = float(bar.close)
        self.when = bar.ts_event / NANOS
        self._window.append((float(bar.high), float(bar.low), self.when))
        self.bars_seen += 1
        self._set_has_inputs(True)
        found = [p for p in self._pivots() if (p.when, p.side) not in self._seen]
        for pivot in found:
            self._seen.add((pivot.when, pivot.side))
            self._fold(pivot, scale)
        self._forget()
        # **Pruned by the window, not by the book.** `pivots` rescans the whole
        # window every bar, so a pivot time dropped from `_seen` while its bar
        # is still in the window gets folded again - and since `_forget` drops
        # quiet levels, pruning `_seen` by what the book still holds would
        # re-fold the dropped level's own pivots and resurrect it on the next
        # bar, forever. Keyed on the window's oldest bar, this is bounded by
        # `span` and nothing is ever counted twice.
        oldest = self._window[0][2]
        self._seen = {(t, s) for t, s in self._seen if t >= oldest}
        if not self.initialized and self.levels:
            self._set_initialized(True)

    def reach_for(self, side: int) -> int:
        """The pivot reach for one side, at least 1 bar.

        Rounded, because a reach is a bar count: a tilt of 1.2 on reach 3 is
        3.29 and 2.74, which is 3 either way. The tilt therefore does nothing
        to `reach` until it is large enough to move a whole bar, and a test
        asserting otherwise would be asserting a rounding.
        """
        return max(1, round(self.reach.for_side(side)))

    def _pivots(self) -> list[Pivot]:
        """Confirmed pivots, one scan per distinct reach.

        One scan when the reaches agree, which is every symmetric book, so the
        asymmetry capability costs nothing where it is not used.
        """
        up, down = self.reach_for(1), self.reach_for(-1)
        if up == down:
            return pivots(self._window, up)
        return [p for p in pivots(self._window, up) if p.side > 0] + [
            p for p in pivots(self._window, down) if p.side < 0
        ]

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a bar."""
        self._window.clear()
        self._seen.clear()
        self.levels = []
        self.price = 0.0
        self.when = 0.0
        self.bars_seen = 0
        self.dropped = 0
        self._bar_prev = None
        self._bar_scale = 0.0
        self._set_has_inputs(False)
        self._set_initialized(False)

    def _fold(self, pivot: Pivot, scale: float) -> None:
        """One touch into the nearest level, or a new level if none is near.

        The noise and the merge gap are taken at the **pivot's** side, so a
        book may believe a ceiling's touches more tightly than a floor's.
        """
        believed = self.touch_noise_vol.for_side(pivot.side)
        noise = (believed * scale) ** 2 if scale > 0.0 else 1e-12
        level = self._nearest(pivot.price, scale, pivot.side)
        if level is None:
            level = Level(
                estimator=self._build(),
                first=pivot.when,
                last=pivot.when,
                last_bar=self.bars_seen,
                side=pivot.side,
            )
            self.levels.append(level)
        level.estimator.predict(pivot.confirmed, scale)
        level.estimator.observe(pivot.price, noise, pivot.confirmed)
        # A pivot high is a price met from **below** - price rose into it and
        # turned. Reading the pivot's own side as the approach side is the
        # error that makes a ceiling look like a floor.
        if pivot.side > 0:
            level.from_below += 1
        else:
            level.from_above += 1
        level.last = max(level.last, pivot.when)
        level.last_bar = self.bars_seen
        level.first = min(level.first or pivot.when, pivot.when)
        self._merge(scale)

    def _build(self) -> object:
        build = ESTIMATORS[self.kind]
        if self.kind is Kind.PARTICLE:
            return build(seed=self.seed + len(self.levels))
        return build()

    def _nearest(self, price: float, scale: float, side: int = 0) -> Level | None:
        if not self.levels or scale <= 0.0:
            return None
        gap = self.merge_vol.for_side(side) * scale
        near = [x for x in self.levels if abs(x.at(self.when) - price) <= gap]
        return min(near, key=lambda x: abs(x.at(self.when) - price)) if near else None

    def _merge(self, scale: float) -> None:
        """Fold neighbours that have drifted into each other.

        Keeps the one with more touches, because its posterior is the better
        estimate - not the older one, which only says it was found first.

        The gap is the **wider** of the two levels' sides, because merging is
        symmetric and `ordered` is by price: taking one level's own side would
        make whether a pair merged depend on which came first in the scan, so
        the same book would collapse differently read upwards and downwards.

        **This chains, and `bounded=True` is the version that does not.**
        Keeping the better-evidenced centre moves the anchor, so the next
        comparison is against the new price: nine levels 0.30 units apart at
        `merge_vol` 0.35, each carrying more touches than the last, collapse
        into one level spanning 2.40 units - 6.9 times the gap - centred at a
        price only one of the nine sat at. With equal touch counts the anchor
        holds and the same input gives five levels, so whether it collapses
        depends on the touch counts rather than on the prices, and the case
        where it does is the ordinary one of a later touch having seen more.
        See `grouping.cluster`, which bounds the span by construction.

        The default is still the chaining version, because every level this
        desk has measured was read off it and flipping it silently would move
        every level at once.
        """
        if scale <= 0.0 or len(self.levels) < 2:
            return
        if self.bounded:
            self._regroup(scale)
            return
        ordered = sorted(self.levels, key=lambda x: x.at(self.when))
        kept: list[Level] = []
        for level in ordered:
            mine = self.merge_vol.for_side(level.side)
            gap = scale * (max(mine, self.merge_vol.for_side(kept[-1].side)) if kept else mine)
            if kept and abs(level.at(self.when) - kept[-1].at(self.when)) <= gap:
                better, worse = (
                    (level, kept[-1]) if level.touches > kept[-1].touches else (kept[-1], level)
                )
                better.from_below += worse.from_below
                better.from_above += worse.from_above
                better.first = min(better.first, worse.first)
                better.last = max(better.last, worse.last)
                better.last_bar = max(better.last_bar, worse.last_bar)
                kept[-1] = better
                continue
            kept.append(level)
        self.levels = kept

    def _regroup(self, scale: float) -> None:
        """Merge by bounded clustering instead, so no group chains.

        One width for the whole book - the wider of the two sides, which is
        the rule `_merge` already applies pairwise - because a per-group width
        would depend on which levels landed in the group and so on the order
        again.

        Each group folds into its best-evidenced member, which is the same
        choice `_merge` makes; what differs is only which levels are in a
        group together.
        """
        width = scale * max(self.merge_vol.for_side(1), self.merge_vol.for_side(-1))
        prices = [x.at(self.when) for x in self.levels]
        kept: list[Level] = []
        start = 0
        order = sorted(range(len(prices)), key=lambda i: prices[i])
        for group in grouping.cluster(
            [prices[i] for i in order],
            width,
            weights=[float(self.levels[i].touches) for i in order],
        ):
            members = [self.levels[i] for i in order[start : start + group.members]]
            start += group.members
            best = max(members, key=lambda x: x.touches)
            for other in members:
                if other is best:
                    continue
                best.from_below += other.from_below
                best.from_above += other.from_above
                best.first = min(best.first, other.first)
                best.last = max(best.last, other.last)
                best.last_bar = max(best.last_bar, other.last_bar)
            kept.append(best)
        self.levels = kept

    def _forget(self) -> None:
        """Drop what has gone quiet, and cap the book.

        A level nobody has touched within `forget` is one this object has
        never heard of, and keeping it makes the book describe last week. The
        horizon may be in seconds, minutes, hours or bars - see `Forget`, and
        note that only bars ignore a closed market.
        """
        alive = [
            x
            for x in self.levels
            if not self.forget.stale(
                idle_seconds=self.when - x.last, idle_bars=self.bars_seen - x.last_bar
            )
        ]
        self.dropped += len(self.levels) - len(alive)
        if len(alive) > self.keep:
            alive.sort(key=lambda x: (-x.touches, x.age(self.when)))
            self.dropped += len(alive) - self.keep
            alive = alive[: self.keep]
        self.levels = alive

    # ------------------------------------------------------------ the reading

    @property
    def count(self) -> int:
        return len(self.levels)

    def above(self, price: float | None = None) -> Level | None:
        """The nearest level above `price`, defaulting to the last close."""
        here = self.price if price is None else price
        out = [x for x in self.levels if x.at(self.when) > here]
        return min(out, key=lambda x: x.at(self.when) - here) if out else None

    def below(self, price: float | None = None) -> Level | None:
        """The nearest level below `price`, defaulting to the last close."""
        here = self.price if price is None else price
        out = [x for x in self.levels if x.at(self.when) < here]
        return max(out, key=lambda x: x.at(self.when) - here) if out else None

    def holding(self, price: float | None = None) -> Level | None:
        """The level whose zone contains `price`, if any."""
        here = self.price if price is None else price
        for level in self.levels:
            if level.holds(here, self.when):
                return level
        return None

    def distance_vol(self, level: Level | None) -> float | None:
        """Signed distance from price to a level, in volatility units.

        None without a level or a scale, rather than 0.0: a zero would read as
        "price is at the level", which is the opposite of "there is no level".
        """
        if level is None or self._bar_scale <= 0.0:
            return None
        return (self.price - level.at(self.when)) / self._bar_scale

    def width_vol(self, level: Level | None) -> float | None:
        """A level's zone width in volatility units - its confidence, readable."""
        if level is None or self._bar_scale <= 0.0:
            return None
        low, high = level.zone(self.when)
        return (high - low) / self._bar_scale

    @property
    def strongest(self) -> Level | None:
        """The most-touched level in the book."""
        return max(self.levels, key=lambda x: x.touches) if self.levels else None


def compare(
    window: Sequence[tuple[float, float, float]],
    *,
    reach: int = REACH,
    unit: float = 1.0,
) -> dict[str, dict[str, float]]:
    """Run every estimator over the same pivots and report what each says.

    The point of making the estimator selectable is to be able to ask whether
    the choice matters, and this is that question in one call: same window,
    same pivots, same clustering, three estimators. If the Kalman's gain
    scheduling and the particle cloud buy nothing over `Mean`, the extra
    machinery is not earning its place - and that is the result to expect
    first, not last.
    """
    found = pivots(window, reach)
    out: dict[str, dict[str, float]] = {}
    for kind in Kind:
        book = Levels(kind=kind, reach=reach, unit=unit, unit_from=None, span=max(len(window), 1))
        book.when = window[-1][2] if window else 0.0
        book._bar_scale = unit
        for pivot in found:
            book._fold(pivot, unit)
        book.levels.sort(key=lambda x: -x.touches)
        best = book.levels[0] if book.levels else None
        out[str(kind)] = {
            "levels": float(len(book.levels)),
            "touches": float(best.touches) if best else 0.0,
            "price": best.at(book.when) if best else 0.0,
            "width_vol": (book.width_vol(best) or 0.0) if best else 0.0,
        }
    return out


# ==========================================================================
# the Bjorgum zones
# ==========================================================================

LEFT = 20
RIGHT = 15

#: Zones tracked per side. The script's `nPiv`, and **4, not 10** - it is the
#: array size, so the fifth pivot high evicts the first.
N_PIVOTS = 4

#: ATR window for the band. The script's `atrLen`.
ATR_LEN = 30

#: Band width as a multiple of ATR, from box bottom to box top - so each side
#: gets half, which is what the script's trailing `/2` does.
#:
#: **0.5, and the harness agrees** (`research/harness/bjorgum.py`). An earlier
#: note here claimed the script used 0.015 and that the harness had widened it;
#: reading the source, 0.5 is the script's own default and 0.015 belonged to a
#: different lab. The Pine source is not in this tree, so that half rests on a
#: reading nobody here can repeat - the harness half is checkable. The
#: correction is recorded rather than quietly fixed, because the wrong version
#: of it was the basis for a `PINE_MULT` constant that no longer exists.
MULT = 0.5

#: Ceiling on the band as a percentage of price - the script's `per`. Some
#: assets are too volatile at low prices and produce an unreasonable zone.
MAX_PERCENT = 5.0

#: Bars a visit is judged over. The harness's, not the script's: the script
#: draws and alerts, and never scores an outcome.
FORWARD = 60

#: A touch, in ATR from the level. Not entering a band whose size is the thing
#: being tested - see `Zone.near`, which makes the argument in place.
TOUCH_ATR = 0.25

#: A break, in ATR beyond the level on the far side.
BREAK_ATR = 1.0

#: The harness's settings, which every number in `bjorgum.md` was measured on.
#: Reachable as `BjorgumLevels.measured()`.
MEASURED = {"left": 5, "right": 5, "atr_len": 14, "keep": 10, "pivots": "high_low"}


class PivotSource(StrEnum):
    """Where a pivot price is taken from. The script's `src`, all three.

    The default is **Heikin-Ashi**, which is worth knowing because it is not
    the obvious choice and the script's own tooltip says why: it "tracks the
    highest and lowest bodies of HA candles to average price action, which can
    result in a level that sits in the overlap of support and resistance". An
    HA body is already an average of four prices, so a level drawn on it is
    deliberately smoother than one drawn on a wick.
    """

    #: Heikin-Ashi body extremes. The script's default.
    HA = "ha"
    #: Raw wick extremes: `high` for a resistance pivot, `low` for support.
    #: Truer to where price actually reached, and the harness's choice.
    HIGH_LOW = "high_low"
    #: Ordinary body extremes: `max(open, close)` and `min(open, close)`. A
    #: level at the body ignores the wick that overshot it, which is the right
    #: reading if a level is where the auction *settled* rather than where it
    #: reached - and on an instrument whose round trip is a whole bar range,
    #: the exotics measured at 0.40 to 0.97 of one, the wick is partly spread.
    HIGH_LOW_BODY = "high_low_body"


class Detect(StrEnum):
    """Which feed drives visit and role detection."""

    #: One test per closed bar, which is what the study measured.
    BARS = "bars"
    #: One test per tick. Finer, and **not the same measurement**: a visit
    #: lasting three ticks inside the band is one visit either way, but a bar
    #: that dips into the band and back out within itself is invisible to
    #: `BARS` and is a visit to `TICKS`. Every rate in `bjorgum.md` is a
    #: `BARS` rate, so a `TICKS` rate is not comparable with any of them.
    #:
    #: Zones are still built from bars whichever this is - a pivot needs bars
    #: either side of it and an ATR needs a range - so `TICKS` means *bars
    #: build, ticks detect*, and both feeds are correct on one instance. That
    #: is the one documented exception to the one-feed rule `bars.check_feed`
    #: enforces, which is why `BjorgumLevels` calls it with the source this
    #: setting names rather than with a literal.
    TICKS = "ticks"


@dataclass(slots=True)
class Visit:
    """One separate visit to a zone, and how it resolved.

    `broke_edge` and `broke_atr` are both None while the visit is still open or
    still inside its `FORWARD` window - **not False**. A visit whose outcome is
    not yet known is
    not a visit that held, and recording it as one is how a hold rate becomes a
    measurement of how often the window ran out.
    """

    #: Bar count at which the visit started, and the unix seconds.
    started: int
    when: float
    #: Which side price arrived from.
    from_above: bool
    #: Resolved by the band's far edge, and by ATR from the level.
    broke_edge: bool | None = None
    broke_atr: bool | None = None
    #: The visit number this was for its zone, counting from 1.
    number: int = 0


@dataclass(slots=True)
class Zone:
    """One ATR-banded level at a confirmed pivot, with its history."""

    top: float
    bottom: float
    #: The pivot price the band was drawn around, and the ATR there.
    level: float
    atr: float
    #: Bar count and unix seconds of the pivot.
    at: int
    when: float
    #: Drawn as resistance (from a pivot high) or support (from a pivot low).
    resistance: bool
    #: Which side price is on now, and how many times that has changed.
    above: bool = False
    breaks: int = 0
    visits: list[Visit] = field(default_factory=list)
    _inside: bool = False

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def width(self) -> float:
        """`(top - bottom) / mid`. The feature that measured strongest, and
        half of what it first appeared to be.

        `bjorgum.md` in research/docs: width read 0.7602 against a 0.5417
        control, the strongest of the five, and about half of that was the
        label seeing the width rather than the width predicting anything. It
        is real at half the size first reported, which is why `near` exists -
        a touch test that entered through the band would be measuring the
        feature under test.
        """
        return (self.top - self.bottom) / self.mid if self.mid else 0.0

    @property
    def flipped(self) -> bool:
        """Its original role and its current one disagree.

        A 15m effect that does not survive to 4h. Reported, not trusted.
        """
        return self.resistance != (not self.above)

    @property
    def fresh(self) -> bool:
        """Never visited. **A break signal, not a hold signal.**"""
        return not self.visits

    @property
    def tested(self) -> int:
        """How many separate visits this zone has had."""
        return len(self.visits)

    @property
    def proven(self) -> bool:
        """Three to five prior visits: the best cell on the book at 4h."""
        return 3 <= self.tested <= 5

    def holds(self, high: float, low: float) -> bool:
        """Is a bar's range inside the band at all?"""
        return high >= self.bottom and low <= self.top

    def near(self, high: float, low: float) -> bool:
        """Is a bar within `TOUCH_ATR` of the **level**, band aside?

        The width-free touch test. Used for `broke_atr`, so that which visits
        exist does not depend on how wide the band happens to be.
        """
        if self.atr <= 0.0:
            return False
        reach = TOUCH_ATR * self.atr
        return high >= self.level - reach and low <= self.level + reach

    def age(self, bars: int) -> int:
        """Bars since the pivot."""
        return max(0, bars - self.at)


def band(
    level: float,
    atr_now: float,
    *,
    mult: float = MULT,
    max_percent: float = MAX_PERCENT,
) -> tuple[float, float] | None:
    """`(top, bottom)` around `level`, or None if there is no usable ATR.

    The ceiling is on the **whole** width as a percentage of price, halved for
    each side, exactly as the harness does it.

    `mult` and `max_percent` are arguments rather than the module constants
    they default to. They were the constants, and the instance's settings were
    stored and never read - so a band built with `mult=0.015` came out
    identical to one built with `mult=0.5`, a parameter that existed, was
    accepted, and did nothing. It was caught by printing the two widths side by
    side; the test that did so did not survive the port, and nothing in
    `tests/` exercises `band`, `mult` or `max_percent` today.
    """
    if not math.isfinite(atr_now) or atr_now <= 0.0:
        return None
    half = min(atr_now * mult, abs(level) * max_percent / 100.0) / 2.0
    if half <= 0.0:
        return None
    return level + half, level - half


def merge(zones: list[Zone], *, keep: int = N_PIVOTS) -> list[Zone]:
    """Fold overlapping same-side zones. One level found twice is not two.

    Newest first, so the surviving zone is the most recent statement of where
    the level is - and the older one's `breaks` are carried, because the role
    changes happened whether or not the band that recorded them survived.
    """
    kept: list[Zone] = []
    for zone in sorted(zones, key=lambda z: z.at, reverse=True):
        hit = next(
            (
                o
                for o in kept
                if o.resistance == zone.resistance and zone.bottom <= o.top and zone.top >= o.bottom
            ),
            None,
        )
        if hit is not None:
            hit.top = max(hit.top, zone.top)
            hit.bottom = min(hit.bottom, zone.bottom)
            hit.breaks += zone.breaks
            hit.visits.extend(zone.visits)
            continue
        kept.append(zone)
    resistance = [z for z in kept if z.resistance][:keep]
    support = [z for z in kept if not z.resistance][:keep]
    return resistance + support


class BjorgumLevels(Indicator):
    """Bjorgum key levels, one bar at a time.

    Registered with `Actor.register_indicator_for_bars` or the identical method
    on `Strategy`.

    **The role and visit counting is incremental here, and is a batch pass in
    the harness.** `research/harness/bjorgum.py` builds a zone and then walks
    `close[index:]` to count its role changes, which is correct for computing
    features over stored history and is lookahead on a live feed. This updates
    each zone from the bar in hand, so `breaks`, `visits` and `flipped` are
    always as of now - the same numbers the harness would have had at that bar,
    arrived at without seeing past it.
    """

    @classmethod
    def measured(cls, **kwargs: Any) -> BjorgumLevels:
        """The harness's settings, which every number in `bjorgum.md` is on.

        `research/harness/bjorgum.py` ran at a symmetric 5/5 pivot, an ATR of
        14, ten zones a side and raw high/low pivots. The script's defaults -
        which this class now carries - are 20/15, an ATR of 30, four zones a
        side and Heikin-Ashi bodies.

        Both reachable, neither a silent default: `BjorgumLevels()` is the
        script and `BjorgumLevels.measured()` reproduces the study. Mixing them
        gives numbers belonging to neither, which is how a figure ends up
        quoted for a configuration it was never run on.
        """
        for key, value in MEASURED.items():
            kwargs.setdefault(key, value)
        return cls(**kwargs)

    def __init__(
        self,
        *,
        left: int = LEFT,
        right: int = RIGHT,
        atr_len: int = ATR_LEN,
        mult: float = MULT,
        max_percent: float = MAX_PERCENT,
        keep: int = N_PIVOTS,
        forward: int = FORWARD,
        pivots: PivotSource | str = PivotSource.HA,
        detect: Detect | str = Detect.BARS,
    ) -> None:
        if left < 1 or right < 1:
            raise ValueError(
                f"left={left} and right={right} must both be at least 1: with "
                f"no bars either side every bar is a pivot."
            )
        if atr_len < 2:
            raise ValueError(f"atr_len={atr_len} is not an average.")
        self.pivots = PivotSource(pivots)
        self.detect = Detect(detect)
        super().__init__(
            [left, right, atr_len, mult, max_percent, keep, forward, self.pivots, self.detect]
        )
        self.left = int(left)
        self.right = int(right)
        self.atr_len = int(atr_len)
        self.mult = float(mult)
        self.max_percent = float(max_percent)
        self.keep = int(keep)
        self.forward = int(forward)
        self._fed = ""
        self._window: deque[tuple[float, float, float, float]] = deque(
            maxlen=self.left + self.right + 1
        )
        #: `min(atr * mult, close * max_percent / 100)` per bar, so the band
        #: can be read at the pivot bar rather than at the bar that confirmed
        #: it. The script writes that as `[right]` on the whole expression;
        #: without it a zone's width would be set by volatility `right` bars
        #: after the swing it describes.
        self._spans: deque[float] = deque(maxlen=self.right + 1)
        self._ranges: deque[float] = deque(maxlen=self.atr_len)
        self._prev_close: float | None = None
        #: Heikin-Ashi carries its own open, recursively.
        self._ha_open: float | None = None
        self._ha_close: float | None = None
        self.bars = 0
        self.when = 0.0
        self.close = 0.0
        self.atr = 0.0
        self.zones: list[Zone] = []
        self._seen: set[int] = set()

    # ------------------------------------------------------------- the engine

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. `ts_event` is the bar's close.

        Order matters: existing zones are updated from this bar **before** a new
        pivot is drawn from it. A zone created now has not been visited by the
        bar that created it, and updating after would record a visit to a band
        the bar itself defined.
        """
        check_feed(self, "bars")
        high, low, close = float(bar.high), float(bar.low), float(bar.close)
        self.when = bar.ts_event / NANOS
        self.close = close
        self.bars += 1
        self._set_has_inputs(True)
        self._advance_atr(high, low, close)
        self._spans.append(
            min(self.atr * self.mult, abs(close) * self.max_percent / 100.0)
            if self.atr > 0.0
            else 0.0
        )
        self._window.append(self._pivot_prices(bar))
        if self.detect is Detect.BARS:
            self._detect(high, low, close)
        self._draw()
        self.zones = merge(self.zones, keep=self.keep)
        if not self.initialized and self.zones:
            self._set_initialized(True)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a bar."""
        self._window.clear()
        self._ranges.clear()
        self._spans.clear()
        self._prev_close = None
        self._ha_open = None
        self._ha_close = None
        self.bars = 0
        self.when = 0.0
        self.close = 0.0
        self.atr = 0.0
        self.zones = []
        self._seen.clear()
        self._fed = ""
        self._set_has_inputs(False)
        self._set_initialized(False)

    def _advance_atr(self, high: float, low: float, close: float) -> None:
        """True range into a simple average, as the harness computes it."""
        prior = self._prev_close if self._prev_close is not None else close
        self._ranges.append(
            max(high - low, abs(high - prior), abs(low - prior)),
        )
        self._prev_close = close
        self.atr = (
            sum(self._ranges) / len(self._ranges) if len(self._ranges) == self.atr_len else 0.0
        )

    def _draw(self) -> None:
        """A zone at the pivot this bar just confirmed, if there is one.

        The pivot sits `right` bars back, so it is confirmed by the bar in
        hand - which is what makes a level here one that could have been drawn
        at the time, and what makes it `right` bars late.

        The band comes from the span recorded **at the pivot bar**, not the
        current one. The script does that with a `[right]` offset on the whole
        `min(atr * mult, perc)` expression, and it matters: a volatility spike
        in the fifteen bars after a swing would otherwise widen the zone that
        swing produced.
        """
        if len(self._window) < self._window.maxlen or len(self._spans) <= self.right:
            return
        centre = self.left
        high, low, _, when = self._window[centre]
        others = [w for i, w in enumerate(self._window) if i != centre]
        at = self.bars - self.right
        if at in self._seen:
            return
        span = self._spans[0]
        if span <= 0.0:
            return
        half = span / 2.0
        for resistance, level, wins in (
            (True, high, all(w[0] < high for w in others)),
            (False, low, all(w[1] > low for w in others)),
        ):
            if not wins:
                continue
            self._seen.add(at)
            self.zones.append(
                Zone(
                    top=level + half,
                    bottom=level - half,
                    level=level,
                    atr=self.atr,
                    at=at,
                    when=when,
                    resistance=resistance,
                    # **From the pivot type, not from the current close.** The
                    # script seeds `highBull` false for a pivot high and
                    # `lowsBull` true for a pivot low, so a zone starts in the
                    # role its own pivot gave it and `flipped` measures a
                    # change from that. Seeding it from where price happens to
                    # be would make a zone drawn below price already flipped.
                    above=not resistance,
                )
            )

    def handle_quote_tick(self, tick: Any) -> None:
        """Detection on the **mid**, when `detect` is `TICKS`.

        Zones are still built from bars - a pivot needs bars either side and an
        ATR needs a range - so this does not call `check_feed`: bars build and
        ticks detect, and both feeds on one instance is the design rather than
        the mistake the other detectors guard against.

        Ignored under `Detect.BARS`, so a stray subscription cannot
        double-count visits.
        """
        bid = getattr(tick, "bid_price", None)
        ask = getattr(tick, "ask_price", None)
        if bid is None or ask is None:
            return
        self._on_tick((float(bid) + float(ask)) / 2.0, tick.ts_event)

    def handle_trade_tick(self, tick: Any) -> None:
        """Detection on the traded price, when `detect` is `TICKS`."""
        price = getattr(tick, "price", None)
        if price is not None:
            self._on_tick(float(price), tick.ts_event)

    def _on_tick(self, price: float, ts_event: int) -> None:
        if self.detect is not Detect.TICKS:
            return
        self.when = ts_event / NANOS
        self.close = price
        self._set_has_inputs(True)
        # A tick has no range, so its high and low are the print itself.
        self._detect(price, price, price)

    def _pivot_prices(self, bar: Bar) -> tuple[float, float, float, float]:
        """The `(high, low, close, when)` a pivot is judged on.

        Three sources, the script's `src`, and the default is Heikin-Ashi:

            srcHigh = haSrc ? hiHaBod : hiLoSrc ? high : hiBod

        An HA body is an average of the bar's four prices and of the previous
        HA bar, so a level drawn on it sits where price action *averaged*
        rather than where it reached - the script's own tooltip says this can
        put a level "in the overlap of support and resistance", which is the
        intent and not a defect.
        """
        open_, close = float(bar.open), float(bar.close)
        if self.pivots is PivotSource.HIGH_LOW:
            return float(bar.high), float(bar.low), close, self.when
        if self.pivots is PivotSource.HIGH_LOW_BODY:
            return max(open_, close), min(open_, close), close, self.when
        ha_close = (open_ + float(bar.high) + float(bar.low) + close) / 4.0
        ha_open = (
            (open_ + close) / 2.0
            if self._ha_open is None
            else (self._ha_open + (self._ha_close or ha_close)) / 2.0
        )
        self._ha_open, self._ha_close = ha_open, ha_close
        return max(ha_open, ha_close), min(ha_open, ha_close), close, self.when

    def _detect(self, high: float, low: float, close: float) -> None:
        """Roles, visits and outcomes for every zone, from this bar."""
        for zone in self.zones:
            if close > zone.top and not zone.above:
                zone.above, zone.breaks = True, zone.breaks + 1
            elif close < zone.bottom and zone.above:
                zone.above, zone.breaks = False, zone.breaks + 1
            # Separate visits: a run of bars inside counts once.
            inside = zone.holds(high, low)
            if inside and not zone._inside:
                zone._inside = True
                zone.visits.append(
                    Visit(
                        started=self.bars,
                        when=self.when,
                        from_above=(self._prev_close or close) > zone.top,
                        number=len(zone.visits) + 1,
                    )
                )
            elif not inside and zone._inside:
                zone._inside = False
            self._resolve(zone, close)

    def _resolve(self, zone: Zone, close: float) -> None:
        """Score any visit still open, on both labels."""
        for visit in zone.visits:
            if self.bars - visit.started > self.forward:
                # The window ran out with no break. Held on both labels.
                if visit.broke_edge is None:
                    visit.broke_edge = False
                if visit.broke_atr is None:
                    visit.broke_atr = False
                continue
            if visit.broke_edge is None:
                through = close < zone.bottom if visit.from_above else close > zone.top
                if through:
                    visit.broke_edge = True
            if visit.broke_atr is None and zone.atr > 0.0:
                reach = BREAK_ATR * zone.atr
                beyond = (
                    close < zone.level - reach if visit.from_above else close > zone.level + reach
                )
                if beyond:
                    visit.broke_atr = True

    # ------------------------------------------------------------ the reading

    @property
    def count(self) -> int:
        return len(self.zones)

    @property
    def resistance(self) -> list[Zone]:
        return [z for z in self.zones if z.resistance]

    @property
    def support(self) -> list[Zone]:
        return [z for z in self.zones if not z.resistance]

    def above(self, price: float | None = None) -> Zone | None:
        """The nearest zone entirely above `price`."""
        here = self.close if price is None else price
        found = [z for z in self.zones if z.bottom > here]
        return min(found, key=lambda z: z.bottom - here) if found else None

    def below(self, price: float | None = None) -> Zone | None:
        """The nearest zone entirely below `price`."""
        here = self.close if price is None else price
        found = [z for z in self.zones if z.top < here]
        return max(found, key=lambda z: z.top - here) if found else None

    def holding(self, price: float | None = None) -> Zone | None:
        """The zone whose band contains `price`, if any."""
        here = self.close if price is None else price
        for zone in self.zones:
            if zone.bottom <= here <= zone.top:
                return zone
        return None

    def break_rate(self, *, atr_label: bool = True) -> float | None:
        """Resolved visits that broke, over resolved visits. None if none.

        `atr_label` picks the width-free label and defaults to True, because
        the other one halved when the width came out of it. Unresolved visits
        are excluded from both ends rather than counted as holds.
        """
        resolved = [
            (v.broke_atr if atr_label else v.broke_edge)
            for z in self.zones
            for v in z.visits
            if (v.broke_atr if atr_label else v.broke_edge) is not None
        ]
        if not resolved:
            return None
        return sum(1 for x in resolved if x) / len(resolved)

    @property
    def fresh(self) -> list[Zone]:
        """Never-visited zones. **These are the ones most likely to break.**"""
        return [z for z in self.zones if z.fresh]

    @property
    def proven(self) -> list[Zone]:
        """Zones with three to five visits: the best cell measured at 4h."""
        return [z for z in self.zones if z.proven]

    def features(self, zone: Zone | None) -> dict[str, float]:
        """The study's features for one zone, or `{}`.

        Absent rather than zeroed when there is no zone: a zero in the `width`
        column would read later as "the zone had no width", which is the
        opposite of "there was no zone".
        """
        if zone is None:
            return {}
        return {
            "bjorgum_width": round(zone.width, 6),
            "bjorgum_visits": float(zone.tested),
            "bjorgum_fresh": float(zone.fresh),
            "bjorgum_flipped": float(zone.flipped),
            "bjorgum_crossings": float(zone.breaks),
            "bjorgum_age": float(zone.age(self.bars)),
            "bjorgum_distance_atr": (
                round((self.close - zone.level) / zone.atr, 4) if zone.atr > 0 else 0.0
            ),
        }


# ==========================================================================
# the pips skeleton
# ==========================================================================

DEFAULT_CONFIRM = 3

#: Below four points there is nothing to select - the endpoints are the series.
MIN_POINTS = 4

#: Points asked for by the indicator. Enough for a structure sequence, few
#: enough that the selection is doing work.
DEFAULT_COUNT = 12

#: Bars the indicator keeps. The window is the whole input to the selection,
#: so it sets what "globally important" means.
DEFAULT_SPAN = 240


class Swing(StrEnum):
    HIGH = "high"
    LOW = "low"
    #: An endpoint, or a point on a straight run. Carries no level information,
    #: which is why `Point.is_turn` excludes it.
    EDGE = "edge"


class Structure(StrEnum):
    """Relative position of a swing against the previous swing of the same kind."""

    HIGHER_HIGH = "HH"
    LOWER_HIGH = "LH"
    HIGHER_LOW = "HL"
    LOWER_LOW = "LL"


@dataclass(frozen=True, slots=True)
class Point(Restorable):
    """One perceptually important point."""

    index: int
    time: int
    price: float
    swing: Swing
    #: How far this point sat from the line joining its neighbours, in basis
    #: points of price. The selection criterion, kept because it is also the
    #: best single measure of how pronounced the swing was.
    prominence_bps: float
    #: When this became knowable, or `inf` while it still is not.
    #:
    #: Infinity rather than "the end of the window" matters more than it looks:
    #: clamping would let a swing one bar from the edge claim to be settled
    #: after one bar instead of `confirm`, and those trailing swings are
    #: precisely the ones that have not earned it yet. Every look-ahead bug in
    #: this file would live in that clamp.
    confirmed: float
    #: Relative to the previous swing of the same kind. Wired in by
    #: `structure()`, and left empty for the first high/low in a sequence.
    structure: Structure | None = None

    @property
    def is_turn(self) -> bool:
        return self.swing is not Swing.EDGE


def _vertical_gap(prices: Sequence[float], left: int, right: int, i: int) -> float:
    """How far `prices[i]` is from the chord between `left` and `right`."""
    span = right - left
    if span <= 0:
        return 0.0
    slope = (prices[right] - prices[left]) / span
    expected = prices[left] + slope * (i - left)
    return abs(prices[i] - expected)


def extract(prices: Sequence[float], count: int) -> list[int]:
    """The `count` most important indices, in order. Endpoints are always in.

    The classic algorithm: start with both ends, then repeatedly add whichever
    remaining point is furthest from the line joining its two current
    neighbours, until there are enough.
    """
    n = len(prices)
    if n <= 2 or count <= 2:
        return list(range(n)) if n <= 2 else [0, n - 1]

    kept = [0, n - 1]
    while len(kept) < min(count, n):
        best_gap, best_index, best_slot = 0.0, -1, -1
        for slot in range(len(kept) - 1):
            left, right = kept[slot], kept[slot + 1]
            for i in range(left + 1, right):
                gap = _vertical_gap(prices, left, right, i)
                if gap > best_gap:
                    best_gap, best_index, best_slot = gap, i, slot
        if best_index < 0:
            break  # a perfectly straight run: nothing left worth keeping
        kept.insert(best_slot + 1, best_index)
    return kept


def _classify(prices: Sequence[float], kept: Sequence[int], slot: int) -> Swing:
    """High, low, or neither, judged against the adjacent kept points."""
    if slot == 0 or slot == len(kept) - 1:
        return Swing.EDGE
    here = prices[kept[slot]]
    before, after = prices[kept[slot - 1]], prices[kept[slot + 1]]
    if here > before and here > after:
        return Swing.HIGH
    if here < before and here < after:
        return Swing.LOW
    return Swing.EDGE


def points(
    times: Sequence[int],
    prices: Sequence[float],
    count: int,
    *,
    confirm: int = DEFAULT_CONFIRM,
) -> list[Point]:
    """PIPs with their swing type, prominence and confirmation time.

    `prices` is normally the close series. Highs and lows can be passed instead
    when wicks matter, but mixing them within one call would compare points
    that never coexisted.
    """
    if len(times) != len(prices):
        raise ValueError("times and prices must be the same length")
    if len(prices) < MIN_POINTS:
        return []

    kept = extract(prices, count)
    last = len(prices) - 1
    found: list[Point] = []
    for slot, index in enumerate(kept):
        swing = _classify(prices, kept, slot)
        left = kept[slot - 1] if slot > 0 else index
        right = kept[slot + 1] if slot < len(kept) - 1 else index
        gap = _vertical_gap(prices, left, right, index) if left != right else 0.0
        price = prices[index]
        # Confirmation is a *bar* offset, so a gap in the series (a weekend)
        # does not make a swing look confirmed sooner than it was. A swing
        # without `confirm` bars after it yet is not confirmed at all.
        if swing is Swing.EDGE:
            settled: float = times[index]
        elif index + confirm <= last:
            settled = times[index + confirm]
        else:
            settled = math.inf
        found.append(
            Point(
                index=index,
                time=times[index],
                price=price,
                swing=swing,
                prominence_bps=(gap / price * 10_000) if price else 0.0,
                confirmed=max(float(times[index]), settled),
            )
        )
    return found


def extremes(
    times: Sequence[int],
    highs: Sequence[float],
    lows: Sequence[float],
    count: int,
    *,
    confirm: int = DEFAULT_CONFIRM,
) -> list[Point]:
    """Swing highs from the highs and swing lows from the lows.

    See `structures-drawing-pips.md` in research/docs.
    """
    if len(times) != len(highs) or len(times) != len(lows):
        raise ValueError("times, highs and lows must be the same length")
    peaks = [p for p in points(times, highs, count, confirm=confirm) if p.swing is Swing.HIGH]
    troughs = [p for p in points(times, lows, count, confirm=confirm) if p.swing is Swing.LOW]
    return sorted(peaks + troughs, key=lambda point: point.index)


def as_of(found: Sequence[Point], when: float) -> list[Point]:
    """Only the points that were knowable at `when`.

    The whole reason `confirmed` exists. Filtering on `time` instead would
    include swings that had not yet happened as far as anyone watching could
    tell, which is the difference between a backtest and a fiction.
    """
    # Trailing swings carry `inf` until enough bars follow them, so they fall
    # out here without needing a special case.
    return [point for point in found if point.confirmed <= when]


def turns(found: Sequence[Point]) -> list[Point]:
    """Just the highs and lows - the points a level can be drawn at."""
    return [point for point in found if point.is_turn]


def structure(turns: Sequence[Point]) -> list[tuple[Point, Structure | None]]:
    """Label consecutive swing highs and lows as HH, LH, HL or LL.

    A swing high is compared with the previous swing high, and a swing low with
    the previous swing low. The first high or low in a sequence has no prior
    comparison and is returned with `None`.

    The returned point is a shallow copy with its `structure` field set, so the
    structure is part of the turn sequence once it is wired into the pipeline.
    """
    found: list[tuple[Point, Structure | None]] = []
    last_high: Point | None = None
    last_low: Point | None = None
    for point in turns:
        label: Structure | None
        if point.swing is Swing.HIGH:
            if last_high is None:
                label = None
            else:
                label = (
                    Structure.HIGHER_HIGH if point.price > last_high.price else Structure.LOWER_HIGH
                )
            last_high = point
        elif point.swing is Swing.LOW:
            if last_low is None:
                label = None
            else:
                label = (
                    Structure.HIGHER_LOW if point.price > last_low.price else Structure.LOWER_LOW
                )
            last_low = point
        else:
            label = None
        updated = replace(point, structure=label)
        found.append((updated, label))
    return found


class Pips(Indicator):
    """PIPs over a rolling window, with only the confirmed ones published.

    Registered with `Actor.register_indicator_for_bars` or the identical method
    on `Strategy`.

    **`points` is `as_of` the last bar, not the raw selection.** The selection
    always includes both endpoints and a trailing swing is always a candidate,
    so the raw list contains points that are not yet knowable - that is the
    algorithm working, not a fault. Publishing them is the lookahead this
    module exists to prevent, so the property filters and `provisional` says
    how many were held back.

    The window is recomputed per bar. `extract` is O(span x count), which at
    the defaults is a few thousand operations - the selection is global, so
    there is no incremental form that gives the same answer, and an
    approximation that drifted from the measured one would be worse than the
    cost. Cython is the route if it ever matters, as it is for the rest of
    this package.
    """

    def __init__(
        self,
        *,
        count: int = DEFAULT_COUNT,
        span: int = DEFAULT_SPAN,
        confirm: int = DEFAULT_CONFIRM,
        wicks: bool = False,
    ) -> None:
        if count < MIN_POINTS:
            raise ValueError(
                f"count={count} leaves nothing to select: below {MIN_POINTS} "
                f"the endpoints are the series."
            )
        if span <= count + confirm:
            raise ValueError(
                f"span={span} cannot hold {count} points plus {confirm} bars "
                f"of confirmation, so nothing would ever be published."
            )
        super().__init__([count, span, confirm, wicks])
        self.count = int(count)
        self.span = int(span)
        self.confirm = int(confirm)
        #: Take swing highs off the highs and lows off the lows, rather than
        #: both off the closes. Truer to where price actually turned, and the
        #: two cannot be mixed within one selection - a high and a low from the
        #: same bar never coexisted as a path.
        self.wicks = bool(wicks)
        self._fed = ""
        self._times: list[int] = []
        self._closes: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        self.when = 0.0
        self.found: list[Point] = []

    # ------------------------------------------------------------- the engine

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. `ts_event` is the bar's close."""
        check_feed(self, "bars")
        self.when = bar.ts_event / NANOS
        self._times.append(int(bar.ts_event))
        self._closes.append(float(bar.close))
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        for held in (self._times, self._closes, self._highs, self._lows):
            del held[: max(0, len(held) - self.span)]
        self._set_has_inputs(True)
        if len(self._closes) < MIN_POINTS:
            return
        if self.wicks:
            self.found = extremes(
                self._times, self._highs, self._lows, self.count, confirm=self.confirm
            )
        else:
            self.found = points(self._times, self._closes, self.count, confirm=self.confirm)
        if not self.initialized and self.points:
            self._set_initialized(True)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a bar."""
        self._times.clear()
        self._closes.clear()
        self._highs.clear()
        self._lows.clear()
        self.found = []
        self.when = 0.0
        self._fed = ""
        self._set_has_inputs(False)
        self._set_initialized(False)

    # ------------------------------------------------------------ the reading

    @property
    def points(self) -> list[Point]:
        """The points knowable as of the last bar handled."""
        return as_of(self.found, self.when * NANOS)

    @property
    def provisional(self) -> int:
        """Points the selection found that are not yet confirmed.

        Published because it is the honest measure of how much of the current
        shape is still provisional - a window whose last third is unconfirmed
        is a window whose shape may still change.
        """
        return len(self.found) - len(self.points)

    @property
    def turns(self) -> list[Point]:
        """Just the confirmed highs and lows - where a level can be drawn."""
        return turns(self.points)

    @property
    def labelled(self) -> list[Point]:
        """The confirmed turns, each labelled HH, LH, HL or LL."""
        return [point for point, _ in structure(self.turns)]

    @property
    def last_high(self) -> Point | None:
        found = [p for p in self.turns if p.swing is Swing.HIGH]
        return found[-1] if found else None

    @property
    def last_low(self) -> Point | None:
        found = [p for p in self.turns if p.swing is Swing.LOW]
        return found[-1] if found else None

    @property
    def trend(self) -> int:
        """+1 on HH and HL, -1 on LH and LL, 0 when they disagree or are absent.

        The plainest reading of a structure sequence, and the one to be most
        careful with: this desk's measured record is that **direction is
        closed** - the gate that looks for it finds a *planted* drift at
        z +2.90 and still earns only 2% of one spread there, and on the eight
        traded instruments it reads +/-0.000 with not one cell past |z| of 2
        (`statespace-directional-edge.md` in research/docs). A structure label
        is a
        description of what happened, and an entry rule built on it is a claim
        that has already been refused.
        """
        labelled = self.labelled
        highs = [p for p in labelled if p.swing is Swing.HIGH and p.structure]
        lows = [p for p in labelled if p.swing is Swing.LOW and p.structure]
        if not highs or not lows:
            return 0
        up = (
            highs[-1].structure is Structure.HIGHER_HIGH
            and lows[-1].structure is Structure.HIGHER_LOW
        )
        down = (
            highs[-1].structure is Structure.LOWER_HIGH
            and lows[-1].structure is Structure.LOWER_LOW
        )
        return 1 if up else (-1 if down else 0)

    def prominence(self) -> float:
        """Median prominence of the confirmed turns, in basis points.

        How pronounced this window's swings are, which is a volatility reading
        wearing a structure's clothes - worth remembering before reading it as
        anything else, since levels, ranges and shapes all restate volatility
        on this desk's own measurements.
        """
        got = sorted(p.prominence_bps for p in self.turns)
        if not got:
            return 0.0
        mid = len(got) // 2
        return got[mid] if len(got) % 2 else (got[mid - 1] + got[mid]) / 2.0


# ==========================================================================
# displacement and its origin
# ==========================================================================

PUSH_MIN = 2

#: A candle is impulsive when its body is at least this much of its own range.
#: The desk: *"make the body at least 70% of the total candle range"*.
PUSH_BODY = 0.70

#: Ordinary candles a leg may skip before it has ended. The desk: *"sometimes
#: we might have 2 impulsive then a candle that is not too strong then another
#: impulsive"*. Consecutive-only cannot see that shape and drops the whole
#: setup over one ordinary candle in the middle of an obvious move.
CHAIN_GAP = 1

#: Bars kept. A displacement is a local event; a long window buries the leg
#: that just happened under every older one.
SPAN = 40

#: Origins kept per leg, counted back from its end. Zone 1 is the
#: pause nearest the end, which is the one a reader marks first.
ORIGIN_KEEP = 4


@dataclass(frozen=True, slots=True)
class Candle:
    """One bar, as this module reads it. Plain floats, so the kernel is pure."""

    high: float
    low: float
    open: float
    close: float
    #: Unix seconds of the bar's close.
    when: float

    @property
    def span(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return self.close - self.open

    @property
    def sign(self) -> int:
        """+1 bullish, -1 bearish, 0 for a doji."""
        if self.close > self.open:
            return 1
        return -1 if self.close < self.open else 0

    def impulsive(self, body: float = PUSH_BODY) -> bool:
        """Body at least `body` of the range, and a direction at all."""
        if self.span <= 0.0 or self.sign == 0:
            return False
        return abs(self.body) / self.span >= body


@dataclass(frozen=True, slots=True)
class Origin:
    """The candle a leg left from.

    An **order block**, a displacement origin and a supply/demand zone are the
    same candle under three names - `delivering.md` says so in a table - and
    this package calls it the origin, because that is what it is: where the
    displacement came from.

    The band is drawn **high to low** rather than body-high, and the line sits
    where the origin closed - in a continuous market, where the first push
    candle opened. Both are the desk's later specification rather than the
    version the 82% was measured under; `order-block-zones.md` records that the
    rule moved the same evening the numbers were taken.
    """

    #: +1 for demand (an origin below, left by an up leg), -1 for supply.
    side: int
    #: The band, low first.
    low: float
    high: float
    #: Where the origin closed: the price a fade aims at.
    line: float
    #: Unix seconds of the origin candle's close.
    when: float
    #: 1 is the pause nearest the end of the leg - the one marked first.
    rank: int
    #: The leg this came from: signed size in price, and the bars it took.
    move: float
    bars: int

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0

    def holds(self, price: float) -> bool:
        """Is `price` inside the band?"""
        return self.low <= price <= self.high


@dataclass(frozen=True, slots=True)
class Leg:
    """One displacement: the impulsive chain, and where it started."""

    side: int
    #: Indices into the window: the candle before the chain, and the last
    #: impulsive candle in it.
    origin: int
    end: int
    #: Indices of the pauses inside the chain - each one is also a zone.
    pauses: tuple[int, ...]
    move: float

    @property
    def bars(self) -> int:
        return max(1, self.end - self.origin)


def _clears(here: Candle, before: Candle, side: int, strong: bool) -> bool:
    """Does `here` close past `before`, in `side`'s direction?

    The strong form asks for the whole range of the previous candle, the weak
    one only for its close. The strong form measured **worse**, which is why
    `strong` defaults to False here and the rule file's `PUSH_STRONG=1` is
    recorded as what the published numbers were taken under.
    """
    mark = (before.high if side > 0 else before.low) if strong else before.close
    return here.close > mark if side > 0 else here.close < mark


def chains(
    window: Sequence[Candle],
    *,
    push_min: int = PUSH_MIN,
    push_body: float = PUSH_BODY,
    chain_gap: int = CHAIN_GAP,
    strong: bool = False,
) -> list[Leg]:
    """Every displacement leg in `window`, oldest first.

    Chains do not overlap: once one has consumed its bars the scan resumes
    after it, so an impulsive candle is never part of two legs.

    Pure, and over a bounded window, so the indicator recomputes it per bar
    rather than carrying a state machine. That is a deliberate trade - a leg
    that extends is re-read rather than updated in place, which costs `SPAN`
    comparisons and removes a class of bug where the machine's state and the
    bars disagree.
    """
    out: list[Leg] = []
    i = 0
    n = len(window)
    while i < n:
        side = _seed(window, i, push_min, push_body, strong)
        if side == 0:
            i += 1
            continue
        end = i + push_min - 1
        pauses: list[int] = []
        while True:
            step = _extend(window, end, side, push_body, chain_gap, strong)
            if step is None:
                break
            nxt, skipped = step
            pauses.extend(skipped)
            end = nxt
        if i == 0:
            # No candle before the chain, so no origin to name.
            i = end + 1
            continue
        start, finish = window[i], window[end]
        move = (finish.high - start.low) if side > 0 else (finish.low - start.high)
        out.append(Leg(side=side, origin=i - 1, end=end, pauses=tuple(pauses), move=move))
        i = end + 1
    return out


def _seed(window: Sequence[Candle], i: int, push_min: int, push_body: float, strong: bool) -> int:
    """`side` when `push_min` impulsive candles start a chain at `i`, else 0.

    Every adjacent pair must clear, not only the first: a run that stalls in
    the middle is a push and then a pause.
    """
    if i + push_min > len(window):
        return 0
    first = window[i]
    if not first.impulsive(push_body):
        return 0
    side = first.sign
    for k in range(i + 1, i + push_min):
        here = window[k]
        if not here.impulsive(push_body) or here.sign != side:
            return 0
        if not _clears(here, window[k - 1], side, strong):
            return 0
    return side


def _extend(
    window: Sequence[Candle],
    end: int,
    side: int,
    push_body: float,
    chain_gap: int,
    strong: bool,
) -> tuple[int, list[int]] | None:
    """The next impulsive candle after `end`, and the pauses skipped to reach it.

    None when the leg has ended: no impulsive candle of the right colour within
    `chain_gap` ordinary ones.
    """
    for gap in range(chain_gap + 1):
        k = end + 1 + gap
        if k >= len(window):
            return None
        here = window[k]
        if (
            here.impulsive(push_body)
            and here.sign == side
            and _clears(here, window[end], side, strong)
        ):
            return k, list(range(end + 1, k))
    return None


def origins_of(window: Sequence[Candle], leg: Leg, *, keep: int = ORIGIN_KEEP) -> list[Origin]:
    """The origins a leg leaves: every pause inside it, plus the candle before it.

    Ranked from the end of the leg backwards, so rank 1 is the pause nearest
    the end. The candle before the chain always ranks last - it is the furthest
    from where price is now, which is also why it is the one a fade aims at
    when the nearer pauses have already been taken.
    """
    marks = [*sorted(leg.pauses, reverse=True), leg.origin]
    out: list[Origin] = []
    for rank, index in enumerate(marks, start=1):
        if keep and rank > keep:
            break
        candle = window[index]
        out.append(
            Origin(
                side=leg.side,
                low=candle.low,
                high=candle.high,
                line=candle.close,
                when=candle.when,
                rank=rank,
                move=leg.move,
                bars=leg.bars,
            )
        )
    return out


class Displacement(Indicator):
    """Displacement legs and the origins they left from, one bar at a time.

    Registered with `Actor.register_indicator_for_bars` or the identical method
    on `Strategy`. `source` and the unit are read the same way as every other
    indicator here, through `bars.bar_input`, so `size_vol` means the same
    thing on gold as on EURUSD.
    """

    def __init__(
        self,
        *,
        span: int = SPAN,
        push_min: int = PUSH_MIN,
        push_body: float = PUSH_BODY,
        chain_gap: int = CHAIN_GAP,
        strong: bool = False,
        keep: int = ORIGIN_KEEP,
        source: Reading = Reading.CLOSE,
        unit: float = 0.0,
        unit_from: Reading | None = Reading.RANGE,
        unit_span: int = 0,
    ) -> None:
        check_scale(type(self).__name__, source, unit, unit_from)
        if push_min < 2:
            raise ValueError(
                f"push_min={push_min} is not a displacement: a single candle "
                f"with a 70% body is an ordinary strong candle, and the rule "
                f"as the desk gave it asks for at least two."
            )
        super().__init__([span, push_min, push_body, chain_gap, strong])
        self.span = int(span)
        self.push_min = int(push_min)
        self.push_body = float(push_body)
        self.chain_gap = int(chain_gap)
        self.strong = bool(strong)
        self.keep = int(keep)
        self.source = source
        self.unit = float(unit)
        self.unit_from = unit_from
        self.unit_span = int(unit_span)
        self._bar_prev: float | None = None
        self._bar_scale = 0.0
        self._window: deque[Candle] = deque(maxlen=self.span)
        self.legs: list[Leg] = []
        self.origins: list[Origin] = []

    # ------------------------------------------------------------- the engine

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. `ts_event` is the bar's close."""
        bar_input(self, bar)
        self._window.append(
            Candle(
                high=float(bar.high),
                low=float(bar.low),
                open=float(bar.open),
                close=float(bar.close),
                when=bar.ts_event / NANOS,
            )
        )
        self._set_has_inputs(True)
        self._recompute()
        if not self.initialized and len(self._window) >= self.push_min + 1:
            self._set_initialized(True)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a bar."""
        self._window.clear()
        self.legs = []
        self.origins = []
        self._bar_prev = None
        self._bar_scale = 0.0
        self._set_has_inputs(False)
        self._set_initialized(False)

    def _recompute(self) -> None:
        window = list(self._window)
        self.legs = chains(
            window,
            push_min=self.push_min,
            push_body=self.push_body,
            chain_gap=self.chain_gap,
            strong=self.strong,
        )
        found: list[Origin] = []
        for leg in self.legs:
            found.extend(origins_of(window, leg, keep=self.keep))
        # Newest leg first, then rank, so `origins[0]` is the nearest one of
        # the most recent displacement.
        found.sort(key=lambda b: (-b.when, b.rank))
        self.origins = found

    # -------------------------------------------------------------- the reading

    @property
    def leg(self) -> Leg | None:
        """The most recent displacement, or None."""
        return self.legs[-1] if self.legs else None

    @property
    def origin(self) -> Origin | None:
        """The origin of the most recent leg: the price a fade aims at.

        The *candle before the chain* - rank last, furthest from price. Not an
        entry signal: see the table in `delivering.md` in research/docs, which
        `Origin` quotes.
        """
        if not self.legs:
            return None
        window = list(self._window)
        marks = origins_of(window, self.legs[-1], keep=0)
        return marks[-1] if marks else None

    @property
    def side(self) -> int:
        """+1 when the last leg was up, -1 down, 0 when there is none."""
        leg = self.leg
        return leg.side if leg is not None else 0

    @property
    def size_vol(self) -> float:
        """The last leg's signed size in volatility units, 0.0 without a scale.

        Reported apart from `bars` because they are different claims: four
        units over four bars is a run, four over forty is a drift.
        """
        leg = self.leg
        if leg is None or self._bar_scale <= 0.0:
            return 0.0
        return leg.move / self._bar_scale

    @property
    def bars(self) -> int:
        """How many bars the last leg took."""
        leg = self.leg
        return leg.bars if leg is not None else 0

    def toward(self, price: float, side: int) -> Origin | None:
        """The nearest origin entirely above (`side` +1) or below (-1) `price`.

        `side` is **where to look**, not the direction of a trade: a fade that
        is selling wants the origin above it and asks for `+1`. Naming it for
        the trade instead reads the same at the call site and means the
        opposite, which is worth a sentence here rather than a reversed target
        in production.

        An origin price is already inside is neither above nor below it, so it is
        excluded by the comparison and there is nothing extra to check.
        """
        out = [b for b in self.origins if (b.low > price if side > 0 else b.high < price)]
        if not out:
            return None
        return min(out, key=lambda b: abs(b.line - price))


# ==========================================================================
# the gaps
# ==========================================================================

GAP_SPAN = 2

#: The least a gap must span, in volatility units, before it counts. Without a
#: floor every rounding tick between two bars is an "imbalance" and the count
#: becomes a measure of the tick size.
MIN_GAP_VOL = 0.10

#: Filled gaps kept, newest first. Only a rate needs them, and a rate does not
#: need all of history.
KEEP_FILLED = 64


@dataclass(slots=True)
class Gap:
    """One imbalance: the band, when it opened, and when it closed.

    Mutable, unlike the batch `Imbalance` below, because the whole point here
    is that a gap
    has a life: it opens, it is live for a while, and it may close. An
    immutable one would have to be replaced to record its own fill, and the
    replacement is where a list of "open gaps" quietly becomes a list of "gaps
    that were never going to fill".
    """

    #: +1 when the gap points up - price left a hole below it, demand side.
    side: int
    #: The edges of the hole, low first.
    low: float
    high: float
    #: Unix seconds of the bar that completed the gap.
    when: float
    #: Unix seconds of the bar that first traded back into it, or None.
    filled_at: float | None = None
    #: How far into the band price has been, as a fraction of its width. 0
    #: while untouched, 1 once fully traded through.
    depth: float = 0.0

    @property
    def size(self) -> float:
        return self.high - self.low

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0

    @property
    def near(self) -> float:
        """The edge price reaches first coming back: the one to aim at."""
        return self.low if self.side > 0 else self.high

    @property
    def far(self) -> float:
        """The edge price has to clear to be past it."""
        return self.high if self.side > 0 else self.low

    @property
    def live(self) -> bool:
        return self.filled_at is None

    def touched_by(self, low: float, high: float) -> float:
        """How far a bar of `[low, high]` reached into the band, as a fraction.

        0.0 for a bar that never reached it, 1.0 for one that traded through
        the whole band. Measured from `near`, so an up gap is entered from
        below.
        """
        if self.size <= 0.0:
            return 0.0
        reach = self.high - low if self.side > 0 else high - self.low
        return max(0.0, min(1.0, reach / self.size))

    def age(self, now: float) -> float:
        """Hours since the gap formed."""
        return max(0.0, (now - self.when) / 3_600.0)


class Gaps(Indicator):
    """Fair value gaps, opened and closed one bar at a time.

    Registered with `Actor.register_indicator_for_bars` or the identical method
    on `Strategy`. The scale is read through `bars.bar_input` like every other
    indicator here, so `MIN_GAP_VOL` means the same thing on gold as on
    EURUSD - without it the floor is in price and the gap count becomes a
    measure of the instrument.
    """

    def __init__(
        self,
        *,
        span: int = GAP_SPAN,
        min_gap_vol: float = MIN_GAP_VOL,
        keep_filled: int = KEEP_FILLED,
        full_fill: bool = False,
        source: Reading = Reading.CLOSE,
        unit: float = 0.0,
        unit_from: Reading | None = Reading.RANGE,
        unit_span: int = 0,
    ) -> None:
        check_scale(type(self).__name__, source, unit, unit_from)
        if span < 1:
            raise ValueError(
                f"span={span} compares a bar with itself: a gap is between two "
                f"bars with at least one between them."
            )
        super().__init__([span, min_gap_vol, full_fill])
        self.span = int(span)
        self.min_gap_vol = float(min_gap_vol)
        self.keep_filled = int(keep_filled)
        #: Whether a gap closes on the first touch or only once price has
        #: traded through the whole band. First touch is the default because it
        #: is what "the hole is gone" means to a reader, and because the first
        #: touch is the informative one.
        self.full_fill = bool(full_fill)
        self.source = source
        self.unit = float(unit)
        self.unit_from = unit_from
        self.unit_span = int(unit_span)
        self._bar_prev: float | None = None
        self._bar_scale = 0.0
        self._recent: deque[tuple[float, float]] = deque(maxlen=self.span + 1)
        self.live: list[Gap] = []
        self.filled: deque[Gap] = deque(maxlen=self.keep_filled)
        self.opened = 0

    # ------------------------------------------------------------- the engine

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. `ts_event` is the bar's close.

        Fills are applied **before** a new gap is opened, so a bar cannot both
        complete a gap and be the bar that filled it - which it would appear to
        do if the new gap were added first and then tested against its own
        forming bar.
        """
        _, scale = bar_input(self, bar)
        high, low = float(bar.high), float(bar.low)
        when = bar.ts_event / NANOS
        self._set_has_inputs(True)
        self._apply_fills(low, high, when)
        self._open(low, high, when, scale)
        self._recent.append((high, low))
        if not self.initialized and len(self._recent) > self.span:
            self._set_initialized(True)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a bar."""
        self._recent.clear()
        self.live = []
        self.filled.clear()
        self.opened = 0
        self._bar_prev = None
        self._bar_scale = 0.0
        self._set_has_inputs(False)
        self._set_initialized(False)

    def _apply_fills(self, low: float, high: float, when: float) -> None:
        still: list[Gap] = []
        for gap in self.live:
            gap.depth = max(gap.depth, gap.touched_by(low, high))
            done = gap.depth >= 1.0 if self.full_fill else gap.depth > 0.0
            if done:
                gap.filled_at = when
                self.filled.appendleft(gap)
            else:
                still.append(gap)
        self.live = still

    def _open(self, low: float, high: float, when: float, scale: float) -> None:
        if len(self._recent) < self.span:
            return
        before_high, before_low = self._recent[-self.span]
        if low > before_high:
            side, band_low, band_high = 1, before_high, low
        elif high < before_low:
            side, band_low, band_high = -1, high, before_low
        else:
            return
        floor = self.min_gap_vol * scale if scale > 0.0 else 0.0
        if band_high - band_low <= floor:
            return
        self.live.append(Gap(side=side, low=band_low, high=band_high, when=when))
        self.opened += 1

    # ------------------------------------------------------------ the reading

    @property
    def count(self) -> int:
        """How many gaps are open."""
        return len(self.live)

    def above(self, price: float) -> Gap | None:
        """The nearest open gap entirely above `price`."""
        out = [g for g in self.live if g.low > price]
        return min(out, key=lambda g: g.low - price) if out else None

    def below(self, price: float) -> Gap | None:
        """The nearest open gap entirely below `price`."""
        out = [g for g in self.live if g.high < price]
        return max(out, key=lambda g: g.high - price) if out else None

    @property
    def fill_rate(self) -> float | None:
        """Closed over opened, or None before anything has opened.

        Counts the gaps that filled against **every** gap opened, including the
        ones still live. A rate over the closed ones alone is 1.0 by
        construction, which is the shape of the survivor bias this class was
        written to avoid.
        """
        if not self.opened:
            return None
        return min(1.0, self.filled_total / self.opened)

    @property
    def filled_total(self) -> int:
        """How many gaps have closed. Not `len(self.filled)`, which is capped."""
        return self.opened - len(self.live)


# ==========================================================================
# the batch readings
# ==========================================================================

NAN = float("nan")

#: **Both of the next two names are already bound above in this module**, at
#: the same values, and these lines rebind them - so `Displacement` and `Gaps`
#: close over the earlier pair while the batch functions below see these. They
#: agree today and a change to either half would be half-applied. Reported
#: rather than merged here, because deleting a module-level name is not a
#: documentation change.
#:
#: Bars the readings are taken over. Shorter than the regression's 100: a
#: displacement is a local event and a hundred bars of context would bury the
#: one that just happened under every older one.
SPAN = 40

#: The least a gap must span, in volatility units, before it counts. Without a
#: floor every rounding tick between two bars is an "imbalance" and the count
#: becomes a measure of the tick size.
MIN_GAP_VOL = 0.10


@dataclass(frozen=True, slots=True)
class Imbalance:
    """One three-bar imbalance, as the far side of the hole it left."""

    #: Index of the middle bar - the one that displaced.
    at: int
    #: +1 when the gap points up - the hole is below the price that left it,
    #: the demand side - and -1 down. The same sign convention as `Gap.side`.
    side: int
    #: The edges of the hole, low first.
    low: float
    high: float

    @property
    def size(self) -> float:
        return self.high - self.low

    @property
    def far(self) -> float:
        """The edge price has to clear to be past it."""
        return self.high if self.side > 0 else self.low


def gaps(bars: Sequence[Ohlc], unit: float = 0.0) -> list[Imbalance]:
    """Every three-bar imbalance in `bars`, oldest first, unfilled ones only.

    A gap is filled once any later bar trades back inside it, which is checked
    against the whole remainder of the window rather than the next bar alone:
    the question a reader asks is "is that hole still there", not "was it
    skipped once".

    `unit` of zero keeps every gap; a positive one drops those under
    `MIN_GAP_VOL`, which is how a caller with a volatility scale avoids
    counting tick noise.
    """
    out: list[Imbalance] = []
    floor = MIN_GAP_VOL * unit if unit > 0 else 0.0
    for k in range(1, len(bars) - 1):
        before, after = bars[k - 1], bars[k + 1]
        if after.low > before.high:
            low, high, side = before.high, after.low, 1
        elif after.high < before.low:
            low, high, side = after.high, before.low, -1
        else:
            continue
        if high - low <= floor:
            continue
        # Still open: nothing after the gap has traded back into it.
        rest = bars[k + 2 :]
        if side > 0 and any(b.low < high for b in rest):
            continue
        if side < 0 and any(b.high > low for b in rest):
            continue
        out.append(Imbalance(at=k, side=side, low=low, high=high))
    return out


def displacement(bars: Sequence[Ohlc]) -> tuple[float, int, int]:
    """The most recent directional leg: (signed price move, bars, bars since).

    The leg is read between the window's extremes in the order they happened -
    if the low came first the leg is up, if the high came first it is down.
    That is the plainest reading of "the move that got us here" and it needs no
    pivot definition, no lookback parameter and no tuning, which is three fewer
    things to be wrong about.

    `(nan, 0, 0)` when there are not two bars to measure between.
    """
    if len(bars) < 2:
        return NAN, 0, 0
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    hi = max(range(len(bars)), key=lambda i: highs[i])
    lo = min(range(len(bars)), key=lambda i: lows[i])
    if hi == lo:
        return NAN, 0, 0
    if lo < hi:
        move, took, ended = highs[hi] - lows[lo], hi - lo, hi
    else:
        move, took, ended = lows[lo] - highs[hi], lo - hi, lo
    return move, max(1, took), len(bars) - 1 - ended


def features(bars: Sequence[Ohlc], *, unit: float = 0.0, span: int = SPAN) -> dict[str, float]:
    """The readings as journal features, or `{}` when there is nothing to say.

    `unit` is one volatility unit in price - the same one every distance on a
    decision is quoted in. Without it there is no scale to divide by and the
    numbers would not be comparable between an index at 30,000 and a rate at
    1.12, so the honest answer is an empty dict rather than price-unit figures
    wearing the same names.
    """
    if unit <= 0 or math.isnan(unit) or span < 3 or len(bars) < 3:
        return {}
    window = list(bars[-span:])
    if len(window) < 3:
        return {}
    spot = float(window[-1].close)
    move, took, since = displacement(window)
    out: dict[str, float] = {}
    if not math.isnan(move):
        out["displacement_vol"] = move / unit
        out["displacement_bars"] = float(took)
        out["displacement_speed_vol"] = (move / unit) / float(took)
        out["displacement_age"] = float(since)
    found = gaps(window, unit)
    out["imbalance_n"] = float(len(found))
    above = [g for g in found if g.low >= spot]
    below = [g for g in found if g.high <= spot]
    # Nearest first: the one price would meet, which is the one a target has to
    # clear. The furthest is reported too, because "way past the imbalance" is
    # a different target from "past the first one".
    if above:
        near = min(above, key=lambda g: g.low - spot)
        far = max(above, key=lambda g: g.high - spot)
        out["imbalance_above_vol"] = (near.low - spot) / unit
        out["imbalance_above_far_vol"] = (far.high - spot) / unit
        out["imbalance_above_size_vol"] = near.size / unit
        out["imbalance_above_age"] = float(len(window) - 1 - near.at)
    if below:
        near = min(below, key=lambda g: spot - g.high)
        far = max(below, key=lambda g: spot - g.low)
        out["imbalance_below_vol"] = (spot - near.high) / unit
        out["imbalance_below_far_vol"] = (spot - far.low) / unit
        out["imbalance_below_size_vol"] = near.size / unit
        out["imbalance_below_age"] = float(len(window) - 1 - near.at)
    return out


def card_line(got: dict[str, float]) -> list[str]:
    """The impulse line for an alert card, or nothing when there is no reading."""
    move = got.get("displacement_vol")
    if move is None or math.isnan(float(move)):
        return []
    move = float(move)
    bars_ = int(float(got.get("displacement_bars") or 0))
    age = int(float(got.get("displacement_age") or 0))
    which = "up" if move > 0 else "down"
    line = f"displaced {abs(move):.1f}v {which} over {bars_} bars"
    if age:
        line += f", {age} ago"
    n = got.get("imbalance_n")
    if n is not None and float(n) > 0:
        parts = []
        up, down = got.get("imbalance_above_vol"), got.get("imbalance_below_vol")
        if up is not None and not math.isnan(float(up)):
            parts.append(f"{float(up):.1f}v above")
        if down is not None and not math.isnan(float(down)):
            parts.append(f"{float(down):.1f}v below")
        if parts:
            many = "s" if float(n) > 1 else ""
            line += f" · {int(float(n))} open imbalance{many} ({', '.join(parts)})"
    return [line]
