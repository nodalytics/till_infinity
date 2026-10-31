"""`service.Trader`'s gates, as a Nautilus strategy.

The first increment of the port in
`docs/specs/2026-10-31-service-becomes-nautilus-strategies.md`. What these
tests are for is the part that is *ours*: the gate sequence, what each gate
records, and that an accepted intent reaches the venue in the right shape.
What they deliberately do not test is order bookkeeping, reconciliation or
position tracking - Nautilus owns those, and a test of them here would be a
test of the framework.
"""

from __future__ import annotations

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from till_infinity.domain.models import Intent, Refusal, Side
from till_infinity.strategies.entries import (
    ArrivalEntry,
    ArrivalEntryConfig,
    EdgeEntry,
    EdgeEntryConfig,
    RestingEntry,
    RestingEntryConfig,
    _side,
)

VENUE = Venue("SIM")
EURUSD = TestInstrumentProvider.default_fx_ccy("EUR/USD", VENUE)
BAR_TYPE = BarType.from_str(f"{EURUSD.id}-1-HOUR-LAST-EXTERNAL")


def engine_with(
    strategy_config: EdgeEntryConfig, build: type[EdgeEntry] = EdgeEntry
) -> tuple[BacktestEngine, EdgeEntry]:
    """A one-venue engine with the strategy added and started.

    `run()` is not called: these tests drive the handlers directly, because
    what is under test is the gate sequence rather than a backtest's loop.
    """
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001",
            logging=LoggingConfig(bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
    )
    engine.add_instrument(EURUSD)
    strategy = build(strategy_config)
    engine.add_strategy(strategy)
    return engine, strategy


def config(**kwargs) -> EdgeEntryConfig:
    base = {
        "instrument_id": EURUSD.id,
        "bar_type": BAR_TYPE,
        "rule": "statespace-surprise",
    }
    return EdgeEntryConfig(**(base | kwargs))


def quote(bid: float, ask: float, ts: int = 0) -> QuoteTick:
    return QuoteTick(
        instrument_id=EURUSD.id,
        bid_price=Price(bid, 5),
        ask_price=Price(ask, 5),
        bid_size=Quantity(1_000_000, 0),
        ask_size=Quantity(1_000_000, 0),
        ts_event=ts,
        ts_init=ts,
    )


def bar(close: float, ts: int = 0) -> Bar:
    return Bar(
        BAR_TYPE,
        Price(close, 5),
        Price(close + 0.0005, 5),
        Price(close - 0.0005, 5),
        Price(close, 5),
        Quantity(1_000_000, 0),
        ts_event=ts,
        ts_init=ts,
    )


def intent(**kwargs) -> Intent:
    base = {
        "feed": "eurusd",
        "symbol": "EUR/USD",
        "side": Side.BUY,
        "volume": 100_000.0,
        "entry": 1.1000,
        "stop": 1.0950,
        "target": 1.1100,
        "reason": "test",
    }
    return Intent(**(base | kwargs))


# ------------------------------------------------------------ the framework


def test_an_entry_is_a_real_nautilus_strategy():
    """Not an object a runner calls: the framework's own base, so the engine
    drives it and `strategy_id` is on every order it sends."""
    from nautilus_trader.trading.strategy import Strategy

    engine, strategy = engine_with(config())
    assert isinstance(strategy, Strategy)
    assert str(strategy.id).startswith("EdgeEntry")
    engine.dispose()


def test_starting_builds_the_rule_and_registers_the_detectors():
    """An unknown detector or rule must fail at wiring time: one the config
    asked for and the strategy quietly did not build is a sweep reporting a
    null for a question it never asked."""
    engine, strategy = engine_with(config(indicators=("cusum", "trend:typical")))
    engine.trader.start()
    assert strategy.rule is not None
    assert strategy.rule.name == "statespace-surprise"
    assert set(strategy.detectors) == {"cusum", "trend:typical"}
    assert len(strategy.registered_indicators) == 2
    engine.dispose()


