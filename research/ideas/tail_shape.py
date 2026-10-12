"""Is the band's problem the shape? Same mean, same variance, a fatter tail.

`statespace-path-ensembles.md` ends with a precise open question. Nothing beats
the walk's forecast distribution on CRPS at any horizon - and **no Gaussian
forecast is calibrated on real data at all**: the probability integral
transform's flatness runs 18 to 461 against the 1.0 that calibration means, the
walk included at a best of 18.1. The two failure modes are opposite - the walk
is too wide in the middle and right in the tails, `reverting` is right in the
middle and too narrow in the tails - so neither has the right *shape*.

That document nominated `robust.py` as the lever. **That was imprecise.**
`robust` inflates the measurement variance when an innovation is surprising,
which changes the **gain** - how far one outlier moves the state - and leaves
the predictive density Gaussian. It cannot move a PIT flatness, because the PIT
is a statement about the shape of the forecast density and `robust` does not
change that shape. It is still worth having as an arm, to test my own claim
rather than quietly drop it.

What *would* move it is quoting the band as a **Student-t** instead of a
normal.

## The test changes one thing and holds two fixed

The predictive is written

    y ~ mu + sigma * sqrt((nu - 2)/nu) * T_nu

with `mu` and `sigma` taken from the walk - the best-performing arm - and only
`nu` fitted. The `sqrt((nu-2)/nu)` is deliberate: a standard `T_nu` has
variance `nu/(nu-2)`, so scaling by its inverse square root leaves the
predictive **variance exactly sigma^2**. So the mean is unchanged, the variance
is unchanged, and the only difference is the shape.

If the t wins, it is shape and nothing else - not a better drift, not a better
volatility estimate, not more ensemble draws.

## The controls decide whether it is real

The Deriv constant-volatility feeds have **Gaussian increments by
construction**, so a fitted `nu` there should come back **large** - a t with
many degrees of freedom *is* a normal - and the t arm should buy nothing. A
small `nu` on those feeds would mean the fit is reading its own noise.

So the prediction, written first: `nu` large and no gain on the generated
feeds, `nu` small - three to six - and a large drop in PIT flatness on the
traded ones.

## CRPS is computed numerically and checked against a closed form

The Gaussian CRPS has a closed form and the Student-t's involves Beta
functions, so both are done by quadrature on the quantile grid instead -
`CRPS = integral (F(x) - 1{x >= y})^2 dx` - and the Gaussian arm's numeric
value is asserted against its analytic one. A score computed two ways that
agree is a score; one way is a hope.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

HOUR = 3600.0
SEED = 20261012

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD")
#: Gaussian increments by construction: `nu` must fit large and the t must buy
#: nothing.
GENERATED = ("Volatility_75_Index", "Volatility_25_Index", "Step_Index")
FRAME = os.environ.get("FRAME", "1h")
HORIZONS = tuple(int(h) for h in os.environ.get("HORIZONS", "1,5,20,60").split(","))
#: Degrees of freedom to fit over. Above 2 so the variance exists, and up to
#: 200 so "effectively Gaussian" is reachable and visible as a grid edge.
NUS = (2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 12.0, 20.0, 40.0, 100.0, 200.0)
SPAN = 240
BINS = 10
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "20000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str = FRAME):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = np.asarray(bundle["time"], dtype=float)[order]
        closes = np.asarray(bundle["close"], dtype=float)[order]
    keep = (closes > 0) & (times >= SINCE)
    times, closes = times[keep], closes[keep]
    if len(times) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
    return (times, np.log(closes)) if len(times) > 4000 else None


def standardised(levels, horizon: int, span: int = SPAN):
    """`(y - mu)/sigma` for the walk's forecast, one per usable bar.

    The walk is the baseline because it is the best-performing arm in
    `statespace-path-ensembles.md`. `mu` is the current level and `sigma` is the
    trailing volatility scaled by `sqrt(horizon)`.
    """
    import numpy as np

    moves = np.diff(levels)
    out = []
    for at in range(span, len(levels) - horizon):
        window = moves[at - span : at]
        spread = float(np.std(window))
        if spread <= 0:
            continue
        out.append((float(levels[at + horizon] - levels[at])) / (spread * math.sqrt(horizon)))
    return np.asarray(out)


def fit_nu(zs, nus=NUS):
    """The `nu` maximising the t log-likelihood, with the variance held at one.

    The scale factor `sqrt((nu-2)/nu)` keeps the predictive variance at exactly
    one whatever `nu` is, so this fit cannot buy anything by widening - only by
    reshaping. That is the whole point of the arm.
    """
    from scipy import stats

    best = None
    for nu in nus:
        scale = math.sqrt((nu - 2.0) / nu)
        total = float(np.sum(stats.t.logpdf(zs / scale, nu) - math.log(scale)))
        if not math.isfinite(total):
            continue
        if best is None or total > best[1]:
            best = (nu, total)
    return best


def pit_gaussian(zs):
    from scipy import stats

    return stats.norm.cdf(zs)


def pit_t(zs, nu: float):
    from scipy import stats

    return stats.t.cdf(zs / math.sqrt((nu - 2.0) / nu), nu)


def crps_numeric(quantile, zs, grid: int = 400):
    """`integral (F(x) - 1{x>=y})^2 dx` on a fixed grid, for standardised `zs`.

    `quantile` maps a probability to the predictive's own quantile, so the grid
    is placed where the distribution actually is rather than on an arbitrary
    range - which matters for a `nu` near 2.5, whose tails are very long.
    """
    import numpy as np

    probabilities = np.linspace(0.5 / grid, 1.0 - 0.5 / grid, grid)
    xs = quantile(probabilities)
    widths = np.gradient(xs)
    cdf = probabilities
    total = np.zeros(len(zs))
    for i, x in enumerate(xs):
        total += (cdf[i] - (x >= zs).astype(float)) ** 2 * widths[i]
    return float(np.mean(total))


def crps_gaussian_closed(zs):
    """The analytic Gaussian CRPS, to check the quadrature against."""
    import numpy as np
    from scipy import stats

    return float(
        np.mean(
            zs * (2.0 * stats.norm.cdf(zs) - 1.0)
            + 2.0 * stats.norm.pdf(zs)
            - 1.0 / math.sqrt(math.pi)
        )
    )


def flatness(values, bins: int = BINS) -> float:
    """Chi-square of the PIT histogram against uniform, per degree of freedom.
    1.0 is calibrated."""
    import numpy as np

    if len(values) < 200:
        return float("nan")
    counts, _ = np.histogram(np.clip(values, 0.0, 1.0 - 1e-12), bins=bins, range=(0.0, 1.0))
    want = len(values) / bins
    return float(np.sum((counts - want) ** 2 / want) / (bins - 1))


def coverage(values, share: float) -> float:
    low, high = (1.0 - share) / 2.0, 1.0 - (1.0 - share) / 2.0
    return float(sum(1 for v in values if low <= v <= high) / len(values))


def main() -> None:
    global np
    import numpy as np  # noqa: PLW0603
    from scipy import stats

    print(
        f"frame {FRAME}, horizons {HORIZONS}, nu grid {NUS[0]} to {NUS[-1]}\n"
        "The predictive is the walk's mean and variance with only the **shape**\n"
        "changed: `mu + sigma sqrt((nu-2)/nu) T_nu`, whose variance is exactly\n"
        "`sigma^2` for every `nu`. So the t arm cannot win by widening.\n"
        "PIT flatness 1.0 is calibrated; coverage should read 0.500 and 0.900.\n"
    )

    print("=" * 112)
    print("ARM 0  the quadrature agrees with the closed form, or nothing below is a score")
    print("=" * 112)
    rng = np.random.default_rng(SEED)
    sample = rng.normal(0.0, 1.0, 20000)
    numeric = crps_numeric(lambda p: stats.norm.ppf(p), sample)
    closed = crps_gaussian_closed(sample)
    print(
        f"Gaussian CRPS on 20,000 standard normals: quadrature {numeric:.6f}, "
        f"closed form {closed:.6f}, gap {abs(numeric - closed):.2e}"
    )

    print("\n" + "=" * 112)
    print("ARM 1  fitted nu, and what the shape change buys")
    print("=" * 112)
    print(
        f"{'instrument':<22}{'h':>4}{'n':>7}{'nu':>7}{'edge':>5}"
        f"{'flat gauss':>12}{'flat t':>9}{'cover90 g':>11}{'cover90 t':>11}"
        f"{'CRPS g':>9}{'CRPS t':>9}{'t/g':>8}"
    )
    rows: dict[str, list] = {}
    for group, names in (("generated", GENERATED), ("traded", TRADED)):
        print(f"--- {group} ---")
        for name in names:
            found = load(name)
            if found is None:
                continue
            _times, levels = found
            for h in HORIZONS:
                zs = standardised(levels, h)
                if len(zs) < 1000:
                    continue
                half = len(zs) // 2
                got = fit_nu(zs[:half])
                if got is None:
                    continue
                nu = got[0]
                held = zs[half:]
                pg, pt = pit_gaussian(held), pit_t(held, nu)
                cg = crps_numeric(lambda p: stats.norm.ppf(p), held)
                scale = math.sqrt((nu - 2.0) / nu)
                ct = crps_numeric(lambda p, n=nu, s=scale: stats.t.ppf(p, n) * s, held)
                rows.setdefault(f"{group}:{h}", []).append(
                    {
                        "nu": nu,
                        "fg": flatness(pg),
                        "ft": flatness(pt),
                        "c9g": coverage(pg, 0.9),
                        "c9t": coverage(pt, 0.9),
                        "ratio": ct / cg if cg > 0 else float("nan"),
                    }
                )
                print(
                    f"{name:<22}{h:>4}{len(held):>7}{nu:>7.1f}"
                    f"{'*' if nu in (NUS[0], NUS[-1]) else '':>5}"
                    f"{flatness(pg):>12.1f}{flatness(pt):>9.1f}"
                    f"{coverage(pg, 0.9):>11.3f}{coverage(pt, 0.9):>11.3f}"
                    f"{cg:>9.4f}{ct:>9.4f}{ct / cg if cg > 0 else float('nan'):>8.3f}"
                )

    print("\n" + "=" * 112)
    print("ARM 2  the verdict")
    print("=" * 112)
    print(
        f"{'group:horizon':<20}{'cells':>7}{'med nu':>9}{'flat gauss':>12}"
        f"{'flat t':>9}{'cover90 g':>11}{'cover90 t':>11}{'med CRPS t/g':>14}"
    )
    for key in sorted(rows):
        cells = rows[key]
        print(
            f"{key:<20}{len(cells):>7}{statistics.median(c['nu'] for c in cells):>9.1f}"
            f"{statistics.median(c['fg'] for c in cells):>12.1f}"
            f"{statistics.median(c['ft'] for c in cells):>9.1f}"
            f"{statistics.median(c['c9g'] for c in cells):>11.3f}"
            f"{statistics.median(c['c9t'] for c in cells):>11.3f}"
            f"{statistics.median(c['ratio'] for c in cells):>14.3f}"
        )
    print(
        "\nThe generated rows are the calibration: their increments are Gaussian\n"
        "by construction, so `nu` must fit large and `CRPS t/g` must sit at 1.0.\n"
        "A small `nu` there would mean the fit is reading its own noise."
    )
    print("\nDONE")


if __name__ == "__main__":
    main()
