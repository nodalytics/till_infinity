"""Which desks a node runs, and that the two nodes run the same ones.

The last of those is the point. Nearly every hard lesson on this desk is a
measurement that did not mean what it claimed - an edge with good fills and
-98%, a 0.6365 that was overlapping touches and became 0.5092, a directional
AUC of 0.79 that collapsed to 0.51 - and all of them are the same failure: the
thing that measured and the thing that traded were not the same thing. Two
functions building two sets of desks is that failure waiting to happen, so a
test asserts they name the same ones.
"""

from __future__ import annotations

import pytest

from till_infinity.node import desks


@pytest.fixture
def loop():
    """A fresh event loop, because `TradingNode` asks for one in `__init__`.

    `asyncio.get_event_loop()` raises once something earlier in the session has
    closed the loop, so these three tests passed alone and failed in the suite -
    which is the worse way round: a node that builds under `pytest tests/x.py`
    and not under `pytest` is a node whose buildability depends on what ran
    before it. Supplying one makes the dependency explicit instead.
    """
    import asyncio

    made = asyncio.new_event_loop()
    asyncio.set_event_loop(made)
    try:
        yield made
    finally:
        asyncio.set_event_loop(None)
        made.close()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """A known environment, so a developer's shell cannot change the answer."""
    for name in (
        "TRADING_SYMBOLS",
        "TRADING_ENTRIES",
        "TRADING_STRATEGIES",
        "TRADING_INTERVALS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD GBPUSD")


# ------------------------------------------------------------- the vocabulary


def test_the_defaults_are_the_simplest_venue_can_serve():
    """`edge` places at market and needs nothing beyond an order. A default
    that quietly needs a venue minimum or bars is one that fails on the
    narrowest venue."""
    assert desks.entries() == ("edge",)
    assert desks.rules() == ("statespace-surprise",)
    assert desks.intervals() == ("15m",)


def test_a_typo_in_the_entries_raises_rather_than_running_nothing():
    """A node that reports up and trades nothing is the failure three deploys
    already produced by a different route."""
    import os

    os.environ["TRADING_ENTRIES"] = "edge arival"
    try:
        with pytest.raises(ValueError, match="not a mechanism"):
            desks.entries()
    finally:
        del os.environ["TRADING_ENTRIES"]


def test_a_list_may_be_commas_or_spaces():
    import os

    os.environ["TRADING_ENTRIES"] = "edge, resting"
    try:
        assert desks.entries() == ("edge", "resting")
    finally:
        del os.environ["TRADING_ENTRIES"]


def test_an_unknown_interval_raises_with_what_it_knows():
    with pytest.raises(ValueError, match="not an interval"):
        desks.bar_type("EURUSD", "MT5", "7m")


def test_a_bar_type_is_external_because_the_venue_aggregates():
    """An `INTERNAL` type would have Nautilus build bars from ticks, and MT5's
    tick stream is *sampled* - those bars would not match the venue's own."""
    got = desks.bar_type("EURUSD", "MT5", "15m")
    assert str(got) == "EURUSD.MT5-15-MINUTE-LAST-EXTERNAL"
    assert "EXTERNAL" in str(got)


# ---------------------------------------------------------------- the desks


def test_one_desk_per_rule_entry_and_instrument(monkeypatch):
    monkeypatch.setenv("TRADING_ENTRIES", "edge resting")
    built, clipped = desks.build("MT5")
    assert len(built) == 4, "two symbols x one rule x two entries"
    assert not clipped
    assert {type(s).__name__ for s in built} == {"EdgeEntry", "RestingEntry"}


def test_every_desk_gets_a_distinct_tag(monkeypatch):
    """Left unset they are all `EdgeEntry-None` and share an order-id tag, so
    Nautilus generates colliding client order ids and the `strategy_id` that
    was the whole argument for the carve-up names several desks at once."""
    monkeypatch.setenv("TRADING_ENTRIES", "edge resting")
    built, _ = desks.build("MT5")
    tags = [s.order_id_tag for s in built]
    ids = [str(s.id) for s in built]
    assert len(set(tags)) == len(tags), tags
    assert len(set(ids)) == len(ids), ids
    assert "None" not in " ".join(ids)