def test_an_unknown_rule_is_refused_by_the_registry():
    """And the registry owns the message, listing what it does have.

    `Desk.on_start` had its own check for this and it was dead code: `build`
    raises first. A second check would either never run or would disagree with
    the registry about what exists.
    """
    engine, _ = engine_with(config(rule="no-such-rule"))
    with pytest.raises(ValueError, match="unknown strategy: no-such-rule"):
        engine.trader.start()
    engine.dispose()


def test_the_engine_feeds_the_registered_indicators():
    """`on_bar` runs after Nautilus has updated every registered indicator, so
    nothing here calls `handle_bar` and the detectors still warm."""
    engine, strategy = engine_with(config(indicators=("trend",)))
    engine.trader.start()
    detector = strategy.detectors["trend"]
    for i in range(40):
        strategy.handle_bar(bar(1.1000 + 0.0001 * i, i * 3_600_000_000_000))
    assert detector.has_inputs
    engine.dispose()


# ----------------------------------------------------------------- the gates


def test_a_signal_for_an_untraded_instrument_is_counted_not_refused():
    """Counted, not journalled. It is not a refusal - the desk does not trade
    it - but a tally of nothing is a tally nobody can read."""
    engine, strategy = engine_with(config())
    engine.trader.start()
    # No instrument in the cache for a different id, so `_spec` is None. Done
    # by clearing rather than by a second config, so the gate is what differs.
    strategy._spec = lambda: None
    assert strategy.consider({"feed": "eurusd"}) is None
    assert strategy.passed_over == {"(desk):untraded": 1}
    engine.dispose()


def test_a_missing_quote_is_a_refusal_with_its_gate():
    """The misleading silence `Trader` recorded: an instrument the desk *does*
    trade, refused for a reason nothing recorded."""
    engine, strategy = engine_with(config())
    engine.trader.start()
    strategy.rule.wants = lambda payload: True
    got = strategy.consider({"feed": "eurusd"})
    assert isinstance(got, Refusal)
    assert got.gate == "no-quote"
    assert strategy.passed_over == {"(desk):no-quote": 1}
    engine.dispose()


def test_a_crossed_quote_is_a_bad_tick_and_not_a_tight_spread():
    """Folding it in would make the cost read *better* than the truth, which is
    the one direction of error that lets an idea through."""
    engine, strategy = engine_with(config())
    engine.trader.start()
    strategy.rule.wants = lambda payload: True
    strategy.cache.add_quote_tick(quote(1.10050, 1.10000))
    got = strategy.consider({"feed": "eurusd"})
    assert isinstance(got, Refusal)
    assert got.gate == "crossed"
    engine.dispose()


def test_a_rule_that_does_not_want_the_signal_is_counted_and_not_journalled():
    """Hundreds a day. Journalling all of it buries the refusals that matter."""
    engine, strategy = engine_with(config())
    engine.trader.start()
    strategy.rule.wants = lambda payload: False
    assert strategy.consider({"feed": "eurusd"}) is None
    assert strategy.passed_over == {"statespace-surprise:unwanted": 1}
    assert strategy.refused == 0, "an unwanted signal is not a refusal"
    engine.dispose()


def test_a_declined_signal_counts_the_rules_own_gate():
    engine, strategy = engine_with(config())
    engine.trader.start()
    strategy.rule.wants = lambda payload: True
    strategy.rule.consider = lambda *a, **k: Refusal(gate="probability", detail="too low")
    strategy.cache.add_quote_tick(quote(1.10000, 1.10010))
    got = strategy.consider({"feed": "eurusd"})
    assert isinstance(got, Refusal)
    assert strategy.refused == 1
    assert strategy.passed_over == {"statespace-surprise:probability": 1}
    engine.dispose()


# --------------------------------------------------------------- the placing


