"""Which client factory a venue gets, so a node is not one broker's node.

`live.py` used to register `MT5LiveDataClientFactory` for every venue it
built, which made "multi-venue" mean "several MT5 accounts". It is a real
arrangement - a demo beside a live one, two brokers both on MT5 - but it is
not the question somebody asks when they say multi-venue.

**Nautilus ships eighteen adapters** and they all follow one naming
convention: a module under `nautilus_trader.adapters.<kind>` exporting
`<Name>LiveDataClientFactory`, `<Name>LiveExecClientFactory`,
`<Name>DataClientConfig` and `<Name>ExecClientConfig`. So this resolves them
**by shape rather than by a table of names**: the four classes are found by
what they are called, not by a mapping somebody has to extend. Adding Binance
is then a value in `TRADING_VENUES`, not a code change, and the eighteen
include `binance`, `bybit`, `kraken`, `okx`, `deribit`, `hyperliquid`,
`polymarket`, `interactive_brokers`, `databento` and `sandbox`.

    TRADING_VENUES="MT5,BINANCE"
    TRADING_SYMBOLS_MT5="EURUSD,XAUUSD"
    TRADING_SYMBOLS_BINANCE="ETHUSDT-PERP,BTCUSDT-PERP"

## What this does and does not buy

**It buys one kernel over several venues**, which is the part that matters:
one cache, one portfolio and one message bus, so exposure is answerable across
venues and an Actor sees every venue's data in one place. A node per venue
would put each one's positions out of the other's sight, and
`risk/exposure.py` exists because what is at risk is a question about an
account rather than about a ticket.

**It does not make this desk's rules venue-agnostic**, and that is worth
saying plainly rather than discovering later:

* `strategies/config.py`'s `INSTRUMENTS` is a broker-symbol table built for
  MT5 feeds, and a slug that resolves on one venue resolves to nothing on
  another.
* **The spread column is in points, not price**, which is an MT5 convention -
  reading it as price once made EURUSD look like a 476% round trip. A venue
  that reports spread differently needs its own conversion or costs come out
  wrong by orders of magnitude, and cost is what ends most ideas here.
* The magic number is an MT5 concept. It survives as one number the bridge
  stamps to tell this desk's orders from a human's, and means nothing
  elsewhere; attribution is `strategy_id`, which is the framework's.
* Credentials come from each adapter's **own** environment variables, because
  that is how Nautilus's adapters read them - `BINANCE_API_KEY` and
  `BINANCE_API_SECRET` for Binance, and so on. Only MT5's config is built
  from this desk's variables, since MT5's adapter is ours.

So the plumbing is venue-agnostic and some of the policy above it is not.
A second venue trades correctly once its symbols, its costs and its sizing
have been checked on that venue - not merely once it connects.
"""

from __future__ import annotations

import importlib
from typing import Any

#: The venue this desk was built for, and the only one whose adapter is ours.
MT5 = "mt5"


def kind(venue: str) -> str:
    """Which adapter serves a venue. `TRADING_VENUE_KIND_<VENUE>`, else the
    venue's own name.

    The two are usually the same - a venue called `BINANCE` is served by the
    `binance` adapter - and the override exists for the case that made this
    whole module necessary: two MT5 accounts under different venue names, both
    served by `mt5`. `TRADING_VENUE_KIND_DERIV=mt5` says so.
    """
    import os

    override = os.environ.get(f"TRADING_VENUE_KIND_{venue.upper()}")
    return (override or venue).strip().lower()


def factories(name: str) -> tuple[Any, Any]:
    """The data and execution client factories for one adapter kind.

    Found by the shape of the names rather than by a table, so every adapter
    Nautilus ships works and a new one needs nothing here. A kind that does
    not resolve raises with the list of what does - rather than falling back
    to MT5, which would connect to the wrong venue and look like it worked.
    """
    if name == MT5:
        from till_infinity.adapters.mt5 import (
            MT5LiveDataClientFactory,
            MT5LiveExecClientFactory,
        )

        return MT5LiveDataClientFactory, MT5LiveExecClientFactory

    module = _adapter(name)
    data = _one(module, "LiveDataClientFactory", name)
    orders = _one(module, "LiveExecClientFactory", name)
    return data, orders


def configs(name: str, venue: str) -> tuple[Any, Any]:
    """The data and execution client configs for one venue.

    MT5's are built from this desk's own variables, because MT5's adapter is
    ours. Every other adapter's config is **default-constructed**, which is
    not laziness: Nautilus's adapters read their own credentials from their
    own environment variables at connect time, so a default config is the
    documented way to use them and inventing our own variable names for them
    would be a second place for a credential to be wrong.
    """
    if name == MT5:
        from till_infinity.node import live

        return live.data_config(venue), live.exec_config(venue)

    module = _adapter(name)
    data = _one(module, "DataClientConfig", name, exclude="Live")
    orders = _one(module, "ExecClientConfig", name, exclude="Live")
    return (
        data(**_account(data, venue), **_venue_field(data, venue)),
        orders(**_account(orders, venue), **_venue_field(orders, venue)),
    )


