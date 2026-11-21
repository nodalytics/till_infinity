"""Generate data from the model, so a parameter can be recovered rather than argued.

`dynamax` makes this a first-class operation - `sample(params, key, num_timesteps)`
sits beside `fit_em` and `smoother` - and it is the primitive this package was
hand-rolling in every test. It matters more here than in a library, for two
reasons this repository has already paid for.

**A null has to mimic the structure of the thing it is a null for.** The desk's
own record is explicit: every pause rule matched random pausing *at the same duty
cycle*, and the cross-asset result in `peering.md` was killed by a synthetic
control showing a **larger** effect than the real assets. A generator that
produces paths from the model itself is what makes those controls constructible -
and `research/docs/vol-particle.md` names the two nulls it ran before touching
real data, one of which existed only to prove the test could read a null at all.

**And a passed null is not a correct implementation.** The same study's Kalman
arm first reported a negative log-likelihood of 1.15e17, because `log(r^2)` of a
rounded-to-zero FX bar is about -690 - and both nulls passed anyway, because a
Gaussian generator never produces one. So `simulate` is for recovering parameters
and bounding claims, not for believing a filter works.

## What it is not

Not a market simulator. A path from this model is a thrice-integrated Gaussian
jerk with additive measurement noise, which is the model's own assumption about
the world and is **known to be wrong** in at least one measured direction: the
volatility study found real non-Gaussianity large enough for a particle filter to
beat the linearisation on three of four series. Fitting on simulated data proves
the estimator can recover a parameter *from its own model*. Nothing more.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

HOUR = 3_600.0


@dataclass(frozen=True, slots=True)
class Path:
    """A generated path and what a filter would have been shown of it."""

    #: Unix seconds, as given.
    times: tuple[float, ...]
    #: The latent value at each time - what the filter is trying to recover and
    #: can never see.
    truth: tuple[float, ...]
    #: The latent rate, per hour.
    rates: tuple[float, ...]
    #: What the filter is given: `truth` plus measurement noise.
    measured: tuple[float, ...]
    #: The parameters it was generated from, so a recovery test cannot drift
    #: away from the thing it is recovering.
    jerk: float
    noise: float

    def __len__(self) -> int:
        return len(self.times)


def simulate(
    times: Sequence[float],
    *,
    jerk: float,
    noise: float,
    value: float = 0.0,
    rate: float = 0.0,
    accel: float = 0.0,
    seed: int = 0,
) -> Path:
    """A path from the model this package assumes, sampled at `times`.

    The continuous model is a triple integrator driven by white jerk with
    spectral density `jerk`, discretised at each step by the **actual elapsed
    time** - so an uneven `times` is the interesting case and the one I6 is
    about. `noise` is the measurement variance.

    The increments use the exact integrated covariance rather than a per-step
    approximation, which matters precisely when the steps are uneven: a weekend
    gap must inject the variance of a weekend, and a scheme that adds a fixed
    amount per sample is the per-bar mistake in generator form.
    """
    rng = random.Random(seed)
    ts = [float(t) for t in times]
    if len(ts) < 2:
        raise ValueError("a path needs at least two times")

    truth, rates, measured = [], [], []
    v, r, a = float(value), float(rate), float(accel)
    q = max(float(jerk), 0.0)
    sd_noise = math.sqrt(max(float(noise), 0.0))
    prev = ts[0]

    for t in ts:
        dt = (t - prev) / HOUR
        prev = t
        if dt > 0:
            # Advance the state, then add the exactly-integrated jerk increment.
            # The three components are correlated; drawing them independently
            # would generate a process this filter is not a filter for.
            half = 0.5 * dt * dt
            v = v + r * dt + a * half
            r = r + a * dt
            if q > 0:
                # Cholesky of Q(dt) for white jerk, lower triangular. Written
                # out because it is three rows, and because a library call here
                # would be an undeclared dependency.
                dt3 = dt * dt * dt
                l22 = math.sqrt(q * dt)
                l12 = (q * dt * dt / 2.0) / l22
                l11 = math.sqrt(max(q * dt3 / 3.0 - l12 * l12, 0.0))
                l02 = (q * dt3 / 6.0) / l22
                l01 = ((q * dt * dt * dt * dt / 8.0) - l02 * l12) / l11 if l11 > 0 else 0.0
                l00 = math.sqrt(max(q * dt3 * dt * dt / 20.0 - l01 * l01 - l02 * l02, 0.0))
                z0, z1, z2 = rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)
                v += l00 * z0 + l01 * z1 + l02 * z2
                r += l11 * z1 + l12 * z2
                a += l22 * z2
        truth.append(v)
        rates.append(r)
        measured.append(v + rng.gauss(0.0, sd_noise) if sd_noise > 0 else v)

    return Path(
        times=tuple(ts),
        truth=tuple(truth),
        rates=tuple(rates),
        measured=tuple(measured),
        jerk=float(jerk),
        noise=float(noise),
    )


def hourly(n: int, *, start: float = 0.0, step_hours: float = 1.0) -> tuple[float, ...]:
    """`n` evenly spaced times. The easy case, for a baseline."""
    return tuple(start + i * step_hours * HOUR for i in range(n))


def with_gaps(
    n: int, *, start: float = 0.0, step_hours: float = 1.0, gap_hours: float = 62.0, every: int = 24
) -> tuple[float, ...]:
    """`n` times with a weekend-shaped gap every `every` steps.

    The case that separates a rate per hour from a rate per bar, and the shape
    this desk actually produces: sessions close, venues drop out, and the
    synthetics run continuously while the real instruments do not.
    """
    out, t = [], float(start)
    for i in range(n):
        out.append(t)
        t += (gap_hours if every and (i + 1) % every == 0 else step_hours) * HOUR
    return tuple(out)
