"""95% accuracy on FX direction is not skill. What is it?

The suspicion: research/resolution.md found two thirds of outcomes resolving
within two seconds. A touch that resolves in two seconds is not a prediction
about a future move - it is a slice of the move already in progress, and
consecutive slices at one level push the same way because they are the *same
move* counted several times.

If that is what `up_rate` is reading, accuracy should collapse as the hold
lengthens. Bucket the floor's accuracy by how long the touch took to resolve.
"""

import json
import sqlite3
from collections import defaultdict

c = sqlite3.connect("file:/app/.data/journal/journal.db?mode=ro", uri=True)
rows = c.execute(
    "select context from entries where actor='structures' and kind='outcome'"
    " order by time desc limit 200000"
).fetchall()

buckets = [(0, 2), (2, 10), (10, 60), (60, 300), (300, 1800), (1800, 10**9)]
got = defaultdict(lambda: [0, 0, 0])  # label -> [right, seen, ups]
keys = None
for (blob,) in rows:
    try:
        d = json.loads(blob or "{}")
    except (ValueError, TypeError):
        continue
    if keys is None:
        keys = sorted(d)
    rate, push, secs = d.get("up_rate"), d.get("push_vol"), d.get("seconds")
    if rate is None or push is None or secs is None:
        continue
    try:
        rate, push, secs = float(rate), float(push), float(secs)
    except (TypeError, ValueError):
        continue
    if rate == 0.5:
        continue
    label = next((f"{lo}-{hi}s" for lo, hi in buckets if lo <= secs < hi), "odd")
    got[label][0] += (rate > 0.5) == (push > 0)
    got[label][1] += 1
    got[label][2] += push > 0

print("keys on a structures outcome:", keys)
print(f"\n{'held for':14s} {'n':>7s} {'accuracy':>9s} {'base':>7s} {'edge':>8s}")
order = [f"{lo}-{hi}s" for lo, hi in buckets] + ["odd"]
for label in order:
    right, seen, up = got[label]
    if not seen:
        continue
    base = max(up / seen, 1 - up / seen)
    print(f"{label:14s} {seen:7d} {right / seen:9.1%} {base:7.1%} {right / seen - base:+8.2%}")

total = sum(v[1] for v in got.values())
quick = got["0-2s"][1] + got["2-10s"][1]
print(f"\n{quick} of {total} resolved inside ten seconds ({quick / max(total, 1):.1%})")
