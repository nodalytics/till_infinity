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
    assert {type(s).__name__ for s in built} == {"SurpriseEdge", "SurpriseResting"}


def test_what_is_built_can_actually_decide_and_exit(monkeypatch):
    """**The composed leaf, not the bare entry.**

    This built `EdgeEntry` itself, with no decision mixin in front of it, and
    `Desk.decide` raises by design - so every desk this node registered raised
    `NotImplementedError` on the first proposal it was handed, and nothing said
    so because a node that judges nothing looks exactly like a quiet market.
    The composed leaves existed and were tested; they were built by nothing.

    The same held on the exit side: without an `ExitMechanism` in the bases a
    position has no book tracking it, so no stop moves, nothing banks, no stale
    clock runs and the basket close - which is published, not submitted -
    reaches nobody.
    """
    from till_infinity.strategies.desk import Desk
    from till_infinity.strategies.exits import ExitMechanism

    monkeypatch.setenv("TRADING_ENTRIES", "edge resting arrival")
    built, _ = desks.build("MT5")
    assert built
    for strategy in built:
        name = type(strategy).__name__
        # `Desk.decide` is the one that raises, so inheriting it *is* the bug.
        assert type(strategy).decide is not Desk.decide, f"{name} has no decision"
        assert isinstance(strategy, ExitMechanism), f"{name} has no exit"
        assert strategy.label != name, f"{name} has no profile to name itself by"


def test_an_unknown_rule_raises_rather_than_running_nothing(monkeypatch):
    """A typo that silently runs nothing is a node that reports up and trades
    nothing, which is on record from three deploys that were built, tagged,
    health-checked and ran none of the code they claimed."""
    monkeypatch.setenv("TRADING_STRATEGIES", "statespace-surprize")
    with pytest.raises(ValueError, match=r"not a\s+decision rule"):
        desks.rules()


def test_the_exit_override_replaces_the_rule_s_own_everywhere(monkeypatch):
    """`TRADING_EXITS=venue` is for the deploy that cannot switch the bridge's
    own trailing handler off: `manage.py` says three things can move a stop and
    exactly one may, so a desk whose stop the bridge is already trailing must
    not also run `advance`."""
    from till_infinity.strategies.exits import ManagedExit, VenueExit

    monkeypatch.setenv("TRADING_ENTRIES", "edge")
    assert desks.exits() == "", "each rule keeps its own by default"
    assert all(isinstance(s, ManagedExit) for s in desks.build("MT5")[0])

    monkeypatch.setenv("TRADING_EXITS", "venue")
    assert desks.exits() == "venue"
    swapped = desks.build("MT5")[0]
    assert swapped
    for strategy in swapped:
        assert isinstance(strategy, VenueExit)
        assert not isinstance(strategy, ManagedExit)

    monkeypatch.setenv("TRADING_EXITS", "trailing")
    with pytest.raises(ValueError, match=r"not an exit mechanism|exactly one"):
        desks.exits()


