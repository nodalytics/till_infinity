"""Where the journal lives.

Append-only, and that is enforced rather than promised: writes are
`INSERT OR IGNORE` on a content-addressed id, there is no update path, and an
outcome is a *new* entry pointing back at the decision it judges. A journal you
can edit is not a journal - the value of "why we thought that at the time" is
entirely in nobody having tidied it up afterwards.

Reads open the file `mode=ro`, the same guarantee the agents' data views give,
so an analyst reading its own history cannot rewrite it.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..logging import get_logger
from .models import Entry, Kind

log = get_logger(__name__)

DEFAULT_DB = ".data/journal/journal.db"

#: How many entries a listing shows before it stops being readable. A display
#: ceiling, not a storage one - `read` honours whatever limit it is given, and
#: this is the default the CLI reaches for.
MAX_ROWS = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          TEXT PRIMARY KEY,
    time        REAL NOT NULL,
    kind        TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL,
    rationale   TEXT NOT NULL DEFAULT '',
    context     TEXT NOT NULL DEFAULT '{}',
    tags        TEXT NOT NULL DEFAULT '[]',
    confidence  REAL,
    parent      TEXT NOT NULL DEFAULT '',
    written     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_time   ON entries (time DESC);
CREATE INDEX IF NOT EXISTS entries_kind   ON entries (kind, time DESC);
CREATE INDEX IF NOT EXISTS entries_actor  ON entries (actor, time DESC);
CREATE INDEX IF NOT EXISTS entries_parent ON entries (parent) WHERE parent != '';
"""

_INSERT = """
INSERT OR IGNORE INTO entries
    (id, time, kind, actor, title, rationale, context, tags, confidence, parent, written)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class Journal:
    """The writer. One connection, WAL, opened lazily."""

    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> Journal:
        await self.open()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def open(self) -> None:
        await asyncio.to_thread(self._connect)

    def _connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.executescript(SCHEMA)
        conn.commit()
        self._conn = conn

    async def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            await asyncio.to_thread(conn.close)

    def _require(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("journal is not open")
        return self._conn

    async def write(self, entries: Entry | Sequence[Entry]) -> int:
        """Append. Returns how many were new - re-writing one is not an error."""
        batch = [entries] if isinstance(entries, Entry) else list(entries)
        if not batch:
            return 0
        async with self._lock:
            return await asyncio.to_thread(self._write, batch)

    def _write(self, batch: list[Entry]) -> int:
        conn = self._require()
        now = time.time()
        rows = [
            (
                entry.id,
                entry.time,
                str(entry.kind),
                entry.actor,
                entry.title,
                entry.rationale,
                json.dumps(entry.context, default=str),
                json.dumps(list(entry.tags)),
                entry.confidence,
                entry.parent,
                now,
            )
            for entry in batch
        ]
        before = conn.total_changes
        with conn:
            conn.executemany(_INSERT, rows)
        return conn.total_changes - before

    async def entries(self, **filters: Any) -> list[Entry]:
        async with self._lock:
            return await asyncio.to_thread(lambda: read(self.path, **filters))


# ------------------------------------------------------------------- reading


@contextmanager
def read_only(path: Path | str) -> Iterator[sqlite3.Connection]:
    """Open the journal read-only. Nothing that reads history can rewrite it."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"no journal at {target} - nothing has been recorded yet")
    conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def read(
    path: Path | str = DEFAULT_DB,
    *,
    kind: str | Kind | None = None,
    actor: str = "",
    tag: str = "",
    parent: str | None = None,
    since: float | None = None,
    hours: float | None = None,
    limit: int = 50,
) -> list[Entry]:
    """Most recent first. Every filter is optional and they compose.

    `limit` is honoured as asked. It used to be silently clamped to `MAX_ROWS`,
    which made the argument a suggestion: `facto.dataset` asked for 200,000 rows
    to assemble its training examples, received the most recent 500, and found
    ~167 usable outcomes in a journal holding 9,359 of them. Nothing reported a
    truncation, so the shortfall read as a data problem - outcomes recorded
    without their features - rather than as a window that was never opened.

    `MAX_ROWS` remains what it always was in practice: the ceiling the CLI puts
    on a listing so a long history cannot flood a terminal. That is a display
    concern, and it belongs to the display. A caller that names a number is
    stating what it can hold, and the callers here bound themselves.
    """
    where: list[str] = []
    params: list[Any] = []
    if kind:
        where.append("kind = ?")
        params.append(str(kind))
    if actor:
        where.append("actor = ?")
        params.append(actor)
    if tag:
        # tags is a JSON array; quoting the needle stops "gold" matching "golden"
        where.append("tags LIKE ?")
        params.append(f'%"{tag}"%')
    if parent is not None:
        where.append("parent = ?")
        params.append(parent)
    if hours is not None:
        since = time.time() - hours * 3600
    if since is not None:
        where.append("time >= ?")
        params.append(since)

    clause = f" WHERE {' AND '.join(where)}" if where else ""
    params.append(max(1, int(limit)))
    with read_only(path) as conn:
        rows = conn.execute(
            f"SELECT * FROM entries{clause} ORDER BY time DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    return [Entry.from_row(row) for row in rows]


def get(path: Path | str, entry_id: str) -> Entry | None:
    with read_only(path) as conn:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return Entry.from_row(row) if row else None


def summary(path: Path | str = DEFAULT_DB) -> list[dict[str, Any]]:
    """What is in there, by actor and kind."""
    with read_only(path) as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT actor, kind, COUNT(*) AS entries, MIN(time) AS first, MAX(time) AS last"
                " FROM entries GROUP BY actor, kind ORDER BY entries DESC"
            )
        ]


def export(path: Path | str = DEFAULT_DB, *, target: Path | None = None, **filters: Any) -> int:
    """Write the journal out as JSON lines, oldest first.

    Oldest first because that is the order a sequence model wants, and one
    object per line because that is what every dataframe loader reads without
    argument. `context` stays nested - flattening it here would bake in one
    guess about which features matter.
    """
    filters.setdefault("limit", MAX_ROWS)
    rows = sorted(read(path, **filters), key=lambda entry: entry.time)
    lines = [json.dumps(entry.to_dict(), default=str) for entry in rows]
    payload = "\n".join(lines) + ("\n" if lines else "")
    if target is None:
        print(payload, end="")
    else:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(payload)
    return len(rows)