def test_an_accepted_intent_becomes_a_bracket_with_its_protection():
    """The stop and the target go **on** the order, not in a second call.

    `Trader._protect` set them afterwards and had to handle the window in which
    a filled position had no stop - which is exactly when a fast move finds it.
    A bracket has no such window.

    What is captured here is what `place` *builds*, not what the venue does
    with it. Submitting through a connected exec client is Nautilus's to get
    right, and a test of it here would be a test of the framework - this
    module's docstring says so. (An `engine.run()` version of this crashed
    inside the Cython exec client, which is a second reason not to make a
    framework path the subject of our test.)
    """
    engine, strategy = engine_with(config())
    engine.trader.start()
    sent: list[object] = []
    strategy.submit_order_list = sent.append

    strategy.place(intent())

    assert len(sent) == 1, "a bracket is one order list"
    orders = sent[0].orders
    assert len(orders) == 3, [str(o.order_type) for o in orders]
    entry, *exits = orders
    assert entry.side is OrderSide.BUY
    assert entry.quantity == EURUSD.make_qty(100_000.0)
    # Both exits are the other side, and both reduce.
    assert {o.side for o in exits} == {OrderSide.SELL}
    kinds = {o.order_type.name for o in exits}
    assert "STOP_MARKET" in kinds, kinds
    prices = {float(getattr(o, "trigger_price", 0) or getattr(o, "price", 0)) for o in exits}
    assert prices == {1.0950, 1.1100}
    engine.dispose()


def test_without_a_bracket_the_stop_is_attached_on_the_fill():
    """The fallback for a venue that cannot bracket - MT5 through the bridge.

    Still ours, but one *event* later rather than one *poll* later, which is
    the difference that matters: a poll leaves a window, an event does not.
    """
    engine, strategy = engine_with(config(bracket=False))
    engine.trader.start()
    sent: list[object] = []
    strategy.submit_order = sent.append

    strategy.place(intent())
    assert len(sent) == 1
    assert sent[0].order_type.name == "MARKET"
    assert strategy._pending, "the intent is held until its fill"

    # The fill arrives as an event, carrying the id the intent was keyed on.
    filled = type("Filled", (), {"client_order_id": sent[0].client_order_id})()
    strategy.on_order_filled(filled)
    assert len(sent) == 2
    stop = sent[1]
    assert stop.order_type.name == "STOP_MARKET"
    assert stop.side is OrderSide.SELL, "the stop closes, so it is the other side"
    assert float(stop.trigger_price) == 1.0950
    assert stop.is_reduce_only
    assert not strategy._pending, "and the intent is not held twice"
    engine.dispose()


def test_a_volume_that_rounds_to_zero_is_refused_rather_than_nudged_up():
    """Nudging it to the minimum would place a trade nobody sized."""
    engine, strategy = engine_with(config())
    engine.trader.start()
    strategy.place(intent(volume=0.0))
    assert strategy.passed_over == {"(desk):zero-volume": 1}
    assert not strategy.cache.orders(strategy_id=strategy.id)
    engine.dispose()


def test_an_unknown_side_raises_rather_than_defaulting_to_buying():
    assert _side(Side.BUY) is OrderSide.BUY
    assert _side(Side.SELL) is OrderSide.SELL
    with pytest.raises(ValueError, match="neither a buy nor a sell"):
        _side("sideways")  # type: ignore[arg-type]


# ----------------------------------------------------------- what Nautilus owns


def test_the_held_guard_sees_every_strategys_positions():
    """ "First taker wins - two strategies wanting the same instrument is one
    idea found twice." `Trader` enforced that by running them in one object;
    the cache is shared, so the same guard is a query that is not filtered by
    `strategy_id` unless asked.
    """
    engine, strategy = engine_with(config())
    engine.trader.start()
    # Nothing held yet.
    assert strategy._already_held() is None
    engine.dispose()


# -------------------------------------------------------------- the resting entry


def resting(**kwargs) -> RestingEntryConfig:
    base = {"instrument_id": EURUSD.id, "bar_type": BAR_TYPE, "rule": "statespace-surprise"}
    return RestingEntryConfig(**(base | kwargs))


def _resting_engine(**kwargs) -> tuple[BacktestEngine, RestingEntry]:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001", logging=LoggingConfig(bypass_logging=True)
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
    )
    engine.add_instrument(EURUSD)
    strategy = RestingEntry(resting(**kwargs))
    engine.add_strategy(strategy)
    engine.trader.start()
    return engine, strategy


