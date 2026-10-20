"""Is the matching loop locally honest and globally wrong, or just wrong?

`pool-spread.md` measured `E[z^2]` per member at the measured `R = 0.265` and
found 2.0 to 3.1 on markets against **1.01 to 1.03 on a generator whose sigma
is constant by construction**. `adapting.Adapting` exists to drive exactly that
quantity to one, and it succeeds where the latent variance is stationary and
misses by two to three fold where it moves.

Two explanations fit, and they want opposite fixes.

* **Composition.** An exponentially weighted match converges on the periods the
  series spends most of its time in, and the unconditional second moment of a
  series whose conditional variance clusters exceeds one even when every local
  window is matched. Nothing is broken; the lever is answering a different
  question from the one the unconditional average asks. The fix, if it is one,
  is in how the loop weights its history.
* **Lag or a clamp.** The loop is too slow for the regime changes it meets, or
  its lever is pinned at `LEAST`/`MOST` and cannot reach the value it wants.
  Then the fix is the step, the memory or the clamp.

## The loop publishes its own answer, so read that first

`Adapting` exposes `excess` - the exponentially weighted mean of the squared
standardised innovation, whose docstring says "**1.0 is an honest filter**" -
and `factor`, `lowest`, `highest`, under a comment saying a loop that never
moves is not adapting and one sitting on a clamp is not either.

That makes Part A arithmetic rather than inference. If `excess` sits at one
while the **sample** mean of `z^2` over the same bars reads 2.5, the loop is
locally converged and the unconditional average is measuring something else:
composition, demonstrated by the loop's own two numbers disagreeing. If
`excess` itself reads 2.5, the loop has not converged, and `factor` against the
clamps says whether it could.

## Then strata, then the lever it would be fixed with

Part B scores `E[z^2]` inside deciles of two things known **before** the
reading: the trailing mean of log variance, which is the level, and the
previous bar's `|z|`, which is how surprised the filter just was. Composition
predicts the first shows a pattern and each decile sits near one; lag predicts
the miss concentrates in the high-`|z|` deciles, right after a move.

Part C sweeps `Adapting.memory` from 16 to 1024 observations. Under composition
no memory fixes the unconditional average - a shorter one tracks the local
level better and makes the global mismatch no smaller. Under lag, a shorter
memory closes it.

Controls: the Deriv volatility family, where the answer is already one; and two
synthetics - one with a **clustered** latent variance, which must reproduce the
pattern if composition is the mechanism, and one with a **constant** latent
variance, which must not. Planting the mechanism is what makes a null here mean
anything.
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

from till_infinity.statespace.adapting import LEAST, MEMORY, MOST, Adapting  # noqa: E402
from till_infinity.statespace.engine import dispersion  # noqa: E402
from till_infinity.statespace.pooling import DEFAULT, LEVERS, Pooled, _factories  # noqa: E402

#: The measured sampling variance of `log(garman_klass)`, where the miss is
#: largest and cleanest. `dispersion-noise.md`.
NOISE = 0.265

MEMORIES = (16.0, 64.0, 256.0, 1_024.0)
#: Clamps for Part D. `MOST` ships at 1e3, which every traded member reaches.
CLAMPS = (1e3, 1e5, 1e7, 1e9)
FRAMES = ("1h",)
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 3
LIMIT = 12_000
WARM = 500
STRATA = 10
#: Bars in the trailing mean that strata are cut on. Known before the reading.
LOOKBACK = 48
SEED = 20261020


def _pool(memory: float = MEMORY, most: float = MOST) -> Pooled:
    """The shipped pool, with two knobs reachable: the loop's memory and clamp."""
    built = _factories(DEFAULT)
    return Pooled(
        names=DEFAULT,
        _pool=[
            Adapting(
                build=make,
                lever=LEVERS.get(name, "jerk"),
                mode="matching",
                memory=memory,
                most=most,
            )
            for name, make in zip(DEFAULT, built, strict=False)
        ],
    )


