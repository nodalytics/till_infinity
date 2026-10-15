"""Indirect inference: fit each process family to each asset class, then compare.

[`pattern-fingerprint.md`](../docs/pattern-fingerprint.md) measured sixteen
scale-free pattern statistics across ten process families and every instrument
in the cache. The matcher recovered a held-out family 97 times in 100, and then
every traded class landed **210 to 460** away from its best family where
in-family scatter is about 1.

That result is about the **library**, not about the families, because the
parameters were fixed - `t` at four degrees of freedom, GARCH at 0.02/0.10/0.88,
a jump intensity of 0.002. A GARCH fitted to EURUSD would obviously land closer
than a GARCH fitted to nothing. This does the fitting.

## The method

Simulated method of moments. For a family and a parameter vector, simulate,
compute the fingerprint, and score it against the instrument's by the same
scaled distance the fingerprint study used. Minimise over the parameters, then
compare families on the distance each one **can** reach.

## Common random numbers, which is what makes it work at all

The objective is a simulation, so it carries simulation noise, and a noisy
surface cannot be descended - a grid search would be reading its own variance.
So the innovations are **drawn once as uniforms** and mapped through each
family's inverse distribution for whatever parameters are being tried. Changing
the degrees of freedom then moves the objective smoothly rather than
redrawing a new world, and the same uniforms serve every family, so two
families are compared on the same underlying randomness.

## What is fitted

| family | free parameters |
| --- | --- |
| `gaussian`, `lattice` | none - the fixed references |
| `student_t` | degrees of freedom |
| `drift` | drift per step |
| `momentum`, `reversal` | the AR(1) coefficient |
| `ou` | the mean-reversion rate |
| `garch` | the shock and memory weights |
| `jump` | intensity and jump size |
| `regime` | both switching rates and the volatility ratio |

## The control, again

Fitting adds parameters, and parameters buy distance whether or not the family
is right. So a **known** target is fitted first: a simulated series from a
named family, at parameters held back. The fit has to pick that family and
recover its parameters, or the ranking below is a ranking of flexibility.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pattern_fingerprint import (  # noqa: E402
    classify,
    fingerprint,
    load,
)
from pattern_fingerprint import STATS as ALL_STATS  # noqa: E402

#: `wick tilt` is dropped, and the reason is a defect it caused here rather
#: than a preference. It is identically **0.000** on every symmetric family -
#: the median upper and lower wick are equal - so its replicate spread is zero,
#: the floor below stands in for it, and a real value of -0.006 then scores a
#: `z` of 44 to 79. It was the largest single contributor to the distance for
#: five of seven traded classes while carrying no information about any family.
#: `pattern-fingerprint.md` had already found it dead weight as a discriminator;
#: here it was actively misleading.
STATS = tuple(s for s in ALL_STATS if s != "wick tilt")

CACHE = Path.home() / "till_infinity/data/seqlab"
FRAME = "1h"
#: Bars per simulation while fitting, and sub-bar steps each is built from.
#: Smaller than the fingerprint study's 20,000 x 24 because a fit evaluates
#: this hundreds of times.
BARS = 9000
SUB = 16
#: Replicates per parameter point, for the mean fingerprint and its spread.
REPLICATES = 4
#: Instruments per class whose fingerprints are pooled into the target.
PER_CLASS = 12
SEED = 20261015
TRADED = ("fx_major", "fx_cross", "metal", "index", "energy", "soft", "basket")
GENERATED = ("volatility", "step", "boom", "jump")


def draws(count: int, rng) -> dict[str, np.ndarray]:
    """The common random numbers: uniforms every family maps through.

    Drawn once and reused for every parameter point and every family, so the
    objective is a smooth function of the parameters and two families are
    compared on the same underlying randomness rather than on two different
    worlds.
    """
    return {
        "main": rng.random(count),
        "jump": rng.random(count),
        "size": rng.random(count),
        "state": rng.random(count),
    }


def steps_for(family: str, theta, common: dict[str, np.ndarray]) -> np.ndarray:
    """Sub-bar returns for `family` at `theta`, from the shared uniforms."""
    from scipy.special import ndtri
    from scipy.stats import t as student

    normal = ndtri(np.clip(common["main"], 1e-12, 1 - 1e-12))
    count = len(normal)
    if family == "gaussian":
        out = normal
    elif family == "lattice":
        out = np.where(common["main"] > 0.5, 1.0, -1.0)
    elif family == "student_t":
        out = student.ppf(np.clip(common["main"], 1e-12, 1 - 1e-12), max(theta[0], 2.2))
    elif family == "drift":
        out = normal + theta[0]
    elif family in {"momentum", "reversal"}:
        from scipy.signal import lfilter

        rho = float(np.clip(theta[0], -0.98, 0.98))
        out = lfilter([1.0], [1.0, -rho], normal)
    elif family == "ou":
        from scipy.signal import lfilter

        pull = float(np.clip(theta[0], 1e-4, 0.5))
        level = lfilter([1.0], [1.0, -(1.0 - pull)], normal)
        out = np.diff(np.concatenate(([0.0], level)))
    elif family == "garch":
        shock = float(np.clip(theta[0], 0.001, 0.4))
        memory = float(np.clip(theta[1], 0.0, 0.998 - shock))
        constant = max(1.0 - shock - memory, 1e-6)
        out = np.empty(count)
        variance = 1.0
        previous = 0.0
        for i in range(count):
            variance = constant + shock * previous**2 + memory * variance
            previous = np.sqrt(variance) * normal[i]
            out[i] = previous
    elif family == "jump":
        rate = float(np.clip(theta[0], 1e-5, 0.1))
        size = float(np.clip(theta[1], 0.5, 40.0))
        out = normal.copy()
        hit = common["jump"] < rate
        extra = ndtri(np.clip(common["size"], 1e-12, 1 - 1e-12)) * size
        out = out + np.where(hit, extra, 0.0)
    elif family == "regime":
        wake = float(np.clip(theta[0], 1e-5, 0.5))
        sleep = float(np.clip(theta[1], 1e-5, 0.5))
        ratio = float(np.clip(theta[2], 1.2, 30.0))
        quiet = np.empty(count, dtype=bool)
        state = True
        flips = common["state"]
        for i in range(count):
            if flips[i] < (wake if state else sleep):
                state = not state
            quiet[i] = state
        out = normal * np.where(quiet, 1.0, ratio)
    else:
        raise ValueError(family)
    spread = float(np.std(out))
    return out / spread if spread > 0 else out


def bars_from(steps: np.ndarray, bars: int, sub: int) -> dict[str, np.ndarray]:
    path = np.exp(np.cumsum(steps[: bars * sub] * 0.0004))
    grid = path.reshape(bars, sub)
    return {
        "open": grid[:, 0],
        "high": grid.max(axis=1),
        "low": grid.min(axis=1),
        "close": grid[:, -1],
        "time": np.arange(bars, dtype=float) * 3600.0,
    }


GRIDS: dict[str, tuple] = {
    "gaussian": ((),),
    "lattice": ((),),
    "student_t": tuple((nu,) for nu in (2.5, 3.0, 3.5, 4.0, 5.0, 7.0, 12.0, 30.0)),
    "drift": tuple((mu,) for mu in (0.0, 0.01, 0.02, 0.05, 0.1)),
    "momentum": tuple((rho,) for rho in (0.0, 0.3, 0.6, 0.8, 0.9, 0.95)),
    "reversal": tuple((rho,) for rho in (0.0, -0.3, -0.6, -0.8, -0.9, -0.95)),
    "ou": tuple((pull,) for pull in (0.0005, 0.002, 0.005, 0.02, 0.06, 0.15)),
    "garch": tuple(
        (shock, memory)
        for shock in (0.02, 0.05, 0.10, 0.18, 0.30)
        for memory in (0.60, 0.80, 0.90, 0.96)
        if shock + memory < 0.999
    ),
    "jump": tuple(
        (rate, size)
        for rate in (0.0005, 0.002, 0.01, 0.04)
        for size in (2.0, 5.0, 12.0, 25.0)
    ),
    "regime": tuple(
        (wake, sleep, ratio)
        for wake in (0.001, 0.01)
        for sleep in (0.005, 0.05)
        for ratio in (2.0, 5.0, 12.0)
    ),
}
FAMILIES = tuple(GRIDS)


def profile_at(family: str, theta, commons: list[dict]) -> dict[str, tuple[float, float]]:
    """`(mean, sd)` per statistic over replicates at one parameter point."""
    seen: dict[str, list[float]] = {}
    for common in commons:
        got = fingerprint(bars_from(steps_for(family, theta, common), BARS, SUB))
        for stat in STATS:
            if got[stat] == got[stat]:
                seen.setdefault(stat, []).append(got[stat])
    out = {}
    for stat in STATS:
        values = seen.get(stat, [])
        out[stat] = (
            (float(np.mean(values)), float(np.std(values, ddof=1)))
            if len(values) > 1
            else (float("nan"), float("nan"))
        )
    return out


def gap(target: dict[str, float], shape: dict[str, tuple[float, float]]) -> float:
    """Mean squared z-distance, each statistic scaled by its replicate spread.

    A floor is put under the spread. Without it a statistic that happens to be
    identical across four replicates - `wick tilt` is 0.000 on every symmetric
    family - divides by zero and swamps everything.
    """
    total = count = 0.0
    for stat in STATS:
        mean, spread = shape[stat]
        value = target.get(stat, float("nan"))
        if value != value or mean != mean:
            continue
        floor = max(spread, 1e-4 + 0.01 * abs(mean))
        total += ((value - mean) / floor) ** 2
        count += 1
    return total / count if count else float("inf")


def best_fit(target: dict[str, float], family: str, commons: list[dict]):
    """The parameter point in this family's grid that comes closest."""
    best = (float("inf"), None, None)
    for theta in GRIDS[family]:
        shape = profile_at(family, theta, commons)
        score = gap(target, shape)
        if score < best[0]:
            best = (score, theta, shape)
    return best


