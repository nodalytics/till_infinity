"""Choose the delay embedding's parameters instead of assuming them.

Run from the repository root:  python research/harness/embed.py

`tda.py` and `shapes.py` both fixed the embedding at dimension 3 with unit lag, and
both returned negative results. **A negative result under arbitrary parameters is
weak**, because the obvious reply is that the embedding was wrong. This picks the
parameters the way the dynamical-systems literature says to, so that the next negative
result - if it is one - is worth more.

The measure-theoretic embedding paper (Botvinick-Greenhouse et al., math.DS 2024) is
explicit about this: it lists "False Nearest Neighbors, Cao's method, mutual
information, and approaches based on persistent homology" and then says it will "assume
that the time delay tau and the embedding dimension m have already been chosen using
these techniques". Nothing here had done that.

## The lag, from mutual information

Takens permits any lag, so the choice is about usefulness rather than validity. Too
small and successive coordinates are nearly equal, so the cloud collapses onto the
diagonal and carries no shape. Too large and they are independent, so the cloud is
noise.

The standard answer is the **first local minimum of the average mutual information**
between the series and itself lagged by `tau` - the point where the coordinates have
stopped being redundant but have not yet stopped being related. Mutual information
rather than autocorrelation because autocorrelation only sees linear dependence, and
the whole premise of embedding a price series is that the dependence is not linear.

## The dimension, from false nearest neighbours

Embed at `m` and at `m+1`. A pair of points that are close in `m` dimensions but far
apart in `m+1` were only neighbours because the projection collapsed them - a **false**
neighbour. As `m` grows the false fraction falls, and the dimension to use is where it
stops falling: adding coordinates past that point buys nothing and costs sample density.

## What this cannot settle

Both criteria were designed for deterministic chaotic systems observed with little
noise. A price series is neither, so these should be read as "the least arbitrary
choice available" rather than as the correct embedding. The honest use of this file is
to show that the earlier results do not hinge on `DIM = 3`, or to show that they do.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Lags to consider for the mutual-information curve.
MAX_LAG = 24

#: Dimensions to consider for false nearest neighbours.
MAX_DIM = 8

#: Bins for the mutual-information histogram. Enough to see structure, few enough
#: that a bin is not mostly empty at these sample sizes.
BINS = 16

#: A neighbour is false when the extra coordinate moves it by more than this multiple
#: of the series' own spread. 10 is the value Kennel's original paper uses.
FALSE = 10.0

#: The false fraction below which a dimension is accepted.
SETTLED = 0.05


def mutual_information(series: np.ndarray, lag: int, bins: int = BINS) -> float:
    """Average mutual information between the series and itself lagged by `lag`.

    Computed from a 2-D histogram, which is the standard estimator here and is
    adequate because only the *shape* of the curve against `lag` matters - the first
    local minimum - not the absolute value of the information.
    """
    if lag <= 0 or lag >= len(series):
        return 0.0
    a, b = series[:-lag], series[lag:]
    joint, _, _ = np.histogram2d(a, b, bins=bins)
    joint = joint / max(joint.sum(), 1)
    pa = joint.sum(axis=1, keepdims=True)
    pb = joint.sum(axis=0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        term = joint * np.log(joint / (pa * pb))
    return float(np.nansum(term))


def best_lag(series: np.ndarray, max_lag: int = MAX_LAG) -> tuple[int, list[float]]:
    """The first local minimum of the mutual-information curve, and the curve.

    Falls back to the global minimum when the curve has no local minimum inside the
    range, which happens on a series with little structure - and saying so is better
    than silently returning 1.
    """
    curve = [mutual_information(series, lag) for lag in range(1, max_lag + 1)]
    for i in range(1, len(curve) - 1):
        if curve[i] < curve[i - 1] and curve[i] <= curve[i + 1]:
            return i + 1, curve
    return int(np.argmin(curve)) + 1, curve


def false_neighbours(series: np.ndarray, lag: int, dim: int) -> float:
    """Fraction of nearest neighbours in `dim` that separate in `dim + 1`."""
    from scipy.spatial import cKDTree

    need = (dim + 1) * lag + 1
    if len(series) < need + 10:
        return 1.0
    count = len(series) - dim * lag
    low = np.stack([series[i * lag : i * lag + count] for i in range(dim)], axis=1)
    extra = series[dim * lag : dim * lag + count]
    if len(low) < 20:
        return 1.0
    # The nearest neighbour other than the point itself.
    tree = cKDTree(low)
    dist, idx = tree.query(low, k=2)
    near, mate = dist[:, 1], idx[:, 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        stretch = np.abs(extra - extra[mate]) / np.where(near > 0, near, np.nan)
    ok = np.isfinite(stretch)
    if not ok.any():
        return 1.0
    return float((stretch[ok] > FALSE).mean())


def best_dim(series: np.ndarray, lag: int, max_dim: int = MAX_DIM) -> tuple[int, list[float]]:
    """The smallest dimension whose false-neighbour fraction has settled."""
    curve = [false_neighbours(series, lag, dim) for dim in range(1, max_dim + 1)]
    for dim, share in enumerate(curve, start=1):
        if share <= SETTLED:
            return dim, curve
    return int(np.argmin(curve)) + 1, curve


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--sample", type=int, default=20000, help="bars to estimate from")
    args = ap.parse_args()

    print(
        f"lag from the first minimum of mutual information (up to {MAX_LAG}), "
        f"dimension from false nearest neighbours (up to {MAX_DIM})\n"
    )
    print(f"{'instrument':<24}{'lag':>5}{'dim':>5}   mutual information curve, first six")
    chosen = {}
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<24} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        close = bars[-args.sample :, 4]
        close = close[close > 0]
        if len(close) < 1000:
            print(f"{symbol:<24} only {len(close)} usable bars")
            continue
        returns = np.diff(np.log(close))
        returns = returns / (returns.std() or 1.0)
        lag, curve = best_lag(returns)
        dim, fnn = best_dim(returns, lag)
        chosen[symbol] = (lag, dim)
        head = "  ".join(f"{v:.3f}" for v in curve[:6])
        print(f"{symbol:<24}{lag:>5}{dim:>5}   {head}")
        print(f"{'':<24}{'':>10}   false neighbours: " + "  ".join(f"{v:.2f}" for v in fnn[:6]))

    if chosen:
        lags = [v[0] for v in chosen.values()]
        dims = [v[1] for v in chosen.values()]
        print(f"\nmedian lag {int(np.median(lags))}, median dimension {int(np.median(dims))}")
        print(
            "  `tda.py` and `shapes.py` both used lag 1 and dimension 3. If the chosen\n"
            "  values differ, their negative results were measured at the wrong\n"
            "  embedding and are worth re-running before being believed."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
