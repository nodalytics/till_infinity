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
from till_infinity.statespace.proposing import TRIGGER
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


class _Deciding(EdgeEntry):
    """An entry with a decision, since `Desk` deliberately has none.

    A test subclass rather than a stubbed attribute: `Desk.decide` raises by
    design now, so a test that needs a decision supplies one the way a real
    strategy does - by composition.
    """

    def decide(self, payload):
        return intent()


class _Unwanting(EdgeEntry):
    """Declines to judge the signal at all - not its shape or feed."""

    def wants(self, payload) -> bool:
        return False

    def decide(self, payload):
        raise AssertionError("should not be asked")


class _Declining(EdgeEntry):
    """Judges it and says no, under its own gate."""

    def decide(self, payload):
        return Refusal(gate="probability", detail="too low")


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


def test_starting_registers_the_detectors_ours_and_the_frameworks():
    """An unknown detector must fail at wiring time: one the config asked for
    and the strategy quietly did not build is a sweep reporting a null for a
    question it never asked.

    Both sources, one syntax: `trend:typical` names one of ours and the float
    it reads, `rsi:7` one of Nautilus's and its period.
    """
    engine, strategy = engine_with(config(indicators=("cusum", "trend:typical", "rsi:7")))
    engine.trader.start()
    assert set(strategy.detectors) == {"cusum", "trend:typical", "rsi:7"}
    assert len(strategy.registered_indicators) == 3
    assert strategy.detectors["rsi:7"].period == 7, "the period reached the framework's own"
    engine.dispose()


def test_an_unknown_indicator_is_refused_with_both_catalogues():
    engine, _ = engine_with(config(indicators=("no-such-detector",)))
    with pytest.raises(ValueError, match="is not a detector"):
        engine.trader.start()
    engine.dispose()


def test_a_desk_with_no_decision_says_so_rather_than_doing_nothing():
    """What replaced the abstract method.

    A `Strategy` ABC made the decision a hierarchy; a `Desk` with no mixin is
    a strategy nobody gave a decision to, and it should say which mixin is
    missing rather than silently refusing every signal.
    """
    engine, strategy = engine_with(config())
    engine.trader.start()
    with pytest.raises(NotImplementedError, match="compose it with a mixin"):
        strategy.decide({"feed": "eurusd"})
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


def test_a_proposal_about_another_feed_places_nothing():
    """`PROPOSALS` is one topic and all thirty desks subscribe to it.

    `Surprise.wants` checked the payload's feed against its *allowlist* and
    nothing checked it was **this** desk's feed, while `place` always sizes
    the desk's own instrument. So on 2026-11-07 at 12:30:38 one proposal -
    `surprise 5.66 on btcusd` - became BUY brackets on USDCAD, EURUSD,
    USDJPY, USDCHF, Wall Street 30, US SP 500 and US Tech 100 inside 119ms,
    seven desks each logging `btcusd` beside its own prices. EURUSD and
    USDCHF were both bought, which is the same exposure twice in opposite
    directions.

    Driven through `on_data` rather than `consider` because the bug was that
    an order got *placed*: a gate that returns the right verdict and still
    reaches the venue would pass a `consider`-only test.
    """
    engine, strategy = engine_with(config(), build=_Deciding)
    engine.trader.start()
    # A quote good enough that the desk's own feed would be placed, so what
    # the guard refuses is the feed and not the tick.
    strategy.cache.add_quote_tick(quote(1.09995, 1.10005))
    # Stubbed because `trader.start()` alone leaves the portfolio with no
    # account, and a desk with no equity refuses at `unsized` - which would
    # make this pass with the gate absent. See the sibling test below.
    strategy._equity = lambda: 1_000_000.0
    sent: list[object] = []
    strategy.submit_order_list = sent.append

    strategy.on_data({"feed": "btcusd"})

    assert sent == [], "a proposal about btcusd placed an order on EUR/USD"
    assert strategy.passed_over == {"(desk):other-feed": 1}
    assert strategy.refused == 0, "another feed's proposal was never ours to decline"
    assert strategy.taken == 0
    engine.dispose()


