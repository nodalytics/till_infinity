"""Orchestration: fan symbol sweeps out across sources, funnel bars into a store.

Every source gets its own concurrency limit (TradingView tolerates more parallel
sockets than Yahoo tolerates parallel scrapes), and a failed symbol retries with
backoff without stalling the others.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..logging import get_logger
from .config import DEFAULT_SOURCES, Feed, Settings
from .models import INTERVALS, Bar, Interval, SeriesKey, WriteResult
from .source import Job, Source, TransientError
from .store import Store
from .tradingview import TradingViewSource
from .yahoo import YahooSource

log = get_logger(__name__)

SOURCES: dict[str, type[Source]] = {
    TradingViewSource.name: TradingViewSource,
    YahooSource.name: YahooSource,
}


def build_sources(names: Sequence[str] | None, settings: Settings) -> list[Source]:
    chosen = tuple(names) if names else DEFAULT_SOURCES
    unknown = [n for n in chosen if n not in SOURCES]
    if unknown:
        raise ValueError(f"unknown source(s): {', '.join(unknown)} (have: {', '.join(SOURCES)})")
    return [SOURCES[name](settings) for name in chosen]


@dataclass(frozen=True, slots=True)
class JobResult:
    job: Job
    result: WriteResult
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(slots=True)
class Summary:
    """Outcome of one full sweep."""

    total: WriteResult = field(default_factory=WriteResult)
    jobs: int = 0
    failed: int = 0
    elapsed: float = 0.0

    def __str__(self) -> str:
        return (
            f"{self.total.inserted} new, {self.total.updated} updated "
            f"across {self.jobs} symbol sweeps"
            + (f", {self.failed} failed" if self.failed else "")
            + f" in {self.elapsed:.1f}s"
        )


ProgressHook = Callable[[JobResult], None]


async def sweep(
    *,
    settings: Settings,
    store: Store,
    feeds: Sequence[Feed],
    intervals: Sequence[Interval],
    bars: int,
    sources: Sequence[str] | None = None,
    on_done: ProgressHook | None = None,
) -> Summary:
    """Run one pass over every (source, feed, symbol) and persist what comes back."""
    started = time.monotonic()
    summary = Summary()

    async def sink(key: SeriesKey, candles: Sequence[Bar]) -> WriteResult:
        return await store.write(key, candles, INTERVALS[key.interval])

    async with AsyncExitStack() as stack:
        live: list[Source] = []
        for source in build_sources(sources, settings):
            try:
                live.append(await stack.enter_async_context(source))
            except Exception as exc:
                log.error("source %s unavailable: %s", source.name, exc)

        tasks: list[asyncio.Task[JobResult]] = []
        async with asyncio.TaskGroup() as group:
            for source in live:
                limit = asyncio.Semaphore(max(1, source.concurrency))
                tasks.extend(
                    group.create_task(_run_job(source, job, bars, sink, limit, settings))
                    for job in source.jobs(feeds, intervals)
                )

    for task in tasks:
        outcome = task.result()
        summary.jobs += 1
        summary.total += outcome.result
        if not outcome.ok:
            summary.failed += 1
        if on_done is not None:
            on_done(outcome)

    summary.elapsed = time.monotonic() - started
    return summary


async def _run_job(
    source: Source,
    job: Job,
    bars: int,
    sink: Callable[..., object],
    limit: asyncio.Semaphore,
    settings: Settings,
) -> JobResult:
    async with limit:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max(1, settings.retries)),
                wait=wait_exponential_jitter(initial=1.0, max=20.0),
                retry=retry_if_exception_type(TransientError),
                reraise=True,
            ):
                with attempt:
                    return JobResult(job, await source.fetch(job, bars, sink))  # type: ignore[arg-type]
        except RetryError as exc:  # pragma: no cover - reraise=True makes this rare
            return JobResult(job, WriteResult(), str(exc))
        except Exception as exc:
            log.warning("%s failed: %s", job, exc)
            return JobResult(job, WriteResult(), str(exc))
    raise AssertionError("unreachable")


async def backfill(
    *,
    settings: Settings,
    store: Store,
    feeds: Sequence[Feed],
    intervals: Sequence[Interval],
    sources: Sequence[str] | None = None,
    bars: int | None = None,
    on_done: ProgressHook | None = None,
) -> Summary:
    """One deep pull per series, as far back as each provider will go."""
    return await sweep(
        settings=settings,
        store=store,
        feeds=feeds,
        intervals=intervals,
        bars=bars or settings.backfill_bars,
        sources=sources,
        on_done=on_done,
    )


async def collect(
    *,
    settings: Settings,
    store: Store,
    feeds: Sequence[Feed],
    intervals: Sequence[Interval],
    sources: Sequence[str] | None = None,
    bars: int | None = None,
    cycles: int | None = None,
    on_cycle: Callable[[int, Summary], None] | None = None,
    on_done: ProgressHook | None = None,
) -> None:
    """Poll for new bars forever (or `cycles` times), pacing each pass."""
    window = bars or settings.live_bars
    cycle = 0
    while cycles is None or cycle < cycles:
        started = time.monotonic()
        summary = await sweep(
            settings=settings,
            store=store,
            feeds=feeds,
            intervals=intervals,
            bars=window,
            sources=sources,
            on_done=on_done,
        )
        cycle += 1
        if on_cycle is not None:
            on_cycle(cycle, summary)
        if cycles is not None and cycle >= cycles:
            return
        await asyncio.sleep(max(0.0, settings.cycle_seconds - (time.monotonic() - started)))
