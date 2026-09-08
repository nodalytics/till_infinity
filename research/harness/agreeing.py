"""Does a change point that shows on every timeframe mean more than one on the fastest?

Todo 7a, option 2, and the smaller of the two shapes on purpose: one statistic
across 5m, 15m, 1h and 4h, rather than six detectors into one model. If the
cross-timeframe signal is not there in the cleanest possible form it will not
be there in a six-detector soup, and `research/localising.md` has just finished
measuring that pooling more inputs made things worse.

`confluence` already assumes agreement across timeframes means something about
**levels**. Nobody has asked it about **changes**.

## What an event is

One `Focus` per timeframe per direction, fed that timeframe's own closes in its
own volatility units, reset when it fires. A timeframe is *saying change* while
the most recent bar it closed fired - so a 4h call stands for four hours, which
is how a person reads it, and a 5m call is stale in five minutes.

Agreement is how many of the four are saying change in the same direction at
the same moment, read on the 5m grid.

## The confound this exists to defeat

**A 4h change is a bigger move by construction.** It takes more to trip a
detector on a bar four hundred and eighty times longer, so "four timeframes
agree" will predict "a big move happened" with no market content whatever. Any
comparison that does not hold the *realised* move fixed is measuring the
detector's own threshold.

So every event carries `trigger` - the move already made, in volatility units -
and the buckets are compared **inside deciles of it**. The pooled table is
reported first because it is the one that looks impressive, and it is the one
that means nothing on its own.

## Causality

Every scale is an EWMA of what had already printed, every statistic comes from
a bar that had already closed, and the forward return starts at the event bar's
close. The one thing taken from the whole series is which venue has the most
bars per feed.
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

DB = "/app/.data/research/bt1m.db"
#: The grid every reading is taken on, in minutes, and the timeframes read.
GRID = 5
#: **4h is not in this list and the todo asked for it.** The research database
#: holds 24 days of one-minute bars per feed from its best venue, which is 144
#: four-hour bars - fewer than the warmup, let alone a sample. Reporting a
#: cross-timeframe result that leaned on 144 bars would be reporting noise with
#: a table around it. 30m stands in its place, and the 4h arm waits for data.
INTERVALS = (5, 15, 30, 60)
#: FOCuS's own shipped threshold - 12 nats. Swept below rather than trusted.
THRESHOLD = float(os.environ.get("THRESHOLD", "12.0"))
#: EWMA span for the scale each detector is fed in, and the bars of warmup
#: before an event is allowed to count.
DECAY = 0.02
WARMUP = 60
#: How long a call stands, in minutes. **A common window rather than each
#: timeframe's own bar length**, which was the first version and is wrong: it
#: gives a 5m call five minutes to be agreed with and an hour to the 60m one,
#: so four-way agreement becomes an artefact of the fastest clock rather than a
#: fact about the market. An hour, so "these timeframes called the same change"
#: means what a person would mean by it.
WINDOW = 60
#: Forward horizons, in grid bars: an hour, four hours, a day.
HORIZONS = (12, 48, 288)
#: The realised move each event is conditioned on, in grid bars.
LOOKBACK = 12


class _Bar:
    __slots__ = ("close", "time")

    def __init__(self, ts, c):
        self.time, self.close = ts, c


def load(conn, feed):
    venue = conn.execute(
        "SELECT venue, COUNT(*) n FROM bars WHERE feed=? AND interval='1m' AND high > low "
        "GROUP BY venue ORDER BY n DESC LIMIT 1",
        (feed,),
    ).fetchone()
    if not venue:
        return []
    rows = conn.execute(
        "SELECT ts, close FROM bars WHERE feed=? AND interval='1m' AND venue=? ORDER BY ts",
        (feed, venue[0]),
    ).fetchall()
    return [_Bar(*r) for r in rows]


def aggregate(fine, size):
    """Coarse bars, each stamped with the time it **closed**.

    The close time rather than the open, because everything downstream asks
    "what had this timeframe said by now" and a bar stamped with its open is a
    bar that answers four hours early.
    """
    out, bucket = [], []
    for bar in fine:
        if bucket and (bar.time // 60) % size == 0:
            out.append(_Bar(bar.time, bucket[-1].close))
            bucket = []
        bucket.append(bar)
    return out


def fired(bars):
    """When each timeframe called a change, and which way.

    Returns one entry per bar: `(close time, up fired, down fired)`. The
    detector is reset on firing, so these are discrete events rather than a
    level staying above a line.
    """
    up, down = Focus(threshold=THRESHOLD), Focus(threshold=THRESHOLD, up=False)
    scale, out = 0.0, []
    for i, bar in enumerate(bars):
        if i == 0:
            out.append((bar.time, False, False))
            continue
        step = bar.close - bars[i - 1].close
        # Causal scale: the EWMA of what has already printed. A detector fed a
        # scale computed from the whole series is being told the future.
        scale = abs(step) if scale <= 0 else scale * (1 - DECAY) + abs(step) * DECAY
        if scale <= 0 or i < WARMUP:
            out.append((bar.time, False, False))
            continue
        hot_up = up.update(step, scale=scale)
        hot_down = down.update(step, scale=scale)
        if hot_up:
            up.reset()
        if hot_down:
            down.reset()
        out.append((bar.time, hot_up, hot_down))
    return out


def agreement(fine, feed):
    """Every grid bar, with how many timeframes were calling a change on it."""
    grid = aggregate(fine, GRID)
    if len(grid) < WARMUP * 2:
        return [], []
    # What each timeframe was saying, carried forward to the grid. A 4h call
    # stands until 4h prints again; a 5m call is replaced in five minutes.
    # When each timeframe called a change, as two sorted lists of times.
    calls = {}
    for size in INTERVALS:
        events = fired(aggregate(fine, size))
        calls[size] = (
            [t for t, hot, _ in events if hot],
            [t for t, _, hot in events if hot],
        )

    scale, rows = 0.0, []
    for i, bar in enumerate(grid):
        if i:
            step = bar.close - grid[i - 1].close
            scale = abs(step) if scale <= 0 else scale * (1 - DECAY) + abs(step) * DECAY
        up = down = 0
        floor = bar.time - WINDOW * 60
        for size in INTERVALS:
            ups, downs = calls[size]
            # Strictly in the past: a call stamped exactly now is a bar that
            # closed now and is allowed; anything later is the future.
            up += 1 if _called(ups, floor, bar.time) else 0
            down += 1 if _called(downs, floor, bar.time) else 0
        rows.append((i, up, down, scale))
    return grid, rows


def _called(stamps, floor, now):
    """Whether this timeframe called a change inside the window ending now."""
    left = bisect.bisect_right(stamps, floor)
    right = bisect.bisect_right(stamps, now)
    return right > left


def measure(grid, rows, feed):
    """One record per event: how many agreed, what had moved, what followed."""
    out = []
    longest = max(HORIZONS)
    for i, up, down, scale in rows:
        if scale <= 0 or i < LOOKBACK or i + longest >= len(grid):
            continue
        for count, sign in ((up, 1.0), (down, -1.0)):
            if not count:
                continue
            here = grid[i].close
            trigger = abs(here - grid[i - LOOKBACK].close) / scale
            forward = tuple(
                sign * (grid[i + h].close - here) / scale for h in HORIZONS
            )
            out.append((count, trigger, forward, feed))
    return out


def decile(values, count=10):
    ordered = sorted(values)
    if not ordered:
        return []
    return [ordered[min(len(ordered) - 1, len(ordered) * k // count)] for k in range(1, count)]


def table(title, events, index):
    print(f"\n{title}")
    print(f"  {'agree':>6s} {'n':>7s} {'median':>9s} {'mean':>9s} {'>0':>7s} {'trigger':>9s}")
    for k in (1, 2, 3, 4):
        rows = [e for e in events if e[0] == k]
        if len(rows) < 30:
            continue
        forward = [e[2][index] for e in rows]
        trigger = [e[1] for e in rows]
        print(
            f"  {k:6d} {len(rows):7d} {st.median(forward):8.3f}v {st.fmean(forward):8.3f}v "
            f"{sum(1 for f in forward if f > 0) / len(forward):6.1%} {st.median(trigger):8.2f}v"
        )


def conditioned(events, index, rng):
    """The comparison that survives the confound: matched on the realised move.

    Events are split into deciles of `trigger` - how far price had already
    travelled when the call came - and one-timeframe events are compared with
    three-or-more-timeframe events **inside each decile**. A difference here is
    a difference the size of the move does not explain.
    """
    edges = decile([e[1] for e in events])
    if not edges:
        return
    print(f"\n  conditioned on the realised move, horizon {HORIZONS[index] * GRID}m")
    print(f"  {'decile':>7s} {'trigger':>16s} {'n 1tf':>7s} {'n 3+tf':>7s} "
          f"{'1tf':>9s} {'3+tf':>9s} {'gap':>9s}")
    lows, alls = [], []
    for k in range(len(edges) + 1):
        lo = edges[k - 1] if k else -math.inf
        hi = edges[k] if k < len(edges) else math.inf
        inside = [e for e in events if lo <= e[1] < hi]
        one = [e[2][index] for e in inside if e[0] == 1]
        many = [e[2][index] for e in inside if e[0] >= 3]
        if len(one) < 30 or len(many) < 30:
            continue
        a, b = st.median(one), st.median(many)
        lows += one
        alls += many
        label = f"{lo:6.2f}-{hi:6.2f}" if math.isfinite(lo) and math.isfinite(hi) else (
            f"  <{hi:6.2f}" if not math.isfinite(lo) else f"  >{lo:6.2f}"
        )
        print(f"  {k + 1:7d} {label:>16s} {len(one):7d} {len(many):7d} "
              f"{a:8.3f}v {b:8.3f}v {b - a:8.3f}v")
    if lows and alls:
        print(f"  {'pooled':>7s} {'':>16s} {len(lows):7d} {len(alls):7d} "
              f"{st.median(lows):8.3f}v {st.median(alls):8.3f}v "
              f"{st.median(alls) - st.median(lows):8.3f}v")
    # The null: the same events with their agreement counts shuffled. If the
    # gap survives this, the label is doing no work and the deciles are.
    shuffled = [e[0] for e in events]
    rng.shuffle(shuffled)
    fake = [(k, e[1], e[2], e[3]) for k, e in zip(shuffled, events)]
    one = [e[2][index] for e in fake if e[0] == 1]
    many = [e[2][index] for e in fake if e[0] >= 3]
    if len(one) > 30 and len(many) > 30:
        print(f"  {'shuffled':>7s} {'':>16s} {len(one):7d} {len(many):7d} "
              f"{st.median(one):8.3f}v {st.median(many):8.3f}v "
              f"{st.median(many) - st.median(one):8.3f}v")


def per_feed(events, index):
    """The same gap, one instrument at a time.

    **The cheapest defence against the obvious objection.** Forward windows of
    a day overlap heavily on five-minute events, so a single instrument having
    one long trend inside a 24-day sample could carry the pooled number on its
    own. If the gap is real it should appear on most of the eight separately,
    and if it is one trend wearing a table it will not.
    """
    print(f"\n  per instrument, horizon {HORIZONS[index] * GRID}m, "
          f"trigger above the 60th percentile")
    print(f"  {'feed':10s} {'n 1tf':>7s} {'n 3+tf':>7s} {'1tf':>9s} {'3+tf':>9s} {'gap':>9s}")
    edges = decile([e[1] for e in events])
    floor = edges[5] if len(edges) > 5 else 0.0
    wins = 0
    seen = 0
    for feed in sorted({e[3] for e in events}):
        inside = [e for e in events if e[3] == feed and e[1] >= floor]
        one = [e[2][index] for e in inside if e[0] == 1]
        many = [e[2][index] for e in inside if e[0] >= 3]
        if len(one) < 20 or len(many) < 20:
            print(f"  {feed:10s} {len(one):7d} {len(many):7d} {'-':>9s} {'-':>9s} {'-':>9s}")
            continue
        a, b = st.median(one), st.median(many)
        seen += 1
        wins += 1 if b > a else 0
        print(f"  {feed:10s} {len(one):7d} {len(many):7d} {a:8.3f}v {b:8.3f}v {b - a:8.3f}v")
    if seen:
        print(f"  3+tf ahead on {wins} of {seen} instruments with enough of both")


def run(feeds, seed=5):
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60.0)
    everything = []
    print(f"threshold {THRESHOLD} nats, grid {GRID}m, timeframes {INTERVALS}\n")
    print(f"{'feed':10s} {'grid bars':>10s} {'events':>8s} " + " ".join(
        f"{'agree ' + str(k):>9s}" for k in (1, 2, 3, 4)))
    for feed in feeds:
        fine = load(conn, feed)
        if len(fine) < 20_000:
            continue
        grid, rows = agreement(fine, feed)
        if not rows:
            continue
        events = measure(grid, rows, feed)
        everything += events
        counts = [sum(1 for e in events if e[0] == k) for k in (1, 2, 3, 4)]
        print(f"{feed:10s} {len(grid):10d} {len(events):8d} " + " ".join(
            f"{c:9d}" for c in counts))
    if not everything:
        print("\nno events")
        return
    for index, horizon in enumerate(HORIZONS):
        table(f"forward {horizon * GRID}m, signed with the change", everything, index)
    for index in range(len(HORIZONS)):
        conditioned(everything, index, rng)
    for index in range(len(HORIZONS)):
        per_feed(everything, index)


if __name__ == "__main__":
    run(sys.argv[1].split(","))
