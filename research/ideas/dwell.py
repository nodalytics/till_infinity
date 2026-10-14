"""Are regime durations memoryless, or patterned? - Benner's logic, made testable.

Asked on 2026-10-14: *on benner i think we can derive the formula and logic
behind it and use it.* That is the right objection to the previous answer, which
treated Benner as a single pinned frequency and concluded - correctly but
uselessly - that fifty-five years of data gives six repetitions of a nine-year
cycle and so no test.

## The derivation

Benner's 1875 structure is not a sinusoid. It is a **repeating sequence of
intervals**:

    pig iron lows   : 11, 9, 7, 11, 9, 7, ...   (summing to 27)
    pig iron peaks  : 8, 9, 10, 8, 9, 10, ...   (summing to 27)
    corn peaks      : 5, 6, 5, 6, ...           (summing to 11)

A deterministic renewal process whose inter-arrival times cycle through a fixed
list. The general object that contains it is already in this package's
vocabulary: a standard hidden Markov model has **geometric** dwell times -
memoryless, a constant hazard of leaving a state each step - while Benner's
durations are **patterned**, the extreme opposite. The model spanning both is a
hidden **semi**-Markov model, with an explicit duration distribution per state,
and Benner is the degenerate case where that distribution is a point mass
cycling through 11, 9 and 7.

## Why that is testable and the original claim was not

A nine-year cycle needs decades. **Duration dependence needs transitions**, and
intraday data has thousands of them. So the question becomes:

- Is the hazard of leaving a regime **flat** in how long the regime has lasted?
  Flat means memoryless, which means every fixed-interval cycle theory has no
  mechanism to stand on.
- Is the coefficient of variation of dwell times near **one**? A geometric
  distribution has CV about one. Patterned durations give CV well below one -
  that is the signature Benner's logic predicts. Clustered durations give CV
  above one.

Both are read against the same series **block-shuffled**, which preserves bar
geometry and the marginal distribution and destroys the ordering a regime would
live in - so a shuffled series should land on the geometric answer.

Regimes here are deliberately crude - volatility above or below its own rolling
median - because the claim is about **durations**, not about a clever state
definition. A sophisticated regime detector would put its own structure into
the dwell times, which is the mistake `null-pivot-ideas-against-a-walk-first`
records.
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

#: Bars the volatility estimate and its median are taken over.
WINDOW = int(os.environ.get("WINDOW", "20"))
MEDIAN = int(os.environ.get("MEDIAN", "500"))
#: Durations the hazard is reported at.
STEPS = (1, 2, 3, 5, 8, 13, 21, 34)


def runs(bars) -> list[int]:
    """Lengths of consecutive stretches on one side of rolling median volatility."""
    closes = bars["close"]
    if len(closes) < MEDIAN + 4 * WINDOW:
        return []
    rets = np.diff(np.log(closes))
    if not np.isfinite(rets).all():
        return []
    # Rolling standard deviation, then its own rolling median as the split.
    cumulative = np.cumsum(rets**2)
    vol = np.sqrt((cumulative[WINDOW:] - cumulative[:-WINDOW]) / WINDOW)
    if len(vol) < MEDIAN + 10:
        return []
    high = np.empty(len(vol) - MEDIAN, dtype=bool)
    for i in range(len(high)):
        high[i] = vol[MEDIAN + i] > np.median(vol[i : MEDIAN + i])
    out: list[int] = []
    length = 1
    for i in range(1, len(high)):
        if high[i] == high[i - 1]:
            length += 1
        else:
            out.append(length)
            length = 1
    return out


def hazard(lengths: list[int], at: int) -> float:
    """`P(the run ends at exactly `at` | it reached `at`)`."""
    reached = sum(1 for n in lengths if n >= at)
    ended = sum(1 for n in lengths if n == at)
    return ended / reached if reached >= 20 else float("nan")


def describe(pool: list[list[int]], label: str) -> None:
    if not pool:
        print(f"    {label:<10} nothing")
        return
    flat = [n for lengths in pool for n in lengths]
    mean = float(np.mean(flat))
    cv = float(np.std(flat)) / mean if mean > 0 else float("nan")
    # Per feed, because a pooled dwell distribution mixes instruments with
    # different activity and this desk has been caught by pooling before.
    cvs = []
    for lengths in pool:
        if len(lengths) < 50:
            continue
        m = float(np.mean(lengths))
        if m > 0:
            cvs.append(float(np.std(lengths)) / m)
    cells = []
    for at in STEPS:
        got = hazard(flat, at)
        cells.append("-" if not math.isfinite(got) else f"{got:.3f}")
    print(
        f"    {label:<10}{len(flat):>8,}{mean:>8.1f}{cv:>7.3f}"
        f"{float(np.median(cvs)) if cvs else float('nan'):>8.3f}  "
        + " ".join(f"{c:>5}" for c in cells)
    )


def arm(group: str, names: tuple[str, ...], rng) -> None:
    real: list[list[int]] = []
    mixed: list[list[int]] = []
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        got = runs(bars)
        if len(got) >= 50:
            real.append(got)
        got = runs(shuffle_blocks(bars, rng))
        if len(got) >= 50:
            mixed.append(got)
    print(f"  {group}: {len(real)} feeds")
    print(
        f"    {'arm':<10}{'runs':>8}{'mean':>8}{'CV':>7}{'CV/feed':>8}  "
        + " ".join(f"{f'h({d})':>5}" for d in STEPS)
    )
    describe(real, "real")
    describe(mixed, "shuffled")
    print()


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"regimes = {WINDOW}-bar volatility against its own {MEDIAN}-bar median\n"
        "CV near 1 is memoryless (geometric). Patterned durations - Benner's\n"
        "logic - give CV well below 1. A flat hazard across h(1)..h(34) is\n"
        "memoryless; a rising one is duration dependence.\n"
    )
    for group, names in (("traded", TRADED), ("control", CONTROL), ("generated", GENERATED)):
        print("=" * 88)
        print(group)
        print("=" * 88)
        arm(group, names, rng)


if __name__ == "__main__":
    main()
