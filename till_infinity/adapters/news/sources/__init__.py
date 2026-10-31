"""The fetchers: one module per provider, and the plumbing they share.

**A source fetches and parses, and does nothing else.** It opens an HTTP
client, polls one provider, and returns a `Batch` of `Article`, `Event` and
`Observation` values. It does not persist, publish, retry on a schedule or
know that Nautilus exists - which is what lets every parser in here be tested
against a captured response with no database, no event loop policy and no
node. `test_news_parsers.py` is that test file, and the shape of it is the
argument for the boundary.

The contract is `Source`:

* `name` - the key in `SOURCES`, and the `source` column every row it writes
  carries. Two providers covering the same release are stored side by side
  under their own names, so a print can be cross-checked between them.
* `slow` - calendars and monthly macro series barely move between prints, so
  the client re-polls them on a longer clock than headline feeds.
* `async with source:` - opens and closes the HTTP client. A source that has
  not been entered raises rather than fetching without its timeouts.
* `await source.poll() -> Batch` - the current state of the provider, not a
  delta. Dedup belongs to the store, which knows what it already has.
* failures are `TransientError` (timeout, disconnect, 5xx - worth retrying) or
  `PermanentError` (404, a dead feed, a body that is not what the provider
  documents). The caller retries only the first kind; `PermanentError` on one
  provider must not take the other five with it.

**Nothing in here imports the store or the client**, and the direction is the
point: `adapters` may not reach up, and a parser that knew where its output
landed could not be run without the place it lands.
"""

from collections.abc import Sequence

from .calendar import (
    ForexFactoryCalendar,
    TradingViewCalendar,
    parse_forexfactory,
    parse_tradingview,
)
from .config import (
    CALENDAR_COUNTRIES,
    CALENDAR_CURRENCIES,
    DEFAULT_SOURCES,
    HEADLINE_CATEGORIES,
    HEADLINE_SYMBOLS,
    RSS_FEEDS,
    Settings,
)
from .cot import CotSource
from .fred import FredSource
from .headlines import HeadlineSource, category_for, parse_headlines
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
    clean,
    digest,
    parse_importance,
    parse_number,
    parse_period,
    parse_time,
)
from .rss import RssSource, parse_feed
from .source import PermanentError, Source, SourceError, TransientError

#: Every provider, by the name a configuration uses to ask for it.
#:
#: **This registry moved here from the retired bus service**, and it belongs
#: with the sources rather than with whatever polls them: the thing that knows
#: a provider exists should be the package that holds it, or adding a source
#: means editing a caller that has no other reason to change.
SOURCES: dict[str, type[Source]] = {
    RssSource.name: RssSource,
    ForexFactoryCalendar.name: ForexFactoryCalendar,
    TradingViewCalendar.name: TradingViewCalendar,
    HeadlineSource.name: HeadlineSource,
    ImfSource.name: ImfSource,
    FredSource.name: FredSource,
    CotSource.name: CotSource,
}


def build_sources(names: Sequence[str] | None, settings: Settings) -> list[Source]:
    """Construct the named sources, refusing a name nobody serves.

    Refused rather than skipped: a misspelled provider that silently collects
    nothing looks exactly like a provider that is up and quiet.
    """
    chosen = tuple(names) if names else DEFAULT_SOURCES
    unknown = [n for n in chosen if n not in SOURCES]
    if unknown:
        raise ValueError(f"unknown source(s): {', '.join(unknown)} (have: {', '.join(SOURCES)})")
    return [SOURCES[name](settings) for name in chosen]


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
    "Article",
    "Batch",
    "CotSource",
    "Event",
    "FeedInfo",
    "ForexFactoryCalendar",
    "FredSource",
    "HeadlineSource",
    "ImfSource",
    "Observation",
    "PermanentError",
    "RssSource",
    "Settings",
    "Source",
    "SourceError",
    "TradingViewCalendar",
    "TransientError",
    "WriteResult",
    "build_sources",
    "category_for",
    "clean",
    "digest",
    "parse_dataset",
    "parse_feed",
    "parse_forexfactory",
    "parse_headlines",
    "parse_importance",
    "parse_number",
    "parse_period",
    "parse_time",
    "parse_tradingview",
]
