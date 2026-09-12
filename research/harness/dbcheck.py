"""Which of the lab's stores is actually corrupt, and which was only assumed to be.

`feed.py`'s docstring says both `research.db` and `prices.db` read back
"database disk image is malformed". That was written from one study's failure
and never checked per file, and a second study may have been downgraded to a
twentieth of its sample on the strength of it. This settles it.

`PRAGMA quick_check` rather than `integrity_check`: the question is whether the
pages are readable, not whether every index is consistent, and on a store this
size the full walk is the expensive answer to a cheap question.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: Where the lab keeps them. Both are looked for rather than assumed present.
ROOTS = (Path.home(), Path.home() / "till_infinity")


def find(name: str) -> Path | None:
    for root in ROOTS:
        for path in root.rglob(name):
            return path
    return None


def check(path: Path) -> str:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60.0)
    except sqlite3.Error as exc:
        return f"cannot open: {exc}"
    try:
        verdict = conn.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        return f"quick_check raised: {exc}"
    tables = [
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    ]
    counted, broken = [], []
    for table in tables[:12]:
        try:
            got = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            counted.append(f"{table}={got:,}")
        except sqlite3.DatabaseError as exc:
            broken.append(f"{table}: {str(exc)[:40]}")
    conn.close()
    out = [f"quick_check: {verdict}", f"tables: {len(tables)}"]
    if counted:
        out.append("scanned " + ", ".join(counted[:6]))
    if broken:
        out.append("UNREADABLE " + "; ".join(broken))
    return " | ".join(out)


if __name__ == "__main__":
    for name in ("research.db", "prices.db"):
        path = find(name)
        if path is None:
            print(f"{name:14} not found")
            continue
        size = path.stat().st_size / 1e9
        print(f"{name:14} {size:.2f}GB at {path}")
        print(f"               {check(path)}")
