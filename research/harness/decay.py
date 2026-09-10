"""Does a call have an edge in the first seconds, and how fast does it decay?

The observation this exists to test: a `down` call went out on AUDJPY, price
fell for a few seconds and then came back. If that is systematic it is an edge
we currently throw away by holding - and it would explain something already
measured, because `by_interval` puts sub-15m trading at **-821.75 over 129
closes** against +35.03 at 15m and above. "Right for seconds, wrong for hours"
and "short holds lose money" are the same sentence read from two ends.

## The control is the whole measurement

Price moves 0.3 volatility units in *any* thirty seconds. So the excursion
after a call is not evidence of anything on its own, and the number that
matters is the excursion after a call **minus the excursion after a matched
random moment on the same instrument**. Without that this harness would
rediscover volatility and call it alpha.

The control draws its timestamps from the same feed and the same hours as the
calls it is matched against, because volatility has a strong intraday shape -
sampling uniformly across the day would compare live sessions against dead ones
and hand back the session effect as an edge.

## Three quantities, and only one of them is tradeable

* **Excursion at k seconds** - where price is, relative to the call, k seconds
  later. The honest one.
* **Best excursion within k seconds** - the most favourable point reached at
  any moment up to k. This is what a perfect exit would have captured and is
  therefore an *upper bound* nobody trades, but the gap between it and the
  first number says how much of the edge is timing.
* **Net of the spread** - excursion minus a round trip. On this book the
  crossing cost runs from 0.003v on btc to **2.5v on gbpusd intraday**, so a
  gross edge of half a unit is a loss on most FX. This is the only column that
  decides anything.

## The hold has to be weighted by the timeframe, and that is measurable

A `down` call on 4h and a `down` call on 15m are not the same claim, so they
should not be held for the same number of seconds. The obvious move is to scale
the hold by the interval - but the multiplier should come from the decay curve
rather than from taste, so every table below is also broken out **by the
interval the call came from**. If the coarse curve is flatter, interval-weighted
holds are justified and the shape of the weighting is read straight off it. If
all the intervals decay at the same rate, one hold is right for all of them and
the weighting is a complication buying nothing.

The value of an aggressive trailing stop is in these tables too, and it is the
gap between the `at k` and `best k` columns. `best` is the most favourable point
reached at any moment up to k; `at` is where price actually was at k. A wide gap
means most of the excursion is given back and a tight trail captures it. A
narrow gap means the trail has nothing to catch and only adds a way to be
stopped out early.

## Latency is a column, not a footnote

The path is structures -> bus -> trading -> broker. If the edge decays in ten
seconds and the round trip is 500ms we keep most of it; if it decays in two we
do not. So every horizon is also measured from a *delayed* entry, and the decay
of the edge against the delay is the answer to "is this reachable from here".
"""

from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import statistics as st
import sys
import time
from bisect import bisect_left
from collections import defaultdict

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
JOURNAL = os.path.join(DATA, "journal.db")
#: **Ticks, not quotes.** This first read the production quote table, which is a
#: sampled stream - and for a measurement whose entire subject is the first few
#: seconds after a call, a sample of those seconds is the wrong instrument. The
#: broker bridge serves `copy_ticks_range`, so the record itself is available:
#: `research/harness/mt5fill.py ticks` fills it.
PRICES = os.environ.get("DB", os.path.join(DATA, "research.db"))

DAYS = float(os.environ.get("DAYS", "10"))
#: Seconds after the call at which the excursion is read.
HORIZONS = (1, 2, 5, 10, 30, 60, 300)
#: Entry delays, in seconds. 0 is a perfect fill; the rest are latency.
DELAYS = (0.0, 0.5, 1.0, 3.0)
#: Control draws per call.
CONTROLS = int(os.environ.get("CONTROLS", "3"))
SEED = 11