def test_a_rest_is_a_limit_at_the_intents_entry():
    engine, strategy = _resting_engine()
    sent: list[object] = []
    strategy.submit_order = sent.append
    strategy.place(intent())
    assert len(sent) == 1
    order = sent[0]
    assert order.order_type.name == "LIMIT"
    assert float(order.price) == 1.1000
    assert strategy._waiting, "the intent is held so it can be withdrawn"
    engine.dispose()


def test_a_rest_is_pushed_clear_of_the_venues_minimum():
    """Measured on the live desk: Volatility 100 Index reports 138 points at a
    point of 0.01, so the venue wants 1.38 while a 0.50v edge asked for 0.23 -
    and four of six rests in an hour came back `Invalid price`."""
    engine, strategy = _resting_engine()
    # The venue wants 20 pips; the entry is 1 pip from the market.
    strategy._min_distance = lambda instrument: 0.0020
    strategy._reference = lambda: 1.1001
    got = strategy._restable(EURUSD, intent(entry=1.1000, stop=1.0900))
    assert got is not None
    assert got == pytest.approx(1.0980), "pushed out by the venue's minimum"
    engine.dispose()


def test_a_rest_is_never_pushed_through_its_own_stop():
    """The stop does not move with the entry, so a limit on the far side of it
    opens a trade that is already beaten."""
    engine, strategy = _resting_engine()
    strategy._min_distance = lambda instrument: 0.0020
    strategy._reference = lambda: 1.1001
    # A stop only 5 pips below the entry: pushing out 20 would cross it.
    assert strategy._restable(EURUSD, intent(entry=1.1000, stop=1.0995)) is None
    engine.dispose()


def test_giving_up_the_venue_side_order_is_not_giving_up_the_trade():
    """The in-process wait is untouched - that is the fallback, and it was the
    whole mechanism before resting existed."""
    engine, strategy = _resting_engine(give_up_when_crowded=False)
    strategy._min_distance = lambda instrument: 0.0020
    strategy._reference = lambda: 1.1001
    got = strategy._restable(EURUSD, intent(entry=1.1000, stop=1.0995))
    assert got == pytest.approx(1.1000), "left at the entry rather than abandoned"
    engine.dispose()


def test_a_rest_is_withdrawn_when_the_window_expires():
    """A resting order with no deadline is a trade taken on information that
    has gone stale."""
    engine, strategy = _resting_engine(window_hours=0.0)
    sent: list[object] = []
    strategy.submit_order = sent.append
    strategy.place(intent())
    assert strategy._waiting
    strategy.on_quote_tick(quote(1.10000, 1.10010))
    assert not strategy._waiting, "the window had already closed"
    assert any("withdrawn" in k for k in strategy.passed_over)
    engine.dispose()


def test_a_rest_is_withdrawn_when_the_spread_reaches_the_target():
    """Against the **target**, which is what risk measures it against when the
    same setting refuses an entry - not against the stop."""
    engine, strategy = _resting_engine()
    strategy.submit_order = lambda order: None
    strategy.settings.max_spread_fraction = 0.1
    strategy.place(intent(entry=1.1000, target=1.1100))
    # Reward is 100 pips, so a 15-pip spread is 15% of it.
    strategy.on_quote_tick(quote(1.10000, 1.10150))
    assert not strategy._waiting
    engine.dispose()


def test_a_rest_that_fills_leaves_nothing_behind():
    """An order left behind is one that fills on a setup this system has
    already refused - the exact failure a venue-side limit invites."""
    engine, strategy = _resting_engine()
    sent: list[object] = []
    strategy.submit_order = sent.append
    strategy.place(intent())
    filled = type("Filled", (), {"client_order_id": sent[0].client_order_id})()
    strategy.on_order_filled(filled)
    assert not strategy._waiting
    engine.dispose()


# -------------------------------------------------------------- the arrival entry


