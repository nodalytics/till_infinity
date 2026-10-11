"""Close the gap on the one quantity that is forecastable. Baseline captures 11%.

The oracle harness measured a ceiling and how little of it is reached: ranking by
a twenty-bar mean absolute move captures **10.7% to 13.4%** of the dispersion a
perfect volatility forecast would capture. Direction is a coin in every test here;
volatility is not. So the whole of the available improvement is in this one place,
and it is a seven-to-nine-fold gap rather than a few percent.

## Five things the baseline is doing wrong, each with a fix

**1. It aggregates in the wrong unit.** The Cboe methodology blends *variances*,
weighted by time, and takes the square root **once at the end**. The baseline
averages absolute moves, which is an L1 measure that does not add over time - so
combining horizons with it is not an approximation of the right thing, it is a
different thing. `rv` here is `sqrt(mean(move^2))`.

**2. It throws away the high and the low.** A close-to-close estimator sees two
numbers a bar; the bar also has a high and a low, and the range carries far more
information about how far price travelled. Parkinson's estimator is around five
times as efficient as close-to-close for the same sample, and Garman-Klass adds
the open. **The data has had `high` and `low` all along and no estimator here has
used them.**

**3. It weights every one of its twenty bars equally.** A flat window says a bar
twenty ago matters as much as the last one and a bar twenty-one ago not at all.
An exponential weighting says neither. RiskMetrics' `lambda = 0.94` is the
standard to beat.

**4. It uses one lookback.** Volatility has structure at several time scales, and
Corsi's HAR-RV exploits exactly that: regress future realised variance on a
short, a medium and a long realised variance together. It is the standard
benchmark in this literature and it is hard to beat, which is the point of
including it.

**5. It ignores liquidity, which is the other thing the desk has been reading
about.** Two measures from the microstructure literature need no order book:
**Amihud illiquidity**, `|return| / volume`, and **Roll's implied spread**,
`2*sqrt(-cov(dp_t, dp_t-1))` when that covariance is negative. Illiquidity
predicts volatility, and both are computable from what the seqlab files already
carry.

## How this is scored

Against the oracle, exactly as before, so the numbers are comparable to the
10.7% already on record: rank the bars by each forecast, rank them by the
realised future move, and report what share of the oracle's quintile spread the
forecast captures. Plus Spearman rank correlation against the realised move,
which is the same question without the bucketing.

**Variance, not volatility, is regressed and blended** throughout - the root is
taken once, where it is reported.

Runs on the lab. Production has two cores and a 2.6GB container limit, and
research on it OOM-killed the live desk three times - see `research/starving.md`.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)
FRAMES = ("15m", "1h", "1d")
HORIZONS = (1, 5, 20)

LIMIT = int(os.environ.get("LIMIT", "20000"))

#: RiskMetrics' decay. Not fitted, so it is a benchmark rather than a result.
LAMBDA = 0.94


def load(stem: str, frame: str):
    """`(times, open, high, low, close, volume)`."""
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        keys = set(bundle.keys())
        if not {"time", "open", "high", "low", "close"} <= keys:
            return None
        order = np.argsort(bundle["time"])
        got = {k: bundle[k][order].tolist() for k in ("time", "open", "high", "low", "close")}
        got["volume"] = bundle["volume"][order].tolist() if "volume" in keys else [0.0] * len(order)
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation. The bucketing-free version of the same question."""
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