def test_a_proposal_about_this_desks_own_feed_is_still_placed():
    """The positive control for the gate above.

    A guard that compared the wrong pair of names - `feed_of` is
    `symbol.lower()` with the separator dropped, the producer's is
    `feeds.get(symbol, symbol.lower())` - would block every proposal and read
    as a quiet desk, which is the failure this file's `no-quote` test was
    written for.
    """
    engine, strategy = engine_with(config(), build=_Deciding)
    engine.trader.start()
    strategy.cache.add_quote_tick(quote(1.09995, 1.10005))
    strategy._equity = lambda: 1_000_000.0
    sent: list[object] = []
    strategy.submit_order_list = sent.append

    strategy.on_data({"feed": "eurusd"})

    assert len(sent) == 1, f"the desk's own feed was blocked: {strategy.passed_over}"
    assert strategy.taken == 1
    engine.dispose()


def test_the_tally_names_its_own_feed():
    """**Two diagnoses this weekend turned on not knowing which desk spoke.**

    The tally is logged by `SurpriseEdge`, which is one class shared by thirty
    instruments, so a line reading `gates={'statespace-surprise:cost': 1}`
    could be any of them. On 2026-11-08 the cost readings `15% of target` and
    `27% of target` had to be attributed by re-running the rule offline on
    every crypto and matching the numbers, and a later `21%/42%` reading could
    not be attributed at all.

    One word on a line that is already at INFO removes that.
    """
    engine, strategy = engine_with(config())
    engine.trader.start()

    line = strategy._tally_line()

    assert "eurusd" in line, line
    assert "taken=" in line, line
    assert "gates=" in line, line
    engine.dispose()


def test_a_missing_quote_is_a_refusal_with_its_gate():
    """The misleading silence `Trader` recorded: an instrument the desk *does*
    trade, refused for a reason nothing recorded."""
    engine, strategy = engine_with(config(), build=_Deciding)
    engine.trader.start()
    got = strategy.consider({"feed": "eurusd"})
    assert isinstance(got, Refusal)
    assert got.gate == "no-quote"
    assert strategy.passed_over == {"(desk):no-quote": 1}
    engine.dispose()


def test_a_crossed_quote_is_a_bad_tick_and_not_a_tight_spread():
    """Folding it in would make the cost read *better* than the truth, which is
    the one direction of error that lets an idea through."""
    engine, strategy = engine_with(config(), build=_Deciding)
    engine.trader.start()
    strategy.cache.add_quote_tick(quote(1.10050, 1.10000))
    got = strategy.consider({"feed": "eurusd"})
    assert isinstance(got, Refusal)
    assert got.gate == "crossed"
    engine.dispose()


def test_a_rule_that_does_not_want_the_signal_is_counted_and_not_journalled():
    """Hundreds a day. Journalling all of it buries the refusals that matter."""
    engine, strategy = engine_with(config(), build=_Unwanting)
    engine.trader.start()
    assert strategy.consider({"feed": "eurusd"}) is None
    assert strategy.passed_over == {"_Unwanting:unwanted": 1}
    assert strategy.refused == 0, "an unwanted signal is not a refusal"
    engine.dispose()


def test_a_declined_signal_counts_the_rules_own_gate():
    engine, strategy = engine_with(config(), build=_Declining)
    engine.trader.start()
    strategy.cache.add_quote_tick(quote(1.10000, 1.10010))
    got = strategy.consider({"feed": "eurusd"})
    assert isinstance(got, Refusal)
    assert strategy.refused == 1
    assert strategy.passed_over == {"_Declining:probability": 1}
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


# ------------------------------------------------------- the counterfactual


@pytest.mark.parametrize(
    "build",
    [EdgeEntry, RestingEntry, ArrivalEntry],
    ids=["edge", "resting", "arrival"],
)
def test_every_entry_keeps_resolving_its_counterfactual(build):
    """An override of `on_quote_tick` that forgets `super()` leaves
    `following` climbing forever and the trial count wrong - and nothing else
    would show it, because the number still prints.

    `RestingEntry` and `ArrivalEntry` both override it, and both forgot on the
    first pass. This is the test that would have caught that.
    """
    from till_infinity.domain.models import Intent as DomainIntent

    cfgs = {
        EdgeEntry: EdgeEntryConfig,
        RestingEntry: RestingEntryConfig,
        ArrivalEntry: ArrivalEntryConfig,
    }
    base = {"instrument_id": EURUSD.id, "bar_type": BAR_TYPE, "rule": "statespace-surprise"}
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
    strategy = build(cfgs[build](**base))
    engine.add_strategy(strategy)
    engine.trader.start()

    # One declined trade, followed. It never fills, so the fill window ends it.
    wanted: DomainIntent = intent(entry=1.0500)
    strategy.counterfactual.wanted(wanted, by="test", now=0.0, hold=1.0)
    assert strategy.counterfactual.following == 1

    strategy.on_quote_tick(quote(1.10000, 1.10010, 10_000_000_000))
    assert strategy.counterfactual.following == 0, (
        f"{build.__name__}.on_quote_tick did not resolve - did it call super()?"
    )
    assert strategy.resolved
    assert strategy.resolved[0].how == "never filled"
    engine.dispose()


