"""Would several PIP windows give production better levels than one?

Run from the repository root:  python research/harness/pip_levels.py

The proposal is to draw perceptually important points at several window lengths rather than one.
`engine._points` currently calls `pips.points(times, closes, self.pip_count)` on the whole series
buffer - **one window, one count, per interval** - while running many different *formations* over
it and many *intervals* beside it.

So there are two questions, and the second is the one that decides whether to ship.

## Question one: is a window sweep redundant with the interval ladder?

Prod already looks at 5m, 15m, 30m, 1h and up. A 300-bar window on 1h covers the same span as a
75-bar window on 4h, so a window sweep within one interval may simply rediscover what the ladder
already provides. If so, adding windows multiplies the level count for nothing - and level count
is not free: every extra level is another thing price can be near, which dilutes whatever
`confluence` means.

This is measured as **overlap**: the share of levels found by a second window on one interval
that were already within a tolerance of a level the interval ladder had found anyway.

## Question two: does agreement across windows predict a reaction?

The reason to want several windows is the hope that a level found at *all* of them is stronger
than one found at a single length. That is a testable claim and it is the only one that justifies
production code.

Each time price arrives at a level, a trade is taken in the rejection direction with **stop and
target one true range apart**, so fair odds is 50% for every row and the geometry confound that
decided `premium_discount.py` across 314,794 rows cannot explain a result. Rows are grouped by
**how many windows agreed** on that level, so the reading is whether 4-window agreement beats
1-window agreement.

## Point-in-time correctness is the whole difficulty

A turn is only recognisable after the bars that follow it. `pips.points` records `confirmed` for
exactly this reason, and this harness recomputes the level set **every `REFORM` bars using only
points confirmed by then**, through `pips.as_of`. Levels are then tested against the bars that
come after.

Skipping that is the single easiest way to make this look profitable: a level drawn at a swing
the future has already revealed is a level nobody could have drawn, and it will be respected
beautifully.

## The minimum detectable effect, stated before the run

The discipline from `power-and-sizing.md`, applied to this design rather than discovered
afterwards. Cost is **0.063 TR of slippage** from 305 live fills plus spread, so break-even is
about 52.0% on FX - a 2.0-point hurdle. At 80% power with a handful of agreement buckets, that
needs roughly **5,000 to 8,000 touches per bucket**. The run prints its actual counts against
that requirement, and a bucket that falls short is reported as underpowered rather than as a
null.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402
import imbalance  # noqa: E402

from till_infinity.structures.drawing import pips  # noqa: E402

#: Window lengths, in bars of the interval being tested.
WINDOWS = (120, 300, 800, 2000)

#: Points asked of each window. Prod's `pip_count` is a single number; this holds it fixed
#: across windows so the variable under test is the window and not the count.
COUNT = 12

#: Bars between level recomputations. Prod reforms periodically too - see `Series.due`.
REFORM = 24

#: Two levels are the same level within this fraction of price.
TOLERANCE = 0.0015

#: Bars allowed to resolve a reaction.
HORIZON = 24

#: Measured costs, in true ranges. Slippage is the live figure from 305 journal stop-outs.
SLIPPAGE = 0.063
SPREAD = {"boom": 0.004, "crash": 0.004, "volatility": 0.004, "default": 0.020}

#: The interval ladder prod already runs, as multiples of the base interval, for question one.
LADDER = (1, 4, 8, 24)


def spread_for(symbol: str) -> float:
    for key, value in SPREAD.items():
        if key in symbol:
            return value
    return SPREAD["default"]


def levels_at(bars: np.ndarray, end: int, window: int, count: int = COUNT) -> list[float]:
    """Confirmed swing prices from one window ending at bar `end`.

    `as_of` is what keeps this honest: a trailing swing carries `inf` until enough bars
    follow it, so it falls out rather than being counted as a level nobody could see.
    """
    start = max(0, end - window + 1)
    if end - start + 1 < pips.MIN_POINTS:
        return []
    times = [int(t) for t in bars[start : end + 1, 0]]
    closes = [float(c) for c in bars[start : end + 1, 4]]
    found = pips.points(times, closes, count)
    visible = pips.as_of(found, float(times[-1]))
    return [p.price for p in pips.turns(visible)]


def agree(sets: dict[int, list[float]], tolerance: float = TOLERANCE) -> list[tuple[float, int]]:
    """Cluster levels across windows; return `(price, how many windows agreed)`."""
    flat = sorted((price, w) for w, prices in sets.items() for price in prices)
    clusters: list[list[tuple[float, int]]] = []
    for price, w in flat:
        if clusters and abs(price - clusters[-1][-1][0]) / max(price, 1e-9) < tolerance:
            clusters[-1].append((price, w))
        else:
            clusters.append([(price, w)])
    out = []
    for group in clusters:
        prices = [p for p, _ in group]
        windows = {w for _, w in group}
        out.append((float(np.mean(prices)), len(windows)))
    return out


def react(bars: np.ndarray, tr: np.ndarray, at: int, side: int, horizon: int) -> int:
    """+1 target first, -1 stop first, 0 neither. Both in one bar counts as a stop."""
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    here = close[at]
    unit = tr[at] * max(here, 1e-12)
    if unit <= 0:
        return 0
    target, stop = here + side * unit, here - side * unit
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


def study(symbol: str, bars: np.ndarray, tally: dict, overlap: dict, horizon: int) -> int:
    tr = candles.true_range(bars)
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    n = len(bars)
    counted = 0
    start = max(WINDOWS) + 2

    # **Fold once, then slice.** The first version folded `bars[:end + 1]` inside the loop,
    # which is quadratic - 2,700 reforms over 65,000 bars, each folding the whole prefix
    # again. Folding each multiple once up front and locating `end` in it by timestamp is the
    # same result in linear time, and the difference is a run that finishes.
    folded: dict[int, np.ndarray] = {}
    for mult in LADDER:
        if mult == 1:
            continue
        got = imbalance.fold(bars, mult * 3600)
        if len(got) >= pips.MIN_POINTS * 3:
            folded[mult] = got

    for end in range(start, n - horizon, REFORM):
        sets = {w: levels_at(bars, end, w) for w in WINDOWS}
        clustered = agree(sets)
        if not clustered:
            continue

        # Question one: how much of the window sweep is already in the interval ladder?
        # The ladder is the same instrument folded to coarser bars, which is what prod runs.
        ladder: list[float] = []
        now = bars[end, 0]
        for series in folded.values():
            # Only bars that had completed by `now`, so the ladder is as causal as the sweep.
            upto = int(np.searchsorted(series[:, 0], now, side="right")) - 1
            if upto >= pips.MIN_POINTS * 3:
                ladder.extend(levels_at(series, upto, WINDOWS[1]))
        ladder.extend(levels_at(bars, end, WINDOWS[1]))
        for price, votes in clustered:
            near = any(abs(price - other) / max(price, 1e-9) < TOLERANCE for other in ladder)
            overlap[votes].append(near)

        # Question two: does agreement predict a reaction? Test on the bars that follow.
        for at in range(end + 1, min(end + REFORM + 1, n - horizon)):
            unit = tr[at] * max(close[at], 1e-12)
            if unit <= 0:
                continue
            for price, votes in clustered:
                touched = low[at] <= price <= high[at]
                if not touched:
                    continue
                # Rejection direction: away from the level, judged by where price came from.
                side = 1 if close[at - 1] < price else -1
                got = react(bars, tr, at, side, horizon)
                if got == 0:
                    continue
                tally[(symbol, votes)].append(got > 0)
                counted += 1
    return counted


def mde(n: int, buckets: int = 4, power: float = 0.80) -> float:
    """Detection floor for one bucket, Bonferroni-corrected, as in `power.py`."""
    if n <= 0:
        return float("inf")
    from power import normal_quantile

    z_a = normal_quantile(1.0 - 0.05 / (2.0 * buckets))
    return (z_a + normal_quantile(power)) * math.sqrt(0.25 / n)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # Env rather than arguments, because `lab.sh run` forwards the former and not the latter.
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
        or ["xauusd", "eurusd", "boom_1000_index"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    args = ap.parse_args()

    tally: dict[tuple[str, int], list] = defaultdict(list)
    overlap: dict[int, list] = defaultdict(list)

    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < max(WINDOWS) + 2000:
            continue
        got = study(symbol, bars, tally, overlap, args.horizon)
        print(f"  {symbol:<22}{len(bars):>8,} bars{got:>9,} touches")

    print(
        "\nQUESTION ONE - is a window sweep redundant with the interval ladder prod runs?\n"
        f"  {'windows agreeing':<20}{'levels':>9}{'already in the ladder':>24}"
    )
    for votes in sorted(overlap):
        got = overlap[votes]
        if len(got) < 30:
            continue
        print(f"  {votes:<20}{len(got):>9,}{float(np.mean(got)):>23.1%}")
    print(
        "  A high share means the sweep is rediscovering the ladder and adds level count\n"
        "  rather than information."
    )

    cost = SLIPPAGE + SPREAD["default"]
    breakeven = (1.0 + cost) / (2.0 + cost)
    print(
        "\nQUESTION TWO - does agreement across windows predict a reaction?\n"
        "stop and target one true range apart, so fair odds is 50.0% for every row\n"
        f"break-even after measured costs is {breakeven:.1%}, a "
        f"{breakeven - 0.5:+.2%} hurdle\n"
        f"\n  {'windows':<9}{'n':>9}{'hit':>8}{'excess':>9}{'MDE*':>8}{'net R':>9}  verdict"
    )
    pooled: dict[int, list] = defaultdict(list)
    for (_symbol, votes), got in tally.items():
        pooled[votes].extend(got)
    for votes in sorted(pooled):
        got = pooled[votes]
        if len(got) < 100:
            continue
        won = np.array(got, dtype=float)
        hit = float(won.mean())
        floor = mde(len(got))
        net = hit * 1.0 - (1 - hit) * (1.0 + SLIPPAGE) - SPREAD["default"]
        verdict = "underpowered" if floor > 0.02 else ("clears" if net > 0 else "does not pay")
        print(
            f"  {votes:<9}{len(got):>9,}{hit:>8.1%}{hit - 0.5:>+9.2%}"
            f"{floor:>8.2%}{net:>+9.3f}  {verdict}"
        )

    print(
        "\n  The claim being tested is **monotonicity**: a level all four windows agree on\n"
        "  should beat one only a single window found. A flat column means agreement carries\n"
        "  no information and production should keep its single window.\n"
        "\n  MDE* is this bucket's detection floor, corrected for the bucket count. Where it\n"
        "  exceeds the 2-point hurdle the row cannot answer the question either way, which is\n"
        "  a statement about the design rather than about levels."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
