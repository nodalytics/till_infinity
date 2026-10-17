"""Where a market's displacement points, and whether it visits every direction.

A random walk in three or more dimensions is **transient** - it escapes to
infinity and never returns to the origin - and yet the *angle* of its
displacement from the start keeps turning and visits every direction infinitely
often. Transience is a statement about the radius; recurrence still holds for
the direction.

That is a question a one-dimensional price series cannot be asked. It has no
angle. The question has teeth only in an embedding, and this desk has two
natural ones:

* **across instruments** - the vector of `N` instruments' log-price changes
  from a common start is a direction in `R^N`, and this is the case the theorem
  is actually about;
* **across horizons** - the pair `(change over h1, change over h2)` is a
  direction in the plane, one per bar, for a single instrument.

## What makes it a test rather than a restatement

A walk's displacement direction is **asymptotically uniform on the sphere**,
because its increments are isotropic. A market's increments are not isotropic
and this desk has already measured why: three principal components carry
**63.2%** of return variance across 20 instruments, and the residuals after
them still correlate up to `0.9422` along **currency** lines. So a market's
displacement should be **confined to a low-dimensional cone** - it should visit
far fewer directions than a walk of the same dimension, and revisit them more.

That is a sharp, falsifiable difference, and it is not the Mandelbrot critique.
The fat-tailed-marginal half of that argument is already settled here: traded
return kurtosis reads **20.07** against the Deriv synthetics' **3.19**, where
Gaussian is 3.0. This is about **direction**, which that measurement says
nothing about - a fat-tailed walk is still isotropic.

## What is measured

Each displacement is normalised to the unit sphere and binned, so "a direction"
is a cell rather than a point:

* **spread** - the share of cells ever visited, and the entropy of the visit
  distribution over cells, as an effective count. A walk should spread; a
  factor-driven market should not.
* **discovery** - how the count of distinct cells grows with time. The theorem
  says it grows without bound; the question is the *rate*, and a confined
  process saturates.
* **revisits** - the median gap between consecutive visits to the same cell.
  Recurrence makes this finite; confinement makes it short.
* **effective dimension** - the participation ratio of the displacement
  covariance's eigenvalues, which says how many directions the walk actually
  has rather than how many it is embedded in.

## The nulls

* **a walk** - `nulls.Walk` is the package's forecast floor and the right null
  here too: isotropic increments with the same per-instrument scale, which is
  the thing a market is being compared against;
* **rotation** - each instrument rotated in time by `nulls.rotated`, which
  keeps every marginal exactly and destroys only the cross-instrument
  alignment. This is the sharper null: it has the market's own fat tails and
  volatility clustering and none of its factor structure, so a difference
  between the real and rotated arms **is** the factor structure and not the
  tails;
* **the generated instruments** - independent by construction, so their
  displacement should already be near-isotropic and they are the positive
  control for "a universe with no factors looks like a walk".

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relationship_screen as screen  # noqa: E402

#: Instruments embedded. The direction lives in this many dimensions.
WIDTH = int(os.environ.get("WIDTH", "8"))
#: Bars between displacement readings, so successive directions are not the
#: same point seen twice.
STRIDE = int(os.environ.get("STRIDE", "24"))
#: Bars in one displacement, measured from a rolling start.
REACH = int(os.environ.get("REACH", "240"))
#: Cells per axis when a direction is binned. The sphere is binned by the sign
#: and magnitude pattern rather than by angle, which does not need a parametric
#: spherical grid in high dimensions.
CELLS = int(os.environ.get("CELLS", "3"))
#: Null repetitions.
REPS = int(os.environ.get("REPS", "6"))
SEED = 20261013


def directions(matrix, reach: int = REACH, stride: int = STRIDE):
    """Unit-normalised displacements over `reach` bars, every `stride` bars."""
    import numpy as np

    out = []
    width, length = matrix.shape
    for at in range(reach, length, stride):
        step = matrix[:, at] - matrix[:, at - reach]
        size = float(np.linalg.norm(step))
        if size <= 0:
            continue
        out.append(step / size)
    return np.asarray(out) if out else None


def cell_of(point, cells: int = CELLS) -> tuple[int, ...]:
    """A direction's bin.

    **Binned by sign and coarse magnitude per axis, not by spherical angle.** A
    spherical grid in eight dimensions needs a tessellation nobody here has a
    reason to trust; a per-axis sign plus a `cells`-way magnitude split is a
    partition of the sphere into cells of comparable measure, which is all the
    visit statistics need. The cell count is `(2 * cells) ** width`, so the
    comparison between arms is on an identical partition.
    """
    out = []
    for value in point:
        share = min(int(abs(value) * cells * 2.0), cells - 1)
        out.append(int(share) if value >= 0 else -(int(share) + 1))
    return tuple(out)


def spread_of(points, cells: int = CELLS) -> dict[str, float]:
    """Visit statistics over the direction cells, plus the effective dimension."""
    import numpy as np

    if points is None or len(points) < 40:
        return {}
    seen: dict[tuple[int, ...], list[int]] = {}
    for i, point in enumerate(points):
        seen.setdefault(cell_of(point, cells), []).append(i)
    counts = np.asarray([len(v) for v in seen.values()], dtype=float)
    share = counts / counts.sum()
    # Entropy as an effective number of cells: how many directions the process
    # behaves as if it has, rather than how many it touched once.
    entropy = float(-np.sum(share * np.log(share)))
    gaps = [
        visits[k + 1] - visits[k]
        for visits in seen.values()
        for k in range(len(visits) - 1)
    ]
    # Participation ratio of the covariance spectrum: `(sum l)^2 / sum l^2`,
    # which is `d` for isotropic and 1 for a single direction.
    values = np.linalg.eigvalsh(np.cov(points.T))
    values = values[values > 0]
    effective = (
        float(values.sum() ** 2 / np.sum(values**2)) if len(values) else float("nan")
    )
    # Discovery rate: distinct cells in the first half against the whole.
    half = len(points) // 2
    early = len({cell_of(p, cells) for p in points[:half]})
    return {
        "cells": float(len(seen)),
        "effective_cells": float(math.exp(entropy)),
        "revisit": float(statistics.median(gaps)) if gaps else float("nan"),
        "revisited": float(sum(1 for v in seen.values() if len(v) > 1) / len(seen)),
        "effective_dim": effective,
        "discovery": float(len(seen) - early) / max(early, 1),
        "n": float(len(points)),
    }


def walk_like(matrix, rng):
    """An isotropic walk with each instrument's own scale: the package's floor."""
    import numpy as np

    width, length = matrix.shape
    out = np.zeros_like(matrix)
    for i in range(width):
        steps = np.diff(matrix[i])
        scale = float(steps.std()) or 1e-9
        drawn = rng.standard_normal(length - 1) * scale
        out[i, 1:] = np.cumsum(drawn)
        out[i] += matrix[i, 0]
    return out


def rotated_like(matrix, picker):
    """Each instrument rotated in time: marginals exact, alignment destroyed."""
    import numpy as np

    from till_infinity.statespace.nulls import rotated

    out = np.empty_like(matrix)
    for i in range(matrix.shape[0]):
        shift = picker.randrange(50, max(matrix.shape[1] - 50, 60))
        out[i] = np.asarray(rotated(list(matrix[i]), shift))[: matrix.shape[1]]
    return out


def report(label: str, got: dict[str, float]) -> None:
    if not got:
        print(f"{label:<30}  too short")
        return
    print(
        f"{label:<30}{got['cells']:>8.0f}{got['effective_cells']:>12.1f}"
        f"{got['effective_dim']:>9.2f}{got['revisited']:>11.3f}"
        f"{got['revisit']:>10.1f}{got['discovery']:>11.3f}{got['n']:>7.0f}"
    )


def planted() -> None:
    """An isotropic walk, and one confined to a plane, through the same bins."""
    import numpy as np

    print("=" * 112)
    print("ARM 0  planted: an isotropic walk against one confined to a few directions")
    print("=" * 112)
    print(
        f"{'planted':<30}{'cells':>8}{'eff cells':>12}{'eff dim':>9}"
        f"{'revisited':>11}{'gap':>10}{'discovery':>11}{'n':>7}"
    )
    rng = np.random.default_rng(5)
    length = 20_000
    isotropic = np.cumsum(rng.standard_normal((WIDTH, length)), axis=1)
    report("isotropic walk", spread_of(directions(isotropic)))

    # One factor driving every instrument, plus a small idiosyncratic part: the
    # shape a factor-driven market should have.
    factor = np.cumsum(rng.standard_normal(length))
    loadings = rng.uniform(0.6, 1.0, size=WIDTH)
    confined = np.outer(loadings, factor) + np.cumsum(
        rng.standard_normal((WIDTH, length)) * 0.25, axis=1
    )
    report("one factor plus noise", spread_of(directions(confined)))

    three = np.cumsum(rng.standard_normal((3, length)), axis=1)
    mixing = rng.standard_normal((WIDTH, 3))
    report("three factors", spread_of(directions(mixing @ three)))
    print(
        "\nA walk should touch many cells with a high effective dimension; a\n"
        "factor-driven process should touch few and sit near its factor count.\n"
        "If those two rows do not separate, the bins cannot see confinement and\n"
        "the real rows below say nothing."
    )


def main() -> None:
    print(
        f"{WIDTH} instruments embedded, displacements over {REACH} bars every\n"
        f"{STRIDE}, direction binned {CELLS} ways per axis per sign\n"
    )
    planted()

    import numpy as np

    traded = [n for n in screen.TRADED if screen.load(n) is not None][:WIDTH]
    generated = [
        n for n in screen.universe(screen.FRAME, cap=40) if screen.load(n) is not None
    ][:WIDTH]

    def embed(names):
        stamps = None
        for name in names:
            times = screen.load(name)[0]
            stamps = times if stamps is None else np.intersect1d(stamps, times)
        if stamps is None or len(stamps) < REACH * 4:
            return None
        rows = []
        for name in names:
            times, values, _ = screen.load(name)
            _, index, _ = np.intersect1d(times, stamps, return_indices=True)
            rows.append(values[index])
        return np.vstack(rows)

    print("\n" + "=" * 112)
    print("ARM 1  where a real universe's displacement points")
    print("=" * 112)
    print(
        f"{'':<30}{'cells':>8}{'eff cells':>12}{'eff dim':>9}"
        f"{'revisited':>11}{'gap':>10}{'discovery':>11}{'n':>7}"
    )
    rng = np.random.default_rng(SEED)
    picker = random.Random(SEED)
    for label, names in (("traded", traded), ("generated", generated)):
        matrix = embed(names)
        if matrix is None:
            print(f"{label:<30}  not enough common bars")
            continue
        report(label, spread_of(directions(matrix)))
        walk_rows = [spread_of(directions(walk_like(matrix, rng))) for _ in range(REPS)]
        walk_rows = [r for r in walk_rows if r]
        if walk_rows:
            report(
                f"  walk null, {label}",
                {k: statistics.median(r[k] for r in walk_rows) for k in walk_rows[0]},
            )
        spun = [
            spread_of(directions(rotated_like(matrix, picker))) for _ in range(REPS)
        ]
        spun = [r for r in spun if r]
        if spun:
            report(
                f"  rotation null, {label}",
                {k: statistics.median(r[k] for r in spun) for k in spun[0]},
            )
    print(
        "\n**The rotation null is the one that matters.** It carries the market's\n"
        "own fat tails and volatility clustering and none of its factor\n"
        "structure, so a gap between the traded row and its rotation is the\n"
        "factor structure - and a gap to the walk null could still be the tails.\n"
        "The generated rows are the positive control: independent by\n"
        "construction, so they should already look like a walk."
    )


if __name__ == "__main__":
    main()
