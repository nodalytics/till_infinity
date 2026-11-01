"""Which adapter a venue gets, and that a node can hold more than one.

`live.py` registered `MT5LiveDataClientFactory` for every venue it built, so
"multi-venue" meant "several MT5 accounts" - a real arrangement, and not the
question anybody is asking when they say multi-venue. These tests pin the
resolver that fixed it and the two-venue node it makes possible.

The resolver finds an adapter's four classes **by the shape of their names**
rather than from a table, so the test that matters most is the one asserting
that shape still holds for adapters nobody here has used: a convention is only
worth relying on while it is true, and `nautilus_trader` is free to change it.
"""

from __future__ import annotations

import asyncio

import pytest

from till_infinity.node import desks, venues


@pytest.fixture
def loop():
    """A fresh event loop, because `TradingNode` asks for one in `__init__`.

    Without it these pass alone and fail in the suite, which is the worse way
    round: a node whose buildability depends on what ran before it.
    """
    made = asyncio.new_event_loop()
    asyncio.set_event_loop(made)
    try:
        yield made
    finally:
        asyncio.set_event_loop(None)
        made.close()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in (
        "TRADING_VENUES",
        "TRADING_SYMBOLS",
        "TRADING_SYMBOLS_MT5",
        "TRADING_SYMBOLS_DERIV",
        "TRADING_SYMBOLS_BINANCE",
        "TRADING_VENUE_KIND_DERIV",
        "TRADING_ENTRIES",
        "TRADING_LIVE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOG_LEVEL", "ERROR")


# ------------------------------------------------------------- what resolves


def test_the_default_venue_is_the_one_whose_adapter_is_ours():
    """A single-venue deploy names nothing and gets MT5, which is what every
    existing one does."""
    assert desks.venues() == ("MT5",)
    assert venues.kind("MT5") == "mt5"


def test_every_adapter_this_install_ships_is_available():
    """Read off the package rather than listed, so the answer cannot go stale
    against the installed version of `nautilus_trader`."""
    found = venues.available()
    for expected in ("binance", "bybit", "kraken", "interactive_brokers", "mt5"):
        assert expected in found, f"{expected} missing from {found}"


@pytest.mark.parametrize("name", ["binance", "bybit", "kraken", "okx", "deribit"])
def test_a_shipped_adapter_resolves_by_convention(name):
    """**The convention this whole resolver rests on.** Each adapter exports
    exactly one `*LiveDataClientFactory` and one `*LiveExecClientFactory`, so
    adding a venue is a value in `TRADING_VENUES` rather than a code change.

    If `nautilus_trader` ever breaks that naming, this fails here rather than
    at a deploy - which is the only reason to test somebody else's package.
    """
    data, orders = venues.factories(name)
    assert data.__name__.endswith("LiveDataClientFactory")
    assert orders.__name__.endswith("LiveExecClientFactory")
    assert hasattr(data, "create")
    assert hasattr(orders, "create")


def test_our_own_adapter_resolves_too():
    data, orders = venues.factories("mt5")
    assert data.__name__ == "MT5LiveDataClientFactory"
    assert orders.__name__ == "MT5LiveExecClientFactory"


def test_an_unknown_venue_refuses_rather_than_falling_back():
    """Falling back to MT5 would connect to the wrong venue and look like it
    worked, which is strictly worse than not starting."""
    with pytest.raises(ValueError, match="no adapter for venue kind"):
        venues.factories("ftx")


def test_the_refusal_says_what_is_available():
    """A deploy that mistypes a venue should not have to read this file."""
    with pytest.raises(ValueError, match="no adapter for venue kind") as raised:
        venues.factories("coinbase-pro")
    assert "binance" in str(raised.value)


def test_a_venue_can_be_served_by_another_kind(monkeypatch):
    """The case that made this module necessary: two MT5 accounts under two
    venue names - a demo beside a live one - both served by `mt5`."""
    monkeypatch.setenv("TRADING_VENUE_KIND_DERIV", "mt5")
    assert venues.kind("DERIV") == "mt5"
    assert venues.kind("BINANCE") == "binance", "and an unmapped venue is its own kind"


# -------------------------------------------------------- per-venue symbols


def test_each_venue_can_carry_its_own_symbols(monkeypatch):
    """Two venues rarely list the same things: a Deriv account carries the
    synthetics and an ECN account carries the FX crosses. A shared list would
    have each node asking its venue for instruments it does not have."""
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD")
    monkeypatch.setenv("TRADING_SYMBOLS_DERIV", "Volatility 75 Index,")
    assert desks.symbols("MT5") == ("EURUSD",), "falls back to the shared list"
    assert desks.symbols("DERIV") == ("Volatility 75 Index",)


