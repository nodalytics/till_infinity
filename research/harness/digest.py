"""A period of trading in one line, plus anything that deserves its own.

Per-event reporting was right while the desk was stalled and is noise now that
it trades several times an hour. What still deserves interrupting for is a
threshold being crossed, not a trade happening.
"""

import json
import sqlite3
import time
from collections import Counter
from datetime import UTC, datetime

#: On the mounted volume, not /tmp. The container is recreated on every deploy,
#: so a mark in /tmp is lost with it and the next digest silently falls back to
#: a flat 30-minute window - double-counting or skipping whatever happened
#: since the real last look. `drift.py` had exactly this bug and it is why its
#: "movement between checks" was never once computed.
MARK = "/app/.data/digest.mark"
c = sqlite3.connect("file:/app/.data/journal/journal.db?mode=ro", uri=True)
try:
    with open(MARK) as fh:
        since = float(fh.read().strip())
except (OSError, ValueError):
    since = time.time() - 1800
now = time.time()

takes = closes = wins = 0
net = 0.0
heat, front = [], []
untaken = Counter()
worst = None
for _when, kind, (blob,) in (
    (w, k, (b,))
    for w, k, b in c.execute(
        "select time, kind, context from entries where actor = ? and time > ?", ("trading", since)
    )
):
    try:
        d = json.loads(blob or "{}")
    except (ValueError, TypeError):
        continue
    if str(d.get("shape") or "") == "untaken":
        untaken[str(d.get("resolved"))] += 1
    if kind == "decision" and d.get("entry") is not None:
        takes += 1
    elif kind == "outcome" and d.get("profit") is not None:
        p = float(d["profit"])
        closes += 1
        net += p
        wins += p > 0
        if worst is None or p < worst[0]:
            worst = (p, str(d.get("symbol")), str(d.get("exit_kind")))
        if d.get("best_r") is not None:
            front.append((float(d["best_r"]), p))
        if d.get("adverse_r") is not None:
            heat.append(float(d["adverse_r"]))

with open(MARK, "w") as fh:
    fh.write(str(now))
span = (now - since) / 60
stamp = datetime.fromtimestamp(now, UTC).strftime("%H:%M")

# A trade well in front that still LOST is the thing worth naming. The first
# version counted every trade that went past 1R and closed below its own high,
# which is nearly all of them and reads as a give-back when it is not - it
# flagged a +4.04 winner as one.
gave_back = sum(1 for r, p in front if r >= 1.0 and p <= 0)
bits = [f"{takes} taken, {closes} closed, {net:+.2f}"]
if closes:
    bits.append(f"{wins}/{closes} up")
if untaken:
    bits.append("untaken " + "/".join(f"{k} {v}" for k, v in untaken.most_common()))
if gave_back:
    bits.append(f"**{gave_back} reached 1R in front and still lost**")
print(f"{stamp} last {span:.0f}m: " + " · ".join(bits))
if worst and worst[0] < -25:
    print(f"   worst {worst[1]} {worst[0]:+.2f} ({worst[2]})")
