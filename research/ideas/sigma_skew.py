"""Is the band's last 3 to 50x of misfit skew, or a dof held fixed while it drifts?

`sigma_holdout.py` settled that the one-bar band's defect is the **family**: a
Student-t over a slow sigma is flatter and cheaper on CRPS than a Gaussian on
64 of 64 out-of-sample feed-frames, cutting the misfit from 60-180x the
calibrated level to 3-50x. It did not close the gap, and named two suspects.

- **Skew.** The t is symmetric and returns are not.
- **A drifting tail index.** dof was fitted once on a training half and then
  held fixed over the whole holdout.

These are separable, and the first diagnostic is free: look at **where** the
surviving misfit sits. A bin-wise decomposition of the t's PIT says whether
the two tails are wrong by the same amount - which is dof, not skew - or by
different amounts, which is skew. That runs before any fitting and tells us
which arm to believe.

Then three arms over the same slow sigma, all fitted on a training half only:

- **symmetric t**, the incumbent fix, at the CRPS-greedy dof.
- **Hansen's skewed t**, fitted by maximum likelihood in `(eta, lambda)`. It is
  the standard two-parameter skewed t in finance, standardised to zero mean and
  unit variance so it drops straight into the same `sigma` scaling.
- **a refitted symmetric t**, with dof re-estimated by maximum likelihood on a
  trailing window and applied one step ahead. This is the drift arm, and it is
  the control for the skew arm: a skewed t has one more parameter than a
  symmetric one, so it should win a little even if skew is absent.

## Scoring a density with no closed-form CRPS

Hansen's skewed t has no closed-form CRPS. It does not need one. Every arm here
is a **standardised shape scaled by `sigma`**, and CRPS is positively
homogeneous, so `CRPS(sigma * F, y) = sigma * CRPS(F, y / sigma)`. The
standardised CRPS is therefore one fixed function of `z` per parameter pair,
and it is computed once on a fine grid from

    CRPS(F, z) = integral of F^2 below z, plus integral of (1 - F)^2 above z

by cumulative trapezoid, then interpolated at the observed `z`. Beyond the grid
it is extrapolated with slope one, which is the correct asymptote, and the
share of readings that land out there is reported.

**The grid is validated against the closed form.** The same machinery is run on
the symmetric t, where `crps_student` gives the exact answer, and the two are
asserted to agree. A quadrature that reproduces a known closed form is a
quadrature that can be trusted on the density that has none.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import minimize  # type: ignore[import-untyped]
from scipy.special import gammaln  # type: ignore[import-untyped]
from scipy.stats import t as student  # type: ignore[import-untyped]

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screen import load  # noqa: E402
from sigma_sweep import BINS, WARM, crps_student, flatness, sigma_path  # noqa: E402

FRAMES = tuple(os.environ.get("FRAMES", "15m,1h,4h,1d").split(","))
DOFS = tuple(float(k) for k in os.environ.get("DOFS", "3,3.5,4,4.5,5,6,7,10,20").split(","))
BASE = float(os.environ.get("BASE", "40"))
WINDOW = int(os.environ.get("WINDOW", "2000"))
REFIT = int(os.environ.get("REFIT", "250"))
GRID = int(os.environ.get("GRID", "24001"))
REACH = float(os.environ.get("REACH", "40"))
NAMES = tuple(
    os.environ.get("PAIRS", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,EURGBP").split(",")
)


def hansen_parts(eta: float, lam: float) -> tuple[float, float, float]:
    """`c`, `a`, `b` for Hansen's skewed t, standardised to mean 0 variance 1."""
    c = math.exp(gammaln(0.5 * (eta + 1.0)) - gammaln(0.5 * eta)) / math.sqrt(math.pi * (eta - 2.0))
    a = 4.0 * lam * c * (eta - 2.0) / (eta - 1.0)
    b = math.sqrt(1.0 + 3.0 * lam**2 - a**2)
    return c, a, b


