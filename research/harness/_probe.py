import os, sqlite3, json, datetime as dt
DATA = os.path.expanduser("~/till_infinity/data")
j = sqlite3.connect(f"file:{os.path.join(DATA,'journal.db')}?mode=ro", uri=True)
print("schema:", j.execute("SELECT sql FROM sqlite_master WHERE name='entries'").fetchone()[0])
print("time range:", j.execute("SELECT MIN(time), MAX(time) FROM entries").fetchone())
for k in ("outcome","decision","observation"):
    r = j.execute("SELECT actor, COUNT(*) FROM entries WHERE kind=? GROUP BY actor ORDER BY 2 DESC LIMIT 8", (k,)).fetchall()
    print(k, r)
    row = j.execute("SELECT id,time,kind,actor,title,rationale,context,tags FROM entries WHERE kind=? ORDER BY id DESC LIMIT 1", (k,)).fetchone()
    print("  sample:", str(row)[:1400])
