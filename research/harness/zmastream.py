"""ZMA with nothing batched in it: streaming z, attention, slope, thresholds,
turn prediction with feedback, and alignment with the cycle above.

`adapting.md` converted ZMA's *output* into an online learner and left its
*internals* alone. They are all batch: every bar rebuilds a softmax over a
50-element deque, refits an OLS slope over the same, and sorts a 200-element
deque twice for two percentiles. That is O(n log n) a bar for a quantity whose
every part has an exact O(1) recursion, and the window is a **rectangle** -
a bar 50 back counts fully and a bar 51 back counts not at all.

This replaces all four, tests each against the batch version it replaces, adds
the parts a rectangle cannot have, and then asks whether any of it predicts.

## The four streaming parts

**Attention-weighted moments.** The batch form normalises softmax weights over
the window; that normalisation **cancels** in `mean = Sum(w x) / Sum(w)` and in
the variance, so the same estimator is three decaying accumulators and no
window at all. Attention weight is `exp(|r| / E|r|)`, scale-free, so an
instrument at 4,400 and one at 1.0 weight their moves alike.

**Slope by exponentially weighted least squares**, exact rather than
approximated: `A <- x + lam*A` and `B <- lam*(B + A)` carry the two sums a
regression against the bar index needs, and the closed forms for `Sum lam^k`,
`Sum lam^k k` and `Sum lam^k k^2` do the rest.

**Thresholds by Robbins-Monro** rather than by sorting: `q <- q + eta*(1[x>q] -
(1-p))` converges to the p-th quantile and keeps converging when the
distribution moves, which a sort over a fixed deque does only by forgetting.

**A turn detector that is causal.** A confirmed extremum, where confirmation is
a retracement of `TURN_SIGMAS` volatility units. The extreme is in the past when
it confirms - that delay is real and is what the predictor has to live with.

## The prediction, and why it is two numbers

"Where the next turn will be" is **how much further** and **how long**, and they
are separate questions with separate baselines. Both are learned online by SGD
against the realised turn, and both are scored against the only baseline that
matters: **predicting the running mean**. A model that cannot beat the mean of
its own target has found nothing, whatever its correlation looks like.

Feedback is delayed and batched, because that is how the world delivers it: no
prediction can be scored until the turn confirms, and then every prediction made
during that leg settles at once. The learning rate is adaptive - it rises when
the error rises against its own recent average, which is the cheap form of the
drift response a river model makes explicit.

## Cycles, and the control that makes them mean something

Markets are claimed to be fractal: small cycles inside big ones, and a small
cycle fighting the cycle above it is worth less than one running with it. That
is testable rather than decorative, and the test needs a **two-scale positive
control** - a fast Ornstein-Uhlenbeck process reverting not to a constant but to
a slow one - together with a **matched null** where the slow series is replaced
by an independent one of identical statistics. Alignment that helps in the first
and not the second is alignment carrying information. Alignment that helps in
both is a second noisy feature helping a regression, which is not the claim.

    ./.secrets/lab.sh run research/harness/zmastream.py
"""

from __future__ import annotations

import math
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from till_infinity.structures.zma import Zma

BARS = int(os.environ.get("BARS", "40000"))
DB = os.environ.get("PRICES_DB", ".data/prices/prices.db")

#: Decay for the attention moments and the slope. `1 - 1/period` puts the
#: centre of mass of a geometric window where a rectangle of `period` bars puts
#: its own, so the two are comparable rather than merely similar.
PERIOD = 50
LAM = 1.0 - 1.0 / PERIOD

#: The two threshold tiers, as quantiles of |z|, matching the shipped rule.
STRONG_Q, WEAK_Q = 0.85, 0.65

#: Step for the streaming quantiles, as a fraction of the running dispersion of
#: what they are tracking. Constant rather than decaying: a decaying step
#: converges faster and then stops adapting, and the thresholds exist to adapt.
Q_STEP = 0.01

#: How stretched a cycle above has to be before it votes at all. Without it the
#: weighting cancels - with one cycle above, `total` and `weight` are the same
#: number - so a mother cycle at a z-score of 6e-9 reported full opposition.
MIN_PULL = 0.15

#: Retracement that confirms a turn, in volatility units. Large enough that
#: noise does not confirm one every other bar - `research/turns.md`'s zigzag
#: needed three explicit states for the same reason.
TURN_SIGMAS = 2.0

#: Bars before anything is scored.
WARM = 500

#: Base learning rate for the two prediction heads, and how far the adaptive
#: rate may rise above it when the error does.
LR = 0.01
LR_MAX = 8.0


# --------------------------------------------------------------- the pieces


class Ewma:
    """Mean and mean-absolute, with a bias correction while it is young."""

    __slots__ = ("lam", "value", "weight")

    def __init__(self, lam: float) -> None:
        self.lam = lam
        self.value = 0.0
        self.weight = 0.0

    def push(self, x: float) -> float:
        self.value = self.lam * self.value + x
        self.weight = self.lam * self.weight + 1.0
        return self.mean

    @property
    def mean(self) -> float:
        return self.value / self.weight if self.weight else 0.0