def test_a_refusal_with_no_intent_follows_nothing():
    """Most gates refuse before there is an intent to build, and a
    counterfactual invented from a refusal with no entry would be following a
    trade nobody specified."""
    engine, strategy = engine_with(config())
    engine.trader.start()
    strategy._follow(Refusal(gate="no-quote", detail="none"), {"feed": "eurusd"})
    assert strategy.counterfactual.following == 0
    engine.dispose()


def test_a_refusal_carrying_its_intent_is_followed():
    engine, strategy = engine_with(config())
    engine.trader.start()
    strategy._follow(
        Refusal(gate="probability", detail="too low"),
        {"feed": "eurusd", "intent": intent(), "regime": 0.7, "market": "quiet"},
    )
    assert strategy.counterfactual.following == 1
    assert strategy.passed_over == {"(desk):following-probability": 1}
    engine.dispose()


def test_following_can_be_switched_off_but_is_on_by_default():
    """On by default and it should stay on: the DSR's `Var(SR_trials)` is a
    variance over the whole search."""
    assert config().follow_untaken is True
    engine, strategy = engine_with(config(follow_untaken=False))
    engine.trader.start()
    strategy._follow(Refusal(gate="g", detail="d"), {"feed": "eurusd", "intent": intent()})
    assert strategy.counterfactual.following == 0
    engine.dispose()


# ------------------------------------------------------ decision x mechanism


def test_one_decision_composes_with_every_mechanism():
    """What replaced the ABC.

    A `Strategy` ABC fixed the pair in the wrong direction: the decision knew
    nothing about how it would be placed, and the thing that placed it knew
    nothing about what it was. A mixin with no base lets any decision compose
    with any entry, which is what "entries and exits are asymmetric" means in
    code - and each leaf is a Nautilus `Strategy`, so the framework records
    *which* pairing took a trade.
    """
    from nautilus_trader.trading.strategy import Strategy

    from till_infinity.strategies.surprise import (
        Surprise,
        SurpriseArrival,
        SurpriseEdge,
        SurpriseResting,
    )

    for built, mechanism in (
        (SurpriseEdge, EdgeEntry),
        (SurpriseResting, RestingEntry),
        (SurpriseArrival, ArrivalEntry),
    ):
        assert issubclass(built, Surprise), built
        assert issubclass(built, mechanism), built
        assert issubclass(built, Strategy), "the leaf is the framework's class"
        # The decision comes before the mechanism, so `decide` is the mixin's
        # and `place` is the entry's.
        assert built.decide is Surprise.decide
        assert built.place is mechanism.place


def test_the_decision_mixin_carries_no_nautilus_base():
    """Which is what makes it composable. A mixin that subclassed `Strategy`
    would force a second base into every pairing and the MRO would decide the
    mechanism rather than the class name."""
    from nautilus_trader.common.actor import Actor
    from nautilus_trader.trading.strategy import Strategy

    from till_infinity.strategies.surprise import Surprise

    assert Surprise.__mro__ == (Surprise, object)
    assert not issubclass(Surprise, Strategy)
    assert not issubclass(Surprise, Actor)


def test_the_label_names_the_decision_and_not_the_class():
    """A gate tally keyed on the class name would say `SurpriseEdge` and
    `SurpriseResting` were different strategies refusing for different
    reasons, when they are one decision placed two ways."""
    from till_infinity.strategies.surprise import SurpriseEdge, SurpriseResting

    base = {"instrument_id": EURUSD.id, "bar_type": BAR_TYPE}
    edge = SurpriseEdge(EdgeEntryConfig(order_id_tag="A", **base))
    rest = SurpriseResting(RestingEntryConfig(order_id_tag="B", **base))
    assert edge.label == rest.label == "statespace-surprise"


