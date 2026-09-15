"""The online z-score: streaming internals, nested timeframes, and turn prediction.

`zma.py` is the shipped indicator and every part of it is batch - a softmax over
a 50-element deque, an OLS refit over the same, and two sorts of a 200-element
deque, every bar. This is the same reading with an exact O(1) recursion for each
part, a stream per timeframe, and two learned heads that predict where the next
turn will be and are corrected by it when it arrives.

## What is custom here and what is river's, and why the line falls there

`river` is a dependency of this project already - `har.py`, `learned.py`,
`facto.py` and `volatility.py` all use it - and everything here that **learns**
is river's: `LinearRegression` under a `StandardScaler` for the two heads,
`ADWIN` for drift, `stats.Quantile` for the thresholds. Those are solved
problems with tested implementations and no reason to write again.

What is not river's is the **indicator**, because river has no equivalent:

* **Attention-weighted moments.** No river statistic takes a per-observation
  weight that the caller computes from the observation itself.
* **Exponentially weighted least squares against the bar index.** `river` has
  regression against *features*; the slope here is against position in the
  stream, which is a different object with a two-line exact recursion.

Writing those two by hand and taking the rest from river is the line, and it is
drawn by what river actually has rather than by preference.

## What `research/adapting.md` and `research/streaming.md` measured

Three things bear on anything built here, and two of them are negative.

**The shipped attention does nothing.** `exp(|r| - max|r|)` over absolute
returns near 1e-4 gives every bar a weight of 1.0000: Kish's effective sample
size is **49.00 of 50** on real bars, on a spiky series, and on an OU process.
The "attention-weighted" z-score is a plain rolling z-score. `AttentionZ` fixes
it with a temperature - dividing by the running mean absolute return puts the
exponent at O(1), where a softmax has an opinion - **and fixing it changes
nothing measurable**: 0.654 against 0.654 on a two-scale control. So attention
is off by default here, and the switch exists to keep the measurement
reproducible rather than because it is expected to pay.

**Nested timeframes did not add anything either.** Three ways of using the cycle
above - displacement agreement, direction agreement, and dividing the mother
cycle out of the price before reading it - all track the plain fast reading to
within 0.005 across a contamination sweep, against a matched null. `alignment`
and `with_trend` are published because the desk asked the question and a
published reading can be settled from the journal, not because they are
believed.

**The turn depth is predictable where the process reverts.** Skill against the
running mean is negative or zero on every simulated arm and positive on 8 of 8
constructed spreads, +0.03 to +0.19. **How long** until the turn is not: `when`
scores positive on the nulls too, so its positive values are a property of the
metric rather than of the series.

## Saving

Weights are saved **separately from the engine's own state**, and that is the
point rather than a convenience. `structures/store.py` hashes the shape of every
persisted dataclass and invalidates the whole file when any of them changes, so
a deploy that adds one field to one unrelated class throws away every weight
this has learned. `save` and `load` write a small file of their own that
survives that, and `Book.loaded` says whether it happened.
"""

from __future__ import annotations

import math
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path

from river import drift, linear_model, optim, preprocessing, stats

from ..logging import get_logger
from ..shared import effects
from .state import Restorable
from .zma import CAP, TEMPERATURE

log = get_logger(__name__)

#: Recorded and surfaced. Like `zma.ENABLED` this costs a few floats a bar.
ENABLED = os.environ.get("STRUCTURES_CYCLES", "1") not in ("0", "false", "no")

#: **Whether any of it may influence a decision.** Off, and the module note says
#: why: two of the three things this adds were measured at nothing.
CYCLES_ACT = os.environ.get("STRUCTURES_CYCLES_ACT", "0") not in ("0", "false", "no")

#: Attention weighting. On, now that `zma.TEMPERATURE` makes it a real knob
#: rather than an exponent that could not do anything - and harmless at the
#: temperature that was measured, where the effective sample size is 47.99 of 50
#: and every arm is inside 0.002 of a flat weighting. Sharper is worse: see
#: `zma.TEMPERATURE` for the sweep.
ATTENTION = os.environ.get("STRUCTURES_CYCLES_ATTENTION", "1") not in ("0", "false", "no")

