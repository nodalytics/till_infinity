"""Does buying in discount and selling in premium beat the fair-odds line?

Run from the repository root:  python research/harness/premium_discount.py

The rule, as taught: mark the current swing range, take its midpoint, and only buy when
price sits in the lower half (the "discount") and only sell when it sits in the upper
half (the "premium"). It is the backbone of the structure-and-liquidity style of
teaching - the single most repeated instruction in the course transcript this was taken
from - and it is stated numerically, which is what makes it testable when most of that
material is not.

## Why it needs a fair-odds comparison rather than a hit rate

A trade taken in discount has its stop below the swing low and its target at the swing
high **by construction**, so it is a near stop and a far target. `barrier_pde.py` shows
what that does on its own: a driftless diffusion reaches the target first with
probability `a / (a + b)`, so the deeper into discount price sits, the *lower* the hit
rate and the *larger* the payoff, in exact compensation.

**So a discount trade will show a low hit rate and a high reward-to-risk whether or not
the rule works.** Measuring either alone says nothing. What has to be measured is
whether the outcome beats `a / (a + b)` at the same geometry - which is what
`patterns.py` learned the hard way when double bottoms turned out to be their own
geometry and nothing else.

## What is measured

For every bar, with the swing low `L` and swing high `H` most recently confirmed:

    position = (price - L) / (H - L)

`position < 0.5` is discount, `> 0.5` is premium. A discount row is scored as a long
with its stop at `L` and its target at `H`; a premium row as a short with the mirror.
Then, per position decile:

* the **realised** hit rate,
* the **fair-odds** rate `a / (a + b)` for that row's own geometry,
* the **excess**, which is the only column that can show an edge.

If the rule works, excess should be positive in the deep-discount deciles for longs and
in the deep-premium deciles for shorts. If it is flat and near zero across every decile,
the rule has been describing geometry in words.

**A bar touching both barriers counts as a stop**, as everywhere else here, so every
excess is biased slightly negative and the comparison between deciles - which shares the
bias - is the part to read.
"""

from __future__ import annotations

import argparse
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Bars either side of a pivot for it to count as a swing, and therefore the delay
#: before it may be used. Matches `patterns.py` so the two are comparable.
SWING = 5

#: Bars allowed for a barrier to be reached.
HORIZON = 96

#: Rows whose swing range is narrower than this many true ranges are dropped: a
#: "range" of half a bar's noise gives a meaningless position and a trivial barrier.
MIN_RANGE = 2.0


def structure(bars: np.ndarray, k: int = SWING) -> tuple[np.ndarray, np.ndarray]:
    """Most recently *confirmed* swing low and high at each bar.

    A pivot at `j` is only knowable at `j + k`, so the value carried at bar `i` comes
    from pivots at `i - k` or earlier. Getting this wrong would let the rule see the
    high it is about to trade towards.
    """
    high, low = bars[:, 2], bars[:, 3]
    n = len(bars)
    lows = np.full(n, np.nan)
    highs = np.full(n, np.nan)
    low_now = high_now = np.nan
    for i in range(k, n - k):
        j = i - k
        if j >= k:
            if high[j] >= high[j - k : j + k + 1].max():
                high_now = float(high[j])
            if low[j] <= low[j - k : j + k + 1].min():
                low_now = float(low[j])
        lows[i] = low_now
        highs[i] = high_now
    return lows, highs


def outcomes(bars: np.ndarray, tr: np.ndarray, horizon: int):
    """Per bar: position in range, side taken, fair odds, and what happened."""
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    lows, highs = structure(bars)
    n = len(bars)
    place = np.full(n, np.nan)
    fair = np.full(n, np.nan)
    got = np.zeros(n, dtype=np.int64)
    side = np.zeros(n, dtype=np.int64)
    ok = np.zeros(n, dtype=bool)

    for at in range(n - horizon):
        lo, hi = lows[at], highs[at]
        here = close[at]
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            continue
        span = hi - lo
        if span < MIN_RANGE * tr[at] * max(here, 1e-12):
            continue
        if not (lo < here < hi):
            continue
        pos = (here - lo) / span
        # Discount buys towards the high, premium sells towards the low. In both
        # cases the stop is the near edge and the target is the far one, which is
        # the geometry the rule prescribes rather than one chosen here.
        if pos < 0.5:
            mine, stop, target = 1, lo, hi
        else:
            mine, stop, target = -1, hi, lo
        a = abs(here - stop)
        b = abs(target - here)
        if a <= 0 or b <= 0:
            continue

        result = 0
        for step in range(1, horizon + 1):
            up = high[at + step] >= max(stop, target)
            down = low[at + step] <= min(stop, target)
            if up and down:
                result = -1  # adverse first, by convention
                break
            reached_target = up if mine > 0 else down
            reached_stop = down if mine > 0 else up
            if reached_target:
                result = 1
                break
            if reached_stop:
                result = -1
                break
        if result == 0:
            continue
        place[at], fair[at], got[at], side[at], ok[at] = pos, a / (a + b), result, mine, True
    return place, fair, got, side, ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    args = ap.parse_args()

    places, fairs, gots, sides = [], [], [], []
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < args.horizon + 200:
            continue
        tr = candles.true_range(bars)
        place, fair, got, side, ok = outcomes(bars, tr, args.horizon)
        places.append(place[ok])
        fairs.append(fair[ok])
        gots.append(got[ok])
        sides.append(side[ok])
        print(f"{symbol:<22} {int(ok.sum()):>7,} resolved rows")

    if not places:
        print("nothing to measure")
        return 1
    place = np.concatenate(places)
    fair = np.concatenate(fairs)
    got = np.concatenate(gots)
    side = np.concatenate(sides)
    won = (got > 0).astype(float)

    print(f"\n{len(place):,} rows, horizon {args.horizon} bars")
    print(f"  {'position in range':<22}{'n':>9}{'hit':>8}{'fair odds':>11}{'excess':>9}{'+/-':>7}")
    edges = np.arange(0.0, 1.01, 0.1)
    for lo, hi in pairwise(edges):
        mine = (place >= lo) & (place < hi)
        n = int(mine.sum())
        if n < 200:
            continue
        hit = float(won[mine].mean())
        theory = float(fair[mine].mean())
        excess = hit - theory
        se = float(np.sqrt(hit * (1 - hit) / n))
        tag = "discount, long" if hi <= 0.5 else "premium, short"
        print(
            f"  {lo:.1f}-{hi:.1f} {tag:<13}{n:>9,}{hit:>8.1%}{theory:>11.1%}"
            f"{excess:>+9.1%}{2 * se:>7.1%}"
        )

    deep_d = place < 0.2
    deep_p = place > 0.8
    for name, mine in (("deep discount (<0.2)", deep_d), ("deep premium (>0.8)", deep_p)):
        if mine.sum() > 200:
            hit = float(won[mine].mean())
            theory = float(fair[mine].mean())
            se = float(np.sqrt(hit * (1 - hit) / int(mine.sum())))
            print(
                f"\n  {name}: {hit:.1%} against fair odds {theory:.1%}, "
                f"excess {hit - theory:+.1%} +/- {2 * se:.1%} on {int(mine.sum()):,}"
            )
    del side
    print(
        "\n  The rule predicts positive excess at the extremes - deep discount for\n"
        "  longs, deep premium for shorts. A low hit rate there is expected and is\n"
        "  not evidence against it: the target is far and the stop is near, so the\n"
        "  fair-odds column falls with it. Only the excess can show an edge."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
