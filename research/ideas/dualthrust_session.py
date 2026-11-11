"""Dual Thrust with a daily range and a wall-clock flat: is +0.038 the fill?

[`dual-thrust.md`](../docs/dual-thrust.md) measured the published rule - the
range over the last `N` bars of the trading clock, an always-invested reversal
system - and refuted it. A reader then reported a **different** configuration
as profitable: EURUSD, the range over the last **8 daily** bars, `K = 0.3`,
entries intraday, **flat at 21:00 UTC**, about ten trades a month at a median
hold of eight hours, **+0.038R a trade** at Sharpe 0.86, beating 99% of random
entry times.

Two clocks and an exit the published rule does not have, so `dualthrust.py`
cannot express it: its `run_rule` triggers off **each bar's own open** and has
**no flat state** by construction. This file is that rule, and nothing else.

## The one question

**+0.038 a trade is inside the range the trigger fill is worth on a series
with no direction in it.** That is `dual-thrust.md`'s central measurement: an
OHLC fill at a touched trigger price earns **+0.03 to +0.06 units a trade** on
a direction-free arm, and the same test against a coin passes on 57 of 216
rows with 52 of them positive. Run at the reader's own `N` and `K` on 15m, the
`reflect` arm earned **+0.0574 [+0.0314, +0.0794]** against the real market's
**+0.0088** - the market *underperformed* its own direction-free twin.

So the statistic is `real - reflect` and never `real` against zero. `reflect`
keeps every real bar, its range, its gap and its wick, and coins the sign of
its body: it is the same market with the direction taken out. If +0.038
survives that, the claim is about direction and worth taking seriously. If it
lands where the artefact lands, it is the fill.

**"Beats 99% of random entry times" does not reach this**, which is why it is
worth a separate run: a random *entry time* does not fill at a trigger, so the
offset that a touched-price fill collects is absent from that null by
construction. Two controls can both be honest and test different things.

## Re-running

    ./.secrets/lab.sh run research/ideas/dualthrust_session.py \
        DTS_SYMBOLS=EURUSD DTS_N=8 DTS_K=0.3 DTS_FLAT=21
"""

from __future__ import annotations

import math
import os
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dualthrust import (  # noqa: E402
    BOOT,
    Series,
    Trade,
    block_ci,
    cache_series,
    daily,
    reflect,
    shuffle,
)

#: The reader's cell. Defaults are theirs, not this desk's.
N = int(os.environ.get("DTS_N") or 8)
K = float(os.environ.get("DTS_K") or 0.3)

#: UTC hour at which any open position is closed. The reader's rule flattens
#: at 21:00; `-1` turns the flat off and makes this the always-invested rule
#: on a daily range, which is the arm that says how much the flat is worth.
FLAT = int(os.environ.get("DTS_FLAT") or 21)

SYMBOLS = tuple(s.strip().lower() for s in (os.environ.get("DTS_SYMBOLS") or "eurusd").split(","))
DRAWS = int(os.environ.get("DTS_DRAWS") or 6)
SEED = int(os.environ.get("DTS_SEED") or 20261111)
OUT = Path(os.environ.get("DTS_OUT") or Path.home() / "till_infinity/out/dualthrust-session")


def daily_frame(series: Series) -> tuple[np.ndarray, np.ndarray]:
    """The 8-day thrust range and the day's open, broadcast to every 15m bar.

    **The range is a daily object and the entries are intraday**, which is the
    whole shape of the reader's rule and the reason `dualthrust.run_rule`
    cannot express it: that one reads `open_[i]`, each bar's own open.

    Both are shifted so a bar sees only completed days: the range comes from
    the `N` days *before* today and the reference open is today's first open,
    which is known at the first bar of the day and not before it.
    """
    day = np.floor(series.ts / 86_400.0).astype(np.int64)
    edge = np.flatnonzero(np.diff(day)) + 1
    starts = np.concatenate(([0], edge))
    stops = np.concatenate((edge, [len(day)]))
    bars = daily(series)

    width = np.full(len(series.close), np.nan)
    opens = np.full(len(series.close), np.nan)
    # `daily()` drops any day with fewer than two bars, so the day index is
    # matched on the timestamp rather than on position - an off-by-one here
    # would hand a day the next day's range, which is lookahead.
    by_ts = {int(t): i for i, t in enumerate(bars.ts)}
    for a, b in zip(starts, stops, strict=True):
        at = by_ts.get(int(series.ts[a]))
        if at is None or at < N:
            continue
        hh = bars.high[at - N : at].max()
        ll = bars.low[at - N : at].min()
        hc = bars.close[at - N : at].max()
        lc = bars.close[at - N : at].min()
        width[a:b] = max(hh - lc, hc - ll)
        opens[a:b] = series.open[a]
    return width, opens


