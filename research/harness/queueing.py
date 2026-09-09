"""Is the slow strategies' problem supply, or is it the queue?

87% of published calls are 5m or faster, which looked like the answer. But
`TRADING_STRATEGIES` is a priority list and **the first taker wins** - so a
strategy only ever sees what everyone ahead of it refused.

`sweep-aware` accepts 1m, 3m, 5m, 15m and 30m. `swing-level` accepts 15m and
30m only. sweep-aware is **ahead** of it. So every 15m and 30m call sweep-aware
wants is gone before swing-level is asked, and what reaches swing-level is the
1m remainder it cannot trade - which is exactly what its refusals say: 72%
`interval: 1m is not scalped`.

If that is right, the fix is not more slow calls. It is the order.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time

DB = "/app/.data/journal/journal.db"
ORDER = ["runner", "sweep-aware", "approach-scalp", "swing-level",
         "origin-swing", "opportunity", "ride", "momentum-scalp"]
PAT = re.compile(r"^([a-z-]+) would have (taken|passed|never filled|stop|target)")


def run():
    now = time.time()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=180.0)
    calls = {}
    for when, title, ctx in conn.execute(
        "SELECT time, title, context FROM entries WHERE actor='trading' AND kind='observation' "
        "AND time>=? AND title LIKE '%would have%'",
        (now - 7 * 86400,),
    ):
        m = PAT.match(str(title))
        if not m:
            continue
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            d = {}
        key = (int(float(when) // 60), str(d.get("feed") or ""))
        entry = calls.setdefault(key, {"interval": "", "verdicts": {}})
        entry["verdicts"][m.group(1)] = m.group(2)
        if d.get("interval"):
            entry["interval"] = str(d["interval"])

    print(f"{len(calls)} call-moments with shadow verdicts, 7 days\n")
    wants = lambda v: v in ("taken", "target", "stop", "never filled")

    for band, label in ((("15m", "30m"), "slow calls (15m/30m)"),
                        (("1m", "3m", "5m"), "fast calls (1m/3m/5m)")):
        part = {k: v for k, v in calls.items() if v["interval"] in band}
        print(f"=== {label}: {len(part)} call-moments ===")
        if not part:
            print("  (none)\n")
            continue
        print(f"  {'strategy':18s} {'wants it':>9s} {'gets it first':>14s}")
        for name in ORDER:
            wanted = sum(1 for v in part.values() if wants(v["verdicts"].get(name, "")))
            first = 0
            for v in part.values():
                for candidate in ORDER:
                    if wants(v["verdicts"].get(candidate, "")):
                        first += candidate == name
                        break
            print(f"  {name:18s} {wanted:9d} {first:14d}")
        starved = sum(
            1 for v in part.values()
            if wants(v["verdicts"].get("swing-level", ""))
            and any(wants(v["verdicts"].get(c, "")) for c in ORDER[:ORDER.index("swing-level")])
        )
        print(f"\n  swing-level wanted it and something ahead took it: {starved}")
        print()


if __name__ == "__main__":
    run()
