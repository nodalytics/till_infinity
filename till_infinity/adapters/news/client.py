"""The news data client: live subscriptions and point-in-time history.

`LiveDataClient` rather than `LiveMarketDataClient`, because none of this is
per-instrument market data. It publishes custom types, which is how Databento
and Tardis are shaped too.

**History is the half that matters.** `_request` serves from our own store, so
a backtest replays what was known when - and that is the whole argument for
building news as an adapter instead of an Actor.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from nautilus_trader.live.config import LiveDataClientConfig
from nautilus_trader.live.data_client import LiveDataClient
from nautilus_trader.model.identifiers import ClientId

from .data import CalendarEvent, Importance, MacroObservation, Stage

#: How often to look for new calendar entries and releases.
#:
#: Minutes rather than seconds: a release lands on a schedule known in
#: advance, so polling faster buys nothing but load on somebody's API. The
#: *embargo* is driven off the schedule, which is already known.
DEFAULT_POLL = 300.0


class NewsDataClientConfig(LiveDataClientConfig, frozen=True):
    """Where the calendar comes from and which parts to carry."""

    #: Our own store, which is also what `_request` reads for a backtest.
    db_path: str | None = None
    poll_seconds: float = DEFAULT_POLL
    #: Carry only entries at or above this importance. Low-importance
    #: releases move nothing and standing aside for all of them is standing
    #: aside always.
    minimum_importance: str = "medium"
    countries: tuple[str, ...] = ()
    #: Fetch from the network at all. False makes the client history-only,
    #: which is what a backtest node wants.
    live: bool = True


class NewsDataClient(LiveDataClient):
    """Publishes `CalendarEvent` and `MacroObservation`."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        msgbus: Any,
        cache: Any,
        clock: Any,
        config: NewsDataClientConfig,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=None,  # not a venue; this is a data provider
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        self._cfg = config
        self._floor = Importance(config.minimum_importance)
        self._poller: asyncio.Task | None = None
        #: Entries already published, by `(event_id, stage)`, so an entry is
        #: announced once and released once rather than on every poll.
        self._published: set[tuple[str, str]] = set()

    # ──── lifecycle ────
    async def _connect(self) -> None:
        if not self._cfg.live:
            self._log.info("news: history only, not polling")
            return
        self._poller = self.create_task(self._poll())

    async def _disconnect(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._poller
            self._poller = None

    # ──── subscriptions ────
    async def _subscribe(self, command: Any) -> None:
        """Both custom types arrive through the generic hook.

        A `DataType` of `CalendarEvent` or `MacroObservation`; nothing else is
        served, and an unknown type is refused rather than silently ignored -
        a subscription that returns nothing forever is worse than one that
        fails at startup.
        """
        wanted = getattr(command.data_type, "type", None)
        if wanted not in (CalendarEvent, MacroObservation):
            raise NotImplementedError(
                f"{self.id} serves CalendarEvent and MacroObservation, not {wanted}"
            )
        self._log.info(f"news: subscribed to {wanted.__name__}")

    # ──── history, which is the point ────
    async def _request(self, request: Any) -> None:
        """Serve the calendar as it stood, from our own store.

        **Two rows per entry, in the order they were knowable**: the scheduled
        announcement at the time it was announced, then the release at its
        release time. A single row emitted at the scheduled time would carry
        the actual, which is the number everybody is waiting for - and that is
        lookahead of the same shape as `drawing.gaps`, which emitted only the
        gaps that went on to be filled and read +0.50R a trade as a bias.
        """
        wanted = getattr(request.data_type, "type", None)
        if wanted is CalendarEvent:
            data = self._calendar_history(request)
        elif wanted is MacroObservation:
            data = self._macro_history(request)
        else:
            raise NotImplementedError(f"no history for {wanted}")
        self._handle_data_response(request.data_type, data, request.id, request.params)

    def _calendar_history(self, request: Any) -> list[CalendarEvent]:
        rows = self._rows("events", request)
        out: list[CalendarEvent] = []
        for row in rows:
            importance = Importance.of(row.get("importance"))
            if not self._carried(importance, str(row.get("country") or "")):
                continue
            out.extend(self._stages(row, importance))
        out.sort(key=lambda e: e.ts_event)
        return out

    def _stages(self, row: dict, importance: Importance) -> list[CalendarEvent]:
        """One stored row as its two publishable states."""
        release_ns = int(float(row.get("time") or 0.0) * 1e9)
        if release_ns <= 0:
            return []
        # Announced a week ahead where the store does not say. A calendar is
        # published well in advance; the exact announcement time matters less
        # than it being *before* the release, which is what stops the leak.
        announced_ns = int(float(row.get("announced") or 0.0) * 1e9) or (
            release_ns - 7 * 86_400 * 1_000_000_000
        )
        event_id = str(row.get("id") or f"{row.get('source')}:{row.get('title')}")
        common = {
            "event_id": event_id,
            "title": str(row.get("title") or ""),
            "country": str(row.get("country") or ""),
            "importance": importance,
            "forecast": _number(row.get("forecast")),
            "previous": _number(row.get("previous")),
            "unit": str(row.get("unit") or ""),
            "period": str(row.get("period") or ""),
            "source": str(row.get("source") or ""),
        }
        out = [
            CalendarEvent(
                stage=Stage.SCHEDULED,
                ts_event=announced_ns,
                ts_init=announced_ns,
                actual=None,
                **common,
            )
        ]
        actual = _number(row.get("actual"))
        if actual is not None:
            out.append(
                CalendarEvent(
                    stage=Stage.RELEASED,
                    ts_event=release_ns,
                    ts_init=release_ns,
                    actual=actual,
                    **common,
                )
            )
        return out

    def _macro_history(self, request: Any) -> list[MacroObservation]:
        out = []
        for row in self._rows("observations", request):
            value = _number(row.get("value"))
            if value is None:
                continue
            # The *publication* date, not the period it describes: that is
            # when it could have been acted on, and the two are weeks apart.
            at = int(float(row.get("published") or row.get("time") or 0.0) * 1e9)
            if at <= 0:
                continue
            out.append(
                MacroObservation(
                    series=str(row.get("series") or ""),
                    value=value,
                    period=str(row.get("period") or ""),
                    ts_event=at,
                    ts_init=at,
                    unit=str(row.get("unit") or ""),
                    source=str(row.get("source") or ""),
                )
            )
        out.sort(key=lambda o: o.ts_event)
        return out

    def _rows(self, table: str, request: Any) -> list[dict]:
        """Read from the store, logging a failure rather than raising."""
        rows, error = read_rows(self._cfg.db_path, table, request)
        if error:
            self._log.warning(f"news: could not read {table}: {error}")
        return rows

    def _carried(self, importance: Importance, country: str) -> bool:
        order = (Importance.LOW, Importance.MEDIUM, Importance.HIGH)
        if order.index(importance) < order.index(self._floor):
            return False
        return not self._cfg.countries or country in self._cfg.countries

    # ──── live ────
    async def _poll(self) -> None:
        """Announce what is new, release what has just landed.

        Each `(entry, stage)` is published once. A poll that republished every
        entry it still sees would make an embargo fire continuously, which is
        the same failure as an alert per touched bar.
        """
        while True:
            try:
                await self._sweep()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log.warning(f"news: poll failed: {exc}")
            await asyncio.sleep(self._cfg.poll_seconds)

    async def _sweep(self) -> None:
        now_s = self._clock.timestamp_ns() / 1e9
        rows = self._rows("events", _Window(now_s - 14 * 86_400, now_s + 30 * 86_400))
        for row in rows:
            importance = Importance.of(row.get("importance"))
            if not self._carried(importance, str(row.get("country") or "")):
                continue
            for event in self._stages(row, importance):
                key = (event.event_id, event.stage.value)
                if key in self._published:
                    continue
                # Not yet knowable: a scheduled entry announced in the future,
                # or a release that has not happened. Publishing either early
                # is the leak this client exists to prevent.
                if event.ts_event / 1e9 > now_s:
                    continue
                self._published.add(key)
                self._handle_data(event)


class _Window:
    """The two fields `_rows` reads off a request."""

    def __init__(self, start: float, end: float) -> None:
        self.start = start
        self.end = end
        self.limit = 100_000


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _seconds(value: Any) -> float | None:
    """A request bound as epoch seconds, whatever Nautilus handed us."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value) / (1e9 if value > 1e12 else 1.0)
    timestamp = getattr(value, "timestamp", None)
    return float(timestamp()) if callable(timestamp) else None


def read_rows(db_path: str | None, table: str, request: Any) -> tuple[list[dict], str]:
    """Rows from the news store, bounded by the request's own window.

    **A function rather than a method**, because nothing here needs the
    client: `Component._log` is read-only, so a method could not be exercised
    without standing up a kernel - and the behaviour that matters most here is
    what happens when the store is missing.

    Returns `(rows, error)`. A missing or unreadable store is an empty list
    and a message, never an exception: a node that cannot read the calendar
    must still start, because no news is recoverable and a node that will not
    boot is not.

    `journal-extraction-on-tis` is the warning carried over: a `WHERE` can
    un-bound a rowid `LIMIT`, so the window is applied in SQL *and* the result
    is capped.
    """
    if not db_path:
        return [], ""
    if table not in ("events", "observations"):
        return [], f"unknown table {table!r}"
    import sqlite3

    start = _seconds(getattr(request, "start", None))
    end = _seconds(getattr(request, "end", None))
    column = "time" if table == "events" else "published"
    sql = f"SELECT * FROM {table}"
    clauses, params = [], []
    if start is not None:
        clauses.append(f"{column} >= ?")
        params.append(start)
    if end is not None:
        clauses.append(f"{column} <= ?")
        params.append(end)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += f" ORDER BY {column} LIMIT ?"
    params.append(int(getattr(request, "limit", 0) or 100_000))
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute(sql, params)], ""
    except sqlite3.Error as exc:
        return [], str(exc)
