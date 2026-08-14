"""Where candles land: SQLite by default, append-only JSONL alongside it.

SQLite is primary because an UPSERT keyed on the bar's open time gives dedup for
free *and* lets a bar that was still forming be corrected once it closes —
something the append-only JSONL layout can never do. JSONL stays available
because it is trivially greppable and streams into anything.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Self

import orjson

from .config import FEEDS
from .models import (
    Bar,
    Interval,
    PruneResult,
    Quote,
    QuoteKey,
    SeriesInfo,
    SeriesKey,
    Symbol,
    WriteResult,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    source   TEXT    NOT NULL,
    feed     TEXT    NOT NULL,
    venue    TEXT    NOT NULL,
    ticker   TEXT    NOT NULL,
    interval TEXT    NOT NULL,
    ts       INTEGER NOT NULL,
    open     REAL    NOT NULL,
    high     REAL    NOT NULL,
    low      REAL    NOT NULL,
    close    REAL    NOT NULL,
    volume   REAL,
    closed   INTEGER NOT NULL DEFAULT 1,
    updated  INTEGER NOT NULL,
    PRIMARY KEY (source, feed, venue, ticker, interval, ts)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS bars_series_ts
    ON bars (source, venue, ticker, interval, ts DESC);

CREATE TABLE IF NOT EXISTS quotes (
    source     TEXT    NOT NULL,
    feed       TEXT    NOT NULL,
    venue      TEXT    NOT NULL,
    ticker     TEXT    NOT NULL,
    ts         INTEGER NOT NULL,  -- epoch milliseconds the quote was observed
    bid        REAL,
    ask        REAL,
    last       REAL,
    mid        REAL,
    spread     REAL,
    spread_bps REAL,
    volume     REAL,
    change     REAL,
    change_pct REAL,
    PRIMARY KEY (source, feed, venue, ticker, ts)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS quotes_series_ts
    ON quotes (source, venue, ticker, ts DESC);

CREATE INDEX IF NOT EXISTS quotes_feed_ts
    ON quotes (feed, ts DESC);
"""

_INSERT_QUOTE = """
INSERT OR IGNORE INTO quotes (source, feed, venue, ticker, ts, bid, ask, last, mid,
                              spread, spread_bps, volume, change, change_pct)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPSERT = """
INSERT INTO bars (source, feed, venue, ticker, interval, ts,
                  open, high, low, close, volume, closed, updated)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (source, feed, venue, ticker, interval, ts) DO UPDATE SET
    open = excluded.open,
    high = excluded.high,
    low = excluded.low,
    close = excluded.close,
    volume = excluded.volume,
    closed = excluded.closed,
    updated = excluded.updated