def test_every_desk_gets_a_distinct_tag(monkeypatch):
    """Left unset they are all `SurpriseEdge-None` and share an order-id tag, so
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
    which orphans every open order - not because Nautilus reads the tag
    (`get_tag()` is used only to build order ids) but because the tag composes
    the `strategy_id` the cache indexes every order, fill and position by.
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


def test_the_importable_paths_build_what_a_backtest_would_build(monkeypatch):
    """A path that does not resolve is a backtest that fails at run time,
    which is the one place a typo is most expensive.

    Resolved through Nautilus's own factories rather than by hand. **These are
    the functions `BacktestNode` calls**, so they settle the whole question
    and not the importable half of it: the config dict has to satisfy the
    config class, and the strategy has to accept that config. A path can
    import and still not build - a required field left out of the dict is the
    common way - and `hasattr` on the resolved module, which is what used to
    stand here, cannot see any of it.
    """
    from nautilus_trader.common.actor import Actor
    from nautilus_trader.common.config import ActorFactory
    from nautilus_trader.trading.config import StrategyFactory
    from nautilus_trader.trading.strategy import Strategy

    monkeypatch.setenv("TRADING_ENTRIES", "edge resting arrival")
    back, _ = desks.importable("MT5")
    assert back, "nothing to resolve, so nothing was asserted"
    for config in back:
        made = StrategyFactory.create(config)
        assert isinstance(made, Strategy), config.strategy_path
        assert type(made).__name__ == config.strategy_path.rsplit(":", 1)[1]
        assert type(made.config).__name__ == config.config_path.rsplit(":", 1)[1]

    for actor in desks.importable_actors("MT5"):
        assert isinstance(ActorFactory.create(actor), Actor), actor.actor_path


def test_the_derived_name_is_the_id_nautilus_assigns(monkeypatch):
    """**The join between a measurement and a promotion.** `LadderActor`
    counts a candidate's episodes with `positions_closed(strategy_id=...)`, so
    a discovery run delivering under any other name delivers one the loop can
    never find a sample for - held for want of episodes while the strategy it
    names trades beside it.

    Asserted against each strategy's own `id`, built through the factory
    `BacktestNode` uses, rather than against the formula. The formula is
    Nautilus's and could change under us; a test that restated it would agree
    with `strategy_name` and with nothing else.
    """
    from nautilus_trader.trading.config import StrategyFactory

    monkeypatch.setenv("TRADING_ENTRIES", "edge resting arrival")
    back, _ = desks.importable("MT5")
    assert back, "nothing to name, so nothing was asserted"
    for config in back:
        assert desks.strategy_name(config) == str(StrategyFactory.create(config).id)


def test_a_name_without_a_tag_is_still_a_name():
    """A config carrying no `order_id_tag` would otherwise be named with a
    trailing dash, which is not an id Nautilus would ever assign and so could
    not be matched to anything."""
    from nautilus_trader.trading.config import ImportableStrategyConfig

    bare = ImportableStrategyConfig(
        strategy_path="till_infinity.strategies.surprise:SurpriseEdge",
        config_path="till_infinity.strategies.entries:EdgeEntryConfig",
        config={},
    )
    assert desks.strategy_name(bare) == "SurpriseEdge"


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
            "Heartbeat",
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


def test_the_desk_ceiling_can_be_raised_on_a_measured_box(monkeypatch):
    """**It was the binding constraint on a wider instrument list.**

    `PER_CORE` is 8 and the instance has two cores, so sixteen desks - which at
    two rules a symbol is **eight symbols**. Twenty-one were configured on
    2026-11-04 and twenty-six desks were clipped, every index among them, while
    the container sat at 6.8% CPU and 182MiB of 2.6GiB and the clipped symbols
    still paid for their feed and their fold.

    The default does not move: this number protects against late quotes, and
    late quotes are the one input every gate trusts. What changes is that a box
    which has been *measured* can say so.
    """
    from till_infinity.node import desks

    monkeypatch.delenv("TRADING_DESKS_PER_CORE", raising=False)
    base = desks.ceiling()
    assert base == max(1, desks.sizing.cores() * desks.PER_CORE)

    monkeypatch.setenv("TRADING_DESKS_PER_CORE", str(desks.PER_CORE * 3))
    assert desks.ceiling() == base * 3

    # Never zero, whatever is asked: a live node with no strategies is a node
    # that reports up and trades nothing.
    monkeypatch.setenv("TRADING_DESKS_PER_CORE", "0")
    assert desks.ceiling() >= 1

    # And junk falls back to the default rather than to zero.
    monkeypatch.setenv("TRADING_DESKS_PER_CORE", "lots")
    assert desks.ceiling() == base


def test_the_default_configuration_gets_the_fold_it_consumes(monkeypatch, loop):
    """**The default rule is `statespace-surprise`, and its producer was absent.**

    `desks.rules()` with nothing configured returns `('statespace-surprise',)`,
    whose only producer is `StatespaceActor`. The live node built that actor
    only when `STATESPACE_BARS` was set, so the **default** deploy ran a
    consumer with no producer: measured on the instance on 2026-11-04, seven of
    fourteen desks subscribed to `statespace.proposals` and nothing published
    it. Nothing raised, because each desk logged the topic it subscribed to and
    the actor simply did not exist.

    This is the case that was broken in production, so it is asserted with the
    environment production actually has - no `TRADING_STRATEGIES`, no
    `STATESPACE_BARS` - rather than with a rule named explicitly.
    """
    monkeypatch.delenv("STATESPACE_BARS", raising=False)
    monkeypatch.delenv("TRADING_STRATEGIES", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    from till_infinity.node import desks, live

    assert any(rule.startswith("statespace") for rule in desks.rules()), (
        "the default rule set no longer consumes proposals, so this test is "
        "asserting something else - check what it should pin now"
    )

    node = live.build()
    try:
        names = {str(a.id) for a in node.trader.actors()}
        assert "StatespaceActor" in names, (
            f"the default rules consume statespace.proposals and nothing would "
            f"publish it: {sorted(names)}"
        )
    finally:
        node.dispose()


def test_statespace_is_only_added_when_it_is_configured(monkeypatch, loop):
    """An actor subscribed to nothing is a fold that never runs pretending to
    be a model that does.

    **Statespace is opt-in and the record is opt-out**, which is the opposite
    way round and deliberate: a node that trades without a record is the state
    this desk was in since the port, and an opt-in record is a record nobody
    turns on. So the journal and the notifier are present here and statespace
    is not.

    **The rule has to be one that does not consume proposals, and it did not
    used to be.** This test ran on the default rule, which is
    `statespace-surprise` - whose only producer is the actor it was asserting
    absent. So it passed by encoding the bug: on 2026-11-04 the live instance
    had seven desks subscribed to `statespace.proposals` with nothing
    publishing it, and that was the *default* configuration rather than an
    unusual one. The fold is now built when a configured rule needs it, and
    this test names a rule that decides on bars so it still tests its own
    sentence.
    """
    monkeypatch.delenv("STATESPACE_BARS", raising=False)
    monkeypatch.setenv("TRADING_STRATEGIES", "smc-bos-causal")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    from till_infinity.node import live

    node = live.build()
    try:
        assert {str(a.id) for a in node.trader.actors()} == {
            "BasketExit-MT5",
            "Heartbeat",
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
    # A rule that decides on bars, so the fold is genuinely unwanted here and
    # not merely missing - see the note on the test above.
    monkeypatch.setenv("TRADING_STRATEGIES", "smc-bos-causal")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    monkeypatch.setenv("JOURNAL_OFF", "1")
    monkeypatch.setenv("ALERTS_OFF", "1")

    from till_infinity.node import live

    node = live.build()
    try:
        # `Heartbeat` is not switched off here: the status file is what a
        # container's probe reads, and a deploy that silenced the record
        # should not also silence the thing that says the node is alive.
        assert sorted(str(a.id) for a in node.trader.actors()) == [
            "BasketExit-MT5",
            "Heartbeat",
        ]
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
        "SurpriseEdge-Volatility 75 Index_E270",
        "SurpriseEdge-Volatility 100 Index_E270",
    }
    # The tag suffix is per-entry, so the symbol is what distinguishes these.
    # Both halves matter: a tag-only id would collide across symbols, and a
    # symbol-only id would collide across entries on one symbol.
    #
    # **Joined with `_` and not `-`, and these two desks are why.** They were
    # `...-Volatility 75 Index-E270` and `...-Volatility 100 Index-E270`, two
    # distinct `strategy_id`s - and `StrategyId.get_tag()` returns only what
    # follows the last hyphen, so both named their orders `E270` and collided
    # the moment they proposed on the same bar close. This assertion passing
    # is what made that look impossible; see
    # `test_two_desks_never_generate_the_same_order_id`.
    tags = {strategy.config.order_id_tag for strategy in built}
    assert len(tags) == 2


def test_two_desks_never_generate_the_same_order_id(monkeypatch):
    """**Distinct `strategy_id`s are not enough.**

    Nautilus namespaces order ids on `StrategyId.get_tag()`, which returns
    only the text after the **last** hyphen - and `_tag` put the symbol first
    and the rule hash last, so `EdgeEntry-EURUSD-E287` and
    `EdgeEntry-GBPUSD-E287` are two desks whose ids share one namespace.
    Each carries its own `OrderFactory` with its own counter starting from
    its own cached count, so both call their first bracket `-1`; the datetime
    tag has one-second resolution, so two desks proposing on the same bar
    close produce byte-identical ids and the second is denied `duplicate
    OrderListId`. `_deny_order_list` denies every leg, so each collision is
    three denials.

    That is what happened on the night of 2026-11-05: three brackets refused
    with retcode 10018 on index feeds whose session had ended, and nine
    denials behind them - three collided brackets, not a retry. Nothing in
    this repository retries a refused order.

    With a venue qualifier it is worse: `EURUSD-E287-MT5` tags on `MT5`, so
    every desk on the venue shares one namespace.

    `test_every_desk_gets_a_distinct_tag` passed throughout, because distinct
    tags and distinct `strategy_id`s were never the property that mattered.
    """
    from nautilus_trader.common.component import TestClock
    from nautilus_trader.common.generators import ClientOrderIdGenerator, OrderListIdGenerator
    from nautilus_trader.model.identifiers import TraderId

    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD GBPUSD US500")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")
    built, _ = desks.build("MT5")
    assert len(built) >= 2, "need at least two desks to collide"

    seats = [s.id.get_tag() for s in built]
    assert len(set(seats)) == len(seats), (
        f"desks share an order-id namespace: {sorted(seats)} from {[str(s.id) for s in built]}"
    )

    # The consequence, measured the way production meets it: one clock, so
    # every desk is proposing in the same second.
    trader, clock = TraderId("TRADER-001"), TestClock()
    lists = [OrderListIdGenerator(trader, s.id, clock, 0).generate() for s in built]
    orders = [ClientOrderIdGenerator(trader, s.id, clock, 0).generate() for s in built]
    assert len(set(lists)) == len(lists), f"colliding order list ids: {sorted(map(str, lists))}"
    assert len(set(orders)) == len(orders), (
        f"colliding client order ids: {sorted(map(str, orders))}"
    )


def test_a_venue_qualified_tag_is_also_unique(monkeypatch):
    """The multi-venue shape, which collided hardest: tagging on the venue put
    every desk on the venue into one namespace."""
    from nautilus_trader.model.identifiers import StrategyId

    from till_infinity.node.desks import _tag

    seats = {
        StrategyId(f"EdgeEntry-{_tag('swing-level', 'edge', symbol, 'MT5')}").get_tag()
        for symbol in ("EURUSD", "GBPUSD", "US500")
    }
    assert len(seats) == 3, f"venue-qualified desks share a namespace: {sorted(seats)}"
