"""How large should a position be, from the book's own realised returns.

Run from the repository root, against a file of realised R multiples:

    python research/harness/sizing_kelly.py --from /path/to/live-r.csv

Every number in this repository is **per-trade expectancy**, and expectancy does not say how
much to bet. A positive edge sized too large still goes to zero, and the sizing question has
never been asked here at all - `trading/sizing.py` implements a risk fraction and nothing has
ever checked whether the configured value is the right one.

The input is the live journal's `r_multiple` on closed trades, not a backtest. That matters:
these are realised fills including the slippage, the spread and the swap that
`costs.md` spent a day measuring, so the distribution already contains every cost rather than
needing them modelled on top.

**The data file is deliberately not committed.** It is live account history and this
repository is public; the path is an argument and the file belongs outside the tree.

## What is computed, and why not the textbook formula

The growth-optimal fraction maximises the expected log of wealth. For a bet returning `R`
multiples of the fraction risked,

    g(f) = E[ log(1 + f R) ]

and `f*` is where that peaks. This is solved **numerically over the empirical distribution**
rather than from the Gaussian `mu / sigma^2` approximation, and the reason is the shape of the
data: realised R has a hard floor near -1 with a tail beyond it and a long right tail from
runners. A mean/variance formula on a distribution like that can be out by a factor of two
and will always err optimistically, because it cannot see that one draw near `-1/f` sets
`g(f)` to negative infinity.

The floor is what bounds `f`. With a worst realised loss of `L`, any `f > 1/L` is ruin on a
single repeat of it, whatever the mean says.

## Three fractions are reported, and the gap between them is the point

* **full Kelly** maximises growth and is unusable - its drawdowns are violent by construction;
* **half Kelly** gives about three quarters of the growth for roughly half the drawdown, which
  is the standard practitioner's compromise and the number worth comparing against;
* **the configured fraction**, read from the environment, so the answer is about this book
  rather than about Kelly.

## Concurrency, which the per-trade answer ignores

A per-trade Kelly assumes bets resolve one at a time. This book runs up to
`TRADING_MAX_POSITIONS` at once, so the quantity that can actually ruin it is the **aggregate**
exposure, and correlated instruments make that larger than the count suggests.

So the same calculation is run twice: on single trades, and on **daily aggregates** of realised
R. The daily version needs no correlation model because the correlation is already in the
realised sums - if the book's positions move together, the daily totals are more dispersed than
independence would give, and the aggregate Kelly comes out smaller. Comparing the two is a
direct read on how much concurrency is costing.

## Drawdown, by bootstrap rather than formula

Analytic drawdown bounds assume a distribution this data does not have. Instead equity paths
are resampled in **blocks**, which keeps any streakiness in the realised order, and the
distribution of maximum drawdown is reported per fraction. A median drawdown is not the
interesting number; the 95th percentile is, because that is the one that closes an account.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from collections import defaultdict
from pathlib import Path

import numpy as np

#: Fractions of the growth-optimal point to report alongside it.
SHARES = (1.0, 0.5, 0.25)

#: Bootstrap paths and the block length, in trades, for the drawdown distribution.
PATHS = 2000
BLOCK = 20

#: Search grid for the growth-optimal fraction.
GRID = np.concatenate([np.linspace(0.0, 0.05, 251), np.linspace(0.05, 1.0, 191)])


def load(path: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Realised R multiples, their timestamps, and their symbols."""
    times, values, symbols = [], [], []
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                r = float(row["r_multiple"])
                t = int(row.get("time") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if not math.isfinite(r):
                continue
            times.append(t)
            values.append(r)
            symbols.append(str(row.get("symbol") or "?"))
    order = np.argsort(times, kind="stable")
    return np.array(values)[order], np.array(times)[order], [symbols[i] for i in order]


def growth(values: np.ndarray, f: float) -> float:
    """Expected log growth per bet at fraction `f`, or -inf if any draw ruins it."""
    wealth = 1.0 + f * values
    if np.any(wealth <= 0):
        return -np.inf
    return float(np.mean(np.log(wealth)))


def optimal(values: np.ndarray) -> tuple[float, float]:
    """The growth-optimal fraction and its growth per bet."""
    best_f, best_g = 0.0, 0.0
    for f in GRID:
        g = growth(values, float(f))
        if g > best_g:
            best_f, best_g = float(f), g
    return best_f, best_g


def drawdowns(values: np.ndarray, f: float, seed: int = 0) -> tuple[float, float, float]:
    """Median, 95th and worst maximum drawdown over bootstrapped equity paths.

    Blocks rather than single draws, so a run of losses that actually happened can happen
    again in a path - an independent resample quietly removes the streaks that cause the
    drawdowns being measured.
    """
    if f <= 0:
        return 0.0, 0.0, 0.0
    n = len(values)
    if n < BLOCK * 3:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    count = int(np.ceil(n / BLOCK))
    worst = np.empty(PATHS)
    for p in range(PATHS):
        picks = rng.integers(0, n - BLOCK, size=count)
        drawn = np.concatenate([values[i : i + BLOCK] for i in picks])[:n]
        wealth = 1.0 + f * drawn
        if np.any(wealth <= 0):
            worst[p] = 1.0
            continue
        curve = np.cumprod(wealth)
        worst[p] = float(1.0 - np.min(curve / np.maximum.accumulate(curve)))
    return (
        float(np.median(worst)),
        float(np.quantile(worst, 0.95)),
        float(np.max(worst)),
    )


def describe(name: str, values: np.ndarray, configured: float) -> None:
    n = len(values)
    if n < 15:
        print(f"\n{name}: only {n} observations - nothing can be said")
        return
    thin = n < 60
    mean, sd = float(values.mean()), float(values.std(ddof=1))
    worst = float(values.min())
    ruin_at = (1.0 / abs(worst)) if worst < 0 else float("inf")
    f_star, _g_star = optimal(values)

    print(f"\n{name}  -  {n:,} observations")
    if thin:
        # Reported anyway: for a book running dozens of concurrent trades this is the
        # binding statistic, and the fact that there is barely any of it is the finding.
        print(
            "  **too few to size from.** Shown because this is the statistic that binds and\n"
            "  its scarcity is itself the answer - see the note at the end."
        )
    print(
        f"  mean {mean:+.4f} R   sd {sd:.4f}   "
        f"per-bet Sharpe {mean / sd if sd > 0 else 0:+.4f}   worst {worst:+.3f} R"
    )
    print(f"  a single repeat of the worst loss ruins any fraction above {ruin_at:.3f}")
    if mean <= 0:
        print(
            "  **mean is not positive, so the growth-optimal fraction is zero.** No sizing\n"
            "  rescues a non-positive edge; the only correct bet is none."
        )
    print(
        f"\n  {'fraction':<22}{'of Kelly':>9}{'growth/bet':>12}"
        f"{'med DD':>9}{'p95 DD':>9}{'worst DD':>10}"
    )
    rows = [(f"Kelly x {s:g}", s, f_star * s) for s in SHARES]
    rows.append(("configured", (configured / f_star) if f_star > 0 else float("nan"), configured))
    for label, share, f in rows:
        if not math.isfinite(f) or f <= 0:
            print(f"  {label:<22}{'-':>9}{'-':>12}{'-':>9}{'-':>9}{'-':>10}")
            continue
        med, p95, mx = drawdowns(values, f)
        g = growth(values, f)
        share_txt = f"{share:.2f}x" if math.isfinite(share) else "-"
        print(
            f"  {label + f' = {f:.4f}':<22}{share_txt:>9}{g:>+12.5f}"
            f"{med:>9.1%}{p95:>9.1%}{mx:>10.1%}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="source", required=True, help="CSV of realised r_multiple")
    ap.add_argument(
        "--configured",
        type=float,
        default=float(os.environ.get("TRADING_RISK_FRACTION", "0.005")),
        help="the book's current risk fraction, for comparison",
    )
    args = ap.parse_args()

    values, times, _symbols = load(Path(args.source))
    if not len(values):
        print("nothing to read")
        return 1

    print(
        "sized against realised R multiples from the live journal, so every cost measured\n"
        "in costs.md is already inside these numbers rather than modelled on top.\n"
        f"configured risk fraction: {args.configured:.4f}"
    )

    describe("per trade", values, args.configured)

    # Daily aggregates, which carry the concurrency and the correlation as realised.
    by_day: dict[int, float] = defaultdict(float)
    for t, r in zip(times, values, strict=True):
        by_day[t // 86400] += float(r)
    daily = np.array([by_day[k] for k in sorted(by_day)])
    describe("per day, aggregated", daily, args.configured)

    print(
        f"\n  {len(daily):,} trading days, {len(values) / max(len(daily), 1):.1f} trades a day,\n"
        f"  worst day {daily.min():+.2f} R, best {daily.max():+.2f} R"
    )
    print(
        "\n  The per-day rows are the ones that bind. A per-trade Kelly assumes bets resolve\n"
        "  one at a time; this book runs many at once, and if its positions move together the\n"
        "  daily totals are more dispersed than independence would give - which shows up as a\n"
        "  smaller optimal fraction. The gap between the two blocks is what concurrency costs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