def hansen_logpdf(z: np.ndarray, eta: float, lam: float) -> np.ndarray:
    c, a, b = hansen_parts(eta, lam)
    side = np.where(z < -a / b, 1.0 - lam, 1.0 + lam)
    inner = 1.0 + ((b * z + a) / side) ** 2 / (eta - 2.0)
    return math.log(b * c) - 0.5 * (eta + 1.0) * np.log(inner)


def hansen_cdf(z: np.ndarray, eta: float, lam: float) -> np.ndarray:
    """Closed form via the standard t CDF, continuous at the join `-a/b`."""
    _, a, b = hansen_parts(eta, lam)
    pull = math.sqrt(eta / (eta - 2.0))
    low = (1.0 - lam) * student.cdf(pull * (b * z + a) / (1.0 - lam), eta)
    high = 0.5 * (1.0 - lam) + (1.0 + lam) * (
        student.cdf(pull * (b * z + a) / (1.0 + lam), eta) - 0.5
    )
    return np.where(z < -a / b, low, high)


def fit_hansen(z: np.ndarray) -> tuple[float, float]:
    """Maximum likelihood in `(eta, lambda)`, unconstrained in log/atanh space."""

    def cost(raw: np.ndarray) -> float:
        eta = 2.05 + math.exp(min(raw[0], 8.0))
        lam = math.tanh(raw[1])
        got = -float(np.mean(hansen_logpdf(z, eta, lam)))
        return got if math.isfinite(got) else 1e12

    best = minimize(cost, np.array([1.0, 0.0]), method="Nelder-Mead")
    return 2.05 + math.exp(min(best.x[0], 8.0)), math.tanh(best.x[1])


def crps_table(cdf, grid: np.ndarray) -> np.ndarray:
    """Standardised CRPS on `grid`, from the two-sided integral of the CDF."""
    probs = cdf(grid)
    step = np.diff(grid)
    below = np.concatenate(([0.0], np.cumsum(0.5 * step * (probs[:-1] ** 2 + probs[1:] ** 2))))
    above_bits = 0.5 * step * ((1.0 - probs[:-1]) ** 2 + (1.0 - probs[1:]) ** 2)
    above = np.concatenate((np.cumsum(above_bits[::-1])[::-1], [0.0]))
    return below + above


def crps_from_table(z: np.ndarray, grid: np.ndarray, table: np.ndarray) -> np.ndarray:
    """Interpolate, extrapolating with slope one - the correct asymptote."""
    got = np.interp(z, grid, table)
    low, high = z < grid[0], z > grid[-1]
    got[low] = table[0] + (grid[0] - z[low])
    got[high] = table[-1] + (z[high] - grid[-1])
    return got


