"""A particle ensemble over an anchored selective recurrence. The two fixes, as a member.

Asked for on 2026-10-10: fix `selective`'s two worst trade-offs, **in a new
member rather than in that one**, so the thing that was measured stays
measurable. `selective` keeps losing on its own terms; this is the version that
answers the objections, and the comparison between them is the experiment.

## The two trade-offs this exists to fix

**1. `selective`'s forward extrapolation decays to zero.** `h` summarises
readings that arrived, not a quantity that persists, so with no further readings
`C h -> 0`. A level is the one thing whose character is sitting still, and the
eurusd measurement is consistent with this being expensive: S4D-Real won 3m, 15m,
30m, 1h and 1d and **lost 4h**, the timeframe whose gaps are longest.

The fix is in the spectrum: **one eigenvalue of zero**, `(0, -1, -2, -3)`. That
component does not decay, so it holds the level while the others track movement
around it, and extrapolation goes to the level rather than to nothing.

A zero eigenvalue cannot be driven the way the others are, and that is the
interesting part rather than an inconvenience. `selective`'s entry weight is
`1 - exp(delta * A)`, which is **exactly zero** when `A` is zero - a frozen
state that never sees a reading. So the anchored component is not an
exponential average at all: it is a **random walk**, moved by process noise and
corrected by which particles the data prefers. The decaying components absorb the
*residual* around it. The state therefore reads as

    y = anchor + sum(deviations)

where the deviations decay, so `at_time` far ahead returns the anchor. That is
the whole point.

**2. `selective` has no posterior**, so its `sd` is a fitted parameter and its
band has no reason to be honest. Measured on eurusd 15m: `linear` covered 50.3%
of readings in its two-sigma band and `reverting` 69.9%, against a nominal 95%,
so an asserted spread is not a theoretical worry.

The fix is the ensemble. `COUNT` particles are propagated, weighted by the
Gaussian likelihood of the reading and resampled; `sd` is then the **spread of
the particles**, which is inferred rather than asserted and which widens on
elapsed time by itself because the anchor random-walks. It also restores
`covariance()` from the sample covariance, so unlike `selective` this member can
be smoothed.

## What this is, in the literature's words

A bootstrap particle filter whose transition is a selective state space
recurrence with an anchored spectrum. **It does not consume `family.PENDING`'s
`particle` entry**, which reserves a plain SMC arm over `linear` and `reverting`
scored against "the linearised Kalman arm on the same model" - a different member
with a different null, still unwritten.

Running a particle filter needs **no gradients**, which is why this is
affordable: `PENDING` records that fitting *through* one needs differentiable
resampling (PyDPF, arXiv:2510.25693) and a PyTorch dependency this desk does not
have, and that wall stands only in front of backpropagating through the
resampling step. Parameters here come from the same likelihood grid as `theta`
and `jerk`.

## numpy, and why this member requires it

`COUNT` particles by `SIZE` states advanced one step at a time is the batch
shape measured at **26.6x** - the one place numpy clearly pays in this package.
It is imported lazily, not at module level, and the reason is specific:
`shared/codec.py` walks `structures` with `importlib.import_module`, so every
module here is imported inside the desk process, and `CODEC_UNPERSISTED` opts
this package out of the persistence schema but not out of that import. A
module-level numpy would load it into a 2.6GiB cgroup sitting at ~2.4GB for a
package that publishes nothing.

Unlike `smoothing.py` there is no scalar fallback, because unlike there the
arithmetic is genuinely array-shaped: 200 particles of 4 states is 800 numbers a
step, where the smoother's was nine.

## The null, and it is nearby on purpose

**`selective` on the same series.** Same recurrence, same five parameters, same
score. If the anchor and the particles buy nothing, then a level does not need a
persistent component and its uncertainty did not need to be inferred - which
would be a real finding about this data and not a failure of the member.

The second null is `reverting`, which won eurusd 4h and is the incumbent this has
to beat to matter.

## Nothing here publishes

Same rule as the rest of the package: reachable from tests and research
harnesses only, until a named null has been beaten on held-out data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .linear import EXISTENCE_HALF_LIFE_HOURS
from .selective import INERT, softplus

#: Seconds in an hour. Rates are per hour throughout this package.
HOUR = 3600.0

#: The state size, and the spectrum. **The first eigenvalue is zero** and that
#: is the whole design: it holds the level. The rest are `-(n)` for `n >= 1`,
#: which keeps S4D-Real's spacing for the components that do decay.
SIZE = 4

#: Particles. 200 is not measured: it is the point where the spread of a
#: Gaussian posterior is estimated to a few percent, which is the precision the
#: band is quoted at. The number a score is read against is `seen`, not this.
COUNT = 200

#: Resample when the effective sample size falls below this share of `COUNT`.
#: The standard trigger, and the reason one is needed: without it the weights
#: concentrate on one particle and the posterior collapses to a point - which
#: is the failure this member exists to avoid.
RESAMPLE_BELOW = 0.5


def _numpy():
    """numpy, or a clear failure. See the module docstring for why it is lazy."""
    import numpy

    return numpy


@dataclass(slots=True)
class Swarm:
    """An anchored selective recurrence, carried by a particle ensemble.

    Parameters are `selective`'s, plus `wander` for the anchor's own process
    noise. Defaults put it at a sensible starting point rather than at a null:
    there is no nested null here, because the anchor cannot be switched off
    without changing the spectrum.
    """

    #: `delta`'s constant term. `INERT` means one hour of `delta` per hour.
    drift: float = INERT
    #: How strongly the reading moves `delta`. Zero makes the deviations
    #: time-invariant; the anchor is unaffected either way.
    scale: float = 0.0
    #: How much of a residual the deviations absorb.
    gain: float = 1.0
    #: The read-out scale on the whole state.
    read: float = 1.0
    #: Measurement standard deviation used to weight particles, in the
    #: subject's units. **Not** the reported `sd`: that comes from the spread.
    noise: float = 1.0
    #: The anchor's process noise, per root hour, in the subject's units. This
    #: is the parameter that makes the band widen when nothing arrives, and it
    #: is the direct counterpart of `DRIFT_VOL_PER_HOUR`, which was chosen once
    #: and never fitted.
    wander: float = 0.1

    #: Seed, so a run is reproducible. A particle filter whose answer moves
    #: between runs cannot be compared against a null.
    seed: int = 20261010

    #: How many particles. **`count = 1` is the member without the particle
    #: half**, which is the thing worth being able to ask for: the anchored
    #: recurrence, deterministic, extrapolating to the anchor rather than to
    #: zero, with `sd` falling back to the measurement noise because a single
    #: particle has no spread. The difference between `count = 1` and
    #: `count = 200` is then exactly what the ensemble buys, with nothing else
    #: changing - which is the only way to attribute the two fixes separately.
    #:
    #: This is also why the anchor is not bolted onto `selective` instead.
    #: That member's read-out is the **mean** of its basis, because every one
    #: of its states converges to the reading; put one slow component in and it
    #: retains only `1/SIZE` of the level - measured at 39 of 250 over 48h.
    #: The anchor needs a read-out of *anchor plus deviations*, which is this
    #: member's, so the anchored member is this one at `count = 1` rather than
    #: `selective` with a flag.
    count: int = COUNT

    at: float | None = None
    read_at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    #: One step is skipped: the first reading seeds the ensemble.
    burn: int = 1
    last_standardised: float = 0.0
    existence: float = 1.0
    #: How many times the ensemble has been resampled. Diagnostic: a filter
    #: resampling every step is one whose weights are degenerate.
    resampled: int = 0

    #: `(COUNT, SIZE)` particle states, and `(COUNT,)` weights. Lists until the
    #: first reading, so an unused instance costs no array.
    _h: object = None
    _w: object = None
    _x: float = 0.0

    @staticmethod
    def eigenvalues() -> tuple[float, ...]:
        """`(0, -1, -2, -3)`. The zero is the anchor and the rest decay."""
        return (0.0, *tuple(-(n + 0.0) for n in range(1, SIZE)))

    #: One output. A second row is D3, as everywhere else in this package.
    OUTPUTS: tuple[str, ...] = ("value",)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        """`C`: the anchor plus the deviations, all at `read`.

        **Not the mean.** `selective` averages its basis because every state
        there converges to the reading; here the anchor holds the level and the
        others are departures from it, so they add rather than average.
        """
        return (tuple(self.read for _ in range(SIZE)),)

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def _mean(self) -> tuple[float, ...]:
        """The weighted mean state, or zeros before the first reading."""
        if self._h is None:
            return tuple(0.0 for _ in range(SIZE))
        np = _numpy()
        return tuple(float(v) for v in np.average(self._h, axis=0, weights=self._w))

    @property
    def value(self) -> float:
        """`read * (anchor + deviations)`, averaged over the ensemble."""
        return self.read * sum(self._mean())

    @property
    def anchor(self) -> float:
        """Where the ensemble thinks the level is, with the movement removed.

        The quantity `at_time` converges to, and the one worth reading when the
        question is "where is this level" rather than "where is price now".
        """
        return self.read * self._mean()[0]

    @property
    def rate(self) -> float:
        """Per hour, from the continuous dynamics of the decaying components.

        The anchor contributes nothing: its drift is noise with no mean, so a
        rate read off it would be reporting a random walk's last step as a
        trend.
        """
        mean = self._mean()
        return self.read * sum(a * mean[n] for n, a in enumerate(self.eigenvalues()) if a != 0.0)

    def retention(self, hours: float, z: float = 0.0) -> tuple[float, ...]:
        """`exp(delta * A)` per state. The anchor's is 1.0, by construction."""
        step = max(hours, 0.0) * softplus(self.drift + self.scale * z)
        out = []
        for a in self.eigenvalues():
            if a == 0.0:
                out.append(1.0)
                continue
            u = -a * step
            out.append(0.0 if u > 700.0 else math.exp(-u))
        return tuple(out)

    def _seed_ensemble(self, measured: float) -> None:
        np = _numpy()
        rng = np.random.default_rng(self.seed)
        self._h = np.zeros((self.count, SIZE))
        # The anchor starts at the reading, spread by the measurement noise -
        # an approximate diffuse start, the same choice `linear` makes when it
        # takes the first reading as the state.
        self._h[:, 0] = measured / (self.read or 1.0) + rng.normal(
            0.0, max(self.noise, 1e-9), self.count
        )
        self._w = np.full(self.count, 1.0 / self.count)

    def predict(self, when: float) -> None:
        """Advance the clock and let the anchor wander. Deviations are untouched.

        The deviations decay inside `update`, from the last *reading*, for the
        reason `selective.predict` records: advancing here as well would decay
        them twice per step. The anchor is different - it wanders with elapsed
        time whether or not a reading arrives, which is what makes the band
        widen in a gap.
        """
        if self.at is None:
            self.at = when
            return
        hours = (when - self.at) / HOUR
        if hours <= 0.0:
            return
        if self._h is not None:
            np = _numpy()
            rng = np.random.default_rng(self.seed + self.seen)
            self._h[:, 0] += rng.normal(0.0, self.wander * math.sqrt(hours), self.count)
        if self.existence > 0.0:
            self.existence *= 0.5 ** (hours / EXISTENCE_HALF_LIFE_HOURS)
        self.at = when

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Weight, resample, then absorb the residual. Returns the innovation."""
        if not math.isfinite(measured) or not math.isfinite(noise) or noise < 0.0:
            return 0.0
        if when is None:
            when = self.read_at if self.read_at is not None else (self.at or 0.0)

        if not self.seen:
            self._seed_ensemble(measured)
            self.at = when
            self.read_at = when
            self.seen = 1
            self.existence = 1.0
            self._x = measured
            return 0.0

        np = _numpy()
        # `noise` is a **variance** by the `Filter` contract; `self.noise`
        # is a standard deviation. Taking the root is what makes a harness
        # able to pass one number to every member and mean one thing.
        spread = math.sqrt(noise) if noise > 0.0 else self.noise
        innovation = measured - self.value
        z = innovation / spread if spread > 0.0 else 0.0

        hours = max((when - self.read_at) / HOUR, 0.0) if self.read_at is not None else 0.0
        keep = np.asarray(self.retention(hours, z))
        self._h = self._h * keep

        # Weight by how well each particle predicted this reading, *before* it
        # absorbs it - the only order in which the weight is predictive.
        predicted = self.read * self._h.sum(axis=1)
        errors = (measured - predicted) / max(spread, 1e-12)
        logw = -0.5 * errors * errors
        # **The stabilising shift has to come back into the likelihood.**
        # Subtracting the maximum keeps `exp` off the floor, which is why it is
        # done; leaving it out of the sum computes a log-sum-exp *plus*
        # `-max(logw)`, and that term is non-negative, so the score comes out
        # too high by `0.5 * min(error**2)` at every step. The first run of the
        # four-symbol harness was scored that way and this member's win was
        # inflated by it.
        shift = float(logw.max())
        weights = self._w * np.exp(logw - shift)
        total = weights.sum()
        if total <= 0.0 or not math.isfinite(total):
            # Every particle is impossible. Keep the prior rather than
            # dividing by zero, and let `resampled` record that it happened.
            self.resampled += 1
        else:
            self._w = weights / total
            if self.seen >= self.burn:
                # The log of the weighted mean predictive density: a
                # log-sum-exp over particles plus the Gaussian normalisation.
                self.loglike += (
                    math.log(total)
                    + shift
                    - 0.5 * math.log(2.0 * math.pi)
                    - math.log(max(spread, 1e-12))
                )

        # Resample on a degenerate effective sample size.
        ess = 1.0 / float((self._w**2).sum())
        if self.count > 1 and ess < RESAMPLE_BELOW * self.count:
            rng = np.random.default_rng(self.seed + self.seen + 1)
            # Systematic resampling, which is what the volatility harness used
            # and so is what `family.PENDING` points at.
            positions = (rng.random() + np.arange(self.count)) / self.count
            picked = np.searchsorted(np.cumsum(self._w), positions)
            self._h = self._h[np.clip(picked, 0, self.count - 1)]
            self._w = np.full(self.count, 1.0 / self.count)
            self.resampled += 1

        # The deviations absorb what the anchor could not explain.
        residual = measured - self.read * self._h.sum(axis=1)
        enter = (1.0 - keep) * self.gain
        self._h = self._h + residual[:, None] * enter[None, :] / (self.read or 1.0)

        # **Evidence restores existence, and leaving this out was a bug.**
        # `existence` decays on elapsed time in `predict` and is pulled back
        # toward one by every reading, which is `linear`'s rule - a level being
        # touched is a level that still exists. Without the restore this member
        # only ever decayed: on 6,000 bars of v75 15m it finished at **0.045**
        # while every other member finished at 0.998, which is what exposed it.
        # The claim that existence "depends on elapsed time alone" was wrong,
        # and the two halves are the point: time removes belief, readings
        # return it.
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)

        # Standardised by the predictive spread - the ensemble's own plus the
        # measurement noise - so it is the quantity `linear.last_standardised`
        # is, rather than the raw innovation in units of `R`.
        total = math.sqrt(self.sd**2 + spread * spread)
        self.last_standardised = innovation / total if total > 0.0 else 0.0
        self._x = measured
        self.at = when
        self.read_at = when
        self.seen += 1
        return innovation

    def at_time(self, when: float) -> float:
        """Where the value will be at `when` - converging on the **anchor**.

        The difference from `selective`, which converges on zero. The deviations
        decay and the anchor stays, so far ahead this is the level rather than
        nothing.
        """
        if self.at is None or self._h is None:
            return self.value
        hours = (when - self.at) / HOUR
        if hours <= 0.0:
            return self.value
        keep = self.retention(hours)
        mean = self._mean()
        return self.read * sum(k * v for k, v in zip(keep, mean, strict=True))

    @property
    def sd(self) -> float:
        """The **spread of the ensemble**, not a parameter.

        This is the trade-off this member was written for. `selective.sd` is a
        fitted number that cannot widen in a gap; this is a weighted standard
        deviation over particles, and it widens because the anchor wanders.
        """
        if self._h is None or self.count <= 1:
            # **One particle has no spread, and saying so matters.** At
            # `count = 1` this member fixes the extrapolation and *not* the
            # posterior, so it falls back to an asserted spread exactly as
            # `selective` does. That is the honest separation of the two fixes:
            # the anchor is a spectrum choice and the uncertainty is the
            # ensemble, and only one of them comes free.
            return max(self.noise, 0.0)
        np = _numpy()
        values = self.read * self._h.sum(axis=1)
        mean = float(np.average(values, weights=self._w))
        var = float(np.average((values - mean) ** 2, weights=self._w))
        return math.sqrt(max(var, 0.0))

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        """The interval the value is expected in at `when`, widening with the gap.

        **The widening is the point and the first version did not have it.** It
        used the current ensemble spread at every horizon, so the band at +48h
        was exactly as narrow as the band now - the defect this member was
        written to fix, reproduced one level up. `linear.band` advances its
        covariance before reading it and this has to do the same: the anchor is
        a random walk, so its variance grows by `wander**2` an hour whether or
        not a reading arrives.
        """
        hours = 0.0 if self.at is None else max((float(when) - self.at) / HOUR, 0.0)
        middle = self.at_time(when)
        if self._h is None:
            half = sigmas * math.sqrt(self.noise**2 + self.wander**2 * hours)
            return (middle - half, middle + half)
        np = _numpy()
        keep = np.asarray(self.retention(hours))
        ahead = self.read * (self._h * keep).sum(axis=1)
        mean = float(np.average(ahead, weights=self._w))
        var = float(np.average((ahead - mean) ** 2, weights=self._w))
        half = sigmas * math.sqrt(max(var, 0.0) + self.wander**2 * hours)
        return (middle - half, middle + half)

    def state(self) -> tuple[float, ...]:
        """The weighted mean state: `(anchor, deviation, deviation, deviation)`."""
        return self._mean()

    def covariance(self) -> tuple[tuple[float, ...], ...]:
        """The ensemble's sample covariance.

        **Restored, where `selective` has none.** It is what makes this member
        smoothable: `smoothing.smooth` needs a covariance and a transition, and
        this answers both.
        """
        if self._h is None:
            return tuple(tuple(1.0 if i == j else 0.0 for j in range(SIZE)) for i in range(SIZE))
        np = _numpy()
        mean = np.average(self._h, axis=0, weights=self._w)
        centred = self._h - mean
        cov = (self._w[:, None] * centred).T @ centred
        return tuple(tuple(float(v) for v in row) for row in cov)

    def transition(self, dt: float) -> tuple[tuple[float, ...], ...]:
        """`F(dt)`, diagonal, with `dt` in hours as the smoother passes it."""
        keep = self.retention(dt)
        return tuple(tuple(keep[i] if i == j else 0.0 for j in range(SIZE)) for i in range(SIZE))

    def effective(self) -> float:
        """Effective sample size. A diagnostic, and the one worth watching.

        Near `count` the ensemble is healthy; near one it has collapsed to a
        point estimate and the `sd` above has stopped meaning anything.
        """
        if self._w is None:
            return float(self.count)
        np = _numpy()
        return 1.0 / float((np.asarray(self._w) ** 2).sum())
