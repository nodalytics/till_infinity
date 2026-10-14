"""Does the Student-t band survive out of sample, feed by feed?

`sigma_sweep.py` found that a t with dof 4 over a slow sigma is both the
flattest arm and the cheapest on CRPS - 0.0057 against the Gaussian's 0.0782
at 1h, at a CRPS of 0.987. Two flaws in that result are worth more than the
result itself:

- **dof was chosen on the data that scored it**, over five candidates. Mild,
  but it is the same in-sample choice this repo has caught several times.
- **the CRPS margin is 1.3%**, reported as a median over eight feeds, which
  says nothing about whether eight feeds improved a little or two improved a
  lot while six got worse.

So here dof is fitted on a **training half** and every number is reported on
the **held-out half**, two ways:

- **by maximum likelihood** on the standardised residuals `r / sigma`, which
  never sees CRPS or the PIT at all. This is the independent estimate: if the
  tail index that fits the residuals is also the one that wins the scores,
  the two agree for a reason.
- **by CRPS** on the training half, the greedy version, kept only to show how
  far the greedy choice drifts from the honest one.

And the verdict is a **count of feeds**, not a median: how many of the eight
improve on flatness, and how many on CRPS. A real fix improves nearly all of
them. A median that hides a split does not.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
from scipy.stats import norm, t as student  # type: ignore[import-untyped]

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screen import load  # noqa: E402
from sigma_sweep import WARM, crps_normal, crps_student, flatness, sigma_path  # noqa: E402

FRAMES = tuple(os.environ.get("FRAMES", "15m,1h,4h,1d").split(","))
DOFS = tuple(float(k) for k in os.environ.get("DOFS", "3,3.5,4,4.5,5,6,7,10,20").split(","))
BASE = float(os.environ.get("BASE", "40"))
NAMES = tuple(
    os.environ.get("PAIRS", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,EURGBP").split(",")
)


def fit_dof(z: np.ndarray) -> float:
    """Tail index by maximum likelihood on standardised residuals."""
    dof = student.fit(z, floc=0.0)[0]
    return float(min(max(dof, 2.1), 500.0))


def main() -> None:
    print(
        "dof fitted on the first half, every number scored on the held-out second\n"
        "half. CRPS as a ratio to the Gaussian on the same held-out bars, so below\n"
        f"1.000 beats it. Incumbent is a Gaussian at half-life {BASE:g}.\n"
    )
    for frame in FRAMES:
        rows = []
        for name in NAMES:
            bars = load(name, frame)
            if bars is None:
                continue
            rets = np.diff(np.log(bars["close"]))
            rets = rets[np.isfinite(rets)]
            if len(rets) < WARM + 4000:
                continue
            sd = sigma_path(rets, BASE)
            live = rets[WARM:]
            half = len(live) // 2
            z_train = live[:half] / sd[:half]
            # The two candidate tail indices, both chosen on the training half only.
            by_mle = fit_dof(z_train)
            by_crps = min(DOFS, key=lambda d: crps_student(live[:half], sd[:half], d))
            # Everything below is the held-out half and has seen neither choice.
            x, s = live[half:], sd[half:]
            base_flat = flatness(norm.cdf(x / s))
            base_cost = crps_normal(x, s)
            got = {}
            for label, dof in (("mle", by_mle), ("crps", by_crps)):
                scale = s * math.sqrt((dof - 2.0) / dof)
                got[label] = (
                    dof,
                    flatness(student.cdf(x / scale, dof)),
                    crps_student(x, s, dof) / base_cost,
                )
            rows.append((name, len(x), base_flat, got))
        if not rows:
            continue
        print(f"{frame}: {len(rows)} feeds")
        print(
            f"  {'feed':<9}{'n test':>8}{'gauss flat':>11}"
            f"{'mle dof':>9}{'flat':>9}{'CRPS':>7}"
            f"{'  |':>3}{'crps dof':>9}{'flat':>9}{'CRPS':>7}"
        )
        for name, n, base_flat, got in rows:
            a, b = got["mle"], got["crps"]
            print(
                f"  {name:<9}{n:>8,}{base_flat:>11.5f}"
                f"{a[0]:>9.2f}{a[1]:>9.5f}{a[2]:>7.3f}"
                f"{'  |':>3}{b[0]:>9.1f}{b[1]:>9.5f}{b[2]:>7.3f}"
            )
        for label in ("mle", "crps"):
            flat_win = sum(1 for _, _, bf, g in rows if g[label][1] < bf)
            cost_win = sum(1 for _, _, _, g in rows if g[label][2] < 1.0)
            dofs = [g[label][0] for _, _, _, g in rows]
            print(
                f"  {label:<5} dof median {np.median(dofs):.2f}"
                f" (range {min(dofs):.2f} to {max(dofs):.2f}),"
                f" flatter on {flat_win}/{len(rows)},"
                f" cheaper on {cost_win}/{len(rows)}"
            )
        print()
    print(
        "  A fix improves nearly every feed on both scores and its two dof choices\n"
        "  land in the same place. A split count, or an MLE tail index far from the\n"
        "  CRPS-greedy one, means the win is a few feeds and a lucky parameter."
    )


if __name__ == "__main__":
    main()
