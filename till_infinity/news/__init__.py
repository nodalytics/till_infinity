"""News and macro events: headlines, and the economic calendar around them.

    from till_infinity.news import Settings, SqliteStore, collect

    settings = Settings.from_env()
    async with SqliteStore(settings.database) as store:
        await collect(settings=settings, store=store, cycles=1)

Sources are RSS (ForexLive, FXStreet, Investing, CoinDesk, CoinTelegraph),
TradingView's symbol-attached headlines, and two economic calendars -
ForexFactory and TradingView - kept side by side so a print can be
cross-checked between providers.
"""

from .calendar import ForexFactoryCalendar, TradingViewCalendar
from .config import (
    CALENDAR_COUNTRIES,
    CALENDAR_CURRENCIES,
    DEFAULT_SOURCES,
    HEADLINE_CATEGORIES,
    HEADLINE_SYMBOLS,
    RSS_FEEDS,
    Settings,
)
from .headlines import HeadlineSource
from .imf import ImfSource, parse_dataset
from .models import (
    HIGH,
    LOW,
    MEDIUM,
    Article,
    Batch,
    Event,
    FeedInfo,
    Observation,
    WriteResult,
    parse_importance,
    parse_number,
    parse_period,
    parse_time,
)
from .rss import RssSource
from .service import SOURCES, Announcer, Summary, build_sources, collect, poll_once
from .source import PermanentError, Source, SourceError, TransientError
from .store import JsonlStore, MultiStore, SqliteStore, Store, open_store

__all__ = [
    "CALENDAR_COUNTRIES",
    "CALENDAR_CURRENCIES",
    "DEFAULT_SOURCES",
    "HEADLINE_CATEGORIES",
    "HEADLINE_SYMBOLS",
    "HIGH",
    "LOW",
    "MEDIUM",
    "RSS_FEEDS",
    "SOURCES",
    "Announcer",
    "Article",
    "Batch",
    "Event",
    "FeedInfo",
    "ForexFactoryCalendar",
    "HeadlineSource",
    "ImfSource",
    "JsonlStore",
    "MultiStore",
    "Observation",
    "PermanentError",
    "RssSource",
    "Settings",
    "Source",
    "SourceError",
    "SqliteStore",
    "Store",
    "Summary",
    "TradingViewCalendar",
    "TransientError",
    "WriteResult",
    "build_sources",
    "collect",
    "open_store",
    "parse_dataset",
    "parse_importance",
    "parse_number",
    "parse_period",
    "parse_time",
    "poll_once",
]
