"""Bjorgum key levels, ported to measure rather than to trade.

Source of the idea: **Bjorgum Key Levels**, by Bjorgum on TradingView —
https://www.tradingview.com/script/CapG3ivf-Bjorgum-Key-Levels/ — reached here
through the Pine-to-Python port in `dq/terminal/sage`. The arithmetic below is
a reimplementation of that indicator's zone construction; the attribution is
the author's and this file exists so the ideas can be *tested* before any of
them reach production.

Three things it does that this repository does not:

1. **Role flipping.** A zone remembers which side price was on and counts how
   many times that changed. A zone whose original role differs from its
   current one - support now acting as resistance - is `flipped`, and the
   original describes those as among the most reliable.
2. **Separate-visit counting.** A run of consecutive bars inside a zone counts
   **once**. Price sitting in a level for nine bars is one test of it, not
   nine, and counting bars would call a level heavily defended precisely when
   it was not defended at all.
3. **ATR-scaled bands with a percent ceiling, and merging.** The band is
   `min(ATR * mult, price * max_percent) / 2` either side of the pivot, and
   overlapping same-side zones fold together: one level price found twice is
   not two levels.

What this harness asks of them, on our own bars:

* do zone touches resolve differently by `flipped`, by visit count, and by
  freshness (never revisited)?
* against the synthetic control, which is a generated process and should show
  none of it.
"""

import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np

LEFT = RIGHT = 5  # bars either side of a pivot
ATR_LEN = 14
MULT = 0.5  # wider than the sage lab's 0.015: we want zones, not lines
MAX_PERCENT = 5.0
KEEP = 10  # zones retained per side
FORWARD = 60  # bars to judge a touch over


@dataclass
class Zone:
    top: float
    bottom: float
    index: int
    resistance: bool
    above: bool = False
    breaks: int = 0
    visits: int = 0

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def flipped(self) -> bool:
        """Its original role and its current one disagree."""
        return self.resistance != (not self.above)


#: Bars kept per feed, and feeds kept per family.
#:
#: Bounded because the first version was not: run unbounded inside the trading
#: container it was OOM-killed (exit 137). The service survived - 0 restarts,
#: 502MB of its 2.6GB - but a research pass has no business competing with a
#: live desk for memory, and "it only killed my process" is luck, not design.
MAX_BARS = 20_000
MAX_FEEDS = 10


