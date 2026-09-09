"""What the risk changes of 2026-09-09 actually did to the book's mix.

Five settings moved that afternoon, four of them upward:

    max_positions           4  -> 10      total risk 2% -> 5%
    max_currency_exposure   1% -> 2.5%    so the 5% is reachable on FX
    instruments            42  -> 53      synthetics 9 -> 20
    volatility_target_bps  off -> 3.0     shrinks the hot instruments
    strategies             13  -> 10      the three largest losers removed

The first three raise exposure, the last two lower it, and they landed on a
book that was losing - -1,365 over 548 closes. The net is not knowable from
the record that existed before, because 41% of closes were unattributed until
the ticket-to-decision map shipped the same day.

**The question this answers is not "did it work".** Two days of trading cannot
say that. It is the narrower one the capacity argument in `scaling.by_interval`
actually made: *where do the extra slots go?* If they go to synthetics - which
the currency cap does not touch, and which are the loss centre in every
breakdown - the change made the concentration worse. If they go to the slower
signals that were being crowded out, it did what it was meant to.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
import time

DB = "/app/.data/journal/journal.db"
#: The afternoon the settings moved: 2026-09-09 18:20 UTC, the last of the five
#: deploys that carried them.
#:
#: Written out rather than computed, and checked on use - the first version of
#: this constant was twenty hours in the *future*, and `max(1.0, ...)` below
#: turned that into a confident "1.0 hours since the changes" instead of an
#: error. A clamp that makes a wrong number look plausible is worse than no
#: clamp.
CHANGED = 1788978000.0
SYNTHETIC = ("volatility", "boom", "crash", "step", "jump", "range_break")


def synthetic(feed: str) -> bool:
    return any(m in feed.lower() for m in SYNTHETIC)


def load(conn, lo, hi=None):
    rows = []
    q = "SELECT time, kind, context FROM entries WHERE actor='trading' AND time>=?"
    args: list = [lo]
    if hi:
        q += " AND time<?"
        args.append(hi)
    for when, kind, ctx in conn.execute(q, args):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(d, dict) or "profit" not in d:
            continue
        if kind == "outcome" or d.get("unattributed"):
            d["_when"] = float(when)
            rows.append(d)
    return rows


def describe(name, rows, hours):
    if not rows:
        print(f"  {name:14s} no closes")
        return
    profit = [float(d.get("profit") or 0) for d in rows]
    syn = [d for d in rows if synthetic(str(d.get("feed") or d.get("symbol") or ""))]
    attributed = [d for d in rows if not d.get("unattributed")]
    intervals = [str(d.get("interval") or "") for d in rows]
    known = [i for i in intervals if i]
    fast = sum(1 for i in known if i in ("1m", "3m", "5m"))
    print(
        f"  {name:14s} {len(rows):4d} closes ({len(rows) / hours:5.2f}/h)  "
        f"net {sum(profit):+9.2f}  won {sum(1 for p in profit if p > 0) / len(rows):5.1%}  "
        f"synthetic {len(syn) / len(rows):5.1%}  attributed {len(attributed) / len(rows):5.1%}  "
        f"interval known {len(known) / len(rows):5.1%}"
        + (f"  of those sub-15m {fast / len(known):5.1%}" if known else "")
    )


def run():
    now = time.time()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=180.0)
    after = load(conn, CHANGED)
    before = load(conn, CHANGED - 7 * 86400, CHANGED)
    elapsed = (now - CHANGED) / 3600
    if elapsed <= 0:
        print(f"CHANGED is {-elapsed:.1f} hours in the future - fix the constant")
        return
    hours_after = max(elapsed, 1e-6)
    print(f"{elapsed:.1f} hours since the changes")
    if elapsed < 24:
        print("**Too early to read the mix.** Reported anyway, and not to be argued from.\n")
    else:
        print()
    describe("before (7d)", before, 7 * 24)
    describe("after", after, hours_after)

    print("\n  where the extra slots went, after the change:")
    book: dict[str, list] = {}
    for d in after:
        feed = str(d.get("feed") or d.get("symbol") or "?")
        book.setdefault(feed, []).append(float(d.get("profit") or 0))
    for feed, ps in sorted(book.items(), key=lambda kv: sum(kv[1])):
        tag = "synthetic" if synthetic(feed) else ""
        print(f"    {feed:26s} {len(ps):4d} {sum(ps):+9.2f}  {tag}")

    print("\n  the eleven instruments added that afternoon:")
    added = ("jump_10", "jump_25", "crash_300", "crash_500", "range_break", "_1s_")
    new = [d for d in after if any(a in str(d.get("feed") or "") for a in added)]
    if new:
        ps = [float(d.get("profit") or 0) for d in new]
        print(f"    {len(new)} closes, net {sum(ps):+9.2f}, mean {st.fmean(ps):+7.2f}")
    else:
        print("    none have closed yet")

    print("\n  capacity refusals, before and after:")
    for label, lo, hi in (("before", CHANGED - 7 * 86400, CHANGED), ("after", CHANGED, None)):
        q = ("SELECT rationale FROM entries WHERE actor='trading' AND time>=?"
             + (" AND time<?" if hi else ""))
        args = [lo] + ([hi] if hi else [])
        n = sum(
            1
            for (why,) in conn.execute(q, args)
            if why and ("max_positions" in str(why) or "currency" in str(why))
        )
        print(f"    {label:7s} {n}")


if __name__ == "__main__":
    run()
