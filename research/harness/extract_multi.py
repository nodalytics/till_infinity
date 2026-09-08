"""Build a research extract for the multi-asset test, from prices.db.

`bt1m.db` carries eight feeds and neither `usdcad` nor `silver`, and prices.db
has no index on `feed` - so a scan per feed is one pass over five million rows
each. One pass over the whole table, filtered in Python, is cheaper than
twenty-two of them.
"""
import sqlite3
import sys
import time

WANT = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else set()
OUT = "/app/.data/research/multi.db"

src = sqlite3.connect("file:/app/.data/prices/prices.db?mode=ro", uri=True, timeout=300)
src.execute("PRAGMA mmap_size=268435456")
dst = sqlite3.connect(OUT)
dst.executescript(
    "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;"
    "DROP TABLE IF EXISTS bars;"
    "CREATE TABLE bars (feed TEXT, venue TEXT, ts INTEGER, open REAL, high REAL,"
    " low REAL, close REAL, volume REAL);"
)
started = time.time()
kept = 0
seen = {}
batch = []
for feed, venue, ts, o, h, low, c, v in src.execute(
    "SELECT feed, venue, ts, open, high, low, close, volume FROM bars WHERE interval='1m'"
):
    seen[feed] = seen.get(feed, 0) + 1
    if WANT and feed not in WANT:
        continue
    if h is None or low is None or c is None or h <= low:
        continue
    batch.append((feed, venue, ts, o, h, low, c, v))
    if len(batch) >= 50_000:
        dst.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?)", batch)
        kept += len(batch)
        batch = []
if batch:
    dst.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?)", batch)
    kept += len(batch)
dst.execute("CREATE INDEX bars_feed_ts ON bars (feed, venue, ts)")
dst.commit()
print("kept %d rows in %.0fs" % (kept, time.time() - started))
print("feeds present in prices.db at 1m (%d):" % len(seen))
for feed in sorted(seen, key=lambda f: -seen[f]):
    print("  %-28s %8d" % (feed, seen[feed]))
