"""Trading: turning level calls into positions, on MT5 or on paper.

    structures ──▶ structures.signals ──▶ trading ──┬──▶ broker
    prices     ──▶ prices.quotes     ──┘            ├──▶ alerts
                                                    └──▶ journal

The only part of this project that can lose money, and the only one that is
written to fail closed: paper unless `TRADING_LIVE=1`, no order without a
resolved symbol and a checked terminal, and every decision — taken or refused —
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
| `models` | sides, specs, ticks, intents, refusals — nothing broker-shaped |
| `broker` | the port, and which of the three backends this host can run |
| `symbols` | which instruments this broker actually offers, resolved once |
| `sizing` | volatility units to price, price to lots |
| `plans` | risk limits as named, internally consistent bundles |
| `risk` | may this account take another trade right now |
| `strategy` | the port a strategy implements, and the register |
| `scalper` | the five level strategies |
| `speeds` | three EWMAs and their agreement, for `momentum-scalp` |
| `book` | the levels seen so far, for the ones that trade toward a level |
| `service` | the bus loop, the orders, the reconciliation, the record |
"""

from __future__ import annotations

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
    NATIVE,
    OPTIONAL_SYMBOLS,
    PAPER,
    SUFFIXES,
    Settings,
    feed_for,
    resolve_symbols,
)
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
from .risk import Guard
from .scalper import (
    ApproachScalp,
    ConfluenceScalp,
    LevelScalp,
    LevelStrategy,
    MomentumScalp,
)
from .service import Trader, listen
from .sizing import Sizing, lots, price_distance
from .speeds import Speeds
from .strategy import STRATEGIES, Strategy, catalogue
from .symbols import Resolution, resolve

__all__ = [
    "BACKENDS",
    "DEFAULT_MAGIC",
    "DEFAULT_SYMBOLS",
    "HTTP",
    "INSTRUMENTS",
    "NATIVE",
    "OPTIONAL_SYMBOLS",
    "PAPER",
    "PLANS",
    "STRATEGIES",
    "SUFFIXES",
    "Account",
    "ApproachScalp",
    "Book",
    "Broker",
    "BrokerError",
    "ConfluenceScalp",
    "Guard",
    "Intent",
    "LevelScalp",
    "LevelStrategy",
    "MomentumScalp",
    "NotConnectedError",
    "Order",
    "OrderResult",
    "PaperBroker",
    "Plan",
    "Position",
    "Refusal",
    "RejectedError",
    "Resolution",
    "Seen",
    "Settings",
    "Side",
    "Sizing",
    "Speeds",
    "Strategy",
    "SymbolSpec",
    "Tick",
    "Trader",
    "TransientError",
    "Verdict",
    "available",
    "build",
    "catalogue",
    "choose",
    "feed_for",
    "listen",
    "lots",
    "price_distance",
    "resolve",
    "resolve_symbols",
]
