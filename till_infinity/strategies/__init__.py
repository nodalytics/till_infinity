"""Trading: turning a published reading into a position, through Nautilus.

    statespace ──▶ statespace.proposals ──▶ a Desk ──┬──▶ ExecutionEngine ──▶ MT5
    prices     ──▶ the engine's own feed  ──┘        ├──▶ alerts
                                                     └──▶ journal

The only part of this project that can lose money. Each leaf here **is** a
`nautilus_trader` `Strategy`, so the framework assigns it a `strategy_id` and
carries it on every order, fill and position - which is what retired the magic
number as an identifier, after off-by-one relabelled every strategy as its
neighbour.

Nothing here builds a node, and that is a boundary the suite enforces: a
docstring that so much as *writes* the import is a failing test, because
`strategies` sits below `node` and a cycle would make either one unusable
alone. The desks named by `TRADING_SYMBOLS` x `TRADING_ENTRIES` are started
from above:

```sh
python -m till_infinity.node.live
```

**Arming is not here any more, and this is the one thing to know when reading
this package.** It used to be: `service.py` picked `PaperBroker` unless
`TRADING_LIVE=1`, and that sentence sat in this docstring. `service.py` retired
on 2026-11-01 and the switch went with it, which left a node that registered
the execution client unconditionally - real orders from an environment that
used to paper-trade. The gate is now `node/live._arm`, which puts Nautilus's
`RiskEngine` in `HALTED` without `TRADING_LIVE=1`: it denies every trading
command except cancels, below the strategies and above the client, so nothing
a decision, an exit or a managed stop does can route around it. **A strategy
in this package may therefore assume it is allowed to try, and must not
assume its order went anywhere.**

The pieces, in dependency order:

| | |
|---|---|
| `config` | what to trade, on which terminal, and the magic the bridge stamps |
| `profile` | the numbers a decision runs on, and the helpers measured on them |
| `surprise` | the one registered decision: is this reading worth trading |
| `entries` | the three mechanisms that place it - at market, resting, on arrival |
| `exits` | moving a stop, banking, turning out, and letting a stale one go |
| `basket` | the one exit that is portfolio-wide, so an Actor rather than a strategy |
| `desk` | the gate sequence, in the order it is applied, and the journal reasons |
| `counterfactual` | what would have happened to the ones it refused |
| `sizing` | volatility units to price, price to lots |
| `plans` | risk limits as named, internally consistent bundles |
| `affordable` | whether the account can survive the stop it is about to set |
| `floors` | pushing a target out until it pays for its own risk |
| `context` | what the rest of the system knows: the calendar, the venues, the regime |
| `guard` | may this account take another trade right now |
| `book` | the levels seen so far, for the ones that trade toward a level |
| `sessions` | which hours a feed is worth trading in |
| `spreads` | what a round trip costs, in the units the decision uses |
| `manage` | moving a stop after the trade is on. Off by default |
| `turning` | the cycle reading as an entry, gated on its own record |
| `valuation` | asking what a thing is worth, rather than which way it goes |
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