#: Bars in the fast window, and the decay that puts a geometric window's centre
#: of mass where a rectangle of `PERIOD` bars puts its own.
PERIOD = 50
LAM = 1.0 - 1.0 / PERIOD

#: Threshold tiers, as quantiles of |z|. The same two the shipped rule uses.
STRONG_Q, WEAK_Q = 0.85, 0.65

#: How stretched a cycle above has to be before it votes at all. Below this it
#: is mid-range and has no opinion, which is not the same as opposing.
#:
#: Without it the weighting **cancels**: with one cycle above, `total` and
#: `weight` are the same number and the ratio is +/-1 whatever the magnitude, so
#: a mother cycle at a z-score of 6e-9 - numerically still - reported full
#: opposition. Caught by a test that fed it a constant series.
MIN_PULL = 0.15

#: Retracement that confirms a turn, in volatility units.
TURN_SIGMAS = 2.0

#: Settled turns before `skill` is worth reading.
WARM = 200

#: Learning rate for the heads. Small for the reason `har.py` gives: the inputs
#: are standardised and one violent bar should not rewrite the coefficients.
LEARNING_RATE = 0.01

#: Where weights live when no path is given.
WEIGHTS = Path(os.environ.get("STRUCTURES_CYCLES_WEIGHTS", ".data/structures/cycles.pkl"))

effects.declare("structures.cycles", enabled=ENABLED)


def _head():
    return preprocessing.StandardScaler() | linear_model.LinearRegression(
        optimizer=optim.SGD(LEARNING_RATE)
    )


# --------------------------------------------------------------- the pieces


@dataclass(slots=True)
class Ewma(Restorable):
    """Exponentially weighted mean, bias-corrected while it is young."""

    lam: float = LAM
    total: float = 0.0
    weight: float = 0.0

    def push(self, x: float) -> float:
        self.total = self.lam * self.total + x
        self.weight = self.lam * self.weight + 1.0
        return self.mean

    @property
    def mean(self) -> float:
        return self.total / self.weight if self.weight else 0.0


@dataclass(slots=True)
class AttentionZ(Restorable):
    """Attention-weighted mean, variance and z, in O(1) and with no window.

    The batch form normalises a softmax over the window; that normalisation
    **cancels** in `sum(w x) / sum(w)` and in the variance, so what is left is
    three decaying accumulators. The rectangle becomes a geometric window, which
    is the improvement rather than the approximation: a bar fifty back stops
    mattering gradually instead of all at once.
    """

    lam: float = LAM
    attention: bool = ATTENTION
    scale: Ewma = field(default_factory=lambda: Ewma(LAM))
    sw: float = 0.0
    swx: float = 0.0
    swxx: float = 0.0
    last: float = 0.0
    z_score: float = 0.0
    seen: int = 0

    def push(self, price: float) -> float:
        w = 1.0
        if self.seen:
            ret = abs(price - self.last) / max(abs(self.last), 1e-12)
            typical = self.scale.push(ret)
            if self.attention:
                # **The temperature is the whole thing.** A softmax over raw
                # returns is a softmax over numbers near 1e-4 and `exp` of those
                # is 1.0000 for every one of them, which is what `zma.py` did
                # for the whole life of the indicator. Dividing by the running
                # mean absolute return puts the exponent at O(1) and makes the
                # weighting scale-free at the same time.
                #
                # `zma.TEMPERATURE` rather than a number of its own: a streaming
                # reading that sharpened differently from the batch one would be
                # a second indicator wearing the same name, and the sweep behind
                # that constant is the only measurement either has.
                w = math.exp(min(ret / (TEMPERATURE * typical + 1e-12), CAP))
        self.last = price
        self.seen += 1
        self.sw = self.lam * self.sw + w
        self.swx = self.lam * self.swx + w * price
        self.swxx = self.lam * self.swxx + w * price * price
        mean = self.swx / self.sw
        var = max(self.swxx / self.sw - mean * mean, 0.0)
        self.z_score = (price - mean) / (math.sqrt(var) + 1e-12)
        return self.z_score


