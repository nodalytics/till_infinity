"""The neural architectural family, as a member rather than as a dependency.

`A` fixed, `B`, `C` and the step size `delta` functions of the input: Mamba's
selective state space model, S6, from Gu and Dao, arXiv:2312.00752. Asked for on
2026-10-10 - "we can have a neural architectural family like mamba inside our
statespace lib" - after the paper had been read and this had been written down
as declined. The decline was about the *training method*, and it still is; this
module is the part of the architecture that survives without it.

## What is here and what is not

**Here:** the selective recurrence itself. `A` is a fixed diagonal, `-(n+1)`,
which is S4D-Real - the initialisation that scored best of the four the paper
ablates, 8.71 perplexity, tied with random and ahead of the complex S4D-Lin at
9.16. `B`, `C` and `delta` are affine functions of the input, which is what makes
it selective rather than an S4. The entry weight is `1 - exp(delta * A)`, a
normalised exponential average that is exact zero-order hold only at `A = -1`
and is not the reference's `delta * B` either - `retention` says why, and the
reason is this member's fixed `C`.

**Not here: backpropagation.** The paper's `B`, `C` and `delta` are produced by
`Linear` layers whose weights are learned by gradient descent, and that needs an
autodiff framework this desk does not have - the same wall `family.PENDING`
records for PyDPF and differentiable resampling. So the projections here are
**affine in one scalar and carry five parameters in total**, which the likelihood
grid already used for `theta` and `jerk` can fit. That is a smaller claim than
the paper's and it is the claim that can be checked here.

**No numpy, deliberately.** `A` is diagonal, so the recurrence is `n` independent
scalars and there is no matrix algebra to do. `TODO.md` argues numpy's case for
this package and the first thing that genuinely needs it is D1's HiPPO matrix,
which is dense. This is not that.

## The null, and the honest expectation

`reverting` on held-out one-step predictive likelihood, the same score I5 was
settled on. The null is **nested inside this member**: `drift = 0` and
`scale = INERT` make `delta` exactly the elapsed time and the recurrence
time-invariant, so a loss here is a statement about selection and not about an
unrelated model.

**And the expectation is that it loses on this data.** The paper's own limitation
section says the selection mechanism helps on discrete modalities "but this
conversely can impede their performance on data that LTI SSMs excel on", reports
that replacing S4 with S6 "significantly hampers performance" on long-form audio,
and concludes that "layers closer to the raw audio signal should be LTI". A
level's position is a continuous-time quantity sampled irregularly, with no
vocabulary and nothing to retrieve by content - the first kind, not the second.
Selection exists to fix a weakness on text and DNA that this data does not have.

That is an argument, not a measurement, which is why the member is written
instead of only being argued about. But a loss is the predicted outcome and
should be recorded as a confirmation rather than mourned.

## Theorem 1, which is the part that pays immediately

The paper's Theorem 1: with one state, `A = -1`, `B = 1` and
`delta = softplus(z)`, the recurrence becomes a gated RNN,

    h_t = (1 - g) h_{t-1} + g x_t      g = sigmoid(z)

and the identity behind it is exact at `drift = 0`, `scale = 1`, because
zero-order hold on `A = -1` gives a retention of `exp(-delta)`:

    1 - exp(-softplus(z)) = 1 - 1/(1 + e^z) = e^z / (1 + e^z) = sigmoid(z)

So **a one-state selective SSM is an exponentially weighted moving average whose
decay depends on its input**. This desk is full of fixed-decay averages. The
cheapest experiment in the whole state-space thesis is therefore not a new
member at all - it is letting one existing average's decay depend on activity
instead of on the clock - and `test_statespace.py` pins the identity to the
twelfth decimal so that claim rests on arithmetic rather than on a reading of a
paper.

Large `delta` resets the state onto the current input; small `delta` keeps the
state and ignores the input. That is the behaviour wanted across a regime break,
where a level's older history should stop counting.

## Nothing here publishes

Same rule as the rest of the package: reachable from tests and research
harnesses only, until a named null has been beaten on held-out data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .linear import EXISTENCE_HALF_LIFE_HOURS

#: Seconds in an hour. Rates are per hour throughout this package - see
#: `rates.py` for why a per-bar rate is not a rate.
HOUR = 3600.0

#: The state size. Four is not a measurement: the paper's own ablation found
#: that raising `N` from 1 to 16 bought almost nothing while `B` and `C` were
#: *not* selective - 9.88 to 9.81 - and only paid once they were, 9.73 to 8.71.
#: This package's own I5 measurement agrees from the other direction: a third
#: state is estimable and still loses 0.138 nats a point. So the state is kept
#: small until selection has been shown to earn it here.
SIZE = 4


def inverse_softplus(target: float) -> float:
    """The `drift` whose `softplus` is `target`: `x + log(-expm1(-x))`.

    Lifted from the reference implementation
    (`state-spaces/mamba`, `mamba_simple.py`), which sets its `dt` bias this way
    under the comment "Initialize dt bias so that F.softplus(dt_bias) is between
    dt_min and dt_max". It is the honest way to say "I want this step size":
    `drift` lives on the pre-softplus scale, so choosing it directly is choosing
    a number whose meaning is one transform away.
    """
    return target + math.log(-math.expm1(-target))


#: `softplus(INERT) == 1`, so `delta` is exactly the elapsed hours and this
#: member is time-invariant - the point the nested null sits at. Equal to
#: `log(e - 1)`, and written through `inverse_softplus` because that generalises
#: to any target and this does not.
INERT = inverse_softplus(1.0)

#: The range the reference samples its step size from, log-uniformly, with a
#: floor of 1e-4: `dt_min=0.001` to `dt_max=0.1`. Kept as the shape a grid over
#: `drift` should take - log-uniform across orders of magnitude rather than
#: linear - and **not** as the values. Theirs is a step per token in a sequence
#: with no clock; `delta` here multiplies real elapsed hours, so the numbers do
#: not transfer even though the spacing does.
REFERENCE_DELTA = (0.001, 0.1)

#: Beyond this the exponential is zero to double precision and `expm1` is the
#: only form that keeps the retention accurate.
_BIG = 700.0


def softplus(z: float) -> float:
    """`ln(1 + e^z)`, without overflowing for large `z`.

    `math.log1p(math.exp(z))` overflows at about 710 and loses the identity
    `softplus(z) -> z` that keeps a large `delta` finite rather than infinite.
    """
    if z > 30.0:
        return z
    if z < -30.0:
        return math.exp(z)
    return math.log1p(math.exp(z))


def sigmoid(z: float) -> float:
    """`1 / (1 + e^-z)`, by halves so neither tail overflows."""
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass(slots=True)
class Selective:
    """S6 as a family member: fixed diagonal `A`, selective `B`, `C` and `delta`.

    The five parameters are `drift`, `scale`, `gain`, `read` and `noise`, and
    they are what a likelihood search would fit. Defaults put the member at its
    own nested null - time-invariant, unit gain - so an unfitted instance is a
    plain exponential filter rather than an arbitrary one.
    """

    #: The constant term in `delta`'s projection. `INERT` means one hour of
    #: `delta` per hour of clock.
    drift: float = INERT
    #: How strongly the input moves `delta`. **Zero is the null**: `delta`
    #: stops depending on the input and the recurrence becomes time-invariant,
    #: which is what makes `reverting` a nested special case rather than a
    #: different model.
    scale: float = 0.0
    #: `B`'s projection, how much of a reading enters the state.
    gain: float = 1.0
    #: `C`'s projection, how much of the state is read out. One, because the
    #: state is in the subject's units and a read-out scale is only
    #: identifiable against a fitted `gain`.
    read: float = 1.0
    #: One-step predictive standard deviation, in the subject's units. A
    #: selective SSM is a deterministic map and has no posterior covariance, so
    #: this is a fitted residual spread and not a propagated one - see `sd`.
    noise: float = 1.0

    #: `h`, the latent state. Diagonal `A`, so these never interact.
    h: list[float] = field(default_factory=lambda: [0.0] * SIZE)
    #: Unix seconds of the last advance, or None before the first - a sentinel
    #: that is not a valid timestamp, because zero is one.
    at: float | None = None
    #: Measurements folded in.
    seen: int = 0

    #: Accumulated log predictive density, the same quantity `linear.loglike`
    #: holds and under the same name, so a caller scoring members against each
    #: other does not have to know which one it is holding. Added when the
    #: family was audited for exactly that: the three Kalman members answered
    #: `loglike` and this one answered `predictive`, which is the same concept
    #: with a different name and is how two members stop being comparable.
    loglike: float = 0.0

    #: Steps excluded from `loglike`. One, not three: the first reading is taken
    #: as the state, and unlike `linear` there are no further diffuse states
    #: reached only through the first - every state here sees the input directly.
    burn: int = 1

    #: The most recent standardised innovation. A correctly specified filter
    #: makes this a standard normal, which is what `diagnostics.py` consumes -
    #: and here it is also the signal `delta`'s projection reads, so the
    #: diagnostic and the selection see the same number.
    last_standardised: float = 0.0

    #: Belief that the quantity still exists, in [0, 1]. Decays with the same
    #: half-life `linear` uses, because an absence of evidence means the same
    #: thing whichever member is holding the state.
    existence: float = 1.0

    #: Unix seconds of the last *reading*, which is not `at`: `predict` moves
    #: `at` without one. Keeping them apart is load-bearing - advancing to a
    #: time and then folding a reading in at that same time made `delta` zero,
    #: and with `B̄ = delta * B` a zero `delta` means the reading never entered
    #: the state at all. The member tracked nothing and reported 0.0.
    read_at: float | None = None

    #: The last reading, kept because `rate` is read from the continuous
    #: dynamics `dh/dt = A h + B x` and that needs the `x` in force.
    _x: float = 0.0

    @staticmethod
    def eigenvalues() -> tuple[float, ...]:
        """`A`'s diagonal: `-(n+1)`, per state, in units of inverse hours.

        S4D-Real. The paper ablates four initialisations and this one ties for
        best at 8.71 perplexity; the complex S4D-Lin form is the worst of them
        once the model is selective, at 9.16. Fixed, not learned - selective
        `A` is the one thing the paper leaves untested, saying only that it
        expects similar performance.
        """
        return tuple(-(n + 1.0) for n in range(SIZE))

    def _readout(self, vector: list[float] | tuple[float, ...]) -> float:
        """`C v`, with `C = read / SIZE` spread evenly over the basis.

        **The mean and not the sum.** Every state is an exponential average of
        the same input at its own rate, so each converges to the reading and a
        sum converges to `SIZE` times it: with four states a level held at 100
        was reported as heading to 400. Mamba has no such problem because `C`
        is learned and absorbs the scale; `C` here is fixed, so it has to carry
        the `1/SIZE` itself.
        """
        return self.read * sum(vector) / SIZE

    @property
    def value(self) -> float:
        """`C h`, the quantity this member believes in, in the subject's units."""
        return self._readout(self.h)

    @property
    def rate(self) -> float:
        """Per hour, from the continuous dynamics rather than from a state slot.

        There is no rate in `h` - that is the point of a basis the transition
        chose rather than one physics chose - so the rate is what
        `dh/dt = A h + B x` implies at the reading in force.
        """
        return self._readout(
            [a * self.h[n] + self.gain * self._x for n, a in enumerate(self.eigenvalues())]
        )

    def retention(self, hours: float, z: float = 0.0) -> tuple[float, ...]:
        """`exp(delta * A)` per state: how much of `h` survives `hours`.

        `delta = hours * softplus(drift + scale * z)`, so `scale = 0` leaves it
        proportional to elapsed time and the member time-invariant.

        **What the entry weight is, stated properly**, because an earlier
        version of this docstring called it "zero-order hold, which is what
        Mamba uses" and that was wrong in both halves. `update` pairs this
        retention with an entry weight of `1 - keep`, so the two sum to one and
        each state is a **normalised exponential average** of the readings. That
        is:

        * **exact ZOH only at `A = -1`.** Exact zero-order hold is
          `B̄ = (e^{delta*A} - 1) / A`, which carries a `1/|A|` the form here
          does not: at `delta = 0.5` this gives 0.632 where exact ZOH gives
          0.316 for `A = -2`, and 0.865 against 0.216 for `A = -4`.
        * **not what the reference does either.** `mamba_simple.py` computes
          `dB = einsum("bd,bn->bdn", dt, B)` - plainly `delta * B`, which is
          Euler and is 0.5 for every state at that step.

        The normalisation is deliberate and the read-out is why. With weights
        summing to one every state converges to the reading, so their mean is
        the reading and `_readout` is meaningful; with exact ZOH a slow state
        would converge to `B/|A|` instead and the mean of the basis would not be
        an estimate of anything. Mamba does not face this because its `C` is
        learned and absorbs whatever scale the states settle at.
        """
        step = max(hours, 0.0) * softplus(self.drift + self.scale * z)
        out = []
        for a in self.eigenvalues():
            u = -a * step  # positive, since every eigenvalue is negative
            out.append(0.0 if u > _BIG else math.exp(-u))
        return tuple(out)

    def predict(self, when: float) -> None:
        """Move the clock. **Leaves `h` alone**, which is not what a Kalman
        member's `predict` does and is not an oversight.

        There is no "advance without a reading" in this architecture. Every step
        of a selective state space model consumes an input - Mamba has one
        token per step and no notion of a gap - and the decay across a gap is
        already applied inside `update`, from `read_at` to the new reading. An
        earlier version decayed `h` here as well and the state was advanced
        **twice** per step: with `predict(t)` then `update(x, noise, t)`, a
        level held near 101 was tracked to 65.8 and the standardised innovation
        reached 164. The two arms were each individually defensible, which is
        why it took a protocol audit to see them together.

        So this decays `existence`, because an absence of evidence is a real
        thing that time alone causes, and it does not touch the state.
        """
        if self.at is None:
            self.at = when
            return
        hours = (when - self.at) / HOUR
        if hours <= 0.0:
            return
        if self.existence > 0.0:
            self.existence *= 0.5 ** (hours / EXISTENCE_HALF_LIFE_HOURS)
        self.at = when

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in one reading. Returns the innovation, as every member must.

        The innovation is formed *before* the state moves and is also what
        `delta`'s projection reads, which is the whole content of "selective":
        how much the state advances depends on the reading in front of it and
        not only on the clock. A surprising reading opens `delta`, which both
        resets the state onto the input and shortens what the state remembers.

        **A zero-length step folds in nothing, and that is the architecture
        rather than a bug.** `delta` is this member's only entry channel, so no
        elapsed time means no entry - where a Kalman member would take two
        simultaneous readings as two pieces of evidence and shrink `R`. Mamba
        has no notion of two tokens at one position and neither does this. Two
        venues printing the same instant is a real thing, so it is recorded here
        instead of being smoothed over.
        """
        if not math.isfinite(measured) or not math.isfinite(noise) or noise < 0.0:
            return 0.0
        if when is None:
            when = self.read_at if self.read_at is not None else (self.at or 0.0)

        if not self.seen:
            # First reading: take it as the state rather than averaging it with
            # a prior nobody chose, which is what `linear` does and for the same
            # reason. Spread across the basis, since `value` is their sum.
            self.h = [measured / self.read] * SIZE if self.read != 0.0 else [0.0] * SIZE
            self._x = measured
            self.at = when
            self.read_at = when
            self.seen = 1
            self.existence = 1.0
            return 0.0

        innovation = measured - self.value
        spread = noise if noise > 0.0 else self.noise
        z = innovation / spread if spread > 0.0 else 0.0

        # Scored before the state moves, which is the only order that gives a
        # *predictive* density rather than a fitted one.
        self.last_standardised = z
        if self.seen >= self.burn:
            self.loglike += self.predictive(measured)
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)

        hours = max((when - self.read_at) / HOUR, 0.0) if self.read_at is not None else 0.0
        keep = self.retention(hours, z)
        # `B̄ = delta * B` for a diagonal `A`, the simplification the paper
        # makes and the reason the entry weight below is exactly `1 - keep`.
        self.h = [
            k * v + (1.0 - k) * self.gain * measured for k, v in zip(keep, self.h, strict=True)
        ]

        self._x = measured
        self.at = when
        self.read_at = when
        self.seen += 1
        return innovation

    def gate(self, hours: float, z: float) -> float:
        """Theorem 1's `g` for the first state: `1 - exp(delta * A_0)`.

        Exposed because it is the quantity worth reusing even if this member
        loses the comparison. `A_0` is `-1`, so at `drift = 0`, `scale = 1` and
        `hours = 1` this is exactly `sigmoid(z)` - an exponential average whose
        decay depends on its input, to 1.1e-16 over z in [-8, 12].

        **Not at the default `drift`.** `INERT` makes `delta` the elapsed hours,
        which is the nested null and a different configuration; an earlier
        version of this docstring claimed the identity held there and it does
        not - at `drift = INERT` the gate is `1 - exp(-softplus(INERT + z))`,
        which is 0.13 away from `sigmoid(z)` at `z = 0`.
        """
        return 1.0 - self.retention(hours, z)[0]

    def at_time(self, when: float) -> float:
        """Where the value will be at `when` - which **decays toward zero**.

        A real limitation rather than a quirk, and it says something about the
        architecture. `h` is a summary of the readings that have arrived, not an
        estimate of a quantity that persists on its own, so with no further
        readings the summary decays and `C h` goes to zero. `linear` carries a
        value state that stays where it is and `reverting` reverts the *rate*
        and not the value; neither of them wanders off.

        For a level - a quantity whose whole character is that it sits still -
        that makes this member's forward extrapolation close to useless, and it
        is a second reason to expect it to lose the comparison that `TODO.md`
        already predicts on the paper's own grounds. Use `value` for what it
        has seen; do not read `band()` far ahead.
        """
        if self.at is None:
            return self.value
        hours = (when - self.at) / HOUR
        if hours <= 0.0:
            return self.value
        keep = self.retention(hours)
        return self._readout([k * v for k, v in zip(keep, self.h, strict=True)])

    @property
    def sd(self) -> float:
        """The fitted one-step spread, and **not** a propagated uncertainty.

        A selective SSM is a deterministic sequence map: there is no posterior
        covariance in it, so there is nothing for `smoothing.smooth` to run
        backwards and this member deliberately does not answer `covariance()`.
        The smoother returns None for it, which is a true statement about the
        member rather than a shortcoming of the smoother - the same contract a
        member that cannot state its own `F` already has.
        """
        return max(self.noise, 0.0)

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        """The interval the value is expected in at `when`."""
        middle = self.at_time(when)
        half = sigmas * self.sd
        return (middle - half, middle + half)

    #: What `C` reads out. One row, and unlike the other members it is **not**
    #: a slot in the state: `h` holds coefficients of the transition's own
    #: basis, so there is no "value" component to point at and the output is a
    #: weighted sum of all of them. This is the member that makes writing the
    #: observation equation down worth doing.
    OUTPUTS: tuple[str, ...] = ("value",)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        """`C`, which is `read / SIZE` across the basis - see `_readout`."""
        return (tuple(self.read / SIZE for _ in range(SIZE)),)

    def output(self) -> tuple[float, ...]:
        """`y = C h`. Equals `value`, and a test holds the two together."""
        return (self._readout(self.h),)

    def state(self) -> tuple[float, ...]:
        """`h`. Coefficients of the transition's own basis, not named quantities.

        There is no `('value', 'rate', 'accel')` here to hand out, which is why
        `Smoothed.component` would raise for this member if it could be smoothed
        at all. `value` and `rate` above are read out of `h`; they are not in it.
        """
        return tuple(self.h)

    def transition(self, dt: float) -> tuple[tuple[float, ...], ...]:
        """`F(dt)`, diagonal, with `dt` in **hours** as the smoother passes it.

        A member can state its transition and still not be smoothable: the
        missing piece here is the covariance, not this. Hours rather than
        seconds because that is the unit `smoothing.smooth` divides down to
        before calling, and guessing from the magnitude of `dt` - which an
        earlier draft of this did - makes a one-hour step and a one-second step
        the same number.
        """
        keep = self.retention(dt)
        return tuple(tuple(keep[i] if i == j else 0.0 for j in range(SIZE)) for i in range(SIZE))

    def predictive(self, measured: float) -> float:
        """Gaussian log density of one reading under the current belief.

        The score. A deterministic map has no likelihood of its own, so one
        parameter buys it comparability: `noise` as a fitted one-step spread
        makes this the same quantity `reverting` and `linear` are scored on, and
        a search over the five parameters maximises the same sum.
        """
        spread = max(self.noise, 1e-12)
        z = (measured - self.value) / spread
        return -0.5 * (z * z + math.log(2.0 * math.pi) + 2.0 * math.log(spread))
