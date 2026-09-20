"""Orchestration: fan symbol sweeps out across sources, funnel bars into a store.

Every source gets its own concurrency limit (TradingView tolerates more parallel
sockets than Yahoo tolerates parallel scrapes), and a failed symbol retries with
backoff without stalling the others.
"""

from __future__ import annotations

import asyncio
import sqlite3
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
from .broker import BrokerSource
from .config import DEFAULT_SOURCES, Feed, Settings
from .crypto import CcxtSource
from .models import INTERVALS, Bar, Interval, SeriesKey, WriteResult
from .source import Job, Source, TransientError, first_cause
from .spreads import SOURCE as SPREAD_SOURCE
from .spreads import Built, Spread, aggregate, catalogue, construct, register
from .store import Store
from .tradingview import TradingViewSource
from .yahoo import YahooSource

log = get_logger(__name__)

SOURCES: dict[str, type[Source]] = {
    TradingViewSource.name: TradingViewSource,
    YahooSource.name: YahooSource,
    BrokerSource.name: BrokerSource,
    CcxtSource.name: CcxtSource,
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

    See `prices-service.md` in research/docs.
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


async def announce(bus: Bus, key: SeriesKey, candles: Sequence[Bar], result: WriteResult) -> None:
    """Publish one notice per new bar, and say so when `MAX_NOTICES` truncates.

    Both sweeps announce and only one of them counted what `notices` left out,
    so a derived spread with more than `MAX_NOTICES` new bars lost its oldest
    ones silently - the exact shape `MAX_NOTICES` documents a warning against.
    Shared rather than repeated, so the accounting cannot be forgotten by the
    next caller either.
    """
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
            await announce(bus, key, candles, result)
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


@dataclass(slots=True)
class DeriveSummary:
    """What one derivation pass produced, per constructed feed."""

    built: int = 0
    written: int = 0
    skipped: int = 0
    thin: list[str] = field(default_factory=list)
    elapsed: float = 0.0

    def __str__(self) -> str:
        out = f"{self.built} series, {self.written} bars written"
        if self.skipped:
            out += f", {self.skipped} with nothing to build"
        return out


async def derive(
    *,
    settings: Settings,
    store: Store,
    spreads: Sequence[Spread],
    intervals: Sequence[Interval],
    base: str = "1m",
    bars: int = 0,
    bus: Bus | None = None,
) -> DeriveSummary:
    """Build constructed spread series from stored bars, and store them like any other.

    See `prices-service.md` in research/docs.
    """
    started = time.monotonic()
    summary = DeriveSummary()
    path = settings.database
    if path is None or not spreads:
        return summary

    def build_all() -> list[Built]:
        made: list[Built] = []
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            for spread in spreads:
                for interval in intervals:
                    if interval.name == base:
                        got = construct(conn, spread, base, limit=bars)
                    else:
                        got = aggregate(
                            conn,
                            spread,
                            interval.name,
                            base=base,
                            seconds=interval.seconds,
                            limit=bars,
                        )
                    made.append(got)
        return made

    try:
        results = await asyncio.to_thread(build_all)
    except sqlite3.Error as exc:
        log.warning("prices: could not read bars to derive spreads: %s", exc)
        return summary

    for got in results:
        if not got.bars:
            summary.skipped += 1
            continue
        summary.built += 1
        # A spread that drops more buckets than it keeps is two series that
        # were rarely collected at the same moment, not an instrument. Named
        # rather than filtered: the bars it did build are still correct, and
        # what to do about a thin one is a decision somebody makes.
        if got.dropped > len(got.bars):
            summary.thin.append(f"{got.spread.name} {got.interval}")
        key = SeriesKey(
            source=SPREAD_SOURCE,
            feed=got.spread.name,
            symbol=got.spread.symbol,
            interval=got.interval,
        )
        interval = INTERVALS[got.interval]
        # The open bucket is still moving - its last leg bar is the current one
        # - so it is written like any other partial bar and `closed` on the
        # notice says so.
        result = await store.write(key, got.bars, interval)
        summary.written += result.touched
        if bus is not None and result.touched:
            await announce(bus, key, got.bars, result)
    summary.elapsed = time.monotonic() - started
    log.info(
        "prices: derived %s in %.1fs%s",
        summary,
        summary.elapsed,
        f" (thin: {', '.join(summary.thin[:5])})" if summary.thin else "",
    )
    return summary


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


def spread_catalogue(settings: Settings) -> list[Spread]:
    """The constructed series this configuration asks for, registered as feeds.

    Registered here rather than at import: which spreads exist is a property of
    what the store actually holds, so it cannot be a module constant. Reading
    the store once at the top of the loop is the compromise - a venue that
    starts being collected mid-run is picked up on the next restart, and a
    catalogue that changed under a running service would be worse.
    """
    if not settings.spreads or settings.database is None:
        return []
    try:
        with sqlite3.connect(f"file:{settings.database}?mode=ro", uri=True) as conn:
            found = catalogue(
                conn,
                kinds=settings.spread_kinds,
                interval=settings.spread_base,
                min_shared=settings.spread_min_shared,
                cross_source=settings.spread_cross_source,
                pairs=settings.spread_pairs,
            )
    except sqlite3.Error as exc:
        log.warning("prices: could not read the store to list spreads: %s", exc)
        return []
    added = register(found)
    log.info(
        "prices: %d constructed spread(s), %d new, %d tradeable",
        len(found),
        len(added),
        sum(1 for s in found if s.tradeable),
    )
    return found


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
    # In a thread, because every actor on this box shares one event loop and
    # this reads the store. Discovery is a census of every stored series and
    # costs a full pass over a 23GB table; run inline, that pass held the loop
    # and the desk wrote no quotes while it ran.
    spreads = await asyncio.to_thread(spread_catalogue, settings)
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
        if spreads:
            # After the sweep, never beside it: these are built out of the bars
            # it just wrote, and overlapping the two would pair one leg's new
            # bar with the other's old one.
            await derive(
                settings=settings,
                store=store,
                spreads=spreads,
                intervals=intervals,
                base=settings.spread_base,
                bars=window,
                bus=bus,
            )
        cycle += 1
        if on_cycle is not None:
            on_cycle(cycle, summary)
        if cycles is not None and cycle >= cycles:
            return
        await asyncio.sleep(max(0.0, settings.cycle_seconds - (time.monotonic() - started)))
