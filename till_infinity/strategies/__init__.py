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

**`sizing` and `affordable` left for `risk/` on 2026-11-01**, which is part of
why the table below is four rows shorter than the directory. Both answer account
questions - how many lots a risk budget buys, and whether the account survives
the smallest position an instrument permits - and neither reads a signal, so
neither was a strategy's business. They are not re-exported here either: a name
re-exported from two packages is a name whose owner nobody can tell.

**`guard` and `plans` followed them the same day**, which is the move
`risk/__init__.py` had written down as blocked. What unblocked it is
`Settings.envelope()` in `config.py`: the twenty-two numbers those two need,
projected into a frozen `risk.envelope.Envelope` and handed down as an
argument. `guard` also needed five methods of `context`, and takes a
structural protocol instead - so the context still answers the questions and
the import still points downhill. `Guard`, `Plan` and `PLANS` are gone from
the names below on the same rule as `sizing`.

What stayed, and why, is worth knowing before offering `risk/` anything else:
`sessions` and `spreads` are not risk at all. Tradable hours and what a round
trip costs are *inputs* to a decision, and neither can refuse anything on its
own.

The pieces, in dependency order:

| | |
|---|---|
| `config` | what to trade, on which terminal, and the magic the bridge stamps |
| `profile` | the numbers a decision runs on, and the helpers measured on them |
| `surprise` | the one registered decision: is this reading worth trading |
| `entries` | the three mechanisms that place it - at market, resting, on arrival |
| `exits` | the two mechanisms that hold it - the venue's bracket, or ours |
| `basket` | the one exit that is portfolio-wide, so an Actor rather than a strategy |
| `desk` | the gate sequence, in the order it is applied, and the journal reasons |
| `counterfactual` | what would have happened to the ones it refused |
| `floors` | pushing a target out until it pays for its own risk |
| `context` | what the rest of the system knows: the calendar, the venues, the regime |
| `book` | the levels seen so far, for the ones that trade toward a level |
| `sessions` | which hours a feed is worth trading in |
| `spreads` | what a round trip costs, in the units the decision uses |
| `manage` | moving a stop after the trade is on. Off by default |
| `turning` | the cycle reading as an entry, gated on its own record |
| `valuation` | asking what a thing is worth, rather than which way it goes |
| `report` | scoring the closed trades, and refusing to when there are too few |

`leaves` is not in the table and is not re-exported here, deliberately: it is
the one module that names every **(decision, exit, entry)** this node builds,
and it reaches into `statespace` for the two side decisions. Importing it from
here would put the whole statespace fold behind `import till_infinity.strategies`
for every caller, including the ones that only want `Settings`. `node/desks.py`
imports it directly, which is the only thing that needs it.
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
from .exits import (
    ExitMechanism,
    Exits,
    ManagedExit,
    Plan,
    Protection,
    VenueExit,
    protection_for,
)
from .manage import Move, advance
from .profile import Profile
from .report import Report, Trade
from .structure import Fold, Structure, StructureEdge
from .surprise import Surprise, SurpriseArrival, SurpriseEdge, SurpriseResting
from .turning import TurnExit, TurnOutcome, TurnTally
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
    "RPYC",
    "SUFFIXES",
    "Account",
    "ArrivalEntry",
    "Book",
    "Context",
    "Desk",
    "DeskConfig",
    "EdgeEntry",
    "ExitMechanism",
    "Exits",
    "Fold",
    "Intent",
    "ManagedExit",
    "Move",
    "Order",
    "OrderResult",
    "Plan",
    "Position",
    "Priced",
    "Profile",
    "Protection",
    "Refusal",
    "Release",
    "Report",
    "RestingEntry",
    "Seen",
    "Settings",
    "Side",
    "Speeds",
    "Structure",
    "StructureEdge",
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
    "VenueExit",
    "Verdict",
    "advance",
    "feed_for",
    "magic_for",
    "ours",
    "price_it",
    "protection_for",
    "report",
    "resolve_symbols",
    "strategy_for",
]
