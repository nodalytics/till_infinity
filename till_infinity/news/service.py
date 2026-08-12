"""Orchestration: poll every source, funnel headlines and events into a store.

Sources run on two clocks. Headlines are re-fetched every `news_poll_seconds`
because stories arrive continuously; calendars are marked `slow` and re-fetched
every `calendar_poll_seconds`, which is frequent enough to catch an `actual`
shortly after the print without hammering a file that changes hourly.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..logging import get_logger
from .calendar import ForexFactoryCalendar, TradingViewCalendar
from .config import DEFAULT_SOURCES, Settings
from .headlines import HeadlineSource
from .imf import ImfSource
from .models import Batch, WriteResult
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


async def poll_once(
    *,
    settings: Settings,
    store: Store,
    sources: Sequence[Source],
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
    for batch in batches:
        if batch is None:
            summary.failed += 1
            continue
        if batch.articles:
            summary.articles += await store.write_articles(batch.articles)
        if batch.events:
            summary.events += await store.write_events(batch.events)
        if batch.observations:
            summary.observations += await store.write_observations(batch.observations)

    summary.elapsed = time.monotonic() - started
    return summary


async def collect(
    *,
    settings: Settings,
    store: Store,
    sources: Sequence[str] | None = None,
    cycles: int | None = None,
    on_cycle: Callable[[int, Summary], None] | None = None,
) -> None:
    """Poll forever (or `cycles` times), each source on its own clock."""
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

            summary = await poll_once(settings=settings, store=store, sources=due)
            cycle += 1
            if on_cycle is not None:
                on_cycle(cycle, summary)
            if cycles is not None and cycle >= cycles:
                return
            await asyncio.sleep(max(0.0, settings.news_poll_seconds - (time.monotonic() - started)))
