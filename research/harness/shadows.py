"""Did the trades that were stopped go on to reach their target?

A stop hit at full size looks identical whether the level failed or the stop
sat inside the noise, and the account cannot tell them apart. That single
ambiguity has driven most of the stop-width argument, and nothing measured it.

The live watcher built for this holds pending shadows **in memory**, so every
container restart discards them. With a two-hour window and a development day
of frequent deploys, not one ever survived to report - the watch was
decorative. This is the durable version: the close already records the entry,
the stop, the target and the time, so the question can be answered afterwards
from price history, retroactively, for every loss ever taken.

The worked example this was written after: a us30 short filled at 53519 and
stopped at 53525. Fourteen minutes later price ran to 53529.8 - through the
stop - and then dropped to 53439, eighty points *through* the entry. The
thesis was right, the stop was six points away, and the move needed it to
survive eleven. That is not a level failing. It is a stop too tight relative to
where the fill landed, which is a different problem with a different fix.

Usage:

    uv run python research/harness/shadows.py journal.db prices.db
"""

import asyncio
import json
import sqlite3
import sys

from till_infinity.prices.store import SqliteStore


def losses(db):
    """Every losing trade, with what it was aiming at."""
    con = sqlite3.connect(db)
    out = []
    q = "select time, context from entries where actor='trading' and kind='outcome'"
    for when, ctx in con.execute(q):
        d = json.loads(ctx or "{}")
        if (d.get("profit") or 0.0) >= 0:
            continue
        if not d.get("target") or not d.get("entry"):
            continue
        out.append(
            {
                "when": float(when),
                "feed": d.get("feed") or "",
                "side": str(d.get("side") or ""),
                "entry": float(d["entry"]),
                "stop": float(d.get("stop") or 0.0),
                "target": float(d["target"]),
                "profit": float(d.get("profit") or 0.0),
                "strategy": d.get("strategy") or "?",
                "seconds": float(d.get("seconds") or 0.0),
            }
        )
    return out


#: Interval names smallest first. `SeriesKey.interval` is the name, and the
#: seconds live on `Interval` rather than being derivable from the string, so
#: the ordering is written out rather than computed from a method that does not
#: exist - which is what the first draft of this assumed.
FINENESS = ("1m", "3m", "5m", "15m", "1h", "4h", "1d", "1w")


async def after(store, feed, when, horizon):
    """Highs and lows on the finest series available, after `when`."""
    best = None
    for info in await store.series():
        key = info.key
        if key.feed != feed or key.interval not in FINENESS:
            continue
        if best is None or FINENESS.index(key.interval) < FINENESS.index(best.interval):
            best = key
    if best is None:
        return []
    bars = await store.bars(best, limit=4000)
    return [b for b in bars if when <= b.time <= when + horizon]


async def main():
    jdb = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    pdb = sys.argv[2] if len(sys.argv) > 2 else ".data/prices.db"
    rows = losses(jdb)
    print(f"{len(rows)} losing trades\n")
    if not rows:
        return

    store = SqliteStore(pdb)
    await store.open()
    try:
        print(f"{'when':6s} {'feed':8s} {'strategy':14s} {'verdict':12s} {'best R':>7s}")
        print("-" * 52)
        won = 0
        for r in rows:
            horizon = max(r["seconds"] * 4, 3600)
            bars = await after(store, r["feed"], r["when"], horizon)
            if not bars:
                print(f"{'':6s} {r['feed']:8s} {r['strategy'][:14]:14s} {'no prices':12s}")
                continue
            sign = 1 if r["side"].lower().endswith("buy") else -1
            reach = max((b.high if sign > 0 else -b.low) for b in bars) * sign
            risk = abs(r["entry"] - r["stop"]) or 1.0
            got = (reach - r["entry"]) * sign / risk
            hit = (reach - r["target"]) * sign >= 0
            won += hit
            import datetime

            hh = datetime.datetime.utcfromtimestamp(r["when"]).strftime("%H:%M")
            print(
                f"{hh:6s} {r['feed']:8s} {r['strategy'][:14]:14s} "
                f"{('WOULD HAVE WON' if hit else 'still lost')[:12]:12s} {got:+7.2f}"
            )
        print(f"\n{won} of {len(rows)} stopped trades later reached their target.")
        print("Above 1.00R means the stop cost a trade that was right.")
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
