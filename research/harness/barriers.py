"""The double-barrier trade: price between two levels, which one is hit first?

Not a prediction problem. If a higher-timeframe level nearly always holds - 1h
breaks 0.6% of the time - then the trade is to bet on the hold and run to the
opposite level. The two levels are the horizontal barriers of the triple-barrier
method and the hold is the vertical one, and the label is which barrier price
touches first.

That is answerable from the record without a replay, because a level call
already carries the levels either side of it: `origin_above_*` and
`origin_below_*` on every signal.

Three things this asks:

* **availability** - how often is price actually between two of them;
* **which barrier first** - the opposite level, or back through the entry;
* **the geometry** - how wide the corridor is against the risk it takes.
"""

import json
import sqlite3
import statistics as st
from collections import Counter

c = sqlite3.connect("file:/app/.data/journal/journal.db?mode=ro", uri=True)

rows = []
for (blob,) in c.execute(
    "select context from entries where actor = ? and kind = ? order by time desc limit 400000",
    ("structures", "decision"),
):
    try:
        d = json.loads(blob or "{}")
    except (ValueError, TypeError):
        continue
    if "level" not in d:
        continue
    rows.append(d)

print(f"{len(rows)} level calls\n")

both = [
    d
    for d in rows
    if d.get("origin_above_low") is not None and d.get("origin_below_high") is not None
]
print(f"price between two origins on {len(both)} of them ({len(both) / max(len(rows), 1):.1%})")

per = Counter()
corridor = []
for d in both:
    try:
        above, below = float(d["origin_above_low"]), float(d["origin_below_high"])
        level = float(d["level"])
        vol = float(d.get("vol_bps") or 0)
    except (TypeError, ValueError, KeyError):
        continue
    if above <= below or vol <= 0 or level <= 0:
        continue
    unit = level * vol / 10_000
    if unit <= 0:
        continue
    corridor.append((above - below) / unit)
    per[str(d.get("interval") or "")] += 1

if corridor:
    corridor.sort()
    q = lambda p: corridor[min(len(corridor) - 1, int(p * len(corridor)))]
    print(f"\ncorridor width, in volatility units: n={len(corridor)}")
    print(f"   p25 {q(0.25):.1f}v   median {st.median(corridor):.1f}v   p75 {q(0.75):.1f}v")
    print("   by interval:", dict(per.most_common(8)))

print("\nhow far a touch that HELD actually travelled, by interval:")
moves = {}
for (blob,) in c.execute(
    "select context from entries where actor = ? and kind = ? order by time desc limit 400000",
    ("structures", "outcome"),
):
    try:
        d = json.loads(blob or "{}")
    except (ValueError, TypeError):
        continue
    if str(d.get("outcome") or "") not in ("reject", "backcheck", "trap"):
        continue
    iv = str(d.get("interval") or "")
    try:
        moves.setdefault(iv, []).append(abs(float(d.get("push_vol") or 0.0)))
    except (TypeError, ValueError):
        continue
for iv in ("1m", "5m", "15m", "30m", "1h", "4h"):
    got = moves.get(iv)
    if got and len(got) >= 30:
        got.sort()
        print(
            f"   {iv:4s} n={len(got):6d}  median {st.median(got):5.2f}v"
            f"  p75 {got[int(0.75 * len(got))]:5.2f}v  p90 {got[int(0.9 * len(got))]:5.2f}v"
        )
