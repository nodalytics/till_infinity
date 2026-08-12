"""Price data: fetch OHLCV candles from several providers and store them.

from till_infinity.prices import Settings, SqliteStore, backfill, resolve_feeds
from till_infinity.prices.models import resolve_intervals

settings = Settings.from_env()
async with SqliteStore(settings.database) as store:
    await backfill(
        settings=settings,
        store=store,
        feeds=resolve_feeds(("gold",)),
        intervals=resolve_intervals(("1h", "1d")),
    )
"""

from .config import (
    DEFAULT_SOURCES,
    DEFAULT_SYMBOLS,
    FEEDS,
    SYMBOL_ALIASES,
    TRADINGVIEW,
    YAHOO,
    Feed,
    Settings,
    resolve_feeds,
    resolve_symbols,
)
from .models import (
    DEFAULT_INTERVALS,
    INTERVALS,
    Bar,
    Interval,
    Quote,
    QuoteKey,
    SeriesInfo,
    SeriesKey,
    Symbol,
    WriteResult,
    resolve_intervals,
)
from .quotes import (
    DEFAULT_QUOTE_SOURCES,
    QUOTE_SOURCES,
    QuoteSource,
    QuoteTick,
    TradingViewQuotes,
    TradingViewScannerQuotes,
    YahooQuotes,
    build_quote_sources,
    poll_once,
    stream,
)
from .service import SOURCES, JobResult, Summary, backfill, build_sources, collect, sweep
from .source import Job, PermanentError, Source, SourceError, TransientError
from .store import JsonlStore, MultiStore, SqliteStore, Store, iter_bars, open_store
from .tradingview import TradingViewSource
from .yahoo import YahooSource

__all__ = [
    "DEFAULT_INTERVALS",
    "DEFAULT_QUOTE_SOURCES",
    "DEFAULT_SOURCES",
    "DEFAULT_SYMBOLS",
    "FEEDS",
    "INTERVALS",
    "QUOTE_SOURCES",
    "SOURCES",
    "SYMBOL_ALIASES",
    "TRADINGVIEW",
    "YAHOO",
    "Bar",
    "Feed",
    "Interval",
    "Job",
    "JobResult",
    "JsonlStore",
    "MultiStore",
    "PermanentError",
    "Quote",
    "QuoteKey",
    "QuoteSource",
    "QuoteTick",
    "SeriesInfo",
    "SeriesKey",
    "Settings",
    "Source",
    "SourceError",
    "SqliteStore",
    "Store",
    "Summary",
    "Symbol",
    "TradingViewQuotes",
    "TradingViewScannerQuotes",
    "TradingViewSource",
    "TransientError",
    "WriteResult",
    "YahooQuotes",
    "YahooSource",
    "backfill",
    "build_quote_sources",
    "build_sources",
    "collect",
    "iter_bars",
    "open_store",
    "poll_once",
    "resolve_feeds",
    "resolve_intervals",
    "resolve_symbols",
    "stream",
    "sweep",
]
