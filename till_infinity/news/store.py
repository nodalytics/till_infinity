"""Where headlines and events land: SQLite by default, JSONL alongside it.

The two tables behave differently on purpose. A headline is written once and
never touched again - `INSERT OR IGNORE` is the whole story. A calendar event
is the opposite: it sits there as a forecast for days, and when the print lands
the row is *rewritten* with the actual. Polling the same window repeatedly is
the point, so the upsert only fires when a field genuinely changed.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Self

import orjson

from .models import Article, Event, FeedInfo, Observation, WriteResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    source    TEXT    NOT NULL,
    id        TEXT    NOT NULL,
    published REAL,
    title     TEXT    NOT NULL,
    url       TEXT,
    provider  TEXT,
    summary   TEXT,
    symbols   TEXT,
    urgency   INTEGER,
    fetched   REAL    NOT NULL,
    PRIMARY KEY (source, id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS articles_published ON articles (published DESC);

CREATE TABLE IF NOT EXISTS events (
    source     TEXT    NOT NULL,
    id         TEXT    NOT NULL,
    time       REAL,
    title      TEXT    NOT NULL,
    country    TEXT,
    importance INTEGER NOT NULL DEFAULT 0,
    actual     TEXT,
    forecast   TEXT,
    previous   TEXT,
    unit       TEXT,
    period     TEXT,
    updated    REAL    NOT NULL,
    PRIMARY KEY (source, id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS events_time ON events (time DESC);
CREATE INDEX IF NOT EXISTS events_importance ON events (importance DESC, time DESC);

CREATE TABLE IF NOT EXISTS observations (
    source    TEXT    NOT NULL,
    series    TEXT    NOT NULL,
    time      REAL    NOT NULL,
    value     REAL    NOT NULL,
    scale     INTEGER NOT NULL DEFAULT 0,
    country   TEXT,
    indicator TEXT,
    frequency TEXT,
    period    TEXT,
    updated   REAL    NOT NULL,
    PRIMARY KEY (source, series, time)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS observations_country ON observations (country, time DESC);
"""

_UPSERT_OBSERVATION = """
INSERT INTO observations
    (source, series, time, value, scale, country, indicator, frequency, period, updated)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (source, series, time) DO UPDATE SET
    value = excluded.value,
    scale = excluded.scale,
    updated = excluded.updated
WHERE observations.value IS NOT excluded.value
   OR observations.scale IS NOT excluded.scale
"""

_INSERT_ARTICLE = """
INSERT OR IGNORE INTO articles
    (source, id, published, title, url, provider, summary, symbols, urgency, fetched)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPSERT_EVENT = """
INSERT INTO events
    (source, id, time, title, country, importance, actual, forecast, previous,
     unit, period, updated)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (source, id) DO UPDATE SET
    time = excluded.time,
    title = excluded.title,
    country = excluded.country,
    importance = excluded.importance,
    actual = excluded.actual,
    forecast = excluded.forecast,
    previous = excluded.previous,
    unit = excluded.unit,
    period = excluded.period,
    updated = excluded.updated
WHERE events.actual IS NOT excluded.actual
   OR events.forecast IS NOT excluded.forecast
   OR events.previous IS NOT excluded.previous
   OR events.time IS NOT excluded.time
