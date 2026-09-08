"""Does a change point on *other instruments* say anything about this one?

The cross-timeframe version returned the largest result on this line - three or
more timeframes agreeing is followed by +7.92v a day out against -1.24v for one
alone (`agreeing.md`). This asks the same question across instruments.

## The confound is worse here than it was there

**These instruments are not independent.** EURUSD, USDCAD and USDJPY are three
views of the dollar; gold and silver are one metal trade. Three of them calling
a change at the same moment may be *one event seen three times* rather than
three confirmations - which is exactly how MD-FOCuS failed in `localising.md`,
where pooling the co-dependent high, low and close made the estimate worse.

So a peer count that predicts is not yet a result. It has to predict **beyond
what the instrument's own timeframes already say**, because an instrument's own
change is correlated with its peers' by construction. Every table is therefore
conditioned on `own` as well as on the realised move.

## Direction does not mean what it looks like

EURUSD up and USDJPY up are *opposite* dollar moves, and sign-aligning would
need a reference and a fitted correlation. So both are taken:

* `peers_same` - peers calling in the same signed direction. Interpretable
  inside a bloc that moves together, misleading across the dollar pairs.
* `peers_any` - peers calling a change in **either** direction. No sign to get
  wrong, and the cleaner primitive: "the market broadly is changing" needs no
  sign. This is the headline.

## The synthetic control

Deriv's synthetics are generated processes with no shared macro factor, so the
expected cross-asset effect on them is **zero**. A non-zero result there does
not automatically mean a bug - independent processes still show windows of
apparent co-movement, and nine days is short enough for a sample-period
coincidence - but it does mean the real-asset number is not measuring what it
looks like it is measuring. Run as a group of their own.
"""

from __future__ import annotations

import bisect
import math
import os
import random
import sqlite3
import statistics as st
import sys

from till_infinity.structures.learning.focus import Focus

