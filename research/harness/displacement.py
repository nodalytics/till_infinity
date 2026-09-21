"""Displacement: a move that breaks an extreme, leaves imbalance, and shows intent.

Run from the repository root:  python research/harness/displacement.py

The operator's hypothesis, stated as a conjunction on the **move** rather than on a
level: a move worth following must either jump or grind consistently in one direction,
it must leave imbalances behind it, and it must break an extreme.

Everything else measured here has been a condition on a *place* - a gap edge, a swing
level, a premium zone - and all of it came back at the fair-odds line. This is a
different shape of claim and deserves its own test.

## The three conditions, made precise

**Breaks an extreme.** The move's end closes beyond the most recent confirmed swing high
(for an up-move) or low (for a down-move). Close, not wick, because a wick through a
level is the sweep in `smc.py` and is a different event.

**Leaves an imbalance.** Somewhere inside the move there is at least one unfilled
three-candle gap - `high[j-2] < low[j]` for an up-move - which is untouched at the moment
the move completes. This is `imbalance.py`'s construction, reused rather than restated.

**Jumps or grinds.** Either one candle in the move has a body of at least `JUMP` true
ranges, or the move contains a run of at least `RUN` same-coloured candles. The operator
allows both, so both are accepted, and they are also reported separately because they are
very different processes - the Boom and Crash result in `jump_odds.py` turned on exactly
that distinction.

## The ablation is the experiment

Each condition is scored alone, in pairs, and all together. **If any single condition
scores what the conjunction scores, the others are decoration.**

This matters because the conjunction is rare, so it will be measured on far fewer
samples than its parts - and a rare rule with a wide error bar can look better than a
common one purely by having more room to move. The sample count sits next to every row
for that reason.

The whole persistent-homology literature spent eight years without running its
equivalent ablation; when someone finally did, the loops contributed nothing and the
component doing the work was ordinary dispersion.

## What is measured

The trade is taken at the close of the bar completing the move, in the move's direction.
The stop goes at the move's origin - the extreme it started from, which is what the
move would have to retrace entirely to be wrong. The target is the same distance beyond
the entry, so reward-to-risk is one by construction and **the fair-odds line is 50% for
every row**, which removes the geometry confound that decided `patterns.md` and
`premium_discount.py`.

Both barriers in one bar counts as a stop, as everywhere here.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Bars either side of a pivot, and the delay before it may be used.
SWING = 5

#: Bars a move may span. Long enough for a grind, short enough to be one move.
SPAN = 12

#: A candle counts as a jump when its body reaches this many true ranges.
JUMP = 2.0

#: Same-coloured candles that count as a grind.
RUN = 4

#: Bars allowed to resolve the trade.
HORIZON = 96

#: The move must travel at least this far, in true ranges, to be a move at all.
MIN_MOVE = 2.0


def running_pivots(bars: np.ndarray, k: int = SWING):
    """Last confirmed swing high and low at each bar, delayed by `k`."""
    high, low = bars[:, 2], bars[:, 3]
    n = len(bars)
    hi = np.full(n, np.nan)
    lo = np.full(n, np.nan)
    hi_now = lo_now = np.nan
    for i in range(k, n - k):
        j = i - k
        if j >= k:
            if high[j] >= high[j - k : j + k + 1].max():
                hi_now = float(high[j])
            if low[j] <= low[j - k : j + k + 1].min():
                lo_now = float(low[j])
        hi[i], lo[i] = hi_now, lo_now
    return hi, lo


def conditions(bars: np.ndarray, tr: np.ndarray, at: int, side: int, hi, lo) -> dict[str, bool]:
    """Which of the three conditions this move satisfies, at bar `at`."""
    close, opens, high, low = bars[:, 4], bars[:, 1], bars[:, 2], bars[:, 3]
    start = at - SPAN
    here = close[at]
    unit = max(tr[at] * here, 1e-12)

    # Broke an extreme: the close is beyond the level that stood before the move.
    level = hi[start] if side > 0 else lo[start]
    broke = bool(np.isfinite(level) and ((here > level) if side > 0 else (here < level)))

    # Left an imbalance: an unfilled three-candle gap inside the move.
    gap = False
    for j in range(start + 2, at + 1):
        up_gap = side > 0 and high[j - 2] < low[j]
        if up_gap and low[j + 1 : at + 1].min(initial=np.inf) > low[j]:
            gap = True
            break
        down_gap = side < 0 and low[j - 2] > high[j]
        if down_gap and high[j + 1 : at + 1].max(initial=-np.inf) < high[j]:
            gap = True
            break

    # Jumped, or ground consistently.
    bodies = close[start : at + 1] - opens[start : at + 1]
    jumped = bool(np.max(np.abs(bodies)) >= JUMP * unit)
    colours = np.sign(bodies)
    best = run = 0
    for c in colours:
        run = run + 1 if c == side else 0
        best = max(best, run)
    ground = bool(best >= RUN)

    return {"breaks extreme": broke, "leaves imbalance": gap, "jumps or grinds": jumped or ground}


def resolve(bars: np.ndarray, at: int, side: int, stop: float, target: float, horizon: int):
    high, low = bars[:, 2], bars[:, 3]
    for step in range(1, horizon + 1):
        i = at + step
        if i >= len(bars):
            return 0
        if side > 0:
            hit_t, hit_s = high[i] >= target, low[i] <= stop
        else:
            hit_t, hit_s = low[i] <= target, high[i] >= stop
        if hit_t and hit_s:
            return -1
        if hit_t:
            return 1
        if hit_s:
            return -1
    return 0


def walk(bars: np.ndarray, tr: np.ndarray, horizon: int, tally: dict) -> int:
    hi, lo = running_pivots(bars)
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    counted = 0
    for at in range(SWING * 2 + SPAN, len(bars) - horizon):
        here = close[at]
        start = at - SPAN
        origin_hi = float(high[start : at + 1].max())
        origin_lo = float(low[start : at + 1].min())
        unit = tr[at] * max(here, 1e-12)
        if unit <= 0:
            continue

        for side in (1, -1):
            travel = (here - origin_lo) if side > 0 else (origin_hi - here)
            if travel < MIN_MOVE * unit:
                continue
            # Stop at the move's origin; target the same distance beyond. R:R is one,
            # so fair odds is 50% for every row and geometry cannot explain a result.
            risk = travel
            stop = here - risk if side > 0 else here + risk
            target = here + risk if side > 0 else here - risk
            got = resolve(bars, at, side, stop, target, horizon)
            if got == 0:
                continue
            met = conditions(bars, tr, at, side, hi, lo)
            names = [k for k, v in met.items() if v]
            tally["all moves"].append(got > 0)
            for name in names:
                tally[name].append(got > 0)
            for a, b in combinations(sorted(names), 2):
                tally[f"{a} + {b}"].append(got > 0)
            if len(names) == 3:
                tally["ALL THREE"].append(got > 0)
            counted += 1
    return counted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=["xauusd", "eurusd", "gbpusd", "usdjpy", "boom_1000_index", "crash_1000_index"],
    )
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    args = ap.parse_args()

    tally: dict[str, list] = defaultdict(list)
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < args.horizon + 500:
            continue
        tr = candles.true_range(bars)
        n = walk(bars, tr, args.horizon, tally)
        print(f"{symbol:<22} {n:>8,} resolved moves")

    print(
        f"\nreward-to-risk is 1 by construction, so fair odds is 50.0% for every row\n"
        f"\n  {'condition':<38}{'n':>9}{'hit':>8}{'excess':>9}{'+/-':>7}"
    )
    rows = []
    for name, got in tally.items():
        if len(got) < 300:
            continue
        won = np.array(got, dtype=float)
        hit = float(won.mean())
        se = float(np.sqrt(hit * (1 - hit) / len(won)))
        rows.append((hit - 0.5, name, len(won), hit, 2 * se))
    for excess, name, n, hit, band in sorted(rows, reverse=True):
        mark = "  <-" if abs(excess) > band else ""
        print(f"  {name:<38}{n:>9,}{hit:>8.1%}{excess:>+9.1%}{band:>7.1%}{mark}")

    print(
        "\n  Read the ablation, not the winner. If a single condition scores what the\n"
        "  conjunction scores, the other two are decoration - and the conjunction is\n"
        "  rarer, so it has a wider band and more room to look good by chance."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