def calls(conn: sqlite3.Connection, since: float) -> dict[str, list[tuple]]:
    """Published directional calls, by feed: (time, sign, vol_bps, interval)."""
    out: dict[str, list[tuple]] = defaultdict(list)
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE actor='structures' AND kind='decision' "
        "AND time>=? ORDER BY time ASC",
        (since,),
    ):
        try:
            got = json.loads(ctx or "{}")
        except Exception:
            continue
        feed = str(got.get("feed") or "")
        way = str(got.get("direction") or "").lower()
        vol = got.get("vol_bps")
        if not feed or way not in ("up", "down"):
            continue
        if not isinstance(vol, int | float) or vol <= 0:
            continue
        out[feed].append((float(when), 1 if way == "up" else -1, float(vol),
                          str(got.get("interval") or "")))
    return out


def quotes_for(conn: sqlite3.Connection, feed: str, lo: float, hi: float):
    """(t, mid, spread) for one feed over a window, in time order.

    From the `ticks` table, which is every print the terminal recorded, at
    millisecond resolution. The spread is carried per tick rather than assumed,
    because it is the number that decides whether any of this is tradeable.
    """
    rows = []
    for ts, bid, ask in conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? AND ts BETWEEN ? AND ? ORDER BY ts ASC",
        (feed, int(lo * 1000), int(hi * 1000)),
    ):
        if not isinstance(bid, int | float) or not isinstance(ask, int | float):
            continue
        if bid <= 0 or ask <= 0 or ask < bid:
            continue
        rows.append((ts / 1000.0, (bid + ask) / 2.0, ask - bid))
    return rows


def measure(path, times, t0: float, sign: int, unit: float, delay: float) -> dict | None:
    """Excursion in volatility units at each horizon, from a delayed entry.

    **Bisected, and the first version was not.** It walked the whole tick list
    once per horizon per call - O(calls x horizons x ticks) - which on a feed
    with a few hundred thousand ticks and tens of thousands of calls does not
    finish in any useful time. It ran for fifteen minutes on two days of data
    without printing a line, and the natural reading of that was a stalled
    query against an unindexed journal. The journal has four indexes and
    780,439 rows; the harness was the slow thing.

    `times` is the tick timestamps in order, passed in so the bisect is over a
    plain list rather than rebuilt per call.
    """
    if unit <= 0:
        return None
    start_i = bisect_left(times, t0 + delay)
    if start_i >= len(path):
        return None
    _, start, spread_at_entry = path[start_i]
    out = {"spread_vol": spread_at_entry / unit}
    # One pass forward through the window, tracking the running best as each
    # horizon boundary is crossed. The horizons are sorted, so this is a single
    # walk rather than one per horizon.
    best = float("-inf")
    last = None
    i = start_i
    for k in HORIZONS:
        edge = t0 + delay + k
        while i < len(path) and path[i][0] <= edge:
            move = sign * (path[i][1] - start) / unit
            if move > best:
                best = move
            last = move
            i += 1
        if last is None:
            continue
        out[f"at{k}"] = last
        out[f"best{k}"] = best
    return out if len(out) > 1 else None


def summarise(rows: list[dict], label: str) -> dict[str, float]:
    got = {}
    for k in HORIZONS:
        vals = [r[f"at{k}"] for r in rows if f"at{k}" in r]
        bests = [r[f"best{k}"] for r in rows if f"best{k}" in r]
        if len(vals) < 30:
            continue
        got[f"at{k}"] = st.fmean(vals)
        got[f"best{k}"] = st.fmean(bests)
        got[f"n{k}"] = len(vals)
    spreads = [r["spread_vol"] for r in rows if "spread_vol" in r]
    got["spread_vol"] = st.median(spreads) if spreads else float("nan")
    return got


