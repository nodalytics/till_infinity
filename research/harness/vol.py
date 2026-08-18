"""How well does the volatility estimate predict the next move?

Every threshold in this project is denominated in volatility units. `resolve_vol`
is 1.5 of them, `MIN_ZONE_VOL` is 0.35, `KEEP_VOL` is 8. If the denominator is
wrong the whole scale is wrong, and nobody has ever checked it.

`Volatility` is an exponentially weighted **mean absolute return**, so the claim
it makes is precise and testable: the next bar's absolute return should be about
`bps`, on average. Not the standard deviation — the mean absolute deviation, and
those differ by a factor of 1.25 for a normal (see `timing.MAD_TO_SIGMA`, which
is a mistake this project has already made once).

Strictly walk-forward: the estimate is read **before** the bar it is judged on,
and the bar is folded in afterwards. Compared against three baselines a forecast
has to beat to be worth anything:

  last        the previous bar's absolute return — the naive persistence forecast
  rolling20   a flat mean of the last twenty
  constant    each series' own long-run mean, which knows the future and is
              therefore a ceiling rather than a competitor
"""

from __future__ import annotations

import math
import sqlite3
import statistics
import sys
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from till_infinity.structures.volatility import Volatility

DB = ".data/prices/prices.db"  # run from the repository root
INTERVALS = ("1m", "5m", "15m", "1h", "1d")


def series():
    """One consensus close series per (ticker, interval), oldest first."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    marks = ",".join("?" * len(INTERVALS))
    rows = conn.execute(
        f"select ticker, interval, ts, close from bars where interval in ({marks})"
        " order by ticker, interval, ts",
        INTERVALS,
    )
    out = defaultdict(list)
    for ticker, interval, ts, close in rows:
        if close:
            out[(ticker, interval)].append((ts, float(close)))
    return out


def main() -> None:
    found = series()
    print(f"{len(found)} series\n")

    per_interval = defaultdict(lambda: defaultdict(list))
    for (ticker, interval), points in found.items():
        if len(points) < 300:
            continue
        vol = Volatility()
        recent: deque[float] = deque(maxlen=20)
        previous = points[0][1]
        vol.update(previous)
        for _ts, close in points[1:]:
            if not previous:
                previous = close
                continue
            realised = abs((close - previous) / previous * 10_000)
            # Read before the bar is folded in — this is the forecast.
            if vol.warm and recent:
                per_interval[interval]["model"].append((vol.bps, realised))
                per_interval[interval]["last"].append((recent[-1], realised))
                per_interval[interval]["rolling20"].append((statistics.fmean(recent), realised))
            recent.append(realised)
            vol.update(close)
            previous = close

    print(
        "%-6s %-11s %7s %9s %9s %8s %8s"
        % ("iv", "forecast", "n", "mean pred", "mean real", "ratio", "corr")
    )
    print("-" * 66)
    for interval in INTERVALS:
        rows = per_interval.get(interval)
        if not rows:
            continue
        for name in ("model", "last", "rolling20"):
            pairs = rows[name]
            if len(pairs) < 100:
                continue
            pred = [p for p, _ in pairs]
            real = [r for _, r in pairs]
            mp, mr = statistics.fmean(pred), statistics.fmean(real)
            try:
                corr = statistics.correlation(pred, real)
            except Exception:
                corr = float("nan")
            print(
                "%-6s %-11s %7d %9.3f %9.3f %8.2f %8.3f"
                % (interval, name, len(pairs), mp, mr, mr / mp if mp else 0, corr)
            )
        print()

    print("ratio 1.00 means the estimate is the size of a typical move.")
    print("Above 1 it understates, below 1 it overstates. Correlation says")
    print("whether it tracks the *changes*, which is the harder half.")


if __name__ == "__main__":
    main()
