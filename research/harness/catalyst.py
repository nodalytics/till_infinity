"""Does a catalyst change the rate of going nowhere? Todo 7g.

Technicals say where and which way; news decides which instrument has a reason
to travel. The testable half is that **structure without a catalyst is a trade
that expires rather than one that loses** - it reaches neither the stop nor the
target and is closed by the clock.

## What a catalyst is here

`news.db` has three tables and only one is usable for this. `articles` carries
a `symbols` column and it is **`[]` on all 24,214 rows** - the field exists and
has never been populated, so RSS cannot be linked to an instrument at all.
`observations` is weekly COT, which is not a catalyst. That leaves `events`:
the economic calendar, tagged by country or currency.

So a catalyst is a **scheduled calendar item for a currency the instrument is
priced in**, inside a window ending at the entry.

## The three traps, each of which has already cost a wrong answer here

* **The window ends at the entry, never spans it.** An event landing after
  entry explains a move the trade caught by luck.
* **The control is matched on busyness, not on the absence of news.** Trades
  and events both cluster in the active session, so an unmatched comparison
  measures the clock. Matching is on the instrument and the hour of day.
* **The synthetics are the control that cannot be argued with.** Deriv's
  indices are generated, have no underlying and no calendar. They are given the
  *same US calendar flag* anyway: if the effect appears on instruments the
  events cannot possibly reach, the effect is the time of day.
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import sqlite3
import statistics as st
import time

NEWS = "/app/.data/news/news.db"
JOURNAL = "/app/.data/journal/journal.db"
DAYS = float(os.environ.get("DAYS", "45"))
#: How long before the entry a calendar item still counts, in seconds.
WINDOW = float(os.environ.get("WINDOW", str(2 * 3600)))
#: Calendar importance to require. 0 keeps everything the source published.
IMPORTANCE = int(os.environ.get("IMPORTANCE", "0"))

#: Which calendar tags move which instrument. Both ISO country and currency
#: codes appear in the feed - `US` and `USD` are the same source disagreeing
#: with itself - so both forms are listed.
TAGS: dict[str, tuple[str, ...]] = {
    "eurusd": ("EUR", "EU", "DE", "FR", "IT", "US", "USD"),
    "gbpusd": ("GBP", "GB", "UK", "US", "USD"),
    "usdjpy": ("JPY", "JP", "US", "USD"),
    "usdcad": ("CAD", "CA", "US", "USD"),
    "usdchf": ("CHF", "CH", "US", "USD"),
    "audusd": ("AUD", "AU", "US", "USD"),
    "nzdusd": ("NZD", "NZ", "US", "USD"),
    # Dollar-priced, so the dollar calendar is its calendar.
    "gold": ("US", "USD"),
    "silver": ("US", "USD"),
    "spx500": ("US", "USD"),
    "us100": ("US", "USD"),
    # Crypto has no calendar of its own and does respond to US macro.
    "btc": ("US", "USD"),
    "eth": ("US", "USD"),
}
#: Generated instruments. No underlying, no calendar, no channel - the control.
SYNTHETIC = ("volatility", "boom", "crash", "step", "jump", "range_break")


def synthetic(feed: str) -> bool:
    return any(mark in feed.lower() for mark in SYNTHETIC)


def load_events(conn, since):
    """Event times per tag, sorted, so a lookup is a bisect."""
    book: dict[str, list[float]] = {}
    for when, country, importance in conn.execute(
        "SELECT time, country, importance FROM events WHERE time >= ?", (since,)
    ):
        if not isinstance(when, (int, float)) or country is None:
            continue
        if (importance or 0) < IMPORTANCE:
            continue
        book.setdefault(str(country).upper(), []).append(float(when))
    for tag in book:
        book[tag].sort()
    return book


def had_catalyst(book, tags, entry) -> bool:
    """Whether any of these tags printed inside the window **ending** at entry."""
    floor = entry - WINDOW
    for tag in tags:
        stamps = book.get(tag)
        if not stamps:
            continue
        if bisect.bisect_right(stamps, entry) > bisect.bisect_right(stamps, floor):
            return True
    return False


def load_trades(conn, since):
    out = []
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE actor='trading' AND kind='outcome' AND time>=?",
        (since,),
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(d.get("r_multiple"), (int, float)):
            continue
        held = d.get("seconds")
        if not isinstance(held, (int, float)) or held < 0:
            continue
        # The journal stamps the *outcome*; the entry is that long before it.
        out.append(
            {
                "entry_at": float(when) - float(held),
                "feed": str(d.get("feed") or ""),
                "exit": str(d.get("exit_kind") or "?"),
                "r": float(d["r_multiple"]),
                "profit": float(d.get("profit") or 0.0),
                "strategy": str(d.get("strategy") or "?"),
            }
        )
    return out


def expired(trade) -> bool:
    return trade["exit"] in ("hold", "stale")


def report(label, rows):
    if len(rows) < 12:
        print(f"  {label:34s} {len(rows):4d} trades - too few to report")
        return None
    share = sum(1 for t in rows if expired(t)) / len(rows)
    rs = [t["r"] for t in rows]
    print(
        f"  {label:34s} {len(rows):4d} trades  expired {share:5.1%}  "
        f"mean {st.fmean(rs):+6.3f}R  net {sum(t['profit'] for t in rows):+9.2f}"
    )
    return share


def main():
    now = time.time()
    since = now - DAYS * 86400
    news = sqlite3.connect(f"file:{NEWS}?mode=ro", uri=True, timeout=90)
    book = load_events(news, since - WINDOW)
    trades = load_trades(sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=90), since)
    print(
        f"{len(trades)} closed trades over {DAYS:.0f} days; calendar window "
        f"{WINDOW / 3600:.0f}h, importance >= {IMPORTANCE}\n"
    )

    real = [t for t in trades if not synthetic(t["feed"])]
    synth = [t for t in trades if synthetic(t["feed"])]
    for t in trades:
        tags = TAGS.get(t["feed"].lower(), ())
        t["catalyst"] = had_catalyst(book, tags, t["entry_at"]) if tags else None
        # The control flag: the US calendar applied to instruments it cannot
        # possibly reach.
        t["placebo"] = had_catalyst(book, ("US", "USD"), t["entry_at"])
        t["hour"] = dt.datetime.fromtimestamp(t["entry_at"], dt.timezone.utc).hour

    print("real instruments, split by whether a calendar item preceded the entry:")
    with_c = [t for t in real if t["catalyst"] is True]
    without = [t for t in real if t["catalyst"] is False]
    a = report("catalyst in the window", with_c)
    b = report("none", without)
    if a is not None and b is not None:
        print(f"  {'difference in expiry share':34s} {a - b:+6.1%}")

    print("\nsynthetics, given the same US calendar flag (it cannot reach them):")
    a = report("flag set", [t for t in synth if t["placebo"]])
    b = report("flag clear", [t for t in synth if not t["placebo"]])
    if a is not None and b is not None:
        print(f"  {'difference in expiry share':34s} {a - b:+6.1%}  <- should be ~0")

    print("\nmatched on instrument and hour of day (real instruments):")
    cells: dict[tuple[str, int], list] = {}
    for t in real:
        if t["catalyst"] is None:
            continue
        cells.setdefault((t["feed"], t["hour"]), []).append(t)
    paired = []
    for rows in cells.values():
        yes = [t for t in rows if t["catalyst"]]
        no = [t for t in rows if not t["catalyst"]]
        if yes and no:
            paired.append(
                (
                    sum(1 for t in yes if expired(t)) / len(yes),
                    sum(1 for t in no if expired(t)) / len(no),
                    len(yes) + len(no),
                )
            )
    if len(paired) < 5:
        print(f"  only {len(paired)} cells carry both - not reportable")
    else:
        gaps = [y - n for y, n, _ in paired]
        print(
            f"  {len(paired)} cells with both, {sum(c for _, _, c in paired)} trades: "
            f"median gap {st.median(gaps):+6.1%}, mean {st.fmean(gaps):+6.1%}, "
            f"{sum(1 for g in gaps if g < 0)}/{len(gaps)} cells expire less with a catalyst"
        )

    print("\nfor reference, the expiry share overall:")
    report("every trade", trades)
    report("real instruments", real)
    report("synthetics", synth)


if __name__ == "__main__":
    main()