def run_session(
    series: Series, width: np.ndarray, opens: np.ndarray, k: float, flat_hour: int
) -> list[Trade]:
    """Entries at the trigger price, one position at a time, flat at the hour.

    Filled **at the trigger**, as the rule says and as the reader's does -
    which is exactly where the measured offset lives, so changing it here
    would answer a different question.

    A day with no entry is simply absent; the duty cycle is therefore below
    one, unlike the published rule's, and the comparison against `reflect` is
    arm-to-arm on the identical construction so the cycle cancels.
    """
    hour = ((series.ts % 86_400.0) / 3600.0).astype(int)
    day = np.floor(series.ts / 86_400.0).astype(np.int64)
    trades: list[Trade] = []
    pos, entry_px, entry_i, entry_u = 0, 0.0, 0, 0.0
    # **One entry per day, and the flat ends the day.** Without this the loop
    # re-enters at 21:15 on a trigger still touched, because flattening clears
    # the position and the next bar sees `pos == 0` - which read 5,669 trades
    # where the rule as described takes about ten a month. The duty cycle is
    # the thing under test, so getting it wrong changes the object measured.
    spent = -1
    for i in range(len(series.close)):
        if pos and flat_hour >= 0 and hour[i] >= flat_hour:
            trades.append(
                Trade(entry_i, i, pos, entry_px, float(series.close[i]), entry_u, entry_u)
            )
            pos = 0
            spent = int(day[i])
            continue
        w = width[i]
        if pos or int(day[i]) == spent:
            continue
        if not math.isfinite(w) or w <= 0.0 or not math.isfinite(opens[i]):
            continue
        cap, floor = opens[i] + k * w, opens[i] - k * w
        up, down = series.high[i] >= cap, series.low[i] <= floor
        if up and down:
            # Unobservable from a bar which was touched first. Skipped rather
            # than guessed: a convention here would have a side, and the
            # published study's first one left every whipsaw bar short.
            continue
        if up:
            pos, entry_px = 1, float(cap)
        elif down:
            pos, entry_px = -1, float(floor)
        else:
            continue
        entry_i, entry_u = i, float(k * w)
        spent = int(day[i])
    return trades


def mean_units(trades: list[Trade]) -> tuple[float, int]:
    if not trades:
        return float("nan"), 0
    got = np.array([t.gross / t.unit for t in trades if t.unit > 0])
    return (float(got.mean()), len(got)) if len(got) else (float("nan"), 0)


def arm(series: Series, label: str, rng: random.Random) -> tuple[float, int, list[Trade]]:
    width, opens = daily_frame(series)
    trades = run_session(series, width, opens, K, FLAT)
    mean, n = mean_units(trades)
    return mean, n, trades


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pop = [s for s in cache_series() if s.feed.lower() in SYMBOLS and s.interval == "15m"]
    if not pop:
        print(f"no 15m series for {SYMBOLS}")
        return 1
    rng = random.Random(SEED)
    print(f"N={N} days  K={K}  flat={FLAT if FLAT >= 0 else 'never'}  draws={DRAWS}\n")
    print(f"{'symbol':10} {'arm':10} {'n':>7} {'mean_u':>10} {'lo':>9} {'hi':>9}")
    for series in pop:
        real, n_real, trades = arm(series, "real", rng)
        lo, hi = block_ci(
            np.array([t.gross / t.unit for t in trades if t.unit > 0]), rng, draws=BOOT
        )
        print(f"{series.feed:10} {'real':10} {n_real:7d} {real:10.4f} {lo:9.4f} {hi:9.4f}")
        for name, build in (("reflect", reflect), ("shuffle", shuffle)):
            means, counts = [], []
            for _ in range(DRAWS):
                got, n, _t = arm(build(series, rng), name, rng)
                if n:
                    means.append(got)
                    counts.append(n)
            if not means:
                continue
            spread = float(np.std(means, ddof=1)) if len(means) > 1 else float("nan")
            print(
                f"{series.feed:10} {name:10} {int(np.mean(counts)):7d} "
                f"{float(np.mean(means)):10.4f} {'':>9} {'':>9}  sd over draws {spread:.4f}"
            )
            if name == "reflect":
                print(
                    f"{series.feed:10} {'real-refl':10} {'':>7} "
                    f"{real - float(np.mean(means)):10.4f}   <- the statistic"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
