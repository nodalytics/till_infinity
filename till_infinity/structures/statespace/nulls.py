"""The nulls, as library code rather than as something each harness rebuilds.

`structures/learning/baseline.py` makes the argument this module acts on:

> Every touch that resolves goes to all three models **and** to `up_rate` - no
> model at all, the level's own record read straight off the feature, as the
> floor everything else has to clear.

The filter family has two such floors and neither was in the library. They lived
in research harnesses, were copied between them, and drifted - which is how both
defects below survived.

* `Walk` is the null for a **forecast**: the next value equals this one, with a
  band that diffuses as `sqrt(elapsed)`. Every member here has to separate from
  it, and the family's whole rule is that a member beats a *named* null.
* `Trailing` is the null for a **magnitude**: the standard deviation of recent
  moves. It has beaten a three-state HMM, a fifty-neighbour analogue on 0 of 20
  window-by-horizon cells, an Ising susceptibility, a panel of stale forecasts
  at seven lags, and a rank-then-map model trained across five instruments.
  Nothing in this repository has beaten it.

## Two defects the move exposed

Both were in the copy that every statespace comparison has been scored against,
and both flattered the members.

**`band` was defined twice.** The first definition returned a fixed interval and
the second one diffusing as `sqrt(h)`; Python keeps the last, so the first was
dead code that read as though it were doing something. Harmless by luck - the
surviving one is the correct one - but a reader checking the null's band would
have read the wrong function.

**The likelihood used the wrong spread.** `last_standardised` divided the
innovation by `sqrt(noise^2 + R)`, the predictive spread, while `loglike` used
`noise` alone. For a Gaussian the log density is
`-0.5 (i/s)^2 - log s`, so understating `s` inflates the quadratic penalty: the
null was scored with a spread smaller than the one it actually predicts with,
and **every member's likelihood margin over it was therefore overstated**. The
two now use the same number, which is what the `Filter` contract has always
said: `noise` is the measurement *variance*.

Nothing here is a model this desk would ship. They are the floor.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

#: Default predictive spread for `Walk`, in the caller's own units.
NOISE = 1.0


@dataclass(slots=True)
class Walk:
    """The next value equals this one. The null for a forecast.

    **Why it is the right null and not a straw man.** Every `selective` and
    `swarm` fit pinned `drift` at the top of its grid, and `drift` enters as
    `delta = hours * softplus(drift)`; as it grows, retention `exp(delta * A)`
    goes to zero and every state collapses onto the current reading. So "the
    next value equals this one" is the *limit* of that family rather than an
    outsider, and a member that cannot beat it has found nothing.

    Satisfies enough of `Filter` to be scored beside the members, and is
    deliberately **not** in `members()`.
    """

    noise: float = NOISE
    last: float | None = None
    at: float | None = None
    #: Bar length, learned as the smallest gap between readings, so the band can
    #: diffuse per bar without being told the timeframe.
    step: float = 0.0
    seen: int = 0
    loglike: float = 0.0
    last_standardised: float = 0.0
    existence: float = 1.0
    _read_at: float | None = field(default=None, repr=False)

    @property
    def value(self) -> float:
        return 0.0 if self.last is None else self.last

    @property
    def rate(self) -> float:
        """Zero. A walk has no slope, and inventing one would be a claim."""
        return 0.0

    @property
    def sd(self) -> float:
        return self.noise

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def state(self) -> tuple[float, ...]:
        return (self.value,)

    def predict(self, when: float) -> None:
        self.at = when

    def at_time(self, when: float) -> float:  # noqa: ARG002
        """The last reading, at every horizon. **Flat is the point.**

        `when` is ignored, deliberately and visibly: the signature matches the
        members so this can be scored beside them, and a null that used the
        argument would not be this null.

        A random walk has no view beyond one step, which is exactly why it is
        the right null: a member carrying real structure has to separate from a
        flat line as the horizon grows, and if it cannot then it has none.
        """
        return self.value

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        """Widening as `sqrt(elapsed)`, which is the other half of the null.

        A flat forecast with a *fixed* band would be a straw man: it would lose
        every coverage test for a reason that has nothing to do with its
        forecast. The honest null diffuses, and the bar length is learned from
        the intervals it has seen rather than passed in, so it needs no
        parameter the members do not have.
        """
        bars = 1.0
        if self.step > 0 and self.at is not None:
            bars = max((float(when) - self.at) / self.step, 0.0)
        half = sigmas * self.noise * math.sqrt(max(bars, 1.0))
        return (self.value - half, self.value + half)

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in a reading. `noise` is the measurement **variance**."""
        innovation = 0.0 if self.last is None else measured - self.last
        if self.last is not None:
            # **One spread, used for both.** See the module docstring: these
            # disagreed, and the disagreement overstated every member's margin.
            spread = math.sqrt(self.noise**2 + max(noise, 0.0))
            self.last_standardised = innovation / spread if spread > 0 else 0.0
            self.loglike += (
                -0.5 * (innovation / spread) ** 2 - 0.5 * math.log(2.0 * math.pi) - math.log(spread)
            )
        if when is not None and self._read_at is not None and when > self._read_at:
            gap = when - self._read_at
            self.step = gap if self.step <= 0 else min(self.step, gap)
        if when is not None:
            self._read_at = when
        self.last = measured
        self.seen += 1
        return innovation


