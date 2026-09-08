"""How should a FOCuS threshold change with the timeframe it runs on?

A threshold in nats is scale-free across *instruments* - that is what dividing
by a volatility unit buys. It is **not** scale-free across *timeframes*, and
the reason is not about volatility at all: it is that a 5m series contains 288
times as many bars per calendar day as a 1d series, and the running maximum of
a likelihood-ratio statistic grows with the number of chances it has had.

For a statistic like this the expected running maximum over `n` observations
grows like `log n`, so holding a constant false-alarm rate per unit of
**wall-clock time** wants

    threshold(tf) = base + k * ln(reference / tf)

with `k = 1` if the theory is right. Lower timeframe, higher threshold - which
is the direction intuition already suggests, and the point of this file is to
find out whether `k = 1` is the number.

## What is measured

Fires per calendar day, per timeframe, at a fixed threshold. If the log rule is
right then adding `ln(reference / tf)` to the threshold should flatten that
curve. Both are computed and printed side by side, so the correction is scored
rather than asserted.

**This is a null-shaped question and it has a null.** A rule that flattens the
rate on real prices might be flattening it on any series with this bar count,
so the same sweep runs on a **phase-randomised** copy of each series - same
marginal distribution, same length, no structure - and a correction that only
works on the real one is measuring the market rather than the arithmetic.
"""

from __future__ import annotations

import math
import os
import random
import sqlite3
import statistics as st
import sys

from till_infinity.structures.learning.focus import Focus

DB = os.environ.get("MULTI_DB", "/app/.data/research/multi.db")
INTERVALS = (5, 15, 30, 60, 120, 240, 480, 1440)
BASE = float(os.environ.get("BASE", "3.0"))
REFERENCE = 1440
DECAY = 0.02
WARMUP = 60


class _Bar:
    __slots__ = ("close", "time")

    def __init__(self, ts, c):
        self.time, self.close = ts, c


def load(conn, feed):
    venue = conn.execute(
        "SELECT venue, COUNT(*) n FROM bars WHERE feed=? GROUP BY venue ORDER BY n DESC LIMIT 1",
        (feed,),
    ).fetchone()
    if not venue:
        return []
    rows = conn.execute(
        "SELECT ts, close FROM bars WHERE feed=? AND venue=? ORDER BY ts", (feed, venue[0])
    ).fetchall()
    return [_Bar(*r) for r in rows]


def aggregate(fine, size):
    out, bucket = [], []
    for bar in fine:
        if bucket and (bar.time // 60) % size == 0:
            out.append(_Bar(bar.time, bucket[-1].close))
            bucket = []
        bucket.append(bar)
    return out


def shuffled(bars, rng):
    """The same bars with their steps shuffled - the null.

    Destroys every ordering effect and keeps the marginal distribution and the
    length, which is exactly the pair of properties this needs: if a threshold
    correction is really about *how many chances the detector had*, it must
    work here too.
    """
    if len(bars) < 3:
        return bars
    steps = [bars[i].close - bars[i - 1].close for i in range(1, len(bars))]
    rng.shuffle(steps)
    out, price = [_Bar(bars[0].time, bars[0].close)], bars[0].close
    for i, step in enumerate(steps, start=1):
        price += step
        out.append(_Bar(bars[i].time, price))
    return out


def fires(bars, threshold):
    """How many discrete calls this series produces, and over how many days."""
    up, down = Focus(threshold=threshold), Focus(threshold=threshold, up=False)
    scale, count = 0.0, 0
    for i, bar in enumerate(bars):
        if i == 0:
            continue
        step = bar.close - bars[i - 1].close
        scale = abs(step) if scale <= 0 else scale * (1 - DECAY) + abs(step) * DECAY
        if scale <= 0 or i < WARMUP:
            continue
        if up.update(step, scale=scale):
            up.reset()
            count += 1
        if down.update(step, scale=scale):
            down.reset()
            count += 1
    days = (bars[-1].time - bars[0].time) / 86400.0 if len(bars) > 1 else 0.0
    return count, days


def sweep(feeds, seed=11):
    """Which `k` in `base + k * ln(reference / tf)` actually flattens the rate.

    `k = 1` is what the theory gives if the statistic's tail falls like
    `exp(-h)`. Measured, a nat buys only about a third of that, so the constant
    has to be found rather than derived - which is the same lesson `CHANGE_THRESHOLD`
    learned in `localising.md`, where a default set for a different question
    made the estimator look useless.
    """
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120.0)
    series = {}
    for feed in feeds:
        fine = load(conn, feed)
        if len(fine) < 20_000:
            continue
        for size in INTERVALS:
            bars = aggregate(fine, size)
            if len(bars) < WARMUP + 30:
                continue
            series.setdefault(size, []).append(bars)
    print(f"base {BASE} nats, reference {REFERENCE}m\n")
    print(f"{'k':>5s} " + " ".join(f"{s:>7d}m" for s in sorted(series)) + f" {'spread':>9s}")
    for k in (0.0, 1.0, 2.0, 3.0, 4.0):
        rates = {}
        for size, book in sorted(series.items()):
            lift = k * math.log(REFERENCE / size)
            got = []
            for bars in book:
                n, days = fires(bars, BASE + lift)
                if days > 0:
                    got.append(n / days)
            if got:
                rates[size] = st.median(got)
        values = [v for v in rates.values() if v > 0]
        spread = max(values) / min(values) if len(values) > 1 else float("nan")
        print(
            f"{k:5.1f} " + " ".join(f"{rates.get(s, 0):8.2f}" for s in sorted(series))
            + f" {spread:9.1f}x"
        )
    del rng