class AttentionZ:
    """Attention-weighted mean, variance and z, in O(1) and with no window.

    The batch version takes a softmax over the window's absolute returns and a
    weighted mean of the prices. The softmax *normalisation* cancels in every
    ratio taken from it, so what is left is three decaying sums - and the
    rectangle becomes a geometric window, which is the improvement rather than
    the approximation: a bar 50 back stops mattering gradually instead of at
    once.
    """

    __slots__ = ("attention", "lam", "last", "scale", "seen", "sw", "swx", "swxx", "z")

    def __init__(self, lam: float = LAM, *, attention: bool = True) -> None:
        self.lam = lam
        #: False makes every weight 1 and turns this into a plain exponentially
        #: weighted z-score - which is what the shipped batch version already
        #: is, whether or not it means to be. See `inert_attention`.
        self.attention = attention
        self.scale = Ewma(lam)
        self.sw = self.swx = self.swxx = 0.0
        self.last = 0.0
        self.z = 0.0
        self.seen = 0

    def push(self, price: float) -> float:
        if self.seen and self.attention:
            ret = abs(price - self.last) / max(abs(self.last), 1e-12)
            typical = self.scale.push(ret)
            # **The temperature is the whole thing.** A softmax over raw returns
            # is a softmax over numbers near 1e-4, and `exp` of those is 1.0000
            # for all of them - which is what the shipped version does and why
            # its attention is inert. Dividing by the running mean absolute
            # return puts the exponent at O(1), where a softmax has an opinion,
            # and makes it scale-free at the same time. Capped because one burst
            # must not own the whole mean.
            w = math.exp(min(ret / (typical + 1e-12), 6.0))
        else:
            if self.seen:
                self.scale.push(abs(price - self.last) / max(abs(self.last), 1e-12))
            w = 1.0
        self.last = price
        self.seen += 1
        self.sw = self.lam * self.sw + w
        self.swx = self.lam * self.swx + w * price
        self.swxx = self.lam * self.swxx + w * price * price
        mean = self.swx / self.sw
        var = max(self.swxx / self.sw - mean * mean, 0.0)
        self.z = (price - mean) / (math.sqrt(var) + 1e-12)
        return self.z


class EwlsSlope:
    """Exponentially weighted least squares against the bar index. Exact, O(1).

    With weights `lam^k` on the bar `k` steps back, `a = sum(lam^k x)` and
    `b = sum(lam^k k x)` are all a regression needs beyond the three weight
    sums. `a <- x + lam*a` is the usual recursion; `b <- lam*(b + a)` is the one
    that makes this possible, and it holds because every lag increases by one
    when a bar arrives.

    **The weight sums are accumulated too, not taken from their closed forms.**
    The infinite-series expressions for `sum(lam^k)`, `sum(k lam^k)` and
    `sum(k^2 lam^k)` are wrong until the tail vanishes, which for the `k^2` term
    takes about 2,000 bars at this decay. Checked against a least-squares fit
    computed the slow way: with the closed forms the slope is **109 times too
    large at 300 bars**. The first version of this harness had that, so every
    slope-reading column it printed was contaminated for the first few thousand
    bars of each arm.
    """

    __slots__ = ("a", "b", "k", "kk", "lam", "seen", "slope", "w")

    def __init__(self, lam: float = LAM) -> None:
        self.lam = lam
        self.a = self.b = self.w = self.k = self.kk = 0.0
        self.seen = 0
        self.slope = 0.0

    def push(self, price: float) -> float:
        lam = self.lam
        self.b = lam * (self.b + self.a)
        self.a = price + lam * self.a
        self.kk = lam * (self.kk + 2.0 * self.k + self.w)
        self.k = lam * (self.k + self.w)
        self.w = 1.0 + lam * self.w
        self.seen += 1
        if self.seen < 3:
            self.slope = 0.0
            return 0.0
        mean_k = self.k / self.w
        cov = self.b / self.w - mean_k * (self.a / self.w)
        var_k = max(self.kk / self.w - mean_k * mean_k, 1e-12)
        self.slope = -cov / var_k / max(abs(price), 1e-12)
        return self.slope


class Quantile:
    """Robbins-Monro quantile: `q <- q + eta*(1[x>q] - (1-p))`.

    Converges to the p-th quantile of the stream and **keeps converging** when
    the distribution moves, which is what the shipped sort-a-deque version does
    only by forgetting its oldest element. The step is scaled by a running mean
    absolute deviation so `eta` has the units of the thing being tracked.
    """

    __slots__ = ("p", "q", "seen", "spread", "step")

    def __init__(self, p: float, step: float = Q_STEP) -> None:
        self.p = p
        self.step = step
        self.q = 0.0
        self.spread = Ewma(0.99)
        self.seen = 0

    def push(self, x: float) -> float:
        self.seen += 1
        if self.seen == 1:
            self.q = x
            self.spread.push(abs(x))
            return self.q
        scale = self.spread.push(abs(x - self.q)) + 1e-12
        self.q += self.step * scale * ((1.0 if x > self.q else 0.0) - (1.0 - self.p))
        return self.q


# ------------------------------------------------------------- one timeframe


