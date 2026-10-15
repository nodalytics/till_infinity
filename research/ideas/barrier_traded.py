"""The discrete-monitoring shift on traded instruments, where it is not measured.

`statespace/bounding.py` converts between a target, a stop, a probability and a
horizon with two first-passage laws, and both carry an additive barrier
correction `B`:

    P = (down + B) / (up + down + 2B)        T = (up + B) * (down + B)

`B` is `SHIFT = 0.5826`, the Broadie-Glasserman-Kou constant `-zeta(1/2)/sqrt(2*pi)`:
a barrier watched once a bar sits effectively that much further away than one
watched continuously, because the walk can cross and come back inside the bar.

`SHIFTS` carries **measured** replacements for eight Deriv families, and
`barrier_overshoot.py` earned them - the `Volatility_*` control recovers 0.5745
to 0.6002 against the theoretical 0.5826, which is the check that an estimator
reproduces the constant it replaces.

**There is not one traded instrument in that table.** `shifts_for` falls back to
`(SHIFT, SHIFT)` for every live feed on the desk, and the fallback's docstring
is explicit that this is the honest default for a process whose asymmetry has
not been measured - so the gap is known and not yet closed.

It matters because `SHIFT` is a **diffusion** result and traded instruments are
not diffusions. `synthetics-are-a-poor-tail-control` records kurtosis of 3.19 on
the synthetic legs against 20.07 traded, and the overshoot is precisely a
tail quantity: a barrier crossed by a jump is overshot by the size of the jump.
So the prediction is that traded `B` exceeds 0.5826, and the sharper prediction
is that it **grows with the barrier distance**, because a distant barrier is
reached disproportionately by large moves where a diffusion's overshoot is
distance-free.

## What is measured, and the one thing synthetics do not have

The mean excess beyond the barrier at first crossing in units of one bar's
standard deviation, by direction, non-overlapping entries - the same estimand as
`barrier_overshoot.py`.

With one addition: a traded series has **session gaps**. A weekend is one row
in the cache and a large step in the diff, and that step is a gap rather than a
bar of trading, so a barrier "crossed" there was never watched at all. Every
path here is therefore run inside a gap-free segment, and the all-steps arm is
reported beside it so the size of that choice is visible rather than argued.
"""

from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import relationship_screen as screen  # noqa: E402

#: The constant being tested.
SHIFT = 0.5826
#: Barrier distances in bar standard deviations. 16 is left out for the reason
#: `barrier_overshoot.REACHES` records: first passage needs about `reach^2`
#: bars, so a window four times that leaves too few independent entries.
REACHES = (2.0, 4.0, 8.0)
FRAMES = ("15m", "1h", "4h")
#: A step whose timestamp gap exceeds this many modal intervals starts a new
#: segment. 1.5 rather than 2 so a single missing bar also breaks the path.
GAPS = 1.5
#: Bars a segment needs beyond the window, or it contributes nothing.
LEAST_SEGMENT = 16
#: Entries each direction needs before a mean is reported.
LEAST = 12
#: `touches.py` publishes for FX at 15m only, so the majors lead the table.
MAJORS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD")
CROSSES = ("EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD", "CADJPY")
METALS = ("XAUUSD", "XAGUSD")
#: The control that has to reproduce the published figures.
CONTROL = ("Volatility_75_Index", "Volatility_100_Index", "Volatility_25_Index")
GROUPS = (("fx majors", MAJORS), ("fx crosses", CROSSES), ("metals", METALS))
SEED = 20261015


def segments(times, values):
    """Gap-free runs of log prices, as step arrays.

    The modal interval is taken from the median timestamp difference rather
    than from the frame's name, so a frame whose bars are not where its label
    says still segments correctly.
    """
    import numpy as np

    if len(times) < 4:
        return []
    steps = np.diff(np.asarray(values, dtype=float))
    gaps = np.diff(np.asarray(times, dtype=float))
    modal = float(np.median(gaps))
    if not (modal > 0):
        return [steps]
    breaks = np.flatnonzero(gaps > GAPS * modal)
    out, start = [], 0
    for at in list(breaks) + [len(steps)]:
        run = steps[start : int(at)]
        if len(run) >= LEAST_SEGMENT:
            out.append(run)
        start = int(at) + 1
    return out


def overshoot(runs, reach: float, sd: float):
    """`(up, down, counts, share up)` pooled over gap-free runs.

    The same walk-forward as `barrier_overshoot.overshoots` - non-overlapping
    entries, a window of about `4 * reach^2` bars - with the path confined to
    one run so no first passage spans a session gap. `sd` is passed in rather
    than taken per run, because a run's own standard deviation would rescale
    the barrier by how volatile that particular week was.
    """
    import numpy as np

    if sd <= 0:
        return None
    level = reach * sd
    span = int(max(4.0 * reach * reach, 64))
    up: list[float] = []
    down: list[float] = []
    for run in runs:
        if len(run) <= span:
            continue
        for start in range(0, len(run) - span, span):
            path = np.cumsum(run[start : start + span])
            hit = np.flatnonzero(np.abs(path) >= level)
            if not len(hit):
                continue
            where = hit[0]
            excess = (abs(path[where]) - level) / sd
            (up if path[where] > 0 else down).append(excess)
    if len(up) < LEAST or len(down) < LEAST:
        return None
    return {
        "up": statistics.mean(up),
        "down": statistics.mean(down),
        "n": len(up) + len(down),
        "share_up": len(up) / (len(up) + len(down)),
    }


