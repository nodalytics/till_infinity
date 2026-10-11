"""Does a phase-locked seasonal earn its states on real series?

Asked on 2026-10-11, after `jpy-silver-pair.md` found the largest effect in
that study was an hour-of-day pattern: the USDJPY-XAGUSD correlation ran from
-0.054 at 21:00 UTC to -0.394 at 12:00. Nothing in the state-space package
was seasonal, so `seasonal.py` was written and this measures it.

## What is being asked

Not whether markets have sessions - they plainly do, and the volatility
profile of the trading day is one of the oldest facts in the subject. The
question is whether a **phase-locked seasonal component on the level** earns
its six states per period, which is a different and much weaker claim: a
daily pattern in *volatility* says nothing about a daily pattern in *price*,
and it is the price the member observes.

## Three nulls, and the second is the one that matters

* **matched** - the identical member with `seasonal_on=False`: same level
  noise, same anchor, harmonics not observed. On a flat series the full
  member *loses* by 39 nats, so flexibility alone cannot win this.
* **a broken clock** - the same series with the *observations* slid half a
  period against the timestamps, so each value arrives at the wrong time of
  day. If that fits as well, the component is a smooth periodic function of
  something else and the alignment to the clock is doing no work. **This is
  the null specific to seasonals and the easy one to get wrong.**

  The first attempt shifted every timestamp by twelve hours and produced a
  likelihood identical to the real one in all 26 cells, to one decimal. That
  was not a finding about markets, it was a vacuous null: a *uniform* shift
  only relabels time, the relative spacing is untouched, and the phase offset
  is a free parameter absorbed into each harmonic's `(a, b)` pair. The member
  simply refits the same shape shifted. Sliding the data against the stamps
  is the version that changes which value sits at which phase.
* **generated markets** - the Deriv synthetics have no sessions at all. A
  seasonal amplitude there is six spare parameters fitting noise.

A fourth reading comes free: the same series at 1h and 4h should give the
**same fitted daily shape**, because the rotation is in hours. A shape that
changes with the frame would mean the component is counting bars after all.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.structures.statespace.seasonal import Seasonal

HOUR = 3600.0
TAU = 2.0 * math.pi

TRADED = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "XAUUSD",
    "XAGUSD",
    "BTCUSD",
    "ETHUSD",
    "SPX500",
)
GENERATED = ("Volatility_75_Index", "Volatility_100_Index", "Step_Index", "Boom_500_Index")

FRAMES = tuple(os.environ.get("FRAMES", "1h,4h").split(","))
PERIODS = (24.0, 168.0)
HARMONICS = 3
SINCE = float(os.environ.get("SINCE", "1420070400"))
LIMIT = int(os.environ.get("LIMIT", "30000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    for path in (CACHE / f"{name}.{frame}.npz", Path(f"data/seqlab/{name}.{frame}.npz")):
        if not path.exists():
            continue
        with np.load(path) as bundle:
            if not {"time", "close"} <= set(bundle.keys()):
                continue
            order = np.argsort(bundle["time"])
            times = bundle["time"][order].tolist()
            closes = bundle["close"][order].tolist()
        first = 0
        while first < len(times) and times[first] < SINCE:
            first += 1
        times, closes = times[first:], closes[first:]
        if len(times) > LIMIT:
            times, closes = times[-LIMIT:], closes[-LIMIT:]
        return (times, closes) if len(times) > 2000 else None
    return None


def score(times, values, *, on: bool, slide: int = 0):
    """One pass, returning the likelihood, the amplitude and the daily shape.

    The measurement noise is the series' own one-step spread, fixed and shared
    across every arm. Fitting it per arm would let the seasonal win by being
    better calibrated, which is the comparison this is trying to avoid.
    """
    if slide:
        # The values slid against the stamps: same stamps, same values, each
        # arriving at the wrong time of day. Both arms are trimmed to the
        # overlap so the comparison is over the same number of readings.
        times = times[: len(times) - slide]
        values = values[slide:]
    steps = [values[i] - values[i - 1] for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9

    member = Seasonal(periods=PERIODS, harmonics=HARMONICS, seasonal_on=on, wander=1e-7)
    for when, value in zip(times, values, strict=True):
        member.predict(when)
        member.update(value, noise, when)

    base = member.at or 0.0
    shape = [member.profile(base + h * HOUR, period=24.0) for h in range(24)]
    return member.loglike, member.amplitude, shape, noise


def main() -> None:
    print(
        f"periods {PERIODS} harmonics {HARMONICS} frames {FRAMES}\n"
        "gain = the seasonal's likelihood less the same member with the harmonics off\n"
    )
    print(
        f"{'instrument':<22}{'frame':<6}{'n':>7}{'gain':>10}{'slid':>10}"
        f"{'amp/noise':>11}{'shape span':>12}"
    )

    shapes: dict[str, list[float]] = {}
    rows: list[tuple[str, float, float]] = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            found = load(name, frame)
            if found is None:
                continue
            times, closes = found
            logs = [math.log(c) for c in closes if c > 0]
            if len(logs) != len(times):
                continue

            gaps = [times[i] - times[i - 1] for i in range(1, min(len(times), 500))]
            bar = statistics.median(gaps) / HOUR if gaps else 1.0
            half = max(round(12.0 / bar), 1)

            full, amplitude, shape, noise = score(times, logs, on=True)
            flat, _, _, _ = score(times, logs, on=False)
            # The data slid half a day against the clock, and its own matched
            # null, because sliding also shortens the sample.
            spun, _, _, _ = score(times, logs, on=True, slide=half)
            spun_flat, _, _, _ = score(times, logs, on=False, slide=half)

            label = f"*{name}" if name in GENERATED else name
            span = max(shape) - min(shape)
            print(
                f"{label:<22}{frame:<6}{len(times):>7}{full - flat:>10.1f}"
                f"{spun - spun_flat:>10.1f}{amplitude / noise:>11.2f}"
                f"{span / noise:>12.2f}"
            )
            shapes[f"{label} {frame}"] = [v / noise for v in shape]
            rows.append((label, full - flat, spun - spun_flat))

    traded = [(a, b) for label, a, b in rows if not label.startswith("*")]
    made = [(a, b) for label, a, b in rows if label.startswith("*")]
    print()
    for arm, pool in (("traded", traded), ("generated", made)):
        if not pool:
            continue
        print(
            f"{arm:<10} median gain {statistics.median([a for a, _ in pool]):>10.1f}"
            f"   clock broken {statistics.median([b for _, b in pool]):>10.1f}"
        )

    # The portability reading: the same instrument's shape at two frames.
    print("\n== is the fitted daily shape the same at 1h and 4h?")
    print(f"{'instrument':<22}{'correlation':>12}{'span 1h':>9}{'span 4h':>9}")
    for name in TRADED + GENERATED:
        label = f"*{name}" if name in GENERATED else name
        one = shapes.get(f"{label} 1h")
        two = shapes.get(f"{label} 4h")
        if not one or not two:
            continue
        mx, my = statistics.fmean(one), statistics.fmean(two)
        num = sum((a - mx) * (b - my) for a, b in zip(one, two, strict=True))
        den = math.sqrt(sum((a - mx) ** 2 for a in one) * sum((b - my) ** 2 for b in two))
        shown = num / den if den > 0 else float("nan")
        print(f"{label:<22}{shown:>12.3f}{max(one) - min(one):>9.2f}{max(two) - min(two):>9.2f}")


# ------------------------------------------- the seasonal that should be there

#: The level arm came back negative on all 26 cells, which is the expected
#: answer on reflection: the intraday regularity everybody knows about is in
#: **volatility**, not in price. A daily pattern in how far the market moves
#: says nothing about which way, and the level member observes the way.
#:
#: So the same component is tried on the **spread** instead of the level: fit
#: a 24-hour profile to the size of the innovations and feed it back as the
#: measurement noise. This is what `driven.py` is for - a door that takes an
#: outside signal into `Q` - and the signal here is the clock.


def profile_of_size(times, values, harmonics: int = 3):
    """Fit a 24-hour harmonic profile to log innovation size.

    Least squares on `log|step|` against `[1, cos, sin, cos2, sin2, ...]`,
    which is a seasonal on the **log** scale so the profile multiplies the
    spread rather than adding to it - the right scale for a quantity that
    cannot go negative, and the one that makes the profile a ratio.

    Returned as a callable, and fitted on the **first half only**, because a
    profile fitted on everything and then scored on everything is a profile
    scored on its own training data.
    """
    steps = [(times[i], abs(values[i] - values[i - 1])) for i in range(1, len(values))]
    steps = [(t, v) for t, v in steps if v > 0]
    if len(steps) < 500:
        return None
    half = len(steps) // 2

    def basis(when: float) -> list[float]:
        hours = (when % 86400.0) / HOUR
        row = [1.0]
        for j in range(1, harmonics + 1):
            angle = TAU * j * hours / 24.0
            row.extend((math.cos(angle), math.sin(angle)))
        return row

    width = 1 + 2 * harmonics
    normal = [[0.0] * width for _ in range(width)]
    target = [0.0] * width
    for when, size in steps[:half]:
        row = basis(when)
        value = math.log(size)
        for i in range(width):
            target[i] += row[i] * value
            for j in range(width):
                normal[i][j] += row[i] * row[j]

    # Gauss-Jordan with partial pivoting. Seven unknowns, so the explicit
    # solve is cheaper than pulling in a dependency and it keeps the harness
    # runnable on a machine with nothing installed.
    for col in range(width):
        pivot = max(range(col, width), key=lambda r: abs(normal[r][col]))
        if abs(normal[pivot][col]) < 1e-12:
            return None
        normal[col], normal[pivot] = normal[pivot], normal[col]
        target[col], target[pivot] = target[pivot], target[col]
        scale = normal[col][col]
        normal[col] = [v / scale for v in normal[col]]
        target[col] /= scale
        for row_index in range(width):
            if row_index == col:
                continue
            factor = normal[row_index][col]
            if factor == 0.0:
                continue
            normal[row_index] = [
                a - factor * b for a, b in zip(normal[row_index], normal[col], strict=True)
            ]
            target[row_index] -= factor * target[col]

    middle = target[0]

    def shape(when: float) -> float:
        row = basis(when)
        fitted = sum(a * b for a, b in zip(row, target, strict=True))
        # Relative to the mean level, so the profile multiplies by one on
        # average and the comparison is not a change of overall scale.
        return math.exp(fitted - middle)

    return shape, half


def score_driven(times, values, shape, *, use_shape: bool, slide: int = 0):
    """A level filter whose measurement noise follows the clock, or does not.

    Scored on the **second half only**, which is the half the profile was not
    fitted on.
    """
    if slide:
        times = times[: len(times) - slide]
        values = values[slide:]
    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    base = statistics.pstdev(steps) or 1e-9
    start = len(times) // 2

    member = Seasonal(periods=PERIODS, harmonics=HARMONICS, seasonal_on=False)
    for when, value in zip(times, values, strict=True):
        noise = base * (shape(when) if use_shape else 1.0)
        member.predict(when)
        member.update(value, noise, when)
        if member.seen == start:
            member.loglike = 0.0
    return member.loglike


def variance_arm() -> None:
    print("\n== the same component on the spread instead of the level")
    print("   a 24h profile fitted to log innovation size on the first half,")
    print("   fed back as measurement noise, scored on the second half only")
    print(
        f"{'instrument':<22}{'frame':<6}{'gain':>10}{'slid':>10}{'profile hi/lo':>15}{'peak h':>8}"
    )
    rows: list[tuple[str, float, float]] = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            found = load(name, frame)
            if found is None:
                continue
            times, closes = found
            logs = [math.log(c) for c in closes if c > 0]
            if len(logs) != len(times):
                continue
            fitted = profile_of_size(times, logs)
            if fitted is None:
                continue
            shape, _ = fitted

            gaps = [times[i] - times[i - 1] for i in range(1, min(len(times), 500))]
            bar = statistics.median(gaps) / HOUR if gaps else 1.0
            half = max(round(12.0 / bar), 1)

            driven = score_driven(times, logs, shape, use_shape=True)
            flat = score_driven(times, logs, shape, use_shape=False)
            slid = score_driven(times, logs, shape, use_shape=True, slide=half)
            slid_flat = score_driven(times, logs, shape, use_shape=False, slide=half)

            profile = [shape(h * HOUR) for h in range(24)]
            peak = max(range(24), key=lambda h: profile[h])
            label = f"*{name}" if name in GENERATED else name
            print(
                f"{label:<22}{frame:<6}{driven - flat:>10.1f}{slid - slid_flat:>10.1f}"
                f"{max(profile) / max(min(profile), 1e-9):>15.2f}{peak:>8}"
            )
            rows.append((label, driven - flat, slid - slid_flat))

    traded = [(a, b) for label, a, b in rows if not label.startswith("*")]
    made = [(a, b) for label, a, b in rows if label.startswith("*")]
    print()
    for arm, pool in (("traded", traded), ("generated", made)):
        if not pool:
            continue
        print(
            f"{arm:<10} median gain {statistics.median([a for a, _ in pool]):>10.1f}"
            f"   clock broken {statistics.median([b for _, b in pool]):>10.1f}"
        )


if __name__ == "__main__":
    main()
    variance_arm()
