"""Are `kalman` and `robust` mis-scaled, or correctly scaled and heavy-tailed?

`pool-spread.md` released the matching loop's clamp and found `reverting`
reaching `E[z^2] = 1.03` while **`kalman` stops at 1.53-1.84 and `robust` at
1.49-1.72**, with the lever converged well inside the clamp it was given. A
member that cannot reach one at any process noise is not mis-scaled.

## The arithmetic that makes this worth a run rather than a knob

`adapting.Adapting` in matching mode steps `lever *= excess ** step`, so its
only fixed point is `excess = 1`. For a Student-t innovation with `nu` degrees
of freedom and scale `c`, the **variance** is `c^2 nu / (nu - 2)`. So a filter
that reports its scale correctly - `spread = c^2` - reads

    E[z^2] = nu / (nu - 2)

which is **1.67 at nu = 5, 1.80 at nu = 4.5 and 1.50 at nu = 6**: exactly the
range these two members sit at. If that is what is happening, they are not
wrong at all, the target is: driving `E[z^2]` to one would inflate the reported
spread to the t's variance, which is right for a Gaussian band and wrong for
every quantile outside the body.

And the desk has measured this shape before, independently.
`no-gaussian-band-is-calibrated`: a Student-t with **3 to 5** degrees of
freedom beat a Gaussian on PIT flatness *and* CRPS on 64 of 64 out-of-sample
feed-frames, which is why `tails.py` exists. Two measurements arriving at the
same `nu` from opposite directions would be the strongest evidence in this
whole thread.

## Part A settles a precondition before any of that matters

The loop's fixed point is `excess = 1`. At the released clamp the lever
**converged at 1.3 to 4.2 million, inside a clamp of 1e7**, while the sample
`E[z^2]` reads 1.84. Those two cannot both be true of a loop at rest: if
`excess` really were 1.84, `move = 1.84 ** 0.02 > 1` and the lever would still
be climbing.

So Part A reports `excess`, the sample, the lever and the clamp side by side at
both clamps. Either `excess` reads one - in which case it and the sample
measure different things and the diagnosis in `pool-spread.md` needs rewriting
- or it reads 1.84 and the lever is still moving, in which case the run was too
short rather than the clamp too tight. **This is the arm that decides whether
the rest of the page is about anything.**

## Part B fits the shape

Per member and class, a Student-t fitted to the standardised innovations by
maximum likelihood - `nu` on a grid, the scale by EM at each `nu` - against a
Gaussian fitted the same way. Reported: `nu`, the implied `nu / (nu - 2)`, the
measured `E[z^2]`, and the log-likelihood gap. If the implied value tracks the
measurement across classes and members, the members are scale-correct and the
metric is the thing that is wrong.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.statespace.adapting import MOST, Adapting  # noqa: E402
from till_infinity.statespace.engine import dispersion  # noqa: E402
from till_infinity.statespace.pooling import DEFAULT, LEVERS, Pooled, _factories  # noqa: E402

NOISE = 0.265
CLAMPS = (MOST, 1e7)
FRAMES = ("1h",)
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 3
LIMIT = 12_000
WARM = 500
#: Degrees of freedom tried. Below 2 a t has no variance, so `nu/(nu-2)` is
#: meaningless there and the grid starts clear of it.
DOFS = (2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 8.0, 12.0, 20.0, 50.0, 200.0)


def _pool(most: float) -> Pooled:
    built = _factories(DEFAULT)
    return Pooled(
        names=DEFAULT,
        _pool=[
            Adapting(build=make, lever=LEVERS.get(name, "jerk"), mode="matching", most=most)
            for name, make in zip(DEFAULT, built, strict=False)
        ],
    )


def _fold(series: np.ndarray, stamps: np.ndarray, most: float) -> dict:
    """Fold once and keep each member's innovations, belief and lever."""
    pool = _pool(most)
    per: dict[str, list[float]] = {}
    for i, value in enumerate(series):
        pool.predict(float(stamps[i]), 0.0)
        pool.update(float(value), NOISE, float(stamps[i]))
        if i >= WARM:
            for name, one in zip(pool.names, pool.members, strict=False):
                z = float(getattr(one, "last_standardised", 0.0))
                if math.isfinite(z):
                    per.setdefault(name, []).append(z)
    state = {
        name: (
            float(getattr(one, "excess", float("nan"))),
            float(getattr(one, "factor", float("nan"))),
            float(getattr(one, "highest", float("nan"))),
        )
        for name, one in zip(pool.names, pool.members, strict=False)
    }
    return {"per": per, "state": state}


def _t_scale(z: np.ndarray, dof: float, rounds: int = 60) -> float:
    """ML scale of a Student-t at fixed `dof`, by the usual EM weights."""
    scale2 = max(float(np.mean(z * z)), 1e-12)
    for _ in range(rounds):
        weight = (dof + 1.0) / (dof + (z * z) / scale2)
        fresh = float(np.mean(weight * z * z))
        if abs(fresh - scale2) <= 1e-12 * max(scale2, 1.0):
            scale2 = fresh
            break
        scale2 = max(fresh, 1e-12)
    return scale2