def _fold(
    series: np.ndarray,
    memory: float = MEMORY,
    times: np.ndarray | None = None,
    most: float = MOST,
) -> dict:
    """Fold a log-variance series through the pool and keep every diagnostic.

    **`times` is the arm, not a convenience.** Every member's `Q` is per hour
    and `predict` takes the elapsed time, so a weekend inflates the predicted
    variance by sixty-five hours' worth before Monday's bar - and volatility
    does not become sixty-five hours more uncertain over a weekend, it mean
    reverts. `pool_calibration.py` folded the real stamps and read `E[z^2]` of
    2.0 to 3.1; this harness was written folding a uniform hourly clock. If the
    two disagree on the same bars, the miss is the **time axis** rather than
    the loop, and no step, memory or clamp reaches it.
    """
    pool = _pool(memory, most)
    zs: list[float] = []
    per: dict[str, list[float]] = {}
    excess: dict[str, list[float]] = {}
    when = 0.0
    for i, value in enumerate(series):
        when = float(times[i]) if times is not None else when + 3600.0
        pool.predict(when, 0.0)
        spread = float(pool.variance) + NOISE
        if spread > 0 and i >= WARM:
            zs.append((float(value) - float(pool.value)) / math.sqrt(spread))
        pool.update(float(value), NOISE, when)
        if i >= WARM:
            for name, member in zip(pool.names, pool.members, strict=False):
                standardised = float(getattr(member, "last_standardised", 0.0))
                if math.isfinite(standardised):
                    per.setdefault(name, []).append(standardised)
                excess.setdefault(name, []).append(float(getattr(member, "excess", float("nan"))))
    levers = {
        name: (
            float(getattr(member, "factor", float("nan"))),
            float(getattr(member, "lowest", float("nan"))),
            float(getattr(member, "highest", float("nan"))),
        )
        for name, member in zip(pool.names, pool.members, strict=False)
    }
    return {"pool": np.asarray(zs), "per": per, "excess": excess, "levers": levers}


def _within(values: np.ndarray, cut: np.ndarray) -> list[float]:
    """`E[z^2]` inside each decile of `cut`, which must be known beforehand."""
    good = np.isfinite(cut) & np.isfinite(values)
    if good.sum() < STRATA * 50:
        return []
    edges = np.quantile(cut[good], np.linspace(0, 1, STRATA + 1)[1:-1])
    which = np.digitize(cut, edges)
    out = []
    for band in range(STRATA):
        keep = good & (which == band)
        out.append(float(np.mean(np.square(values[keep]))) if keep.sum() >= 50 else float("nan"))
    return out


def _series(name: str, frame: str) -> tuple[np.ndarray, np.ndarray] | None:
    """The log-variance series and the stamps each reading arrived at."""
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
    series = np.asarray(out, dtype=float)
    stamps = np.asarray(when, dtype=float)
    return (series, stamps) if len(series) > WARM + 2_000 else None


#: Half-amplitude of the planted daily cycle, in log variance. 0.55 gives a
#: peak-to-trough ratio of `exp(1.1)` - about **3x in variance** - which is
#: what `seasonality-belongs-on-q` measured on FX, peaking at 14-15 UTC.
CYCLE = 0.55

#: Ticks a planted bar is built from, for the arm whose noise has the
#: estimator's real shape. `dispersion-noise.md` measures `log(garman_klass)`
#: at variance 0.2702 and bias -0.18 on a 1,440-tick bar.
TICKS = 1_440


