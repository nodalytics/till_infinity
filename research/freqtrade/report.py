"""Judge the freqtrade backtests the way this program judges everything (see README.md).

For each strategy and its coin twin: net return per trade after fees and funding, a 95% interval
resampling whole days, both halves (2024, and 2025 on), and the strategy minus its coin.

    .venv/bin/python report.py FundingFade CoilBreakout FundingStamp
"""
from __future__ import annotations

import glob
import json
import sys

import numpy as np
import pandas as pd

from freqtrade.data.btanalysis import load_backtest_data

RNG = np.random.default_rng(13)
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def trades(name: str) -> pd.DataFrame:
    """The latest export holding `name` (freqtrade names exports by time; the .meta.json says whose)."""
    found = []
    for meta in sorted(glob.glob("user_data/backtest_results/*.meta.json")):
        if name in json.loads(open(meta).read()):
            found.append(meta.replace(".meta.json", ".zip"))
    if not found:
        raise FileNotFoundError(name)
    return load_backtest_data(found[-1], strategy=name)


def boot(t: pd.DataFrame, col: str = "profit_ratio") -> tuple[float, float]:
    day = t["open_date"].dt.floor("D")
    groups = [g[col].to_numpy() for _, g in t.groupby(day)]
    means = [np.concatenate([groups[k] for k in RNG.integers(0, len(groups), len(groups))]).mean()
             for _ in range(1000)]
    return tuple(np.percentile(means, [2.5, 97.5]))


def judge(t: pd.DataFrame) -> dict:
    lo, hi = boot(t)
    first, second = t[t["open_date"] < SPLIT], t[t["open_date"] >= SPLIT]
    out = dict(n=len(t), mean_pct=100 * t["profit_ratio"].mean(), ci_pct=(100 * lo, 100 * hi),
               first_pct=100 * first["profit_ratio"].mean(), second_pct=100 * second["profit_ratio"].mean(),
               win=(t["profit_ratio"] > 0).mean(),
               hours=t["trade_duration"].mean() / 60)
    if "funding_fees" in t:
        out["funding_usdt"] = t["funding_fees"].sum()
    return out


def main(names: list[str]) -> None:
    for name in names:
        a, b = trades(name), trades(name + "Coin")
        ja, jb = judge(a), judge(b)
        for label, j in ((name, ja), (name + "Coin", jb)):
            print(f"{label:18s} n={j['n']:6d}  {j['mean_pct']:+.3f}% a trade "
                  f"[{j['ci_pct'][0]:+.3f}, {j['ci_pct'][1]:+.3f}]  2024 {j['first_pct']:+.3f}  "
                  f"2025+ {j['second_pct']:+.3f}  win {j['win']:.2f}  hold {j['hours']:.1f}h"
                  + (f"  funding {j['funding_usdt']:+.1f} USDT" if "funding_usdt" in j else ""))
        print(f"{'':18s} strategy minus coin: {ja['mean_pct'] - jb['mean_pct']:+.3f}% a trade "
              f"(2024 {ja['first_pct'] - jb['first_pct']:+.3f}, 2025+ {ja['second_pct'] - jb['second_pct']:+.3f})\n")


if __name__ == "__main__":
    main(sys.argv[1:] or ["FundingFade", "CoilBreakout", "FundingStamp"])