@dataclass(slots=True)
class Slope(Restorable):
    """Exponentially weighted least squares against the bar index. Exact, O(1).

    With weights `lam^k` on the bar `k` steps back, `a = sum(lam^k x)` and
    `b = sum(lam^k k x)` are everything a regression needs beyond the three
    weight sums. `a <- x + lam*a` is the usual recursion; `b <- lam*(b + a)` is
    the one that makes this possible, and it holds because every lag increases
    by one when a bar arrives.

    **The weight sums are accumulated too, rather than taken from their closed
    forms.** `sum(lam^k)`, `sum(k lam^k)` and `sum(k^2 lam^k)` have tidy
    infinite-series expressions and using them is wrong until the stream is
    long enough for the tail to vanish - which for the `k^2` term takes about
    **2,000 bars** at this decay. Checked against a least-squares fit computed
    the slow way: with the closed forms the slope is **109 times too large at
    300 bars**, converges by 2,000, and is exact from there. With the
    accumulated sums it is exact at every length, including the first bar.

    That is not a rounding difference. A slope 109x too large is the difference
    between an indicator that warms up and one that emits noise for the first
    month of every new instrument, silently, on exactly the feeds nobody is
    watching yet.
    """

    lam: float = LAM
    a: float = 0.0
    b: float = 0.0
    w: float = 0.0
    k: float = 0.0
    kk: float = 0.0
    seen: int = 0
    value: float = 0.0
    #: The second derivative, as the smoothed change in the first. A reversal is
    #: a first derivative crossing zero *and* a second derivative confirming
    #: which kind of turning point it is - a maximum or a minimum - which is
    #: what a sign change alone cannot say.
    previous: float = 0.0
    curve: Ewma | None = None

    def push(self, price: float) -> float:
        lam = self.lam
        # Every one of these reads the previous step's values, so the order
        # matters: `b`, `kk` and `k` before the terms they are built from.
        self.b = lam * (self.b + self.a)
        self.a = price + lam * self.a
        self.kk = lam * (self.kk + 2.0 * self.k + self.w)
        self.k = lam * (self.k + self.w)
        self.w = 1.0 + lam * self.w
        self.seen += 1
        if self.seen < 3:
            self.value = 0.0
            return 0.0
        mean_k = self.k / self.w
        cov = self.b / self.w - mean_k * (self.a / self.w)
        var_k = max(self.kk / self.w - mean_k * mean_k, 1e-12)
        # Negative because `k` counts backwards: a positive covariance between
        # lag and price means price was higher in the past.
        was = self.value
        self.value = -cov / var_k / max(abs(price), 1e-12)
        if self.curve is None:
            self.curve = Ewma(self.lam)
        self.curve.push(self.value - was)
        self.previous = was
        return self.value

    @property
    def curvature(self) -> float:
        return self.curve.mean if self.curve is not None else 0.0