def test_the_shared_list_still_applies_where_nothing_overrides(monkeypatch):
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD,GBPUSD")
    assert desks.symbols("ANYTHING") == ("EURUSD", "GBPUSD")
    assert desks.symbols() == ("EURUSD", "GBPUSD")


# ---------------------------------------------------------- the ceiling, once


def test_the_ceiling_is_shared_across_venues(monkeypatch):
    """**It is a property of the machine, not of a venue.** Built per venue it
    multiplies: two venues at `PER_CORE` x cores each is twice the fold on the
    same cores, and `tis-research-jobs-starve-the-service` is what that
    costs - a node that cannot keep up has late quotes, and a late quote is
    the one input every gate trusts."""
    monkeypatch.setenv("TRADING_VENUES", "MT5,DERIV")
    monkeypatch.setenv("TRADING_VENUE_KIND_DERIV", "mt5")
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD,GBPUSD,XAUUSD")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")

    built, clipped = desks.build_all()
    assert len(built) + len(clipped) == 6, "three symbols on each of two venues"
    assert len(built) <= desks.ceiling()


def test_a_clip_says_which_venue_it_happened_on(monkeypatch):
    """A set silently smaller than the one asked for is the shape of bug this
    desk has paid for repeatedly - a min-events guard once dropped 141 of 146
    feeds and made 0.9 sigma look like 4.8 - so the venue travels with the
    name."""
    monkeypatch.setenv("TRADING_VENUES", "MT5,DERIV")
    monkeypatch.setenv("TRADING_VENUE_KIND_DERIV", "mt5")
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD,GBPUSD")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")

    budget = _budget(cores=0)
    built, clipped = desks.build_all(budget=budget)
    assert built, "it floors at one: a live node with no strategies trades nothing"
    assert clipped, "and the rest are reported"
    assert all(name.split(":")[0] in ("MT5", "DERIV") for name in clipped)


def test_the_ceiling_accepts_a_budget_at_all():
    """`ceiling(budget)` read `.cores` off a `Budget` that has no such field,
    so it raised `AttributeError` - and nothing had ever passed one, so the
    branch was dead until `build_all` needed to spend a single budget across
    several venues."""
    assert desks.ceiling(_budget(cores=4)) == 4 * desks.PER_CORE


def _budget(cores: int):
    from till_infinity.node import sizing

    measured = sizing.measure()
    return type(measured)(
        workers=measured.workers,
        concurrent=measured.concurrent,
        windows=measured.windows,
        cores_seen=cores,
        memory_mb=measured.memory_mb,
        why="a test",
    )


# ------------------------------------------------------------- the whole node


def test_one_node_holds_two_venues(monkeypatch, loop):
    """**One kernel, not two nodes.** One cache, one portfolio and one message
    bus, so exposure is answerable across venues and an Actor sees both
    feeds. A node per venue would put each one's positions out of the other's
    sight, which is what `risk/exposure.py` exists to answer."""
    monkeypatch.setenv("TRADING_VENUES", "MT5,DERIV")
    monkeypatch.setenv("TRADING_VENUE_KIND_DERIV", "mt5")
    monkeypatch.setenv("TRADING_SYMBOLS_MT5", "EURUSD")
    monkeypatch.setenv("TRADING_SYMBOLS_DERIV", "Volatility 75 Index,")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")

    from till_infinity.node import live

    node = live.build()
    try:
        data = {str(client) for client in node.kernel.data_engine.registered_clients}
        orders = {str(client) for client in node.kernel.exec_engine.registered_clients}
        assert data == orders == {"MT5", "DERIV"}
        held = {str(strategy.config.instrument_id) for strategy in node.trader.strategies()}
        assert held == {"EURUSD.MT5", "Volatility 75 Index.DERIV"}
    finally:
        node.dispose()


