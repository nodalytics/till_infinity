"""A filter member, watched by the FOCuS detector that was already here.

Romano, Eckley, Fearnhead and Rigaill, *Fast Online Changepoint Detection via
Functional Pruning CUSUM statistics*, JMLR 24 (2023), arXiv:2110.08205. Asked
for on 2026-10-11 after the comparison with BOCPD, and the conclusion there was
that the two do different jobs:

* **FOCuS detects.** It maximises a CUSUM likelihood ratio over *every*
  candidate change location and *every* change magnitude at once - exactly, not
  approximately - and it comes with a threshold, so the false-alarm rate is a
  choice rather than an emergent property of a hazard prior nobody fitted.
* **A filter member forecasts.** It answers `value`, `sd`, `band` and
  `loglike`: a predictive distribution. FOCuS yields a *statistic*, not a
  density, so it can never be a family member - it cannot be scored on held-out
  likelihood against `linear`, which is the one comparison this package
  insists on.

So the pairing is the answer rather than the choice, and `Paired` is it.

## This module used to contain a second FOCuS, and that was the bug

`structures/learning/focus.py` already implements it - the same statistic, the
same convex-hull pruning, and **tested against an O(n^2) brute-force reference
on every step**, which is a stronger guarantee than anything written here was
going to carry. Writing another one was duplication, and it was caught the way
duplication usually is here: not by review but by a *collision*. The
persistence registry keys classes by module basename and class name
(`shared/codec.py`), so two modules called `focus` holding two classes called
`Focus` both resolve to `focus.Focus`, one silently shadowed the other, and
restoring the origins detectors tried to build this class for the other one's
saved state. Two tests caught it in CI.

So the detector here is the existing one, and this module is named for what it
actually contributes. It runs **two instances**, up and down: that module is
one-sided on purpose - "moves got bigger" and "moves got smaller" are different
events - and both matter when the quantity being watched is a signed
innovation.

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

from .accruing import THRESHOLD, OneSided

HOUR = 3600.0

#: Readings before the detector is allowed to fire. A hull of two points will
#: happily report a large statistic, and a member's first few innovations are
#: not standard normal anyway - `linear` takes its first reading as its state.
WARMUP = 20


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
    #: Two one-sided detectors. The innovations are signed, and a member that
    #: has started reading high is a different failure from one reading low.
    _up: OneSided = field(default=None, repr=False)
    _down: OneSided = field(default=None, repr=False)
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
        if self._up is None:
            self._up = OneSided(threshold=self.threshold, up=True)
        if self._down is None:
            self._down = OneSided(threshold=self.threshold, up=False)

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
    def side(self) -> int:
        """Which direction the evidence points, `+1` high, `-1` low, `0` none."""
        if self.statistic <= 0.0:
            return 0
        return 1 if self._up.statistic >= self._down.statistic else -1

    @property
    def where(self) -> int:
        """The candidate reading the statistic attains, as an index."""
        return self._up.at if self.side >= 0 else self._down.at

    @property
    def candidates(self) -> int:
        """Surviving candidates across both hulls. The cost claim, observable."""
        return len(self._up.hull) + len(self._down.hull)

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
        if not math.isfinite(got):
            got = 0.0
        self._up.update(got, 1.0)
        self._down.update(got, 1.0)
        self.statistic = max(self._up.statistic, self._down.statistic)

        if self._up.seen >= self.warmup and self.statistic >= self.threshold:
            self.detections += 1
            # Carry the likelihood forward, rebuild, and start the detector
            # again from here.
            self._loglike += float(getattr(self._member, "loglike", 0.0))
            self._member = self.build()
            self._up.reset()
            self._down.reset()
            self._reset_at = when if when is not None else self._read_at
            # Seed the fresh member with the reading that caused the detection,
            # so it starts from the new regime rather than from nothing.
            self._member.update(measured, noise, when)  # type: ignore[union-attr]
        return innovation
