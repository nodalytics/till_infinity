"""Long memory from a sum of short memories.

Lillo's review (arXiv:2105.00521) puts the problem plainly: the sign of order
flow has an autocorrelation decaying as `tau^-gamma` with `gamma` near 0.5, a
**power law**, which is to say it has no typical time scale. Every member in
this package decays **exponentially**, because that is what a Markovian state
does, and an exponential has exactly one time scale by construction. No
amount of fitting makes `exp(-t/h)` look like `t^-gamma` over more than a
decade.

The standard remedy is older than the problem's finance literature: **a power
law is a sum of exponentials**. Superimposing Ornstein-Uhlenbeck processes
whose rates are spaced geometrically gives a kernel that is power-law over the
range the rates span, and the approximation is good to a few percent with a
handful of modes. It is the same device the S4/HiPPO lineage uses - already in
this package's reading list - to give a long-memory kernel a state-space form,
and the two halves have never been joined here.

## Why this is a member rather than a parameter

`reverting` is this with one mode. Adding modes is not a tweak to it: a single
OU's autocorrelation falls off a cliff at its half-life, and the whole point is
to have no cliff. So the thing being tested is whether **the market's memory
has a scale**, and that is a question about model class.

## The rates are durations, and they span the ladder

`SLOWEST` and `FASTEST` are half-lives in hours, geometrically spaced across
`modes`. From an hour to four weeks by default, which is the range
`inputs.LADDER` resolves and the range this desk trades. A member whose
fastest mode is slower than the bar it is fed cannot see anything, so the
caller is expected to pass a span its data covers.

## Where this member does win: the variance

`statespace-fractals.md` took the sentence below at its word and put the
ladder on **log-volatility** instead of the level. It beats a single OU on
seven of seven traded instruments, by +191 to +547 nats out of sample, and
loses on five of five controls - including on a series whose log-volatility
genuinely is one OU, which it loses by 453. So the modes are not idle; they
were on the wrong quantity.

## A prediction I made before running it, and it was wrong

`facts.py` measured every member rolled forward and not one generated
volatility clustering. I expected this member to be the first that did - a
sum of exponentials has memory at every scale, and clustering is memory - and
wrote that down before running it.

It does not. Rolled out over 6,000 hours it clusters at **+0.192** against
`reverting`'s **+0.190**: no difference at all.

The reason is worth more than the prediction was. **Long memory in the level
is not long memory in the variance.** The modes here give the *mean* a kernel
with no typical scale, which is the right device for Lillo's finding, because
his long memory is in the **sign of order flow**. Volatility clustering is a
statement about the conditional *variance* depending on past magnitudes, and
this member's process noise is constant - so its increments inherit no memory
of their own size however long the mean remembers.

The device is right and the quantity is wrong. The member that would cluster
is this one applied to **log variance**, which is a long-memory stochastic
volatility model - and that is exactly the object
`research/ideas/volatility_roughness.py` has been measuring the Hurst exponent
of. The two pieces of work point at the same unbuilt member, which is worth
more than a member that happened to pass.

So what this is: the long-memory **level** member, whose null is `reverting`
and `linear` on held-out likelihood. What it is not: the answer to the
clustering gap.

## Nothing here publishes

The null is `reverting` - the one-mode case - and `linear`, on held-out
likelihood, on the same series. A member with five times the states has to
earn them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

HOUR = 3600.0

#: Half-lives spanned by the modes, in **hours**. An hour to four weeks.
FASTEST = 1.0
SLOWEST = 4 * 7 * 24.0

#: How many modes. Five spans the range at roughly a factor of six apart,
#: which is about where the sum-of-exponentials approximation to a power law
#: stops improving per mode added.
MODES = 5

#: Process noise per mode, per hour. The modes share it, so the *shape* of the
#: kernel comes from the rates and only its scale is a parameter.
WANDER = 1e-3


@dataclass(slots=True)
class Fractional:
    """Several Ornstein-Uhlenbecks at geometrically spaced rates, summed.

    The observed value is the sum of the modes, so the observation row is all
    ones - which makes this a genuinely multi-state member with a scalar
    observation, like `linear`, and schedulable by the same machinery.
    """

    modes: int = MODES
    fastest: float = FASTEST
    slowest: float = SLOWEST
    wander: float = WANDER

    #: The modes themselves, and their covariance.
    parts: list[float] = field(default_factory=list)
    covariance: list[list[float]] = field(default_factory=list)

    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    burn: int = 10
    existence: float = 1.0
    last_standardised: float = 0.0

    def __post_init__(self) -> None:
        if not self.parts:
            self.parts = [0.0] * self.modes
        if not self.covariance:
            self.covariance = [
                [1.0 if i == j else 0.0 for j in range(self.modes)] for i in range(self.modes)
            ]

    @property
    def half_lives(self) -> tuple[float, ...]:
        """Each mode's half-life in hours, geometrically spaced.

        Geometric rather than linear because a power law is scale-free: equal
        ratios between rates is what makes the sum look the same at every
        scale, and equal *differences* would crowd every mode at the slow end.
        """
        if self.modes == 1:
            return (self.slowest,)
        step = (self.slowest / self.fastest) ** (1.0 / (self.modes - 1))
        return tuple(self.fastest * step**i for i in range(self.modes))

    # ------------------------------------------------------------- the reading

    @property
    def value(self) -> float:
        return sum(self.parts)

    @property
    def rate(self) -> float:
        """Zero. The modes are levels; a trend would be a different member."""
        return 0.0

    @property
    def sd(self) -> float:
        """`H P H'` with `H` all ones: every entry of the covariance."""
        return math.sqrt(max(sum(sum(row) for row in self.covariance), 0.0))

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def state(self) -> tuple[float, ...]:
        return tuple(self.parts)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return (tuple(1.0 for _ in range(self.modes)),)

    def transition(self, dt_hours: float) -> tuple[tuple[float, ...], ...]:
        """Diagonal: each mode retains `0.5 ** (dt / half-life)` of itself."""
        keep = [0.5 ** (dt_hours / h) for h in self.half_lives]
        return tuple(
            tuple(keep[i] if i == j else 0.0 for j in range(self.modes)) for i in range(self.modes)
        )

    def at_time(self, when: float) -> float:
        """The sum of the modes, each decayed to `when`.

        **This is where long memory shows.** The fast modes vanish within
        hours and the slow ones persist for weeks, so the forecast decays
        quickly at first and then very slowly - which is the shape a power law
        has and a single exponential cannot.
        """
        elapsed = 0.0
        if self.at is not None:
            elapsed = max((float(when) - self.at) / HOUR, 0.0)
        return sum(
            part * 0.5 ** (elapsed / h) for part, h in zip(self.parts, self.half_lives, strict=True)
        )

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        elapsed = 0.0
        if self.at is not None:
            elapsed = max((float(when) - self.at) / HOUR, 0.0)
        keep = [0.5 ** (elapsed / h) for h in self.half_lives]
        total = 0.0
        for i in range(self.modes):
            for j in range(self.modes):
                total += keep[i] * self.covariance[i][j] * keep[j]
            total += self.wander * elapsed
        half = sigmas * math.sqrt(max(total, 0.0))
        middle = self.at_time(when)
        return (middle - half, middle + half)

    # ------------------------------------------------------------- the filter

    def predict(self, when: float, control: float = 0.0) -> None:  # noqa: ARG002
        if self.at is None:
            self.at = float(when)
            return
        dt = (float(when) - self.at) / HOUR
        self.at = float(when)
        if dt <= 0.0:
            return
        keep = [0.5 ** (dt / h) for h in self.half_lives]
        self.parts = [k * p for k, p in zip(keep, self.parts, strict=True)]
        self.covariance = [
            [
                keep[i] * self.covariance[i][j] * keep[j] + (self.wander * dt if i == j else 0.0)
                for j in range(self.modes)
            ]
            for i in range(self.modes)
        ]

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        if when is not None and self.at is None:
            self.at = float(when)
        size = self.modes
        if self.seen == 0:
            # Split the first reading across the modes rather than giving it
            # to one: the modes are exchangeable before any data, and handing
            # it all to the slowest would be a prior nobody chose.
            self.parts = [measured / size] * size
            self.seen = 1
            self.existence = 1.0
            return 0.0

        ph = [sum(self.covariance[i]) for i in range(size)]
        s = sum(ph) + max(noise, 0.0)
        innovation = measured - self.value
        if s <= 0.0:
            return innovation

        self.last_standardised = innovation / math.sqrt(s)
        if self.seen >= self.burn:
            self.loglike += -0.5 * (math.log(2.0 * math.pi * s) + innovation * innovation / s)

        gain = [v / s for v in ph]
        self.parts = [p + g * innovation for p, g in zip(self.parts, gain, strict=True)]
        updated = [
            [self.covariance[i][j] - gain[i] * ph[j] for j in range(size)] for i in range(size)
        ]
        self.covariance = [
            [0.5 * (updated[i][j] + updated[j][i]) for j in range(size)] for i in range(size)
        ]
        self.seen += 1
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)
        return innovation
