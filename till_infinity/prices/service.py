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

from ..bus import BARS, Bus
from ..logging import get_logger
from .config import DEFAULT_SOURCES, Feed, Settings
from .models import INTERVALS, Bar, Interval, SeriesKey, WriteResult
from .source import Job, Source, TransientError, first_cause
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


#: Most bars one sweep may announce for a single series.
#:
#: A sweep asks for hundreds of bars and usually writes one or two new ones, so
#: this bites only after a gap - a restart, a dropped connection, an interval
#: slower than the sweep cadence. In those cases the live path needs the bars it
#: missed, but it does not need a backfill replayed onto the bus one message at
#: a time: `structures` seeds itself from the store, which is the path built for
#: bulk, and this one is for keeping up.
#:
#: When more than this are new the oldest are dropped and `sweep` says so,
#: because a live path quietly seeing less than the store is the exact shape of
#: the bug this was written to fix.
MAX_NOTICES = 8


def announce_bars(key: SeriesKey, candles: Sequence[Bar], result: WriteResult) -> dict[str, object]:
    """What goes on the wire when a series moves - a notice, not the candles.

    The newest bar only. `notices` is what the sweep actually publishes; this
    remains because a single-bar notice is what most callers mean.
    """
    latest = max(candles, key=lambda bar: bar.time)
    return _notice(key, latest, result)


def notices(key: SeriesKey, candles: Sequence[Bar], result: WriteResult) -> list[dict[str, object]]:
    """One notice per newly written bar, oldest first.

    **This used to be one notice carrying only the newest bar**, whatever the
    sweep had written. Everything else went to the store and never reached the
    bus, so on any sweep that wrote more than one bar the live path formed
    levels from a subset of the series and counted touches on a subset of the
    interactions - silently, and differently from a replay of the same data.
    That is the same shape as the close-only bug: the live path seeing less
    than the store, with nothing saying so.

    Republishing is safe where it overlaps. `Series.add` treats a bar it
    already holds as a correction rather than a new one, and the touch check is
    gated on the bar being new, so a bar delivered twice cannot count its
    interaction twice.
    """
    if not candles:
        return []
    fresh = sorted(candles, key=lambda bar: bar.time)[-max(1, result.touched) :]
    return [_notice(key, bar, result) for bar in fresh[-MAX_NOTICES:]]


def _notice(key: SeriesKey, latest: Bar, result: WriteResult) -> dict[str, object]:
    return {
        "source": key.source,
        "feed": key.feed,
        "venue": key.symbol.venue,
        "ticker": key.symbol.ticker,
        "interval": key.interval,
        "inserted": result.inserted,
        "updated": result.updated,
        "time": latest.time,
        "open": latest.open,
        # The extremes, which used to be left off. `structures` reads them with
        # a fallback of `high = low = close`, so every bar arriving live looked
        # like a doji: levels formed on the live path were built from closing
        # prices alone, and the leg extremes that place an origin existed only
        # in the replayed history. A notice is still a notice - these are four
        # floats, not the candle series.
        "high": latest.high,
        "low": latest.low,
        #: Activity, not size: TradingView's `v` counts price changes rather
        #: than contracts, and spot FX has no real volume at all. Consumers
        #: must treat it as a ratio against the instrument's own typical bar.
        "volume": latest.volume,
        "close": latest.close,
        "closed": latest.is_closed(INTERVALS[key.interval], time.time()),
    }


async def sweep(
    *,
    settings: Settings,
    store: Store,
    feeds: Sequence[Feed],
    intervals: Sequence[Interval],
    bars: int,
    sources: Sequence[str] | None = None,
    on_done: ProgressHook | None = None,
    bus: Bus | None = None,
) -> Summary:
    """Run one pass over every (source, feed, symbol) and persist what comes back."""
    started = time.monotonic()
    summary = Summary()

    async def sink(key: SeriesKey, candles: Sequence[Bar]) -> WriteResult:
        # Store first, announce after: the store is the source of truth, so a
        # subscriber that hears about a bar can always go and read it.
        result = await store.write(key, candles, INTERVALS[key.interval])
        if bus is not None and result.touched and candles:
            batch = notices(key, candles, result)
            dropped = min(result.touched, len(candles)) - len(batch)
            if dropped > 0:
                log.warning(
                    "prices: %s wrote %d bars and announced %d - %d never reached the live path",
                    key,
                    result.touched,
                    len(batch),
                    dropped,
                )
            for payload in batch:
                await bus.publish(BARS, payload, source="prices")
        return result

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
            reason = first_cause(exc)
            log.warning("%s failed: %s", job, reason)
            return JobResult(job, WriteResult(), reason)
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
    bus: Bus | None = None,
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
        bus=bus,
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
    bus: Bus | None = None,
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
            bus=bus,
        )
        cycle += 1
        if on_cycle is not None:
            on_cycle(cycle, summary)
        if cycles is not None and cycle >= cycles:
            return
        await asyncio.sleep(max(0.0, settings.cycle_seconds - (time.monotonic() - started)))
