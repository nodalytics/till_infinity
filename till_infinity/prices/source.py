"""The contract every price source implements.

A source owns one symbol sweep end to end so it can reuse whatever connection
it has (TradingView keeps a socket open across intervals; Yahoo keeps a thread
pool warm). It hands finished bars to a sink instead of writing directly, which
keeps storage choices out of the fetch path.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import ClassVar, Self

from .config import Feed, Settings
from .models import Bar, Interval, SeriesKey, Symbol, WriteResult

BarSink = Callable[[SeriesKey, Sequence[Bar]], Awaitable[WriteResult]]


@dataclass(frozen=True, slots=True)
class Job:
    """One symbol's full interval sweep for a single source."""

    source: str
    feed: str
    symbol: Symbol
    intervals: tuple[Interval, ...]

    def key(self, interval: Interval) -> SeriesKey:
        return SeriesKey(self.source, self.feed, self.symbol, interval.name)

    def __str__(self) -> str:
        return f"{self.source}:{self.feed} {self.symbol.full}"


def first_cause(exc: BaseException, depth: int = 5) -> str:
    """Name the real failure behind an ExceptionGroup.

    anyio — which httpx-ws runs on — reports a failed connect as an
    ExceptionGroup whose str() is the famously unhelpful "unhandled errors in a
    TaskGroup (1 sub-exception)". Unwrap it so the log says what went wrong.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions and depth > 0:
        exc = exc.exceptions[0]
        depth -= 1
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class SourceError(Exception):
    """Base for source failures."""


class PermanentError(SourceError):
    """Bad symbol, unsupported interval — retrying will not help."""


class TransientError(SourceError):
    """Timeout, disconnect, throttle — worth another attempt."""


class Source(ABC):
    """Fetches candles for one provider."""

    name: ClassVar[str]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def concurrency(self) -> int:
        """How many symbol sweeps may run at once against this provider."""
        return 4

    def symbols(self, feed: Feed) -> tuple[Symbol, ...]:
        return feed.for_source(self.name)

    def supported(self, intervals: Sequence[Interval]) -> tuple[Interval, ...]:
        """Filter the requested intervals down to what this source can serve."""
        return tuple(intervals)

    def jobs(self, feeds: Sequence[Feed], intervals: Sequence[Interval]) -> list[Job]:
        usable = self.supported(intervals)
        if not usable:
            return []
        return [
            Job(self.name, feed.name, symbol, usable)
            for feed in feeds
            for symbol in self.symbols(feed)
        ]

    def keep(self, bars: Sequence[Bar], interval: Interval) -> list[Bar]:
        """Drop the still-forming bar unless the caller asked to keep it.

        The original script wrote the in-progress candle and then deduped on
        timestamp forever, so a partial bar could never be corrected. Closed
        bars only, by default.
        """
        if self.settings.include_partial:
            return list(bars)
        now = time.time()
        return [bar for bar in bars if bar.is_closed(interval, now)]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    @abstractmethod
    async def fetch(self, job: Job, bars: int, sink: BarSink) -> WriteResult:
        """Fetch every interval for `job`, passing each batch to `sink`."""