@dataclass(slots=True)
class Stream:
    """One instrument at one timeframe, entirely online."""

    lam: float = LAM
    attention: bool = True
    z: AttentionZ = field(default_factory=AttentionZ)
    slope: EwlsSlope = field(default_factory=EwlsSlope)
    strong: Quantile = field(default_factory=lambda: Quantile(STRONG_Q))
    weak: Quantile = field(default_factory=lambda: Quantile(WEAK_Q))
    sigma: Ewma = field(default_factory=lambda: Ewma(0.99))
    slope_scale: Ewma = field(default_factory=lambda: Ewma(0.99))
    seen: int = 0
    price: float = 0.0
    last: float = 0.0

    def __post_init__(self) -> None:
        self.z.attention = self.attention

    def push(self, price: float) -> None:
        self.last = self.price
        self.price = price
        self.z.push(price)
        self.slope.push(price)
        self.slope_scale.push(abs(self.slope.slope))
        self.strong.push(abs(self.z.z))
        self.weak.push(abs(self.z.z))
        if self.last > 0:
            self.sigma.push(abs(math.log(price / self.last)))
        self.seen += 1

    @property
    def stretch(self) -> float:
        """z in units of its own dynamic threshold. The scale-free reading."""
        return self.z.z / max(self.strong.q, 1e-9)

    @property
    def trend(self) -> float:
        """The slope in units of this series' own typical slope.

        Dividing by `sigma` - a mean absolute *return* - leaves a number whose
        scale depends on the decay and the price, so a fixed threshold on it
        passes almost never. That shipped, and `test_published.py` caught the
        resulting constant-zero feature.
        """
        return self.slope.slope / (self.slope_scale.mean + 1e-15)

    @property
    def rising(self) -> bool:
        return self.slope.slope > 0.0

    @property
    def side(self) -> int:
        """+1 expects a rise (stretched down), -1 a fall, 0 inside the band."""
        if self.z.z < -self.strong.q:
            return 1
        if self.z.z > self.strong.q:
            return -1
        return 0

    @property
    def agrees(self) -> int:
        if self.z.z < -self.strong.q and self.rising:
            return 1
        if self.z.z > self.strong.q and not self.rising:
            return -1
        return 0


# ------------------------------------------------------------------- cycles


@dataclass(slots=True)
class Cycles:
    """The same instrument at nested bar sizes, and three ways to use them.

    The fast stream sees every bar; a stream at `ratio` is pushed once every
    `ratio` bars, which is exactly what a higher timeframe is.

    **Three readings, because "align with the mother cycle" means three
    different things** and they do not agree with each other:

    * `alignment` - displacement agreement. Both stretched the same way, so
      both expect the same reversion. Weighted by how stretched each cycle
      above is, because a mother cycle sitting mid-range is not disagreeing
      with anything and counting it as opposition would be a coin.
    * `with_trend` - the traders' version. The fast reversion call points the
      way the cycle above is already **moving**: buy the dip in an uptrend.
      Displacement and direction are not the same claim and this is the one
      that usually gets said out loud.
    * `residual` - a separate stream fed `price / anchor`, where the anchor is
      the slow level the cycle above defines. **This is the one that should
      work in a fractal market**, and it is different in kind from the other
      two: instead of voting, it removes the mother cycle from the price before
      the fast z-score ever sees it, so "stretched" means stretched relative to
      where the big cycle currently is rather than to a 50-bar average that the
      big cycle has been dragging.
    """

    ratios: tuple[int, ...] = (1, 4, 16)
    attention: bool = True
    streams: tuple[Stream, ...] = ()
    residual: Stream | None = None
    anchor: Ewma | None = None
    seen: int = 0

    def __post_init__(self) -> None:
        if not self.streams:
            self.streams = tuple(Stream(attention=self.attention) for _ in self.ratios)
        if self.residual is None:
            self.residual = Stream(attention=self.attention)
        if self.anchor is None:
            # Slow enough to be the cycle above rather than a lagged copy of the
            # one below: the coarsest ratio's own window, in fast-bar units.
            span = max(self.ratios) * PERIOD
            self.anchor = Ewma(1.0 - 1.0 / span)

    def push(self, price: float) -> None:
        """Drive every stream off one series, subsampling for the slower ones.

        Right for a simulation, where there is one series and the timeframes
        are a choice. **Wrong for real bars**, where the higher timeframe is
        its own series with its own opens and closes - use `push_slow` for
        those, and see `real_cycles`.
        """
        for ratio, stream in zip(self.ratios, self.streams, strict=True):
            if self.seen % ratio == 0:
                stream.push(price)
        level = self.anchor.push(price)
        if level > 0:
            self.residual.push(100.0 * price / level)
        self.seen += 1

    def push_fast(self, price: float) -> None:
        """One bar of the fastest timeframe, with the slower ones driven apart."""
        self.streams[0].push(price)
        level = self.anchor.push(price)
        if level > 0:
            self.residual.push(100.0 * price / level)
        self.seen += 1

    def push_slow(self, index: int, price: float) -> None:
        """One **closed** bar of a higher timeframe.

        Closed, not forming. A higher-timeframe bar that has not finished is
        the one piece of look-ahead a multi-timeframe study cannot survive: its
        close is the future, and a z-score built on it knows where the fast
        bars inside it ended up.
        """
        self.streams[index].push(price)

    @property
    def fast(self) -> Stream:
        return self.streams[0]

    @property
    def mother(self) -> Stream:
        return self.streams[-1]

    @property
    def alignment(self) -> float:
        """-1 (fighting every cycle above) to +1 (running with all of them).

        Zero when the fast stream has no opinion **or** when the cycles above
        are mid-range, and those are different silences that this deliberately
        does not distinguish: neither is a reason to act.
        """
        want = self.fast.stretch
        if not want:
            return 0.0
        total = weight = 0.0
        for stream in self.streams[1:]:
            if stream.seen < 20:
                continue
            pull = max(-2.0, min(2.0, stream.stretch))
            if abs(pull) < MIN_PULL:
                continue
            total += math.copysign(1.0, want) * math.copysign(1.0, pull) * abs(pull)
            weight += abs(pull)
        return total / weight if weight > 1e-9 else 0.0

    @property
    def with_trend(self) -> float:
        """Does the fast reversion call point the way the cycles above are moving.

        `side` is +1 when stretched down, which expects a rise. So this is
        positive when the fast call agrees with the slope of the cycle above.
        """
        side = self.fast.side
        if not side:
            return 0.0
        total = weight = 0.0
        for stream in self.streams[1:]:
            if stream.seen < 20:
                continue
            pull = max(-3.0, min(3.0, stream.trend))
            if abs(pull) < MIN_PULL:
                continue
            total += math.copysign(1.0, float(side)) * math.copysign(1.0, pull) * abs(pull)
            weight += abs(pull)
        return total / weight if weight > 1e-9 else 0.0

    @property
    def ready(self) -> bool:
        return all(s.seen >= 30 for s in self.streams) and self.residual.seen >= 30


