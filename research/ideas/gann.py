"""Gann, stripped to the three claims that can be measured.

Asked on 2026-10-14 alongside Elliott and Wyckoff. Gann's apparatus is large and
mostly unfalsifiable as stated, but three components are density claims about
observable quantities, and a density claim is testable against the same series
block-shuffled.

**Angles.** Gann drew lines at fixed price-to-time slopes - 1x1, 2x1, 1x2, 4x1,
1x4, 8x1, 1x8, 3x1, 1x3 - and held that price respects them. The scale-free
form of that claim needs no choice of units: the **ratio of one leg's slope to
the previous leg's** should cluster at those values.

**Squaring price and time.** A turn is said to come when price travelled equals
time elapsed in the market's own units. In units of the typical bar that is
`size / bars = 1`, with the other angles at 2, 1/2 and so on - so this is the
same density test applied to the slope itself rather than to a ratio of slopes.

**Time cycles.** Turns are said to recur at particular counts - 30, 45, 60, 90,
120, 180, 270, 360 - which is a density claim about inter-turn durations, and
structurally the same question `dwell.py` asked of regime durations, where the
hazard decayed rather than humping.

The segmentation is `waves.legs`, reused rather than rewritten so the two files
cannot disagree about what a leg is - and because its first version silently
segmented **zero** legs from forty thousand bars, which is the kind of defect
worth having behind one implementation instead of two.

Every arm sweeps the zigzag threshold, because a density in a quantity derived
from a segmentation is a function of the segmentation's parameter, and a result
at one threshold only is the threshold.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import CONTROL, GENERATED, SEED, TRADED, shuffle_blocks  # noqa: E402
from screen import load  # noqa: E402
from waves import legs  # noqa: E402

THRESHOLDS = tuple(float(k) for k in os.environ.get("THRESHOLDS", "1.0,2.0,4.0").split(","))
#: Gann's angles, as slope ratios. `1.0` is the 1x1.
ANGLES = (0.125, 0.25, 0.3333, 0.5, 1.0, 2.0, 3.0, 4.0, 8.0)
#: His time counts, in bars.
COUNTS = (30, 45, 60, 90, 120, 180, 270, 360)
NEAR = float(os.environ.get("NEAR", "0.05"))
#: Half-width for the duration test, in bars - a count is "hit" within this.
WIDTH = int(os.environ.get("WIDTH", "3"))


def near_density(values: list[float], targets) -> dict[float, float]:
    """Share of `values` landing within `NEAR` of each target."""
    if len(values) < 50:
        return {}
    out = {}
    for target in targets:
        lo, hi = target * (1 - NEAR), target * (1 + NEAR)
        out[target] = sum(1 for v in values if lo <= v <= hi) / len(values)
    return out


def count_density(durations: list[float], counts) -> dict[int, float]:
    """Share of durations within `WIDTH` bars of each named count.

    Normalised by the width of the window rather than left raw, because the
    counts are not equally spaced and a wider absolute window at a larger count
    would otherwise look like a denser one.
    """
    if len(durations) < 50:
        return {}
    out = {}
    for count in counts:
        hit = sum(1 for d in durations if abs(d - count) <= WIDTH)
        out[count] = hit / len(durations)
    return out


def slopes(found: list[dict]) -> tuple[list[float], list[float], list[float]]:
    """Slope ratios between consecutive legs, raw slopes, and durations."""
    ratios: list[float] = []
    raw: list[float] = []
    durations: list[float] = []
    for leg in found:
        if leg["bars"] > 0 and leg["size"] > 0:
            raw.append(leg["size"] / leg["bars"])
            durations.append(leg["bars"])
    for i in range(len(raw) - 1):
        if raw[i] > 0:
            ratios.append(raw[i + 1] / raw[i])
    return ratios, raw, durations


def report(label: str, real: list[list[dict]], mixed: list[list[dict]]) -> None:
    def gather(pool):
        out = ([], [], [])
        for found in pool:
            a, b, c = slopes(found)
            out[0].append(a)
            out[1].append(b)
            out[2].append(c)
        return out

    r_ratio, r_raw, r_dur = gather(real)
    m_ratio, m_raw, m_dur = gather(mixed)

    print("    ANGLES - one leg's slope over the previous leg's")
    print(f"      {'ratio':>7}{'real':>9}{'shuffled':>10}{'lift':>9}   feeds agreeing")
    for target in ANGLES:
        here = [d[target] for x in r_ratio if (d := near_density(x, ANGLES))]
        there = [d[target] for x in m_ratio if (d := near_density(x, ANGLES))]
        if not here or not there:
            continue
        a, b = float(np.mean(here)), float(np.mean(there))
        agree = sum(1 for v in here if v > b) / len(here)
        print(
            f"      {target:>7.4f}{a:>9.4f}{b:>10.4f}{a - b:>+9.4f}   {agree:>5.0%} of {len(here)}"
        )

    print("    SQUARING - the slope itself, in typical bars per bar")
    print(f"      {'slope':>7}{'real':>9}{'shuffled':>10}{'lift':>9}   feeds agreeing")
    for target in ANGLES:
        here = [d[target] for x in r_raw if (d := near_density(x, ANGLES))]
        there = [d[target] for x in m_raw if (d := near_density(x, ANGLES))]
        if not here or not there:
            continue
        a, b = float(np.mean(here)), float(np.mean(there))
        agree = sum(1 for v in here if v > b) / len(here)
        print(
            f"      {target:>7.4f}{a:>9.4f}{b:>10.4f}{a - b:>+9.4f}   {agree:>5.0%} of {len(here)}"
        )

    print(f"    TIME COUNTS - leg duration within {WIDTH} bars of each count")
    print(f"      {'count':>7}{'real':>9}{'shuffled':>10}{'lift':>9}   feeds agreeing")
    for count in COUNTS:
        here = [d[count] for x in r_dur if (d := count_density(x, COUNTS))]
        there = [d[count] for x in m_dur if (d := count_density(x, COUNTS))]
        if not here or not there:
            continue
        a, b = float(np.mean(here)), float(np.mean(there))
        agree = sum(1 for v in here if v > b) / len(here)
        print(f"      {count:>7}{a:>9.4f}{b:>10.4f}{a - b:>+9.4f}   {agree:>5.0%} of {len(here)}")


def arm(group: str, names: tuple[str, ...], rng) -> None:
    print("=" * 76)
    print(group)
    print("=" * 76)
    for threshold in THRESHOLDS:
        real: list[list[dict]] = []
        mixed: list[list[dict]] = []
        for name in names:
            bars = load(name)
            if bars is None:
                continue
            got = legs(bars, threshold)
            if len(got) >= 60:
                real.append(got)
            got = legs(shuffle_blocks(bars, rng), threshold)
            if len(got) >= 60:
                mixed.append(got)
        if not real:
            print(f"  threshold {threshold:g}: nothing segmented\n")
            continue
        print(
            f"  threshold {threshold:g} typical bars: {len(real)} feeds, "
            f"{sum(len(f) for f in real):,} legs"
        )
        report(group, real, mixed)
        print()


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"Gann as three density claims. Angles and squaring within {NEAR:.0%} of\n"
        f"each value, time counts within {WIDTH} bars. Every number is read\n"
        "against the same bars block-shuffled.\n"
    )
    for group, names in (("traded", TRADED), ("control", CONTROL), ("generated", GENERATED)):
        arm(group, names, rng)
    _ = math


if __name__ == "__main__":
    main()
