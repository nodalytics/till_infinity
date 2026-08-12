"""Read-only views over the collected data.

Everything the model can see comes through here, and every connection is opened
``mode=ro`` — the agent cannot write to the stores even if it tries, and a
prompt injection in a headline cannot turn into an UPDATE. That guarantee is
worth more than the convenience of reusing the async stores directly, which is
why this module talks to SQLite itself and stays synchronous: tool callbacks
run in a plain function, not a coroutine.

The queries here are the cross-cutting ones an analyst actually asks for —
spread per venue, divergence between brokers, what is about to print — rather
than the row-level accessors the collectors use.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Nothing the model can ask for should be able to pull the whole table.
MAX_ROWS = 200


class DataError(Exception):
    """A store is missing or unreadable."""


@contextmanager
def read_only(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a store read-only. Writes fail at the driver, not by convention."""
    if not Path(path).exists():
        raise DataError(f"no store at {path} — run the collectors first")
    conn = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params)]


def _clamp(limit: int, ceiling: int = MAX_ROWS) -> int:
    return max(1, min(int(limit), ceiling))


def stamp(value: float | int | None) -> str | None:
    """Epoch seconds -> an ISO string the model can reason about."""
    if not value:
        return None
    return datetime.fromtimestamp(float(value), UTC).strftime("%Y-%m-%d %H:%M UTC")


# ------------------------------------------------------------------- prices


def instruments(prices_db: Path) -> list[dict[str, Any]]:
    """What is tracked, and how much of it there is."""
    with read_only(prices_db) as conn:
        bars = _rows(
            conn,
            "SELECT feed, COUNT(DISTINCT venue) AS venues, COUNT(*) AS bars,"
            " MAX(ts) AS latest FROM bars GROUP BY feed ORDER BY feed",
        )
        quotes = {
            row["feed"]: row
            for row in _rows(
                conn,
                "SELECT feed, COUNT(*) AS quotes, MAX(ts)/1000.0 AS latest"
                " FROM quotes GROUP BY feed",
            )
        }
    for row in bars:
        quoted = quotes.get(row["feed"], {})
        row["latest_bar"] = stamp(row.pop("latest"))
        row["quotes"] = quoted.get("quotes", 0)
        row["latest_quote"] = stamp(quoted.get("latest"))
    return bars


def quotes(prices_db: Path, feed: str, limit: int = 20) -> list[dict[str, Any]]:
    """Latest top of book per venue for one instrument, tightest spread first."""
    with read_only(prices_db) as conn:
        rows = _rows(
            conn,
            "SELECT venue, ticker, bid, ask, mid, spread, spread_bps, ts/1000.0 AS ts"
            " FROM quotes q WHERE feed = ?"
            " AND ts = (SELECT MAX(ts) FROM quotes q2 WHERE q2.feed = q.feed"
            "           AND q2.venue = q.venue AND q2.ticker = q.ticker)"
            " ORDER BY spread_bps LIMIT ?",
            (feed, _clamp(limit)),
        )
    for row in rows:
        row["observed"] = stamp(row.pop("ts"))
    return rows


def spreads(prices_db: Path, feed: str, hours: int = 24) -> list[dict[str, Any]]:
    """Spread statistics per venue — who is consistently tightest, and who blew out."""
    since = (time.time() - hours * 3600) * 1000
    with read_only(prices_db) as conn:
        return _rows(
            conn,
            "SELECT venue, COUNT(*) AS samples,"
            " ROUND(AVG(spread_bps), 3) AS avg_bps,"
            " ROUND(MIN(spread_bps), 3) AS min_bps,"
            " ROUND(MAX(spread_bps), 3) AS max_bps"
            " FROM quotes WHERE feed = ? AND ts >= ? AND spread_bps IS NOT NULL"
            " GROUP BY venue ORDER BY avg_bps",
            (feed, since),
        )


def divergence(prices_db: Path, feed: str) -> dict[str, Any]:
    """How far apart the brokers are right now — the cross-broker signal.

    Returns the tightest and widest mid across venues at each one's latest
    quote, and the gap between them in basis points.
    """
    rows = quotes(prices_db, feed, limit=MAX_ROWS)
    priced = [r for r in rows if r.get("mid") is not None]
    if len(priced) < 2:
        return {"feed": feed, "venues": len(priced), "divergence_bps": None}
    low = min(priced, key=lambda r: r["mid"])
    high = max(priced, key=lambda r: r["mid"])
    middle = (low["mid"] + high["mid"]) / 2
    return {
        "feed": feed,
        "venues": len(priced),
        "lowest": {"venue": low["venue"], "mid": low["mid"]},
        "highest": {"venue": high["venue"], "mid": high["mid"]},
        "divergence_bps": round((high["mid"] - low["mid"]) / middle * 10_000, 3)
        if middle
        else None,
    }