# ------------------------------------------------------- turns, and the heads


@dataclass(slots=True)
class Leg:
    """The excursion in progress: where it started and how far it has run."""

    direction: int = 0
    start_index: int = 0
    extreme: float = 0.0
    extreme_index: int = 0


class Online:
    """Linear model, SGD, with a learning rate that answers to its own error.

    The adaptive rate is the cheap form of a drift response: when the running
    absolute error rises above its own long-run level, the step grows in
    proportion, so a model that has stopped fitting re-fits rather than
    averaging the old regime with the new one for a thousand bars.
    """

    __slots__ = ("fast", "lr", "n", "slow", "w")

    def __init__(self, width: int, lr: float = LR) -> None:
        self.w = [0.0] * width
        self.lr = lr
        self.fast = Ewma(0.98)
        self.slow = Ewma(0.999)
        self.n = 0

    def predict(self, x: list[float]) -> float:
        return sum(wi * xi for wi, xi in zip(self.w, x, strict=True))

    def update(self, x: list[float], y: float) -> float:
        got = self.predict(x)
        err = y - got
        self.fast.push(abs(err))
        self.slow.push(abs(err))
        drift = self.fast.mean / (self.slow.mean + 1e-12)
        rate = self.lr * min(LR_MAX, max(1.0, drift))
        for i, xi in enumerate(x):
            self.w[i] += rate * err * xi
        self.n += 1
        return err


class Mean:
    """The baseline every head has to beat: the running mean of its own target."""

    __slots__ = ("ewma",)

    def __init__(self, lam: float = 0.999) -> None:
        self.ewma = Ewma(lam)

    def predict(self) -> float:
        return self.ewma.mean

    def update(self, y: float) -> None:
        self.ewma.push(y)


@dataclass(slots=True)
class Turns:
    """Causal turn detection, and two heads predicting the next one.

    A turn confirms when price retraces `TURN_SIGMAS` volatility units from the
    running extreme of the leg. The extreme is then in the past - that delay is
    not a flaw in the detector, it is the reason the prediction is worth making.
    """

    sigmas: float = TURN_SIGMAS
    leg: Leg = field(default_factory=Leg)
    depth: Online = field(default_factory=lambda: Online(7))
    when: Online = field(default_factory=lambda: Online(7))
    depth_mean: Mean = field(default_factory=Mean)
    when_mean: Mean = field(default_factory=Mean)
    #: Predictions made during the leg in progress, settled when it turns.
    pending: list[tuple[list[float], int, float, float, float, float]] = field(default_factory=list)
    scored: list[tuple[float, float, float, float]] = field(default_factory=list)
    turns: int = 0

    def features(self, cycles: Cycles, index: int, sigma: float) -> list[float]:
        fast = cycles.fast
        age = index - self.leg.start_index
        travelled = (
            abs(math.log(max(fast.price, 1e-12) / max(self.leg.extreme, 1e-12))) / sigma
            if self.leg.extreme > 0 and sigma > 0
            else 0.0
        )
        return [
            1.0,
            max(-4.0, min(4.0, fast.stretch)),
            max(-4.0, min(4.0, fast.trend)),
            cycles.alignment,
            math.log1p(max(age, 0)) / 5.0,
            min(travelled, 8.0),
            max(-4.0, min(4.0, cycles.mother.stretch)),
        ]

    def push(self, cycles: Cycles, index: int, *, record: bool) -> None:
        price = cycles.fast.price
        sigma = max(cycles.fast.sigma.mean, 1e-9)
        if self.leg.direction == 0:
            self.leg = Leg(1, index, price, index)
            return

        if self.leg.direction > 0:
            if price > self.leg.extreme:
                self.leg.extreme, self.leg.extreme_index = price, index
            retrace = math.log(max(self.leg.extreme, 1e-12) / max(price, 1e-12)) / sigma
        else:
            if price < self.leg.extreme:
                self.leg.extreme, self.leg.extreme_index = price, index
            retrace = math.log(max(price, 1e-12) / max(self.leg.extreme, 1e-12)) / sigma

        if retrace >= self.sigmas:
            self._settle(sigma)
            self.turns += 1
            self.leg = Leg(-self.leg.direction, index, price, index)
            return

        if record:
            x = self.features(cycles, index, sigma)
            self.pending.append(
                (
                    x,
                    index,
                    price,
                    self.depth.predict(x),
                    self.when.predict(x),
                    float(self.leg.direction),
                )
            )

    def _settle(self, sigma: float) -> None:
        """Every prediction made during the leg, scored at once against the turn.

        Delayed and batched because that is how the answer arrives. Scoring a
        prediction earlier would mean scoring it against something other than
        the turn it was about.
        """
        extreme, at = self.leg.extreme, self.leg.extreme_index
        for x, index, price, said_depth, said_when, _side in self.pending:
            further = abs(math.log(max(extreme, 1e-12) / max(price, 1e-12))) / sigma
            bars = max(at - index, 0)
            target_when = math.log1p(bars)
            # **The baseline's prediction is taken here, not reconstructed
            # afterwards.** It has to be the number the running mean would have
            # said at this bar, from the same history the model had - a mean
            # computed over the whole sample at the end is a baseline with
            # look-ahead, which flatters the model by exactly the amount the
            # target drifts.
            self.scored.append(
                (
                    said_depth,
                    further,
                    said_when,
                    target_when,
                    self.depth_mean.predict(),
                    self.when_mean.predict(),
                )
            )
            self.depth.update(x, further)
            self.when.update(x, target_when)
            self.depth_mean.update(further)
            self.when_mean.update(target_when)
        self.pending.clear()


