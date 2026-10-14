"""Is the one-bar band's residual misfit the tick grid?

`one-bar-band.md` leaves one thing open: after sigma is tracked, a large PIT
misfit survives at a single bar, and neither lever on record can move it -
`robust.py` changes the gain rather than the density, and a Student-t is
already refuted.

The next hypothesis is not a fatter continuous density but a **discrete** one.
A one-bar return lives on a tick grid and carries the bid-ask bounce, so its
distribution has **mass points** in it, and no continuous density fits a
distribution with mass points however its tails are shaped.

## The record already hints at it

The flatness is horizon-dependent: h=20 reads 1.6 once the overlap is removed,
h=1 does not. Discreteness predicts exactly that - a twenty-bar move spans many
more ticks than a one-bar move, so the grid washes out as the horizon grows.
Tail weight does not predict it, because a fat tail is scale-free.

So the test is whether the misfit tracks **ticks per move** rather than the
frame. If the feeds and frames whose typical bar spans few ticks are the
miscalibrated ones, the grid is the cause.

## What is measured

The tick is inferred rather than assumed: the smallest non-zero absolute change
across the series, which on a quoted grid is the grid. Then, per feed and
frame: the share of one-bar changes that are **exactly zero**, the typical move
in ticks, and the PIT flatness of a tracked-sigma Gaussian - the best arm from
`one-bar-band.md`.

A mass point at zero is the clearest form of the problem, because a continuous
density assigns it probability zero and the PIT of a tied outcome is not even
well defined.
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

from screen import load  # noqa: E402

FRAMES = tuple(os.environ.get("FRAMES", "15m,1h,4h,1d").split(","))
HALF_LIFE = float(os.environ.get("HALF_LIFE", "40"))
BINS = int(os.environ.get("BINS", "10"))
WARM = int(os.environ.get("WARM", "200"))


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def flatness(pits: np.ndarray) -> float:
    if len(pits) < 10 * BINS:
        return float("nan")
    counts = np.histogram(pits, bins=BINS, range=(0.0, 1.0))[0]
    expected = len(pits) / BINS
    # Divided by `n` as well, so it is comparable **across** samples - the
    # defect named in `one-bar-band.md`, where chi-square per degree of freedom
    # grew with n and made 2,055 incomparable to a recorded 73.3.
    return float(((counts - expected) ** 2 / expected).sum()) / len(pits)


def tick_of(prices: np.ndarray) -> float:
    """The quoted grid, inferred as the smallest non-zero change."""
    steps = np.abs(np.diff(prices))
    steps = steps[steps > 0]
    if len(steps) < 100:
        return float("nan")
    # The 0.1st percentile rather than the minimum, so one bad print cannot
    # define the grid for a whole series.
    return float(np.quantile(steps, 0.001))


def main() -> None:
    names = tuple(
        os.environ.get(
            "PAIRS",
            "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,EURGBP,XAGUSD,USDCHF",
        ).split(",")
    )
    print(
        "inferred tick = the 0.1st percentile of non-zero close changes.\n"
        "flatness is chi-square over n, so it compares across samples.\n"
    )
    rows: list[tuple[str, str, float, float, float, float]] = []
    for frame in FRAMES:
        for name in names:
            bars = load(name, frame)
            if bars is None:
                continue
            close = bars["close"]
            tick = tick_of(close)
            if not math.isfinite(tick) or tick <= 0:
                continue
            raw = np.diff(close)
            rets = np.diff(np.log(close))
            if len(rets) < WARM + 500:
                continue
            zero = float(np.mean(raw == 0.0))
            ticks_per_move = float(np.median(np.abs(raw))) / tick
            # The best arm from one-bar-band.md: a tracked sigma.
            alpha = 1.0 - 0.5 ** (1.0 / HALF_LIFE)
            var = float(np.var(rets[:WARM]))
            pits = []
            for i in range(WARM, len(rets)):
                sigma = math.sqrt(var) if var > 0 else 0.0
                if sigma > 0:
                    pits.append(normal_cdf(float(rets[i]) / sigma))
                var += alpha * (rets[i] ** 2 - var)
            got = flatness(np.asarray(pits))
            if math.isfinite(got):
                rows.append((frame, name, tick, zero, ticks_per_move, got))
    if not rows:
        print("nothing measured")
        return
    print(
        f"  {'frame':<6}{'feed':<10}{'tick':>12}{'zero share':>12}{'ticks/move':>12}{'flatness':>11}"
    )
    for frame, name, tick, zero, per_move, got in rows:
        print(f"  {frame:<6}{name:<10}{tick:>12.6f}{zero:>12.4f}{per_move:>12.1f}{got:>11.5f}")
    # The test: does the misfit track ticks per move?
    per = np.array([r[4] for r in rows])
    flat = np.array([r[5] for r in rows])
    zeros = np.array([r[3] for r in rows])
    keep = np.isfinite(per) & np.isfinite(flat) & (per > 0)
    if keep.sum() > 6:
        print(
            f"\n  correlation of flatness with ticks per move "
            f"{float(np.corrcoef(np.log(per[keep]), flat[keep])[0, 1]):+.3f}"
        )
        print(
            f"  correlation of flatness with the zero share        "
            f"{float(np.corrcoef(zeros[keep], flat[keep])[0, 1]):+.3f}"
        )
    print(
        "\n  Discreteness predicts a **negative** correlation with ticks per move\n"
        "  - fewer ticks in a move means a coarser grid relative to it - and a\n"
        "  **positive** one with the share of exact zeros. Tail weight predicts\n"
        "  neither, because a fat tail is scale-free."
    )


if __name__ == "__main__":
    main()