def main() -> None:
    grid = np.linspace(-REACH, REACH, GRID)
    # The quadrature is only trustworthy if it reproduces a known closed form.
    for dof in (3.0, 5.0, 10.0):
        scale = math.sqrt((dof - 2.0) / dof)
        table = crps_table(lambda x, d=dof, s=scale: student.cdf(x / s, d), grid)
        probe = np.array([-4.0, -1.0, 0.0, 0.5, 3.0])
        mine = crps_from_table(probe.copy(), grid, table)
        exact = np.array([crps_student(np.array([p]), np.array([1.0]), dof) for p in probe])
        off = float(np.max(np.abs(mine - exact)))
        assert off < 2e-3, f"quadrature off by {off} at dof {dof}"
        print(f"  quadrature check, symmetric t dof {dof:g}: max error {off:.2e}")
    print(
        f"\ndof and skew fitted on the first half, scored on the held-out second.\n"
        f"CRPS as a ratio to the symmetric t on the same bars, so below 1.000 beats\n"
        f"the fix already on record. Sigma is a Gaussian-era EWMA at half-life {BASE:g}.\n"
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
            cut = len(live) // 2
            train, s_train = live[:cut], sd[:cut]
            x, s = live[cut:], sd[cut:]
            z = x / s
            dof = min(DOFS, key=lambda d: crps_student(train, s_train, d))
            eta, lam = fit_hansen(train / s_train)

            # Incumbent: one symmetric t, fitted once.
            flat_t = flatness(student.cdf(z / math.sqrt((dof - 2.0) / dof), dof))
            cost_t = crps_student(x, s, dof)

            # Where does the surviving misfit sit? Signed, per bin.
            pit_t = student.cdf(z / math.sqrt((dof - 2.0) / dof), dof)
            counts = np.histogram(pit_t, bins=BINS, range=(0.0, 1.0))[0]
            lean = (counts - len(z) / BINS) / (len(z) / BINS)

            # Arm one: skew.
            table = crps_table(lambda g: hansen_cdf(g, eta, lam), grid)
            flat_skew = flatness(hansen_cdf(z, eta, lam))
            cost_skew = float(np.mean(s * crps_from_table(z.copy(), grid, table)))

            # Arm two: a refitted dof, the control for the extra parameter.
            moving = np.empty(len(z))
            held = dof
            for i in range(0, len(z), REFIT):
                start = cut + i - WINDOW
                if start >= 0:
                    past = live[start : cut + i] / sd[start : cut + i]
                    held = float(min(max(student.fit(past, floc=0.0)[0], 2.2), 60.0))
                moving[i : i + REFIT] = held
            pit_move = student.cdf(z / np.sqrt((moving - 2.0) / moving), moving)
            flat_move = flatness(pit_move)
            cost_move = float(
                np.mean(
                    [
                        crps_student(x[i : i + 1], s[i : i + 1], moving[i])
                        for i in range(0, len(z), max(1, len(z) // 4000))
                    ]
                )
            )
            step = max(1, len(z) // 4000)
            cost_t_thin = crps_student(x[::step], s[::step], dof)
            rows.append(
                (
                    name,
                    lean,
                    (dof, flat_t),
                    (eta, lam, flat_skew, cost_skew / cost_t),
                    (float(np.median(moving)), flat_move, cost_move / cost_t_thin),
                )
            )
        if not rows:
            continue
        print(f"{frame}: {len(rows)} feeds")
        print(
            f"  {'feed':<9}{'dof':>5}{'t flat':>9}"
            f"{'  |':>3}{'eta':>6}{'lam':>7}{'flat':>9}{'CRPS':>7}"
            f"{'  |':>3}{'dof~':>6}{'flat':>9}{'CRPS':>7}"
        )
        for name, _, base, skew, move in rows:
            print(
                f"  {name:<9}{base[0]:>5.1f}{base[1]:>9.5f}"
                f"{'  |':>3}{skew[0]:>6.2f}{skew[1]:>7.3f}{skew[2]:>9.5f}{skew[3]:>7.3f}"
                f"{'  |':>3}{move[0]:>6.2f}{move[1]:>9.5f}{move[2]:>7.3f}"
            )
        lams = [r[3][1] for r in rows]
        print(
            f"  lambda median {np.median(lams):+.3f}"
            f" (range {min(lams):+.3f} to {max(lams):+.3f}),"
            f" negative on {sum(1 for v in lams if v < 0)}/{len(rows)}"
        )
        for label, idx, flat_at, cost_at in (("skew", 3, 2, 3), ("refit dof", 4, 1, 2)):
            flat_win = sum(1 for r in rows if r[idx][flat_at] < r[2][1])
            cost_win = sum(1 for r in rows if r[idx][cost_at] < 1.0)
            print(
                f"  {label:<10} flatter than the fixed t on {flat_win}/{len(rows)},"
                f" cheaper on {cost_win}/{len(rows)}"
            )
        mean_lean = np.mean([r[1] for r in rows], axis=0)
        print("  mean signed PIT lean of the fixed t, by decile:")
        print("   " + " ".join(f"{v:+.3f}" for v in mean_lean))
        tails = f"{mean_lean[0]:+.3f} vs {mean_lean[-1]:+.3f}"
        print(f"   lower tail vs upper tail: {tails}\n")
    print(
        "  Two tails wrong by the same amount is dof, and the refit arm should take\n"
        "  it. Two tails wrong by different amounts is skew, and the skewed arm\n"
        "  should take it. A skewed t beating a symmetric one by less than the\n"
        "  refitted dof does is just the extra parameter, not skew."
    )


if __name__ == "__main__":
    main()
