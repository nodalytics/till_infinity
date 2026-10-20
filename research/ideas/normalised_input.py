"""Does normalising the input remove the clamp, rather than the clamp being raised?

`adapting_strata.md` found every traded member **pinned against
`adapting.MOST`** - `factor = 1000.000`, travel `1 to 1e+03` - with the loop's
own `excess` reading exactly what the sample reads. Released to 1e7 the loop
converges at a factor of **1.3 to 4.2 million**, so the process noise it wants
is six orders of magnitude above the member's starting value.

**Six orders of magnitude is a unit problem, not a tuning problem.** Every
member's default `jerk` and `sigma2` were set on **price**, and this desk folds
`log(garman_klass(...))`, which lives at about -16 with a spread near one where
a price lives at 1.5 or 4,400 with a spread of a basis point. A loop that has
to travel a million-fold before it starts being useful is converting units, and
it runs out of clamp before it finishes.

So the question this asks is whether the clamp needs raising at all, or whether
the input needs putting where the priors already are. Raising a clamp weakens
a guard that exists for a reason - `adapting.py`: "a process noise of infinity
is a state that is pure noise. Both are reachable by a loop chasing an
outlier" - and a unit change weakens nothing.

## A fixed affine transform, estimated where nothing is scored

`z = (x - m) / s`, with `m` and `s` the mean and standard deviation of the
first `WARM` readings - bars that are already excluded from every score. That
makes it **causal, constant and invertible**: it is a change of units and
nothing else.

It is deliberately **not** a trailing or expanding normalisation.
`trailing-zscore-fakes-reversion` measured what that family costs - a +0.137
effect at z 4.23 of which the shuffled twin took +0.111 - and AE-BCP's
structural limit in `indicator-libraries.md` is exactly this: standardising
over a trailing window makes a slow drift invisible by construction. A fixed
transform has neither problem, because it moves every bar by the same amount.

**`R` is normalised with it**, to `R / s^2`. The measurement variance is in the
units of the observation, so leaving it at 0.265 while dividing the input by
`s` would be comparing a filter that was handed the right noise against one
that was handed the wrong noise, and the arm would measure that instead.

## What the arms can show

* if `normalised` reaches `E[z^2]` near one at the **shipped** clamp, the fix
  is a unit change and the clamp stays where it is;
* if it still needs the released clamp, the units were not the problem;
* if it lands at the same 2.05 the released clamp reached, then whatever is
  left is the pooling rule rather than the process noise, which is what
  `pool-spread.md` is testing in parallel.

The constant-sigma Deriv family is the reference for a different reason than
usual here: its lever sits at **0.028**, nowhere near the ceiling, so it is the
one class where the clamp was never the constraint and normalising should
change nothing at all.
"""

from __future__ import annotations

import math
import sys
from collections import deque
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.statespace.adapting import MOST, Adapting  # noqa: E402
from till_infinity.statespace.diagnostics import crps  # noqa: E402
from till_infinity.statespace.engine import dispersion  # noqa: E402
from till_infinity.statespace.facade import Desk  # noqa: E402
from till_infinity.statespace.pacing import Pace  # noqa: E402
from till_infinity.statespace.pooling import DEFAULT, LEVERS, Pooled, _factories  # noqa: E402

NOISE = 0.265
COVERS = (0.90, 0.95, 0.99)
CLAMPS = (MOST, 1e7)
FRAMES = ("1h", "15m")
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 3
LIMIT = 12_000
WARM = 500


def _desk(feed: str, interval: str, most: float) -> Desk:
    desk = Desk()
    key = (feed, interval)
    built = _factories(DEFAULT)
    desk._members[key] = Pooled(
        names=DEFAULT,
        _pool=[
            Adapting(build=make, lever=LEVERS.get(name, "jerk"), mode="matching", most=most)
            for name, make in zip(DEFAULT, built, strict=False)
        ],
    )
    desk._paces[key] = Pace(exponent=desk.exponent)
    desk._residuals[key] = deque(maxlen=desk.window)
    return desk


def _series(bars: dict) -> tuple[np.ndarray, np.ndarray]:
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
    return np.asarray(out, dtype=float), np.asarray(when, dtype=float)


