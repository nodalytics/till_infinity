"""Is the residual one-bar misfit shape, or a tracker that is simply too slow?

`tick_grid.py` refuted discreteness: only 0.06 to 2.4% of one-bar changes land
on exactly zero and a typical move spans 27 to 413 ticks, so the grid is far
too fine to matter, and the correlation of flatness with the zero share is
-0.022 where discreteness predicts a positive one.

`one-bar-band.md` showed that tracking sigma at all cuts the misfit by 55 to
64% and that a range estimator does not improve on close-to-close. What it
never asked is whether the **half-life** was the binding constraint. It was:
at 1h the misfit falls monotonically from 0.078 at half-life 40 to 0.021 at
half-life 2 with no bottom reached, and adding a second slower timescale
always lands between its two members rather than beating them.

That raises the objection this harness exists to settle. **A very fast tracker
buys calibration with estimation noise.** A noisy variance estimate is itself a
mixture, and a mixture of Gaussians has fatter tails than a Gaussian, so the
PIT can flatten for a reason that has nothing to do with knowing more about
tomorrow's scale. If that is what is happening, the gain is paid for in
sharpness and it is not a fix.

So every arm is scored twice:

- **flatness**, chi-square over `n` so it compares across samples - the defect
  named in `one-bar-band.md`. A calibrated PIT sits at `(BINS-1)/n`, printed
  per frame, and anything far above it is miscalibrated however small it looks.
- **CRPS**, as a ratio to the half-life-40 Gaussian each feed, because CRPS
  carries the units of the series and cannot be pooled raw. CRPS is proper, so
  it falls only for a genuinely better forecast and rises when calibration was
  bought with noise.

And a **Student-t** arm sits beside the Gaussian at a slow half-life. If the
only thing a fast tracker does is fatten the tail, a t over a slow sigma
reaches the same place while keeping its sharpness, and the fix is the family.
If the fast tracker wins on CRPS as well, the fix is the tracker and the
family was never the problem.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
from scipy.special import beta as beta_fn  # type: ignore[import-untyped]
from scipy.stats import norm, t as student  # type: ignore[import-untyped]

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screen import load  # noqa: E402

FRAMES = tuple(os.environ.get("FRAMES", "15m,1h,4h,1d").split(","))
HALVES = tuple(float(k) for k in os.environ.get("HALVES", "1,1.5,2,3,5,10,20,40").split(","))
DOFS = tuple(float(k) for k in os.environ.get("DOFS", "3,4,5,7,10").split(","))
BASE = float(os.environ.get("BASE", "40"))
BINS = int(os.environ.get("BINS", "10"))
WARM = int(os.environ.get("WARM", "300"))


def sigma_path(rets: np.ndarray, half: float) -> np.ndarray:
    """One-step-ahead sd, using only bars strictly before each reading."""
    alpha = 1.0 - 0.5 ** (1.0 / half)
    var = float(np.var(rets[:WARM]))
    out = np.empty(len(rets) - WARM)
    for i in range(WARM, len(rets)):
        out[i - WARM] = var
        var += alpha * (rets[i] ** 2 - var)
    return np.sqrt(np.maximum(out, 1e-300))


def flatness(pits: np.ndarray) -> float:
    counts = np.histogram(pits, bins=BINS, range=(0.0, 1.0))[0]
    expected = len(pits) / BINS
    return float(((counts - expected) ** 2 / expected).sum()) / len(pits)


def crps_normal(x: np.ndarray, sd: np.ndarray) -> float:
    z = x / sd
    return float(
        np.mean(sd * (z * (2.0 * norm.cdf(z) - 1.0) + 2.0 * norm.pdf(z) - 1.0 / math.sqrt(math.pi)))
    )


def crps_student(x: np.ndarray, sd: np.ndarray, dof: float) -> float:
    """CRPS of a t scaled to predictive sd `sd` (Jordan, Kruger, Lerch)."""
    scale = sd * math.sqrt((dof - 2.0) / dof)
    z = x / scale
    tail = (
        (2.0 * math.sqrt(dof) / (dof - 1.0))
        * beta_fn(0.5, dof - 0.5)
        / beta_fn(0.5, 0.5 * dof) ** 2
    )
    body = z * (2.0 * student.cdf(z, dof) - 1.0) + 2.0 * student.pdf(z, dof) * (dof + z**2) / (
        dof - 1.0
    )
    return float(np.mean(scale * (body - tail)))


def main() -> None:
    names = tuple(
        os.environ.get("PAIRS", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,EURGBP").split(
            ","
        )
    )
    print(
        f"one bar ahead, {BINS}-bin PIT. flatness = chi-square / n, so it compares\n"
        f"across samples; CRPS as a ratio to the half-life-{BASE:g} Gaussian per feed,\n"
        "since CRPS carries the units of the series. Lower is better in both.\n"
    )
    for frame in FRAMES:
        series = []
        for name in names:
            bars = load(name, frame)
            if bars is None:
                continue
            rets = np.diff(np.log(bars["close"]))
            rets = rets[np.isfinite(rets)]
            if len(rets) > WARM + 20 * BINS:
                series.append(rets)
        if not series:
            continue
        n = int(np.median([len(r) - WARM for r in series]))
        calibrated = (BINS - 1) / n
        # Every arm for one feed is scored off the same cached sigma paths.
        paths = [{half: sigma_path(r, half) for half in set(HALVES) | {BASE}} for r in series]
        anchors = [crps_normal(r[WARM:], p[BASE]) for r, p in zip(series, paths)]

        rows: list[tuple[str, float, float]] = []
        for half in HALVES:
            flat = [flatness(norm.cdf(r[WARM:] / p[half])) for r, p in zip(series, paths)]
            cost = [crps_normal(r[WARM:], p[half]) / a for r, p, a in zip(series, paths, anchors)]
            rows.append(
                (f"gaussian half-life {half:g}", float(np.median(flat)), float(np.median(cost)))
            )
        for dof in DOFS:
            flat = [
                flatness(student.cdf(r[WARM:] / (p[BASE] * math.sqrt((dof - 2.0) / dof)), dof))
                for r, p in zip(series, paths)
            ]
            cost = [
                crps_student(r[WARM:], p[BASE], dof) / a for r, p, a in zip(series, paths, anchors)
            ]
            rows.append(
                (f"t dof {dof:g} over hl {BASE:g}", float(np.median(flat)), float(np.median(cost)))
            )

        print(f"{frame}: {len(series)} feeds, about {n:,} readings each")
        print(f"  calibrated flatness would be {calibrated:.5f}")
        print(f"  {'arm':<26}{'flatness':>10}{'x calib':>9}{'CRPS':>8}")
        for label, flat, cost in rows:
            print(f"  {label:<26}{flat:>10.5f}{flat / calibrated:>9.0f}{cost:>8.3f}")
        kind = min(rows, key=lambda r: r[1])
        cheap = min(rows, key=lambda r: r[2])
        print(f"  flattest: {kind[0]}  |  best CRPS: {cheap[0]} at {cheap[2]:.3f}\n")
    print(
        "  If the flattest arm is also the cheapest, the fix is the tracker and the\n"
        "  family was never the problem. If a fast tracker flattens while costing\n"
        "  CRPS, its calibration was bought with estimation noise. If a t over a\n"
        "  slow sigma matches it and keeps its CRPS, the fix is the family."
    )


if __name__ == "__main__":
    main()
