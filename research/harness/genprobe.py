"""Throwaway probe: what is actually in research.db, for the generator study."""
from __future__ import annotations
import os, sqlite3

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
print("tables:", [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")])
for t in ("bars", "ticks"):
    try:
        print(t, "schema:", conn.execute(f"SELECT sql FROM sqlite_master WHERE name='{t}'").fetchone()[0])
    except Exception as e:
        print(t, "err", e)
print("--- bars by feed/interval ---")
for feed, interval, n, lo, hi in conn.execute(
    "SELECT feed, interval, COUNT(*), MIN(ts), MAX(ts) FROM bars GROUP BY feed, interval ORDER BY feed, interval"
):
    print(f"{feed:32s} {interval:5s} {n:8d} {lo} {hi}")
print("--- ticks by feed ---")
try:
    for feed, n, lo, hi in conn.execute(
        "SELECT feed, COUNT(*), MIN(ts), MAX(ts) FROM ticks GROUP BY feed ORDER BY feed"
    ):
        print(f"{feed:32s} {n:9d} {lo} {hi}")
except Exception as e:
    print("ticks err", e)