DB = os.environ.get("MULTI_DB", "/app/.data/research/multi.db")
GRID = 5
INTERVALS = (5, 15, 30, 60)
THRESHOLD = float(os.environ.get("THRESHOLD", "12.0"))
DECAY = 0.02
WARMUP = 60
WINDOW = 60
HORIZONS = (12, 48, 288)
LOOKBACK = 12


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
    """Coarse bars stamped with the time they **closed**, not opened."""
    out, bucket = [], []
    for bar in fine:
        if bucket and (bar.time // 60) % size == 0:
            out.append(_Bar(bar.time, bucket[-1].close))
            bucket = []
        bucket.append(bar)
    return out


def fired(bars):
    """The times this timeframe called a change, up and down."""
    up, down = Focus(threshold=THRESHOLD), Focus(threshold=THRESHOLD, up=False)
    scale, ups, downs = 0.0, [], []
    for i, bar in enumerate(bars):
        if i == 0:
            continue
        step = bar.close - bars[i - 1].close
        scale = abs(step) if scale <= 0 else scale * (1 - DECAY) + abs(step) * DECAY
        if scale <= 0 or i < WARMUP:
            continue
        if up.update(step, scale=scale):
            up.reset()
            ups.append(bar.time)
        if down.update(step, scale=scale):
            down.reset()
            downs.append(bar.time)
    return ups, downs


def _in(stamps, floor, now):
    return bisect.bisect_right(stamps, now) > bisect.bisect_right(stamps, floor)


def build(conn, feeds):
    """Per feed: its grid, its own per-timeframe calls, and its merged calls."""
    out = {}
    for feed in feeds:
        fine = load(conn, feed)
        if len(fine) < 5_000:
            continue
        grid = aggregate(fine, GRID)
        if len(grid) < WARMUP * 4:
            continue
        own_up, own_down = [], []
        for size in INTERVALS:
            ups, downs = fired(aggregate(fine, size))
            own_up.append(ups)
            own_down.append(downs)
        out[feed] = {
            "grid": grid,
            "times": [b.time for b in grid],
            "up": own_up,
            "down": own_down,
            "any": sorted({t for xs in own_up + own_down for t in xs}),
            "merged_up": sorted({t for xs in own_up for t in xs}),
            "merged_down": sorted({t for xs in own_down for t in xs}),
        }
    return out


def measure(book):
    """One record per event: own count, peer count, realised move, what followed."""
    out = []
    longest = max(HORIZONS)
    names = sorted(book)
    for feed in names:
        data = book[feed]
        grid, times = data["grid"], data["times"]
        others = [n for n in names if n != feed]
        scale = 0.0
        for i, bar in enumerate(grid):
            if i:
                step = bar.close - grid[i - 1].close
                scale = abs(step) if scale <= 0 else scale * (1 - DECAY) + abs(step) * DECAY
            if scale <= 0 or i < LOOKBACK or i + longest >= len(grid):
                continue
            now = bar.time
            floor = now - WINDOW * 60
            for direction, sign in (("up", 1.0), ("down", -1.0)):
                own = sum(1 for xs in data[direction] if _in(xs, floor, now))
                if not own:
                    continue
                same = other = live = 0
                for peer in others:
                    pd = book[peer]
                    # Only count a peer that was **trading**. A market that was
                    # shut cannot have agreed or disagreed, and folding it in
                    # as a silent no would make every weekend look like calm
                    # consensus.
                    if not _in(pd["times"], floor, now):
                        continue
                    live += 1
                    if _in(pd["any"], floor, now):
                        other += 1
                    if _in(pd["merged_" + direction], floor, now):
                        same += 1
                here = bar.close
                trigger = abs(here - grid[i - LOOKBACK].close) / scale
                forward = tuple(sign * (grid[i + h].close - here) / scale for h in HORIZONS)
                out.append((own, other, same, live, trigger, forward, feed))
    return out


def decile(values, count=10):
    ordered = sorted(values)
    if not ordered:
        return []
    return [ordered[min(len(ordered) - 1, len(ordered) * k // count)] for k in range(1, count)]


def split(events, index, peer_index, label, rng, own_at=None):
    """Peers high against peers low, conditioned on the realised move.

    `own_at` restricts to events where the instrument's own timeframes said the
    same thing, which is the control that makes this a separate result rather
    than a restatement of `agreeing.md`.
    """
    rows = events if own_at is None else [e for e in events if e[0] == own_at]
    if len(rows) < 200:
        print(f"  {label}: only {len(rows)} events, not reported")
        return
    edges = decile([e[4] for e in rows])
    if not edges:
        return
    cut = st.median([e[peer_index] for e in rows])
    low_all, high_all = [], []
    for k in range(len(edges) + 1):
        lo = edges[k - 1] if k else -math.inf
        hi = edges[k] if k < len(edges) else math.inf
        inside = [e for e in rows if lo <= e[4] < hi]
        low = [e[5][index] for e in inside if e[peer_index] <= cut]
        high = [e[5][index] for e in inside if e[peer_index] > cut]
        if len(low) < 30 or len(high) < 30:
            continue
        low_all += low
        high_all += high
    if not low_all or not high_all:
        print(f"  {label}: no decile carried 30 of both, not reported")
        return
    a, b = st.median(low_all), st.median(high_all)
    shuffled = [e[peer_index] for e in rows]
    rng.shuffle(shuffled)
    fake = [(p, e[5][index]) for p, e in zip(shuffled, rows)]
    fa = st.median([v for p, v in fake if p <= cut])
    fb = st.median([v for p, v in fake if p > cut])
    print(
        f"  {label:26s} {len(low_all):6d} {len(high_all):6d} "
        f"{a:8.3f}v {b:8.3f}v {b - a:8.3f}v   null {fb - fa:7.3f}v"
    )


def run(feeds, seed=7):
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120.0)
    book = build(conn, feeds)
    if len(book) < 3:
        print(f"only {len(book)} usable feeds, need 3")
        return
    events = measure(book)
    print(f"{len(book)} instruments, {len(events)} events\n")
    print(f"{'feed':26s} {'events':>8s} {'own>=3':>8s} {'peers med':>10s} {'live med':>9s}")
    for feed in sorted(book):
        rows = [e for e in events if e[6] == feed]
        if not rows:
            continue
        print(
            f"{feed:26s} {len(rows):8d} {sum(1 for e in rows if e[0] >= 3):8d} "
            f"{st.median([e[1] for e in rows]):10.1f} {st.median([e[3] for e in rows]):9.1f}"
        )
    for index, horizon in enumerate(HORIZONS):
        print(f"\nforward {horizon * GRID}m - peers above median vs below, "
              f"conditioned on the realised move")
        print(f"  {'cut':26s} {'n low':>6s} {'n high':>6s} {'low':>9s} {'high':>9s} {'gap':>9s}")
        split(events, index, 1, "peers_any, all events", rng)
        split(events, index, 2, "peers_same, all events", rng)
        # The control: does the peer count add anything once the instrument's
        # own timeframes have spoken?
        split(events, index, 1, "peers_any | own == 1", rng, own_at=1)
        split(events, index, 1, "peers_any | own == 2", rng, own_at=2)
        split(events, index, 1, "peers_any | own == 3", rng, own_at=3)


if __name__ == "__main__":
    run(sys.argv[1].split(","))
