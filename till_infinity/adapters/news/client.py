"""The news data client: live subscriptions and point-in-time history.

`LiveDataClient` rather than `LiveMarketDataClient`, because none of this is
per-instrument market data. It publishes custom types, which is how Databento
and Tardis are shaped too.

**History is the half that matters.** `_request` serves from our own store, so
a backtest replays what was known when - and that is the whole argument for
building news as an adapter instead of an Actor.

The live half fills that store: the poll loop collects from `sources/` and
writes through `store.py`, then publishes what has *become* knowable since the
last pass. Collecting and serving sit in one client on purpose - the store is
the only thing joining them, and a separate collector process would be a
second way to run the desk, which is how `till.env needs a container recreate`
happens.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nautilus_trader.live.config import LiveDataClientConfig
from nautilus_trader.live.data_client import LiveDataClient
from nautilus_trader.model.identifiers import ClientId
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from till_infinity.utils.logging import get_logger

from .data import CalendarEvent, Importance, MacroObservation, Stage
from .sources import Batch, Settings, Source, TransientError, WriteResult, build_sources
from .store import SqliteStore, Store

log = get_logger(__name__)

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
    #: Which providers to poll. Empty means `NEWS_SOURCES`, then
    #: `DEFAULT_SOURCES`.
    #:
    #: **A setting because it was not one**, and the cost of that is recorded
    #: in `sources/config.py`: the old collector called `collect` with no
    #: source list, so the default won and nothing a deployment said could
    #: change it. `fred` was configured on a live box, the key was present,
    #: the name was in the environment - and the source was never constructed,
    #: with no error to say so, because nothing read it.
    sources: tuple[str, ...] = ()


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
        #: Everything the sources need - timeouts, retries, the calendar
        #: window, the FRED key - read from the environment once.
        self._settings = Settings.from_env()
        if config.db_path:
            self._settings.database = Path(config.db_path)
        #: **One path, read and written.** The config may name it; otherwise
        #: `NEWS_DB`/`NEWS_DIR` do. Resolving it here rather than leaving
        #: `db_path` to default to nothing is what makes a live run collect
        #: and serve the same file without anybody configuring two.
        self._db = str(self._settings.database)
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
        rows, error = read_rows(self._db, table, request)
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
        """Collect, then announce what is new and release what has landed.

        Each pass fetches every due source into the store and then sweeps the
        store, so publishing reads what was *persisted* rather than what came
        back over the wire: the store is the source of truth, and an entry a
        provider has stopped serving does not vanish from the sweep.

        Each `(entry, stage)` is published once. A poll that republished every
        entry it still sees would make an embargo fire continuously, which is
        the same failure as an alert per touched bar.

        **Two clocks, which is what `Source.slow` is for.** Headline feeds
        move continuously; a calendar barely moves until a print lands, and
        monthly reserves do not move at all between months. Re-polling them on
        the fast clock would be load on somebody's API for nothing.
        """
        try:
            async with AsyncExitStack() as stack:
                store = await stack.enter_async_context(SqliteStore(Path(self._db)))
                live: list[Source] = []
                for source in build_sources(
                    self._cfg.sources or self._settings.sources or None, self._settings
                ):
                    try:
                        live.append(await stack.enter_async_context(source))
                    except Exception as exc:  # one bad provider is not fatal
                        self._log.error(f"news: source {source.name} unavailable: {exc}")
                fast = [s for s in live if not s.slow]
                slow = [s for s in live if s.slow]
                self._log.info(
                    f"news: collecting {[s.name for s in fast]} every "
                    f"{self._cfg.poll_seconds:.0f}s, {[s.name for s in slow]} every "
                    f"{self._slow_seconds:.0f}s, into {self._db}"
                )
                next_slow = 0.0
                while True:
                    started = time.monotonic()
                    due = list(fast)
                    if started >= next_slow:
                        due += slow
                        next_slow = started + self._slow_seconds
                    try:
                        if due:
                            harvest = await fetch_into(store, due, retries=self._settings.retries)
                            self._log.info(f"news: {harvest}")
                        await self._sweep(self._clock.timestamp_ns() / 1e9)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self._log.warning(f"news: poll failed: {exc}")
                    await asyncio.sleep(
                        max(0.0, self._cfg.poll_seconds - (time.monotonic() - started))
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A node that cannot collect the calendar must still trade: no
            # news is recoverable, a node that will not boot is not.
            self._log.error(f"news: collecting stopped: {exc}")

    @property
    def _slow_seconds(self) -> float:
        """The calendar clock, never faster than the headline one."""
        return max(self._cfg.poll_seconds, self._settings.calendar_poll_seconds)

    async def _sweep(self, now_s: float) -> None:
        """Publish every calendar stage that has become knowable by `now_s`.

        **The clock is an argument, not `self._clock`.** `Component._clock` is
        read-only - as `_log` is, which is why `read_rows` was pulled out of
        the client - so a sweep that read the clock itself could only be
        exercised by standing up a kernel, and the thing most worth testing
        here is precisely what it does with the time: an entry announced in
        the future, or a release that has not happened, must not be published.

        **Calendar entries only, deliberately.** A `MacroObservation` is
        served by `_request` but not emitted live, because the store records
        the *period* a reserve or a rate belongs to and not the day it was
        published - and those are weeks apart. Emitting one at its period
        stamp would be the lookahead this client exists to prevent, so the
        live side stays silent until a source carries a publication date.
        """
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


@dataclass(slots=True)
class Harvest:
    """What one collecting pass wrote.

    `updated` is the half worth reading: an event row is *rewritten* when its
    actual lands, so a pass that inserts nothing and updates twelve rows is a
    pass in which twelve prints came out.
    """

    articles: WriteResult = field(default_factory=WriteResult)
    events: WriteResult = field(default_factory=WriteResult)
    observations: WriteResult = field(default_factory=WriteResult)
    failed: int = 0

    def __str__(self) -> str:
        parts = [f"{self.articles.inserted} headlines"]
        if self.events.touched:
            parts.append(f"{self.events.inserted} new events, {self.events.updated} released")
        if self.observations.touched:
            parts.append(
                f"{self.observations.inserted} macro rows, {self.observations.updated} revised"
            )
        if self.failed:
            parts.append(f"{self.failed} failed")
        return ", ".join(parts)


async def fetch_into(store: Store, sources: Sequence[Source], *, retries: int = 3) -> Harvest:
    """Poll every source concurrently and write what came back.

    **A function rather than a method**, for the same reason `read_rows` is
    one: it needs a store and a list of sources, not a client, so the
    collecting half is exercisable with a fake source and a temporary file
    instead of a kernel.

    A source that fails is counted and logged, never raised: five providers
    must not go dark because the sixth did. `TransientError` is retried with
    backoff - a timeout or a throttle is worth another attempt - and
    `PermanentError` is not, because a 404 will be a 404 next minute too.
    """

    async def one(source: Source) -> Batch | None:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max(1, retries)),
                wait=wait_exponential_jitter(initial=1.0, max=15.0),
                retry=retry_if_exception_type(TransientError),
                reraise=True,
            ):
                with attempt:
                    return await source.poll()
        except Exception as exc:
            log.warning("%s poll failed: %s", source.name, exc)
            return None
        return None

    harvest = Harvest()
    batches = await asyncio.gather(*(one(source) for source in sources))
    for batch in batches:
        if batch is None:
            harvest.failed += 1
            continue
        # The store dedups, so a provider re-serving its whole window costs
        # one write that changes nothing rather than a duplicate row.
        if batch.articles:
            harvest.articles += await store.write_articles(batch.articles)
        if batch.events:
            harvest.events += await store.write_events(batch.events)
        if batch.observations:
            harvest.observations += await store.write_observations(batch.observations)
    return harvest


#: Which column bounds a request's window, per table, best first.
#:
#: **Not a single name, because the right one depends on what the store
#: actually has.** An event's window is its release time and only that. An
#: observation *should* be bounded by when it was published, which is when it
#: could have been acted on - but `store.py` records the period a figure
#: describes, so there is no `published` column to read and `time` is the
#: fallback. Asking for a column that is not there is how this read used to
#: return nothing at all: `SELECT * FROM observations ORDER BY published`
#: raised "no such column", and the client logged a warning and served an
#: empty history, which looks exactly like a store with no macro rows in it.
_BOUND_ON: dict[str, tuple[str, ...]] = {
    "events": ("time",),
    "observations": ("published", "time"),
}


def _bound_column(db: Any, table: str) -> str:
    """The first of `_BOUND_ON[table]` the table has, else the preferred one."""
    present = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    wanted = _BOUND_ON[table]
    return next((name for name in wanted if name in present), wanted[0])


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
    if table not in _BOUND_ON:
        return [], f"unknown table {table!r}"
    import sqlite3

    start = _seconds(getattr(request, "start", None))
    end = _seconds(getattr(request, "end", None))
    limit = int(getattr(request, "limit", 0) or 100_000)
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            column = _bound_column(db, table)
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
            params.append(limit)
            return [dict(r) for r in db.execute(sql, params)], ""
    except sqlite3.Error as exc:
        return [], str(exc)