def test_a_tag_is_stable_across_processes():
    """**`crc32`, not `hash`.** Python randomises `hash` of a `str` per
    process unless `PYTHONHASHSEED` is fixed - three runs gave 619, 480 and
    849 for the same rule. A tag derived from it changes on every restart,
    which orphans every open order: Nautilus matches an external order to a
    strategy by this tag.
    """
    import subprocess
    import sys

    script = (
        "import os;"
        "os.environ['TRADING_SYMBOLS']='EURUSD';"
        "from till_infinity.node import desks;"
        "print(desks.build('MT5')[0][0].order_id_tag)"
    )
    seen = {
        subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(3)
    }
    assert len(seen) == 1, f"the tag moved between processes: {seen}"


def test_the_set_is_bounded_by_the_machine(monkeypatch):
    monkeypatch.setenv("TRADING_SYMBOLS", " ".join(f"SYM{i}" for i in range(20)))
    built, clipped = desks.build("MT5", limit=5)
    assert len(built) == 5
    assert len(clipped) == 15


def test_what_was_clipped_is_returned_and_not_swallowed(monkeypatch):
    """A set silently smaller than the one asked for is the shape of bug this
    desk has paid for repeatedly: a min-events guard once dropped 141 of 146
    feeds and made 0.9 sigma look like 4.8."""
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD GBPUSD USDJPY")
    built, clipped = desks.build("MT5", limit=1)
    assert len(built) == 1
    assert clipped == ["statespace-surprise/edge/GBPUSD", "statespace-surprise/edge/USDJPY"]


def test_the_ceiling_never_reaches_zero():
    """A live node with no strategies connects, reconciles, reports healthy and
    trades nothing."""
    assert desks.ceiling() >= 1


def test_no_symbols_builds_nothing_rather_than_guessing(monkeypatch):
    monkeypatch.delenv("TRADING_SYMBOLS", raising=False)
    built, clipped = desks.build("MT5")
    assert built == []
    assert clipped == []


# ------------------------------------------------- live and backtest agree


def test_the_live_and_backtest_sets_name_the_same_desks(monkeypatch):
    """The test this module exists for.

    `BacktestRunConfig` is serialisable and holds a path and a config dict,
    where a live node takes an instance - two shapes, and building them from
    two pieces of code is how a backtest comes to measure a desk that is not
    the one deployed.
    """
    monkeypatch.setenv("TRADING_ENTRIES", "edge resting arrival")
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD GBPUSD USDJPY")
    live, live_clipped = desks.build("MT5")
    back, back_clipped = desks.importable("MT5")

    assert len(live) == len(back) == 9
    assert live_clipped == back_clipped
    assert [s.order_id_tag for s in live] == [c.config["order_id_tag"] for c in back]
    assert [type(s).__name__ for s in live] == [c.strategy_path.rsplit(":", 1)[1] for c in back]
    assert [str(s.config.instrument_id) for s in live] == [c.config["instrument_id"] for c in back]
    assert [str(s.config.bar_type) for s in live] == [c.config["bar_type"] for c in back]


def test_the_importable_paths_resolve_to_the_real_classes(monkeypatch):
    """A path that does not import is a backtest that fails at run time, which
    is the one place a typo is most expensive."""
    import importlib

    monkeypatch.setenv("TRADING_ENTRIES", "edge resting arrival")
    back, _ = desks.importable("MT5")
    for config in back:
        module, name = config.strategy_path.split(":")
        assert hasattr(importlib.import_module(module), name), config.strategy_path
        module, name = config.config_path.split(":")
        assert hasattr(importlib.import_module(module), name), config.config_path

    for actor in desks.importable_actors("MT5"):
        module, name = actor.actor_path.split(":")
        assert hasattr(importlib.import_module(module), name)