#: Per-venue settings that may be pushed onto a third-party adapter's config,
#: by the field name the adapter uses.
#:
#: **This is what makes two accounts on one broker possible.** Nautilus's
#: adapters read their credentials from one global pair per broker -
#: `BINANCE_API_KEY` and `BINANCE_API_SECRET` - so two venues both served by
#: `binance` would share one account however they were named, and the second
#: would quietly trade the first's book. `TRADING_BINANCE_A_API_KEY` names one
#: of them instead.
#:
#: Only fields the adapter actually declares are set, so this is safe across
#: adapters that spell their credentials differently or do not have them: a
#: venue on `databento` has no `api_secret` and nothing is passed.
ACCOUNT: tuple[str, ...] = ("api_key", "api_secret", "api_passphrase", "account_type")


def _venue_field(config: Any, venue: str) -> dict[str, Any]:
    """`venue=...` where the adapter declares it, which is what makes **two
    accounts on one broker** possible.

    Nautilus allows exactly one execution client per `Venue` - a second is
    refused with `Execution client for venue Venue('BINANCE') already
    registered` - and that is a principled constraint rather than an
    oversight: a venue is what decides where an instrument trades, so two
    clients on one venue would make the routing of
    `ETHUSDT-PERP.BINANCE` ambiguous.

    The way through is to make the two accounts two *venues*, and some
    adapters allow exactly that: `BinanceDataClientConfig` and
    `BinanceExecClientConfig` both declare `venue`, so `BINANCE_A` and
    `BINANCE_B` are two venues served by one adapter with two keys.
    **`BybitExecClientConfig` does not**, so Bybit is one account per node
    until it does - and that is a limit to state rather than to work around,
    because the alternative is a second node and a second cache, which puts
    each account's positions out of the other's sight.
    """
    fields = set(getattr(config, "__struct_fields__", ()) or getattr(config, "model_fields", {}))
    if "venue" not in fields:
        return {}
    from nautilus_trader.model.identifiers import Venue

    return {"venue": Venue(venue.upper())}


def _account(config: Any, venue: str) -> dict[str, Any]:
    """Per-venue overrides for one adapter config class.

    Read from `TRADING_<VENUE>_<FIELD>`, upper-cased - so
    `TRADING_BINANCE_A_API_KEY` configures the venue named `BINANCE_A`. Absent,
    nothing is passed and the adapter reads its own global environment
    variable, which is the documented single-account arrangement and what
    every existing deploy does.
    """
    import os

    fields = set(getattr(config, "__struct_fields__", ()) or getattr(config, "model_fields", {}))
    found: dict[str, Any] = {}
    for field in ACCOUNT:
        if field not in fields:
            continue
        value = os.environ.get(f"TRADING_{venue.upper()}_{field.upper()}")
        if value:
            found[field] = value
    return found


def _adapter(name: str) -> Any:
    try:
        return importlib.import_module(f"nautilus_trader.adapters.{name}")
    except ImportError as exc:
        raise ValueError(
            f"no adapter for venue kind {name!r}: {exc}. Available: "
            f"{', '.join(available())}. A venue kind that does not resolve is "
            f"a client that connects to nothing, so this refuses rather than "
            f"falling back to MT5 and trading on the wrong venue."
        ) from exc


def _one(module: Any, suffix: str, name: str, exclude: str | None = None) -> Any:
    """The single class in a module whose name ends in `suffix`.

    Ambiguity is an error rather than a first match: an adapter exporting two
    candidates means the convention this resolver relies on does not hold
    there, and picking one silently is how a node ends up with a spot client
    where a futures one was wanted.
    """
    found = [
        getattr(module, attr)
        for attr in dir(module)
        if attr.endswith(suffix) and not (exclude and exclude in attr)
    ]
    if len(found) != 1:
        raise ValueError(
            f"the {name!r} adapter exports {len(found)} names ending in "
            f"{suffix!r}, so it cannot be resolved by convention. Wire it "
            f"explicitly in `node/venues.py` instead of guessing."
        )
    return found[0]


def available() -> tuple[str, ...]:
    """Every adapter kind this install can serve, ours included.

    Read off the package rather than listed, so it cannot go stale against the
    version of `nautilus_trader` actually installed.
    """
    import pkgutil

    from nautilus_trader import adapters

    found = {
        module.name
        for module in pkgutil.iter_modules(adapters.__path__)
        if not module.name.startswith("_")
    }
    found.add(MT5)
    return tuple(sorted(found))
