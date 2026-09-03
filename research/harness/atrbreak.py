"""Does zone width still predict a hold when the label cannot see the width?

[bjorgum.md](../bjorgum.md) found wide zones holding, and named the hole: a
visit was scored a break when price closed beyond the **far edge of the zone**,
and a wider zone has a further far edge. Wide zones may hold the way a wider
net catches more.

So take the width out of both halves of the label:

* a **touch** is price coming within `TOUCH_ATR` of the level, not entering a
  band whose size is the thing being tested;
* a **break** is a close `BREAK_ATR` beyond the level on the far side.

Both distances are in ATR at the pivot, identical for every zone regardless of
how wide its band would have been. Width then plays no part in which visits
exist or in how they are scored, and is a pure feature. If it still separates,
the finding is real; if it collapses, it was geometry.
"""

import itertools
import sqlite3
import sys
from collections import Counter, defaultdict

import numpy as np
from bjorgum import (  # type: ignore[import-not-found]
    MAX_BARS,
    MAX_FEEDS,
    RIGHT,
    atr,
    build,
    merge,
    pivots,
)

TOUCH_ATR = 0.25
BREAK_ATR = 1.0
FORWARD = 60


def auc(scores, labels) -> float:
    s, y = np.asarray(scores, dtype=float), np.asarray(labels, dtype=bool)
    if y.all() or not y.any():
        return float("nan")
    order = np.argsort(s)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, s.size + 1)
    n1, n0 = y.sum(), (~y).sum()
    return (ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def family(feed: str) -> str:
    low = feed.lower()
    if any(k in low for k in ("volatility", "step", "jump", "range_break")):
        return "synthetic control"
    if any(k in low for k in ("boom", "crash")):
        return "boom/crash"
    return "real market"


def visits(high, low, close, level: float, span: float, start: int):
    """Touches of a *price*, at a fixed distance, and how each resolved."""
    near = TOUCH_ATR * span
    far = BREAK_ATR * span
    out = []
    inside = False
    for i in range(start, len(close)):
        here = (high[i] >= level - near) and (low[i] <= level + near)
        if here and not inside:
            inside = True
            came_above = close[i - 1] > level if i else False
            ahead = close[i : i + FORWARD]
            if not ahead.size:
                break
            broke = bool((ahead < level - far).any() if came_above else (ahead > level + far).any())
            out.append((i, broke))
        elif not here:
            inside = False
    return out


def main() -> None:
    interval = sys.argv[1] if len(sys.argv) > 1 else "15m"
    q = sqlite3.connect("file:/app/.data/prices/prices.db?mode=ro", uri=True)
    feeds = [
        r[0] for r in q.execute("select distinct feed from bars where interval = ?", (interval,))
    ]
    rows = defaultdict(list)
    quota: Counter = Counter()
    for feed in feeds:
        fam = family(feed)
        if quota[fam] >= MAX_FEEDS:
            continue
        bars = list(
            q.execute(
                "select high, low, close from bars where feed=? and interval=? "
                "order by ts desc limit ?",
                (feed, interval, MAX_BARS),
            )
        )[::-1]
        if len(bars) < 300:
            continue
        quota[fam] += 1
        high = np.array([b[0] for b in bars], dtype=float)
        low = np.array([b[1] for b in bars], dtype=float)
        close = np.array([b[2] for b in bars], dtype=float)
        band = atr(high, low, close)
        hi_p, lo_p = pivots(high, low)
        zones = merge(
            [z for z in (build(high, low, close, i, True, band) for i in hi_p) if z]
            + [z for z in (build(high, low, close, i, False, band) for i in lo_p) if z]
        )
        for zone in zones:
            span = band[zone.index]
            if not np.isfinite(span) or span <= 0:
                continue
            width = (zone.top - zone.bottom) / max(zone.mid, 1e-9)
            for n, (at, broke) in enumerate(
                visits(high, low, close, zone.mid, span, zone.index + RIGHT + 1), 1
            ):
                rows[fam].append((width, float(n), zone.flipped, broke))

    print(
        f"interval {interval}, break at {BREAK_ATR}xATR from the level, "
        f"touch within {TOUCH_ATR}xATR\n"
    )
    for fam in ("real market", "synthetic control"):
        data = rows.get(fam)
        if not data or len(data) < 300:
            continue
        w = np.array([r[0] for r in data])
        visit = np.array([r[1] for r in data])
        broke = np.array([r[3] for r in data], dtype=bool)
        base = broke.mean()
        print(f"=== {fam}: {len(data):,} visits, base break rate {base:.1%}")
        print(f"  AUC  width {auc(w, broke):.4f}   visit number {auc(visit, broke):.4f}")
        edges = np.quantile(w, [0, 0.25, 0.5, 0.75, 1.0])
        print(f"  {'width band':26s} {'n':>6s} {'break':>8s} {'vs base':>9s}")
        for lo, hi in itertools.pairwise(edges):
            m = (w >= lo) & ((w < hi) if hi < edges[-1] else (w <= hi))
            if m.sum() < 60:
                continue
            r = broke[m].mean()
            print(f"  {lo:11.6f}-{hi:<13.6f} {m.sum():6,d} {r:8.1%} {r - base:+9.1%}")
        fresh = visit == 1
        if fresh.sum() > 60:
            print(
                f"  {'first visit (fresh)':26s} {fresh.sum():6,d} "
                f"{broke[fresh].mean():8.1%} {broke[fresh].mean() - base:+9.1%}"
            )
        print()


if __name__ == "__main__":
    main()