@dataclass(slots=True)
class Stream(Restorable):
    """One instrument at one timeframe, entirely online.

    The thresholds are `river.stats.Quantile`, which is the P-square algorithm:
    five markers, O(1) a bar, no stored history. `zma.py` sorts a 200-element
    deque twice a bar for the same two numbers, and a deque forgets its oldest
    element rather than converging on a moving distribution.
    """

    lam: float = LAM
    attention: bool = ATTENTION
    z: AttentionZ = field(default_factory=lambda: AttentionZ(LAM, ATTENTION))
    slope: Slope = field(default_factory=lambda: Slope(LAM))
    strong: stats.Quantile = field(default_factory=lambda: stats.Quantile(STRONG_Q))
    weak: stats.Quantile = field(default_factory=lambda: stats.Quantile(WEAK_Q))
    sigma: Ewma = field(default_factory=lambda: Ewma(0.99))
    #: Running mean |slope|, so `trend` is in units of this series' own typical
    #: slope. Dividing by `sigma` instead - which is a mean absolute *return* -
    #: leaves a number whose scale depends on the decay and the price, and a
    #: threshold on that is a threshold on nothing. `cycle_with_trend` shipped
    #: constant-zero for exactly this reason and `test_published.py` caught it.
    slope_scale: Ewma = field(default_factory=lambda: Ewma(0.99))
    seen: int = 0
    price: float = 0.0
    previous: float = 0.0

    def push(self, price: float) -> None:
        if price <= 0:
            return
        self.previous = self.price
        self.price = price
        self.z.push(price)
        self.slope.push(price)
        self.slope_scale.push(abs(self.slope.value))
        self.strong.update(abs(self.z.z_score))
        self.weak.update(abs(self.z.z_score))
        if self.previous > 0:
            self.sigma.push(abs(math.log(price / self.previous)))
        self.seen += 1

    @property
    def strong_level(self) -> float:
        got = self.strong.get()
        return float(got) if got else 1.5

    @property
    def stretch(self) -> float:
        """z in units of its own dynamic threshold. The scale-free reading."""
        return self.z.z_score / max(self.strong_level, 1e-9)

    @property
    def trend(self) -> float:
        """The slope in units of this series' own typical slope."""
        return self.slope.value / (self.slope_scale.mean + 1e-15)

    @property
    def rising(self) -> bool:
        return self.slope.value > 0.0

    @property
    def side(self) -> int:
        """+1 expects a rise (stretched down), -1 a fall, 0 inside the band."""
        level = self.strong_level
        if self.z.z_score < -level:
            return 1
        if self.z.z_score > level:
            return -1
        return 0

    @property
    def agrees(self) -> int:
        """`zma.Zma.agrees`, computed from the streaming reading."""
        level = self.strong_level
        if self.z.z_score < -level and self.rising:
            return 1
        if self.z.z_score > level and not self.rising:
            return -1
        return 0