WHERE bars.closed = 0
"""

#: Retention, per series. `bars` is WITHOUT ROWID, so rows are addressed by the
#: primary key rather than by rowid — hence the row-value `IN`, which SQLite has
#: supported since 3.15.
_PRUNE_BARS = """
DELETE FROM bars
WHERE (source, feed, venue, ticker, interval, ts) IN (
    SELECT source, feed, venue, ticker, interval, ts FROM (
        SELECT source, feed, venue, ticker, interval, ts,
               ROW_NUMBER() OVER (
                   PARTITION BY source, feed, venue, ticker, interval
                   ORDER BY ts DESC
               ) AS rank
        FROM bars
    )
    WHERE rank > ?
)
"""


class Store(ABC):
    """Persists candles for a series."""

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
    async def write(
        self, key: SeriesKey, bars: Sequence[Bar], interval: Interval
    ) -> WriteResult: ...

    @abstractmethod
    async def series(self) -> list[SeriesInfo]: ...

    @abstractmethod
    async def write_quote(self, key: QuoteKey, quote: Quote) -> WriteResult: ...


class SqliteStore(Store):
    """One database file, one writer connection, WAL for concurrent readers."""

    name = "sqlite"

    def __init__(self, path: Path, *, dedupe_quotes: bool = True) -> None:
        self.path = Path(path)
        self.dedupe_quotes = dedupe_quotes
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._last_quote: dict[QuoteKey, Quote] = {}

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

    async def write(self, key: SeriesKey, bars: Sequence[Bar], interval: Interval) -> WriteResult:
        if not bars:
            return WriteResult()
        async with self._lock:
            return await asyncio.to_thread(self._write, key, list(bars), interval)

    def _write(self, key: SeriesKey, bars: list[Bar], interval: Interval) -> WriteResult:
        conn = self._require()
        now = int(time.time())
        ident = (key.source, key.feed, key.symbol.venue, key.symbol.ticker, key.interval)
        oldest = min(bar.time for bar in bars)
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT ts FROM bars WHERE source=? AND feed=? AND venue=? AND ticker=?"
                " AND interval=? AND ts>=?",
                (*ident, oldest),
            )
        }
        rows = [
            (
                *ident,
                bar.time,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                int(bar.is_closed(interval, now)),
                now,
            )
            for bar in bars
        ]
        before = conn.total_changes
        with conn:
            conn.executemany(_UPSERT, rows)
        touched = conn.total_changes - before
        inserted = sum(1 for bar in bars if bar.time not in existing)
        return WriteResult(inserted=inserted, updated=max(0, touched - inserted))

    async def prune(self, keep: int, *, vacuum: bool = False) -> PruneResult:
        """Keep the most recent `keep` bars of every series, drop the rest.

        Per **series**, not per table and not per age. A count rather than a
        cutoff date because the models consume a *window of bars* — the level
        engine seeds from the last few hundred per instrument and timeframe —
        so a count keeps exactly what can still be used. It also self-scales
        across timeframes without a table of durations: 2,000 is about a day
        and a half of 1m and about forty years of 1w, which is the right shape,
        since that is also roughly how far back each one's evidence is worth
        anything.

        Quotes are left alone. They are the raw material for the spread median
        and are already bounded by `dedupe_quotes`; bars are what grow without
        limit, and 1m across fourteen instruments and six venues is most of it.

        **Deleting does not shrink the file.** SQLite frees the pages for reuse,
        so growth stops but the database stays its current size until it is
        rebuilt. `vacuum=True` rebuilds it, and needs room for a second copy
        while it runs — which is the one thing in short supply when this is
        being reached for, so it is off by default and the caller decides.
        """
        async with self._lock:
            return await asyncio.to_thread(self._prune, keep, vacuum)

    def _prune(self, keep: int, vacuum: bool) -> PruneResult:
        conn = self._require()
        if keep < 1:
            raise ValueError("keep must be at least 1 — prune does not empty the table")
        before = conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
        with conn:
            conn.execute(_PRUNE_BARS, (keep,))
        after = conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
        if vacuum:
            # Outside the transaction: VACUUM cannot run inside one.
            conn.execute("VACUUM")
        return PruneResult(deleted=before - after, kept=after, vacuumed=vacuum)

    async def series(self) -> list[SeriesInfo]:
        async with self._lock:
            return await asyncio.to_thread(self._series)

    def _series(self) -> list[SeriesInfo]:
        conn = self._require()
        rows = conn.execute(
            "SELECT source, feed, venue, ticker, interval, COUNT(*), MIN(ts), MAX(ts)"
            " FROM bars GROUP BY source, feed, venue, ticker, interval"
            " ORDER BY feed, source, venue, ticker, interval"
        ).fetchall()
        return [
            SeriesInfo(
                key=SeriesKey(source, feed, Symbol(venue, ticker), interval),
                bars=count,
                first_time=first,
                last_time=last,
            )
            for source, feed, venue, ticker, interval, count, first, last in rows
        ]

    async def write_quote(self, key: QuoteKey, quote: Quote) -> WriteResult:
        if quote.is_empty:
            return WriteResult()
        async with self._lock:
            return await asyncio.to_thread(self._write_quote, key, quote)

    def _write_quote(self, key: QuoteKey, quote: Quote) -> WriteResult:
        conn = self._require()
        if self._skip_unchanged(key, quote):
            return WriteResult()
        row = (
            key.source,
            key.feed,
            key.symbol.venue,
            key.symbol.ticker,
            int(quote.time * 1000),
            quote.bid,
            quote.ask,
            quote.last,
            quote.mid,
            quote.spread,
            quote.spread_bps,
            quote.volume,
            quote.change,
            quote.change_pct,
        )
        before = conn.total_changes
        with conn:
            conn.execute(_INSERT_QUOTE, row)
        return WriteResult(inserted=conn.total_changes - before)

    def _skip_unchanged(self, key: QuoteKey, quote: Quote) -> bool:
        """A quiet market repeats the same top of book; store the move, not the poll."""
        if not self.dedupe_quotes:
            return False
        previous = self._last_quote.get(key)
        self._last_quote[key] = quote
        return quote.same_price_as(previous)

    async def quotes(self, key: QuoteKey, limit: int = 500) -> list[Quote]:
        """Most recent `limit` quotes, oldest first."""
        async with self._lock:
            return await asyncio.to_thread(self._quotes, key, limit)

    def _quotes(self, key: QuoteKey, limit: int) -> list[Quote]:
        conn = self._require()
        rows = conn.execute(
            "SELECT ts, bid, ask, last, volume, change, change_pct FROM quotes"
            " WHERE source=? AND feed=? AND venue=? AND ticker=? ORDER BY ts DESC LIMIT ?",
            (key.source, key.feed, key.symbol.venue, key.symbol.ticker, limit),
        ).fetchall()
        return [
            Quote(ts / 1000, bid, ask, last, volume, change, change_pct)
            for ts, bid, ask, last, volume, change, change_pct in reversed(rows)
        ]

    async def bars(self, key: SeriesKey, limit: int = 500) -> list[Bar]:
        """Most recent `limit` bars, oldest first."""
        async with self._lock:
            return await asyncio.to_thread(self._bars, key, limit)

    def _bars(self, key: SeriesKey, limit: int) -> list[Bar]:
        conn = self._require()
        rows = conn.execute(
            "SELECT ts, open, high, low, close, volume FROM bars"
            " WHERE source=? AND feed=? AND venue=? AND ticker=? AND interval=?"
            " ORDER BY ts DESC LIMIT ?",
            (key.source, key.feed, key.symbol.venue, key.symbol.ticker, key.interval, limit),
        ).fetchall()
        return [Bar(*row) for row in reversed(rows)]


class JsonlStore(Store):
    """``<dir>/<source>/<feed>_<VENUE>_<TICKER>_<interval>.jsonl``, append only.

    Dedup is by last written timestamp, so bars only ever move forward. A bar
    already on disk is never rewritten — use SQLite if you need corrections.
    """

    name = "jsonl"

    def __init__(self, root: Path, *, dedupe_quotes: bool = True) -> None:
        self.root = Path(root)
        self.dedupe_quotes = dedupe_quotes
        self._last: dict[SeriesKey, int] = {}
        self._last_quote: dict[QuoteKey, Quote] = {}
        self._lock = asyncio.Lock()

    def path(self, key: SeriesKey) -> Path:
        return self.root / key.source / f"{key.slug}.jsonl"

    def quote_path(self, key: QuoteKey) -> Path:
        return self.root / "quotes" / key.source / f"{key.slug}.jsonl"

    async def write_quote(self, key: QuoteKey, quote: Quote) -> WriteResult:
        if quote.is_empty:
            return WriteResult()
        async with self._lock:
            if self.dedupe_quotes and quote.same_price_as(self._last_quote.get(key)):
                return WriteResult()
            self._last_quote[key] = quote
            return await asyncio.to_thread(self._write_quote, key, quote)

    def _write_quote(self, key: QuoteKey, quote: Quote) -> WriteResult:
        path = self.quote_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"sym": key.symbol.full, "feed": key.feed, **quote.to_dict()}
        with open(path, "ab") as handle:
            handle.write(orjson.dumps(row) + b"\n")
        return WriteResult(inserted=1)

    async def write(
        self,
        key: SeriesKey,
        bars: Sequence[Bar],
        interval: Interval,  # noqa: ARG002 - required by the Store interface
    ) -> WriteResult:
        # JSONL never rewrites a bar, so it has no use for the interval: whether
        # a bar is closed only matters to a store that could correct it later.
        if not bars:
            return WriteResult()
        async with self._lock:
            return await asyncio.to_thread(self._write, key, sorted(bars, key=lambda b: b.time))

    def _write(self, key: SeriesKey, bars: list[Bar]) -> WriteResult:
        path = self.path(key)
        last = self._last.get(key)
        if last is None:
            last = _tail_timestamp(path)
            self._last[key] = last if last is not None else -1
            last = self._last[key]
        fresh = [bar for bar in bars if bar.time > last]
        if not fresh:
            return WriteResult()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"".join(orjson.dumps(bar.to_dict()) + b"\n" for bar in fresh)
        with open(path, "ab") as handle:
            handle.write(payload)
        self._last[key] = fresh[-1].time
        return WriteResult(inserted=len(fresh))

    async def series(self) -> list[SeriesInfo]:
        return await asyncio.to_thread(self._series)

    def _series(self) -> list[SeriesInfo]:
        out: list[SeriesInfo] = []
        for path in sorted(self.root.glob("*/*.jsonl")):
            key = _key_from_path(path)
            if key is None:
                continue
            count = 0
            first: int | None = None
            last: int | None = None
            with open(path, "rb") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        ts = int(orjson.loads(line)["t"])
                    except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
                        continue
                    count += 1
                    first = ts if first is None else min(first, ts)
                    last = ts if last is None else max(last, ts)
            out.append(SeriesInfo(key=key, bars=count, first_time=first, last_time=last))
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

    async def write(self, key: SeriesKey, bars: Sequence[Bar], interval: Interval) -> WriteResult:
        results = [await store.write(key, bars, interval) for store in self.stores]
        return results[0]

    async def write_quote(self, key: QuoteKey, quote: Quote) -> WriteResult:
        results = [await store.write_quote(key, quote) for store in self.stores]
        return results[0]

    async def series(self) -> list[SeriesInfo]:
        return await self.stores[0].series()


def open_store(kind: str, *, database: Path, data_dir: Path, dedupe_quotes: bool = True) -> Store:
    """Build the store named by `kind` (``sqlite``, ``jsonl`` or ``both``)."""
    match kind:
        case "sqlite":
            return SqliteStore(database, dedupe_quotes=dedupe_quotes)
        case "jsonl":
            return JsonlStore(data_dir, dedupe_quotes=dedupe_quotes)
        case "both":
            return MultiStore(
                (
                    SqliteStore(database, dedupe_quotes=dedupe_quotes),
                    JsonlStore(data_dir, dedupe_quotes=dedupe_quotes),
                )
            )
        case _:
            raise ValueError(f"unknown store {kind!r} (use sqlite, jsonl or both)")


def _tail_timestamp(path: Path, window: int = 8192) -> int | None:
    """Last bar time in a JSONL file, read from the tail rather than the whole file."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if not size:
        return None
    with open(path, "rb") as handle:
        handle.seek(max(0, size - window))
        chunk = handle.read()
    for line in reversed(chunk.splitlines()):
        if not line.strip():
            continue
        try:
            return int(orjson.loads(line)["t"])
        except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return None