def test_the_profile_keeps_the_measured_numbers():
    """The ABC's abstract surface went; its arithmetic did not."""
    from till_infinity.strategies.surprise import SurpriseEdge

    profile = SurpriseEdge(
        EdgeEntryConfig(order_id_tag="C", instrument_id=EURUSD.id, bar_type=BAR_TYPE)
    ).profile
    assert profile.reward_floor == 1.70
    # **The floor is the producer's trigger, not a number of its own.** At 3.5
    # against `proposing.TRIGGER` of 3.0, every proposal in [3.0, 3.5) was
    # emitted only to be refused here - and `|surprise| >= 3.0` fires on 1.80%
    # of real-market 15m bars, so the discarded band was not rare. The refusal
    # counter then reads as a quiet market rather than as two constants in
    # different modules disagreeing.
    assert profile.least_surprise == TRIGGER
    assert profile.least_surprise <= TRIGGER, (
        "a floor above the producer's trigger refuses everything it is sent"
    )
    assert profile.cost_share == 0.10
    for helper in ("floored_target", "protection", "risk_scale", "share_of_risk", "hold_for"):
        assert hasattr(profile, helper), helper


# ------------------------------------------------- the refusal reaches the record


def test_a_desk_level_refusal_is_published_to_the_journal():
    """**The producer that was missing.** `JournalActor` subscribed to a topic
    nothing published to, so every desk-level refusal reason went to a debug
    log and the record stayed empty.

    That is the mirror of a failure this desk has paid for twice: a subscriber
    with no publisher and a publisher with no subscriber look identical from
    either side, and both look like a quiet market.

    Only these gates, deliberately. They refuse an instrument the desk *does*
    trade for a reason nothing else carries - the terminal called it
    untradable, the quote was missing, a sibling already held it. The
    per-decision refusals stay at debug: hundreds a day, and journalling them
    would bury these.
    """
    from till_infinity.journal.models import Entry, Kind
    from till_infinity.strategies.desk import Desk
    from till_infinity.utils.topics import JOURNAL

    seen: list[dict] = []

    class Collector:
        """Enough of a component for `topics.publish`, and nothing more."""

        class _Bus:
            @staticmethod
            def publish(topic, msg):
                seen.append((topic, msg))

        msgbus = _Bus()
        id = "EdgeEntry-EURUSD-E270"

        class _Log:
            @staticmethod
            def debug(*_args):
                pass

        log = _Log()
        label = "statespace-surprise"

    Desk._journal(
        Collector(),
        Refusal(gate="no-quote", detail="no quote for EURUSD", feed="eurusd"),
        {"interval": "15m"},
    )

    assert len(seen) == 1
    topic, payload = seen[0]
    assert topic == JOURNAL
    # Round-trips through the wire shape the actor actually receives, rather
    # than asserting on the `Entry` we happen to have built here.
    entry = Entry.from_message(payload)
    assert entry.context["gate"] == "no-quote"
    assert entry.context["feed"] == "eurusd"
    assert entry.rationale == "no quote for EURUSD"
    assert "refusal" in entry.tags
    # **An observation, not a decision.** A refusal is "we noticed something
    # and did not act", which is what `Kind.OBSERVATION` is documented as, and
    # it is also the only kind `report.declines` reads - so while these were
    # written as decisions the gate tally counted none of them, and
    # `report.trades` would have mixed them into its pool of parents as trades
    # that never opened.
    assert entry.kind is Kind.OBSERVATION
    # **The strategy id is still pinned, in the column a reader looks in.**
    # This asserted `entry.actor` until 2026-11-12, on the argument that "a
    # record whose actor is wrong is worse than none" - which is right, and is
    # why the identity had to move rather than go. Every reader
    # (`report.trades`, `report.declines`, `journal.ledger.outcomes`) filters
    # on `actor = 'trading'` exactly and then reads the strategy out of the
    # context, so an entry signed with the strategy's own name was one no
    # reader could see at all.
    assert entry.actor == "trading"
    assert entry.context["strategy"] == "EdgeEntry-EURUSD-E270"
    assert entry.context["rule"] == "statespace-surprise"


def test_a_journal_that_cannot_write_does_not_stop_a_decision():
    """Nautilus's bus calls handlers inline, so this runs on the stack of a
    live decision. A record that cannot be written must not be a halt - the
    actor counts its own failures and degrades, which is where a write problem
    becomes visible."""
    from till_infinity.strategies.desk import Desk

    noted: list[str] = []

    class Broken:
        class _Bus:
            @staticmethod
            def publish(topic, msg):
                raise RuntimeError("the bus is gone")

        msgbus = _Bus()
        id = "EdgeEntry-EURUSD-E270"

        class _Log:
            @staticmethod
            def debug(message):
                noted.append(str(message))

        log = _Log()
        label = "statespace-surprise"

    # Returns rather than raising, and says so once.
    Desk._journal(Broken(), Refusal(gate="untradable", detail="not tradable"), {})
    assert noted
    assert "untradable" in noted[0]
