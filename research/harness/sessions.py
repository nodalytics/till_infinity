"""What it costs to cross, by hour of the day.

research/paying.md priced every instrument at one instant - around 08:45 UTC,
which is the cheapest hour of the day for FX. Two live-money decisions rest on
those rows and the FX ones sit closest to zero, so the number they rest on is
the best case rather than a typical one.

No need to wait for the sessions to come round: `prices.quotes` has carried
`spread_bps` all along. This reads the stored quotes, converts each to
volatility units against the instrument's own estimate, and buckets by UTC
hour.

A spread in volatility units is what `charge_spread` actually deducts, and it
is the only form comparable across instruments - the synthetics quote a median
230 points against FX's 12 and are ten times *cheaper* in the currency that
matters.
"""

from __future__ import annotations

import sqlite3
import statistics as st
import time
from collections import defaultdict
from datetime import UTC, datetime

PRICES = "file:/app/.data/prices/prices.db?mode=ro"

#: Days of quotes to read. Bounded because the table is millions of rows, and
#: because a spread from three weeks ago is not evidence about today's cost.
DAYS = 4

#: The hours each session owns, in UTC. Deliberately coarse: the question is
#: "is the London number the whole story", not where exactly Tokyo ends.
SESSIONS = (
    ("Sydney/Tokyo", range(7)),
    ("London", range(7, 12)),
    ("London/NY overlap", range(12, 17)),
    ("New York", range(17, 21)),
    ("thin hours", range(21, 24)),
)


def volatility(conn) -> dict[str, float]:
    """One volatility estimate per feed, from its 5m closes."""
    from till_infinity.structures.vol.volatility import Volatility

    out: dict[str, float] = {}
    feeds = [f for (f,) in conn.execute("SELECT DISTINCT feed FROM bars")]
    for feed in feeds:
        rows = conn.execute(
            "SELECT close FROM bars WHERE feed=? AND interval='5m' ORDER BY ts DESC LIMIT 500",
            (feed,),
        ).fetchall()
        if len(rows) < 100:
            continue
        vol = Volatility()
        for (c,) in reversed(rows):
            vol.update(float(c))
        if vol.warm and vol.bps > 0:
            out[feed] = vol.bps
    return out


def main() -> None:
    conn = sqlite3.connect(PRICES, uri=True)
    bps = volatility(conn)
    print(f"{len(bps)} instruments with a warm volatility estimate\n")

    #: feed -> hour -> [spread in volatility units]
    seen: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    # Sampled, not scanned. The quotes table is millions of rows and a full
    # pass with per-row work in Python does not finish.
    #
    # Sampled on `ts` rather than `rowid`, because the table is WITHOUT ROWID
    # and has none - the obvious version raises "no such column: rowid". The
    # timestamp is in milliseconds, so this keeps one quote per twenty
    # milliseconds of clock, which is a fair sample of a feed that quotes at
    # most a few times a second.
    # Bounded by time rather than sampled. `CAST(ts) % n` cannot use an index
    # and reads every row anyway; a `ts >=` bound can. The last DAYS days is
    # also the right window on its own terms - a spread from three weeks ago is
    # not evidence about what it costs to trade now.
    since = (time.time() - DAYS * 86_400) * 1000.0
    for feed, ts, spread in conn.execute(
        "SELECT feed, ts, spread_bps FROM quotes"
        " WHERE ts >= ? AND spread_bps IS NOT NULL AND spread_bps > 0",
        (since,),
    ):
        own = bps.get(str(feed))
        if not own:
            continue
        # `quotes.ts` is in **milliseconds** where `bars.ts` is in seconds, and
        # nothing in the schema says so. Read as seconds it dates to the year
        # 58630. The same ms/s confusion has cost this project twice before, so
        # this accepts either rather than assuming which arrived.
        when = float(ts)
        if when > 1e11:
            when /= 1000.0
        hour = datetime.fromtimestamp(when, UTC).hour
        seen[str(feed)][hour].append(float(spread) / own)

    names = [n for n, _ in SESSIONS]
    print(f"{'feed':22s} " + "".join(f"{n[:13]:>15s}" for n in names))
    rows = []
    for feed in sorted(seen):
        per = []
        for _name, hours in SESSIONS:
            got = [v for h in hours for v in seen[feed].get(h, ())]
            per.append(st.median(got) if len(got) >= 20 else None)
        if sum(1 for v in per if v is not None) < 3:
            continue
        rows.append((feed, per))
        cells = "".join(f"{v:15.3f}" if v is not None else f"{'-':>15s}" for v in per)
        print(f"{feed:22s}{cells}")

    print()
    for i, (name, _h) in enumerate(SESSIONS):
        got = [p[i] for _f, p in rows if p[i] is not None]
        if got:
            print(
                f"   {name:20s} median across instruments {st.median(got):.3f}v  ({len(got)} feeds)"
            )

    print("\nwidest hour against cheapest, per instrument:")
    for feed, per in rows:
        got = [v for v in per if v is not None]
        if len(got) >= 3 and min(got) > 0:
            print(f"   {feed:22s} {min(got):.3f}v to {max(got):.3f}v  ({max(got) / min(got):.1f}x)")


if __name__ == "__main__":
    main()