#: The smallest number of observations a shuffled or rotated null will build
#: from. Below this the null is a handful of points and its extreme is noise.
LEAST_FOR_NULL = 64


def rotated(values: Sequence[float], shift: int) -> list[float]:
    """The same series at an offset: every marginal kept, every relationship cut.

    **The null for a claim about two series, when the claim is about one of
    them.** A rotation preserves each series *exactly* - every autocorrelation,
    all volatility clustering, all long memory, because it is the same data -
    and destroys only its alignment to anything else.

    That matters because the obvious alternative destroys the thing under test.
    A block shuffle scrambles volatility clustering across blocks, so a
    volatility relationship measured against a shuffled null is scored against
    a **volatility-free** null and is significant by construction. Measured:
    cross-instrument log-volatility correlation reads a median `0.5170` on
    traded instruments against a rotation null's `-0.0015`, with 104 of 107
    pairs beating the null's maximum.

    Returned as the cumulative sum of the rotated *increments*, re-anchored at
    the original start, so the wrap point is not a false jump in the level.

    Choose `shift` away from a multiple of the series' own period: a rotation
    by exactly one day leaves shared time-of-day structure intact and it gets
    scored as a relationship.
    """
    if len(values) < LEAST_FOR_NULL:
        return list(values)
    # **Rotate the increments, not the values.** Rotating the levels and then
    # differencing them replaces one real increment with the gap across the
    # wrap point, so the marginal is no longer preserved - which is the single
    # property this null exists for. Caught by asserting the increment multiset
    # is unchanged.
    steps = [values[i] - values[i - 1] for i in range(1, len(values))]
    at = int(shift) % len(steps)
    rolled = steps[at:] + steps[:at]
    out = [float(values[0])]
    for step in rolled:
        out.append(out[-1] + step)
    return out


def block_shuffled(values: Sequence[float], order: Sequence[int], blocks: int = 24) -> list[float]:
    """The series' own increments in reordered blocks: tails kept, dependence cut.

    **The null for a claim whose statistic is tail-sensitive.** A permutation of
    the increments preserves each marginal *exactly* - EURUSD's return kurtosis
    reads 18.11 before and 18.11 after - and `blocks` keeps the clustering
    inside a block while destroying it between them.

    This is the null a Dickey-Fuller screen needs, because the threshold moves
    with the **tails** and not with independence. Measured at 1h: the median
    return kurtosis is `20.07` over 20 traded instruments and `3.19` over 36
    Deriv synthetics, where Gaussian is 3.0 - so a synthetic-only null judges
    kurtosis-20 candidates against a kurtosis-3 reference. The split-ratio
    Dickey-Fuller bar reads `-3.46` with no real legs, `-3.94` with one and
    `-4.07` with two, and the count of surviving candidates goes from 17 to 0.

    `order` is the caller's permutation of the block indices, so the randomness
    stays with the caller and the same null can be reproduced.

    **Do not use this where the series' own time structure is the hypothesis**;
    use `rotated` there. Blending a series toward a block-shuffled copy of
    another scored `+104` nats against the `+36` the real factor earned, purely
    because smoothing a series fits a fixed-variance filter better - the null is
    what caught it.
    """
    if len(values) < LEAST_FOR_NULL or blocks < 1:
        return list(values)
    steps = [values[i] - values[i - 1] for i in range(1, len(values))]
    pieces = [steps[i : i + blocks] for i in range(0, len(steps), blocks)]
    picked = [pieces[i] for i in order if 0 <= i < len(pieces)]
    if len(picked) != len(pieces):
        # A partial order would silently shorten the series, which changes the
        # sample the null is compared on.
        picked = pieces
    out = [float(values[0])]
    for piece in picked:
        for step in piece:
            out.append(out[-1] + step)
    return out


