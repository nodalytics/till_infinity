"""The one-bar band: is its problem the tail shape, or the sigma?

`statespace-tail-shape.md` leaves exactly one horizon genuinely miscalibrated.
The PIT flatness range of 18 to 461 was mostly an **overlap artefact** - the
forward window stepped one bar at a time, so at h=20 consecutive residuals
shared 19 of their 20 bars, and stepped by the horizon h=20 reads **1.6**. Only
**h=1** stands, at **73.3**, because a one-bar horizon has no overlap to remove.

That document also closes both candidate levers. `robust.py` cannot move a PIT
because it changes the **gain** and leaves the predictive density Gaussian, and
a Student-t "is not the answer" with `nu` depending on the horizon.

## So the hypothesis here is not the tail at all

A flatness of 73 at one bar does not need a fat-tailed density to explain it.
**A Gaussian with the wrong sigma, bar to bar, is already leptokurtic in
aggregate**: residuals standardised by a sigma that does not track produce a
mixture of normals at different scales, and a mixture of normals is fat-tailed
even though every component is not. Volatility clusters, so a constant or
slow sigma guarantees exactly that.

If that is the cause, the fix is not a shape - it is a better one-bar sigma.

## Which is what the range estimator is

`candle-screen.md` measured that the ratio of a range-based volatility estimator
to the close-to-close one predicts where volatility goes next, **0.6484 within
strata** on twenty FX feeds and **0.6671** on 371 of 392 equities, and that it
strengthens as the window shortens - 0.6232 at a hundred bars, 0.6484 at forty.
`spanning.Span` wires it to `Driven`. Its own gate was stated as "it has to beat
`Q(dt)`, not a six-bin dial", and this is that comparison on the metric the band
problem is written in.

Four arms, same mean, one bar ahead, scored by PIT flatness and CRPS:

- **constant** - one sigma for the whole series. The baseline that reads 73.
- **ewma close** - an exponential mean of squared close-to-close returns.
- **ewma range** - the same, from Parkinson's per-bar variance.
- **garman-klass** - the same, from the fullest per-bar estimator.

Flatness is the chi-square of a ten-bin PIT histogram per degree of freedom, so
**1.0 is calibrated** and larger is worse. One bar ahead has no overlap, so
nothing here needs the horizon-stepping correction.
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
from till_infinity.structures.statespace.spanning import garman_klass, parkinson  # noqa: E402

FRAMES = tuple(os.environ.get("FRAMES", "15m,1h,4h").split(","))
HALF_LIFE = float(os.environ.get("HALF_LIFE", "40"))
BINS = int(os.environ.get("BINS", "10"))
WARM = int(os.environ.get("WARM", "200"))


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def flatness(pits: list[float]) -> float:
    """Chi-square per degree of freedom of the PIT histogram. 1.0 is calibrated."""
    if len(pits) < 10 * BINS:
        return float("nan")
    counts = np.histogram(np.asarray(pits), bins=BINS, range=(0.0, 1.0))[0]
    expected = len(pits) / BINS
    return float(((counts - expected) ** 2 / expected).sum()) / (BINS - 1)


def crps_normal(z: float) -> float:
    """CRPS of a standard normal at `z`, in sigma units - the closed form."""
    return (
        z * (2.0 * normal_cdf(z) - 1.0)
        + 2.0 * math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
        - 1.0 / math.sqrt(math.pi)
    )


def sigmas(bars) -> dict[str, np.ndarray]:
    """One-bar-ahead sigma from each estimator, using bars strictly before."""
    o, h, l_, c = bars["open"], bars["high"], bars["low"], bars["close"]
    rets = np.diff(np.log(c))
    n = len(rets)
    alpha = 1.0 - 0.5 ** (1.0 / HALF_LIFE)
    out = {
        name: np.full(n, np.nan)
        for name in ("constant", "ewma close", "ewma range", "garman-klass")
    }
    # Constant: one sigma for the whole series, which is the baseline.
    whole = float(np.std(rets)) if n > 2 else 0.0
    out["constant"][:] = whole
    close_var = range_var = gk_var = float(np.var(rets[:WARM])) if n > WARM else 0.0
    for i in range(n):
        if i >= WARM:
            out["ewma close"][i] = math.sqrt(close_var) if close_var > 0 else whole
            out["ewma range"][i] = math.sqrt(range_var) if range_var > 0 else whole
            out["garman-klass"][i] = math.sqrt(gk_var) if gk_var > 0 else whole
        # Update with bar i+1's own geometry, which is known once it closes -
        # so the sigma used for bar i+1 is built from bars up to i only.
        close_var += alpha * (rets[i] ** 2 - close_var)
        bar = i + 1
        park = parkinson(float(h[bar]), float(l_[bar]))
        gk = garman_klass(float(o[bar]), float(h[bar]), float(l_[bar]), float(c[bar]))
        if park > 0:
            range_var += alpha * (park - range_var)
        if gk > 0:
            gk_var += alpha * (gk - gk_var)
    return out


def main() -> None:
    names = tuple(
        os.environ.get("PAIRS", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,EURGBP").split(
            ","
        )
    )
    print(
        f"one bar ahead, half-life {HALF_LIFE:g} bars, {BINS}-bin PIT.\n"
        "flatness 1.0 is calibrated; CRPS is in sigma units, lower is better.\n"
        "No overlap at h=1, so no horizon-stepping correction is needed.\n"
    )
    for frame in FRAMES:
        pooled: dict[str, list[float]] = {}
        scores: dict[str, list[float]] = {}
        per_feed: dict[str, list[float]] = {}
        for name in names:
            bars = load(name, frame)
            if bars is None:
                continue
            rets = np.diff(np.log(bars["close"]))
            got = sigmas(bars)
            for arm, sigma in got.items():
                keep = np.isfinite(sigma) & (sigma > 0) & np.isfinite(rets)
                if keep.sum() < 10 * BINS:
                    continue
                z = rets[keep] / sigma[keep]
                pits = [normal_cdf(float(x)) for x in z]
                pooled.setdefault(arm, []).extend(pits)
                scores.setdefault(arm, []).extend(
                    float(sigma[keep][k]) * crps_normal(float(z[k])) for k in range(len(z))
                )
                one = flatness(pits)
                if math.isfinite(one):
                    per_feed.setdefault(arm, []).append(one)
        if not pooled:
            continue
        print(f"{frame}:")
        print(f"  {'arm':<16}{'n':>10}{'flatness':>11}{'per-feed med':>14}{'CRPS':>12}")
        for arm in ("constant", "ewma close", "ewma range", "garman-klass"):
            if arm not in pooled:
                continue
            print(
                f"  {arm:<16}{len(pooled[arm]):>10,}{flatness(pooled[arm]):>11.2f}"
                f"{float(np.median(per_feed[arm])):>14.2f}"
                f"{float(np.mean(scores[arm])) * 1e4:>12.4f}"
            )
        print()
    print(
        "  If `ewma range` and `garman-klass` beat `ewma close`, the one-bar\n"
        "  miscalibration is a sigma problem and the range estimator is its fix.\n"
        "  If all three EWMA arms sit together and far above 1.0, the residual\n"
        "  really is shape - and robust.py still cannot touch it."
    )


if __name__ == "__main__":
    main()
