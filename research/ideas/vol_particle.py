"""Does a stochastic-volatility particle filter beat the shipped EWMA?

**The question is I9's, not "is there a better volatility estimator".** The
desk's `Volatility` is an exponentially weighted mean with no variance, and it
parameterises every level update as if it were exact. A particle filter over
log-volatility would give the estimate a posterior - which is the thing I9 says
is missing. So the scoring is in two parts and the second one is the point:

1. **sharpness** - does it predict the size of the next move better?
2. **calibration** - does its stated uncertainty match its realised error?

An estimator can lose on (1) and still be worth having if it wins on (2),
because a band that knows when it is unsure is what the cascade needs.

## The arms, and why the middle one decides

| arm | what it is |
| --- | --- |
| `ewma` | the shipped estimator: exponentially weighted mean absolute return |
| `kalman` | a Kalman filter on `log(r^2)` - **linear, Gaussian, no particles** |
| `particle` | a bootstrap particle filter on the same SV model |

`kalman` is the arm that decides, and it is the same trick `level-filters.md`
used to settle the particle question for levels. The SV model is non-linear
only because the observation is `r = exp(h/2) * eps`; taking logs makes it
linear with a non-Gaussian (log chi-squared) error, which a Kalman can still
run if that error is approximated by a Gaussian. **If `particle` only ties
`kalman`, the non-Gaussianity is not worth paying for and the particles are
machinery for nothing** - which is exactly what happened with levels.

## The nulls, before any real data

* **constant volatility.** All three must tie. If `particle` wins here it is
  fitting noise.
* **a true SV process.** `particle` must win, or the test is too blunt to read
  a null from.

## No lookahead

Parameters are fitted on the first half and every number reported comes from
the second. The EWMA's half-life is fitted the same way, so it is not being
handicapped by a constant chosen elsewhere.
"""

from __future__ import annotations

import gzip
import math
import sys
from pathlib import Path

import numpy as np

RNG = np.random.default_rng(20261009)
PARTICLES = 512


# ------------------------------------------------------------------ the arms


def ewma_vol(r: np.ndarray, half_life: float) -> np.ndarray:
    """Predictive sigma for each step, from an EWMA of |r|. The shipped shape.

    Returned shifted by one: the value at `t` uses data up to `t-1` only.
    """
    alpha = 1.0 - 0.5 ** (1.0 / max(half_life, 1e-9))
    out = np.empty(len(r))
    mean_abs = float(np.mean(np.abs(r[: min(50, len(r))])))
    for i in range(len(r)):
        out[i] = mean_abs
        mean_abs += alpha * (abs(r[i]) - mean_abs)
    # |r| for a Gaussian has mean sigma*sqrt(2/pi); convert to a sigma.
    return out * math.sqrt(math.pi / 2.0)


def kalman_logvol(r: np.ndarray, phi: float, q: float) -> tuple[np.ndarray, np.ndarray]:
    """Kalman on y = log(r^2), the linearised SV model.

    `log(chi^2_1)` has mean -1.2704 and variance pi^2/2; approximating it by a
    Gaussian with those moments is the standard linearisation, and it is what
    makes this a *cheap* arm rather than a different model.
    """
    y = np.log(np.maximum(r**2, 1e-300))
    offset, obs_var = -1.270363, (math.pi**2) / 2.0
    h = float(np.mean(y) - offset)
    p = obs_var
    mu = h
    pred_h = np.empty(len(r))
    pred_p = np.empty(len(r))
    for i in range(len(r)):
        # predict
        h = mu + phi * (h - mu)
        p = (phi**2) * p + q
        pred_h[i], pred_p[i] = h, p
        # update on this observation
        innov = y[i] - (h + offset)
        s = p + obs_var
        gain = p / s
        h += gain * innov
        p *= 1.0 - gain
    return pred_h, pred_p


def particle_logvol(
    r: np.ndarray, phi: float, q: float, mu: float
) -> tuple[np.ndarray, np.ndarray]:
    """Bootstrap particle filter on h: h' = mu + phi(h-mu) + N(0,q), r ~ N(0, e^h)."""
    n = PARTICLES
    h = mu + RNG.normal(0.0, math.sqrt(q / max(1.0 - phi**2, 1e-6)), n)
    pred_h = np.empty(len(r))
    pred_p = np.empty(len(r))
    for i in range(len(r)):
        h = mu + phi * (h - mu) + RNG.normal(0.0, math.sqrt(q), n)
        pred_h[i], pred_p[i] = float(h.mean()), float(h.var())
        # weight by how likely this observation is under each particle
        logw = -0.5 * (h + (r[i] ** 2) * np.exp(-h))
        logw -= logw.max()
        w = np.exp(logw)
        total = w.sum()
        if not np.isfinite(total) or total <= 0:
            continue
        w /= total
        # systematic resampling
        positions = (RNG.random() + np.arange(n)) / n
        h = h[np.searchsorted(np.cumsum(w), positions, side="right").clip(0, n - 1)]
    return pred_h, pred_p