def captured(forecast: list[float], truth: list[float]) -> tuple[float, float, float]:
    """`(share of the oracle's spread, forecast spread, oracle spread)`.

    The same metric the oracle harness used, so 10.7% stays comparable.
    """
    n = len(forecast)
    if n < 100:
        return 0.0, 0.0, 0.0
    paired = list(zip(forecast, truth, strict=True))
    by_guess = sorted(paired, key=lambda p: p[0])
    by_truth = sorted(paired, key=lambda p: p[1])

    def spread(ordered):
        lo = statistics.fmean(p[1] for p in ordered[: n // 5])
        hi = statistics.fmean(p[1] for p in ordered[4 * n // 5 :])
        return hi / max(lo, 1e-12)

    got, ceiling = spread(by_guess), spread(by_truth)
    share = (got - 1.0) / max(ceiling - 1.0, 1e-12)
    return share, got, ceiling


def estimators(bars: dict, window: int = 20) -> dict[str, list[float]]:
    """Every forecast, as a **variance** series aligned to each bar.

    Each entry at index `k` uses bars up to and including `k` and nothing after
    it. Returned as variances; the root is taken once, when reported.
    """
    close = bars["close"]
    high, low, open_ = bars["high"], bars["low"], bars["open"]
    volume = bars["volume"]
    n = len(close)

    moves = [0.0] + [
        math.log(close[k] / close[k - 1]) if close[k - 1] > 0 and close[k] > 0 else 0.0
        for k in range(1, n)
    ]
    squares = [m * m for m in moves]

    out: dict[str, list[float]] = {}

    # 0. the baseline, in its own L1 unit, squared only so it can sit in a
    #    variance table. This is what captured 10.7%.
    flat_abs = [0.0] * n
    run = 0.0
    for k in range(1, n):
        if k <= window:
            run = statistics.fmean(abs(m) for m in moves[1 : k + 1])
        else:
            run += (abs(moves[k]) - abs(moves[k - window])) / window
        flat_abs[k] = run
    out["baseline mean|r|"] = [v * v for v in flat_abs]

    # 1. realised variance: the same window, aggregated in the right unit.
    rv = [0.0] * n
    run = 0.0
    for k in range(1, n):
        if k <= window:
            run = statistics.fmean(squares[1 : k + 1])
        else:
            run += (squares[k] - squares[k - window]) / window
        rv[k] = run
    out["realised variance"] = list(rv)

    # 2. exponentially weighted, RiskMetrics.
    ewma = [0.0] * n
    run = squares[1] if n > 1 else 0.0
    for k in range(1, n):
        run = LAMBDA * run + (1.0 - LAMBDA) * squares[k]
        ewma[k] = run
    out[f"ewma lambda={LAMBDA}"] = ewma

    # 3. Parkinson: the high-low range, which the baseline never looked at.
    #    `(1/(4 ln 2)) * mean(ln(high/low)^2)`.
    park_bar = [
        (math.log(high[k] / low[k]) ** 2) / (4.0 * math.log(2.0))
        if high[k] > 0 and low[k] > 0 and high[k] >= low[k]
        else 0.0
        for k in range(n)
    ]
    park = [0.0] * n
    run = 0.0
    for k in range(1, n):
        if k <= window:
            run = statistics.fmean(park_bar[1 : k + 1])
        else:
            run += (park_bar[k] - park_bar[k - window]) / window
        park[k] = run
    out["parkinson (high-low)"] = park

    # 4. Garman-Klass, which adds the open.
    gk_bar = []
    for k in range(n):
        if high[k] > 0 and low[k] > 0 and open_[k] > 0 and close[k] > 0 and high[k] >= low[k]:
            hl = math.log(high[k] / low[k])
            co = math.log(close[k] / open_[k])
            gk_bar.append(0.5 * hl * hl - (2.0 * math.log(2.0) - 1.0) * co * co)
        else:
            gk_bar.append(0.0)
    gk = [0.0] * n
    run = 0.0
    for k in range(1, n):
        if k <= window:
            run = statistics.fmean(gk_bar[1 : k + 1])
        else:
            run += (gk_bar[k] - gk_bar[k - window]) / window
        gk[k] = max(run, 0.0)
    out["garman-klass (ohlc)"] = gk

    # 5. HAR: a short, a medium and a long realised variance, blended. The
    #    weights are the literature's equal-ish starting point rather than a
    #    fit, so this is a benchmark and not a tuned model.
    def rolling(source: list[float], span: int) -> list[float]:
        got = [0.0] * n
        run = 0.0
        for k in range(1, n):
            if k <= span:
                run = statistics.fmean(source[1 : k + 1])
            else:
                run += (source[k] - source[k - span]) / span
            got[k] = run
        return got

    short, medium, long = rolling(squares, 5), rolling(squares, 22), rolling(squares, 110)
    out["har (5/22/110)"] = [
        (short[k] + medium[k] + long[k]) / 3.0 for k in range(n)
    ]

    # 6. Parkinson at three scales, the same idea on the better estimator.
    p5, p22, p110 = rolling(park_bar, 5), rolling(park_bar, 22), rolling(park_bar, 110)
    out["har-parkinson"] = [(p5[k] + p22[k] + p110[k]) / 3.0 for k in range(n)]

    # 7. Amihud illiquidity: |return| / volume. Needs real volume, which not
    #    every venue reports - `context/activity.py` records that at length.
    amihud = [0.0] * n
    usable = sum(1 for v in volume if v and v > 0) > n * 0.5
    if usable:
        ratio = [
            abs(moves[k]) / volume[k] if volume[k] and volume[k] > 0 else 0.0
            for k in range(n)
        ]
        amihud = rolling(ratio, window)
    out["amihud |r|/volume"] = amihud

    # 8. Roll's implied spread from the serial covariance of price changes.
    #    Only defined where that covariance is negative, which is the bid-ask
    #    bounce it is measuring.
    roll = [0.0] * n
    for k in range(window + 1, n):
        window_moves = moves[k - window + 1 : k + 1]
        mean = statistics.fmean(window_moves)
        cov = statistics.fmean(
            (window_moves[i] - mean) * (window_moves[i - 1] - mean)
            for i in range(1, len(window_moves))
        )
        roll[k] = 2.0 * math.sqrt(-cov) if cov < 0 else 0.0
    out["roll implied spread"] = [v * v for v in roll]

    return out


def achievable(sigma: list[float], seed: int = 20261011) -> float:
    """What share of the oracle a **perfect** variance forecast could capture.

    **This is the number that was missing, and without it the gap was
    overstated.** The oracle ranks bars by the *realised* future move, and a
    realised move is `sigma * z` where `z` is a fresh standard normal. `z` is
    unforecastable by construction, so even perfect knowledge of `sigma` cannot
    reproduce the oracle's ordering - the ceiling it measures includes
    irreducible noise.

    So "the baseline captures 10.7% of the oracle" does **not** imply that nine
    tenths is available. This estimates how much actually is: take the fitted
    `sigma` as if it were the truth, draw `sigma * z` from it, and ask what
    share of *that* oracle a perfect `sigma` captures. The honest denominator
    for every other row in the table.
    """
    import random

    rng = random.Random(seed)
    usable = [math.sqrt(v) for v in sigma if v > 0]
    if len(usable) < 200:
        return float("nan")
    drawn = [s * rng.gauss(0.0, 1.0) for s in usable]
    share, _got, _ceiling = captured(usable, [abs(d) for d in drawn])
    return share


def main() -> None:
    print("Closing the gap on volatility. The baseline captures 10.7% of the ceiling.")
    print("All estimators are variances; the root is taken once, at reporting.")
    print("'captured' is the share of the oracle's quintile spread, so it is")
    print("directly comparable to the 10.7% already on record.\n")

    for label, stem in SYMBOLS:
        for frame in FRAMES:
            bars = load(stem, frame)
            if bars is None or len(bars["close"]) < 1000:
                continue
            close = bars["close"]
            n = len(close)
            moves = [0.0] + [
                math.log(close[k] / close[k - 1]) if close[k - 1] > 0 else 0.0
                for k in range(1, n)
            ]
            got = estimators(bars)
            print(f"=== {label} {frame}: {n} bars ===")
            # The honest denominator: what a perfect sigma could capture.
            ceiling = achievable(got["har-parkinson"])
            print(f"  a PERFECT sigma forecast would capture {ceiling:.1%} of the"
                  f" realised-move oracle - that is the real denominator")
            print(f"  {'estimator':<24}" + "".join(f"{f'h={h}':>24}" for h in HORIZONS))
            print(f"  {'(of oracle / of achievable)':<24}")
            for name, series in got.items():
                if all(v == 0.0 for v in series):
                    print(f"  {name:<24}" + f"{'(no data)':>24}" * len(HORIZONS))
                    continue
                cells = []
                for horizon in HORIZONS:
                    forecast, truth = [], []
                    for k in range(130, n - horizon):
                        if series[k] <= 0:
                            continue
                        forecast.append(series[k])
                        truth.append(abs(close[k + horizon] / close[k] - 1.0))
                    if len(forecast) < 200:
                        cells.append(f"{'-':>24}")
                        continue
                    share, _mine, _ceiling = captured(forecast, truth)
                    rho = spearman(forecast, truth)
                    # Both: the raw share, and the share of what is achievable.
                    reach = share / ceiling if ceiling and ceiling == ceiling else float("nan")
                    cells.append(f"{share:>8.1%}/{reach:>6.0%} rho{rho:>+6.2f}")
                print(f"  {name:<24}" + "".join(cells))
            print()


if __name__ == "__main__":
    main()