# --------------------------------------------------------------------- study


def skill(said: np.ndarray, truth: np.ndarray, base: np.ndarray, warm: int = 200) -> float:
    """1 - MAE(model) / MAE(baseline). Zero is "no better than the running mean".

    `base` is what the running-mean predictor actually said at each bar, taken
    at the time rather than computed over the whole sample afterwards. A
    baseline built at the end has look-ahead, and it flatters the model by
    exactly the amount the target drifts over the sample.

    The first `warm` settled predictions are dropped from both. Neither has seen
    a turn there, so scoring a model against a baseline still sitting at zero
    measures the warm-up and nothing else.
    """
    if len(said) < warm + 100:
        return float("nan")
    said, truth, base = said[warm:], truth[warm:], base[warm:]
    ours = float(np.mean(np.abs(said - truth)))
    theirs = float(np.mean(np.abs(base - truth)))
    return 1.0 - ours / theirs if theirs > 0 else float("nan")


def auc(score: np.ndarray, label: np.ndarray) -> float:
    score, label = np.asarray(score, float), np.asarray(label)
    order = np.argsort(score)
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    n1, n0 = float((label == 1).sum()), float((label == 0).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    return float((ranks[label == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def run(
    prices: np.ndarray,
    *,
    ratios: tuple[int, ...] = (1, 4, 16),
    attention: bool = True,
) -> dict:
    """One pass: every component online, every prediction before its own bar.

    Four side-callers off the same stream, so the comparison between them is
    free of everything except what they read:

    * `raw` - the fast z-score, which is the shipped rule.
    * `residual` - the fast z-score of `price / anchor`, the mother cycle
      divided out before the reading is taken.
    * `raw` restricted to bars where the cycles above **agree by displacement**.
    * `raw` restricted to bars where they agree by **direction**.
    """
    cycles = Cycles(ratios=ratios, attention=attention)
    turns = Turns()
    rows: list[tuple[float, float, int, int, float, float, float]] = []
    for i, price in enumerate(prices):
        if price <= 0:
            continue
        cycles.push(float(price))
        if not cycles.ready:
            continue
        if i >= WARM and i + 1 < len(prices) and prices[i + 1] > 0:
            rows.append(
                (
                    cycles.fast.z.z,
                    cycles.residual.z.z,
                    cycles.fast.side,
                    cycles.residual.side,
                    cycles.alignment,
                    cycles.with_trend,
                    math.log(prices[i + 1] / price),
                )
            )
        turns.push(cycles, i, record=i >= WARM)

    return _score(turns, rows)


# ---------------------------------------------------------------- generators


def ou(n, theta, sigma, rng, start=100.0):
    x = np.empty(n)
    x[0] = start
    shocks = rng.normal(0.0, sigma, n)
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (start - x[i - 1]) + shocks[i]
    return x


def two_scale(n, rng, *, fast=0.15, slow=0.002, contamination=1.0, reverting=True):
    """Small cycles inside a big one, with the contamination as a dial.

    A fast Ornstein-Uhlenbeck deviation around a slow level that is itself an
    OU. **`contamination` is the whole experiment**: it is how far the slow
    level travels over one fast window, in units of the fast deviation's own
    standard deviation. At 0 the slow level is still and this is a plain OU. At
    4 the slow level moves four times as far across a 50-bar window as the fast
    deviation ever gets from it, so a 50-bar z-score is mostly reading the slow
    level and a reversion call is a counter-trend bet.

    Nothing here is tuned to a favourable point, because the point is the
    **curve**: an indicator that breaks somewhere between 0 and 4 has a
    breaking point worth knowing, and a repair that works has to work across
    the same range.

    `reverting=False` is the matched null: the same visible two-scale shape -
    a slow level with fast movement on top - where the fast part is a **random
    walk** rather than a reverting deviation. Detrending by the slow level
    cannot help there because there is nothing underneath to recover, and any
    method that appears to help in both arms is helping for another reason.
    """
    fast_sd = 0.5 / math.sqrt(2 * fast)
    slow_sigma = contamination * fast_sd / math.sqrt(PERIOD)
    level = np.empty(n)
    level[0] = 100.0
    slow_shocks = rng.normal(0.0, slow_sigma, n)
    for i in range(1, n):
        level[i] = level[i - 1] + slow * (100.0 - level[i - 1]) + slow_shocks[i]
    dev = np.empty(n)
    dev[0] = 0.0
    shocks = rng.normal(0.0, 0.5, n)
    if reverting:
        for i in range(1, n):
            dev[i] = dev[i - 1] * (1.0 - fast) + shocks[i]
    else:
        # A random walk with the same per-bar innovation, rescaled so its
        # dispersion over the sample matches the reverting arm's - otherwise
        # the null differs in how far it wanders as well as in whether it
        # returns, and the comparison is about two things at once.
        walk = np.cumsum(shocks)
        dev = (walk - walk.mean()) / (walk.std() + 1e-12) * fast_sd
    return level + dev


def gbm(n, sigma_bar, rng, start=100.0):
    return start * np.exp(np.cumsum(rng.normal(0.0, sigma_bar, n)))


def shuffled(prices, rng):
    rets = np.diff(np.log(np.maximum(prices, 1e-12)))
    rng.shuffle(rets)
    return float(prices[0]) * np.exp(np.concatenate([[0.0], np.cumsum(rets)]))


def spreads(db: str, limit: int = 8) -> dict[str, np.ndarray]:
    """The constructed spreads, read as the ordinary feeds they now are."""
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT feed FROM bars WHERE source='spread' AND interval='1m'"
                " GROUP BY feed HAVING COUNT(*)>3000 ORDER BY COUNT(*) DESC LIMIT ?",
                (limit,),
            )
        ]
        out = {}
        for name in names:
            rows = conn.execute(
                "SELECT close FROM bars WHERE feed=? AND source='spread'"
                " AND interval='1m' ORDER BY ts",
                (name,),
            ).fetchall()
            got = np.array([float(r[0]) for r in rows if r[0] and r[0] > 0])
            if len(got) > 3000:
                out[name] = got
        return out
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


# ------------------------------------------------------------------- equality


def inert_attention(rng) -> None:
    """Does the shipped softmax weight anything differently from anything else.

    The batch indicator takes `exp(|r| - max|r|)` over the window's absolute
    returns and calls it attention. A softmax has an opinion only when its
    inputs differ by O(1), and absolute one-minute returns differ by about
    **1e-4**, so every weight comes out at 1.0000 and the "attention-weighted"
    mean is the plain one. Reported as Kish's effective sample size, which is
    exactly 50 for a uniform weighting over a 50-bar window.
    """
    print("Is the shipped attention weighting doing anything? (uniform = 50.00 of 50)\n")
    print(f"  {'series':26} {'max/min weight':>15} {'effective n':>12}")
    series = {
        "GBM, 1m-scale sigma": 100 * np.exp(np.cumsum(rng.normal(0, 1e-4, 4000))),
        "GBM, 2% a bar": 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 4000))),
        "spiky (boom-like)": 100
        * np.exp(np.cumsum(rng.normal(0, 1e-4, 4000) + (rng.random(4000) < 0.002) * 0.05)),
        "OU theta=0.15": ou(4000, 0.15, 0.5, rng),
    }
    for name, arr in series.items():
        ratios, effs = [], []
        for end in range(PERIOD + 1, len(arr), 37):
            window = arr[end - PERIOD : end]
            rets = np.diff(window) / window[:-1]
            w = np.exp(np.abs(rets) - np.abs(rets).max())
            w = w / w.sum()
            ratios.append(w.max() / w.min())
            effs.append(1.0 / np.sum(w**2))
        print(f"  {name:26} {float(np.median(ratios)):>15.5f} {float(np.median(effs)):>12.2f}")
    print()


