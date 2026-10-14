"""The Wednesday squeeze reads -0.31 bar-ranges at z -4.99. Does it survive?

`direction_rules.py` measured the published triple-swap idea and found it real
and **backwards**: joining the institutional squeeze on a Wednesday evening
hourly break loses 0.313 bar-ranges an event at z -4.99 with a 0.344 hit rate,
while the Deriv placebo arm reads -0.037 and the block-shuffled twin -0.015.
Fading it is the side that pays.

Three things stand between that and a finding, and each has caught something
in this repo before.

- **Cost.** These are exotic pairs and their spreads are enormous. A measured
  edge has already failed here on cost after surviving everything else. The
  spread column is in **points**, not price, and that error once read a 476%
  round trip on EURUSD - so the point size is inferred per feed from the
  series' own tick grid rather than assumed.
- **Pooling.** 279 events across five pairs could be one pair. A pooled median
  has already agreed with a claim that every subgroup refuted here, so every
  number below is also reported per pair.
- **Direction.** An effect that only exists on one side is usually a trend or a
  carry drift rather than a squeeze, and these pairs all have a large one-way
  drift. Up-breaks and down-breaks are split.

And the obvious confound gets its own arm. These are **high-carry pairs with
strong secular trends**: USDZAR and USDMXN drift one way for years. If a short
on a Wednesday down-break loses, it may simply be a short in an uptrend. So
the same rule runs on **every other weekday** at the same hours, which holds
the pair, the hours, the drift and the break geometry fixed and changes only
the thing the idea says matters.
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

from direction_rules import CARRY, days, hours, weekdays  # noqa: E402
from screen import load  # noqa: E402

HORIZON = int(os.environ.get("HORIZON", "3"))
DRAWS = int(os.environ.get("DRAWS", "400"))
SEED = int(os.environ.get("SEED", "11"))
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")


def tick_of(close: np.ndarray) -> float:
    """The price grid, from the smallest non-zero move the series makes."""
    moved = np.abs(np.diff(close))
    moved = moved[moved > 0]
    return float(np.quantile(moved, 0.001)) if len(moved) else 0.0


def events(bars: dict, weekday: int) -> list[tuple[int, int]]:
    """The rule, parameterised by weekday so a control can hold it fixed."""
    hour, day, when = hours(bars["time"]), days(bars["time"]), weekdays(bars["time"])
    high, low, close = bars["high"], bars["low"], bars["close"]
    out: list[tuple[int, int]] = []
    for i in range(24, len(close)):
        if when[i] != weekday or not 19 <= hour[i] < 22:
            continue
        earlier = (day == day[i]) & (hour < hour[i])
        if earlier.sum() < 4:
            continue
        if close[i] < low[earlier].min():
            out.append((i, -1))
        elif close[i] > high[earlier].max():
            out.append((i, 1))
    return out


def measure(bars: dict, got: list[tuple[int, int]]) -> tuple[np.ndarray, np.ndarray, float]:
    """Signed return and the round-trip cost, both in bar-range units."""
    close, spread = bars["close"], bars["spread"]
    span = np.log(np.maximum(bars["high"], 1e-12)) - np.log(np.maximum(bars["low"], 1e-12))
    scale = float(np.median(span[span > 0])) if (span > 0).any() else 0.0
    tick = tick_of(close)
    if scale <= 0 or tick <= 0:
        return np.empty(0), np.empty(0), 0.0
    moves, costs, signs = [], [], []
    last = -(10**9)
    for i, sign in got:
        if i - last < HORIZON or i + HORIZON >= len(close):
            continue
        last = i
        moves.append(sign * (math.log(close[i + HORIZON]) - math.log(close[i])) / scale)
        # Spread is in points: points * tick is a price, and the round trip is
        # two of them, expressed in the same bar-range units as the move.
        costs.append(2.0 * float(spread[i]) * tick / close[i] / scale)
        signs.append(sign)
    return np.asarray(moves), np.asarray(costs), float(np.mean(signs)) if signs else 0.0


def zed(got: np.ndarray, rng: np.random.Generator) -> float:
    if len(got) < 20:
        return float("nan")
    draws = np.array(
        [float(np.mean(got * rng.choice((-1.0, 1.0), size=len(got)))) for _ in range(DRAWS)]
    )
    spread = float(np.std(draws))
    return float(np.mean(got)) / spread if spread else float("nan")


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"Wednesday hourly break, 19-22 UTC, held {HORIZON} bars. `raw` is the signed\n"
        "return of the published direction in bar-range units, so a negative raw\n"
        "means fading it pays. `net` subtracts the measured round-trip spread.\n"
    )
    print(f"  {'pair':<9}{'n':>5}{'raw':>8}{'cost':>7}{'net':>8}{'z':>7}{'up share':>10}")
    pooled_raw: list[np.ndarray] = []
    pooled_net: list[np.ndarray] = []
    for name in CARRY:
        bars = load(name, "1h")
        if bars is None:
            print(f"  {name:<9}  not in the cache")
            continue
        raw, cost, lean = measure(bars, events(bars, 2))
        if len(raw) < 10:
            print(f"  {name:<9}{len(raw):>5}   too few")
            continue
        net = raw - cost
        pooled_raw.append(raw)
        pooled_net.append(net)
        print(
            f"  {name:<9}{len(raw):>5}{float(np.mean(raw)):>8.3f}"
            f"{float(np.mean(cost)):>7.3f}{float(np.mean(net)):>8.3f}"
            f"{zed(net, rng):>7.2f}{0.5 * (lean + 1.0):>10.2f}"
        )
    if not pooled_raw:
        return
    raw_all = np.concatenate(pooled_raw)
    net_all = np.concatenate(pooled_net)
    print(
        f"  {'POOLED':<9}{len(raw_all):>5}{float(np.mean(raw_all)):>8.3f}"
        f"{float(np.mean(raw_all - net_all)):>7.3f}{float(np.mean(net_all)):>8.3f}"
        f"{zed(net_all, rng):>7.2f}"
    )
    losers = sum(1 for got in pooled_raw if float(np.mean(got)) < 0)
    print(f"  the published direction loses on {losers}/{len(pooled_raw)} pairs before cost")
    print(
        f"  fading it nets {-float(np.mean(net_all)) - 2 * float(np.mean(raw_all - net_all)):+.3f}"
        " bar-ranges after paying the spread in the other direction too\n"
    )

    # Direction split: a one-sided effect on a trending pair is the trend.
    print("  by direction, pooled and before cost:")
    for sign, label in ((1, "up-breaks"), (-1, "down-breaks")):
        got = []
        for name in CARRY:
            bars = load(name, "1h")
            if bars is None:
                continue
            picked = [(i, s) for i, s in events(bars, 2) if s == sign]
            moves, _, _ = measure(bars, picked)
            if len(moves):
                got.append(moves)
        if got:
            joined = np.concatenate(got)
            print(f"    {label:<12}{len(joined):>5} events  mean {float(np.mean(joined)):>7.3f}")

    # The control that holds everything but the weekday fixed.
    print("\n  the same rule on every weekday, which holds the drift and geometry fixed:")
    for weekday, label in enumerate(DAYS):
        got = []
        for name in CARRY:
            bars = load(name, "1h")
            if bars is None:
                continue
            moves, _, _ = measure(bars, events(bars, weekday))
            if len(moves):
                got.append(moves)
        if not got:
            continue
        joined = np.concatenate(got)
        mark = "  <- the claim" if weekday == 2 else ""
        print(
            f"    {label:<5}{len(joined):>5} events  mean {float(np.mean(joined)):>7.3f}"
            f"  z {zed(joined, rng):>6.2f}{mark}"
        )
    print(
        "\n  If every weekday reads the same, the Wednesday rollover is not the cause\n"
        "  and the effect is a property of an evening break on a trending exotic."
    )


if __name__ == "__main__":
    main()