def _arrival_engine(**kwargs) -> tuple[BacktestEngine, ArrivalEntry]:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001", logging=LoggingConfig(bypass_logging=True)
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
    )
    engine.add_instrument(EURUSD)
    base = {"instrument_id": EURUSD.id, "bar_type": BAR_TYPE, "rule": "statespace-surprise"}
    strategy = ArrivalEntry(ArrivalEntryConfig(**(base | kwargs)))
    engine.add_strategy(strategy)
    engine.trader.start()
    return engine, strategy


def test_parking_holds_the_payload_and_not_the_intent():
    """Re-asked, not resurrected: an intent held and then placed would be a
    decision made at a price that has since moved."""
    engine, strategy = _arrival_engine()
    strategy.place(intent(entry=1.0950))
    assert strategy._payload is not None
    assert strategy._trigger == pytest.approx(1.0950)
    assert strategy._side is Side.BUY
    engine.dispose()


def test_an_arrival_marks_after_pullback_before_asking_again():
    """That mark is what lets a turn requirement apply here and only here: the
    same reading means *arriving at the level* before the wait and *the fall
    has not finished* after it."""
    engine, strategy = _arrival_engine(require_candle=False)
    seen: list[dict] = []
    strategy.consider = lambda payload: seen.append(payload) or None
    strategy.place(intent(entry=1.0950))
    # Price comes to it from above.
    strategy.on_quote_tick(quote(1.09490, 1.09500))
    assert seen, "the rule was asked again on arrival"
    assert seen[0]["features"]["after_pullback"] == 1.0
    assert strategy._payload is None, "and the park is released"
    engine.dispose()


def test_price_that_has_not_arrived_keeps_waiting():
    engine, strategy = _arrival_engine()
    strategy.place(intent(entry=1.0950))
    strategy.on_quote_tick(quote(1.10000, 1.10010))
    assert strategy._payload is not None
    engine.dispose()


def test_a_park_expires_rather_than_waiting_forever():
    engine, strategy = _arrival_engine(window_hours=0.0)
    strategy.place(intent(entry=1.0950))
    strategy.on_quote_tick(quote(1.10000, 1.10010))
    assert strategy._payload is None
    assert any("unparked" in k for k in strategy.passed_over)
    engine.dispose()


def test_an_unavailable_candle_confirms_nothing():
    """Treating missing data as a pass would make this silently inactive on
    every instrument whose bars fail - the failure mode that looks like
    working code."""
    engine, strategy = _arrival_engine(require_candle=True)
    assert strategy._candle_at(intent()) == "", "no bars yet"
    refusal = strategy._unconfirmed(intent())
    assert isinstance(refusal, Refusal)
    assert refusal.gate == "unconfirmed"
    assert "no candle" in refusal.detail
    engine.dispose()


def test_either_witness_confirms_unless_both_are_demanded():
    """The disjunction is right for a scalp, which cannot wait four hours for a
    bar to close; the conjunction for a swing, which has the time."""
    engine, strategy = _arrival_engine(require_turn_vol=1.0, require_candle=True)
    turned = intent(features={"pressure_vol": 2.0})
    # The turn alone is enough.
    assert strategy._unconfirmed(turned) is None

    engine2, both = _arrival_engine(
        require_turn_vol=1.0, require_candle=True, needs_both_witnesses=True
    )
    refusal = both._unconfirmed(turned)
    assert isinstance(refusal, Refusal), "a swing wants the candle too"
    assert "no candle" in refusal.detail
    engine.dispose()
    engine2.dispose()


def test_a_turn_the_wrong_way_does_not_confirm_a_buy():
    engine, strategy = _arrival_engine(require_turn_vol=1.0, require_candle=False)
    against = intent(side=Side.BUY, features={"pressure_vol": -2.0})
    refusal = strategy._unconfirmed(against)
    assert isinstance(refusal, Refusal)
    assert "turned -2.00v" in refusal.detail
    engine.dispose()


def test_asking_for_no_witness_confirms_everything():
    """Which is the straight-to-market case, and has to stay reachable."""
    engine, strategy = _arrival_engine(require_turn_vol=0.0, require_candle=False)
    assert strategy._unconfirmed(intent()) is None
    engine.dispose()
