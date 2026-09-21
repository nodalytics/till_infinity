"""Exits that do not use a stop, because the stop is what the costing showed you cannot pay.

Run from the repository root:  python research/harness/stopfree.py

`costs.md` ended the barrier programme. Every study in this repository resolved trades by
asking whether a bar's extreme reached the stop and then charged the loss as exactly 1 R,
and measuring how far past the stop the bar actually travelled gives 0.24 R on Boom and
0.29 R on gold - larger than any effect this research has ever found. The conclusion was
that the positive results are unreachable *with a stop*, not that they are false.

This tests the formulations that do not pay that cost.

## Why a stop slips and a target does not

The asymmetry is mechanical and it is the reason this is worth running. A stop is a
**market** order: it triggers when price touches a level and then fills at whatever is
available, which on a spike instrument is far away. A target is a **limit** order: it fills
at your price or better, or it does not fill. Limit orders do not slip.

So three exit styles are scored, and the middle one is the interesting case:

* **time** - hold exactly `N` bars and exit at the close. No stop, no target, no slippage
  beyond the spread already charged.
* **target or time** - a limit target, and a time exit if it never fills. Still no stop,
  so still no overshoot, but the upside is captured when it arrives.
* **target, stop and time** - the classical version, charged with the measured overshoot,
  carried here only as the comparison that makes the other two legible.

## The statistics change completely, and pretending otherwise would be the error

Without a stop there is no risk unit, so **`R` is undefined and every hit-rate-against-fair-
odds measurement in this repository stops applying**. `a / (a + b)` describes a first
passage between two barriers; with one barrier removed there is nothing for it to say.

What replaces it is the return distribution itself. Returns are measured in true ranges at
entry - dimensionless, comparable across instruments - and what matters is the mean against
the dispersion, plus the left tail, because an unstopped loss is unbounded and a mean that
looks good can sit in front of a ruinous 1st percentile. The 1st percentile is therefore
printed next to the mean and should be read first.

## Two traps this harness is built to avoid

**Overlapping windows.** Sampling an entry on every bar and holding 96 of them makes
neighbouring observations almost the same trade. The naive standard error is then far too
small and manufactures significance out of nothing. The point estimate here uses every
entry, because that is the efficient use of the data, but the error bar comes from a
**moving-block bootstrap with a block longer than the holding period**, which keeps the
overlap inside the blocks where it belongs.

**Drift masquerading as signal.** Boom rose 64.9% over these bars. Any rule that is long
Boom will look good on a long horizon for no reason but that, and any rule that is short
will look bad. So every conditional rule is scored **against the unconditional trade on the
same instrument, same side and same horizon**, and it is the difference that is reported.
A rule that does not beat simply always being in that direction has found nothing.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402
import changepoint  # noqa: E402
import imbalance  # noqa: E402
from net_edge import ANNUAL_SWAP, SPREAD_R  # noqa: E402

#: Holding periods, in bars. One bar to four days at hourly resolution.
HORIZONS = (1, 2, 3, 6, 12, 24, 48, 96)

#: Hours one bar covers, per interval. **Carry is charged per hour, not per bar**, so
#: without this a 5m run would be billed twelve times its real financing - which would
#: bury exactly the effect finer bars were downloaded to measure.
BAR_HOURS = {"1m": 1 / 60, "5m": 1 / 12, "15m": 0.25, "30m": 0.5, "1h": 1.0, "4h": 4.0}

#: Limit target for the "target or time" style, in true ranges.
TARGET = 1.0

#: Bootstrap resamples, and the block length as a multiple of the holding period.
DRAWS = 400
BLOCK = 3


def spread_for(symbol: str) -> float:
    for key, value in SPREAD_R.items():
        if key in symbol:
            return value
    return SPREAD_R["default"]


def signals(bars: np.ndarray, tr: np.ndarray) -> dict[str, tuple[np.ndarray, int]]:
    """Entry rules, each as `(bar indices, side)`.

    `always` is the benchmark every other rule is judged against, not a strategy.
    """
    series = changepoint.increments(bars, tr)
    up, down = changepoint.spikes(series)
    n = len(bars)
    every = np.arange(0, n)

    out: dict[str, tuple[np.ndarray, int]] = {
        "always long": (every, 1),
        "always short": (every, -1),
    }
    if len(up):
        out["fade ON spike"] = (up, -1)
        out["follow ON spike"] = (up, 1)
    if len(down):
        out["fade OFF spike"] = (down, 1)
        out["follow OFF spike"] = (down, -1)

    # The imbalance trade, which `imbalance.md` measured with a stop and which is the
    # natural candidate for re-testing without one.
    touches_up: list[int] = []
    touches_down: list[int] = []
    for gap in imbalance.gaps(bars, tr):
        _j, side, _edge, _disp, _wick = gap
        where = touches_up if side > 0 else touches_down
        where.extend(imbalance.touches(bars, gap, tr))
    if touches_up:
        out["gap edge, bull"] = (np.array(sorted(touches_up)), 1)
    if touches_down:
        out["gap edge, bear"] = (np.array(sorted(touches_down)), -1)
    return out


def returns(
    bars: np.ndarray, tr: np.ndarray, at: np.ndarray, side: int, horizon: int, style: str
) -> np.ndarray:
    """Trade returns in true ranges at entry, for one exit style.

    `target or time` fills the limit at exactly the target price, because a limit order
    fills at its price or better - that is the whole reason this style is here.
    """
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    n = len(bars)
    out: list[float] = []
    for raw in at:
        i = int(raw)
        if i + horizon >= n:
            continue
        entry = close[i]
        unit = tr[i] * max(entry, 1e-12)
        if unit <= 0:
            continue
        if style == "time":
            out.append(side * (close[i + horizon] - entry) / unit)
            continue
        # A limit target, checked bar by bar; no stop, so nothing can slip.
        target = entry + side * TARGET * unit
        filled = False
        for step in range(1, horizon + 1):
            j = i + step
            hit = high[j] >= target if side > 0 else low[j] <= target
            if hit:
                out.append(TARGET)
                filled = True
                break
        if not filled:
            out.append(side * (close[i + horizon] - entry) / unit)
    return np.array(out, dtype=float)


def block_error(values: np.ndarray, horizon: int) -> float:
    """Standard error of the mean from a moving-block bootstrap.

    The block is longer than the holding period so that overlapping trades stay inside a
    block. Using the plain standard error here would divide by a sample size the data does
    not have and would make almost every row look significant.
    """
    n = len(values)
    size = max(horizon * BLOCK, 10)
    if n < size * 3:
        return float("nan")
    starts = n - size
    rng = np.random.default_rng(0)
    count = int(np.ceil(n / size))
    means = np.empty(DRAWS)
    for d in range(DRAWS):
        picks = rng.integers(0, starts, size=count)
        drawn = np.concatenate([values[p : p + size] for p in picks])[:n]
        means[d] = drawn.mean()
    return float(means.std())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=["boom_1000_index", "crash_1000_index", "xauusd", "eurusd"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--style", default="time", choices=["time", "target or time"])
    ap.add_argument("--interval", default=os.environ.get("INTERVAL", "1h"))
    args = ap.parse_args()

    print(
        "returns in true ranges at entry; no stop, so there is no R and no fair-odds line\n"
        f"exit style: {args.style}\n"
        "\n  `vs always` is the rule minus the unconditional trade, same side and horizon -\n"
        "  the column that separates a signal from the instrument's own drift.\n"
        "  `p01` is the 1st percentile of the return distribution and should be read first:\n"
        "  an unstopped loss is unbounded.\n"
    )

    for symbol in args.symbols:
        found = sorted(
            Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_broker.csv.gz")
        )
        if not found:
            print(f"{symbol:<22} no file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < 5000:
            continue
        tr = candles.true_range(bars)
        rules = signals(bars, tr)
        cost = spread_for(symbol)
        annual = ANNUAL_SWAP.get(symbol, 0.0)
        tr_frac = float(np.median(tr[np.isfinite(tr) & (tr > 0)]))
        carry_day = (annual / 365.0 / 100.0) / tr_frac if tr_frac > 0 else 0.0

        print(f"\n{symbol}   spread {cost:.3f} TR, carry {carry_day:.3f} TR/day")
        print(
            f"  {'rule':<18}{'bars':>5}{'n':>8}{'gross':>8}{'net':>8}"
            f"{'+/-':>7}{'p01':>8}{'vs always':>11}"
        )
        for horizon in HORIZONS:
            base: dict[int, float] = {}
            for side in (1, -1):
                got = returns(bars, tr, rules["always long"][0], side, horizon, args.style)
                base[side] = float(got.mean()) if len(got) else 0.0
            for name, (where, side) in rules.items():
                got = returns(bars, tr, where, side, horizon, args.style)
                if len(got) < 200:
                    continue
                hours = horizon * BAR_HOURS.get(args.interval, 1.0)
                charge = cost + carry_day * hours / 24.0
                gross = float(got.mean())
                net = gross - charge
                err = block_error(got, horizon)
                edge = net - (base[side] - charge)
                mark = "  <-" if np.isfinite(err) and net > 2 * err else ""
                print(
                    f"  {name:<18}{horizon:>5}{len(got):>8,}{gross:>+8.3f}{net:>+8.3f}"
                    f"{2 * err if np.isfinite(err) else float('nan'):>7.3f}"
                    f"{np.percentile(got, 1):>8.2f}{edge:>+11.3f}{mark}"
                )

    print(
        "\n  A marked row beats zero by two bootstrap standard errors. That is not enough\n"
        "  on its own: `vs always` has to be positive too, or the rule is capturing the\n"
        "  instrument's drift and could be replaced by holding.\n"
        "\n  Read p01 against the mean. A rule with +0.02 mean and -6 p01 is selling\n"
        "  insurance, and the premium arrives long before the claim."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
