"""The other door the exogenous channel can come through: `Q`, not `B u`.

`inputs.py` builds an exogenous channel - windows from seconds to weeks,
slopes, EMAs, session shares, realised variance - and until today nothing
consumed it. `linear.Gaussian` now takes `control` and applies `x <- x + B u
dt`, which is the contract's own form and the obvious reading of "wire up the
input channel".

**It is the wrong door for the inputs we actually have, and the evidence says
so.** The candidates named for I8 - hour-of-day share, activity - do not move
where the level *is*; they move how far it is likely to go. That is a
variance, and a variance belongs in `Q`. Putting it in `B u` would be asserting
that a busy hour pushes price in a direction, which is a claim this desk has
refuted in every form it has tested.

So both doors exist and the harness decides. `Driven` is the `Q` one.

## Two signals come through it, and one of them needs no caller

`control` is the exogenous channel: a number the caller computes per reading
from `inputs.py` and passes in. `clock` is the **endogenous** one, a function
of the time alone - and it needs no caller because the time is already in
`predict`'s first argument.

That second door is there because it is the one that measured positive.
`statespace-seasonal.md` fitted a time-of-day profile to innovation size and
found FX and metals move three to four times as far per hour at 14:00-15:00
UTC as at 03:00, worth +197 nats at the median against the same member with a
constant `Q`, nothing on markets with a known generator and no session, and
**-443 with the clock deliberately misaligned**. `Profile.factor` is exactly
the callable this takes.

The two compose multiplicatively, because they are both ratios on a variance:
a busy hour and a busy exogenous reading should reinforce rather than one
overwriting the other. `clock=None` leaves the behaviour exactly as it was,
which keeps the control arm available.

## It is `Yielding` with the signal supplied from outside

`yielding.py` scales a member's process noise by its own changepoint
posterior. This scales the same lever by a number the caller passes per
reading, which makes it the exogenous-input member rather than the
self-detecting one - and it reuses `predict`'s `control` argument, so the two
doors take the **same** input through the **same** parameter and differ only in
what they do with it. That is the comparison the harness needs: not two
different inputs, one input and two mechanisms.

## Nothing here publishes

The null is the member alone, on held-out likelihood, plus the `B u` arm on the
same input. If neither door helps, the channel is features nobody needs and
`inputs.py` should say so.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

#: How much the lever moves per unit of input. `0.0` disables the mechanism,
#: which is the control arm.
GAIN = 1.0

#: The attribute each member exposes as its process-noise scale.
LEVER = "jerk"


@dataclass(slots=True)
class Driven:
    """A member whose process noise is scaled by an exogenous input.

    Satisfies `Filter` by delegating. `predict(when, control=u)` sets the lever
    to `base * (1 + gain * u)`, floored just above zero: a process noise of
    zero is a state that cannot move at all, which no input should be able to
    assert however negative it is.
    """

    build: Callable[[], object]
    gain: float = GAIN
    lever: str = LEVER

    #: A **variance** multiplier from the time alone, normally
    #: `seasonal.Profile.factor`. Multiplies the lever beside `control`.
    #:
    #: It takes a variance factor rather than a size factor so the squaring
    #: lives in whatever produced the profile. A caller passing a
    #: standard-deviation profile here would under-drive every busy hour by
    #: its own square, and that mistake is invisible in the output - which is
    #: why the type is named in `Profile.factor` and not left to a comment.
    clock: Callable[[float], float] | None = None
    #: Smallest multiple of the member's own process noise. An input is allowed
    #: to quieten a member, not to freeze it.
    floor: float = 0.01

    _member: object = field(default=None, repr=False)
    _base: float = 0.0
    #: The **total** factor applied at the last reading, and its running mean,
    #: so what the input actually did is observable rather than assumed.
    softness: float = 1.0
    average: float = 1.0
    #: The two channels' contributions separately. Without these a member that
    #: is being driven hard looks the same whether the clock or the caller did
    #: it, and the harness cannot attribute a gain to a door.
    exogenous: float = 1.0
    timed: float = 1.0
    _total: float = field(default=0.0, repr=False)
    _counted: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        if self._member is None:
            self._member = self.build()
        if not hasattr(self._member, self.lever):
            raise AttributeError(
                f"{type(self._member).__name__} has no '{self.lever}' to drive. "
                "A member that cannot name its process noise declines to be "
                "driven, which is a statement about the member."
            )
        self._base = float(getattr(self._member, self.lever))

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
        return float(getattr(self._member, "loglike", 0.0))

    @loglike.setter
    def loglike(self, value: float) -> None:
        """Forwarded to the member, so a harness can zero it at a boundary.

        Without this the wrapper is read-only and a held-out comparison -
        which works by zeroing the likelihood at the train/test split - fails
        on the wrapper and succeeds on the member it wraps. That is a
        comparison the wrapper silently cannot take part in.
        """
        self._member.loglike = float(value)  # type: ignore[union-attr]

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

    def output(self) -> tuple[float, ...]:
        return self._member.output()  # type: ignore[union-attr]

    # --------------------------------------------------------------- driving

    def predict(self, when: float, control: float = 0.0) -> None:
        """Scale the lever by the input, **then** advance.

        The process noise applies over the interval being advanced, so the
        factor has to be in place before `predict` runs. Scaling afterwards
        would apply this reading's input to the *next* step.
        """
        self.exogenous = 1.0 + self.gain * control
        self.timed = float(self.clock(when)) if self.clock is not None else 1.0
        # Floored on the product rather than on each channel, because the
        # floor is a statement about the member - a process noise of zero is a
        # state that cannot move at all - and not about either signal.
        self.softness = max(self.exogenous * self.timed, self.floor)
        self._total += self.softness
        self._counted += 1
        self.average = self._total / self._counted
        setattr(self._member, self.lever, self._base * self.softness)
        self._member.predict(when)  # type: ignore[union-attr]

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        return float(self._member.update(measured, noise, when))  # type: ignore[union-attr]
