"""Is `in_origin` worth acting on, or is it a confound?

Standing inside an origin looked worse for both directions - sells 80.7%
against 81.9%, buys 81.9% against 84.4%. Small, and this folder has had two
effects this week that did not survive their controls, so it is tested before
it is used.

Three ways it could be spurious, each checked:

* **The interval.** Origins are found per timeframe and touches are not evenly
  spread across them, so `in_origin` could be a proxy for "this was a 1m
  touch". Conditioned on interval.
* **The instrument.** Same argument - the synthetics both dominate the touch
  count and behave differently.
* **Chance.** A permutation test rather than a p-value taken on faith.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import statistics as st
import time

DB = "/app/.data/journal/journal.db"
DAYS = float(os.environ.get("DAYS", "7"))


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
    for parent, ctx in conn.execute(
        "SELECT parent, context FROM entries WHERE actor='structures' AND kind='outcome' "
        "AND time>=? AND parent IS NOT NULL",
        (since,),
    ):
        try:
            o = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(o, dict) or str(o.get("outcome")) not in ("reject", "break"):
            continue
        p = decisions.get(str(parent))
        if p is None or not isinstance(p.get("in_origin"), (int, float)):
            continue
        rows.append(
            (
                bool(p["in_origin"]),
                str(o.get("outcome")) == "reject",
                str(p.get("direction") or ""),
                str(p.get("interval") or o.get("interval") or ""),
                str(p.get("feed") or o.get("feed") or ""),
            )
        )
    print(f"{len(rows)} decisive touches carrying in_origin\n")
    rng = random.Random(31)

    def split(part, label):
        inside = [1 if h else 0 for i, h, _, _, _ in part if i]
        outside = [1 if h else 0 for i, h, _, _, _ in part if not i]
        if len(inside) < 40 or len(outside) < 40:
            print(f"  {label:34s} too few ({len(inside)} / {len(outside)})")
            return None
        gap = st.fmean(inside) - st.fmean(outside)
        pool = inside + outside
        cut = len(inside)
        worse = 0
        for _ in range(1000):
            rng.shuffle(pool)
            if (st.fmean(pool[:cut]) - st.fmean(pool[cut:])) <= gap:
                worse += 1
        print(
            f"  {label:34s} inside {st.fmean(inside):6.1%} ({len(inside):5d})  "
            f"outside {st.fmean(outside):6.1%} ({len(outside):5d})  "
            f"gap {gap:+6.1%}  p {worse / 1000:.3f}"
        )
        return gap

    print("pooled:")
    split(rows, "every touch")
    for d in ("down", "up"):
        split([r for r in rows if r[2] == d], f"{'sells' if d == 'down' else 'buys'}")

    print("\nwithin each interval (is it a timeframe proxy?):")
    for interval in sorted({r[3] for r in rows}):
        part = [r for r in rows if r[3] == interval]
        if len(part) >= 400:
            split(part, interval)

    print("\nwithin each instrument, the busiest ten:")
    counts = {}
    for r in rows:
        counts[r[4]] = counts.get(r[4], 0) + 1
    gaps = []
    for feed in sorted(counts, key=lambda f: -counts[f])[:10]:
        got = split([r for r in rows if r[4] == feed], feed)
        if got is not None:
            gaps.append(got)
    if gaps:
        print(
            f"\n  across those instruments: median gap {st.median(gaps):+.1%}, "
            f"{sum(1 for g in gaps if g < 0)}/{len(gaps)} negative"
        )


if __name__ == "__main__":
    run()
