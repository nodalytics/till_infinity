"""Can a scalar observation say anything about the third state, before its noise is fitted?

`linear.Gaussian` - the `kalman` and `robust` members of the service's pool -
holds `(value, rate, accel)` and observes `value` alone. So `rate` and `accel`
are never measured directly, and the question of how much the data can say
about them has a closed-form answer that costs nothing to compute.

Two things make it worth computing now rather than later.

**`jerk` has never been measured.** Its own comment says so: "Spectral density
of the jerk ... this has not been measured for any subject yet", shipped at
`1e-6`. And `adapting-strata.md` found the matching loop pinned against
`MOST = 1e3` at `R = 0.265`, wanting a factor of 1.3 to 4.2 **million** -
which puts the jerk the loop is reaching for at order **one**, six decades
above its default. A loop with nothing to constrain it will run to its clamp,
and an unobservable state is exactly a state with nothing to constrain it.

**And the third state is the one the improvement list says to measure before
tuning.** For a constant-acceleration model with position-only measurement the
observability Gramian gives the answer directly, so there is no reason to
discuss it.

## Part A: the closed form, at the sampling this service actually uses

`F = [[1, dt, dt^2/2], [0, 1, dt], [0, 0, 1]]`, `C = [1, 0, 0]`, and

    G_N = sum over k < N of (F^k)' C' C F^k

is the Fisher information about the state from `N` noiseless observations.
Divided by the measurement variance `R` it is the information actually
available, so `sqrt(inv(G_N / R)[2, 2])` is the **best posterior standard
deviation of `accel` any estimator could reach** from `N` bars at that `R`,
with no process noise at all. Against the magnitude `accel` plausibly takes,
that is the whole answer.

`dt` is swept over the service's own intervals - `config.py` folds 1m and 5m,
and every measurement on this desk is at 15m or longer - because the per-hour
convention makes `dt` the only thing that changes between frames.

## Part B: what the member's own covariance says on real bars

The same question asked of the running code: fold the real log-variance series
at the shipped `R` and read `p22`, the accel's posterior variance, against the
prior it started from, plus `accel / sqrt(p22)` - whether the fitted value is
distinguishable from zero at all.

## Part C: does it matter, which is the only part that decides anything

An arm with `accel` pinned to zero after every update, against the member as
shipped, scored on what the service publishes: the value, the spread, the band
breach, CRPS and `var z`. **If pinning the third state changes nothing, then
`jerk` is a free parameter on an unobserved quantity** - and the clamped loop
is a loop with no information to stop it, which would tie
`adapting-strata.md`'s finding to its cause.

Pinning after the update is not quite a two-state model: `predict` has already
used the accel for that step. It is the arm that answers whether the state
carries anything forward, which is the question.
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

from till_infinity.statespace.diagnostics import crps  # noqa: E402
from till_infinity.statespace.engine import dispersion  # noqa: E402
from till_infinity.statespace.facade import Desk  # noqa: E402

#: The shipped measurement variance, because that is the configuration the
#: service runs - `adapting-strata.md` is the standing lesson on pinning the
#: correct value instead of the shipped one.
NOISE = 0.670
#: Hours per bar, for the intervals the service folds and the ones measured.
STEPS = {"1m": 1.0 / 60.0, "5m": 1.0 / 12.0, "15m": 0.25, "1h": 1.0}
#: Observation counts to report the achievable posterior at.
COUNTS = (60, 240, 500, 2_000)
COVERS = (0.90, 0.95, 0.99)

FRAMES = ("1h", "15m")
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 3
LIMIT = 12_000
WARM = 500


def _gramian(dt: float, count: int) -> np.ndarray:
    """`sum (F^k)' C'C F^k` for the constant-acceleration model."""
    transition = np.array([[1.0, dt, 0.5 * dt * dt], [0.0, 1.0, dt], [0.0, 0.0, 1.0]])
    observe = np.array([[1.0, 0.0, 0.0]])
    total = np.zeros((3, 3))
    power = np.eye(3)
    for _ in range(count):
        total += power.T @ observe.T @ observe @ power
        power = transition @ power
    return total


def part_a() -> None:
    """The closed form: the best posterior any estimator could reach."""
    print("## Part A: what a scalar observation can say about rate and accel\n")
    print(
        f"Best achievable posterior sd from N bars at R = {NOISE}, with no process\n"
        "noise at all - so these are upper bounds on what the data supports.\n"
        "`cond` is the Gramian's condition number: how badly the three directions\n"
        "are confounded by observing only the first.\n"
    )
    print(
        f"{'interval':>9}{'N':>7}{'sd(value)':>12}{'sd(rate)/h':>13}{'sd(accel)/h2':>15}{'cond':>12}"
    )
    for name, dt in STEPS.items():
        for count in COUNTS:
            gramian = _gramian(dt, count)
            information = gramian / NOISE
            try:
                covariance = np.linalg.inv(information)
            except np.linalg.LinAlgError:  # pragma: no cover - singular by construction
                print(f"{name:>9}{count:>7}{'singular':>12}")
                continue
            sds = np.sqrt(np.maximum(np.diag(covariance), 0.0))
            cond = float(np.linalg.cond(gramian))
            print(f"{name:>9}{count:>7}{sds[0]:>12.4f}{sds[1]:>13.4f}{sds[2]:>15.4g}{cond:>12.3g}")
    print(
        "\nRead the accel column against the size of an acceleration that would\n"
        "matter. Log variance moves over a range of a few units, so an accel whose\n"
        "best possible posterior sd is far larger than that is not measurable from\n"
        "this observation however much process noise is fitted to it.\n"
    )


def _series(name: str, frame: str) -> tuple[np.ndarray, np.ndarray] | None:
    bars = load(name, frame)
    if bars is None:
        return None
    bars = {k: v[-LIMIT:] for k, v in bars.items()}
    out: list[float] = []
    when: list[float] = []
    for i in range(len(bars["close"])):
        one = dispersion(
            float(bars["open"][i]),
            float(bars["high"][i]),
            float(bars["low"][i]),
            float(bars["close"][i]),
        )
        if one is not None:
            out.append(one)
            when.append(float(bars["time"][i]))
    values = np.asarray(out, dtype=float)
    stamps = np.asarray(when, dtype=float)
    return (values, stamps) if len(values) > WARM + 2_000 else None


def _score(
    values: np.ndarray, stamps: np.ndarray, feed: str, frame: str, pinned: bool
) -> dict[str, float]:
    """One pass of the service's path, optionally with `accel` held at zero."""
    desk = Desk()
    breaches = dict.fromkeys(COVERS, 0)
    zs: list[float] = []
    published: list[float] = []
    spreads: list[float] = []
    accel: list[float] = []
    accel_sd: list[float] = []
    total_crps = 0.0
    scored = 0
    previous = None
    for i, value in enumerate(values):
        if previous is not None and i >= WARM:
            scored += 1
            for cover in COVERS:
                band = previous.covering(cover)
                if not band.low <= value <= band.high:
                    breaches[cover] += 1
            if previous.quantiles:
                total_crps += crps(previous.quantiles, float(value))
        got = desk.read(feed, frame, float(stamps[i]), float(value), NOISE)
        pool = desk._members[(feed, frame)]
        for one in pool.members:
            member = getattr(one, "_member", one)
            # `reverting` exposes `accel` as a property and refuses to carry
            # one - its own docstring says a consumer wanting the
            # acceleration's uncertainty is sent to `linear` - so the
            # covariance entry is the test of who actually holds the state.
            if not hasattr(member, "p22"):
                continue
            if i >= WARM and not pinned:
                accel.append(float(member.accel))
                accel_sd.append(math.sqrt(max(float(member.p22), 0.0)))
            if pinned:
                member.accel = 0.0
                member.p02 = 0.0
                member.p12 = 0.0
                member.p22 = 0.0
        if i >= WARM:
            zs.append(got.surprise)
            published.append(got.value)
            spreads.append(got.spread)
        previous = got
    if scored < 1_000:
        return {}
    out = {f"breach_{int(100 * c)}": breaches[c] / scored for c in COVERS}
    out["zvar"] = float(np.var(zs))
    out["crps"] = total_crps / scored
    out["value_sd"] = float(np.std(published))
    out["spread_median"] = float(np.median(spreads))
    out["n"] = float(scored)
    if accel:
        ratio = np.abs(np.asarray(accel)) / np.maximum(np.asarray(accel_sd), 1e-300)
        out["accel_over_sd"] = float(np.median(ratio))
        out["accel_sd"] = float(np.median(accel_sd))
    return out