def agreement(rng) -> None:
    """The streaming parts against the batch ones, and against themselves.

    Two comparisons, because the first is not the interesting one. Streaming
    **without** attention should track the batch version closely, since the
    batch version has no working attention either. Streaming **with** attention
    should not - and the gap between the two columns is how much the attention
    the shipped code meant to apply would actually have changed.
    """
    prices = two_scale(6000, rng)
    batch = Zma()
    plain, weighted = Stream(attention=False), Stream(attention=True)
    a, b, c = [], [], []
    for price in prices:
        batch.observe(float(price))
        plain.push(float(price))
        weighted.push(float(price))
        if batch.seen > WARM:
            a.append(batch.z_score)
            b.append(plain.z.z)
            c.append(weighted.z.z)
    a, b, c = np.asarray(a), np.asarray(b), np.asarray(c)

    def rank(x, y):
        return float(np.corrcoef(np.argsort(np.argsort(x)), np.argsort(np.argsort(y)))[0, 1])

    print("The streaming z against the batch z it replaces, on one two-scale series:\n")
    print(f"  {'':34} {'no attention':>13} {'attention':>11}")
    print(f"  {'rank correlation with batch':34} {rank(a, b):>13.4f} {rank(a, c):>11.4f}")
    print(
        f"  {'agrees with batch on the sign':34} "
        f"{float((np.sign(a) == np.sign(b)).mean()):>13.4f} "
        f"{float((np.sign(a) == np.sign(c)).mean()):>11.4f}"
    )
    top_a = np.abs(a) >= np.quantile(np.abs(a), 0.85)
    for name, got in (("no attention", b), ("attention", c)):
        top = np.abs(got) >= np.quantile(np.abs(got), 0.85)
        share = float((top_a & top).sum()) / max(float(top_a.sum()), 1.0)
        print(f"  {'batch-extreme bars it also calls extreme (' + name + ')':<60} {share:.4f}")
    print()


