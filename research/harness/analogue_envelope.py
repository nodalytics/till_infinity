"""Do analogue "twins" forecast a range better than trailing volatility does?

Run from the repository root:  python research/harness/analogue_envelope.py

A pattern-matching service publishes, for each bar, the `k` most similar past windows and the
percentiles of what followed them - a P10/P50/P90 envelope for the next five bars. It states
plainly that the direction is a coin flip and marks every message `NO_TRADE`, so **the only claim
being made is about the range**, and that is what this tests.

This repository has measured the direction question twice already. `motifs.py` clustered recurring
shapes and died on bootstrap; `shapes.py` came out at chance at two different embeddings. The
service's own `p50` agrees: across sixteen published messages it averages +0.003%.

So the question is narrower and fairer: **is an analogue-derived envelope better than the envelope
you get from a trailing volatility estimate?**

## Two things an envelope has to do

**Be calibrated.** If P10 and P90 mean anything, the realised move lands below P10 about 10% of
the time and above P90 about 10% of the time. A 20% total exceedance is the target; 5% means the
envelope is needlessly wide and 40% means it is a fiction.

**Be tight at equal coverage.** Calibration alone is trivial to achieve - widen until it holds.
The useful envelope is the narrower one *at the same exceedance rate*, which is why both are
reported together and neither is reported alone.

## The baseline it has to beat

A trailing standard deviation of log returns, scaled by the square root of the horizon, with the
multiplier chosen so nominal coverage matches. `scaling.py` measured `zeta_2 = 0.9952` across eight
instruments, so the square-root scaling is not an assumption here - it is a measurement, and BTC
came in at 0.989.

If the analogue envelope is no tighter at equal coverage, the nearest-neighbour machinery is
decoration on a volatility estimate, and the honest description of the service is "a trailing
sigma with extra steps".

## Causality, which is the whole difficulty

Neighbours are searched **only in bars strictly before the decision bar**, and the forward window
of a neighbour must also end before it. Getting this wrong is what makes analogue backtests look
remarkable: a twin whose "what happened next" overlaps the present is reporting the answer.

## Match quality is reported too

The service's published match scores run from 59% down to **9%**, and its daily panel's best twin
is a 10% match. This prints the distance distribution so "how similar is the tenth nearest
neighbour, really" has a number attached rather than a label.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: The service's own parameters: a five-bar window, ten twins, five bars forward.
WINDOW = 5
TWINS = 10
FORWARD = 5

#: Bars of history required before a search runs, and the stride between decision bars.
MIN_HISTORY = 3_000
STRIDE = 5

#: Trailing window for the volatility baseline.
VOL_WINDOW = 100

#: Nominal envelope, matching a P10/P90 pair.
LOW, HIGH = 10.0, 90.0

#: Similarity metrics to compare. **The metric is the obvious suspect when a
#: nearest-neighbour method fails, so it is worth eliminating rather than assuming.**
#:
#: `euclid` on shape-normalised returns is the default. `cosine` ignores magnitude entirely
#: and keeps only direction, which is what a shape-matching claim usually means. `corr` is
#: cosine on centred vectors, so it also ignores any constant drift across the window. `rich`
#: is euclid on a wider embedding - returns plus each bar's range and body relative to its
#: own true range - so it can see candle structure the close-only vectors cannot.
METRICS = ("euclid", "cosine", "corr", "rich")


def shape(rets: np.ndarray, at: int) -> np.ndarray:
    """The window's shape: returns scaled by their own dispersion, so level and size drop out."""
    piece = rets[at - WINDOW + 1 : at + 1]
    sd = float(piece.std())
    return piece / sd if sd > 0 else piece


def embed(shapes: np.ndarray, metric: str, extra: np.ndarray | None = None) -> np.ndarray:
    """Prepare the matrix a metric searches over.

    `cosine` and `corr` are computed as Euclidean distance on normalised vectors, which is a
    monotone transform of each - so one search routine serves all four and the comparison is
    genuinely about the metric rather than about two different implementations.
    """
    if metric == "rich" and extra is not None:
        base = np.hstack([shapes, extra])
    else:
        base = shapes
    if metric == "corr":
        base = base - base.mean(axis=1, keepdims=True)
    if metric in ("cosine", "corr"):
        norm = np.linalg.norm(base, axis=1, keepdims=True)
        base = np.divide(base, np.maximum(norm, 1e-12))
    return base


def envelope(
    target: np.ndarray, at: int, shapes: np.ndarray, forwards: np.ndarray, ends: np.ndarray
) -> tuple[float, float, float, float] | None:
    """Analogue P10/P50/P90 for the next `FORWARD` bars, plus the tenth-neighbour distance.

    `ends` is the last bar each candidate's forward window touches; a candidate is admissible
    only if that is strictly before `at`. Without it the search can return a twin whose
    outcome overlaps the period being predicted.
    """
    if not np.isfinite(target).all():
        return None
    usable = ends < at
    if usable.sum() < TWINS * 3:
        return None
    dist = np.linalg.norm(shapes[usable] - target, axis=1)
    picked = np.argpartition(dist, TWINS)[:TWINS]
    got = forwards[usable][picked]
    if not np.isfinite(got).all():
        return None
    return (
        float(np.percentile(got, LOW)),
        float(np.percentile(got, 50.0)),
        float(np.percentile(got, HIGH)),
        float(np.sort(dist[picked])[-1]),
    )