def main() -> None:
    part_a()
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}
    print("classes:", ", ".join(f"{k} ({len(v)})" for k, v in sorted(wanted.items())), flush=True)

    for frame in FRAMES:
        print(f"\n## Parts B and C, {frame}: the member's own covariance, and whether it matters")
        print(
            f"{'class':>12}{'accel':>10}{'|a|/sd(a)':>11}{'sd(a)':>11}{'var z':>9}"
            f"{'CRPS':>9}{'breach .90':>12}{'breach .99':>12}{'sd(value)':>11}"
        )
        for klass, names in sorted(wanted.items()):
            series = [got for got in (_series(n, frame) for n in names) if got is not None]
            if not series:
                continue
            for pinned in (False, True):
                rows = [
                    _score(v, t, n, frame, pinned) for (v, t), n in zip(series, names, strict=False)
                ]
                rows = [r for r in rows if r]
                if not rows:
                    continue
                take = lambda key: float(np.median([r[key] for r in rows if key in r]))  # noqa: E731
                ratio = f"{take('accel_over_sd'):>11.3f}" if not pinned else f"{'-':>11}"
                sd = f"{take('accel_sd'):>11.4g}" if not pinned else f"{'-':>11}"
                print(
                    f"{klass:>12}{'pinned' if pinned else 'free':>10}{ratio}{sd}"
                    f"{take('zvar'):>9.3f}{take('crps'):>9.4f}"
                    f"{take('breach_90'):>12.4f}{take('breach_99'):>12.4f}"
                    f"{take('value_sd'):>11.4f}",
                    flush=True,
                )
    print(
        "\n\nPart C is the decision. `|a|/sd(a)` near zero says the fitted acceleration\n"
        "is indistinguishable from none, and a `pinned` row that matches the `free`\n"
        "one on every published column says the state carries nothing forward. Both\n"
        "together would make `jerk` a free parameter on an unobserved quantity - and\n"
        "a matching loop scaling that parameter has nothing to stop it, which is what\n"
        "`adapting-strata.md` measured running to its clamp.",
        flush=True,
    )


if __name__ == "__main__":
    main()