@dataclass(slots=True)
class Cycles(Restorable):
    """One instrument at several timeframes, and three ways to read them together.

    **None of the three is believed.** `research/streaming.md` measured all of
    them at nothing against a matched null, and they are here so the question
    can be settled from the journal on this desk's own instruments rather than
    from a simulation. See the module note.

    * `alignment` - displacement agreement, weighted by how stretched each cycle
      above is. A mother cycle sitting mid-range is not disagreeing with
      anything, and counting it as opposition would be a coin.
    * `with_trend` - the traders' version: the fast reversion call points the
      way the cycle above is already moving.
    * `residual` - a stream fed `price / anchor`, the mother cycle divided out
      before the z-score is ever taken. Different in kind from the other two,
      because it changes the reading rather than voting on it.
    """

    intervals: tuple[str, ...] = ("1m", "15m", "1h")
    attention: bool = ATTENTION
    streams: tuple[Stream, ...] = ()
    residual: Stream | None = None
    anchor: Ewma | None = None
    #: The long-run volatility the fast stream's own is compared against.
    slow_sigma: Ewma | None = None
    seen: int = 0

    def __post_init__(self) -> None:
        if not self.streams:
            self.streams = tuple(Stream(attention=self.attention) for _ in self.intervals)
        if self.residual is None:
            self.residual = Stream(attention=self.attention)
        if self.anchor is None:
            self.anchor = Ewma(1.0 - 1.0 / (PERIOD * 16))
        if self.slow_sigma is None:
            self.slow_sigma = Ewma(1.0 - 1.0 / (PERIOD * 40))

    def observe(self, interval: str, price: float) -> None:
        """One **closed** bar of one timeframe.

        Closed, not forming, and this is the discipline the whole multi-timeframe
        idea stands on: a higher-timeframe bar that has not finished has the
        close of a candle containing the current fast bar, which is the future.
        `structures.service` only publishes closed bars to this path.
        """
        try:
            at = self.intervals.index(interval)
        except ValueError:
            return
        self.streams[at].push(price)
        if at == 0:
            level = self.anchor.push(price)
            if level > 0:
                self.residual.push(100.0 * price / level)
            if self.fast.sigma.mean > 0:
                self.slow_sigma.push(self.fast.sigma.mean)
            self.seen += 1
            effects.fired("structures.cycles")

    @property
    def fast(self) -> Stream:
        return self.streams[0]

    @property
    def mother(self) -> Stream:
        return self.streams[-1]

    @property
    def ready(self) -> bool:
        return all(s.seen >= 30 for s in self.streams)

    @property
    def alignment(self) -> float:
        """-1 (fighting every cycle above) to +1 (running with all of them)."""
        want = self.fast.stretch
        if not want or not self.ready:
            return 0.0
        total = weight = 0.0
        for stream in self.streams[1:]:
            pull = max(-2.0, min(2.0, stream.stretch))
            if abs(pull) < MIN_PULL:
                continue
            total += math.copysign(1.0, want) * math.copysign(1.0, pull) * abs(pull)
            weight += abs(pull)
        return total / weight if weight > 1e-9 else 0.0

    @property
    def with_trend(self) -> float:
        """Does the fast reversion call point the way the cycles above are moving."""
        side = self.fast.side
        if not side or not self.ready:
            return 0.0
        total = weight = 0.0
        for stream in self.streams[1:]:
            pull = max(-3.0, min(3.0, stream.trend))
            if abs(pull) < MIN_PULL:
                continue
            total += math.copysign(1.0, float(side)) * math.copysign(1.0, pull) * abs(pull)
            weight += abs(pull)
        return total / weight if weight > 1e-9 else 0.0

    def features(self) -> dict[str, float]:
        """What the heads read, and what the journal records.

        Four families, and they are the four things a reversal is described by
        wherever it is described:

        * **the extreme** - how stretched, and how far the leg has already run;
        * **the derivatives** - the slope and its own rate of change, because a
          first derivative crossing zero says a turning point and only the
          second says which kind;
        * **the extremes behind** - the pivots the current structure is built
          on, whose loss is the change of character;
        * **volatility** - the unit everything else is measured in, and how far
          it sits from its own normal.
        """
        fast = self.fast
        return {
            "stretch": max(-4.0, min(4.0, fast.stretch)),
            "slope": max(-4.0, min(4.0, fast.trend)),
            # The second derivative, scaled by the first's own typical size so
            # the two are on one footing.
            "curve": max(-4.0, min(4.0, fast.slope.curvature / (fast.slope_scale.mean + 1e-15))),
            "alignment": self.alignment,
            "with_trend": self.with_trend,
            "mother": max(-4.0, min(4.0, self.mother.stretch)),
            "residual": max(-4.0, min(4.0, self.residual.stretch)),
            # How unusual this instrument's volatility is right now, against its
            # own long run. Everything above is measured in volatility units, so
            # without this the model cannot tell a 2-unit move in a quiet regime
            # from one in a violent regime.
            "vol_stretch": max(-4.0, min(4.0, self.vol_stretch)),
        }

    @property
    def vol_stretch(self) -> float:
        """The fast timeframe's volatility against its own long-run level."""
        fast = self.fast
        if self.slow_sigma is None or self.slow_sigma.mean <= 0:
            return 0.0
        return math.log(max(fast.sigma.mean, 1e-15) / self.slow_sigma.mean)


# ------------------------------------------------------- turns, and the heads


@dataclass(slots=True)
class Leg(Restorable):
    """The excursion in progress: which way, since when, and its extreme."""

    direction: int = 0
    started: int = 0
    extreme: float = 0.0
    extreme_at: int = 0
    #: The two extremes behind this leg, most recent first. The level an uptrend
    #: is made of is the previous higher low, and price taking it out is the
    #: change of character - which cannot be expressed from the current leg
    #: alone. `research/delivering.md` measured that the *last* confirmed pivot
    #: is unbreakable before the next one confirms, so it is the one behind it
    #: that carries the claim.
    behind: tuple[float, float] = (0.0, 0.0)


