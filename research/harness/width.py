"""Is a zone's width just volatility already measured, wearing a band?

[bjorgum.md](../bjorgum.md) found zone width scoring 0.7602 AUC against a break
- alone, above `structures/breaking.py` with all five of its features. Width is
`(top - bottom) / mid` and the band comes from **ATR at the pivot**, so the
obvious explanation is that it is a volatility estimate, and the book already
carries one on every signal.

The test has to be conditional, not marginal. If width only predicts because a
wide zone is a volatile instrument, then inside a volatility band it should say
nothing.

Two volatilities are worth separating, and they are not the same:

* **then** - what volatility was when the zone was drawn, which is what the
  band is made of;
* **now** - what it is at the visit being judged.

If the informative thing is the *ratio*, then the finding is not "wide zones
break" but "a zone drawn in a fast market and visited in a slow one behaves
differently", which is a genuinely different claim and not one `vol_bps`
already makes.
"""

import itertools
import sqlite3
import sys
from collections import Counter, defaultdict

import numpy as np
from bjorgum import (  # type: ignore[import-not-found]
    MAX_BARS,
    MAX_FEEDS,
    atr,
    build,
    merge,
    pivots,
    visits_and_outcomes,
)

VOL_BARS = 20


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


def collect(interval: str):
    """Zone visits, with the volatility when the zone was drawn and now."""
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
        # Relative volatility over the trailing window, at every bar.
        step = np.diff(close, prepend=close[0]) / np.maximum(close, 1e-9)
        sq = np.convolve(step**2, np.ones(VOL_BARS) / VOL_BARS, mode="valid")
        mu = np.convolve(step, np.ones(VOL_BARS) / VOL_BARS, mode="valid")
        vol = np.full(close.shape, np.nan)
        vol[VOL_BARS - 1 :] = np.sqrt(np.maximum(sq - mu**2, 0.0))
        hi_p, lo_p = pivots(high, low)
        zones = merge(
            [z for z in (build(high, low, close, i, True, band) for i in hi_p) if z]
            + [z for z in (build(high, low, close, i, False, band) for i in lo_p) if z]
        )
        for zone in zones:
            width = (zone.top - zone.bottom) / max(zone.mid, 1e-9)
            then = vol[zone.index] if zone.index < vol.size else np.nan
            for at, broke, _ in visits_and_outcomes(high, low, close, zone):
                now = vol[at] if at < vol.size else np.nan
                if not (np.isfinite(now) and np.isfinite(then)) or now <= 0:
                    continue
                rows[fam].append((width, float(now), float(then), broke))
    return rows


def main() -> None:
    interval = sys.argv[1] if len(sys.argv) > 1 else "15m"
    rows = collect(interval)
    print(f"interval {interval}\n")
    for fam in ("real market", "synthetic control"):
        data = rows.get(fam)
        if not data or len(data) < 300:
            continue
        w = np.array([r[0] for r in data])
        now = np.array([r[1] for r in data])
        then = np.array([r[2] for r in data])
        broke = np.array([r[3] for r in data], dtype=bool)
        print(f"=== {fam}: {len(data):,} visits, base break rate {broke.mean():.1%}")
        print(
            f"  correlation width vs volatility now: {np.corrcoef(w, now)[0, 1]:+.3f}"
            f"   vs volatility then: {np.corrcoef(w, then)[0, 1]:+.3f}"
        )
        print(f"\n  {'predictor':28s} {'AUC':>7s}")
        for name, x in (
            ("zone width", w),
            ("volatility now", now),
            ("volatility then", then),
            ("width / volatility now", w / now),
            ("volatility then / now", then / now),
        ):
            print(f"  {name:28s} {auc(x, broke):7.4f}")

        print("\n  break rate by width, *within* volatility bands")
        edges = np.quantile(now, [0, 0.25, 0.5, 0.75, 1.0])
        print(f"    {'volatility now':26s} {'n':>6s} {'narrow':>8s} {'wide':>8s} {'gap':>8s}")
        for lo, hi in itertools.pairwise(edges):
            m = (now >= lo) & ((now < hi) if hi < edges[-1] else (now <= hi))
            if m.sum() < 80:
                continue
            ww, bb = w[m], broke[m]
            cut = np.median(ww)
            narrow, wide = bb[ww <= cut].mean(), bb[ww > cut].mean()
            print(
                f"    {lo:11.5f}-{hi:<13.5f} {m.sum():6,d} {narrow:8.1%} {wide:8.1%}"
                f" {wide - narrow:+8.1%}"
            )
        print()


if __name__ == "__main__":
    main()
