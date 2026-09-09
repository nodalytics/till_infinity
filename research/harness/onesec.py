"""What threshold do the 1-second indices need to speak?

Five of them produced 62 FOCuS events between them at the shipped 12 nats,
against hundreds on everything else. Before they are traded, the detector that
grades their regime has to fire at a comparable rate - a detector that is
silent is not a conservative detector, it is an absent one.

Measured the way production measures: steps divided by a causal EWMA of the
step size, so the reading is scale-free and the only thing being asked is how
often the statistic clears the bar.
"""
from __future__ import annotations
import math, os, sqlite3, statistics as st, sys
from till_infinity.structures.learning.focus import Focus

DB = os.environ.get("MULTI_DB", "/app/.data/research/multi.db")
DECAY, WARMUP = 0.02, 60


class _Bar:
    __slots__ = ("close", "time")
    def __init__(self, ts, c):
        self.time, self.close = ts, c


def load(conn, feed):
    venue = conn.execute(
        "SELECT venue, COUNT(*) n FROM bars WHERE feed=? GROUP BY venue ORDER BY n DESC LIMIT 1",
        (feed,)).fetchone()
    if not venue:
        return []
    return [_Bar(*r) for r in conn.execute(
        "SELECT ts, close FROM bars WHERE feed=? AND venue=? ORDER BY ts", (feed, venue[0]))]


def fires(bars, threshold):
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
            up.reset(); count += 1
        if down.update(step, scale=scale):
            down.reset(); count += 1
    days = (bars[-1].time - bars[0].time) / 86400.0 if len(bars) > 1 else 0.0
    return count, days


def run(feeds):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120.0)
    print(f"{'feed':26s} {'bars':>7s} {'days':>6s} " +
          " ".join(f"{t:>7.0f}n" for t in (4, 6, 8, 10, 12)))
    rates = {}
    for feed in feeds:
        bars = load(conn, feed)
        if len(bars) < 3000:
            print(f"{feed:26s} {len(bars):7d}  too few")
            continue
        row, days = [], 0.0
        for threshold in (4, 6, 8, 10, 12):
            n, days = fires(bars, float(threshold))
            row.append(n / days if days else 0.0)
        rates[feed] = row
        print(f"{feed:26s} {len(bars):7d} {days:6.1f} " + " ".join(f"{r:8.2f}" for r in row))
    # What the traded set does at 12, for comparison.
    traded = [rates[f][4] for f in rates if "_1s_" not in f]
    onesec = [rates[f] for f in rates if "_1s_" in f]
    if traded and onesec:
        want = st.median(traded)
        print(f"\n  traded synthetics at 12 nats: median {want:.2f} fires/day")
        print("  the 1s series need roughly:")
        for threshold, idx in ((4, 0), (6, 1), (8, 2), (10, 3), (12, 4)):
            got = st.median([r[idx] for r in onesec])
            mark = "  <-- closest" if abs(got - want) == min(
                abs(st.median([r[i] for r in onesec]) - want) for i in range(5)) else ""
            print(f"    {threshold:2d} nats -> {got:6.2f} fires/day{mark}")


if __name__ == "__main__":
    run(sys.argv[1].split(","))