def bars(
    prices_db: Path,
    feed: str,
    interval: str = "1h",
    venue: str = "",
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Recent candles, oldest first. One venue, so the series is comparable."""
    with read_only(prices_db) as conn:
        if not venue:
            picked = _rows(
                conn,
                "SELECT venue, COUNT(*) AS n FROM bars WHERE feed = ? AND interval = ?"
                " GROUP BY venue ORDER BY n DESC LIMIT 1",
                (feed, interval),
            )
            if not picked:
                return []
            venue = picked[0]["venue"]
        rows = _rows(
            conn,
            "SELECT ts, open, high, low, close, volume FROM bars"
            " WHERE feed = ? AND interval = ? AND venue = ?"
            " ORDER BY ts DESC LIMIT ?",
            (feed, interval, venue, _clamp(limit)),
        )
    for row in rows:
        row["time"] = stamp(row.pop("ts"))
        row["venue"] = venue
    return list(reversed(rows))


def move(prices_db: Path, feed: str, interval: str = "1h", periods: int = 24) -> dict[str, Any]:
    """Percentage change over the last `periods` bars — the headline number."""
    series = bars(prices_db, feed, interval, limit=periods + 1)
    if len(series) < 2:
        return {"feed": feed, "change_pct": None, "bars": len(series)}
    first, last = series[0]["close"], series[-1]["close"]
    return {
        "feed": feed,
        "venue": series[-1]["venue"],
        "interval": interval,
        "from": series[0]["time"],
        "to": series[-1]["time"],
        "open": first,
        "close": last,
        "change_pct": round((last - first) / first * 100, 4) if first else None,
        "high": max(r["high"] for r in series),
        "low": min(r["low"] for r in series),
    }


# --------------------------------------------------------------------- news


def events(
    news_db: Path,
    hours: int = 24,
    min_importance: int = 2,
    released: bool | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Calendar entries in a window around now.

    `released=False` gives what is still to come, `True` what has already
    printed (with its actual), `None` both.
    """
    now = time.time()
    low, high = (now - hours * 3600, now + hours * 3600)
    clause = ""
    if released is True:
        clause = " AND actual IS NOT NULL AND actual != ''"
    elif released is False:
        clause = " AND (actual IS NULL OR actual = '') AND time >= strftime('%s','now')"
    with read_only(news_db) as conn:
        rows = _rows(
            conn,
            "SELECT source, country, title, time, importance, actual, forecast, previous, unit"
            f" FROM events WHERE time BETWEEN ? AND ? AND importance >= ?{clause}"
            " ORDER BY time LIMIT ?",
            (low, high, min_importance, _clamp(limit)),
        )
    for row in rows:
        row["when"] = stamp(row.pop("time"))
    return rows


def headlines(
    news_db: Path,
    hours: int = 12,
    limit: int = 25,
    symbol: str = "",
) -> list[dict[str, Any]]:
    """Recent stories, newest first. `symbol` filters TradingView's tagging."""
    since = time.time() - hours * 3600
    sql = (
        "SELECT source, provider, title, url, published FROM articles"
        " WHERE COALESCE(published, fetched) >= ?"
    )
    params: list[Any] = [since]
    if symbol:
        sql += " AND symbols LIKE ?"
        params.append(f"%{symbol}%")
    sql += " ORDER BY COALESCE(published, fetched) DESC LIMIT ?"
    params.append(_clamp(limit))
    with read_only(news_db) as conn:
        rows = _rows(conn, sql, tuple(params))
    for row in rows:
        row["published"] = stamp(row["published"])
    return rows


def reserves(news_db: Path, country: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """IMF reserve observations. Values are already in USD — `scale` is provenance."""
    sql = (
        "SELECT country, indicator, period, value, scale FROM observations"
        " WHERE indicator LIKE 'IRFCLDT1_IRFCL54%'"
    )
    params: list[Any] = []
    if country:
        sql += " AND country = ?"
        params.append(country.upper())
    sql += " ORDER BY time DESC LIMIT ?"
    params.append(_clamp(limit))
    with read_only(news_db) as conn:
        return _rows(conn, sql, tuple(params))