def shape(steps) -> tuple[float, float]:
    """`(skew, excess kurtosis)` of the bar step, the tail the prediction is about."""
    import numpy as np

    got = np.asarray(steps, dtype=float)
    sd = float(got.std())
    if sd <= 0:
        return float("nan"), float("nan")
    centred = (got - got.mean()) / sd
    return float((centred**3).mean()), float((centred**4).mean() - 3.0)


def planted() -> None:
    """A Gaussian walk through the segmented estimator must recover 0.5826."""
    import numpy as np

    rng = np.random.default_rng(SEED)
    print("=" * 100)
    print("ARM 0  the control: a driftless Gaussian walk, segmented the same way")
    print("=" * 100)
    print(f"  {'reach':>7}{'B up':>9}{'B down':>9}{'ratio':>8}{'n':>8}   expected {SHIFT}")
    steps = rng.normal(0.0, 1.0, 400_000)
    runs = [steps[at : at + 2000] for at in range(0, len(steps), 2000)]
    for reach in REACHES:
        got = overshoot(runs, reach, float(steps.std()))
        if got is None:
            continue
        ratio = got["up"] / got["down"] if got["down"] > 0 else float("nan")
        print(
            f"  {reach:>7.0f}{got['up']:>9.4f}{got['down']:>9.4f}"
            f"{ratio:>8.3f}{got['n']:>8,}"
        )
    print(
        "  An estimator that cannot reproduce the constant it replaces has no\n"
        "  business replacing it. Segmentation is the only change from\n"
        "  `barrier_overshoot.py`, so this is also the check that it is harmless.\n"
    )


def main() -> None:
    import numpy as np

    print(
        f"barrier distances {REACHES} sd, non-overlapping entries inside gap-free\n"
        f"segments, against a single symmetric shift of {SHIFT}\n"
    )
    planted()
    screen.LIMIT = 40000
    for frame in FRAMES:
        print("=" * 100)
        print(f"{frame}")
        print("=" * 100)
        head = f"  {'instrument':<22}{'kurt':>8}{'skew':>8}{'reach':>7}"
        print(head + f"{'B up':>9}{'B down':>9}{'ratio':>8}{'all-steps':>11}{'n':>8}")
        rows: list[tuple[str, str, float, dict]] = []
        for group, names in (*GROUPS, ("control", CONTROL)):
            for name in names:
                series = screen.load(name, frame)
                if series is None:
                    continue
                times, values = series[0], series[1]
                runs = segments(times, values)
                if not runs:
                    continue
                every = np.diff(np.asarray(values, dtype=float))
                sd = float(np.concatenate(runs).std())
                skew, kurt = shape(np.concatenate(runs))
                for reach in REACHES:
                    got = overshoot(runs, reach, sd)
                    if got is None:
                        continue
                    # The same measurement with gaps left in, for comparison.
                    loose = overshoot([every], reach, float(every.std()))
                    ratio = got["up"] / got["down"] if got["down"] > 0 else float("nan")
                    both = (got["up"] + got["down"]) / 2.0
                    unseg = (
                        (loose["up"] + loose["down"]) / 2.0 if loose else float("nan")
                    )
                    rows.append((group, name, reach, got))
                    print(
                        f"  {name:<22}{kurt:>8.1f}{skew:>+8.2f}{reach:>7.0f}"
                        f"{got['up']:>9.4f}{got['down']:>9.4f}{ratio:>8.3f}"
                        f"{unseg:>11.4f}{got['n']:>8,}"
                    )
                    _ = both
        if not rows:
            continue
        print(f"\n  {'group':<14}{'reach':>7}{'B (median)':>12}{'vs 0.5826':>11}{'rows':>7}")
        for group in ("fx majors", "fx crosses", "metals", "control"):
            for reach in REACHES:
                here = [r for r in rows if r[0] == group and r[2] == reach]
                if not here:
                    continue
                middle = statistics.median(
                    (r[3]["up"] + r[3]["down"]) / 2.0 for r in here
                )
                print(
                    f"  {group:<14}{reach:>7.0f}{middle:>12.4f}"
                    f"{middle - SHIFT:>+11.4f}{len(here):>7}"
                )
        print(
            "  `B (median)` averages the two directions, since no traded feed has a\n"
            "  published one-sided process. A figure above 0.5826 that **grows with\n"
            "  the reach** is the fat-tail signature; one that is flat across reaches\n"
            "  and near the constant means the diffusion result holds after all.\n"
        )
    _ = math


if __name__ == "__main__":
    main()