def trailing(values: Sequence[float], span: int) -> list[float]:
    """Standard deviation of the last `span` increments, causally, per reading.

    **The null for a magnitude**, and the one nothing here has beaten. Written
    once because four harnesses had four copies, and a null that is re-typed
    per study is a null that eventually differs between studies.

    `span` is a **bar count**, because the caller knows its own timeframe and
    `inputs.Window.bars` is the conversion. Passing hours here would hide that
    conversion inside a function whose job is arithmetic.
    """
    out = [0.0] * len(values)
    if span < 2 or len(values) < 2:
        return out
    steps = [0.0] + [values[i] - values[i - 1] for i in range(1, len(values))]
    run = runsq = 0.0
    for i in range(1, len(values)):
        run += steps[i]
        runsq += steps[i] * steps[i]
        if i > span:
            run -= steps[i - span]
            runsq -= steps[i - span] * steps[i - span]
        count = min(i, span)
        if count >= 2:
            mean = run / count
            out[i] = math.sqrt(max(runsq / count - mean * mean, 0.0))
    return out


#: HAR's medium and long windows, in observations. Corsi's daily/weekly/monthly
#: on a daily realised variance; the names are the ratios, not the calendar.
HAR_WEEK = 5
HAR_MONTH = 22


def har(values: Sequence[float], week: int = HAR_WEEK, month: int = HAR_MONTH):
    """The floor for a **volatility** forecast: own value, own week, own month.

    `Walk` above is the floor for a forecast of a *level*. A forecast of
    volatility has a different and much higher floor, and it was not here.

    **Beating an AR(1) on realised volatility is easy and means nothing.** The
    long memory is most of what makes volatility forecastable at all, so a
    member that only beats its own last reading has beaten nothing. HAR -
    Corsi's heterogeneous autoregression - is the standard strong baseline and
    averages the own series over three horizons, which is why it is hard: it
    has already removed most of the measurement noise a cross-sectional or
    state-space estimator would offer to remove.

    Measured consequence: a cross-instrument volatility factor removes 4.3% of
    out-of-sample forecast error against *this* baseline on equities, and the
    same factor against an AR(1) would have looked far larger for no better
    reason than a weaker opponent.

    Returns the design rows `[own, own week mean, own month mean]` aligned to
    the target `values[t + 1]`, with the first `month` observations consumed, so
    a caller fits and scores rather than being handed a fitted number.
    """
    rows: list[list[float]] = []
    targets: list[float] = []
    if len(values) < month + 2:
        return rows, targets
    for t in range(month - 1, len(values) - 1):
        rows.append(
            [
                float(values[t]),
                sum(values[t - week + 1 : t + 1]) / week,
                sum(values[t - month + 1 : t + 1]) / month,
            ]
        )
        targets.append(float(values[t + 1]))
    return rows, targets


def spearman(xs: Sequence[float], ys: Sequence[float], shift: int = 0) -> float:
    """Rank correlation, with an optional rotation of `xs`.

    Here because every harness that scores against `trailing` needs it, and
    because the **rotation** is the matched control this desk insists on: the
    same feature, same distribution, same autocorrelation, no alignment. A
    reading its rotated self matches is a marginal rather than a signal.

    `shift` is a count of positions. `research/ideas/lag_agreement.py` passed a
    fixed 1013 on 999 points - a rotation of 14, which destroys nothing - so
    callers should pass a fraction of `len(xs)`.
    """
    n = len(xs)
    if n < 30 or n != len(ys):
        return float("nan")

    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        for rank, i in enumerate(order):
            out[i] = float(rank)
        return out

    rotated = [xs[(i + shift) % n] for i in range(n)]
    rx, ry = ranks(rotated), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else float("nan")


