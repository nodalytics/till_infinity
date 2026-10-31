"""Turn depth, ported from v1 as a dispersion quantity.

Asked for on 2026-10-17 - "port the turn depth onto the dispersion subject" -
and it is the best-justified port out of v1 because it is one of that package's
few measured-positive results, and because what it measured is the same split
this package has just reorganised itself around.

`structures/cycles.py` runs causal turn detection on a price leg and two online
heads predicting the next turn's **depth** and **when**. Its own docstring
states the verdict:

> The turn depth is predictable where the process reverts. Skill against the
> running mean is negative or zero on every simulated arm and positive on **8
> of 8 constructed spreads, +0.03 to +0.19**. **How long** until the turn is
> not: `when` scores positive on the nulls too, so its positive values are a
> property of the metric rather than of the series.

**Depth is a magnitude and timing is not.** That is a dispersion result and a
direction-and-timing null, measured on different data and by different
machinery from today's dispersion work, which reached the same shape. So depth
belongs in the half this package now claims, and this is where it goes.

## What carries over, and what deliberately does not

**The quantity carries.** A turn's depth is how far price travelled on the
completed move, in volatility units - positive, and logged here so the state
is unconstrained, which is the same treatment `subjects.DISPERSION` gives a
bar's variance.

**The detector does not.** v1 marks a turn when price retraces `TURN_SIGMAS =
2.0` of its leg; this uses `displacements.sequence`, which is built on
`inputs.pivots` and marks a reversal where it is **confirmed** rather than
where it happened. Both are causal and they are not the same event, so the
numbers here are **not comparable to v1's** and no claim should be made that
they reproduce it. What is comparable is the *shape* of the result: whether a
model beats the running mean on depth, and whether it beats it on duration.

**The baseline carries, and it is load-bearing.** v1's positive result is
stated as skill against a **causal running mean**, so that is the baseline
here, maintained inside `Skill` rather than passed in - because a result
quoted against one baseline and computed against another is the easiest way to
lose this finding while appearing to keep it.

**The `when` arm carries too, precisely because it failed.** A port that kept
only the working half would be unable to reproduce the part that says `when`'s
positive skill is an artefact of the metric. An arm that is expected to read
positive on a null has to be present for the null to catch it.

## The member the family does not have

Depth mean-reverts, which is why v1 found it predictable "where the process
reverts" - and `reverting.Reverting` reverts the **rate** to zero, leaving the
value integrated. It therefore models a random walk in depth, not a reversion
to a level, and a random walk cannot beat a running mean on a mean-reverting
magnitude. The same gap turned up in `research/docs/dispersion-forecast.md`,
where an AR(1) arm had to be written for the same reason.

So `ar1` is here as a first-class arm rather than as a convenience: it is the
two-parameter model this quantity actually wants, and any family member has to
beat **it** and not just the mean.

## Nothing here emits a price

A depth is a distance, not a destination. Turning one into a price is
`projecting.py`'s job and only its job.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .displacements import Displacement

#: Measurement variance handed to a member reading log depth. A placeholder
#: that says so, matching `subjects.TURN_DEPTH`: a single swing's size is an
#: exact distance between two confirmed extremes, so the noise here is not
#: estimation error in the measurement but the part of the next depth no state
#: can carry. Unfitted; the fit has the same shape as every other subject's.
NOISE = 0.25

#: Observations before a skill is reported. Below this the baseline is a mean
#: of two or three numbers and the ratio is noise with a sign.
LEAST = 30


@dataclass(frozen=True, slots=True)
class Turn:
    """One completed turn, as the pair a member consumes.

    Named `Turn` rather than `Depth` because `interacting.Depth` already exists
    in this package and means something else - a sweep depth as a posterior -
    and two classes with one name in a package is how a caller imports the
    wrong one.

    `when` is the **confirmation** time and not the time the move ended. The
    two differ by the pivot's confirmation lag, and using the end time would
    let a member fold in a reading that was not yet knowable - which is the
    leak `displacements.Displacement` carries both timestamps to prevent.
    """

    when: float
    #: The measurement: log size in volatility units, or the raw size.
    value: float
    #: Log duration in hours, or the raw hours - the arm that is expected to
    #: fail, kept so that it can.
    span: float
    direction: int


def depths(moves: Iterable[Displacement], *, logged: bool = True) -> list[Turn]:
    """A displacement sequence as depths, on the turn clock rather than the bar clock.

    `logged` is the modelling space. True gives log size and log hours, which
    is what a state should carry for a positive quantity; False gives the raw
    units v1 scored in, so a harness can report both and neither number is
    quietly presented as the other.
    """
    out: list[Turn] = []
    for move in moves:
        if move.size <= 0.0 or move.hours <= 0.0:
            continue
        out.append(
            Turn(
                when=float(move.confirmed),
                value=math.log(move.size) if logged else float(move.size),
                span=math.log(move.hours) if logged else float(move.hours),
                direction=int(move.direction),
            )
        )
    return out


def from_pivots(found: Iterable[object], *, unit: float, logged: bool = True) -> list[Turn]:
    """Depths straight from `pivoting.Pivot`s, bypassing `displacements`.

    `depths(sequence(...))` goes through the fixed-span fractal detector, which
    is the one `pivoting.py` was written to improve on - scale-blind,
    magnitude-blind, fixed confirmation lag and no alternation. This takes the
    directional-change pivots instead, so a harness can ask which detector
    produces the more forecastable depth series rather than assuming.

    The size is the leg between consecutive extremes in volatility units, which
    is the same quantity `Displacement.size` carries, and `when` is again the
    **confirmation** time of the closing pivot.
    """
    if unit <= 0:
        return []
    pivots = list(found)
    out: list[Turn] = []
    for a, b in itertools.pairwise(pivots):
        size = abs(float(b.level) - float(a.level)) / unit
        hours = (float(b.at) - float(a.at)) / 3600.0
        if size <= 0.0 or hours <= 0.0:
            continue
        out.append(
            Turn(
                when=float(b.confirmed),
                value=math.log(size) if logged else size,
                span=math.log(hours) if logged else hours,
                direction=1 if float(b.level) > float(a.level) else -1,
            )
        )
    return out


@dataclass(slots=True)
class Skill:
    """Absolute error against a causal running mean, which is how v1 stated it.

    The baseline is kept here rather than supplied, so an arm cannot be scored
    against a different one than it is reported against. Both errors are sums
    of absolute deviations, because that is the loss v1's skill was computed
    on and changing it would change the number without changing the claim.
    """

    error: float = 0.0
    base: float = 0.0
    settled: int = 0
    _seen: int = 0
    _total: float = 0.0

    def observe(self, guess: float, actual: float) -> None:
        """Score one prediction, then fold the outcome into the baseline.

        In that order. The baseline predicts from what it had **before** this
        observation, exactly as the model does, so neither sees the answer.
        """
        if self._seen:
            mean = self._total / self._seen
            self.error += abs(float(guess) - float(actual))
            self.base += abs(mean - float(actual))
            self.settled += 1
        self._seen += 1
        self._total += float(actual)

    @property
    def warm(self) -> bool:
        return self.settled >= LEAST

    @property
    def skill(self) -> float:
        """`1 - error / baseline_error`. Positive beats the running mean."""
        if not self.warm or self.base <= 0.0:
            return float("nan")
        return 1.0 - self.error / self.base


@dataclass(slots=True)
class AR1:
    """Online AR(1) on a scalar: the model a mean-reverting magnitude wants.

    Three running sums and nothing else. It is here because the family has no
    value-reverting member - `reverting` reverts the rate and leaves the value
    integrated - so without this the only arms would be a random walk and a
    constant, and the interesting comparison would be missing.

    Every quantity is accumulated from readings already folded in, so `guess`
    is a prediction and not a fit.
    """

    seen: int = 0
    total: float = 0.0
    square: float = 0.0
    cross: float = 0.0
    last: float = 0.0

    def observe(self, value: float) -> None:
        value = float(value)
        if self.seen:
            mean = self.total / self.seen
            self.cross += (self.last - mean) * (value - mean)
            self.square += (self.last - mean) ** 2
        self.seen += 1
        self.total += value
        self.last = value

    @property
    def guess(self) -> float:
        """The next value, reverting from `last` toward the mean seen so far."""
        if self.seen < 2 or self.square <= 0.0:
            return self.total / self.seen if self.seen else 0.0
        mean = self.total / self.seen
        phi = self.cross / self.square
        # Clamped to the stationary range: a fitted `phi` outside it is a unit
        # root the sample cannot support, and letting it through turns a
        # prediction into an extrapolation.
        phi = max(-0.999, min(0.999, phi))
        return mean + phi * (self.last - mean)


@dataclass(slots=True)
class Turns:
    """Every arm on one depth series, scored against the same running mean.

    `member` is optional and may be any `family.Filter`. It is driven on the
    **turn clock** - `update` is called at each confirmation time - which is
    the clock `displacements.py` argues for: the sequence advances when price
    turns, not when the bar closes.
    """

    noise: float = NOISE
    member: object | None = None
    #: The arm that is expected to fail. Kept so the null can catch it.
    predict_span: bool = True

    depth: Skill = field(default_factory=Skill)
    span: Skill = field(default_factory=Skill)
    depth_walk: Skill = field(default_factory=Skill)
    depth_member: Skill = field(default_factory=Skill)

    _depth_ar: AR1 = field(default_factory=AR1)
    _span_ar: AR1 = field(default_factory=AR1)

    def observe(self, turn: Turn) -> None:
        """Fold in one completed turn, scoring every arm before it is seen."""
        self.depth.observe(self._depth_ar.guess, turn.value)
        self.depth_walk.observe(self._depth_ar.last, turn.value)
        if self.member is not None:
            guess = (
                float(getattr(self.member, "value", 0.0))
                if getattr(self.member, "seen", 0)
                else self._depth_ar.guess
            )
            self.depth_member.observe(guess, turn.value)
            self.member.update(turn.value, self.noise, turn.when)
        self._depth_ar.observe(turn.value)

        if self.predict_span:
            self.span.observe(self._span_ar.guess, turn.span)
            self._span_ar.observe(turn.span)

    def read(self) -> dict[str, float]:
        """Every arm's skill against the running mean, and how many settled."""
        out = {
            "depth ar1": self.depth.skill,
            "depth walk": self.depth_walk.skill,
            "settled": float(self.depth.settled),
        }
        if self.member is not None:
            out["depth member"] = self.depth_member.skill
        if self.predict_span:
            out["span ar1"] = self.span.skill
        return out


def score(
    series: Sequence[Turn], *, member: object | None = None, noise: float = NOISE
) -> dict[str, float]:
    """Drive every arm over one depth series and read the skills off."""
    turns = Turns(noise=noise, member=member)
    for turn in series:
        turns.observe(turn)
    return turns.read()