def _score(
    values: np.ndarray, stamps: np.ndarray, feed: str, frame: str, most: float, normalise: bool
) -> dict[str, float]:
    """One pass, optionally on a fixed affine transform of the input."""
    noise = NOISE
    if normalise:
        head = values[:WARM]
        centre, scale = float(head.mean()), float(head.std())
        if not scale > 0:
            return {}
        values = (values - centre) / scale
        # The measurement variance is in the units of the observation.
        noise = NOISE / (scale * scale)

    desk = _desk(feed, frame, most)
    breaches = dict.fromkeys(COVERS, 0)
    zs: list[float] = []
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
        got = desk.read(feed, frame, float(stamps[i]), float(value), noise)
        if i >= WARM:
            zs.append(got.surprise)
        previous = got
    if scored < 1_000:
        return {}
    pool = desk._members[(feed, frame)]
    reached = max(float(getattr(one, "factor", float("nan"))) for one in pool.members)
    out = {f"breach_{int(100 * c)}": breaches[c] / scored for c in COVERS}
    out["zvar"] = float(np.var(zs))
    # CRPS is in the units of the input, so the normalised arm's is not
    # comparable to the raw one's. Scaled back by `s^2` it is.
    out["crps"] = total_crps / scored
    out["reached"] = reached
    out["n"] = float(scored)
    return out


def main() -> None:
    print(
        "Does normalising the input remove the clamp, or does the clamp need raising?\n"
        "A fixed affine transform estimated on the first 500 readings, which are\n"
        "excluded from every score, with `R` normalised with it. `reached` is the\n"
        "lever factor the matching loop ended on - the shipped clamp is 1e3, and\n"
        "`adapting_strata.md` found every traded member sitting exactly on it.\n"
        "CRPS is in the units of the input, so compare it down a column, not across.\n",
        flush=True,
    )
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}
    print("classes:", ", ".join(f"{k} ({len(v)})" for k, v in sorted(wanted.items())), flush=True)

    for frame in FRAMES:
        rows: dict[tuple[str, float, bool], list[dict[str, float]]] = {}
        for klass, names in sorted(wanted.items()):
            for name in names:
                bars = load(name, frame)
                if bars is None:
                    continue
                bars = {k: v[-LIMIT:] for k, v in bars.items()}
                values, stamps = _series(bars)
                if len(values) < WARM + 2_000:
                    continue
                for most in CLAMPS:
                    for normalise in (False, True):
                        got = _score(values, stamps, name, frame, most, normalise)
                        if got:
                            rows.setdefault((klass, most, normalise), []).append(got)
        if not rows:
            print(f"\n=== {frame}: nothing loaded", flush=True)
            continue
        print(f"\n=== {frame}")
        print(
            f"{'class':>12}{'clamp':>8}{'input':>12}{'n':>9}{'var z':>9}"
            f"{'lever':>12}{'CRPS':>9}{'breach .90':>12}{'breach .95':>12}"
        )
        for klass in sorted({k for k, _, _ in rows}):
            for most in CLAMPS:
                for normalise in (False, True):
                    got = rows.get((klass, most, normalise))
                    if not got:
                        continue
                    take = lambda key: float(np.median([g[key] for g in got]))  # noqa: E731
                    pinned = " ON A CLAMP" if take("reached") >= most * 0.999 else ""
                    print(
                        f"{klass:>12}{most:>8.0e}{'normalised' if normalise else 'raw':>12}"
                        f"{int(sum(g['n'] for g in got)):>9,}{take('zvar'):>9.3f}"
                        f"{take('reached'):>12.3g}{take('crps'):>9.4f}"
                        f"{take('breach_90'):>12.4f}{take('breach_95'):>12.4f}{pinned}",
                        flush=True,
                    )
    print(
        "\n\nRead the `lever` column against the clamp beside it. If the normalised arm\n"
        "converges well inside 1e3 where the raw arm sits on it, the six orders of\n"
        "magnitude were units and the clamp never needed touching. If `var z` then\n"
        "stops short of one, what is left is not the process noise at all.",
        flush=True,
    )


if __name__ == "__main__":
    main()
