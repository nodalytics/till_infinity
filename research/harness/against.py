"""Do calls taken against a live higher-timeframe call do worse?

A 15m long on `jump_10_index` was stopped for -18.26 on 2026-09-10 while the 4h
was calling **down** with p=0.79 and an expected push of -2.37v. One trade
proves nothing, but it names a question the record can answer: when a fine
timeframe disagrees with a coarse one that is still live, does the fine call
underperform?

If it does, an alignment gate is worth more than any amount of tuning at the
entry, because it removes a class of trade rather than adjusting one.

## What counts as "live"

A call stands for `CHANGE_WINDOW` - one hour - which is the same window
`engine.changing` uses to decide whether timeframes are agreeing. That choice
is deliberate there and is inherited here: giving each timeframe its own bar
length would make agreement a fact about the fastest clock rather than about
the market, which is the mistake `agreeing.md` records having made once.

Only *coarser* calls count. A 15m call is measured against 30m, 1h, 2h, 4h and
1d; never against 5m. The asymmetry is the whole hypothesis.

## The three buckets, and why "none" matters most

* **aligned** - a coarser call in the same direction is live.
* **opposed** - a coarser call in the opposite direction is live.
* **none** - no coarser call is live at all.

`none` is the control. If aligned beats opposed but both beat `none`, then what
is being measured is "a coarse call exists", not "they agree" - and the gate
that follows would be about *activity* rather than about agreement. Splitting
the two is the only way to know which.

## What would kill it

Aligned and opposed landing within a point of each other, which would say the
higher timeframe carries nothing about the lower one's outcome. Or the effect
disappearing once the fine interval is held fixed - because coarse calls are
not evenly distributed across the rungs, and a difference between 5m and 1h
trades would otherwise arrive disguised as a difference between agreement and
disagreement.
"""

from __future__ import annotations

import json
import os
import statistics as st
import sqlite3
import time
from collections import defaultdict

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
JOURNAL = os.path.join(DATA, "journal.db")
DAYS = float(os.environ.get("DAYS", "21"))
#: How long a call stands, in seconds. Matches `engine.CHANGE_WINDOW`.
WINDOW = float(os.environ.get("WINDOW", "3600"))

SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400, "1w": 604800,
}


def load(conn, since: float):
    """Decisions with a direction, and the decisive outcome of each."""
    calls = {}
    for entry_id, when, ctx in conn.execute(
        "SELECT id, time, context FROM entries WHERE actor='structures' AND kind='decision' "
        "AND time>=? ORDER BY time ASC",
        (since,),
    ):
        try:
            got = json.loads(ctx or "{}")
        except Exception:
            continue
        feed = str(got.get("feed") or "")
        iv = str(got.get("interval") or "")
        way = str(got.get("direction") or "").lower()
        if not feed or iv not in SECONDS or way not in ("up", "down"):
            continue
        calls[str(entry_id)] = (float(when), feed, iv, 1 if way == "up" else -1)

    held = {}
    for parent, ctx in conn.execute(
        "SELECT parent, context FROM entries WHERE actor='structures' AND kind='outcome' "
        "AND time>=? AND parent IS NOT NULL",
        (since,),
    ):
        try:
            got = json.loads(ctx or "{}")
        except Exception:
            continue
        out = str(got.get("outcome") or "")
        if out in ("reject", "break"):
            held[str(parent)] = out == "reject"
    return calls, held


def run() -> None:
    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=600.0)
    since = time.time() - DAYS * 86400
    calls, held = load(conn, since)
    print(f"{len(calls):,} directional calls, {len(held):,} with a decisive outcome, "
          f"{DAYS:g} days\n")

    # Calls per feed, in time order, so a lookback is a scan rather than a join.
    by_feed = defaultdict(list)
    for cid, (when, feed, iv, sign) in calls.items():
        by_feed[feed].append((when, iv, sign, cid))
    for feed in by_feed:
        by_feed[feed].sort()

    buckets = defaultdict(list)
    per_interval = defaultdict(lambda: defaultdict(list))
    for feed, rows in by_feed.items():
        for i, (when, iv, sign, cid) in enumerate(rows):
            got = held.get(cid)
            if got is None:
                continue
            mine = SECONDS[iv]
            # The most recent still-live call on any coarser rung.
            coarse = 0
            j = i - 1
            while j >= 0 and when - rows[j][0] <= WINDOW:
                other_iv, other_sign = rows[j][1], rows[j][2]
                if SECONDS[other_iv] > mine:
                    coarse = other_sign
                    break
                j -= 1
            kind = "none" if coarse == 0 else ("aligned" if coarse == sign else "opposed")
            buckets[kind].append(1 if got else 0)
            per_interval[iv][kind].append(1 if got else 0)

    print("=== held rate by agreement with a live higher timeframe ===")
    print(f"  {'bucket':>9s} {'touches':>9s} {'held':>8s}")
    for kind in ("aligned", "none", "opposed"):
        got = buckets.get(kind) or []
        if len(got) < 100:
            print(f"  {kind:>9s} {len(got):9d}   too few")
            continue
        print(f"  {kind:>9s} {len(got):9d} {st.fmean(got):8.1%}")
    a, o = buckets.get("aligned") or [], buckets.get("opposed") or []
    n = buckets.get("none") or []
    if len(a) > 100 and len(o) > 100:
        gap = st.fmean(a) - st.fmean(o)
        print(f"\n  aligned - opposed = {gap:+.1%}")
        if len(n) > 100:
            print(f"  aligned - none    = {st.fmean(a) - st.fmean(n):+.1%}")
            print(f"  none    - opposed = {st.fmean(n) - st.fmean(o):+.1%}")
            print("\n  If `none` sits between the two, agreement is what is being")
            print("  measured. If `none` matches `aligned`, then only *disagreement*")
            print("  carries information and the gate should refuse rather than require.")

    print("\n=== the same, holding the fine interval fixed ===")
    print("  (coarse calls are not evenly spread across rungs, so a difference")
    print("   between 5m and 1h could otherwise arrive disguised as agreement)")
    print(f"\n  {'interval':>8s} {'aligned':>16s} {'none':>16s} {'opposed':>16s}")
    for iv in sorted(per_interval, key=lambda x: SECONDS[x]):
        cells = []
        for kind in ("aligned", "none", "opposed"):
            got = per_interval[iv].get(kind) or []
            cells.append(f"{st.fmean(got):7.1%} ({len(got):5d})" if len(got) >= 50
                         else f"{'-':>7s} ({len(got):5d})")
        print(f"  {iv:>8s} " + " ".join(f"{c:>16s}" for c in cells))


if __name__ == "__main__":
    run()
