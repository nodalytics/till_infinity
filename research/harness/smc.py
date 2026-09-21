"""Liquidity sweeps, breaks of structure and order blocks, against the fair-odds line.

Run from the repository root:  python research/harness/smc.py

Three rules from the structure-and-liquidity style of teaching, taken from a mentorship
transcript and stated here precisely enough to run. The fourth rule from that material -
premium and discount around the 50% of a swing range - is in `premium_discount.py` and
came back as pure geometry: the hit rate tracked `a / (a + b)` across ten deciles and
314,794 rows without departing from it by more than half a point.

These three are tested the same way, which is the only way that can distinguish a rule
from an arithmetic identity.

## The three, as implemented

**Liquidity sweep.** Price trades *through* a confirmed prior swing extreme and then
closes back inside it - the wick takes the level, the body does not hold it. Taken
against the sweep: a swept high is sold, a swept low is bought. Stop beyond the sweep
extreme, target at the opposing swing.

**Break of structure.** Price *closes* beyond a confirmed prior swing extreme, rather
than merely wicking through it. Taken with the break. Stop at the opposing swing, target
the same distance beyond the break as the swing range - a measured move, because the
material gives no other target and one had to be chosen consistently.

**Order block.** The last opposing candle before the move that broke structure: for a
bullish break, the last down-candle before the up-move. The trade is taken when price
*returns* into that candle's range. Stop beyond the block, target at the level the break
reached.

The sweep and the order block share a shape with things already measured here - a sweep
is a level rejection and an order block is a standing zone price returns to - so
`imbalance.md` is the natural comparison: gap edges beat a matched placebo by +0.6% and
still lost to the cost line.

## What would count as a result

Each row is scored against `a / (a + b)`, the driftless first-passage probability for
its own stop and target. That number already explains textbook patterns, gap edges and
the premium/discount rule, so the only interesting outcome is an excess that is
positive, larger than its error bar, and consistent across instruments.

A high hit rate is not a result on its own. A rule that places a near target and a far
stop wins often by construction, and `patterns.md` records a double bottom hitting 58%
whose matched placebo hit 57.6%.

**Both barriers inside one bar counts as a stop**, which biases every excess slightly
negative and is shared across all three rules, so comparisons between them hold.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Bars either side of a pivot, and therefore the delay before it may be used.
SWING = 5

#: Bars allowed to resolve a trade.
HORIZON = 96

#: Bars after a break within which the order block must be revisited for the return
#: to count as the same event rather than a coincidence much later.
RETURN_WITHIN = 48


def pivots(bars: np.ndarray, k: int = SWING):
    """Confirmed swing highs and lows, and the running last of each.

    A pivot at `j` is knowable only at `j + k`. Everything downstream indexes the
    *running* arrays, so the delay is applied in one place.
    """
    high, low = bars[:, 2], bars[:, 3]
    n = len(bars)
    last_hi = np.full(n, np.nan)
    last_lo = np.full(n, np.nan)
    hi_at = np.full(n, -1, dtype=int)
    lo_at = np.full(n, -1, dtype=int)
    hi_now = lo_now = np.nan
    hi_idx = lo_idx = -1
    for i in range(k, n - k):
        j = i - k
        if j >= k:
            if high[j] >= high[j - k : j + k + 1].max():
                hi_now, hi_idx = float(high[j]), j
            if low[j] <= low[j - k : j + k + 1].min():
                lo_now, lo_idx = float(low[j]), j
        last_hi[i], last_lo[i] = hi_now, lo_now
        hi_at[i], lo_at[i] = hi_idx, lo_idx
    return last_hi, last_lo, hi_at, lo_at


def resolve(bars: np.ndarray, at: int, side: int, stop: float, target: float, horizon: int):
    """1 target first, -1 stop first, 0 neither. Both in one bar counts as a stop."""
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


def setups(bars: np.ndarray, horizon: int):
    """Every sweep, break and order block, as (rule, side, entry, stop, target, at)."""
    close, opens, high, low = bars[:, 4], bars[:, 1], bars[:, 2], bars[:, 3]
    last_hi, last_lo, _hi_at, _lo_at = pivots(bars)
    found = []

    for at in range(SWING * 2, len(bars) - horizon):
        hi, lo = last_hi[at], last_lo[at]
        if not (np.isfinite(hi) and np.isfinite(lo)) or hi <= lo:
            continue
        here = close[at]
        span = hi - lo

        # Sweep: the wick takes the level, the close does not hold it.
        if high[at] > hi and here < hi:
            found.append(("sweep", -1, here, float(high[at]), lo, at))
        if low[at] < lo and here > lo:
            found.append(("sweep", 1, here, float(low[at]), hi, at))

        # Break of structure: the close itself is beyond the level.
        if here > hi and close[at - 1] <= hi:
            found.append(("break", 1, here, lo, float(hi + span), at))
            # Order block: the last down-candle before this up-move.
            for back in range(at - 1, max(at - RETURN_WITHIN, SWING), -1):
                if close[back] < opens[back]:
                    top, bottom = float(opens[back]), float(low[back])
                    # The trade happens when price comes back into the block.
                    for fwd in range(at + 1, min(at + RETURN_WITHIN, len(bars) - horizon)):
                        if low[fwd] <= top:
                            found.append(("order block", 1, top, bottom, float(hi + span), fwd))
                            break
                    break
        if here < lo and close[at - 1] >= lo:
            found.append(("break", -1, here, hi, float(lo - span), at))
            for back in range(at - 1, max(at - RETURN_WITHIN, SWING), -1):
                if close[back] > opens[back]:
                    bottom, top = float(opens[back]), float(high[back])
                    for fwd in range(at + 1, min(at + RETURN_WITHIN, len(bars) - horizon)):
                        if high[fwd] >= bottom:
                            found.append(("order block", -1, bottom, top, float(lo - span), fwd))
                            break
                    break
    return found


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

    tally: dict[tuple[str, str], list] = defaultdict(list)
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < args.horizon + 500:
            continue
        got = setups(bars, args.horizon)
        counted = 0
        for rule, side, entry, stop, target, at in got:
            a, b = abs(entry - stop), abs(target - entry)
            if a <= 0 or b <= 0:
                continue
            outcome = resolve(bars, at, side, stop, target, args.horizon)
            if outcome == 0:
                continue
            tally[(rule, symbol)].append((outcome > 0, a / (a + b), b / a))
            counted += 1
        print(f"{symbol:<22} {counted:>7,} resolved setups")

    print(
        f"\n{'rule':<14}{'instrument':<20}{'n':>8}{'R:R':>7}{'hit':>8}{'fair':>8}{'excess':>9}{'+/-':>7}"
    )
    overall: dict[str, list] = defaultdict(list)
    for (rule, symbol), got in sorted(tally.items()):
        if len(got) < 150:
            continue
        won = np.array([g[0] for g in got], dtype=float)
        fair = np.array([g[1] for g in got])
        rr = np.array([g[2] for g in got])
        hit, theory = float(won.mean()), float(fair.mean())
        se = float(np.sqrt(hit * (1 - hit) / len(won)))
        overall[rule].append(hit - theory)
        print(
            f"{rule:<14}{symbol:<20}{len(won):>8,}{np.median(rr):>7.2f}"
            f"{hit:>8.1%}{theory:>8.1%}{hit - theory:>+9.1%}{2 * se:>7.1%}"
        )

    print()
    for rule, gaps in sorted(overall.items()):
        if gaps:
            mean = float(np.mean(gaps))
            wins = sum(1 for g in gaps if g > 0)
            print(
                f"  {rule:<14} mean excess {mean:>+7.2%} over fair odds, "
                f"positive on {wins}/{len(gaps)} instruments"
            )
    print(
        "\n  Excess is the only column that can show an edge. The hit rate moves with\n"
        "  the reward-to-risk ratio by arithmetic, so a rule with a near target will\n"
        "  always look accurate and a rule with a far one will always look poor."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
