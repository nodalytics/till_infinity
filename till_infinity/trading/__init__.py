"""Trading: turning level calls into positions, on MT5 or on paper.

    structures ──▶ structures.signals ──▶ trading ──┬──▶ broker
    prices     ──▶ prices.quotes     ──┘            ├──▶ alerts
                                                    └──▶ journal

The only part of this project that can lose money, and the only one that is
written to fail closed: paper unless `TRADING_LIVE=1`, no order without a
resolved symbol and a checked terminal, and every decision - taken or refused -
written to the journal beside the numbers it was made from.

```python
from till_infinity.trading import Settings, listen

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
| `exposure` | what is at risk per currency, as opposed to per ticket |
| `risk` | may this account take another trade right now |
| `strategy` | the port a strategy implements, and the register |
| `scalper` | the four arithmetic level strategies |
| `council` | agents that reason their own way to a trade, and discuss it |
| `valuation` | asking an analyst what a thing is worth, rather than which way it goes |
| `speeds` | three EWMAs and their agreement, for `momentum-scalp` |
| `book` | the levels seen so far, for the ones that trade toward a level |
| `manage` | moving a stop after the trade is on. Off by default |
| `service` | the bus loop, the orders, the reconciliation, the record |
| `report` | scoring the closed trades, and refusing to when there are too few |
"""

from __future__ import annotations

from . import exposure, report
from .book import Book, Seen
from .broker import (
    Broker,
    BrokerError,
    NotConnectedError,
    RejectedError,
    TransientError,
    available,
    build,
    choose,
)
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
from .council import Council, CouncilStrategy, Opinion, Voice
from .exposure import Exposure
from .manage import Move, advance
from .models import (
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
from .paper import PaperBroker
from .plans import PLANS, Plan
from .report import Report, Trade
from .risk import Guard
from .scalper import (
    ConfluenceScalp,
    LevelScalp,
    LevelStrategy,
    MomentumScalp,
    SweepAware,
)
from .service import Trader, listen
from .sizing import Sizing, lots, price_distance
from .speeds import Speeds
from .strategy import STRATEGIES, Strategy, catalogue
from .swing import (
    ApproachScalp,
    FadeToValue,
    OriginSwing,
    Runner,
    SwingLevel,
)
from .symbols import Resolution, resolve
from .valuation import Priced, Valuation, price_it

__all__ = [
    "BACKENDS",
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
    "STRATEGIES",
    "SUFFIXES",
    "Account",
    "ApproachScalp",
    "Book",
    "Broker",
    "BrokerError",
    "ConfluenceScalp",
    "Context",
    "Council",
    "CouncilStrategy",
    "Exposure",
    "FadeToValue",
    "Guard",
    "Intent",
    "LevelScalp",
    "LevelStrategy",
    "MomentumScalp",
    "Move",
    "NotConnectedError",
    "Opinion",
    "Order",
    "OrderResult",
    "OriginSwing",
    "PaperBroker",
    "Plan",
    "Position",
    "Priced",
    "Refusal",
    "RejectedError",
    "Release",
    "Report",
    "Resolution",
    "Runner",
    "Seen",
    "Settings",
    "Side",
    "Sizing",
    "Speeds",
    "Strategy",
    "SweepAware",
    "SwingLevel",
    "SymbolSpec",
    "Tick",
    "Trade",
    "Trader",
    "TransientError",
    "Valuation",
    "Verdict",
    "Voice",
    "advance",
    "available",
    "build",
    "catalogue",
    "choose",
    "exposure",
    "feed_for",
    "listen",
    "lots",
    "magic_for",
    "ours",
    "price_distance",
    "price_it",
    "report",
    "resolve",
    "resolve_symbols",
    "strategy_for",
]