def _known_slugs() -> dict[str, tuple[str, Symbol]]:
    index: dict[str, tuple[str, Symbol]] = {}
    for feed in FEEDS.values():
        for symbols in feed.symbols.values():
            for symbol in symbols:
                index[symbol.slug] = (feed.name, symbol)
    return index


def _key_from_path(path: Path) -> SeriesKey | None:
    """Recover a SeriesKey from a JSONL filename.

    Venue slugs can themselves contain underscores (``FX_IDC``), so the split is
    resolved against the configured feeds before falling back to a naive guess.
    """
    source = path.parent.name
    parts = path.stem.split("_")
    if len(parts) < 4:
        return None
    feed, interval, middle = parts[0], parts[-1], "_".join(parts[1:-1])
    known = _known_slugs().get(middle)
    if known is not None:
        return SeriesKey(source, known[0], known[1], interval)
    venue, _, ticker = middle.partition("_")
    return SeriesKey(source, feed, Symbol(venue, ticker), interval)


def iter_bars(path: Path) -> Iterable[Bar]:
    """Stream bars out of a JSONL file."""
    with open(path, "rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = orjson.loads(line)
                yield Bar(
                    int(row["t"]),
                    float(row["o"]),
                    float(row["h"]),
                    float(row["l"]),
                    float(row["c"]),
                    None if row.get("v") is None else float(row["v"]),
                )
            except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
