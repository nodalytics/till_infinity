"""The economic calendar and macro series, as a Nautilus data adapter.

**An adapter and not an Actor, and the reason is backtest parity.** An Actor
that fetches from the network cannot be backtested: during a backtest it would
call the live API and get *today's* calendar. A data client's `_request`
history replays into the catalogue, so a backtest sees the calendar **as it
stood then** - which is what this desk's journal already records for spreads
and the calendar, and what news is for: embargo windows.

Nautilus treats data-only adapters as first class - Databento, Tardis,
CoinAPI and Blockchain are all `LiveDataClient`s publishing custom types - so
this is the shape the framework already has, not one invented for us.
"""

from .client import NewsDataClient, NewsDataClientConfig
from .data import CalendarEvent, MacroObservation
from .factories import NewsLiveDataClientFactory

NEWS = "NEWS"

__all__ = [
    "NEWS",
    "CalendarEvent",
    "MacroObservation",
    "NewsDataClient",
    "NewsDataClientConfig",
    "NewsLiveDataClientFactory",
]
