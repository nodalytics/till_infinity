"""How fast a slope actually wanders, against the constant that says it is 0.02.

`rates.py` specifies this measurement and does not run it:

> `Kalman.var_slope` says *how fast the true slope is believed to wander*,
> which is a property of the world and is currently set by
> `DRIFT_VOL_PER_HOUR = 0.02`, a number chosen rather than measured.
>
> Reporting the first does not measure the second. It does make the comparison
> possible, because an estimator that disagrees with the filter by more than
> its own standard error is evidence about the filter's `q`.

`levels.py` carries the constant with the same admission - "process noise per
hour, in volatility units... this is what stops a filter with many observations
from freezing solid" - and `linear.py` names it as the parameter nobody has
measured: "chosen per hour and applied at every timeframe and has never been
fitted."

So three modules point at one number. This measures it.

## The identity does the work

`linear.py` states it: for two readings separated by `dt`,

    var(second - first) = q * dt + 2 * R

With a slope *estimated* in consecutive windows, `R` is not a guess either - it
is `Slope.variance`, the estimator's own standard error, which `rates.py`
returns for exactly this comparison. So

    q = (var(slope change) - 2 * mean estimator variance) / dt

and every term on the right is measured. The subtraction is the point: a slope
series wanders partly because the world moved and partly because the estimator
is noisy, and a measurement that skips the second term attributes all of it to
the first and over-states `q`.

## A walk fails the cross-frame test too, so the test needs a null

`I6` is that a rate is per unit time, so a constant **per hour** applied at 3m
through 1d predicts the fitted value is the same at every frame. The first
version of this measured exactly that and found the fitted `q` falling by
orders of magnitude per frame - 3m reads 10,050 times the 1h value - and
**that is not evidence about the market.**

A walk has no slope. Its apparent slope over an `n`-bar window of `h`-hour bars
is a window artefact of size `sqrt(n) / (n * h)`, so the apparent wander scales
as a power of the bar duration and `q ~ 1 / (n * h^3)`. That predicts a
3m-to-1h ratio of `1 / 0.05^3 = 8000` against the 10,050 observed. **A walk
would fail the cross-frame test in the same direction and by roughly the same
amount**, so the failure says nothing until a walk is run through the identical
pipeline.

So the question is not whether `q` is constant across frames. It is whether the
market's `q` **exceeds a walk's at the same frame** - which is the question of
whether a slope exists at all, and the only form in which a level of `q` means
anything.

`nulls.Walk` is the package's floor for exactly this reason, and the walk null
here is built with each instrument's own per-bar spread so the only difference
from the real arm is the structure.

## In volatility units, because that is how the constant is quoted

`levels.py` converts with `vol.price_units(price, DRIFT_VOL_PER_HOUR)`, so the
constant is a multiple of the instrument's own volatility. The series here is
divided by its trailing per-bar spread before any slope is taken, so a fitted
`q` is directly comparable to `0.02` without a per-instrument conversion.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relationship_screen as screen  # noqa: E402

HOUR = 3600.0
#: The constant under test.
DRIFT_VOL_PER_HOUR = 0.02
#: Frames to fit at, so the per-hour claim can be checked across them.
FRAMES = tuple(os.environ.get("FRAMES", "3m,15m,1h,4h,1d").split(","))
#: Bars per slope window.
WINDOW = int(os.environ.get("WINDOW", "24"))
#: Trailing bars the volatility unit is estimated over.
SPAN = int(os.environ.get("SPAN", "100"))
#: Walk nulls per instrument per frame.
REPS = int(os.environ.get("REPS", "5"))
#: Hours one bar of each frame lasts.
HOURS = {
    "3m": 0.05,
    "15m": 0.25,
    "1h": 1.0,
    "4h": 4.0,
    "6h": 6.0,
    "8h": 8.0,
    "12h": 12.0,
    "1d": 24.0,
}


def in_vol_units(times, values, span: int = SPAN):
    """The series divided by its trailing per-bar spread, so a move of 1 is 1 sigma."""
    import numpy as np

    steps = np.diff(values)
    out_t, out_v, running = [], [], 0.0
    for at in range(span, len(values)):
        spread = float(np.std(steps[at - span : at]))
        if spread <= 0:
            continue
        running += (values[at] - values[at - 1]) / spread
        out_t.append(float(times[at]))
        out_v.append(running)
    return out_t, out_v


def slopes(times, values, window: int = WINDOW):
    """Non-overlapping window slopes per hour, with each one's own variance.

    Non-overlapping on purpose: consecutive overlapping windows share most of
    their data, so their estimator errors are correlated and the `2R` term in
    the identity would not be `2R`.
    """
    from till_infinity.statespace.rates import slope_per_hour

    out = []
    for start in range(0, len(values) - window, window):
        got = slope_per_hour(
            times[start : start + window], values[start : start + window]
        )
        if got is None or not math.isfinite(got.per_hour):
            continue
        if not math.isfinite(got.variance) or got.variance < 0:
            continue
        middle = (times[start] + times[start + window - 1]) / 2.0
        out.append((middle, got.per_hour, got.variance))
    return out


def fit_q(found) -> dict[str, float]:
    """`q` from the identity, with the estimator's variance subtracted off."""
    import numpy as np

    if len(found) < 40:
        return {}
    gaps, changes, noise = [], [], []
    for i in range(1, len(found)):
        dt = (found[i][0] - found[i - 1][0]) / HOUR
        if dt <= 0:
            continue
        gaps.append(dt)
        changes.append(found[i][1] - found[i - 1][1])
        noise.append(found[i][2] + found[i - 1][2])
    if len(changes) < 30:
        return {}
    dt = float(statistics.median(gaps))
    observed = float(np.var(changes))
    # The `2R` term, measured rather than assumed: the sum of the two windows'
    # own estimator variances, averaged over pairs.
    estimator = float(np.mean(noise))
    raw = (observed - estimator) / dt
    return {
        "q": raw,
        "q_naive": observed / dt,
        "observed": observed,
        "estimator": estimator,
        "share_noise": estimator / observed if observed > 0 else float("nan"),
        "dt": dt,
        "n": float(len(changes)),
    }