def _planted(rng: np.random.Generator, kind: str, rows: int = 12_000) -> np.ndarray:
    """Log variance under three planted mechanisms.

    * `constant` - a flat latent level. Nothing for the loop to chase.
    * `clustered` - an AR(1) in the level with a long half-life, which is what
      volatility of volatility looks like.
    * `cycled` - the clustered level plus a **deterministic daily cycle**, a
      mechanism neither of the others has and the only one left after they
      both came back near one. `seasonality-belongs-on-q` measured FX peaking
      at 14-15 UTC at **3x**, and `seasonal.Profile` models exactly that clock
      - and nothing outside this package calls it, `facade.Desk` included.
      `adapting.py`'s own docstring asks whether the loop beats that clock;
      this asks whether the loop can absorb it at all.
    * `estimated` - the same clustered level, but the observation is
      `log(garman_klass(...))` of **simulated bars** at that level rather than
      the level plus a Gaussian draw.

    The third arm exists because the first two came back at `E[z^2]` near one,
    which refutes composition as the mechanism: clustering alone does not
    inflate the unconditional average. What they do not have is the
    estimator's **error shape**. `log` of a range estimator is left-skewed with
    a long tail - a bar that barely moves reads very negative - and a filter
    with Gaussian assumptions meets that tail as a large innovation. Variance
    and bias are measured in `dispersion-noise.md`; the shape is what this arm
    adds, and it is the only one of the three that uses the real one.
    """
    noise = math.sqrt(NOISE)
    if kind == "constant":
        return rng.normal(0.0, noise, rows)

    level = 0.0
    levels = np.zeros(rows)
    for i in range(rows):
        level = 0.995 * level + rng.normal(0.0, 0.12)
        levels[i] = level
    if kind == "clustered":
        return levels + rng.normal(0.0, noise, rows)
    if kind == "cycled":
        hours = np.arange(rows) % 24
        cycle = CYCLE * np.cos(2.0 * math.pi * (hours - 14.0) / 24.0)
        return levels + cycle + rng.normal(0.0, noise, rows)

    # `estimated`: bars at each level, through the estimator the service uses.
    out = np.zeros(rows)
    gk = 2.0 * math.log(2.0) - 1.0
    for i in range(rows):
        sigma = math.exp(0.5 * levels[i])
        step = rng.normal(0.0, sigma / math.sqrt(TICKS), TICKS)
        walk = np.cumsum(step)
        high = max(0.0, float(walk.max()))
        low = min(0.0, float(walk.min()))
        body = float(walk[-1])
        span = high - low
        var = max(0.5 * span * span - gk * body * body, 1e-300)
        out[i] = math.log(var)
    return out