def test_the_basket_is_an_actor_rather_than_a_desk():
    """Its whole subject is other strategies' positions."""
    found = desks.actors("MT5")
    assert [type(a).__name__ for a in found] == ["BasketExit"]


# ----------------------------------------------------------- the nodes build


def test_the_live_node_builds_with_its_desks_on_it(monkeypatch, loop):
    """**This could never have been built before.**

    `live.settings` used `RiskEngineConfig`, and the kernel raises
    `Cannot use RiskEngineConfig in a 'live' environment` from its
    constructor - so the node was unbuildable and nothing caught it, because
    nothing constructed one. The same shape as the three deploys that were
    built, tagged, health-checked and ran none of the code they claimed: every
    check read our own side of the wire.
    """
    monkeypatch.setenv("TRADING_ENTRIES", "edge resting")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    monkeypatch.setenv("STATESPACE_BARS", "EURUSD.MT5-15-MINUTE-LAST-EXTERNAL")

    from till_infinity.node import live

    node = live.build()
    try:
        assert len(node.trader.strategies()) == 4
        # `BasketExit-MT5` and not `BasketExit`: the id carries the venue
        # because Nautilus requires actor ids to be unique in a trader, and
        # two venues both adding a bare `BasketExit` is refused.
        #
        # `JournalActor` and `Notifier` are here because they are **on by
        # default**: both existed and neither was ever registered, so every
        # refusal reason went to a debug log and every alert to nothing.
        assert {str(a.id) for a in node.trader.actors()} == {
            "BasketExit-MT5",
            "JournalActor",
            "Notifier",
            "StatespaceActor",
        }
    finally:
        node.dispose()


