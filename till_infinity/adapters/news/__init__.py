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

The tree reads as the two halves plus what joins them:

    sources/   one module per provider: fetch, parse, return values
    store.py   the SQLite the live half writes and the history half reads
    client.py  the poll loop, the subscriptions and `_request`
    data.py    `CalendarEvent` and `MacroObservation`, and the lookahead guard

**`till_infinity/news/` was the service this replaced**, and its bus
orchestration is in `research/retire/news/`. What came across is everything
that fetches: nothing was rewritten, the parsers are the same files, and the
tests that pin them are the same tests.
"""

from .client import Harvest, NewsDataClient, NewsDataClientConfig, fetch_into, read_rows
from .data import CalendarEvent, Importance, MacroObservation, Stage
from .factories import NewsLiveDataClientFactory
from .store import SqliteStore

NEWS = "NEWS"

__all__ = [
    "NEWS",
    "CalendarEvent",
    "Harvest",
    "Importance",
    "MacroObservation",
    "NewsDataClient",
    "NewsDataClientConfig",
    "NewsLiveDataClientFactory",
    "SqliteStore",
    "Stage",
    "fetch_into",
    "read_rows",
]