def test_each_venue_gets_its_own_basket_actor(monkeypatch, loop):
    """Nautilus requires actor ids to be unique in a trader, so two venues
    both adding a `BasketExit` raised `Already registered an actor with ID
    BasketExit`. Found by building a two-venue node rather than by reading,
    which is the argument for building one."""
    monkeypatch.setenv("TRADING_VENUES", "MT5,DERIV")
    monkeypatch.setenv("TRADING_VENUE_KIND_DERIV", "mt5")
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")

    from till_infinity.node import live

    node = live.build()
    try:
        actors = {str(actor.id) for actor in node.trader.actors()}
        # The basket watcher is per venue; the journal and the notifier are
        # one each for the node, because a record is not a venue's concern.
        assert {name for name in actors if name.startswith("BasketExit")} == {
            "BasketExit-MT5",
            "BasketExit-DERIV",
        }
        assert {"JournalActor", "Notifier"} <= actors
    finally:
        node.dispose()


def test_the_clients_and_the_factories_name_the_same_venues(monkeypatch, loop):
    """`settings()` registers the clients and `build()` registers the
    factories. Named from two places they could disagree, and the failure
    reads as a missing factory rather than as a mismatched list."""
    monkeypatch.setenv("TRADING_VENUES", "MT5,DERIV")
    monkeypatch.setenv("TRADING_VENUE_KIND_DERIV", "mt5")
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")

    from till_infinity.node import live

    configured = set(live.settings().data_clients)
    node = live.build()
    try:
        registered = {str(client) for client in node.kernel.data_engine.registered_clients}
        assert configured == registered
    finally:
        node.dispose()


# ------------------------------------------- a venue that is not another MT5


@pytest.mark.parametrize(
    ("venue", "kind", "symbol", "keys"),
    [
        ("BINANCE", "binance", "ETHUSDT-PERP", "BINANCE"),
        ("BYBIT", "bybit", "ETHUSDT-LINEAR", "BYBIT"),
    ],
)
def test_a_real_second_broker_builds_beside_mt5(monkeypatch, loop, venue, kind, symbol, keys):
    """**The question this module exists to answer.** Before it, every venue
    got `MT5LiveDataClientFactory`, so a venue called BINANCE would have been
    served by the MT5 adapter and connected to an MT5 bridge - which looks
    like a configuration that works right up to the first order.

    Parametrised over two brokers rather than one, because one would prove the
    name `binance` had been wired rather than that the convention holds.

    The credentials are obvious placeholders: each adapter reads its own
    environment variables at **build** time, so a config needs them present to
    construct, and nothing here connects. The node is built and disposed.
    """
    monkeypatch.setenv("TRADING_VENUES", f"MT5,{venue}")
    monkeypatch.setenv("TRADING_SYMBOLS_MT5", "EURUSD")
    monkeypatch.setenv(f"TRADING_SYMBOLS_{venue}", symbol)
    monkeypatch.setenv("TRADING_ENTRIES", "edge")
    for name in (f"{keys}_API_KEY", f"{keys}_TESTNET_API_KEY"):
        monkeypatch.setenv(name, "placeholder-not-a-real-key")
    for name in (f"{keys}_API_SECRET", f"{keys}_TESTNET_API_SECRET"):
        monkeypatch.setenv(name, "placeholder-not-a-real-secret")

    from till_infinity.node import live

    node = live.build()
    try:
        data = {str(client) for client in node.kernel.data_engine.registered_clients}
        orders = {str(client) for client in node.kernel.exec_engine.registered_clients}
        assert data == orders == {"MT5", venue}
        # One kernel, so both venues' desks are in one trader with one cache -
        # which is what makes exposure across venues answerable at all.
        held = {str(strategy.config.instrument_id) for strategy in node.trader.strategies()}
        assert held == {"EURUSD.MT5", f"{symbol}.{venue}"}
    finally:
        node.dispose()


def test_one_symbol_on_two_venues_is_two_strategy_ids(monkeypatch, loop):
    """`EURUSD` on two venues is two desks, and the tag named only the symbol -
    so Nautilus refused the second with `Already registered a strategy with ID
    EdgeEntry-EURUSD-E270`. The venue is appended **only** when there is more
    than one, because changing every existing single-venue tag would stop
    Nautilus recognising its own open orders on the next restart."""
    monkeypatch.setenv("TRADING_VENUES", "MT5,DERIV")
    monkeypatch.setenv("TRADING_VENUE_KIND_DERIV", "mt5")
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")

    built, _ = desks.build_all()
    assert {str(strategy.id) for strategy in built} == {
        "EdgeEntry-EURUSD-E270-MT5",
        "EdgeEntry-EURUSD-E270-DERIV",
    }


