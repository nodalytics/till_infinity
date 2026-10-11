"""FOCuS as the detector, a filter member as the forecaster, paired.

Romano, Eckley, Fearnhead and Rigaill, *Fast Online Changepoint Detection via
Functional Pruning CUSUM statistics*, JMLR 24 (2023), arXiv:2110.08205. Asked
for on 2026-10-11 after the comparison with BOCPD, and the conclusion there was
that the two do different jobs:

* **FOCuS detects.** It maximises a CUSUM likelihood ratio over *every*
  candidate change location and *every* change magnitude at once - exactly, not
  approximately - at an expected cost logarithmic in the number of
  observations, and it comes with a threshold, so the false-alarm rate is a
  choice rather than an emergent property of a hazard prior nobody fitted.
* **A filter member forecasts.** It answers `value`, `sd`, `band` and
  `loglike`: a predictive distribution. FOCuS yields a *statistic*, not a
  density, so it can never be a family member - it cannot be scored on held-out
  likelihood against `linear`, which is the one comparison this package
  insists on.

So the pairing is the answer rather than the choice, and `Paired` is it.

## FOCuS runs on the standardised innovations, which is what makes this work

The detector's Gaussian case assumes a **known** variance. That is usually the
awkward part, and here it is free: `last_standardised` is the innovation divided
by its own predictive spread, so under a correctly specified member the series
of them is standard normal **by construction**. Every member reports it, and
making it mean the same thing on all of them was today's work.

A change in the *mean* of that series is therefore not a change in price - it is
the member's state having stopped describing the series. Which is the event
worth detecting: not "the market moved" but "my model of it is now wrong".

That also makes the detector agnostic to the member. Anything satisfying
`Filter` can be paired, including `changepoint` itself - a Bayesian regime model
watched by a frequentist detector is not redundant, because they are detecting
different things: BOCPD asks whether the *level* changed and this asks whether
the *model* did.

## The pruning, and why the hull is the whole algorithm

For a change at `tau` with post-change mean free, the Gaussian log likelihood
ratio at time `t` maximises to

    Q_t(tau) = (S_t - S_tau)^2 / (2 (t - tau))

on standardised data, where `S` is the cumulative sum. Evaluating every `tau` is
`O(t)` a step. The functional-pruning insight is that `Q_t` as a function of the
post-change mean is a quadratic per candidate, and a candidate dominated by
another can never become the maximiser again - so the survivors are the points
`(i, S_i)` on a **convex hull**, and the hull stays small.

Two hulls, because a rise and a fall are different events and a desk wants to
know which: the lower hull maximises the upward statistic and the upper hull the
downward one.

## What this is not

**Not a trading signal.** A detection says the model has stopped fitting, which
is a reason to re-estimate rather than to take a position - and every
directional test in `README.md` came back a coin. The honest use is the one the
guiding principles name: a member whose parameters drift faster than they can be
estimated is the failure mode with no remedy, and this is how you find out it is
happening.

## Nothing here publishes

Same rule as the rest of the package. The null for `Paired` is **the member
alone**, on held-out likelihood: if resetting on detection does not improve the
forecast, then either the detector is firing on noise or the regimes it finds do
not matter, and both are answers.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

HOUR = 3600.0

#: Threshold on the FOCuS statistic. `Q` is a maximised log likelihood ratio,
#: so `2Q` is chi-squared-ish with one degree of freedom under the null and a
#: threshold of 10 corresponds to a nominal `p` near 1e-3 per observation -
#: before any correction for maximising over candidates, which this does not
#: attempt. **Not calibrated**, and the right way to set it is the realised
#: false-alarm rate on a series known to have no changes, which the Deriv
#: synthetics are the closest thing to.
THRESHOLD = 10.0

#: Readings before the detector is allowed to fire. A hull of two points will
#: happily report a large statistic, and a member's first few innovations are
#: not standard normal anyway - `linear` takes its first reading as its state.
WARMUP = 20


@dataclass(slots=True)
class Focus:
    """The FOCuS statistic over standardised observations, both directions.

    `update` returns the current statistic. `where` is the candidate change
    point that attains it, as an index, so a caller can say *when* rather than
    only *whether*.
    """

    #: Cumulative sum of the observations seen.
    total: float = 0.0
    seen: int = 0
    #: `(index, cumulative sum)` on each hull. Small by construction.
    _lower: list[tuple[int, float]] = field(default_factory=list)
    _upper: list[tuple[int, float]] = field(default_factory=list)
    #: The maximising candidate from the last `update`, and its direction.
    where: int = 0
    side: int = 0

    def __post_init__(self) -> None:
        if not self._lower:
            self._lower = [(0, 0.0)]
        if not self._upper:
            self._upper = [(0, 0.0)]

    @staticmethod
    def _quadratic(total: float, seen: int, point: tuple[int, float]) -> float:
        """`(S_t - S_i)^2 / (2 (t - i))`, the maximised log likelihood ratio."""
        span = seen - point[0]
        if span <= 0:
            return 0.0
        gap = total - point[1]
        return gap * gap / (2.0 * span)

    def _prune(self, hull: list[tuple[int, float]], upward: bool) -> None:
        """Drop candidates that can never maximise again.

        The convex-hull condition: three consecutive points where the middle one
        lies on the wrong side of the line joining its neighbours can be
        removed, because any later `t` that prefers it prefers one of them
        more. This is the functional pruning - without it the candidate set is
        the whole series and the cost is linear.
        """
        hull.append((self.seen, self.total))
        while len(hull) >= 3:
            (i1, s1), (i2, s2), (i3, s3) = hull[-3], hull[-2], hull[-1]
            left = (s2 - s1) * (i3 - i2)
            right = (s3 - s2) * (i2 - i1)
            # Keep the hull convex in the direction the statistic cares about.
            if (left >= right) if upward else (left <= right):
                del hull[-2]
            else:
                break

    def update(self, value: float) -> float:
        """Fold in one standardised observation and return the statistic."""
        if not math.isfinite(value):
            return 0.0
        self.total += value
        self.seen += 1
        self._prune(self._lower, upward=True)
        self._prune(self._upper, upward=False)

        best, at, side = 0.0, 0, 0
        for point in self._lower:
            if self.total - point[1] <= 0:
                continue
            got = self._quadratic(self.total, self.seen, point)
            if got > best:
                best, at, side = got, point[0], 1
        for point in self._upper:
            if self.total - point[1] >= 0:
                continue
            got = self._quadratic(self.total, self.seen, point)
            if got > best:
                best, at, side = got, point[0], -1
        self.where, self.side = at, side
        return best

    def reset(self) -> None:
        """Start again from here. Called after a detection is acted on."""
        self.total = 0.0
        self.seen = 0
        self._lower = [(0, 0.0)]
        self._upper = [(0, 0.0)]
        self.where = 0
        self.side = 0

    @property
    def candidates(self) -> int:
        """How many survive pruning. The claim about cost, observable.

        Logarithmic in expectation, so this should stay small while `seen`
        grows - and a test asserts exactly that, because a hull that grows
        linearly is the pruning being broken in a way nothing else would show.
        """
        return len(self._lower) + len(self._upper)


@dataclass(slots=True)
class Paired:
    """A filter member, watched by FOCuS, rebuilt when the model stops fitting.

    Satisfies `Filter` by delegating to the member, so it can be scored against
    the member alone - which is its null. Adds `statistic`, `detections` and
    `hours_since_reset`.
    """

    build: Callable[[], object]
    threshold: float = THRESHOLD
    warmup: int = WARMUP

    _member: object = field(default=None, repr=False)
    _focus: Focus = field(default_factory=Focus, repr=False)
    #: Statistic from the last reading, and how many times it has fired.
    statistic: float = 0.0
    detections: int = 0
    #: When the member was last rebuilt, and the last reading's time.
    _reset_at: float | None = field(default=None, repr=False)
    _read_at: float | None = field(default=None, repr=False)
    #: Accumulated across resets, because a rebuilt member starts at zero and
    #: the comparison against the unpaired member needs the whole run.
    _loglike: float = 0.0

    def __post_init__(self) -> None:
        if self._member is None:
            self._member = self.build()

    # ----------------------------------------------------- the member's view

    @property
    def value(self) -> float:
        return float(getattr(self._member, "value", 0.0))

    @property
    def rate(self) -> float:
        return float(getattr(self._member, "rate", 0.0))

    @property
    def sd(self) -> float:
        return float(getattr(self._member, "sd", 0.0))

    @property
    def at(self) -> float | None:
        return getattr(self._member, "at", None)

    @property
    def seen(self) -> int:
        return int(getattr(self._member, "seen", 0))

    @property
    def loglike(self) -> float:
        """Accumulated across resets.

        A rebuilt member's own `loglike` restarts at zero, and comparing that
        with an unpaired member's would flatter this one by throwing away every
        reading before the last detection.
        """
        return self._loglike + float(getattr(self._member, "loglike", 0.0))

    @property
    def last_standardised(self) -> float:
        return float(getattr(self._member, "last_standardised", 0.0))

    @property
    def existence(self) -> float:
        return float(getattr(self._member, "existence", 1.0))

    def at_time(self, when: float) -> float:
        return float(self._member.at_time(when))  # type: ignore[union-attr]

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        return self._member.band(when, sigmas)  # type: ignore[union-attr]

    def state(self) -> tuple[float, ...]:
        return tuple(self._member.state())  # type: ignore[union-attr]

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return self._member.observation()  # type: ignore[union-attr]

    def output(self) -> tuple[float, ...]:
        return self._member.output()  # type: ignore[union-attr]

    # -------------------------------------------------------------- the pair

    @property
    def hours_since_reset(self) -> float:
        """How long the current model has stood. In **hours**, not readings.

        The same argument as everywhere else here: "forty bars" is forty bars
        times a timeframe, and this has to mean one thing across series.
        """
        if self._reset_at is None or self._read_at is None:
            return 0.0
        return max((self._read_at - self._reset_at) / HOUR, 0.0)

    def predict(self, when: float) -> None:
        self._member.predict(when)  # type: ignore[union-attr]
        if self._reset_at is None:
            self._reset_at = when

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in a reading, then test whether the member still describes it.

        **Order matters and this is the only correct one.** The member updates
        first, which produces the standardised innovation; the detector reads
        that; and a reset happens *after*, so the reading that triggered the
        detection has already been used. Resetting before would discard the
        evidence that there was anything to reset for.
        """
        innovation = self._member.update(measured, noise, when)  # type: ignore[union-attr]
        if when is not None:
            self._read_at = when
            if self._reset_at is None:
                self._reset_at = when

        got = float(getattr(self._member, "last_standardised", 0.0))
        self.statistic = self._focus.update(got)

        if self._focus.seen >= self.warmup and self.statistic >= self.threshold:
            self.detections += 1
            # Carry the likelihood forward, rebuild, and start the detector
            # again from here.
            self._loglike += float(getattr(self._member, "loglike", 0.0))
            self._member = self.build()
            self._focus.reset()
            self._reset_at = when if when is not None else self._read_at
            # Seed the fresh member with the reading that caused the detection,
            # so it starts from the new regime rather than from nothing.
            self._member.update(measured, noise, when)  # type: ignore[union-attr]
        return innovation