@dataclass(slots=True)
class Turns(Restorable):
    """Causal turn detection, and two river heads predicting the next one.

    A turn confirms when price retraces `TURN_SIGMAS` volatility units from the
    running extreme. The extreme is then in the past - that delay is not a flaw
    in the detector, it is why the prediction is worth making.

    **Feedback is delayed and batched, because that is how the answer arrives.**
    No prediction can be scored until the turn confirms, and then every
    prediction made during the leg settles at once. `ADWIN` watches the residual
    so the desk can be told when the model has stopped fitting rather than
    discovering it from a drawdown.

    `depth` is how much further price runs before turning, in volatility units.
    `when` is `log1p(bars)` until it does. `research/streaming.md` measured the
    first as predictable on constructed spreads and **the second as not**: its
    skill is positive on the nulls too, so a positive value is a property of the
    metric and not of the series. `when_skill` is published anyway, and this
    note is the reason not to read it as a result.
    """

    sigmas: float = TURN_SIGMAS
    leg: Leg = field(default_factory=Leg)
    depth: object = field(default_factory=_head)
    when: object = field(default_factory=_head)
    depth_mean: stats.Mean = field(default_factory=stats.Mean)
    when_mean: stats.Mean = field(default_factory=stats.Mean)
    drift: object = field(default_factory=drift.ADWIN)
    #: Open predictions, settled when the leg turns.
    pending: list[tuple[dict, int, float]] = field(default_factory=list)
    turns: int = 0
    settled: int = 0
    #: Sum of absolute errors, model and baseline, for `skill`.
    depth_error: float = 0.0
    depth_base_error: float = 0.0
    when_error: float = 0.0
    when_base_error: float = 0.0
    drifted: int = 0

    def observe(self, cycles: Cycles, index: int) -> None:
        price = cycles.fast.price
        sigma = max(cycles.fast.sigma.mean, 1e-9)
        if price <= 0:
            return
        if self.leg.direction == 0:
            self.leg = Leg(1, index, price, index)
            return

        if self.leg.direction > 0:
            if price > self.leg.extreme:
                self.leg.extreme, self.leg.extreme_at = price, index
            retrace = math.log(max(self.leg.extreme, 1e-12) / price) / sigma
        else:
            if price < self.leg.extreme:
                self.leg.extreme, self.leg.extreme_at = price, index
            retrace = math.log(price / max(self.leg.extreme, 1e-12)) / sigma

        if retrace >= self.sigmas:
            extreme_now = self.leg.extreme
            self._settle(sigma)
            self.turns += 1
            self.leg = Leg(
                -self.leg.direction,
                index,
                price,
                index,
                behind=(extreme_now, self.leg.behind[0]),
            )
            return

        self.pending.append((self._features(cycles, index, price, sigma), index, price))

    def _features(self, cycles: Cycles, index: int, price: float, sigma: float) -> dict:
        """The cycle reading, plus what only the leg knows."""
        x = dict(cycles.features())
        x["age"] = math.log1p(max(index - self.leg.started, 0)) / 5.0
        # How far the leg has already travelled, and how far the pivots behind
        # it are. Both in volatility units so they mean the same on any feed.
        x["travelled"] = min(
            abs(math.log(max(price, 1e-12) / max(self.leg.extreme, 1e-12))) / sigma, 8.0
        )
        for i, level in enumerate(self.leg.behind):
            gap = abs(math.log(max(price, 1e-12) / level)) / sigma if level > 0 else 0.0
            x[f"behind_{i}"] = min(gap, 8.0)
        return x

    def _settle(self, sigma: float) -> None:
        extreme, at = self.leg.extreme, self.leg.extreme_at
        for x, index, price in self.pending:
            further = abs(math.log(max(extreme, 1e-12) / max(price, 1e-12))) / sigma
            bars = math.log1p(max(at - index, 0))
            # Predict, score, then learn. The baseline is taken here too - what
            # the running mean would have said at this bar - because a mean
            # computed over the whole sample afterwards has look-ahead and
            # flatters the model by however much the target drifts.
            said_depth = float(self.depth.predict_one(x) or 0.0)
            said_when = float(self.when.predict_one(x) or 0.0)
            base_depth = float(self.depth_mean.get() or 0.0)
            base_when = float(self.when_mean.get() or 0.0)
            self.depth_error += abs(said_depth - further)
            self.depth_base_error += abs(base_depth - further)
            self.when_error += abs(said_when - bars)
            self.when_base_error += abs(base_when - bars)
            self.settled += 1
            self.drift.update(abs(said_depth - further))
            if getattr(self.drift, "drift_detected", False):
                self.drifted += 1
            self.depth.learn_one(x, further)
            self.when.learn_one(x, bars)
            self.depth_mean.update(further)
            self.when_mean.update(bars)
        self.pending.clear()

    def predict(self, cycles: Cycles, index: int) -> dict[str, float]:
        """Where the next turn is, as far as this has learned. Empty until warm."""
        if self.settled < WARM or self.leg.direction == 0:
            return {}
        x = self._features(cycles, index, cycles.fast.price, max(cycles.fast.sigma.mean, 1e-9))
        depth = float(self.depth.predict_one(x) or 0.0)
        bars = math.expm1(max(float(self.when.predict_one(x) or 0.0), 0.0))
        sigma = max(cycles.fast.sigma.mean, 1e-9)
        price = cycles.fast.price
        return {
            "turn_depth_vol": round(max(depth, 0.0), 4),
            "turn_price": round(price * math.exp(self.leg.direction * depth * sigma), 6),
            "turn_bars": round(min(bars, 10_000.0), 2),
            "turn_side": float(-self.leg.direction),
        }

    @property
    def warm(self) -> bool:
        return self.settled >= WARM

    @property
    def depth_skill(self) -> float:
        """1 - MAE(model)/MAE(running mean). Zero is no better than the mean."""
        if not self.depth_base_error:
            return float("nan")
        return 1.0 - self.depth_error / self.depth_base_error

    @property
    def when_skill(self) -> float:
        if not self.when_base_error:
            return float("nan")
        return 1.0 - self.when_error / self.when_base_error

    def to_dict(self) -> dict:
        return {
            "turns": self.turns,
            "settled": self.settled,
            "depth_skill": round(self.depth_skill, 4) if self.warm else None,
            "when_skill": round(self.when_skill, 4) if self.warm else None,
            "drifted": self.drifted,
        }


