"""A tick-level synthetic-quote generator with every stage of the pipeline named.

`research/pipeline.md` asks which of Deriv's middle stages can be identified
from the outside. Nothing on that page is believable unless the same test,
pointed at a generator whose stages are *known*, recovers them - and unless the
same test, pointed at a generator built the honest way, stays quiet. So this
module exists before any of the tests do, and every claim on that page is
quoted with the recovery rate and the false-positive rate this file produced.

## The chain, stage by stage, each one a parameter

    CSPRNG -> uniform u -> inverse-normal Phi^-1(u) -> recursion -> quantise -> publish

* **`inverse`** is the stage question 1 is about. `continuous` is numpy's
  ziggurat on 53-bit doubles, which is continuous at any resolution a quote can
  resolve. `bits=k` draws `u` as a `k`-bit integer over `2**k`, so `z` takes at
  most `2**k` values. `table=N` is a pure lookup with `N` entries and no
  interpolation - the crudest thing a venue could ship. `table_interp=N` is the
  same table read with linear interpolation, which is what a real
  implementation looks like and is *much* harder to see, so it is carried
  separately rather than folded in. `z_round` stores the *output* of an exact
  `Phi^-1` to a finite precision, which is the only stage here that puts `z` on
  a genuine lattice and is the positive control the characteristic-function leg
  would otherwise not have.
* **`convention`** is question 2. `ito` puts `-sigma^2/2 dt` in the exponent so
  the price is a martingale; `plain` puts nothing there so the log price is.
* **`grid`** and **`mode`** are question 3 - the lattice spacing and the
  rounding rule. All five modes are here, including the two that differ from
  each other only on exact ties, because the point of carrying them is to show
  what the published quotes can and cannot tell apart.
* **`state`** is question 4, and it is the sharpest switch in the file.
  `continuous` keeps a full-precision internal price and rounds only for
  display, so the rounding residual is a bounded perturbation that never
  accumulates. `feedback` rounds and then *feeds the rounded price back into
  the recursion*, so the residuals random-walk into the path.
* **`dt`**, **`jitter_ms`**, **`wall_clock`** and **`drop`** are question 5 -
  the publication clock, its jitter, the ticks that go missing between the venue
  and here, and the switch that decides whether the *generator* runs on the slot
  counter or on the realised gap. Both clocks are here because question 5's
  regression cannot be graded without both: a slope means nothing until the two
  hypotheses have each been measured with it.

## Why the internal price is carried in log space

`S_t = S_0 exp(sum of increments)` accumulated as a running sum of logs, not as
a running product. A product of five million float64 factors drifts: each
multiply rounds at 1.1e-16 relative and the errors random-walk, reaching about
`sqrt(5e6) * 1.1e-16 = 2.5e-13` - which is nothing against a quote grid, but
*is* something against the 4.5e-4 z-resolution the atom test works at, and the
whole point of the false-positive control is that nothing in the simulator
leaves a signature the test can find. A running sum of logs has the same error
in the *level* and none in the *increments*, and the increments are what every
test on the page reads.

## What this is not

It is not a model of Deriv. It is a machine for producing data whose pipeline is
known, so that a test's answer can be graded. Boom, Crash, Step and Range Break
are different processes and are not simulated here; the questions this file
supports are the Volatility family's.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import ndtri

#: Seconds in a 365-day year. These indices have no session and no weekend, so
#: this is the annualisation rather than an approximation of one.
SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0

#: Every rounding rule a quote pipeline plausibly uses. `trunc` is `floor` for
#: positive prices and is kept separate anyway, because a reader who sees only
#: four of them will wonder which one it was folded into.
MODES = ("floor", "ceil", "trunc", "half_up", "half_even")

#: The two drift conventions, spelled as `projection.py` spells them so the two
#: files are talking about one object.
CONVENTIONS = ("ito", "plain")


def quantise(x: np.ndarray, grid: float, mode: str = "half_even") -> np.ndarray:
    """Put `x` on a lattice of spacing `grid` under one of five rules.

    Returned as a float on the price scale rather than as lattice integers,
    because that is what a feed hands over and every test downstream has to
    recover the integers itself - including from a real feed, where getting it
    wrong is a live failure mode rather than a hypothetical.
    """
    if grid <= 0:
        return np.asarray(x, dtype=float)
    y = np.asarray(x, dtype=float) / grid
    if mode == "floor":
        out = np.floor(y)
    elif mode == "ceil":
        out = np.ceil(y)
    elif mode == "trunc":
        out = np.trunc(y)
    elif mode == "half_up":
        out = np.floor(y + 0.5)
    elif mode == "half_even":
        out = np.rint(y)  # numpy rounds halves to even
    else:
        raise ValueError(f"unknown rounding mode {mode!r} - have {', '.join(MODES)}")
    return out * grid


def normals(
    n: int,
    rng: np.random.Generator,
    *,
    inverse: str = "continuous",
    bits: int | None = None,
    entries: int | None = None,
    zstep: float | None = None,
) -> np.ndarray:
    """`n` standard normals from an inverse-normal stage of a named precision.

    The four stages this file can build, and what each one is a model of:

    * `continuous` - numpy's ziggurat. The honest implementation, and the
      false-positive control for every atom test.
    * `bits` - `u = j / 2**k` for a uniform integer `j`, then an exact
      `Phi^-1`. This is what a generator that draws a `k`-bit word and divides
      produces, and it is the realistic discrete case: the achievable `z` set is
      finite but *dense in the body* and sparse only in the tail.
    * `table` - `z = Phi^-1((i + 1/2) / N)` for a uniform index `i`. A pure
      lookup, the crudest possible stage, and the one worth being able to find.
    * `table_interp` - the same table read with linear interpolation between
      neighbours. Continuous in value, wrong only in *shape*, and invisible to
      every test in this arm that looks for atoms. It is here so the write-up
      can say which lookup tables are excluded and which are not.
    * `z_round` - an exact `Phi^-1` whose **output** is stored to a finite
      precision `zstep`, which is what a fixed-point or short-decimal table
      looks like from outside. This is the one stage that puts `z` on a genuine
      lattice, and it is the target `pipeline.ecf_scan` is built for; without it
      in the control set that scan would have no positive control at all and
      its clean result would be worth nothing.
    """
    if inverse == "continuous":
        return rng.standard_normal(n)
    if inverse == "bits":
        if not bits or bits < 2:
            raise ValueError("inverse='bits' needs bits >= 2")
        m = 1 << int(bits)
        # j in 1 .. m-1 so u is strictly inside (0, 1) and Phi^-1 is finite.
        j = rng.integers(1, m, size=n, dtype=np.int64 if bits < 63 else np.uint64)
        return ndtri(np.asarray(j, dtype=np.float64) / float(m))
    if inverse in ("table", "table_interp"):
        if not entries or entries < 4:
            raise ValueError(f"inverse={inverse!r} needs entries >= 4")
        grid_z = ndtri((np.arange(entries, dtype=np.float64) + 0.5) / float(entries))
        i = rng.integers(0, entries, size=n)
        if inverse == "table":
            return grid_z[i]
        # Linear interpolation between table entries, with the fraction drawn
        # from a continuous uniform - the usual way a table is actually read.
        f = rng.random(n)
        j = np.minimum(i + 1, entries - 1)
        return grid_z[i] + f * (grid_z[j] - grid_z[i])
    if inverse == "z_round":
        if not zstep or zstep <= 0:
            raise ValueError("inverse='z_round' needs zstep > 0")
        return np.round(rng.standard_normal(n) / zstep) * zstep
    raise ValueError(f"unknown inverse-normal stage {inverse!r}")



def _feedback(factor: np.ndarray, price: float, grid: float, mode: str) -> np.ndarray:
    """The rounded price fed back into the recursion, one step at a time.

    Separate from `ticks` so the loop body carries no branch on the rounding
    mode: five modes resolved once, outside three million iterations.
    """
    import math

    out = np.empty(factor.size, dtype=np.float64)
    s = price
    if grid <= 0:
        for i in range(factor.size):
            s = s * factor[i]
            out[i] = s
        return out
    inv = 1.0 / grid
    if mode == "floor" or mode == "trunc":
        # trunc == floor for a positive price, and these are positive by
        # construction; the two are kept apart in `quantise` and collapse here.
        step_fn = math.floor
        shift = 0.0
    elif mode == "ceil":
        step_fn = math.ceil
        shift = 0.0
    elif mode == "half_up":
        step_fn = math.floor
        shift = 0.5
    elif mode == "half_even":
        step_fn = None
        shift = 0.0
    else:
        raise ValueError(f"unknown rounding mode {mode!r}")
    for i in range(factor.size):
        y = s * factor[i] * inv
        s = (round(y) if step_fn is None else step_fn(y + shift)) * grid
        out[i] = s
    return out


@dataclass(slots=True)
class Truth:
    """The parameters a test is graded against. Written before the data exists."""

    sigma: float
    dt: float
    grid: float
    mode: str
    convention: str
    state: str
    inverse: str
    bits: int | None = None
    entries: int | None = None
    zstep: float | None = None

    @property
    def sigma_tick(self) -> float:
        """Standard deviation of one tick's log increment."""
        return self.sigma * np.sqrt(self.dt / SECONDS_PER_YEAR)

    def lattice_sd(self, price: float) -> float:
        """`sigma_Y` - the per-tick move in lattice units, which sets every power here."""
        return self.sigma_tick * price / self.grid if self.grid > 0 else float("inf")


