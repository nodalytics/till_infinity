"""Were the stopped trades wrong, or early?

Stops cost -897.84 over 38 trades and not one of them was up. That is the
account. It has two possible causes and they call for opposite responses:

* **early** - price came back and reached the target inside the intended hold.
  The signal was right and the stop was too tight for it.
* **wrong** - the target was never reached. The stop saved money.

Read from stored bars, forward from each stopped trade's own entry, over its
own intended hold. Nothing is assumed about what "would have happened" beyond
what the bars actually printed.
"""
import json, sqlite3, statistics as st
from collections import Counter

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
PRICES = "file:/app/.data/prices/prices.db?mode=ro"

j = sqlite3.connect(JOURNAL, uri=True)
p = sqlite3.connect(PRICES, uri=True)

rows = j.execute(
    "select time, context from entries where actor='trading' and kind='outcome' order by time asc"
).fetchall()

trades = []
for closed_at, blob in rows:
    try:
        d = json.loads(blob or "{}")
    except (ValueError, TypeError):
        continue
    if d.get("profit") is None:
        continue
    d["_closed"] = float(closed_at)
    trades.append(d)

ended = Counter(str(t.get("exit_kind") or t.get("reason") or "?") for t in trades)
print(f"{len(trades)} closed trades: " + ", ".join(f"{k} {v}" for k, v in ended.most_common()))

stopped = [t for t in trades if str(t.get("exit_kind") or "") == "stop"]
print(f"\n{len(stopped)} stopped out\n")

def bars(feed, interval, since, until):
    return p.execute(
        "select ts, high, low from bars where feed=? and interval=? and ts>=? and ts<=?"
        " order by ts asc",
        (feed, interval, since, until),
    ).fetchall()

early = wrong = unknown = ambiguous = 0
early_money = wrong_money = 0.0
reached_after = []
for t in stopped:
    feed = str(t.get("feed") or "")
    interval = str(t.get("interval") or "")
    try:
        entry, target, stop = float(t["entry"]), float(t["target"]), float(t["stop"])
        held = float(t.get("seconds") or 0.0)
        want = float(t.get("expected_hold_s") or 0.0) or held * 3
        profit = float(t["profit"])
    except (KeyError, TypeError, ValueError):
        unknown += 1
        continue
    started = t["_closed"] - held
    window = bars(feed, interval, started, started + max(want, held) )
    if len(window) < 2:
        unknown += 1
        continue
    up = target > entry
    hit = None
    for ts, high, low in window:
        if high is None or low is None:
            continue
        if (up and float(high) >= target) or (not up and float(low) <= target):
            hit = float(ts)
            break
    if hit is None:
        wrong += 1
        wrong_money += profit
    elif hit <= started + held:
        # Reached before the stop was hit, which cannot be a trade that was
        # stopped early - it is a bar whose high and low both qualify, so the
        # order within the bar is unknown. Counted separately rather than
        # claimed either way.
        ambiguous += 1
    else:
        early += 1
        early_money += profit
        reached_after.append(hit - (started + held))

print(f"   target reached inside the intended hold anyway : {early:3d}   ({early_money:+.2f})")
print(f"   target never reached                           : {wrong:3d}   ({wrong_money:+.2f})")
print(f"   stop and target inside one bar                 : {ambiguous:3d}   (order unknowable)")
print(f"   no bars to judge                               : {unknown:3d}")
if reached_after:
    reached_after.sort()
    q = lambda f: reached_after[min(len(reached_after) - 1, int(f * len(reached_after)))]
    print(f"\n   after the stop it took: median {st.median(reached_after):.0f}s, "
          f"p25 {q(.25):.0f}s, p75 {q(.75):.0f}s")

# How far past the stop did price actually go before turning? That sizes the fix.
overshoot = []
for t in stopped:
    try:
        entry, stop = float(t["entry"]), float(t["stop"])
        sv = float(t.get("stop_vol") or 0.0)
        adverse = float(t.get("adverse_vol") or 0.0)
    except (KeyError, TypeError, ValueError):
        continue
    if sv > 0 and adverse > 0:
        overshoot.append(adverse / sv)
if overshoot:
    overshoot.sort()
    print(f"\n   worst excursion as a multiple of the stop, on {len(overshoot)} trades:")
    print(f"      median {st.median(overshoot):.2f}x   p75 {overshoot[int(.75*len(overshoot))]:.2f}x")
