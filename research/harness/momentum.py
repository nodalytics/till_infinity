"""Does momentum-scalp's rule work? It has never traded, so nothing knows.

The rule: keep three exponential averages of the signed edge of calls arriving
for each instrument - half-lives of 3, 12 and 48 calls - and take a call only
when **all three agree** with the direction it states. What that buys is a
filter against calls fighting their own context; what it costs is the turn,
which it will always miss by construction.

It has taken no trade in 45 days: 109 of 110 refusals are `warmup`, because
`Speeds` was rebuilt on every deploy. The warmup is fixed; whether the rule is
any good is a separate question and this is it.

Replayed against the touch record, which is the same instrument the level work
uses: a `reject` is the level holding - the call was right - and a `break` is
price going through it.

**The comparison that matters is against the calls it would have refused**, on
the same stream, not against the book average. A filter is only worth its cost
if what it declines is worse than what it keeps.
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import statistics as st
import time

from till_infinity.trading.speeds import Speeds

DB = "/app/.data/journal/journal.db"
DAYS = float(os.environ.get("DAYS", "14"))


def run():
    now = time.time()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=180.0)
    since = now - DAYS * 86400

    decisions = {}
    for entry_id, ctx in conn.execute(
        "SELECT id, context FROM entries WHERE actor='structures' AND kind='decision' AND time>=?",
        (since,),
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if isinstance(d, dict):
            decisions[str(entry_id)] = d

    rows = []
    for when, parent, ctx in conn.execute(
        "SELECT time, parent, context FROM entries WHERE actor='structures' AND kind='outcome' "
        "AND time>=? AND parent IS NOT NULL ORDER BY time",
        (since,),
    ):
        try:
            o = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(o, dict) or str(o.get("outcome")) not in ("reject", "break"):
            continue
        p = decisions.get(str(parent))
        if p is None:
            continue
        feed = str(p.get("feed") or o.get("feed") or "")
        direction = str(p.get("direction") or "")
        edge = p.get("edge")
        if not feed or direction not in ("up", "down") or not isinstance(edge, (int, float)):
            continue
        rows.append(
            (float(when), feed, direction, float(edge), str(o.get("outcome")) == "reject",
             str(p.get("interval") or ""))
        )
    print(f"{len(rows)} decisive touches with a direction and an edge, {DAYS:.0f} days\n")

    # Replay in time order, exactly as the strategy would see them.
    speeds = Speeds()
    verdicts = []
    for when, feed, direction, edge, held, interval in rows:
        sign = 1 if direction == "up" else -1
        ready = speeds.ready(feed)
        agrees = speeds.agree(feed, sign) if ready else None
        speeds.observe(feed, edge)          # every call feeds it, taken or not
        verdicts.append((agrees, held, interval, feed, sign))

    warm = [v for v in verdicts if v[0] is not None]
    print(f"warm enough to judge: {len(warm)} of {len(verdicts)} "
          f"({len(warm)/max(1,len(verdicts)):.1%})")
    if len(warm) < 200:
        print("not enough")
        return

    taken = [v for v in warm if v[0]]
    refused = [v for v in warm if not v[0]]
    def held_of(part):
        return st.fmean([1 if v[1] else 0 for v in part]) if part else float("nan")

    print(f"\n  would take   {len(taken):6d}  held {held_of(taken):6.1%}")
    print(f"  would refuse {len(refused):6d}  held {held_of(refused):6.1%}")
    gap = held_of(taken) - held_of(refused)
    print(f"  {'gap':12s} {gap:+6.1%}")

    rng = random.Random(41)
    pool = [1 if v[1] else 0 for v in warm]
    cut = len(taken)
    beaten = 0
    for _ in range(1000):
        rng.shuffle(pool)
        if (st.fmean(pool[:cut]) - st.fmean(pool[cut:])) >= gap:
            beaten += 1
    print(f"  permutation p {beaten/1000:.3f}")

    print("\n  by interval (its entries are 1m/3m/5m/15m/30m):")
    for iv in ("1m", "3m", "5m", "15m", "30m", "1h"):
        part = [v for v in warm if v[2] == iv]
        t = [v for v in part if v[0]]
        r = [v for v in part if not v[0]]
        if len(t) >= 40 and len(r) >= 40:
            print(f"    {iv:5s} take {len(t):5d} held {held_of(t):6.1%}   "
                  f"refuse {len(r):5d} held {held_of(r):6.1%}   gap {held_of(t)-held_of(r):+6.1%}")

    print("\n  how selective it is, per feed (top by volume):")
    per = {}
    for v in warm:
        per.setdefault(v[3], [0, 0])
        per[v[3]][0] += 1
        per[v[3]][1] += 1 if v[0] else 0
    for feed, (n, t) in sorted(per.items(), key=lambda kv: -kv[1][0])[:8]:
        print(f"    {feed:24s} {n:5d} warm, would take {t:5d} ({t/n:5.1%})")


if __name__ == "__main__":
    run()