# --------------------------------------------------------------------- book


@dataclass(slots=True)
class Series(Restorable):
    """One instrument: its nested streams and its turn model."""

    feed: str = ""
    cycles: Cycles = field(default_factory=Cycles)
    turns: Turns = field(default_factory=Turns)
    bars: int = 0

    def observe(self, interval: str, price: float) -> None:
        self.cycles.observe(interval, price)
        if interval == self.cycles.intervals[0] and self.cycles.ready:
            self.bars += 1
            self.turns.observe(self.cycles, self.bars)

    def reading(self) -> dict[str, float]:
        """What this publishes onto a call. Numeric, because `features` is.

        `Signal.to_dict` rounds every value in the features dict, so a string
        here raises at publication rather than at the call site - the same trap
        `zma_state` fell into.
        """
        if not ENABLED or not self.cycles.ready:
            return {}
        fast = self.cycles.fast
        out = {
            "cycle_z": round(fast.z.z_score, 4),
            "cycle_stretch": round(fast.stretch, 4),
            "cycle_side": float(fast.side),
            "cycle_agrees": float(fast.agrees),
            "cycle_alignment": round(self.cycles.alignment, 4),
            "cycle_with_trend": round(self.cycles.with_trend, 4),
            "cycle_residual_z": round(self.cycles.residual.z.z_score, 4),
        }
        out.update(self.turns.predict(self.cycles, self.bars))
        return out