def test_a_single_venue_tag_is_unchanged(monkeypatch):
    """The other half of that asymmetry, and the reason for it: a tag that
    changed between runs would orphan every open order, which is the failure
    `_tag`'s own docstring was written to prevent."""
    monkeypatch.setenv("TRADING_VENUES", "MT5")
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")

    built, _ = desks.build_all()
    assert [str(strategy.id) for strategy in built] == ["EdgeEntry-EURUSD-E270"]


# ------------------------------------------------ two accounts on one broker


def test_two_accounts_on_one_broker_are_two_venues(monkeypatch, loop):
    """**Nautilus allows one execution client per `Venue`**, and refuses a
    second with `Execution client for venue Venue('BINANCE') already
    registered`. That is principled rather than an oversight: a venue decides
    where an instrument trades, so two clients on one venue would make routing
    `ETHUSDT-PERP.BINANCE` ambiguous.

    The way through is for the two accounts to be two venues, which works
    because `BinanceDataClientConfig` and `BinanceExecClientConfig` both
    declare a `venue` field. Each then carries its own key, because the
    adapters otherwise read one global `BINANCE_API_KEY` per broker and the
    second account would quietly trade the first's book.
    """
    monkeypatch.setenv("TRADING_VENUES", "BINANCE_A,BINANCE_B")
    for suffix in ("A", "B"):
        monkeypatch.setenv(f"TRADING_VENUE_KIND_BINANCE_{suffix}", "binance")
        monkeypatch.setenv(f"TRADING_BINANCE_{suffix}_API_KEY", f"placeholder-key-{suffix}")
        monkeypatch.setenv(f"TRADING_BINANCE_{suffix}_API_SECRET", f"placeholder-secret-{suffix}")
    monkeypatch.setenv("TRADING_SYMBOLS_BINANCE_A", "ETHUSDT-PERP")
    monkeypatch.setenv("TRADING_SYMBOLS_BINANCE_B", "BTCUSDT-PERP")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")

    first = venues.configs("binance", "BINANCE_A")[1]
    second = venues.configs("binance", "BINANCE_B")[1]
    assert first.api_key != second.api_key, "two accounts, two keys"
    assert str(first.venue) == "BINANCE_A"
    assert str(second.venue) == "BINANCE_B"

    from till_infinity.node import live

    node = live.build()
    try:
        clients = {str(client) for client in node.kernel.exec_engine.registered_clients}
        assert clients == {"BINANCE_A", "BINANCE_B"}
        held = {str(strategy.config.instrument_id) for strategy in node.trader.strategies()}
        assert held == {"ETHUSDT-PERP.BINANCE_A", "BTCUSDT-PERP.BINANCE_B"}
    finally:
        node.dispose()


def test_two_mt5_accounts_are_two_venues(monkeypatch, loop):
    """The same thing for our own adapter, which is the case that comes up
    first: a demo account beside a live one, or two brokers both on MT5."""
    monkeypatch.setenv("TRADING_VENUES", "MT5,DERIV")
    monkeypatch.setenv("TRADING_VENUE_KIND_DERIV", "mt5")
    monkeypatch.setenv("TRADING_MT5_URL", "http://localhost:8000")
    monkeypatch.setenv("TRADING_MT5_URL_DERIV", "http://localhost:8100")
    monkeypatch.setenv("TRADING_SYMBOLS_MT5", "EURUSD")
    monkeypatch.setenv("TRADING_SYMBOLS_DERIV", "Volatility 75 Index,")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")

    from till_infinity.node import live

    # Each account is a different bridge, which is the point: one terminal is
    # one account, and two accounts are two terminals.
    assert live.data_config("MT5").base_url.endswith(":8000")
    assert live.data_config("DERIV").base_url.endswith(":8100")

    node = live.build()
    try:
        clients = {str(client) for client in node.kernel.exec_engine.registered_clients}
        assert clients == {"MT5", "DERIV"}
    finally:
        node.dispose()


def test_an_adapter_without_a_venue_field_is_one_account_per_node():
    """**A limit worth asserting rather than working around.**
    `BybitExecClientConfig` declares no `venue`, so two Bybit accounts cannot
    be two venues in one node - and the alternative, a second node, puts each
    account's positions out of the other's sight, which is the thing one
    kernel exists to avoid.

    This fails if Nautilus adds the field, which is the point: the limitation
    should stop being reported the moment it stops being true.
    """
    from nautilus_trader.adapters.bybit import BybitExecClientConfig

    fields = set(BybitExecClientConfig.__struct_fields__)
    assert "venue" not in fields, "Bybit gained a venue field - multi-account now works"
    assert "api_key" in fields, "and its credentials are still per-config"
