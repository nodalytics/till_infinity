"""Is `fade-to-value` losing because its stop gets wicked into?

A stop that is *hit and then reversed through* is a different failure from a
stop that was right. The first says the stop sat inside the noise; the second
says the trade was wrong. research/stops.md asked this of every trade at once
and found 20 of 27 simply wrong - but that pooled four strategies with
different geometry, and `fade-to-value` has the odd one: it enters at a
discount to fair value, so its entry is *away* from the level its stop is
anchored to.

Read from stored bars, forward from each stopped trade's own close, over the
hold it was given.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
PRICES = "file:/app/.data/prices/prices.db?mode=ro"


def main() -> None:
    j = sqlite3.connect(JOURNAL, uri=True)
    p = sqlite3.connect(PRICES, uri=True)

    trades = []
    for when, blob in j.execute(
        "SELECT time, context FROM entries WHERE actor='trading' AND kind='outcome'"
        " ORDER BY time ASC"
    ):
        try:
            d = json.loads(blob or "{}")
        except (ValueError, TypeError):
            continue
        if d.get("profit") is None:
            continue
        d["_closed"] = float(when)
        trades.append(d)

    by = defaultdict(lambda: {"n": 0, "back": 0, "target": 0, "gone": 0, "money": 0.0})
    for t in trades:
        if str(t.get("exit_kind") or "") != "stop":
            continue
        name = str(t.get("feed") or "?")
        try:
            entry, target = float(t["entry"]), float(t["target"])
            held = float(t.get("seconds") or 0.0)
            profit = float(t["profit"])
        except (KeyError, TypeError, ValueError):
            continue
        feed, interval = str(t.get("feed") or ""), str(t.get("interval") or "")
        closed = t["_closed"]
        # The window the trade would have had left, had it not been stopped.
        want = float(t.get("expected_hold_s") or 0.0) or max(held, 600.0)
        rows = p.execute(
            "SELECT high, low FROM bars WHERE feed=? AND interval=? AND ts>=? AND ts<=?"
            " ORDER BY ts ASC",
            (feed, interval, closed, closed + want),
        ).fetchall()
        got = by[name]
        got["n"] += 1
        got["money"] += profit
        if len(rows) < 2:
            got["gone"] += 1
            continue
        up = target > entry
        # Came back through the entry after being stopped - the stop sat in the
        # noise rather than marking the trade wrong.
        back = any(
            (up and float(h) >= entry) or (not up and float(low) <= entry)
            for h, low in rows
            if h is not None and low is not None
        )
        hit = any(
            (up and float(h) >= target) or (not up and float(low) <= target)
            for h, low in rows
            if h is not None and low is not None
        )
        got["back"] += back
        got["target"] += hit

    head = f"{'instrument':18s} {'stops':>6s} {'came back':>11s}"
    print(f"{head} {'reached target':>15s} {'no bars':>8s} {'money':>10s}")
    for name, got in sorted(by.items(), key=lambda kv: kv[1]["money"]):
        n = got["n"]
        judged = n - got["gone"]
        if not n:
            continue
        back = f"{got['back']}/{judged} {got['back'] / judged:.0%}" if judged else "-"
        hit = f"{got['target']}/{judged} {got['target'] / judged:.0%}" if judged else "-"
        print(f"{name:18s} {n:6d} {back:>11s} {hit:>15s} {got['gone']:8d} {got['money']:+10.2f}")


if __name__ == "__main__":
    main()
