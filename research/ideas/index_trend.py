"""`ma_pullback` at M15 on every index, with and without an H4 and daily filter.

Two operator asks, 2026-11-20: *"test it with the H4 and daily trend filter"*
and run *"the gross-positive M15 version against the full 14 index symbols to
see if any of them is cheap enough to clear its own cost"*.

Both questions are about the same arithmetic, which is why they are one run.
[`index_pullback.py`](index_pullback.py) measured the rule across six indices
and three frames: **gross +0.0495R at M15 against 0.0807R of cost**, so the
signal finds roughly five basis points of risk and pays eight. The cost is read
from each bar's **own quoted spread**, not a median, and every condition that
looked like it "worked" - wide range, busy quoting, narrow spread, US session -
turned out to be four readings of cost in R rather than four market regimes.

So:

* **A trend filter has to pay for itself twice.** It must raise the gross edge
  *and* not shrink the sample into noise. `reactive-zones.md` records a
  multi-timeframe confluence arm whose sample went to zero, and a filter that
  keeps 5% of trades on a 0.05R gross edge has bought nothing measurable.
* **The cost screen is the other half.** Fifteen indices quote very different
  spreads relative to their own range, and `cost-screen-the-book-you-have` is
  the standing instruction: price the book first, because it ends most ideas.
  A rule that cannot clear 0.08R on the cheapest instrument available cannot
  clear it anywhere here.

Arms, each against its own day-shuffled twin with the spreads carried:

    none    the rule as measured
    h4      the H4 average must already point the trade's way
    d1      the daily average must
    both    both must

**The filter reads only closed higher-frame bars.** The broker stamps a rate
row at the bar's *open*, so an H4 row stamped 12:00 is not knowable until
16:00; `trend_of` returns close times for exactly that reason.

Run as:

    uv run python research/ideas/index_trend.py --windows 14,7
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from index_pullback import (  # noqa: E402
    WIDE,
    agrees,
    conditions,
    point_of,
    pullback,
    read,
    shuffle_days,
    trend_of,
    trim,
)

INDICES = (
    "Australia 200", "Europe 50", "France 40", "Germany 40", "Hong Kong 50", "Japan 225",
    "Netherlands 25", "Spain 35", "Swiss 20", "UK 100", "US Mid Cap 400", "US SP 500",
    "US Small Cap 2000", "US Tech 100", "Wall Street 30",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(INDICES))
    parser.add_argument("--frame", default="M15")
    parser.add_argument("--windows", default="14,7")
    parser.add_argument("--ma", default="20,50")
    parser.add_argument("--reach", default="5,10")
    parser.add_argument("--stop", type=float, default=1.0)
    parser.add_argument("--reward", default="1,2")
    parser.add_argument("--patience", type=int, default=96)
    parser.add_argument("--h4-ma", type=int, default=50)
    parser.add_argument("--d1-ma", type=int, default=50)
    parser.add_argument("--least", type=int, default=30)
    args = parser.parse_args()

    names = [s.strip() for s in args.symbols.split(",") if s.strip()]
    print(
        f"ma_pullback {args.frame} on {len(names)} indices  windows {args.windows}d  "
        f"H4 SMA{args.h4_ma}  D1 SMA{args.d1_ma}  each trade charged its own two quoted spreads"
    )
    for days in (float(d) for d in args.windows.split(",") if d.strip()):
        arms: dict[str, list[np.ndarray]] = {k: [] for k in ("none", "h4", "d1", "both")}
        twins: dict[str, list[np.ndarray]] = {k: [] for k in arms}
        costs: dict[str, list[np.ndarray]] = {k: [] for k in arms}
        states: dict[str, list[np.ndarray]] = {}
        per_symbol: list[tuple] = []
        for symbol in names:
            probe = read(symbol, args.frame, 0.0, WIDE)
            if probe is None:
                continue
            feed = read(symbol, args.frame, point_of(symbol, float(probe.bars.close[-1])), WIDE)
            if feed is None:
                continue
            h4 = trend_of(symbol, "H4", args.h4_ma)
            d1 = trend_of(symbol, "D1", args.d1_ma)
            window = trim(feed, days)
            if len(window.bars) < 400:
                continue
            mine: dict[str, list[np.ndarray]] = {k: [] for k in arms}
            paid: dict[str, list[np.ndarray]] = {k: [] for k in arms}
            for arm_name, source in (("real", window), ("shuffled", shuffle_days(window, 23))):
                for length in (int(v) for v in args.ma.split(",")):
                    for reach in (int(v) for v in args.reach.split(",")):
                        for reward in (float(v) for v in args.reward.split(",")):
                            took = pullback(source, length, reach, args.stop, reward, args.patience)
                            if took.net.size < 5:
                                continue
                            stamps = source.bars.ts[took.at] / 1e9
                            masks = {
                                "none": np.ones(took.net.size, dtype=bool),
                                "h4": agrees(took, stamps, [h4]),
                                "d1": agrees(took, stamps, [d1]),
                                "both": agrees(took, stamps, [h4, d1]),
                            }
                            for key, mask in masks.items():
                                if mask.sum() == 0:
                                    continue
                                if arm_name == "real":
                                    mine[key].append(took.net[mask])
                                    paid[key].append(took.cost[mask])
                                    if key == "none":
                                        for name, value in conditions(source, took).items():
                                            states.setdefault(name, []).append(value)
                                else:
                                    twins[key].append(took.net[mask])
            for key in arms:
                if mine[key]:
                    arms[key].append(np.concatenate(mine[key]))
                    costs[key].append(np.concatenate(paid[key]))
            if mine["none"]:
                every = np.concatenate(mine["none"])
                held = np.concatenate(mine["both"]) if mine["both"] else np.asarray([])
                per_symbol.append(
                    (
                        float(np.concatenate(paid["none"]).mean()),
                        symbol,
                        every.size,
                        float(every.mean()),
                        held.size,
                        float(held.mean()) if held.size else float("nan"),
                    )
                )
        if not arms["none"]:
            print(f"\n  {days:g}d: no feed reached a trade")
            continue
        print(f"\n  last {days:g} days")
        print("    arm     trades      net        gross     cost    shuffled twin   kept")
        base = np.concatenate(arms["none"]).size
        for key in ("none", "h4", "d1", "both"):
            if not arms[key]:
                print(f"    {key:<7} nothing survived the filter")
                continue
            net = np.concatenate(arms[key])
            paid_all = np.concatenate(costs[key])
            twin = np.concatenate(twins[key]) if twins[key] else np.asarray([])
            spread = net.std(ddof=1) / np.sqrt(net.size) if net.size > 1 else np.nan
            shown = f"{twin.mean():+.4f}" if twin.size else "    none"
            print(
                f"    {key:<7} {net.size:>6,}  {net.mean():+.4f}+-{1.96 * spread:.4f}  "
                f"{net.mean() + paid_all.mean():+.4f}  {paid_all.mean():.4f}  {shown:>12}   "
                f"{net.size / base:.0%}"
            )
        print("\n    the cost screen: every index by what it charges this rule")
        print("      cost R  index                  n      net       n(both)  net(both)")
        for cost, symbol, n, net, held_n, held_net in sorted(per_symbol):
            extra = f"{held_net:+.4f}" if held_n else "      -"
            print(f"      {cost:.4f}  {symbol:<22} {n:>5}  {net:+.4f}   {held_n:>7}  {extra}")


if __name__ == "__main__":
    main()