def run(feeds, seed=11):
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120.0)
    flat: dict[int, list[float]] = {}
    fixed: dict[int, list[float]] = {}
    null_fixed: dict[int, list[float]] = {}
    null_flat: dict[int, list[float]] = {}
    for feed in feeds:
        fine = load(conn, feed)
        if len(fine) < 20_000:
            continue
        for size in INTERVALS:
            bars = aggregate(fine, size)
            if len(bars) < WARMUP + 30:
                continue
            lift = math.log(REFERENCE / size)
            for series, a, b in (
                (bars, fixed, flat),
                (shuffled(bars, rng), null_fixed, null_flat),
            ):
                n, days = fires(series, BASE)
                if days > 0:
                    a.setdefault(size, []).append(n / days)
                n, days = fires(series, BASE + lift)
                if days > 0:
                    b.setdefault(size, []).append(n / days)
    print(f"base {BASE} nats, reference {REFERENCE}m, correction = ln(reference / tf)\n")
    print(f"{'tf':>6s} {'lift':>6s} {'fixed/day':>10s} {'corrected/day':>14s} "
          f"{'null fixed':>11s} {'null corr':>10s}")
    for size in INTERVALS:
        if size not in fixed:
            continue
        lift = math.log(REFERENCE / size)
        print(
            f"{size:6d} {lift:6.2f} {st.median(fixed[size]):10.2f} "
            f"{st.median(flat.get(size, [0])):14.2f} "
            f"{st.median(null_fixed.get(size, [0])):11.2f} "
            f"{st.median(null_flat.get(size, [0])):10.2f}"
        )
    # Flatness: the spread of the per-day rate across timeframes, which is the
    # thing the correction is supposed to shrink.
    def spread(book):
        rates = [st.median(v) for k, v in sorted(book.items()) if v]
        if len(rates) < 2 or min(rates) <= 0:
            return float("nan")
        return max(rates) / min(rates)

    print(f"\n  spread across timeframes, fixed threshold:     {spread(fixed):8.1f}x")
    print(f"  spread across timeframes, corrected:          {spread(flat):8.1f}x")
    print(f"  spread on the shuffled null, fixed:           {spread(null_fixed):8.1f}x")
    print(f"  spread on the shuffled null, corrected:       {spread(null_flat):8.1f}x")


if __name__ == "__main__":
    if os.environ.get("SWEEP"):
        sweep(sys.argv[1].split(","))
    else:
        run(sys.argv[1].split(","))