# ------------------------------------------------------------------ scoring


def score(r: np.ndarray, sigma: np.ndarray, var_h: np.ndarray | None) -> dict:
    """Sharpness and calibration of a one-step-ahead predictive distribution."""
    sigma = np.maximum(sigma, 1e-12)
    nll = float(np.mean(0.5 * np.log(2 * math.pi * sigma**2) + 0.5 * (r / sigma) ** 2))
    mae = float(np.mean(np.abs(np.abs(r) - sigma * math.sqrt(2 / math.pi))))
    z = r / sigma
    out = {
        "nll": nll,
        "mae": mae,
        # A Gaussian predictive says 90% of |z| should be under 1.645.
        "cover90": float(np.mean(np.abs(z) < 1.6449)),
        # And the spread of z should be 1. Above 1 means the band is too tight.
        "z_sd": float(np.std(z)),
    }
    if var_h is not None:
        out["mean_sd_h"] = float(np.mean(np.sqrt(np.maximum(var_h, 0.0))))
    return out


def fit_and_score(r: np.ndarray, label: str) -> list[dict]:
    """Fit every arm on the first half, score all of them on the second."""
    cut = len(r) // 2
    train, test = r[:cut], r[cut:]
    rows = []

    best = min(
        (
            (float(np.mean((np.abs(train[1:]) - ewma_vol(train, hl)[:-1]) ** 2)), hl)
            for hl in (8, 16, 32, 64, 128, 256)
        ),
    )[1]
    sig = ewma_vol(r, best)[cut - 1 : -1]
    rows.append({"data": label, "arm": "ewma", "param": f"hl={best}", **score(test, sig, None)})

    grid = [(phi, q) for phi in (0.90, 0.95, 0.98, 0.995) for q in (0.01, 0.05, 0.15, 0.4)]

    def nll_of(fn, args) -> float:
        h, _ = fn(train, *args)
        return score(train, np.exp(h / 2.0), None)["nll"]

    phi, q = min(grid, key=lambda g: nll_of(kalman_logvol, g))
    h, p = kalman_logvol(r, phi, q)
    rows.append(
        {
            "data": label,
            "arm": "kalman",
            "param": f"phi={phi} q={q}",
            **score(test, np.exp(h[cut:] / 2.0), p[cut:]),
        }
    )

    mu = float(np.mean(np.log(np.maximum(train**2, 1e-300))) + 1.270363)
    phi, q = min(grid, key=lambda g: nll_of(particle_logvol, (*g, mu)))
    h, p = particle_logvol(r, phi, q, mu)
    rows.append(
        {
            "data": label,
            "arm": "particle",
            "param": f"phi={phi} q={q}",
            **score(test, np.exp(h[cut:] / 2.0), p[cut:]),
        }
    )
    return rows


# ------------------------------------------------------------------ data


def synthetic_constant(n: int = 8000) -> np.ndarray:
    return RNG.normal(0.0, 0.01, n)


def synthetic_sv(n: int = 8000, phi: float = 0.98, q: float = 0.05) -> np.ndarray:
    h = np.empty(n)
    mu = 2 * math.log(0.01)
    h[0] = mu
    for i in range(1, n):
        h[i] = mu + phi * (h[i - 1] - mu) + RNG.normal(0.0, math.sqrt(q))
    return RNG.normal(0.0, 1.0, n) * np.exp(h / 2.0)


def real(path: Path) -> np.ndarray:
    rows = []
    with gzip.open(path, "rt") as fh:
        next(fh)
        for line in fh:
            parts = line.rstrip("\n").split(",")
            if len(parts) >= 5:
                try:
                    rows.append(float(parts[4]))
                except ValueError:
                    continue
    close = np.asarray(rows)
    close = close[close > 0]
    r = np.diff(np.log(close))
    return r[np.isfinite(r)]


def main() -> None:
    table: list[dict] = []
    table += fit_and_score(synthetic_constant(), "NULL constant vol")
    table += fit_and_score(synthetic_sv(), "NULL true SV")
    for path in sys.argv[1:]:
        p = Path(path)
        r = real(p)
        if len(r) < 2000:
            print(f"skipping {p.name}: only {len(r)} returns")
            continue
        table += fit_and_score(r, f"{p.name.split('_')[0]} {p.name.split('_')[1]} (n={len(r)})")

    head = f"{'data':<26}{'arm':<10}{'NLL':>10}{'MAE':>11}{'cover90':>9}{'z sd':>7}  param"
    print(head)
    print("-" * len(head))
    last = None
    for row in table:
        if last and row["data"] != last:
            print()
        last = row["data"]
        print(
            f"{row['data']:<26}{row['arm']:<10}{row['nll']:>10.4f}{row['mae']:>11.6f}"
            f"{row['cover90']:>9.3f}{row['z_sd']:>7.3f}  {row['param']}"
        )


if __name__ == "__main__":
    main()