def ticks(
    n: int,
    *,
    price: float = 50_000.0,
    sigma: float = 0.75,
    dt: float = 2.0,
    grid: float = 0.01,
    mode: str = "half_even",
    convention: str = "ito",
    state: str = "continuous",
    inverse: str = "continuous",
    bits: int | None = None,
    entries: int | None = None,
    zstep: float | None = None,
    spread: float = 0.0,
    jitter_ms: float = 0.0,
    offset_ms: float = 220.0,
    drop: float = 0.0,
    wall_clock: bool = False,
    seed: int = 0,
) -> dict:
    """One feed's worth of published quotes, from a pipeline whose stages are known.

    Returns the same columns `feed.ticks` does - `time`, `bid`, `ask`, `mid` -
    plus `truth`, so a test can be handed simulated and real data through one
    code path. **That shared path is the point.** A test that takes real data
    one way and simulated data another is grading itself on a different object
    from the one it will be used on, and the recovery rate it reports is then
    about the plumbing rather than about the test.
    """
    rng = np.random.default_rng(seed)
    sigma_tick = sigma * float(np.sqrt(dt / SECONDS_PER_YEAR))
    drift = -0.5 * sigma_tick * sigma_tick if convention == "ito" else 0.0
    z = normals(n, rng, inverse=inverse, bits=bits, entries=entries, zstep=zstep)

    # The clock is built before the path, because one of the two hypotheses
    # about `dt` is that the path depends on it. `wall_clock` integrates the
    # *realised* gap - a tick that arrives 2.5% late carries 2.5% more variance;
    # the default steps once per slot and the jitter is the publisher's alone.
    # Question 5's regression cannot be graded without both.
    slots = np.arange(n, dtype=np.float64)
    t = slots * dt + offset_ms / 1000.0
    if jitter_ms > 0:
        t = t + rng.normal(0.0, jitter_ms / 1000.0, size=n)
    t = np.round(t * 1000.0) / 1000.0  # the feed stores whole milliseconds
    if wall_clock:
        g = np.empty(n)
        g[0] = 1.0
        g[1:] = np.maximum(np.diff(t) / dt, 1e-6)
        step = drift * g + sigma_tick * np.sqrt(g) * z
    else:
        step = drift + sigma_tick * z

    if state == "continuous":
        # Accumulate in log space - see the module docstring on why not a product.
        logs = np.log(price) + np.cumsum(step)
        internal = np.exp(logs)
        published = quantise(internal, grid, mode)
    elif state == "feedback":
        # The rounded price is the state. This loop cannot be vectorised: each
        # step needs the previous *published* price, which is the hypothesis
        # under test. Written in plain Python scalars rather than one-element
        # numpy calls - the array version is forty times slower and this runs at
        # the same sample size as the real feed by design.
        published = _feedback(np.exp(step), float(price), float(grid), mode)
        internal = published
    else:
        raise ValueError(f"unknown state mode {state!r} - 'continuous' or 'feedback'")

    if spread > 0:
        bid = quantise(published - spread / 2.0, grid, mode)
        ask = quantise(published + spread / 2.0, grid, mode)
    else:
        bid = ask = published

    keep = np.ones(n, dtype=bool)
    if drop > 0:
        keep = rng.random(n) >= drop
        keep[0] = keep[-1] = True

    return {
        "time": t[keep],
        "bid": bid[keep],
        "ask": ask[keep],
        "mid": ((bid + ask) / 2.0)[keep] if spread > 0 else published[keep],
        "internal": internal[keep],
        "z": z[keep],
        "truth": Truth(sigma, dt, grid, mode, convention, state, inverse, bits, entries, zstep),
        "wall_clock": wall_clock,
    }


def like(real: dict, n: int, **over) -> dict:
    """A simulated feed matched to a measured one, overridden stage by stage.

    Every control on the page is built through this rather than by retyping the
    parameters, because a control that differs from its target in the price
    level or the grid is measuring two things at once - which is the failure
    `rebuildvol.py` names in `lattice_walk` and the same one applies here.
    """
    base = {
        "price": float(real["price"]),
        "sigma": float(real["sigma"]),
        "dt": float(real["dt"]),
        "grid": float(real["grid"]),
        "spread": float(real.get("spread", 0.0)),
    }
    base.update(over)
    return ticks(n, **base)