def extras(bars: np.ndarray, idx: np.ndarray, tr: np.ndarray) -> np.ndarray:
    """Candle structure per window: each bar's range and body in its own true range."""
    high, low, close, opens = bars[:, 2], bars[:, 3], bars[:, 4], bars[:, 1]
    unit = np.maximum(tr * np.maximum(close, 1e-12), 1e-12)
    rng = (high - low) / unit
    body = (close - opens) / unit
    out = np.empty((len(idx), WINDOW * 2))
    for k, i in enumerate(idx):
        # `rets` is one shorter than `bars`, so a return at index i is bar i + 1.
        lo = i + 2 - WINDOW
        out[k] = np.concatenate([rng[lo : lo + WINDOW], body[lo : lo + WINDOW]])
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
        or ["btcusd"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    print(
        f"analogue envelope vs trailing volatility: {WINDOW}-bar window, {TWINS} twins, "
        f"{FORWARD} bars forward\nneighbours searched strictly in the past; four similarity "
        "metrics compared\n"
    )

    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"  {symbol:<14} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        good = bars[:, 4] > 0
        bars = bars[good]
        if len(bars) < MIN_HISTORY * 2:
            continue
        tr = candles.true_range(bars)
        close = bars[:, 4]
        rets = np.diff(np.log(close))
        n = len(rets)

        idx = np.arange(WINDOW - 1, n - FORWARD)
        shapes = np.array([shape(rets, i) for i in idx])
        forwards = np.array(
            [float(np.exp(rets[i + 1 : i + 1 + FORWARD].sum()) - 1.0) * 100.0 for i in idx]
        )
        ends = idx + FORWARD
        rich = extras(bars, idx, tr)
        where_of = {i: k for k, i in enumerate(idx)}

        print(f"{symbol}  -  {args.interval} bars")
        print(
            f"  {'metric':<14}{'n':>8}{'< P10':>8}{'> P90':>8}{'total':>8}"
            f"{'width':>9}{'equal-cov':>11}{'sign':>8}{'10th d':>9}"
        )

        vol_rows = None
        for metric in METRICS:
            book = embed(shapes, metric, rich)
            lo_l, hi_l, mid_l, real_l, d_l, band_l = [], [], [], [], [], []
            for at in range(MIN_HISTORY, n - FORWARD, STRIDE):
                k = where_of.get(at)
                if k is None:
                    continue
                got = envelope(book[k], at, book, forwards, ends)
                if got is None:
                    continue
                lo, mid, hi, tenth = got
                sd = float(rets[at - VOL_WINDOW + 1 : at + 1].std())
                if sd <= 0:
                    continue
                lo_l.append(lo)
                hi_l.append(hi)
                mid_l.append(mid)
                d_l.append(tenth)
                real_l.append(float(np.exp(rets[at + 1 : at + 1 + FORWARD].sum()) - 1.0) * 100.0)
                band_l.append(1.2816 * sd * math.sqrt(FORWARD) * 100.0)
            if len(real_l) < 500:
                continue
            real = np.array(real_l)
            low, high = np.array(lo_l), np.array(hi_l)
            below = float((real < low).mean())
            above = float((real > high).mean())
            total = below + above
            width = float(np.mean(high - low))
            # What a trailing-sigma band would have to be to exceed at the same rate, so
            # the comparison is like for like rather than a narrower band winning on width.
            band = np.array(band_l)
            equal = float(np.quantile(np.abs(real) / np.maximum(band / 1.2816, 1e-12), 1 - total))
            equal_width = float(np.mean(2 * equal * band / 1.2816))
            sign = float((np.sign(np.array(mid_l)) == np.sign(real)).mean())
            print(
                f"  {metric:<14}{len(real):>8,}{below:>8.1%}{above:>8.1%}{total:>8.1%}"
                f"{width:>8.2f}%{equal_width:>10.2f}%{sign:>8.1%}{np.median(d_l):>9.3f}"
            )
            if vol_rows is None:
                vol_below = float((real < -band).mean())
                vol_above = float((real > band).mean())
                vol_rows = (vol_below, vol_above, float(np.mean(2 * band)))
        if vol_rows:
            print(
                f"  {'trailing sigma':<14}{'':>8}{vol_rows[0]:>8.1%}{vol_rows[1]:>8.1%}"
                f"{vol_rows[0] + vol_rows[1]:>8.1%}{vol_rows[2]:>8.2f}%"
            )
        print(f"  {'nominal':<14}{'':>8}{0.10:>8.1%}{0.10:>8.1%}{0.20:>8.1%}")
        print(
            f"  two random {WINDOW}-bar shapes sit about {math.sqrt(2 * WINDOW):.3f} apart, "
            "so a small `10th d` means the search genuinely found twins\n"
        )

    print(
        "  **`total` against 20% is the calibration test**, and `equal-cov` is the width a\n"
        "  trailing-sigma band would need to exceed at the same rate - so the analogue only\n"
        "  earns its keep if `width` beats `equal-cov`, not if it beats the raw sigma band.\n"
        "\n  If every metric lands in the same place, the distance function is not what is\n"
        "  wrong: the twins are real and similarity simply does not predict."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
