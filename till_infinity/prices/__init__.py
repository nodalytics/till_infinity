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
    DEFAULT_RETAIN_BARS,
    DEFAULT_SOURCES,
    DEFAULT_SYMBOLS,
    FEEDS,
    SYMBOL_ALIASES,
    TRADINGVIEW,
    YAHOO,
    Feed,
    Settings,
    bar_source_names,
    broker_feed_names,
    ccxt_feed_names,
    quote_source_names,
    register_broker_feeds,
    register_ccxt_feeds,
    resolve_feeds,
    resolve_symbols,
)
from .crypto import Board, CcxtSource, Filters, discover_ccxt, filters_from, pairs_for
from .models import (
    DEFAULT_INTERVALS,
    INTERVALS,
    Bar,
    Interval,
    PruneResult,
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
    "DEFAULT_RETAIN_BARS",
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
    "Board",
    "CcxtSource",
    "Feed",
    "Filters",
    "Interval",
    "Job",
    "JobResult",
    "JsonlStore",
    "MultiStore",
    "PermanentError",
    "PruneResult",
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
    "bar_source_names",
    "broker_feed_names",
    "build_quote_sources",
    "build_sources",
    "ccxt_feed_names",
    "collect",
    "discover_ccxt",
    "filters_from",
    "iter_bars",
    "open_store",
    "pairs_for",
    "poll_once",
    "quote_source_names",
    "register_broker_feeds",
    "register_ccxt_feeds",
    "resolve_feeds",
    "resolve_intervals",
    "resolve_symbols",
    "stream",
    "sweep",
]
