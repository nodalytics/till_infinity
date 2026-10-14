"""The ideas behind the cycle theories, as two measurable claims.

Asked on 2026-10-14: *the ideas behind them we are looking at just the same way
we did for benner*. Benner's surface claim - a nine-year period - was untestable
on six repetitions; its **idea** - that durations carry information - was
testable on 25,918 transitions and came back as persistence rather than
periodicity. The same treatment applied to the rest of the list:

| framework | the mechanism | general form | where it is tested |
| --- | --- | --- | --- |
| Benner | durations carry information | duration distribution | `dwell.py` |
| Kitchin, Juglar | lagged negative feedback | damped oscillator | here, arm one |
| Kondratiev, 17.6y | rare structural shifts | over-dispersed dwell | `dwell.py`, CV |
| Gann | price and time commensurable | scaling exponent | here, arm two |
| BTC halving | scheduled known shock | exogenous `Q` input | `seasonal.py`, +197 nats |
| M2 liquidity | slow exogenous state | `inputs.py` channel | data absent |

## Arm one: does it oscillate, or only persist?

Kitchin's forty months and Juglar's seven-to-eleven years are the same
mechanism at different lags - a stock adjusted with a delay overshoots, and the
overshoot corrects. That mechanism is **scale-free**, which is what makes it
testable where the period is not: a delayed negative feedback produces
**negative autocorrelation at a characteristic lag**, and pure persistence
produces none at any lag.

So the claim is not "is there a forty-month cycle" but "is there a lag at which
this series reliably reverses". Measured on returns and on log volatility, at
lags from 2 to 512 bars, against the same series block-shuffled - which keeps
the marginal distribution and destroys the ordering an oscillation needs.

## Arm two: is price commensurable with time?

Gann squared price against time, which presumes a stable exchange rate between
them - a move of one unit per bar being a meaningful constant. That requires

    |price move| ~ horizon ** H   with H near 1

**Diffusion gives H = 0.5.** At a half, the ratio of move to time decays as
`1 / sqrt(horizon)`, so no fixed angle can hold at two horizons at once and
price-time squaring has no stable unit to work in. So Gann's apparatus needs a
scaling exponent near one, and the whole of it rests on a number this desk can
measure to three decimals.

`H` is estimated from the median absolute move against horizon, on a log-log
fit, which is the direct reading rather than a rescaled-range statistic - and
the block-shuffled control is the check that the estimator is not inventing an
exponent of its own.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import CONTROL, GENERATED, SEED, TRADED, shuffle_blocks  # noqa: E402
from screen import load  # noqa: E402

LAGS = (2, 4, 8, 16, 32, 64, 128, 256, 512)
HORIZONS = (1, 2, 4, 8, 16, 32, 64, 128, 256)


def autocorrelations(series: np.ndarray) -> dict[int, float]:
    """Autocorrelation at each lag. Negative at some lag is the oscillation."""
    out: dict[int, float] = {}
    middle = series - series.mean()
    base = float((middle * middle).mean())
    if not (base > 0):
        return out
    for lag in LAGS:
        if len(middle) <= lag + 10:
            continue
        out[lag] = float((middle[:-lag] * middle[lag:]).mean()) / base
    return out


def hurst(closes: np.ndarray) -> float:
    """`H` from the median absolute move against horizon, log-log.

    The median rather than the mean, because a single malformed bar moves a
    mean of absolute moves and this desk has seen a push of 22,415 volatility
    units in its own records.
    """
    logs = np.log(closes)
    xs: list[float] = []
    ys: list[float] = []
    for horizon in HORIZONS:
        if len(logs) <= horizon + 100:
            continue
        moves = np.abs(logs[horizon:] - logs[:-horizon])
        moves = moves[np.isfinite(moves) & (moves > 0)]
        if len(moves) < 100:
            continue
        xs.append(math.log(horizon))
        ys.append(math.log(float(np.median(moves))))
    if len(xs) < 4:
        return float("nan")
    slope, _ = np.polyfit(np.asarray(xs), np.asarray(ys), 1)
    return float(slope)


def arm(group: str, names: tuple[str, ...], rng) -> None:
    print("=" * 92)
    print(group)
    print("=" * 92)
    rows: dict[str, list[dict[int, float]]] = {"returns": [], "logvol": []}
    mixed: dict[str, list[dict[int, float]]] = {"returns": [], "logvol": []}
    exponents: list[float] = []
    shuffled_exponents: list[float] = []
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        for label, pool, source in (
            ("real", rows, bars),
            ("shuffled", mixed, shuffle_blocks(bars, rng)),
        ):
            closes = source["close"]
            rets = np.diff(np.log(closes))
            rets = rets[np.isfinite(rets)]
            if len(rets) < 2000:
                continue
            got = autocorrelations(rets)
            if got:
                pool["returns"].append(got)
            # Log volatility, where this desk's structure usually lives.
            window = 20
            squared = np.cumsum(rets**2)
            vol = np.sqrt((squared[window:] - squared[:-window]) / window)
            vol = vol[vol > 0]
            if len(vol) > 2000:
                got = autocorrelations(np.log(vol))
                if got:
                    pool["logvol"].append(got)
            h = hurst(closes)
            if math.isfinite(h):
                (exponents if label == "real" else shuffled_exponents).append(h)
    print("  ARM ONE  autocorrelation by lag - a negative value is the oscillation")
    print(f"    {'series':<10}{'arm':<10}" + "".join(f"{lag:>8}" for lag in LAGS))
    for which in ("returns", "logvol"):
        for label, pool in (("real", rows), ("shuffled", mixed)):
            found = pool[which]
            if not found:
                continue
            cells = []
            for lag in LAGS:
                vals = [d[lag] for d in found if lag in d]
                cells.append(f"{float(np.mean(vals)):>8.3f}" if vals else f"{'-':>8}")
            print(f"    {which:<10}{label:<10}" + "".join(cells))
    print(
        "      Kitchin and Juglar need a lag where the series reliably reverses.\n"
        "      Pure persistence is positive and decaying at every lag."
    )
    if exponents:
        print("\n  ARM TWO  scaling exponent H - Gann needs 1.0, diffusion gives 0.5")
        print(
            f"    real      H {float(np.mean(exponents)):.4f} "
            f"(sd {float(np.std(exponents)):.4f}, {len(exponents)} feeds)"
        )
        if shuffled_exponents:
            print(
                f"    shuffled  H {float(np.mean(shuffled_exponents)):.4f} "
                f"(sd {float(np.std(shuffled_exponents)):.4f})"
            )
        print(
            "      At H = 0.5 the ratio of move to time decays as 1/sqrt(horizon),\n"
            "      so no fixed angle holds at two horizons at once and price-time\n"
            "      squaring has no stable unit to work in."
        )
    print()


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        "The ideas behind the cycle theories, not their periods.\n"
        f"Lags {LAGS[0]} to {LAGS[-1]}, horizons {HORIZONS[0]} to {HORIZONS[-1]}.\n"
    )
    for group, names in (("traded", TRADED), ("control", CONTROL), ("generated", GENERATED)):
        arm(group, names, rng)


if __name__ == "__main__":
    main()
