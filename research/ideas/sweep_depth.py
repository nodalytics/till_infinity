"""What coverage does `SWEEP_SIGMAS = 1.0` actually buy? The code asks for this.

`engine.SWEEP_SIGMAS` is the band a stop has to clear, and its own docstring
says what is wrong with it:

    One would be roughly the depth 84% of sweeps stay inside **if the depths
    were normal, which they are not** - they are bounded below at zero with a
    long right tail, so real coverage at one sigma is higher than that. [...]
    This is the setting most worth **measuring against outcomes** rather than
    reasoning about.

So this measures it. `levels.wick_deep_vol` returns `centre + sigmas * reach`,
a mean-plus-k-sigma rule applied to a non-negative, right-skewed quantity, and
the question is what fraction of sweeps that actually contains.

**This is also where the Student-t work does not apply, and saying so matters.**
`statespace/tails.py` corrects a *symmetric* predictive band. A sweep depth is
one-sided and bounded at zero, so a t is the wrong family for it by
construction, and reaching for it here would be using a result outside the place
it was measured.

## The construction

A sweep depth needs a level and a touch. Rather than import production's
proposers - which would make this a test of `drawing` rather than of the
depth distribution - the level is the simplest thing that produces real sweeps:
a rolling `LOOK`-bar extreme. When a bar's high exceeds the prior high, the
depth is how far past it the bar reached, in the instrument's own volatility
units. That is the same quantity `wick_deep_vol` models.

Depths are collected per instrument and **kept per instrument**, because the
coverage of a mean-plus-k-sigma rule depends on the shape, and pooling
instruments of different shapes would measure the mixture rather than any of
them.

## What is reported

- **the coverage** of `mean + k * sd` for a range of `k`, so the current
  setting of 1.0 can be read off and compared to the 84% the docstring names;
- **the `k` needed** for 80%, 90% and 95%, which is the number a caller
  choosing a risk budget actually wants;
- **which family fits**, by maximum likelihood with AIC over exponential,
  lognormal, Weibull and Pareto. If one of them wins clearly, its own quantile
  is a better rule than mean-plus-k-sigma at any `k`, and that is a concrete
  change rather than a tuning.
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

FRAMES = tuple(os.environ.get("FRAMES", "15m,1h,4h").split(","))
LOOK = int(os.environ.get("LOOK", "100"))
KS = tuple(float(k) for k in os.environ.get("KS", "0,0.5,1.0,1.5,2.0,3.0").split(","))
WANT = tuple(float(k) for k in os.environ.get("WANT", "0.80,0.90,0.95").split(","))
VOL_BARS = int(os.environ.get("VOL_BARS", "100"))

NAMES = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "EURGBP",
    "XAUUSD",
    "XAGUSD",
)


def depths(bars: dict) -> np.ndarray:
    """How far past a rolling extreme a breaching bar reaches, in vol units."""
    high, low, close = bars["high"], bars["low"], bars["close"]
    span = np.log(np.maximum(high, 1e-12)) - np.log(np.maximum(low, 1e-12))
    out = []
    for i in range(max(LOOK, VOL_BARS), len(close)):
        unit = float(np.median(span[i - VOL_BARS : i]))
        if unit <= 0:
            continue
        prior_high = float(np.max(high[i - LOOK : i]))
        prior_low = float(np.min(low[i - LOOK : i]))
        if high[i] > prior_high > 0:
            out.append((math.log(float(high[i])) - math.log(prior_high)) / unit)
        if 0 < low[i] < prior_low:
            out.append((math.log(prior_low) - math.log(float(low[i]))) / unit)
    return np.asarray([d for d in out if d > 0])


def coverage_at(got: np.ndarray, k: float) -> float:
    return float(np.mean(got <= float(np.mean(got)) + k * float(np.std(got))))


def k_for(got: np.ndarray, want: float) -> float:
    """The multiplier that reaches `want`, from the empirical quantile."""
    mean, sd = float(np.mean(got)), float(np.std(got))
    if sd <= 0:
        return float("nan")
    return (float(np.quantile(got, want)) - mean) / sd


def fits(got: np.ndarray) -> tuple[str, float]:
    """The best of four one-sided families by AIC, and its margin."""
    n = len(got)
    logged = np.log(got)
    scores: dict[str, float] = {}

    # Exponential: one parameter, the mean.
    mean = float(np.mean(got))
    scores["exponential"] = 2 * 1 - 2 * float(np.sum(-np.log(mean) - got / mean))

    # Lognormal: the normal fitted to the logs.
    mu, sigma = float(np.mean(logged)), float(np.std(logged))
    if sigma > 0:
        ll = float(
            np.sum(
                -logged
                - math.log(sigma * math.sqrt(2 * math.pi))
                - 0.5 * ((logged - mu) / sigma) ** 2
            )
        )
        scores["lognormal"] = 2 * 2 - 2 * ll

    # Weibull, by a short Newton sweep on the shape.
    best = None
    for shape in np.linspace(0.4, 4.0, 73):
        scale = float(np.mean(got**shape)) ** (1.0 / shape)
        ll = float(
            np.sum(
                math.log(shape)
                - shape * math.log(scale)
                + (shape - 1.0) * logged
                - (got / scale) ** shape
            )
        )
        if best is None or ll > best[0]:
            best = (ll, shape, scale)
    if best:
        scores["weibull"] = 2 * 2 - 2 * best[0]

    # Pareto above its own minimum, which is the tail-only comparison.
    floor = float(np.min(got))
    if floor > 0:
        alpha = n / float(np.sum(logged - math.log(floor)))
        if alpha > 0:
            ll = float(np.sum(math.log(alpha) + alpha * math.log(floor) - (alpha + 1) * logged))
            scores["pareto"] = 2 * 1 - 2 * ll

    order = sorted(scores.items(), key=lambda kv: kv[1])
    if len(order) < 2:
        return (order[0][0] if order else "none"), float("nan")
    return order[0][0], order[1][1] - order[0][1]


def main() -> None:
    print(
        f"Sweep depth past a rolling {LOOK}-bar extreme, in volatility units, which\n"
        "is the quantity `levels.wick_deep_vol` models as `centre + sigmas * reach`.\n"
        f"Production runs at SWEEP_SIGMAS = 1.0. The docstring expects 84% there and\n"
        "says the real figure is higher, because depths are one-sided.\n"
    )
    for frame in FRAMES:
        print(f"--- {frame}")
        head = "".join(f"{f'k={k:g}':>8}" for k in KS)
        want = "".join(f"{f'{int(w * 100)}%':>7}" for w in WANT)
        print(f"  {'feed':<9}{'n':>7}{'skew':>7}{head}  |{want}  {'family':<12}{'dAIC':>8}")
        pooled = []
        for name in NAMES:
            bars = load(name, frame)
            if bars is None:
                continue
            got = depths(bars)
            if len(got) < 300:
                continue
            pooled.append(got)
            mean, sd = float(np.mean(got)), float(np.std(got))
            skew = float(np.mean(((got - mean) / sd) ** 3)) if sd > 0 else float("nan")
            cells = "".join(f"{coverage_at(got, k):>8.3f}" for k in KS)
            needs = "".join(f"{k_for(got, w):>7.2f}" for w in WANT)
            family, margin = fits(got)
            print(
                f"  {name:<9}{len(got):>7}{skew:>7.2f}{cells}  |{needs}  {family:<12}{margin:>8.0f}"
            )
        if pooled:
            got = np.concatenate(pooled)
            mean, sd = float(np.mean(got)), float(np.std(got))
            skew = float(np.mean(((got - mean) / sd) ** 3))
            cells = "".join(f"{coverage_at(got, k):>8.3f}" for k in KS)
            needs = "".join(f"{k_for(got, w):>7.2f}" for w in WANT)
            family, margin = fits(got)
            print(
                f"  {'POOLED':<9}{len(got):>7}{skew:>7.2f}{cells}  |{needs}  "
                f"{family:<12}{margin:>8.0f}"
            )
        print()
    print(
        "  The `k=1` column is what production buys today. The percentage block is\n"
        "  the multiplier each target coverage needs, which is the number to set\n"
        "  SWEEP_SIGMAS from. A family winning by a large AIC margin everywhere is\n"
        "  a better rule than any multiplier, because its quantile is exact where\n"
        "  mean-plus-k-sigma only approximates."
    )


if __name__ == "__main__":
    main()