def test_a_live_node_with_no_desks_refuses_to_build(monkeypatch, loop):
    """It would connect, reconcile, report healthy and trade nothing."""
    monkeypatch.delenv("TRADING_SYMBOLS", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    from till_infinity.node import live

    with pytest.raises(ValueError, match="no desks to run"):
        live.build()


def test_statespace_is_only_added_when_it_is_configured(monkeypatch, loop):
    """An actor subscribed to nothing is a fold that never runs pretending to
    be a model that does.

    **Statespace is opt-in and the record is opt-out**, which is the opposite
    way round and deliberate: a node that trades without a record is the state
    this desk was in since the port, and an opt-in record is a record nobody
    turns on. So the journal and the notifier are present here and statespace
    is not.
    """
    monkeypatch.delenv("STATESPACE_BARS", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    from till_infinity.node import live

    node = live.build()
    try:
        assert {str(a.id) for a in node.trader.actors()} == {
            "BasketExit-MT5",
            "JournalActor",
            "Notifier",
        }
    finally:
        node.dispose()


def test_the_record_can_be_switched_off_by_name(monkeypatch, loop):
    """Off by name rather than on by name. A deploy that genuinely wants no
    record says so, and the failure of forgetting is then a loud duplicate
    rather than a silent absence."""
    monkeypatch.delenv("STATESPACE_BARS", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    monkeypatch.setenv("JOURNAL_OFF", "1")
    monkeypatch.setenv("ALERTS_OFF", "1")

    from till_infinity.node import live

    node = live.build()
    try:
        assert [str(a.id) for a in node.trader.actors()] == ["BasketExit-MT5"]
    finally:
        node.dispose()


def test_the_backtest_venue_is_the_instruments_own(monkeypatch):
    """It was fixed at MT5 while the desks were built from the instrument's
    venue, so a backtest on `EURUSD.SIM` got a venue called MT5 and the
    instrument would never have resolved."""
    from till_infinity.node import backtest

    for instrument in ("EURUSD.SIM", "EURUSD.MT5"):
        monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD")
        config = backtest.desk_config(instrument)
        assert config.venues[0].name == instrument.rsplit(".", 1)[-1]
        assert config.engine.strategies[0].config["instrument_id"] == instrument


def test_a_backtest_with_no_desks_refuses_rather_than_reporting_nothing(monkeypatch):
    """A result computed from no trades is still a result, which is the
    problem."""
    monkeypatch.delenv("TRADING_SYMBOLS", raising=False)

    from till_infinity.node import backtest

    with pytest.raises(ValueError, match="no desks"):
        backtest.desk_config("EURUSD.SIM")


# --------------------------------------------------- the one gate that costs money


@pytest.mark.parametrize("unset", ["", "0", "false", "no"])
def test_a_node_that_is_not_armed_denies_every_order(monkeypatch, loop, unset):
    """**`TRADING_LIVE` or no orders**, and the regression that put it here.

    `TRADING_LIVE` has always been the desk's arming switch: the retired
    `service.py` chose a paper book without it. When that path retired on
    2026-11-01 the switch went with it, and this node registered the MT5
    execution client unconditionally - so a host with `TRADING_SYMBOLS` set
    and `TRADING_LIVE` unset would have sent **real orders** where the same
    environment used to paper-trade. Nothing failed; a control was simply
    gone, which is why the test is per state rather than per line.

    Driven through `_execute_command` rather than `execute` on purpose:
    `LiveRiskEngine.execute` enqueues onto a loop that is not running here,
    and `_execute_command` is the handler that queue drains into - the same
    path, minus the wait.
    """
    from nautilus_trader.common.component import TestClock
    from nautilus_trader.common.factories import OrderFactory
    from nautilus_trader.core.uuid import UUID4
    from nautilus_trader.execution.messages import SubmitOrderList
    from nautilus_trader.model.enums import OrderSide, TradingState
    from nautilus_trader.model.identifiers import StrategyId, TraderId
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    if unset:
        monkeypatch.setenv("TRADING_LIVE", unset)
    else:
        monkeypatch.delenv("TRADING_LIVE", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    from till_infinity.node import live

    node = live.build()
    try:
        assert node.kernel.risk_engine.trading_state == TradingState.HALTED

        venue = node.trader.strategies()[0].config.instrument_id.venue
        eurusd = TestInstrumentProvider.default_fx_ccy("EUR/USD", venue)
        node.kernel.cache.add_instrument(eurusd)
        factory = OrderFactory(
            trader_id=TraderId("TILL-001"),
            strategy_id=StrategyId("S-1"),
            clock=TestClock(),
        )
        bracket = factory.bracket(
            instrument_id=eurusd.id,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(1_000),
            sl_trigger_price=Price.from_str("1.0900"),
            tp_price=Price.from_str("1.1100"),
        )

        # The denial is an `OrderDenied` sent to `ExecEngine.process`, so the
        # assertion reads the events rather than the orders: the live exec
        # engine queues them, and a status still `INITIALIZED` means the
        # event has not been applied yet, not that nothing was denied.
        seen: list[object] = []
        bus = node.kernel.msgbus
        bus.deregister(endpoint="ExecEngine.process", handler=node.kernel.exec_engine.process)
        bus.register(endpoint="ExecEngine.process", handler=seen.append)

        node.kernel.risk_engine._execute_command(
            SubmitOrderList(
                trader_id=TraderId("TILL-001"),
                strategy_id=StrategyId("S-1"),
                order_list=bracket,
                command_id=UUID4(),
                ts_init=0,
            )
        )

        # Every leg, not just the entry: a bracket whose stop was denied and
        # whose entry was not is worse than no order at all.
        assert len(seen) == len(bracket.orders) == 3
        assert {type(event).__name__ for event in seen} == {"OrderDenied"}
        assert {event.reason for event in seen} == {"TradingState.HALTED"}
    finally:
        node.dispose()


def test_trading_live_arms_the_node(monkeypatch, loop):
    """The other half, because a gate that is always closed is not a gate."""
    from nautilus_trader.model.enums import TradingState

    monkeypatch.setenv("TRADING_LIVE", "1")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    from till_infinity.node import live

    node = live.build()
    try:
        assert node.kernel.risk_engine.trading_state == TradingState.ACTIVE
    finally:
        node.dispose()


# --------------------------------------------- symbols whose names have spaces


def test_a_synthetic_name_is_one_symbol_and_not_three(monkeypatch):
    """**Deriv's synthetics all have spaces in their names**, and the splitter
    used to treat a space and a comma alike - so `Volatility 75 Index` became
    the three symbols `Volatility`, `75` and `Index`.

    Nothing raised: `Symbol("75")` is valid and the instrument simply never
    resolves, so the node came up, registered three desks and traded none of
    them. That is the same failure shape as the three deploys on 2026-10-09
    which were health-checked and ran none of the code they claimed.
    """
    monkeypatch.setenv("TRADING_SYMBOLS", "Volatility 75 Index,Boom 1000 Index")
    assert desks.symbols() == ("Volatility 75 Index", "Boom 1000 Index")


def test_one_spaced_name_needs_a_trailing_comma(monkeypatch):
    """Which is what a hand-edited env file tends to look like anyway, and the
    only unambiguous way to say "this is one name"."""
    monkeypatch.setenv("TRADING_SYMBOLS", "Volatility 75 Index,")
    assert desks.symbols() == ("Volatility 75 Index",)


def test_space_separated_names_still_work(monkeypatch):
    """Every existing deploy and test writes `EURUSD GBPUSD`, so commas only
    take over when there is a comma."""
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD GBPUSD")
    assert desks.symbols() == ("EURUSD", "GBPUSD")


def test_a_torn_name_refuses_rather_than_quoting_a_number(monkeypatch):
    """No broker lists a symbol called `75`, so a bare number among the parts
    is evidence a name was torn apart. A clear error costs a deploy a restart;
    the silent version cost three desks on instruments that do not exist."""
    monkeypatch.setenv("TRADING_SYMBOLS", "Volatility 75 Index")
    with pytest.raises(ValueError, match="torn apart"):
        desks.symbols()


def test_a_desk_builds_for_a_synthetic(monkeypatch, loop):
    """End to end, because the name survives `Symbol`, `InstrumentId` and
    `BarType` individually and the question is whether it survives all three
    plus the strategy id."""
    monkeypatch.setenv("TRADING_SYMBOLS", "Volatility 75 Index,")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    built, clipped = desks.build("MT5")
    assert not clipped
    assert len(built) == 1
    config = built[0].config
    assert config.instrument_id.symbol.value == "Volatility 75 Index"
    # The bar type is the one the data client subscribes with, and a name that
    # round-trips through `BarType.from_str` is the whole requirement.
    assert str(config.bar_type).startswith("Volatility 75 Index.MT5-")


def test_two_synthetics_get_different_strategy_ids(monkeypatch, loop):
    """`strategy_id` is what Nautilus carries on every order, fill and
    position, so a collision would relabel one synthetic as the other - the
    magic-number bug the whole carve-up was done to make impossible.

    Read off `strategy.id` and not `config.strategy_id`, which is `None`:
    the id is assigned by the framework from the class and the
    `order_id_tag`, and asserting on the config field would pass for any two
    desks at all.
    """
    monkeypatch.setenv("TRADING_SYMBOLS", "Volatility 75 Index,Volatility 100 Index")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    built, _ = desks.build("MT5")
    assert len(built) == 2
    ids = {str(strategy.id) for strategy in built}
    assert ids == {
        "EdgeEntry-Volatility 75 Index-E270",
        "EdgeEntry-Volatility 100 Index-E270",
    }
    # The tag suffix is per-entry, so the symbol is what distinguishes these.
    # Both halves matter: a tag-only id would collide across symbols, and a
    # symbol-only id would collide across entries on one symbol.
    tags = {strategy.config.order_id_tag for strategy in built}
    assert len(tags) == 2