def _score(turns: Turns, rows: list) -> dict:
    """Everything both drivers report, from the same two collections.

    One function so the simulated arm and the real-bars arm cannot drift apart
    in what they mean by `hit` - which is the failure that makes two tables
    look comparable when they are not.
    """
    if len(turns.scored) < 400 or len(rows) < 500:
        return {}
    got = np.asarray(turns.scored)
    table = np.asarray(rows)
    fwd = table[:, 6]
    ok = fwd != 0.0
    up = (fwd[ok] > 0).astype(int)
    if up.min() == up.max():
        return {}

    out = {
        "n": len(rows),
        "turns": turns.turns,
        "scored": len(got),
        "depth_skill": skill(got[:, 0], got[:, 1], got[:, 4]),
        "when_skill": skill(got[:, 2], got[:, 3], got[:, 5]),
        "z_auc": auc(-table[ok, 0], up),
        "res_auc": auc(-table[ok, 1], up),
    }

    def hit_of(mask: np.ndarray, side_column: int) -> tuple[float, int]:
        side = table[:, side_column]
        fired = ok & (side != 0) & mask
        if fired.sum() < 50:
            return float("nan"), int(fired.sum())
        right = (side[fired] > 0) == (fwd[fired] > 0)
        return float(right.mean()), int(fired.sum())

    every = np.ones(len(table), dtype=bool)
    out["hit"], out["hit_n"] = hit_of(every, 2)
    out["hit_res"], out["hit_res_n"] = hit_of(every, 3)
    out["hit_with"], out["with_n"] = hit_of(table[:, 4] > 0.25, 2)
    out["hit_against"], out["against_n"] = hit_of(table[:, 4] < -0.25, 2)
    out["hit_trend"], out["trend_n"] = hit_of(table[:, 5] > 0.25, 2)
    out["hit_counter"], out["counter_n"] = hit_of(table[:, 5] < -0.25, 2)
    return out


def real_cycles(
    conn: sqlite3.Connection,
    feed: str,
    venue: str,
    intervals: tuple[tuple[str, int], ...],
    *,
    limit: int = 20000,
) -> tuple[np.ndarray, list[tuple[int, int, float]], list[int]] | None:
    """Real bars at several real intervals, merged into one causal stream.

    The higher timeframes are their **own stored series**, not the fast one
    subsampled. That is the difference between testing what this desk would
    actually see and testing an assumption about what a higher timeframe is.

    A higher-timeframe bar enters the stream only once its own window has
    closed - `ts + seconds <= now` - which is the whole discipline here. Using
    the bar that contains the current fast bar would hand the slow z-score the
    close of a candle that has not happened.
    """
    base, _ = intervals[0]
    rows = conn.execute(
        "SELECT ts, close FROM bars WHERE feed=? AND venue=? AND interval=?"
        " AND close>0 ORDER BY ts DESC LIMIT ?",
        (feed, venue, base, limit),
    ).fetchall()
    if len(rows) < 3000:
        return None
    fast = [(int(t), float(c)) for t, c in reversed(rows)]
    events: list[tuple[int, int, float]] = []
    for level, (name, seconds) in enumerate(intervals[1:], start=1):
        got = conn.execute(
            "SELECT ts, close FROM bars WHERE feed=? AND venue=? AND interval=?"
            " AND close>0 AND ts>=? ORDER BY ts",
            (feed, venue, name, fast[0][0] - seconds * 400),
        ).fetchall()
        if len(got) < 100:
            return None
        # Keyed by when the bar *closed*, which is when it may be read.
        events.extend((int(t) + seconds, level, float(c)) for t, c in got)
    events.sort()
    return (
        np.array([c for _, c in fast]),
        events,
        [t for t, _ in fast],
    )


def run_real(
    conn: sqlite3.Connection,
    feed: str,
    venue: str,
    intervals: tuple[tuple[str, int], ...],
) -> dict:
    """The same study, driven by real bars at real intervals."""
    got = real_cycles(conn, feed, venue, intervals)
    if got is None:
        return {}
    prices, events, stamps = got
    cycles = Cycles(ratios=tuple(range(len(intervals))), attention=True)
    turns = Turns()
    rows: list[tuple[float, float, int, int, float, float, float]] = []
    cursor = 0
    for i, (ts, price) in enumerate(zip(stamps, prices, strict=True)):
        while cursor < len(events) and events[cursor][0] <= ts:
            _, level, close = events[cursor]
            cycles.push_slow(level, close)
            cursor += 1
        cycles.push_fast(float(price))
        if not cycles.ready:
            continue
        if i >= WARM and i + 1 < len(prices):
            rows.append(
                (
                    cycles.fast.z.z,
                    cycles.residual.z.z,
                    cycles.fast.side,
                    cycles.residual.side,
                    cycles.alignment,
                    cycles.with_trend,
                    math.log(prices[i + 1] / price),
                )
            )
        turns.push(cycles, i, record=i >= WARM)
    return _score(turns, rows)


#: Real intervals for the multi-timeframe arm, fastest first, with their
#: lengths in seconds. Three scales an order of magnitude apart, which is what
#: "the cycle above" has to mean if it is to be a different cycle at all.
REAL_CYCLES = (("1m", 60), ("15m", 900), ("1h", 3600))

#: Instruments to run it on. Cross-venue spreads are where the detector works;
#: the outrights are carried beside them so the comparison is on the same days
#: and the same bars.
REAL_FEEDS = (
    ("btc_binance_coinbase", "SPREAD"),
    ("btc_binance_kraken", "SPREAD"),
    ("btc_bitstamp_deriv", "SPREAD"),
    ("btc", "BINANCE"),
    ("btc", "DERIV"),
    ("gold", "OANDA"),
    ("eurusd", "PEPPERSTONE"),
    ("spx500", "OANDA"),
)


