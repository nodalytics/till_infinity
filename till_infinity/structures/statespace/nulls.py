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