def control(xs: Sequence[float], ys: Sequence[float]) -> float:
    """The matched control: `spearman` averaged over three rotations.

    Quarter, half and three quarters of the sample, so the answer does not
    depend on one arbitrary offset and cannot accidentally be a rotation of
    nothing.
    """
    n = len(xs)
    got = [spearman(xs, ys, shift=max(int(n * fraction), 1)) for fraction in (0.25, 0.5, 0.75)]
    usable = [v for v in got if not math.isnan(v)]
    return statistics.fmean(usable) if usable else float("nan")


#: GARCH(1,1) parameters: the constant, the shock loading and the memory.
#: `shock + memory` is the persistence and must stay below one.
GARCH_CONSTANT = 0.02
GARCH_SHOCK = 0.10
GARCH_MEMORY = 0.88

#: Degrees of freedom for the innovation. Five is the usual choice for a
#: return series: finite variance, infinite fourth moment.
GARCH_TAIL = 5.0


def garch(
    count: int,
    *,
    seed: int,
    sigma: float = 1.0,
    constant: float = GARCH_CONSTANT,
    shock: float = GARCH_SHOCK,
    memory: float = GARCH_MEMORY,
    tail: float = GARCH_TAIL,
) -> list[float]:
    """Clustered volatility with an exponential decay and fat tails.

    **The control for anything that might be reading volatility clustering**,
    and it lives here rather than in a harness because three harnesses had
    three copies and all three were wrong in the same way.

    ## The defect, because it is instructive

    A Student-t innovation has to be **standardised** before it is fed back
    into the variance recursion. A raw `t(nu)` has variance `nu / (nu - 2)` -
    five thirds at `nu = 5` - so a recursion written as

        variance = constant + shock * previous^2 + memory * variance

    with an unstandardised `previous` has an effective persistence of
    `shock * nu/(nu-2) + memory`, which at the usual 0.10 and 0.88 is
    **1.046**: explosive. Measured, the variance reached `1e110` and 98.8% of
    the returns sat on whatever clamp the caller had applied, which makes the
    "GARCH surrogate" a clamped square wave with a log-volatility swing
    *below* the estimation-noise floor.

    A control that is accidentally a near-constant series is worse than no
    control, because it still produces a number and the number looks like a
    comparison. The scaling by `sqrt((nu - 2) / nu)` below is the whole fix,
    and `persistence` is exposed so a caller can assert it is under one.

    `sigma` scales the output to a target unconditional standard deviation,
    so the surrogate can be matched to the series it is controlling for.
    """
    if tail <= 2.0:
        raise ValueError("a t innovation needs more than two degrees of freedom")
    if shock + memory >= 1.0:
        raise ValueError(
            f"persistence {shock + memory} is not below one: the variance would explode"
        )

    rng = random.Random(seed)
    # Unit-variance t: a normal over the root of a chi-square mean, rescaled
    # by `sqrt((nu-2)/nu)` so the recursion's persistence is `shock + memory`.
    scale = math.sqrt((tail - 2.0) / tail)
    half = int(tail)
    stationary = constant / (1.0 - shock - memory)

    variance, previous = stationary, 0.0
    out: list[float] = []
    for _ in range(count):
        variance = constant + shock * previous * previous + memory * variance
        chi = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(half))
        draw = rng.gauss(0.0, 1.0) * math.sqrt(half / max(chi, 1e-6)) * scale
        previous = math.sqrt(variance) * draw
        out.append(previous * sigma / math.sqrt(stationary))
    return out


def garch_persistence(shock: float = GARCH_SHOCK, memory: float = GARCH_MEMORY) -> float:
    """`shock + memory`. Below one for a stationary surrogate, and the number
    a caller should assert rather than assume."""
    return shock + memory