def _t_loglike(z: np.ndarray, dof: float, scale2: float) -> float:
    scale = math.sqrt(scale2)
    const = (
        math.lgamma(0.5 * (dof + 1.0))
        - math.lgamma(0.5 * dof)
        - 0.5 * math.log(dof * math.pi)
        - math.log(scale)
    )
    return float(np.sum(const - 0.5 * (dof + 1.0) * np.log1p((z / scale) ** 2 / dof)))


def _gaussian_loglike(z: np.ndarray) -> float:
    var = max(float(np.mean(z * z)), 1e-12)
    return float(np.sum(-0.5 * math.log(2.0 * math.pi * var) - 0.5 * z * z / var))


def _shape(z: np.ndarray) -> tuple[float, float, float]:
    """Best `dof`, its implied `E[z^2]`, and its log-likelihood gap on a Gaussian."""
    best = (-math.inf, math.nan, math.nan)
    for dof in DOFS:
        scale2 = _t_scale(z, dof)
        like = _t_loglike(z, dof, scale2)
        if like > best[0]:
            best = (like, dof, scale2)
    like, dof, scale2 = best
    implied = scale2 * dof / (dof - 2.0) if dof > 2.0 else math.nan
    return dof, implied, (like - _gaussian_loglike(z)) / len(z)


def _series(name: str, frame: str) -> tuple[np.ndarray, np.ndarray] | None:
    bars = load(name, frame)
    if bars is None:
        return None
    bars = {k: v[-LIMIT:] for k, v in bars.items()}
    out: list[float] = []
    when: list[float] = []
    for i in range(len(bars["close"])):
        got = dispersion(
            float(bars["open"][i]),
            float(bars["high"][i]),
            float(bars["low"][i]),
            float(bars["close"][i]),
        )
        if got is not None:
            out.append(got)
            when.append(float(bars["time"][i]))
    values = np.asarray(out, dtype=float)
    stamps = np.asarray(when, dtype=float)
    return (values, stamps) if len(values) > WARM + 2_000 else None


def main() -> None:
    print(
        "Are `kalman` and `robust` mis-scaled, or correctly scaled and heavy-tailed?\n"
        f"R pinned at the measured {NOISE}. For a Student-t innovation at `nu` degrees\n"
        "of freedom, a filter reporting its *scale* correctly reads E[z^2] = nu/(nu-2):\n"
        "1.67 at nu=5, 1.80 at 4.5, 1.50 at 6 - the range these two members sit at.\n"
        "`tails.py` independently measured nu of 3 to 5 for the one-bar band.\n",
        flush=True,
    )
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}
    print("classes:", ", ".join(f"{k} ({len(v)})" for k, v in sorted(wanted.items())), flush=True)

    for frame in FRAMES:
        loaded: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
        for klass, names in sorted(wanted.items()):
            for name in names:
                got = _series(name, frame)
                if got is not None:
                    loaded.setdefault(klass, []).append(got)

        print(f"\n## Part A, {frame}: is the loop at rest, and does it know what we measure")
        print(
            f"{'class':>12}{'clamp':>8}{'member':>11}{'excess':>9}{'sample':>9}"
            f"{'lever':>12}{'highest':>12}{'at rest':>9}"
        )
        kept: dict[tuple[str, float, str], np.ndarray] = {}
        for klass, series in sorted(loaded.items()):
            for most in CLAMPS:
                rows: dict[str, list[float]] = {}
                state: dict[str, list[tuple[float, float, float]]] = {}
                for values, stamps in series:
                    got = _fold(values, stamps, most)
                    for name, zs in got["per"].items():
                        rows.setdefault(name, []).extend(zs)
                    for name, one in got["state"].items():
                        state.setdefault(name, []).append(one)
                for name in sorted(rows):
                    z = np.asarray(rows[name], dtype=float)
                    kept[(klass, most, name)] = z
                    excess = float(np.median([one[0] for one in state[name]]))
                    lever = float(np.median([one[1] for one in state[name]]))
                    highest = float(np.median([one[2] for one in state[name]]))
                    rest = "no" if highest >= most * 0.999 else "yes"
                    print(
                        f"{klass:>12}{most:>8.0e}{name:>11}{excess:>9.3f}"
                        f"{float(np.mean(z * z)):>9.3f}{lever:>12.3g}{highest:>12.3g}{rest:>9}",
                        flush=True,
                    )

        print(f"\n## Part B, {frame}: the shape of those innovations")
        print(
            f"{'class':>12}{'clamp':>8}{'member':>11}{'nu':>7}{'nu/(nu-2) x c^2':>17}"
            f"{'sample E[z^2]':>15}{'loglike gap/bar':>17}"
        )
        for (klass, most, name), z in sorted(kept.items()):
            dof, implied, gap = _shape(z)
            print(
                f"{klass:>12}{most:>8.0e}{name:>11}{dof:>7.1f}{implied:>17.3f}"
                f"{float(np.mean(z * z)):>15.3f}{gap:>17.4f}",
                flush=True,
            )
    print(
        "\n\nPart A first. A member whose `highest` equals its clamp was never at rest,\n"
        "and its sample says nothing about shape - the lever was still climbing. For\n"
        "the ones that did settle, Part B's `nu/(nu-2) x c^2` against the sample is\n"
        "the whole question: if they track, the member reports a scale and the metric\n"
        "asked for a variance, and `tails.py`'s nu of 3 to 5 was the same finding\n"
        "reached from the band instead of the loop.",
        flush=True,
    )


if __name__ == "__main__":
    main()
