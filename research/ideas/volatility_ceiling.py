"""Closing the gap on volatility, with every horizon in time rather than in bars.

**Converted 2026-10-11, and the conversion is the point of this version.** The
first run of this harness counted bars: a twenty-bar window, HAR spans of
5/22/110 bars, horizons of 1/5/20 bars. Stated that way a span is a span *times
a timeframe* - `har (5/22/110)` is 1.25h, 5.5h and 27h at 15m and 5d, 22d and
110d at 1d - so its headline result, that HAR-Parkinson wins intraday and loses
on daily bars, **had a confound in it**: the estimators being compared across
timeframes were not the same estimators.

`statespace/__init__.py` now carries this as a package rule and the statespace
modules obey it. This harness did not, so it does now: windows and horizons are
hours, converted per series from its own median bar spacing and trading
coverage.

It also **uses** the library rather than reimplementing it. `parkinson`,
`garman_klass`, `har`, `rolling` and `ema` moved into
`statespace/inputs.py` with tests; a harness that kept its own copies would be
measuring code nobody else runs.

## What is being measured, unchanged

Each estimator is a **variance**, aggregated in variance with the root taken
once - the Cboe lesson. They are scored against the realised future move by the
share of the oracle's quintile spread they capture, and against the only honest
denominator: what a **perfect** sigma could capture, which is far below the
oracle because a realised move is `sigma * z` and `|z|` is unforecastable. On
eurusd that ceiling is 10.8% of the oracle at 15m, so the baseline's 6.9% was
never 11% of achievable - it was 64% of it.

Runs on the lab. Production has two cores and a 2.6GB container limit, and
research on it OOM-killed the live desk three times - see `research/starving.md`.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.statespace.inputs import (
    bar_hours,
    coverage,
    garman_klass,
    har,
    parkinson,
    rolling,
)

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)
FRAMES = ("15m", "1h", "1d")

#: Forecast horizons in **hours**. "The next four hours" means the same thing on
#: every series; "the next twenty bars" does not.
HORIZONS = (1.0, 4.0, 24.0)

#: The estimator's own lookback, in hours. Five hours rather than twenty bars,
#: which was five hours at 15m and twenty days at 1d.
LOOKBACK = float(os.environ.get("LOOKBACK", "5.0"))

#: HAR's three spans, in hours. The literature's 1 day / 1 week / 1 month on
#: daily data, stated as the time it is rather than the bar counts it was.
HAR_HOURS = (24.0, 5 * 24.0, 22 * 24.0)

#: RiskMetrics' decay, per **hour** of half-life rather than per observation.
#: `lambda = 0.94` on daily data is a half-life near 11 days; that is what is
#: held fixed here, and the per-bar decay is derived from it.
EWMA_HALFLIFE = 11 * 24.0

LIMIT = int(os.environ.get("LIMIT", "20000"))


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        keys = set(bundle.keys())
        if not {"time", "open", "high", "low", "close"} <= keys:
            return None
        order = np.argsort(bundle["time"])
        got = {
            k: bundle[k][order].tolist()
            for k in ("time", "open", "high", "low", "close")
        }
        got["volume"] = (
            bundle["volume"][order].tolist() if "volume" in keys else [0.0] * len(order)
        )
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def spearman(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 30:
        return 0.0

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        for rank, i in enumerate(order):
            out[i] = float(rank)
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(
        sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)
    )
    return num / den if den > 0 else 0.0


def captured(forecast: list[float], truth: list[float]) -> float:
    """Share of the oracle's quintile spread this forecast captures."""
    n = len(forecast)
    if n < 100:
        return 0.0
    paired = list(zip(forecast, truth, strict=True))

    def spread(ordered):
        lo = statistics.fmean(p[1] for p in ordered[: n // 5])
        hi = statistics.fmean(p[1] for p in ordered[4 * n // 5 :])
        return hi / max(lo, 1e-12)

    got = spread(sorted(paired, key=lambda p: p[0]))
    ceiling = spread(sorted(paired, key=lambda p: p[1]))
    return (got - 1.0) / max(ceiling - 1.0, 1e-12)


def achievable(sigma: list[float], seed: int = 20261011) -> float:
    """What a **perfect** sigma could capture. The honest denominator.

    A realised move is `sigma * z` with `z` a fresh standard normal, and `|z|`
    is unforecastable, so the oracle's ceiling is mostly irreducible noise. Take
    the fitted sigma as truth, draw from it, and ask what share of *that* oracle
    a perfect sigma gets.
    """
    import random

    rng = random.Random(seed)
    usable = [math.sqrt(v) for v in sigma if v > 0]
    if len(usable) < 200:
        return float("nan")
    drawn = [s * rng.gauss(0.0, 1.0) for s in usable]
    return captured(usable, [abs(d) for d in drawn])


def estimators(bars: dict, bar: float, cover: float) -> dict[str, list[float]]:
    """Every forecast as a variance series, with spans converted from hours.

    `bar` and `cover` come from the series itself, so a span of five hours is
    five hours of trading on every one of them.
    """
    close, high, low, open_ = bars["close"], bars["high"], bars["low"], bars["open"]
    volume = bars["volume"]
    n = len(close)

    def spans(hours: float) -> int:
        return max(round(hours * max(cover, 1e-9) / bar), 2)

    moves = [0.0] + [
        math.log(close[k] / close[k - 1]) if close[k - 1] > 0 and close[k] > 0 else 0.0
        for k in range(1, n)
    ]
    squares = [m * m for m in moves]
    park_bar = parkinson(high, low)
    gk_bar = garman_klass(open_, high, low, close)
    window = spans(LOOKBACK)

    out: dict[str, list[float]] = {}

    # The baseline, in its own L1 unit, squared so it can sit in a variance
    # table. This is the estimator everything else has to beat.
    flat = rolling([abs(m) for m in moves], window)
    out["baseline mean|r|"] = [v * v for v in flat]

    out["realised variance"] = rolling(squares, window)
    out["parkinson (high-low)"] = rolling(park_bar, window)
    out["garman-klass (ohlc)"] = rolling(gk_bar, window)

    # EWMA with a **time** half-life, so the decay is the same per hour on
    # every series rather than the same per bar.
    decay = 0.5 ** (bar / max(EWMA_HALFLIFE, 1e-9))
    ewma = [0.0] * n
    run = squares[1] if n > 1 else 0.0
    for k in range(1, n):
        run = decay * run + (1.0 - decay) * squares[k]
        ewma[k] = run
    out[f"ewma halflife={EWMA_HALFLIFE / 24:g}d"] = ewma

    triple = tuple(spans(h) for h in HAR_HOURS)
    out[f"har {'/'.join(f'{h / 24:g}d' for h in HAR_HOURS)}"] = har(squares, triple)
    out["har-parkinson"] = har(park_bar, triple)

    # Amihud needs real traded size, which a CFD volume is not - it is a tick
    # count. Kept to record that rather than to expect anything.
    if sum(1 for v in volume if v and v > 0) > n * 0.5:
        ratio = [
            abs(moves[k]) / volume[k] if volume[k] and volume[k] > 0 else 0.0
            for k in range(n)
        ]
        out["amihud |r|/volume"] = rolling(ratio, window)

    # Roll's implied spread, from the serial covariance of price changes.
    roll = [0.0] * n
    for k in range(window + 1, n):
        recent = moves[k - window + 1 : k + 1]
        mean = statistics.fmean(recent)
        cov = statistics.fmean(
            (recent[i] - mean) * (recent[i - 1] - mean) for i in range(1, len(recent))
        )
        roll[k] = 2.0 * math.sqrt(-cov) if cov < 0 else 0.0
    out["roll implied spread"] = [v * v for v in roll]

    return out


def main() -> None:
    print("Volatility, with every window and horizon in HOURS rather than bars.")
    print(f"lookback {LOOKBACK:g}h, HAR {'/'.join(f'{h / 24:g}d' for h in HAR_HOURS)},")
    print(f"horizons {'/'.join(f'{h:g}h' for h in HORIZONS)}.")
    print("'captured' is the share of what a PERFECT sigma could capture.\n")

    for label, stem in SYMBOLS:
        for frame in FRAMES:
            bars = load(stem, frame)
            if bars is None or len(bars["close"]) < 1000:
                continue
            times, close = bars["time"], bars["close"]
            bar = bar_hours(times)
            cover = coverage(times, bar)
            if bar <= 0:
                continue
            n = len(close)
            got = estimators(bars, bar, cover)
            ceiling = achievable(got["har-parkinson"])

            print(f"=== {label} {frame}: {n} bars, bar={bar:g}h, coverage={cover:.3f} ===")
            print(f"  a perfect sigma captures {ceiling:.1%} of the realised-move oracle")
            if ceiling < 0.02:
                print("  * too small to divide by: cells show the RAW share of the oracle")
            print(f"  {'estimator':<26}" + "".join(f"{f'{h:g}h':>18}" for h in HORIZONS))
            for name, series in got.items():
                cells = []
                for hours in HORIZONS:
                    ahead = max(round(hours * cover / bar), 1)
                    forecast, truth = [], []
                    start = max(round(max(HAR_HOURS) * cover / bar), 50)
                    for k in range(start, n - ahead):
                        if series[k] <= 0:
                            continue
                        forecast.append(series[k])
                        truth.append(abs(close[k + ahead] / close[k] - 1.0))
                    if len(forecast) < 200:
                        cells.append(f"{'-':>18}")
                        continue
                    share = captured(forecast, truth)
                    rho = spearman(forecast, truth)
                    # **Guard the denominator.** Where a perfect sigma captures
                    # almost nothing - v75's ceiling is 0.5%, because its
                    # generated volatility does not autocorrelate - dividing by
                    # it turns noise into "-176% of achievable", which is not a
                    # number anyone should read. Report the raw share there and
                    # mark it.
                    if not (ceiling == ceiling) or ceiling < 0.02:
                        cells.append(f"{share:>10.1%}* rho{rho:>+5.2f}")
                    else:
                        cells.append(f"{share / ceiling:>11.0%} rho{rho:>+5.2f}")
                print(f"  {name:<26}" + "".join(cells))
            print()


if __name__ == "__main__":
    main()