def walk_like(values, rng):
    """An isotropic walk with the same per-step scale, in the same vol units."""
    import numpy as np

    steps = np.diff(np.asarray(values, dtype=float))
    scale = float(steps.std()) or 1e-9
    drawn = rng.standard_normal(len(steps)) * scale
    return list(np.concatenate([[values[0]], values[0] + np.cumsum(drawn)]))


def main() -> None:
    print(
        f"slope over {WINDOW}-bar non-overlapping windows, volatility units from\n"
        f"{SPAN} trailing bars, against DRIFT_VOL_PER_HOUR = {DRIFT_VOL_PER_HOUR}\n"
    )
    import numpy as np

    rng = np.random.default_rng(20261013)
    names = [n for n in screen.TRADED if screen.load(n) is not None][:10]

    print("=" * 112)
    print("ARM 1  the fitted q per frame, and whether one per-hour number fits all")
    print("=" * 112)
    print(
        f"{'instrument':<12}{'frame':>6}{'dt hr':>7}{'q fitted':>11}{'q walk':>11}"
        f"{'vs walk':>9}{'noise share':>13}{'n':>7}"
    )
    rows: dict[str, list[tuple[str, float]]] = {}
    for name in names:
        for frame in FRAMES:
            got = screen.load(name, frame)
            if got is None:
                continue
            times, values = in_vol_units(got[0], got[1])
            if len(values) < WINDOW * 60:
                continue
            fitted = fit_q(slopes(times, values))
            if not fitted or not math.isfinite(fitted["q"]) or fitted["q"] <= 0:
                continue
            # The same pipeline on a walk with this series' own scale. Without
            # it the level of `q` and its cross-frame scaling are both
            # uninterpretable, because a walk reproduces the scaling.
            walked = []
            for _ in range(REPS):
                got_null = fit_q(slopes(times, walk_like(values, rng)))
                if got_null and math.isfinite(got_null["q"]) and got_null["q"] > 0:
                    walked.append(got_null["q"])
            null_q = statistics.median(walked) if walked else float("nan")
            rows.setdefault(frame, []).append((name, fitted["q"], null_q))
            print(
                f"{name:<12}{frame:>6}{fitted['dt']:>7.2f}{fitted['q']:>11.5f}"
                f"{null_q:>11.5f}"
                f"{fitted['q'] / null_q if null_q and math.isfinite(null_q) else float('nan'):>9.2f}"
                f"{fitted['share_noise']:>13.3f}{fitted['n']:>7.0f}"
            )

    if not rows:
        print("  nothing fitted")
        return
    print("\n" + "=" * 112)
    print("ARM 2  does a market's slope wander more than a walk's at the same frame")
    print("=" * 112)
    print(
        f"{'frame':>8}{'instruments':>13}{'median q':>12}{'median walk':>13}"
        f"{'ratio':>8}{'above walk':>12}{'vs 0.02':>10}"
    )
    for frame in FRAMES:
        here = rows.get(frame)
        if not here:
            continue
        middle = statistics.median(q for _, q, _ in here)
        pairs = [(q, w) for _, q, w in here if math.isfinite(w) and w > 0]
        null_mid = statistics.median(w for _, w in pairs) if pairs else float("nan")
        above = sum(1 for q, w in pairs if q > w)
        print(
            f"{frame:>8}{len(here):>13}{middle:>12.5f}{null_mid:>13.5f}"
            f"{middle / null_mid if pairs else float('nan'):>8.2f}"
            f"{f'{above}/{len(pairs)}':>12}"
            f"{middle / DRIFT_VOL_PER_HOUR:>10.1f}"
        )
    print(
        "\n**`ratio` is the measurement and `vs 0.02` is not.** The fitted `q`\n"
        "falls by orders of magnitude per frame, and a walk does the same thing\n"
        "for a reason that has nothing to do with markets: a walk has no slope,\n"
        "so its apparent slope is a window artefact scaling as `1/(n*h^3)`. The\n"
        "only readable question is whether the market exceeds its own walk at\n"
        "each frame.\n\n"
        "`noise share` is why the estimator variance is subtracted: it is the\n"
        "share of the observed wander that is the estimator rather than the\n"
        "world, and skipping it attributes all of it to the world."
    )


if __name__ == "__main__":
    main()