@dataclass(slots=True)
class Book(Restorable):
    """One `Series` per feed, with weights that outlive a schema change."""

    intervals: tuple[str, ...] = ("1m", "15m", "1h")
    _by_feed: dict[str, Series] = field(default_factory=dict)
    loaded: int = 0

    def of(self, feed: str) -> Series:
        found = self._by_feed.get(feed)
        if found is None:
            found = self._by_feed[feed] = Series(feed=feed, cycles=Cycles(intervals=self.intervals))
        return found

    def observe(self, feed: str, interval: str, price: float) -> Series:
        got = self.of(feed)
        got.observe(interval, price)
        return got

    def forget(self, keep: set[str]) -> int:
        gone = [f for f in self._by_feed if f not in keep]
        for f in gone:
            del self._by_feed[f]
        return len(gone)

    def standings(self) -> list[tuple[str, float, int]]:
        """Feeds by how well the depth head beats the running mean, worst first."""
        rows = [
            (feed, s.turns.depth_skill, s.turns.settled)
            for feed, s in self._by_feed.items()
            if s.turns.warm
        ]
        return sorted(rows, key=lambda r: r[1])

    # ------------------------------------------------------------ persistence

    def save(self, path: Path | None = None) -> int:
        """Write the learned weights to their own file. Returns feeds written.

        **Separate from the engine's state on purpose.** `structures/store.py`
        hashes the shape of every persisted dataclass and invalidates the whole
        file when any of them changes, so a deploy that adds one field to one
        unrelated class throws away every weight this has learned. Months of
        settled turns are not something to lose to an unrelated refactor.

        Written to a temporary file and renamed, so an interrupted save leaves
        the previous weights rather than a truncated file.
        """
        target = Path(path or WEIGHTS)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                feed: (s.turns.depth, s.turns.when, s.turns.depth_mean, s.turns.when_mean)
                for feed, s in self._by_feed.items()
                if s.turns.settled
            }
            if not payload:
                return 0
            spare = target.with_suffix(target.suffix + ".tmp")
            with spare.open("wb") as handle:
                pickle.dump({"version": 1, "weights": payload}, handle)
            spare.replace(target)
            return len(payload)
        except Exception as exc:
            log.warning("cycles: could not save weights to %s: %s", target, exc)
            return 0

    def load(self, path: Path | None = None) -> int:
        """Read weights back, into the feeds that have them. Returns feeds loaded.

        Only the learned parts: the streams rebuild themselves from bars within
        a few hundred of them, and a stream restored beside weights learned from
        a different stretch of history is a mismatch nobody would notice.
        """
        target = Path(path or WEIGHTS)
        if not target.exists():
            return 0
        try:
            with target.open("rb") as handle:
                got = pickle.load(handle)
            if not isinstance(got, dict) or got.get("version") != 1:
                log.warning("cycles: %s is not a weights file this build reads", target)
                return 0
            for feed, (depth, when, depth_mean, when_mean) in got["weights"].items():
                series = self.of(feed)
                series.turns.depth = depth
                series.turns.when = when
                series.turns.depth_mean = depth_mean
                series.turns.when_mean = when_mean
            self.loaded = len(got["weights"])
            return self.loaded
        except Exception as exc:
            log.warning("cycles: could not load weights from %s: %s", target, exc)
            return 0

    def to_dict(self) -> dict:
        return {
            "enabled": ENABLED,
            "acts": CYCLES_ACT,
            "attention": ATTENTION,
            "intervals": list(self.intervals),
            "feeds": len(self._by_feed),
            "warm": sum(1 for s in self._by_feed.values() if s.turns.warm),
            "loaded": self.loaded,
            "standings": [[f, round(k, 4), n] for f, k, n in self.standings()[:10]],
        }