"""


class Store(ABC):
    """Persists headlines and calendar events."""

    name: str

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    @abstractmethod
    async def write_articles(self, articles: Sequence[Article]) -> WriteResult: ...

    @abstractmethod
    async def write_events(self, events: Sequence[Event]) -> WriteResult: ...

    @abstractmethod
    async def write_observations(self, rows: Sequence[Observation]) -> WriteResult: ...

    @abstractmethod
    async def feeds(self) -> list[FeedInfo]: ...


class SqliteStore(Store):
    """One database file, one writer connection, WAL for concurrent readers."""

    name = "sqlite"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        await asyncio.to_thread(self._connect)

    def _connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
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
            raise RuntimeError("store is not open")
        return self._conn

    async def write_articles(self, articles: Sequence[Article]) -> WriteResult:
        if not articles:
            return WriteResult()
        async with self._lock:
            return await asyncio.to_thread(self._write_articles, list(articles))

    def _write_articles(self, articles: list[Article]) -> WriteResult:
        conn = self._require()
        now = time.time()
        rows = [
            (
                a.source,
                a.id,
                a.published,
                a.title,
                a.url,
                a.provider,
                a.summary,
                orjson.dumps(list(a.symbols)).decode(),
                a.urgency,
                now,
            )
            for a in articles
        ]
        before = conn.total_changes
        with conn:
            conn.executemany(_INSERT_ARTICLE, rows)
        return WriteResult(inserted=conn.total_changes - before)

    async def write_events(self, events: Sequence[Event]) -> WriteResult:
        if not events:
            return WriteResult()
        async with self._lock:
            return await asyncio.to_thread(self._write_events, list(events))

    def _write_events(self, events: list[Event]) -> WriteResult:
        conn = self._require()
        now = time.time()
        known = {(source, ident) for source, ident in conn.execute("SELECT source, id FROM events")}
        rows = [
            (
                e.source,
                e.id,
                e.time,
                e.title,
                e.country,
                e.importance,
                e.actual,
                e.forecast,
                e.previous,
                e.unit,
                e.period,
                now,
            )
            for e in events
        ]
        before = conn.total_changes
        with conn:
            conn.executemany(_UPSERT_EVENT, rows)
        touched = conn.total_changes - before
        inserted = sum(1 for e in events if (e.source, e.id) not in known)
        return WriteResult(inserted=inserted, updated=max(0, touched - inserted))

    async def write_observations(self, rows: Sequence[Observation]) -> WriteResult:
        if not rows:
            return WriteResult()
        async with self._lock:
            return await asyncio.to_thread(self._write_observations, list(rows))

    def _write_observations(self, rows: list[Observation]) -> WriteResult:
        """Revisions are the norm here, so a changed value rewrites its row."""
        conn = self._require()
        now = time.time()
        known = {
            (source, series, when)
            for source, series, when in conn.execute(
                "SELECT source, series, time FROM observations"
            )
        }
        payload = [
            (
                o.source,
                o.series,
                o.time,
                o.value,
                o.scale,
                o.country,
                o.indicator,
                o.frequency,
                o.period,
                now,
            )
            for o in rows
        ]
        before = conn.total_changes
        with conn:
            conn.executemany(_UPSERT_OBSERVATION, payload)
        touched = conn.total_changes - before
        inserted = sum(1 for o in rows if (o.source, o.series, o.time) not in known)
        return WriteResult(inserted=inserted, updated=max(0, touched - inserted))

    async def observations(self, country: str = "", limit: int = 50) -> list[Observation]:
        async with self._lock:
            return await asyncio.to_thread(self._observations, country, limit)

    def _observations(self, country: str, limit: int) -> list[Observation]:
        conn = self._require()
        sql = (
            "SELECT source, series, time, value, country, indicator, frequency, scale, period"
            " FROM observations"
        )
        params: tuple[object, ...] = ()
        if country:
            sql += " WHERE country = ?"
            params = (country,)
        sql += " ORDER BY time DESC LIMIT ?"
        return [Observation(*row) for row in conn.execute(sql, (*params, limit))]

    async def feeds(self) -> list[FeedInfo]:
        async with self._lock:
            return await asyncio.to_thread(self._feeds)

    def _feeds(self) -> list[FeedInfo]:
        conn = self._require()
        out: list[FeedInfo] = []
        for kind, table, column in (
            ("news", "articles", "published"),
            ("calendar", "events", "time"),
            ("macro", "observations", "time"),
        ):
            out.extend(
                FeedInfo(kind, source, count, first, last)
                for source, count, first, last in conn.execute(
                    f"SELECT source, COUNT(*), MIN({column}), MAX({column})"
                    f" FROM {table} GROUP BY source ORDER BY source"
                )
            )
        return out

    async def latest_articles(self, limit: int = 20, source: str | None = None) -> list[Article]:
        async with self._lock:
            return await asyncio.to_thread(self._latest_articles, limit, source)

    def _latest_articles(self, limit: int, source: str | None) -> list[Article]:
        conn = self._require()
        sql = (
            "SELECT source, id, title, url, published, provider, summary, symbols, urgency"
            " FROM articles"
        )
        params: tuple[object, ...] = ()
        if source:
            sql += " WHERE source = ?"
            params = (source,)
        sql += " ORDER BY COALESCE(published, fetched) DESC LIMIT ?"
        rows = conn.execute(sql, (*params, limit)).fetchall()
        return [
            Article(
                source=r[0],
                id=r[1],
                title=r[2],
                url=r[3] or "",
                published=r[4],
                provider=r[5] or "",
                summary=r[6] or "",
                symbols=tuple(orjson.loads(r[7]) if r[7] else ()),
                urgency=r[8],
            )
            for r in rows
        ]

    async def upcoming(self, limit: int = 20, min_importance: int = 0) -> list[Event]:
        """Events from now forward, most imminent first."""
        async with self._lock:
            return await asyncio.to_thread(self._upcoming, limit, min_importance)

    def _upcoming(self, limit: int, min_importance: int) -> list[Event]:
        conn = self._require()
        rows = conn.execute(
            "SELECT source, id, title, country, time, importance, actual, forecast,"
            " previous, unit, period FROM events"
            " WHERE time >= ? AND importance >= ? ORDER BY time LIMIT ?",
            (time.time(), min_importance, limit),
        ).fetchall()
        return [Event(*row) for row in rows]


class JsonlStore(Store):
    """``<dir>/news/<source>.jsonl`` and ``<dir>/calendar/<source>.jsonl``.

    Append-only, so a calendar row cannot be rewritten when its print lands -
    the release simply appends a second, fuller copy. Use SQLite when you want
    one row per event.
    """

    name = "jsonl"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._seen_articles: set[tuple[str, str]] = set()
        self._seen_events: dict[tuple[str, str], str | None] = {}
        self._seen_obs: dict[tuple[str, str, float], float] = {}
        self._lock = asyncio.Lock()

    def path(self, kind: str, source: str) -> Path:
        return self.root / kind / f"{source}.jsonl"

    async def write_articles(self, articles: Sequence[Article]) -> WriteResult:
        if not articles:
            return WriteResult()
        async with self._lock:
            fresh = [a for a in articles if (a.source, a.id) not in self._seen_articles]
            self._seen_articles.update((a.source, a.id) for a in fresh)
            if not fresh:
                return WriteResult()
            await asyncio.to_thread(self._append, "news", [(a.source, a.to_dict()) for a in fresh])
            return WriteResult(inserted=len(fresh))

    async def write_events(self, events: Sequence[Event]) -> WriteResult:
        if not events:
            return WriteResult()
        async with self._lock:
            fresh = [e for e in events if self._seen_events.get((e.source, e.id), "\0") != e.actual]
            for event in fresh:
                self._seen_events[(event.source, event.id)] = event.actual
            if not fresh:
                return WriteResult()
            await asyncio.to_thread(
                self._append, "calendar", [(e.source, e.to_dict()) for e in fresh]
            )
            return WriteResult(inserted=len(fresh))

    def _append(self, kind: str, rows: list[tuple[str, dict[str, object]]]) -> None:
        grouped: dict[str, list[bytes]] = {}
        for source, row in rows:
            grouped.setdefault(source, []).append(orjson.dumps(row) + b"\n")
        for source, payload in grouped.items():
            path = self.path(kind, source)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "ab") as handle:
                handle.write(b"".join(payload))

    async def write_observations(self, rows: Sequence[Observation]) -> WriteResult:
        if not rows:
            return WriteResult()
        async with self._lock:
            fresh = [r for r in rows if self._seen_obs.get((r.source, r.series, r.time)) != r.value]
            for row in fresh:
                self._seen_obs[(row.source, row.series, row.time)] = row.value
            if not fresh:
                return WriteResult()
            await asyncio.to_thread(self._append, "macro", [(r.source, r.to_dict()) for r in fresh])
            return WriteResult(inserted=len(fresh))

    async def feeds(self) -> list[FeedInfo]:
        return await asyncio.to_thread(self._feeds)

    def _feeds(self) -> list[FeedInfo]:
        out: list[FeedInfo] = []
        for kind, field in (("news", "published"), ("calendar", "time"), ("macro", "time")):
            for path in sorted((self.root / kind).glob("*.jsonl")):
                count = 0
                first: float | None = None
                last: float | None = None
                with open(path, "rb") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        try:
                            stamp = orjson.loads(line).get(field)
                        except orjson.JSONDecodeError:
                            continue
                        count += 1
                        if isinstance(stamp, int | float):
                            first = stamp if first is None else min(first, stamp)
                            last = stamp if last is None else max(last, stamp)
                out.append(FeedInfo(kind, path.stem, count, first, last))
        return out


class MultiStore(Store):
    """Writes to several stores; reports the first one's counts."""

    name = "multi"

    def __init__(self, stores: Sequence[Store]) -> None:
        if not stores:
            raise ValueError("MultiStore needs at least one store")
        self.stores = tuple(stores)

    async def open(self) -> None:
        for store in self.stores:
            await store.open()

    async def close(self) -> None:
        for store in reversed(self.stores):
            await store.close()

    async def write_articles(self, articles: Sequence[Article]) -> WriteResult:
        results = [await s.write_articles(articles) for s in self.stores]
        return results[0]

    async def write_events(self, events: Sequence[Event]) -> WriteResult:
        results = [await s.write_events(events) for s in self.stores]
        return results[0]

    async def write_observations(self, rows: Sequence[Observation]) -> WriteResult:
        results = [await s.write_observations(rows) for s in self.stores]
        return results[0]

    async def feeds(self) -> list[FeedInfo]:
        return await self.stores[0].feeds()


def open_store(kind: str, *, database: Path, data_dir: Path) -> Store:
    """Build the store named by `kind` (``sqlite``, ``jsonl`` or ``both``)."""
    match kind:
        case "sqlite":
            return SqliteStore(database)
        case "jsonl":
            return JsonlStore(data_dir)
        case "both":
            return MultiStore((SqliteStore(database), JsonlStore(data_dir)))
        case _:
            raise ValueError(f"unknown store {kind!r} (use sqlite, jsonl or both)")