def pivots(high: np.ndarray, low: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Confirmed swing highs and lows, `LEFT` before and `RIGHT` after.

    Vectorised: a sliding-window extreme compared against the centre bar. The
    loop version was O(bars x window) in Python and did not finish.
    """
    span = LEFT + RIGHT + 1
    if high.size < span:
        return np.array([], dtype=int), np.array([], dtype=int)
    hw = np.lib.stride_tricks.sliding_window_view(high, span)
    lw = np.lib.stride_tricks.sliding_window_view(low, span)
    centre = np.arange(LEFT, high.size - RIGHT)
    # Strictly the extreme of its window, so a flat run does not print a pivot
    # at every bar in it.
    is_high = (hw.max(axis=1) == high[centre]) & ((hw == high[centre, None]).sum(axis=1) == 1)
    is_low = (lw.min(axis=1) == low[centre]) & ((lw == low[centre, None]).sum(axis=1) == 1)
    return centre[is_high], centre[is_low]


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prior = np.concatenate([[close[0]], close[:-1]])
    span = np.maximum(high - low, np.maximum(abs(high - prior), abs(low - prior)))
    out = np.full(span.shape, np.nan)
    if span.size >= ATR_LEN:
        run = np.convolve(span, np.ones(ATR_LEN) / ATR_LEN, mode="valid")
        out[ATR_LEN - 1 :] = run
    return out


def build(high, low, close, index: int, resistance: bool, band: np.ndarray) -> Zone | None:
    span = band[index]
    if not np.isfinite(span) or span <= 0:
        return None
    level = high[index] if resistance else low[index]
    half = min(span * MULT, abs(level) * MAX_PERCENT / 100.0) / 2
    if half <= 0:
        return None
    zone = Zone(top=level + half, bottom=level - half, index=index, resistance=resistance)
    # Which side price ended on, and how often it changed its mind.
    for price in close[index:]:
        if price > zone.top and not zone.above:
            zone.above, zone.breaks = True, zone.breaks + 1
        elif price < zone.bottom and zone.above:
            zone.above, zone.breaks = False, zone.breaks + 1
    return zone


def merge(zones: list[Zone]) -> list[Zone]:
    """One level price found twice is not two levels."""
    kept: list[Zone] = []
    for zone in sorted(zones, key=lambda z: z.index, reverse=True):
        hit = next(
            (
                o
                for o in kept
                if o.resistance == zone.resistance and zone.bottom <= o.top and zone.top >= o.bottom
            ),
            None,
        )
        if hit is not None:
            hit.top = max(hit.top, zone.top)
            hit.bottom = min(hit.bottom, zone.bottom)
            hit.breaks += zone.breaks
            continue
        kept.append(zone)
    res = [z for z in kept if z.resistance][:KEEP]
    sup = [z for z in kept if not z.resistance][:KEEP]
    return res + sup


def visits_and_outcomes(high, low, close, zone: Zone):
    """Every separate visit to a zone, and how each one resolved.

    A visit ends when price leaves the band. It **held** if price left on the
    side it arrived from and did not close beyond the far edge within
    `FORWARD` bars; it **broke** if it closed through.
    """
    out = []
    inside = False
    came_from_above = False
    start = 0
    for i in range(zone.index + RIGHT + 1, len(close)):
        here = high[i] >= zone.bottom and low[i] <= zone.top
        if here and not inside:
            inside, start = True, i
            came_from_above = close[i - 1] > zone.top if i else False
        elif not here and inside:
            inside = False
            ahead = close[i : i + FORWARD]
            if not ahead.size:
                break
            broke = (ahead < zone.bottom).any() if came_from_above else (ahead > zone.top).any()
            out.append((start, bool(broke), came_from_above))
    return out


def main() -> None:
    q = sqlite3.connect("file:/app/.data/prices/prices.db?mode=ro", uri=True)
    interval = sys.argv[1] if len(sys.argv) > 1 else "5m"
    feeds = [
        r[0] for r in q.execute("select distinct feed from bars where interval = ?", (interval,))
    ]

    def family(feed: str) -> str:
        low = feed.lower()
        if any(k in low for k in ("volatility", "step", "jump", "range_break")):
            return "synthetic control"
        if any(k in low for k in ("boom", "crash")):
            return "boom/crash"
        return "real market"

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
            for n, (_, broke, _) in enumerate(visits_and_outcomes(high, low, close, zone), 1):
                rows[family(feed)].append((n, zone.flipped, zone.breaks, broke))

    print(f"interval {interval}, {sum(len(v) for v in rows.values()):,} zone visits\n")
    for fam in ("real market", "boom/crash", "synthetic control"):
        data = rows.get(fam)
        if not data or len(data) < 200:
            continue
        broke = np.array([r[3] for r in data], dtype=bool)
        base = broke.mean()
        print(f"=== {fam}: {len(data):,} visits, base break rate {base:.1%}")

        def cut(title, groups, broke=broke, base=base):
            print(f"  {title}")
            for label, mask in groups:
                if mask.sum() < 40:
                    continue
                rate = broke[mask].mean()
                print(f"    {label:26s} {mask.sum():6,d} {rate:7.1%} {rate - base:+8.1%}")

        n = np.array([r[0] for r in data])
        flip = np.array([r[1] for r in data], dtype=bool)
        brk = np.array([r[2] for r in data])
        cut(
            "by which visit this is (freshness)",
            [
                ("first - fresh", n == 1),
                ("second", n == 2),
                ("third to fifth", (n >= 3) & (n <= 5)),
                ("sixth or later", n > 5),
            ],
        )
        cut("by whether the zone has flipped role", [("never flipped", ~flip), ("flipped", flip)])
        cut(
            "by how often price crossed it",
            [
                ("never crossed", brk == 0),
                ("crossed once", brk == 1),
                ("crossed twice or more", brk >= 2),
            ],
        )
        print()


if __name__ == "__main__":
    main()