def run() -> None:
    random.seed(SEED)
    if not os.path.exists(PRICES):
        print(f"no prices db at {PRICES}")
        sys.exit(1)
    jc = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=600.0)
    pc = sqlite3.connect(f"file:{PRICES}?mode=ro", uri=True, timeout=600.0)
    since = time.time() - DAYS * 86400

    book = calls(jc, since)
    print(f"{sum(len(v) for v in book.values()):,} directional calls "
          f"over {len(book)} feeds, {DAYS:g} days\n")

    for delay in DELAYS:
        live: list[dict] = []
        control: list[dict] = []
        for feed, made in sorted(book.items(), key=lambda kv: -len(kv[1])):
            if len(made) < 20:
                continue
            lo = min(t for t, _s, _v, _i in made) - 60
            hi = max(t for t, _s, _v, _i in made) + max(HORIZONS) + 60
            path = quotes_for(pc, feed, lo, hi)
            if len(path) < 500:
                continue
            times = [t for t, _m, _s in path]
            span = (path[0][0], path[-1][0])
            for t0, sign, vol, _iv in made:
                unit = vol / 10_000.0 * (path[0][1] or 1.0)
                got = measure(path, times, t0, sign, unit, delay)
                if got:
                    got["interval"] = _iv
                    live.append(got)
                # Matched controls: same feed, same sign, a random moment in the
                # same window. Same sign matters - a directional edge measured
                # against an undirected control would be half noise.
                for _ in range(CONTROLS):
                    rt = random.uniform(span[0], max(span[0], span[1] - max(HORIZONS)))
                    got = measure(path, times, rt, sign, unit, delay)
                    if got:
                        got["interval"] = _iv
                        control.append(got)

        if len(live) < 100:
            print(f"delay {delay:.1f}s: only {len(live)} usable calls, skipping")
            continue
        a = summarise(live, "call")
        b = summarise(control, "control")
        print(f"=== entry delayed {delay:.1f}s === "
              f"({len(live):,} calls, {len(control):,} controls, "
              f"median spread {a.get('spread_vol', float('nan')):.3f}v)")
        print(f"  {'k':>5s} {'call':>8s} {'control':>8s} {'edge':>8s} "
              f"{'net':>8s} {'best':>8s} {'n':>7s}")
        for k in HORIZONS:
            if f"at{k}" not in a or f"at{k}" not in b:
                continue
            edge = a[f"at{k}"] - b[f"at{k}"]
            net = edge - a.get("spread_vol", 0.0)
            print(f"  {k:>4d}s {a[f'at{k}']:8.4f} {b[f'at{k}']:8.4f} {edge:+8.4f} "
                  f"{net:+8.4f} {a[f'best{k}']:8.4f} {a[f'n{k}']:7d}")

        # **By the interval the call came from.** A 4h call and a 15m call are
        # not the same claim and should not be held the same length of time -
        # but the multiplier belongs to the data, not to taste. A flatter curve
        # on the coarse rungs is what justifies weighting the hold; identical
        # curves would say one hold serves all of them.
        by_iv = defaultdict(list)
        ctl_iv = defaultdict(list)
        for r in live:
            by_iv[r.get("interval") or "?"].append(r)
        for r in control:
            ctl_iv[r.get("interval") or "?"].append(r)
        shown = [iv for iv in by_iv if len(by_iv[iv]) >= 100]
        if shown:
            print(f"\n  by interval (edge net of spread, {len(shown)} rungs with >=100 calls)")
            head = "  ".join(f"{k}s".rjust(8) for k in HORIZONS)
            print(f"  {'interval':>8s} {'calls':>6s}  {head}")
            for iv in sorted(shown, key=lambda x: -len(by_iv[x])):
                aa, bb = summarise(by_iv[iv], iv), summarise(ctl_iv.get(iv, []), iv)
                cells = []
                for k in HORIZONS:
                    if f"at{k}" not in aa or f"at{k}" not in bb:
                        cells.append("       -")
                        continue
                    net_k = (aa[f"at{k}"] - bb[f"at{k}"]) - aa.get("spread_vol", 0.0)
                    cells.append(f"{net_k:+8.4f}")
                print(f"  {iv:>8s} {len(by_iv[iv]):6d}  " + "  ".join(cells))
        print()

    print("edge = call minus a matched random moment on the same feed, same sign.")
    print("net  = edge minus one round-trip spread. Only `net` decides anything.")
    print("best = the most favourable point reached, an upper bound nobody trades.")


if __name__ == "__main__":
    run()
