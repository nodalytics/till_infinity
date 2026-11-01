"""Trading: turning level calls into positions, on MT5 or on paper.

    structures ──▶ structures.signals ──▶ trading ──┬──▶ broker
    prices     ──▶ prices.quotes     ──┘            ├──▶ alerts
                                                    └──▶ journal

The only part of this project that can lose money, and the only one that is
written to fail closed: paper unless `TRADING_LIVE=1`, no order without a
resolved symbol and a checked terminal, and every decision - taken or refused -
written to the journal beside the numbers it was made from.

```python
from . import Settings, listen

# Whatever this host can reach: the native package on Windows, the Wine bridge
# on Linux, the paper book if neither. Nothing is armed without TRADING_LIVE.
await listen(bus, settings=Settings.from_env(), journal=journal)
```

The pieces, in dependency order:

| | |
|---|---|
| `config` | what to trade, on which terminal, and the arming switch |
| `models` | sides, specs, ticks, intents, refusals - nothing broker-shaped |
| `broker` | the port, and which of the four backends this host can run |
| `symbols` | which instruments this broker actually offers, resolved once |
| `sizing` | volatility units to price, price to lots |
| `plans` | risk limits as named, internally consistent bundles |
| `context` | what the rest of the system knows: the calendar, the venues, the regime |
| `risk.exposure` | what is at risk per currency rather than per ticket. In
  `risk/`, because exposure is an account-level question |
| `risk` | may this account take another trade right now |
| `strategy` | the port a strategy implements, and the register |
| `scalper` | the four arithmetic level strategies |
| `turning` | the cycle reading as an entry, gated on its own record |
| `valuation` | asking an analyst what a thing is worth, rather than which way it goes |
| `speeds` | three EWMAs and their agreement, for `momentum-scalp` |
| `book` | the levels seen so far, for the ones that trade toward a level |
| `manage` | moving a stop after the trade is on. Off by default |
| `service` | the bus loop, the orders, the reconciliation, the record |
| `report` | scoring the closed trades, and refusing to when there are too few |
"""

from __future__ import annotations

from ..domain.models import (
    Account,
    Intent,
    Order,
    OrderResult,
    Position,
    Refusal,
    Side,
    SymbolSpec,
    Tick,
    Verdict,
)
from ..indicators.momentum import Speeds
from . import report
from .affordable import (
    CATASTROPHIC,
    STOPS,
    Affordability,
    judge,
    survey,
    unaffordable,
)
from .book import Book, Seen
from .config import (
    BACKENDS,
    DEFAULT_MAGIC,
    DEFAULT_SYMBOLS,
    HTTP,
    INSTRUMENTS,
    MAGIC_BAND,
    MAGIC_ORDER,
    NATIVE,
    OPTIONAL_SYMBOLS,
    PAPER,
    RPYC,
    SUFFIXES,
    Settings,
    feed_for,
    magic_for,
    ours,
    resolve_symbols,
    strategy_for,
)
from .context import Context, Release
from .desk import Desk, DeskConfig
from .entries import ArrivalEntry, EdgeEntry, RestingEntry
from .guard import Guard
from .manage import Move, advance
from .plans import PLANS, Plan
from .profile import Profile
from .report import Report, Trade
from .sizing import Sizing, lots, price_distance
from .surprise import Surprise, SurpriseArrival, SurpriseEdge, SurpriseResting
from .turning import TurnExit, TurnOutcome, TurnTally
from .valuation import Priced, Valuation, price_it

__all__ = [
    "BACKENDS",
    "CATASTROPHIC",
    "DEFAULT_MAGIC",
    "DEFAULT_SYMBOLS",
    "HTTP",
    "INSTRUMENTS",
    "MAGIC_BAND",
    "MAGIC_ORDER",
    "NATIVE",
    "OPTIONAL_SYMBOLS",
    "PAPER",
    "PLANS",
    "RPYC",
    "STOPS",
    "SUFFIXES",
    "Account",
    "Affordability",
    "ArrivalEntry",
    "Book",
    "Context",
    "Desk",
    "DeskConfig",
    "EdgeEntry",
    "Guard",
    "Intent",
    "Move",
    "Order",
    "OrderResult",
    "Plan",
    "Position",
    "Priced",
    "Profile",
    "Refusal",
    "Release",
    "Report",
    "RestingEntry",
    "Seen",
    "Settings",
    "Side",
    "Sizing",
    "Speeds",
    "Surprise",
    "SurpriseArrival",
    "SurpriseEdge",
    "SurpriseResting",
    "SymbolSpec",
    "Tick",
    "Trade",
    "TurnExit",
    "TurnOutcome",
    "TurnTally",
    "Valuation",
    "Verdict",
    "advance",
    "feed_for",
    "judge",
    "lots",
    "magic_for",
    "ours",
    "price_distance",
    "price_it",
    "report",
    "resolve_symbols",
    "strategy_for",
    "survey",
    "unaffordable",
]