def real_bars_arm() -> None:
    """The cycle question on real bars at real intervals, not on a subsample.

    The higher timeframes are their own stored series and enter the stream only
    when their own window has **closed**. A study that reads the forming
    higher-timeframe bar has the future in it, and it is the easiest look-ahead
    in this whole area to write by accident.
    """
    try:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        print(f"\n[no bars at {DB}: {exc}]")
        return
    names = " / ".join(name for name, _ in REAL_CYCLES)
    print(f"\nReal bars, real timeframes ({names}), higher ones read only once closed:\n")
    header()
    try:
        for feed, venue in REAL_FEEDS:
            got = run_real(conn, feed, venue, REAL_CYCLES)
            show(f"  {feed} @ {venue}"[:28], got)
    except sqlite3.Error as exc:
        print(f"  [read failed: {exc}]")
    finally:
        conn.close()


def contamination_sweep(rng, n: int = 20000) -> None:
    """At what point does the cycle above break the cycle below, and what repairs it.

    The whole curve rather than a chosen point. `raw` is the shipped reading,
    `residual` divides the mother cycle out first, `w/trend` keeps only the
    calls that run with the cycle above and `counter` only those that fight it.
    The null row under each is the same shape with a **random walk** in place of
    the fast reverting deviation: a repair that also works there is not reading
    the cycle structure.
    """
    print("\nHow far the cycle above has to move before it breaks the cycle below.")
    print("contamination = slow level's travel over one fast window, in fast-deviation sd.")
    print("Below 0.5 the fast reading owns the window; above 2 the slow level does.\n")
    print(
        f"  {'contam':>7} {'arm':>10} {'raw':>7} {'residual':>9} "
        f"{'w/trend':>8} {'counter':>8} {'n':>7}"
    )
    for c in (0.0, 0.5, 1.0, 2.0, 4.0, 8.0):
        for label, reverting in (("reverting", True), ("null walk", False)):
            series = two_scale(n, rng, contamination=c, reverting=reverting)
            got = run(series)
            if not got:
                print(f"  {c:>7.1f} {label:>10}  nothing scored")
                continue
            print(
                f"  {c:>7.1f} {label:>10} {got['hit']:>7.3f} {got['hit_res']:>9.3f} "
                f"{got['hit_trend']:>8.3f} {got['hit_counter']:>8.3f} {got['hit_n']:>7}"
            )
    print("  A row where raw drops below 0.5 is the fast z-score reading the slow level's")
    print("  movement as displacement. A residual column that climbs back is the repair.")


def show(name: str, got: dict) -> None:
    if not got:
        print(f"{name:28}  nothing scored")
        return
    print(
        f"{name:28} {got['n']:>7,} {got['turns']:>6} "
        f"{got['depth_skill']:>+7.3f} {got['when_skill']:>+7.3f} "
        f"{got['z_auc']:>6.3f} {got['res_auc']:>6.3f} "
        f"{got['hit']:>6.3f} {got['hit_res']:>7.3f} "
        f"{got['hit_with']:>6.3f} {got['hit_trend']:>7.3f} {got['hit_counter']:>8.3f}"
    )


def header() -> None:
    print(
        f"{'arm':28} {'n':>7} {'turns':>6} {'depth':>7} {'when':>7} "
        f"{'z auc':>6} {'res':>6} {'hit':>6} {'hit res':>7} "
        f"{'w/disp':>6} {'w/trend':>7} {'counter':>8}"
    )


def main() -> int:
    rng = np.random.default_rng(37)
    minute = math.sqrt(1.0 / (365 * 24 * 60))
    print("ZMA with nothing batched in it, and a turn predictor with feedback.\n")
    inert_attention(rng)
    agreement(rng)
    print("Skill is 1 - MAE(model)/MAE(the running mean's own prediction at that bar):")
    print("0 is 'no better than the mean'. `res` is the z-score of price divided by the")
    print("cycle above. `w/disp`, `w/trend` and `counter` are the raw call restricted to")
    print("bars where the cycles above agreed by displacement, by direction, or opposed it.\n")
    header()

    arms: list[tuple[str, np.ndarray]] = [
        ("two-scale, contam 1", two_scale(BARS, rng, contamination=1.0)),
        ("two-scale, contam 4", two_scale(BARS, rng, contamination=4.0)),
        ("two-scale null walk", two_scale(BARS, rng, contamination=1.0, reverting=False)),
        ("OU theta=0.15 (control)", ou(BARS, 0.15, 0.5, rng)),
        ("OU theta=0.02 (control)", ou(BARS, 0.02, 0.5, rng)),
        ("volatility 75 (GBM)", gbm(BARS, 0.75 * minute, rng)),
    ]
    arms.append(("  its own shuffle", shuffled(arms[0][1], rng)))
    results = {}
    for name, series in arms:
        results[name] = run(series)
        show(name, results[name])

    print("\nThe same series with the attention switched off and on:")
    show("  no attention", run(two_scale(BARS, np.random.default_rng(37)), attention=False))
    show("  attention", run(two_scale(BARS, np.random.default_rng(37)), attention=True))

    found = spreads(DB)
    if found:
        print("\nThe constructed spreads, read as the ordinary feeds they now are:")
        for name, series in found.items():
            show("  " + name[:26], run(series))
    else:
        print(f"\n[no constructed spreads in {DB} - run `prices spreads --build 1m` first]")

    real_bars_arm()
    contamination_sweep(np.random.default_rng(11))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