def pooled(fingerprints: list[dict[str, float]]) -> dict[str, float]:
    """A class's target: the median of its instruments', statistic by statistic."""
    out = {}
    for stat in STATS:
        values = [f[stat] for f in fingerprints if f[stat] == f[stat]]
        out[stat] = float(np.median(values)) if values else float("nan")
    return out


def main() -> None:
    rng = np.random.default_rng(SEED)
    commons = [draws(BARS * SUB, rng) for _ in range(REPLICATES)]
    print(
        f"Indirect inference: {len(FAMILIES)} families fitted by simulated method of\n"
        f"moments on {len(STATS)} pattern statistics, {BARS:,} bars x {SUB} sub-steps,\n"
        f"{REPLICATES} replicates per point, common random numbers across every point.\n"
    )

    print("=" * 100)
    print("CONTROL  fit a known family and see whether the fit finds it")
    print("=" * 100)
    checks = (("garch", (0.12, 0.85)), ("student_t", (3.0,)), ("regime", (0.01, 0.05, 8.0)))
    print(f"  {'planted':<24}{'best family':<14}{'distance':>10}{'runner-up':<14}{'theirs':>10}")
    for family, theta in checks:
        spare = draws(BARS * SUB, np.random.default_rng(SEED + 99))
        truth = fingerprint(bars_from(steps_for(family, theta, spare), BARS, SUB))
        # One call per family: the first version called `best_fit` twice to
        # read two fields off it, running the whole grid search a second time.
        scored = [(name, best_fit(truth, name, commons)) for name in FAMILIES]
        ranked = sorted((got[0], name, got[1]) for name, got in scored)
        shown = f"{family}{theta}"
        print(
            f"  {shown:<24}{ranked[0][1]:<14}{ranked[0][0]:>10.1f}"
            f"{ranked[1][1]:<14}{ranked[1][0]:>10.1f}   fitted {ranked[0][2]}"
        )

    print("\n" + "=" * 100)
    print("Fitted distance per class: what each family can reach when tuned")
    print("=" * 100)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob(f"*.{FRAME}.npz")):
        name = path.name[: -len(f".{FRAME}.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = [c for c in (*TRADED, *GENERATED) if c in groups]
    print(f"  {'class':<12}" + "".join(f"{f[:9]:>10}" for f in FAMILIES))
    results = {}
    for label in wanted:
        found = []
        for name in sorted(groups[label])[:PER_CLASS]:
            bars = load(name, FRAME)
            if bars is not None:
                found.append(fingerprint(bars))
        if not found:
            continue
        target = pooled(found)
        row = {}
        for family in FAMILIES:
            score, theta, shape = best_fit(target, family, commons)
            row[family] = (score, theta, shape)
        results[label] = (target, row)
        print(f"  {label:<12}" + "".join(f"{row[f][0]:>10.1f}" for f in FAMILIES))

    print("\n" + "=" * 100)
    print("Best family per class, with the parameters it wanted")
    print("=" * 100)
    for label, (target, row) in results.items():
        ranked = sorted((score, name, theta) for name, (score, theta, _s) in row.items())
        score, name, theta = ranked[0]
        shaped = tuple(round(float(x), 4) for x in theta) if theta else ()
        print(f"  {label:<12}{name:<12}{score:>9.1f}   {shaped}")
        # Which statistics the fitted best still misses. The shape is kept from
        # the search above rather than searched again.
        shape = row[name][2]
        worst = sorted(
            (
                (abs(target[s] - shape[s][0]) / max(shape[s][1], 1e-4 + 0.01 * abs(shape[s][0])), s)
                for s in STATS
                if target.get(s) == target.get(s) and shape[s][0] == shape[s][0]
            ),
            reverse=True,
        )[:3]
        for zed, stat in worst:
            print(
                f"      {stat:<16}z {zed:>8.1f}   class {target[stat]:>9.3f}"
                f"   fitted {shape[stat][0]:>9.3f}"
            )
    print(
        "\n  A distance near 1 means the fitted family sits inside its own replicate\n"
        "  scatter around the class. Compare with the unfitted library, where every\n"
        "  traded class sat at 210 to 460.\n"
    )


if __name__ == "__main__":
    main()
