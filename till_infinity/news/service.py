"""Orchestration: poll every source, funnel headlines and events into a store.

Sources run on two clocks. Headlines are re-fetched every `news_poll_seconds`
because stories arrive continuously; calendars are marked `slow` and re-fetched
every `calendar_poll_seconds`, which is frequent enough to catch an `actual`
shortly after the print without hammering a file that changes hourly.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..bus import ARTICLES, EVENTS, MACRO, Bus
from ..logging import get_logger
from .calendar import ForexFactoryCalendar, TradingViewCalendar
from .config import DEFAULT_SOURCES, Settings
from .headlines import HeadlineSource
from .imf import ImfSource
from .models import Article, Batch, Event, WriteResult
from .rss import RssSource
from .source import Source, TransientError
from .store import Store

log = get_logger(__name__)

SOURCES: dict[str, type[Source]] = {
    RssSource.name: RssSource,
    ForexFactoryCalendar.name: ForexFactoryCalendar,
    TradingViewCalendar.name: TradingViewCalendar,
    HeadlineSource.name: HeadlineSource,
    ImfSource.name: ImfSource,
}


def build_sources(names: Sequence[str] | None, settings: Settings) -> list[Source]:
    chosen = tuple(names) if names else DEFAULT_SOURCES
    unknown = [n for n in chosen if n not in SOURCES]
    if unknown:
        raise ValueError(f"unknown source(s): {', '.join(unknown)} (have: {', '.join(SOURCES)})")
    return [SOURCES[name](settings) for name in chosen]


@dataclass(slots=True)
class Summary:
    """Outcome of one polling pass."""

    articles: WriteResult = field(default_factory=WriteResult)
    events: WriteResult = field(default_factory=WriteResult)
    observations: WriteResult = field(default_factory=WriteResult)
    failed: int = 0
    elapsed: float = 0.0

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
        return ", ".join(parts) + f" in {self.elapsed:.1f}s"


class Announcer:
    """Publishes what is genuinely new.

    The stores dedup on write but report only counts, so the bus needs its own
    memory of what it has already announced — otherwise every poll would
    re-announce the entire feed. It is an LRU rather than a set because a
    collector left running for a week must not grow one forever.
    """

    def __init__(self, bus: Bus, limit: int = 5_000) -> None:
        self.bus = bus
        self.limit = limit
        self._seen: OrderedDict[tuple[str, ...], None] = OrderedDict()

    def fresh(self, mark: tuple[str, ...]) -> bool:
        if mark in self._seen:
            self._seen.move_to_end(mark)
            return False
        self._seen[mark] = None
        while len(self._seen) > self.limit:
            self._seen.popitem(last=False)
        return True

    async def articles(self, items: Sequence[Article]) -> None:
        for item in items:
            if not self.fresh((ARTICLES, item.source, item.id)):
                continue
            await self.bus.publish(
                ARTICLES,
                {
                    "source": item.source,
                    "provider": item.provider,
                    "title": item.title,
                    "url": item.url,
                    "published": item.published,
                    "symbols": list(item.symbols),
                    "urgency": item.urgency,
                },
                source="news",
            )

    async def events(self, items: Sequence[Event]) -> None:
        for item in items:
            # `actual` is part of the mark on purpose: an event already
            # announced as upcoming is worth announcing again once it prints.
            if not self.fresh((EVENTS, item.source, item.id, item.actual or "")):
                continue
            await self.bus.publish(
                EVENTS,
                {
                    "source": item.source,
                    "country": item.country,
                    "title": item.title,
                    "time": item.time,
                    "importance": item.importance,
                    "actual": item.actual,
                    "forecast": item.forecast,
                    "previous": item.previous,
                    "unit": item.unit,
                    "released": bool(item.actual),
                },
                source="news",
            )

    async def macro(self, source: str, result: WriteResult, rows: int) -> None:
        """Macro moves in bulk — one IMF pull is thousands of historic rows.

        Announcing each would be noise, so this is a count: the notice says the
        series changed and the subscriber reads the store for the detail.
        """
        if not result.touched:
            return
        await self.bus.publish(
            MACRO,
            {
                "source": source,
                "inserted": result.inserted,
                "updated": result.updated,
                "rows": rows,
            },
            source="news",
        )


async def poll_once(
    *,
    settings: Settings,
    store: Store,
    sources: Sequence[Source],
    announcer: Announcer | None = None,
) -> Summary:
    """Poll the given sources concurrently and persist what they return."""
    started = time.monotonic()
    summary = Summary()

    async def one(source: Source) -> Batch | None:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max(1, settings.retries)),
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

    batches = await asyncio.gather(*(one(source) for source in sources))
    for source, batch in zip(sources, batches, strict=True):
        if batch is None:
            summary.failed += 1
            continue
        # Store first, announce after — the store stays the source of truth.
        if batch.articles:
            summary.articles += await store.write_articles(batch.articles)
            if announcer is not None:
                await announcer.articles(batch.articles)
        if batch.events:
            summary.events += await store.write_events(batch.events)
            if announcer is not None:
                await announcer.events(batch.events)
        if batch.observations:
            written = await store.write_observations(batch.observations)
            summary.observations += written
            if announcer is not None:
                await announcer.macro(source.name, written, len(batch.observations))

    summary.elapsed = time.monotonic() - started
    return summary


async def collect(
    *,
    settings: Settings,
    store: Store,
    sources: Sequence[str] | None = None,
    cycles: int | None = None,
    on_cycle: Callable[[int, Summary], None] | None = None,
    bus: Bus | None = None,
) -> None:
    """Poll forever (or `cycles` times), each source on its own clock."""
    announcer = Announcer(bus) if bus is not None else None
    cycle = 0
    async with AsyncExitStack() as stack:
        live: list[Source] = []
        for source in build_sources(sources, settings):
            try:
                live.append(await stack.enter_async_context(source))
            except Exception as exc:  # one bad provider is not fatal
                log.error("source %s unavailable: %s", source.name, exc)

        fast = [s for s in live if not s.slow]
        slow = [s for s in live if s.slow]
        next_slow = 0.0

        while cycles is None or cycle < cycles:
            started = time.monotonic()
            due = list(fast)
            if started >= next_slow or cycles is not None:
                due += slow
                next_slow = started + settings.calendar_poll_seconds

            summary = await poll_once(
                settings=settings, store=store, sources=due, announcer=announcer
            )
            cycle += 1
            if on_cycle is not None:
                on_cycle(cycle, summary)
            if cycles is not None and cycle >= cycles:
                return
            await asyncio.sleep(max(0.0, settings.news_poll_seconds - (time.monotonic() - started)))
