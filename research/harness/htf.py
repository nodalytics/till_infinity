"""Do higher-timeframe levels behave differently from fast ones?

The desk claim is that a 1h, 4h or 1d level is *stronger* - more participants
saw it, so more defend it. Nothing here has ever cut the record that way: every
model pools the intervals, and research/similarity.md found that pooling is
what let a tautology dominate.

Two things are separable and worth keeping apart:

* the **interval the level was drawn on** - a 1d level is a different object
  from a 1m one;
* how **long the touch took to resolve**, which research/horizon.md shows is
  where the tautology lives.

A slow level touched and resolved in thirty seconds is still a fast
resolution. So this cuts by interval, and then by interval within the one
duration band where the answer is not definitional.
"""

import json
import sqlite3
from collections import defaultdict

c = sqlite3.connect("file:/app/.data/journal/journal.db?mode=ro", uri=True)
HELD = ("reject", "backcheck", "trap")
BROKE = ("break",)
ORDER = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w")

rows = []
for (blob,) in c.execute(
    "select context from entries where actor = ? and kind = ? order by time desc limit 400000",
    ("structures", "outcome"),
):
    try:
        d = json.loads(blob or "{}")
    except (ValueError, TypeError):
        continue
    outcome = str(d.get("outcome") or "")
    secs = d.get("seconds")
    if outcome not in HELD + BROKE or secs is None or float(secs) < 0:
        continue
    rows.append(
        {
            "interval": str(d.get("interval") or ""),
            "held": outcome in HELD,
            "seconds": float(secs),
            "push": abs(float(d.get("push_vol") or 0.0)),
        }
    )

print(f"{len(rows)} resolved touches\n")


def table(cut, label):
    per = defaultdict(list)
    for r in cut:
        per[r["interval"]].append(r)
    print(label)
    print(f"   {'interval':9s} {'n':>7s} {'held':>7s} {'median hold':>12s} {'E|push|':>9s}")
    for name in ORDER:
        got = per.get(name)
        if not got or len(got) < 30:
            continue
        held = sum(1 for r in got if r["held"]) / len(got)
        import statistics as st

        hold = st.median(r["seconds"] for r in got)
        push = st.median(r["push"] for r in got)
        print(f"   {name:9s} {len(got):7d} {held:7.1%} {hold:11.0f}s {push:9.2f}")


table(rows, "every resolution:")
print()
table(
    [r for r in rows if 300 <= r["seconds"] < 1800],
    "resolved in 300-1800s only - the band where the answer is not definitional:",
)