def _report(label: str, got: dict) -> None:
    """One block: the loop's belief, the sample, and the lever's travel."""
    pool = got["pool"]
    print(f"\n=== {label}  ({len(pool):,} scored)")
    print(f"{'member':>12}{'E[z^2] sample':>15}{'excess (loop)':>15}{'factor':>10}{'travel':>22}")
    for name in sorted(got["per"]):
        sample = float(np.mean(np.square(got["per"][name])))
        belief = float(np.nanmean(got["excess"][name]))
        factor, lowest, highest = got["levers"][name]
        pinned = ""
        if highest >= MOST * 0.999 or lowest <= LEAST * 1.001:
            pinned = "  ON A CLAMP"
        print(
            f"{name:>12}{sample:>15.3f}{belief:>15.3f}{factor:>10.3f}"
            f"{f'{lowest:.3g} to {highest:.3g}':>22}{pinned}"
        )
    print(f"{'pool':>12}{float(np.mean(np.square(pool))):>15.3f}")


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        "Is the matching loop locally honest and globally wrong, or just wrong?\n"
        f"R pinned at the measured {NOISE}. `excess` is the loop's own error signal,\n"
        "whose target is 1.0; `E[z^2] sample` is the unconditional average of the\n"
        "same quantity over the same bars. If they disagree, the loop is converged\n"
        "on something the unconditional average does not ask about.\n",
        flush=True,
    )

    print("## Part A, controls first: three planted mechanisms")
    for kind in ("constant", "clustered", "estimated", "cycled"):
        series = _planted(rng, kind)
        got = _fold(series)
        _report(f"planted, {kind}", got)
        hours = (np.arange(len(series)) % 24)[WARM : WARM + len(got["pool"])]
        inside = _within(got["pool"], hours.astype(float))
        if inside:
            print("      by hour of day: " + " ".join(f"{v:5.2f}" for v in inside))

    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}

    for frame in FRAMES:
        print(f"\n\n## Part A, real bars at {frame}")
        keep: dict[str, list[tuple[str, np.ndarray, np.ndarray]]] = {}
        for klass, names in sorted(wanted.items()):
            for name in names:
                loaded = _series(name, frame)
                if loaded is None:
                    continue
                series, stamps = loaded
                keep.setdefault(klass, []).append((name, series, stamps))
                _report(f"{frame}, {klass}, {name} - real stamps", _fold(series, times=stamps))
                _report(f"{frame}, {klass}, {name} - uniform clock", _fold(series))
                gaps = np.diff(stamps) / 3600.0
                print(
                    f"      gaps in hours: median {float(np.median(gaps)):.2f}, "
                    f"p99 {float(np.quantile(gaps, 0.99)):.1f}, "
                    f"max {float(gaps.max()):.1f}, "
                    f"share over 2h {float((gaps > 2.0).mean()):.3f}"
                )

        print(f"\n\n## Part B, {frame}: E[z^2] inside deciles of what was known beforehand")
        for klass, loaded in sorted(keep.items()):
            rows_level: list[list[float]] = []
            rows_shock: list[list[float]] = []
            flat: list[float] = []
            for _, series, stamps in loaded:
                got = _fold(series, times=stamps)
                pool = got["pool"]
                tail = series[WARM : WARM + len(pool)]
                level = np.full(len(pool), np.nan)
                for i in range(len(pool)):
                    start = WARM + i - LOOKBACK
                    if start >= 0:
                        level[i] = float(series[start : WARM + i].mean())
                shock = np.full(len(pool), np.nan)
                shock[1:] = np.abs(pool[:-1])
                del tail
                one = _within(pool, level)
                two = _within(pool, shock)
                if one:
                    rows_level.append(one)
                if two:
                    rows_shock.append(two)
                flat.append(float(np.mean(np.square(pool))))
            if not rows_level:
                continue
            print(f"\n--- {klass}: unconditional E[z^2] {float(np.median(flat)):.3f}")
            for title, rows in (("by level", rows_level), ("by previous |z|", rows_shock)):
                median = np.nanmedian(np.asarray(rows, dtype=float), axis=0)
                print(f"  {title:>15}: " + " ".join(f"{v:5.2f}" for v in median), flush=True)
            print(
                "                   deciles low to high; composition predicts a pattern here\n"
                "                   with each cell near one, lag predicts the right-hand\n"
                "                   cells of the second row carrying the miss"
            )

        print(f"\n\n## Part C, {frame}: does the loop's memory reach it")
        print(f"{'class':>12}" + "".join(f"{f'memory {m:g}':>14}" for m in MEMORIES))
        for klass, loaded in sorted(keep.items()):
            row = f"{klass:>12}"
            for memory in MEMORIES:
                got = [
                    float(np.mean(np.square(_fold(s, memory, times=t)["pool"])))
                    for _, s, t in loaded
                ]
                row += f"{float(np.median(got)):>14.3f}"
            print(row, flush=True)
        print(f"\n\n## Part D, {frame}: release the clamp and see if the loop can reach one")
        print(
            "Every member on every traded instrument finished at `factor = 1000`,\n"
            "which is `MOST` exactly, with `excess` reading what the sample reads.\n"
            "The loop knows how wrong it is and is not allowed to move, so the\n"
            "diagnosis is a clamp - and a clamp is proved by releasing it.\n"
        )
        print(f"{'class':>12}" + "".join(f"{f'most {m:g}':>16}" for m in CLAMPS))
        for klass, loaded in sorted(keep.items()):
            row = f"{klass:>12}"
            for most in CLAMPS:
                scores = []
                reached = []
                for _, series, stamps in loaded:
                    one = _fold(series, times=stamps, most=most)
                    scores.append(float(np.mean(np.square(one["pool"]))))
                    reached.append(max(v[0] for v in one["levers"].values()))
                row += f"{float(np.median(scores)):>10.3f}{f'@{float(np.median(reached)):.3g}':>6}"
            print(row, flush=True)
        print(
            "\n`@` is the median lever factor reached. A class whose `E[z^2]` falls to\n"
            "one at a factor well inside the clamp it was given has been diagnosed:\n"
            "the loop wanted that much process noise and `MOST` forbade it. One that\n"
            "keeps rising with the clamp has a different problem."
        )
    print(
        "\n\nPart C is the decision. Under composition the unconditional average is\n"
        "flat in memory - a shorter window tracks the local level better and leaves\n"
        "the global mismatch where it was - and under lag it falls as the memory\n"
        "shortens. If it falls, the fix is a constant; if it is flat, the published\n"
        "spread cannot be made honest by this loop at all and the rule or the\n"
        "estimator has to carry it.",
        flush=True,
    )


if __name__ == "__main__":
    main()
