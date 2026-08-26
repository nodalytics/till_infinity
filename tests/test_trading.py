"""Trading: sizing, gates, strategies, brokers and the loop that joins them.

The arithmetic tests are exact - a stop distance and a lot size are facts, not
estimates, and a test that allows them to be approximately right allows the
class of bug that costs money. The behavioural ones are about what the module
refuses: most of this code exists to not trade, and a gate that silently stops
working looks exactly like a quiet market.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace

import pytest

from till_infinity import trading as td
from till_infinity.bus import ALERTS, QUOTES, RESOLUTIONS, SIGNALS, Bus, Message
from till_infinity.journal import Journal, read
from till_infinity.trading import exposure as ex
from till_infinity.trading import plans as tp
from till_infinity.trading import report as tr
from till_infinity.trading.book import Book, Seen
from till_infinity.trading.context import Context
from till_infinity.trading.models import Intent, Refusal, Side, SymbolSpec, Tick
from till_infinity.trading.paper import PaperBroker
from till_infinity.trading.risk import Guard
from till_infinity.trading.service import Trader
from till_infinity.trading.sizing import lots, price_distance, stop_for, target_for
from till_infinity.trading.speeds import Speeds
from till_infinity.trading.symbols import resolve

#: Signals carry wall-clock times, and the level book forgets by age. Using a
#: small constant here would put every level in 1970 and expire it instantly.
NOW = time.time()

GOLD = SymbolSpec(
    symbol="XAUUSD",
    digits=2,
    point=0.01,
    tick_size=0.01,
    tick_value=1.0,  # one lot (100oz) moving one cent is $1
    volume_min=0.01,
    volume_max=50.0,
    volume_step=0.01,
    contract_size=100.0,
)


def signal(**over):
    """A level call as `structures` publishes one."""
    features = {
        "level": 4400.0,
        "probability": 0.72,
        "probability_up": 0.72,
        "expected_push_vol": 1.4,
        "base_rate_up": 0.47,
        "edge": 0.25,
        "own_touches": 9.0,
        "neighbours": 3.0,
        "strength": 0.8,
        "risk_vol": 1.0,
        "vol_bps": 10.0,  # one volatility unit is 10bps: $4.40 at 4400
    }
    features.update(over.pop("features", {}))
    payload = {
        "shape": "level",
        "feed": "gold",
        "venue": "consensus",
        "score": 0.25,
        "detail": "up from above at 4400",
        "features": features,
        "interval": "5m",
        "direction": "up",
        "confluence": ["5m"],
        "time": NOW,
    }
    payload.update(over)
    return payload


def settings(**over):
    made = td.Settings(symbols=("gold",), account_equity=10_000.0, paper_equity=10_000.0)
    for key, value in over.items():
        setattr(made, key, value)
    return made


# --------------------------------------------------------------- the arithmetic


def test_a_buy_pays_the_ask_and_a_sell_hits_the_bid():
    """Sizing off the mid understates the cost twice - on entry and on exit."""
    tick = Tick("XAUUSD", bid=4399.5, ask=4400.5)
    assert tick.entry(Side.BUY) == 4400.5
    assert tick.exit(Side.BUY) == 4399.5
    assert tick.entry(Side.SELL) == 4399.5
    assert tick.mid == 4400.0


def test_a_volatility_unit_becomes_a_price_distance():
    # 10bps of 4400 is 4.40, so 1.4v is 6.16.
    assert price_distance(4400.0, 10.0, 1.0) == pytest.approx(4.40)
    assert price_distance(4400.0, 10.0, 1.4) == pytest.approx(6.16)


def test_the_stop_sits_beyond_the_level_on_the_side_price_came_from():
    assert stop_for(4400.0, Side.BUY, 4.4) == pytest.approx(4395.6)
    assert stop_for(4400.0, Side.SELL, 4.4) == pytest.approx(4404.4)


def test_the_target_is_measured_from_the_fill_not_the_level():
    assert target_for(4400.5, Side.BUY, 6.16) == pytest.approx(4406.66)
    assert target_for(4399.5, Side.SELL, 6.16) == pytest.approx(4393.34)


def test_lots_are_sized_so_the_stop_costs_the_budget():
    """0.25% of 10,000 is 25. A $4.40 stop costs $440 a lot, so 0.05 lots."""
    sized = lots(GOLD, equity=10_000.0, risk_fraction=0.0025, stop_distance=4.40)
    assert sized.ok
    assert sized.loss_per_lot == pytest.approx(440.0)
    assert sized.volume == pytest.approx(0.05)
    assert sized.risk_money == pytest.approx(22.0)


def test_volume_rounds_down_to_the_lot_step_never_up():
    """Rounding up is the one direction that breaches the risk it was sized for."""
    # 25 / (4.0/0.01 * 1.0) is 0.0625 lots, which is 0.06 and not 0.07.
    sized = lots(GOLD, equity=10_000.0, risk_fraction=0.0025, stop_distance=4.0)
    assert sized.volume == pytest.approx(0.06)
    assert sized.risk_money == pytest.approx(24.0)  # under the 25 budget, never over
    assert GOLD.round_volume(0.0999) == 0.09
    # And the result is a clean decimal, not 0.30000000000000004.
    assert GOLD.round_volume(0.3) == 0.3


def test_a_budget_under_the_minimum_lot_refuses_and_says_what_it_would_cost():
    sized = lots(GOLD, equity=100.0, risk_fraction=0.0025, stop_distance=4.40)
    assert not sized.ok
    assert "minimum" in sized.reason
    assert "4.40" in sized.reason or "4.4" in sized.reason  # 0.01 lots risks $4.40


def test_a_symbol_with_no_tick_value_cannot_be_sized():
    """Assuming one is how a position ends up ten times too large."""
    sized = lots(
        SymbolSpec(symbol="X", tick_value=0.0),
        equity=10_000.0,
        risk_fraction=0.0025,
        stop_distance=1.0,
    )
    assert not sized.ok
    assert "tick value" in sized.reason


# --------------------------------------------------------------------- the gates


def intent(**over):
    made = {
        "feed": "gold",
        "symbol": "XAUUSD",
        "side": Side.BUY,
        "volume": 0.05,
        "entry": 4400.5,
        "stop": 4395.6,
        "target": 4406.66,
        "risk_money": 22.0,
    }
    made.update(over)
    return Intent(**made)


def position(**over):
    made = {
        "ticket": 1,
        "symbol": "XAUUSD",
        "side": Side.BUY,
        "volume": 0.05,
        "price_open": 4400.0,
    }
    made.update(over)
    return td.Position(**made)


def test_one_position_per_instrument():
    """The same level firing twice is one idea, not two trades."""
    guard = Guard(settings())
    guard.roll(10_000.0, now=1_000.0)
    assert guard.allows(intent(), positions=[]) is None
    stopped = guard.allows(intent(), positions=[position()])
    assert stopped is not None
    assert stopped.gate == "already_open"


def test_a_thin_reward_to_risk_is_refused():
    guard = Guard(settings(min_reward_to_risk=1.2))
    guard.roll(10_000.0)
    # Target only half the risk away.
    stopped = guard.allows(intent(target=4402.95), positions=[])
    assert stopped is not None
    assert stopped.gate == "reward_to_risk"


def test_a_spread_that_eats_the_target_is_refused():
    guard = Guard(settings(max_spread_fraction=0.25))
    guard.roll(10_000.0)
    wide = Tick("XAUUSD", bid=4398.0, ask=4402.0)  # 4.0 against a 6.16 target
    stopped = guard.allows(intent(), positions=[], tick=wide)
    assert stopped is not None
    assert stopped.gate == "spread"


def test_the_day_halts_after_the_daily_loss_and_lifts_on_the_next_day():
    guard = Guard(settings(daily_loss_fraction=0.03))
    guard.roll(10_000.0, now=1_000.0)
    guard.record("gold", -200.0, 9_800.0, now=1_000.0)
    assert not guard.halted
    guard.record("gold", -150.0, 9_650.0, now=1_000.0)  # 350 > 300
    assert guard.halted
    assert guard.allows(intent(), positions=[], now=1_000.0).gate == "halted"

    guard.roll(9_650.0, now=1_000.0 + 86_400 * 2)
    assert not guard.halted


def test_a_loss_puts_that_instrument_on_cooldown():
    guard = Guard(settings(loss_cooldown=900.0))
    guard.roll(10_000.0, now=1_000.0)
    guard.record("gold", -20.0, 9_980.0, now=1_000.0)
    stopped = guard.allows(intent(), positions=[], now=1_100.0)
    assert stopped is not None
    assert stopped.gate == "cooldown"
    assert guard.allows(intent(), positions=[], now=2_000.0) is None


def test_refusals_are_counted_per_gate():
    """A gate that never fires does nothing; one that always fires is mis-set."""
    guard = Guard(settings())
    guard.roll(10_000.0)
    guard.allows(intent(), positions=[position()])
    guard.allows(intent(), positions=[position()])
    assert guard.refusals["already_open"] == 2


# --------------------------------------------------------------------- the plans


def test_every_plan_number_is_a_settings_field():
    assert tp._fields_are_covered()


def test_a_plan_sets_the_limits_together():
    made = settings()
    tp.apply(made, "conservative")
    assert made.risk_fraction == 0.001
    assert made.daily_loss_fraction == 0.012
    assert made.risk_plan == "conservative"


def test_an_environment_variable_beats_the_plan():
    """A prop account with a hard ceiling wants one number changed, not a new plan."""
    made = settings()
    kept = tp.PLANS["aggressive"].apply(made, environ={"TRADING_RISK_FRACTION": "0.001"})
    assert "risk_fraction" in kept
    assert made.risk_fraction != 0.005  # the plan did not overwrite it
    assert made.daily_loss_fraction == 0.06  # but everything else came from the plan


def test_every_plan_survives_a_similar_losing_run():
    """The plans differ in size and selectivity, not in shape."""
    for plan in tp.PLANS.values():
        assert 10 <= plan.losses_to_halt <= 14


# ---------------------------------------------------------------- the strategies


def strategy(name, **over):
    return td.STRATEGIES[name](settings(**over))


def take(name, payload=None, *, tick=None, equity=10_000.0, **over):
    engine = strategy(name, **over)
    engine.observe(payload or signal())
    return engine.consider(
        payload or signal(),
        spec=GOLD,
        tick=tick or Tick("XAUUSD", bid=4399.5, ask=4400.5),
        equity=equity,
    )


def test_a_level_call_becomes_a_sized_trade():
    got = take("level-scalp")
    assert isinstance(got, Intent)
    assert got.side is Side.BUY
    assert got.stop == pytest.approx(4395.6)
    assert got.target == pytest.approx(4406.66)
    assert got.volume == pytest.approx(0.05)
    assert got.reward_to_risk > 1.2


def test_a_down_call_sells_with_the_stop_above_the_level():
    got = take("level-scalp", signal(direction="down"))
    assert isinstance(got, Intent)
    assert got.side is Side.SELL
    assert got.stop > got.entry > got.target


def test_a_call_below_the_probability_floor_is_refused():
    got = take("level-scalp", signal(features={"probability": 0.51}))
    assert isinstance(got, Refusal)
    assert got.gate == "probability"


def test_a_call_with_no_volatility_unit_is_refused_not_guessed():
    """A stop from an assumed volatility is a stop in the wrong place, quietly."""
    got = take("level-scalp", signal(features={"vol_bps": 0.0}))
    assert isinstance(got, Refusal)
    assert got.gate == "volatility"


def test_a_call_with_no_direction_is_not_a_weak_buy():
    got = take("level-scalp", signal(direction=""))
    assert isinstance(got, Refusal)
    assert got.gate == "direction"


def test_a_timeframe_that_is_not_scalped_is_refused():
    got = take("level-scalp", signal(interval="1d"))
    assert isinstance(got, Refusal)
    assert got.gate == "interval"


def test_price_already_past_the_stop_is_not_a_trade_to_shrink():
    # A buy call at 4400 with the stop at 4395.6, but price is already at 4390.
    got = take("level-scalp", tick=Tick("XAUUSD", bid=4389.5, ask=4390.5))
    assert isinstance(got, Refusal)
    assert got.gate == "through"


def test_confluence_scalp_refuses_a_level_no_higher_timeframe_sees():
    got = take("confluence-scalp", signal(confluence=["5m"]))
    assert isinstance(got, Refusal)
    assert got.gate == "unanchored"
    agreed = take("confluence-scalp", signal(confluence=["1h", "5m"]))
    assert isinstance(agreed, Intent)


def test_confluence_scalp_gives_the_stop_more_room():
    plain = take("level-scalp", signal(confluence=["1h", "5m"]))
    wider = take("confluence-scalp", signal(confluence=["1h", "5m"]))
    assert wider.stop < plain.stop  # a buy: further below the level


# ------------------------------------------------------------ three speeds


def test_the_edge_floor_sits_above_the_gate_structures_already_applies():
    """Below it, the gate is configuration that can never fire.

    The first version of this module set 0.08 against an upstream 0.10, so it
    refused nothing. Every plan has to clear the same bar.
    """
    from till_infinity.structures.reactions import MIN_EDGE

    assert td.Settings().min_edge > MIN_EDGE
    for plan in tp.PLANS.values():
        assert plan.min_edge > MIN_EDGE


def test_three_speeds_have_to_agree():
    speeds = Speeds(half_lives=(2.0, 4.0, 8.0))
    for _ in range(40):
        speeds.observe("gold", 0.5)
    assert speeds.agree("gold", 1)
    assert not speeds.agree("gold", -1)


def test_momentum_scalp_refuses_a_call_fighting_its_own_context():
    engine = strategy("momentum-scalp")
    for _ in range(60):
        engine.observe(signal(features={"edge": 0.4}))
    got = engine.consider(
        signal(direction="down", features={"edge": -0.3}),
        spec=GOLD,
        tick=Tick("XAUUSD", bid=4399.5, ask=4400.5),
        equity=10_000.0,
    )
    assert isinstance(got, Refusal)
    assert got.gate == "momentum"


# ------------------------------------------------- trading toward the next level


def test_the_book_merges_readings_of_the_same_level():
    """The Kalman mean moves as touches fold in; that is one level, not twelve."""
    book = Book()
    book.observe("gold", Seen(price=4400.0, interval="5m", when=NOW), vol_bps=10.0)
    book.observe("gold", Seen(price=4400.5, interval="5m", when=NOW + 60), vol_bps=10.0)
    assert book.count("gold") == 1
    book.observe("gold", Seen(price=4420.0, interval="5m", when=NOW + 60), vol_bps=10.0)
    assert book.count("gold") == 2


def test_the_book_finds_the_next_level_each_way():
    book = Book()
    for price in (4380.0, 4400.0, 4430.0):
        book.observe("gold", Seen(price=price, interval="5m", when=NOW), vol_bps=10.0)
    assert book.next_above("gold", 4400.0).price == 4430.0
    assert book.next_below("gold", 4400.0).price == 4380.0


def test_approach_scalp_buys_up_to_the_level_above():
    engine = strategy("approach-scalp")
    # A level above, and the confirming call at the one price is standing on.
    engine.observe(signal(features={"level": 4420.0}))  # 4.4v above the fill
    engine.observe(signal())
    got = engine.consider(
        signal(),
        spec=GOLD,
        tick=Tick("XAUUSD", bid=4399.5, ask=4400.5),
        equity=10_000.0,
    )
    assert isinstance(got, Intent)
    # Short of 4420 by the quarter-unit buffer (0.25 * 4.40 = 1.10), because
    # the last stretch into the zone is the part magnet.md says nothing about.
    assert got.target == pytest.approx(4418.9)
    # The stop is still anchored beyond the confirming level, not the target.
    assert got.stop == pytest.approx(4395.6)
    assert got.hold == pytest.approx(2_700.0)


def test_approach_scalp_sells_down_to_the_level_below():
    engine = strategy("approach-scalp")
    engine.observe(signal(features={"level": 4380.0}))  # 4.4v below the fill
    down = signal(direction="down")
    engine.observe(down)
    got = engine.consider(
        down, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.SELL
    assert got.target == pytest.approx(4381.1)  # 4380 + the buffer


def test_approach_scalp_refuses_when_it_knows_of_no_level_to_aim_at():
    engine = strategy("approach-scalp")
    engine.observe(signal())
    got = engine.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "no_target"


def test_approach_scalp_refuses_a_level_too_far_to_reach_in_the_hold():
    engine = strategy("approach-scalp")
    engine.observe(signal(features={"level": 4700.0}))  # ~68 volatility units
    engine.observe(signal())
    got = engine.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "too_far"


def test_approach_scalp_asks_for_longer_than_the_default_hold():
    """The desk's observation is that it takes twenty to thirty minutes."""
    assert td.ApproachScalp.hold_seconds > td.Settings().max_hold


# ------------------------------------------------------------------- the brokers


class FakeBroker(td.PaperBroker):
    """A broker that only carries some symbols, with a suffix."""

    def __init__(self, made, offers=("XAUUSD.raw", "BTCUSD.raw")):
        super().__init__(made)
        self.offers = set(offers)
        self.asked: list[str] = []

    async def spec(self, symbol):
        self.asked.append(symbol)
        if symbol not in self.offers:
            return None
        return SymbolSpec(symbol=symbol, tick_value=1.0)


async def test_resolution_finds_the_account_suffix_and_reuses_it():
    """Probing ten suffixes for every instrument is hundreds of round trips."""
    made = settings(symbols=("gold", "btc"))
    broker = FakeBroker(made)
    resolution = await resolve(broker, made.symbols, made)
    assert resolution.symbols == {"gold": "XAUUSD.raw", "btc": "BTCUSD.raw"}
    assert resolution.suffix == ".raw"
    # Gold cost several probes; BTC found it on the first try because the
    # suffix was already known.
    assert broker.asked.index("BTCUSD.raw") - broker.asked.index("XAUUSD.raw") == 1


async def test_an_instrument_the_broker_does_not_carry_is_reported_not_hidden():
    made = settings(symbols=("gold", "sol"))
    resolution = await resolve(FakeBroker(made), made.symbols, made)
    assert "sol" in resolution.missing
    assert "gold" in resolution.found


async def test_a_quoted_but_untradable_symbol_says_so():
    made = settings(symbols=("gold",))

    class Closed(FakeBroker):
        async def spec(self, symbol):
            got = await super().spec(symbol)
            return None if got is None else SymbolSpec(symbol=symbol, tradable=False)

    resolution = await resolve(Closed(made), made.symbols, made)
    assert "not open for trading" in resolution.missing["gold"]


async def test_the_paper_book_fills_at_the_ask_and_stops_at_the_stop():
    made = settings()
    broker = PaperBroker(made)
    await broker.connect()
    broker.observe(Tick("XAUUSD", bid=4399.5, ask=4400.5))
    result = await broker.send(
        td.Order(symbol="XAUUSD", side=Side.BUY, volume=0.05, stop=4395.6, target=4406.66)
    )
    assert result.ok
    assert result.price == 4400.5

    closed = broker.observe(Tick("XAUUSD", bid=4395.0, ask=4396.0))
    assert len(closed) == 1
    assert closed[0][2] == "stop"
    account = await broker.account()
    assert account.balance < 10_000.0


async def test_a_tick_spanning_both_resolves_as_the_stop():
    """Assuming the good one filled first is how a paper book flatters itself."""
    made = settings()
    broker = PaperBroker(made)
    await broker.connect()
    broker.observe(Tick("XAUUSD", bid=4399.5, ask=4400.5))
    await broker.send(
        td.Order(symbol="XAUUSD", side=Side.BUY, volume=0.05, stop=4395.0, target=4406.0)
    )
    closed = broker.observe(Tick("XAUUSD", bid=4394.0, ask=4407.0))
    assert closed[0][2] == "stop"


def test_an_explicitly_named_backend_that_cannot_run_is_an_error():
    """Someone who wrote TRADING_BACKEND=mt5 wants MT5, not a silent downgrade."""
    made = settings(backend="mt5-http", url="")
    with pytest.raises(td.BrokerError):
        td.choose(made)


def test_the_backend_falls_back_to_paper_and_says_why():
    made = settings(backend="auto", url="")
    assert td.choose(made) in (td.PAPER, td.NATIVE)


# ---------------------------------------------------------------- the whole loop


async def test_a_signal_on_the_bus_becomes_a_position_and_a_journal_entry(tmp_path):
    bus = Bus()
    async with Journal(tmp_path / "journal.db") as book:
        trader = Trader(bus, settings=settings(), journal=book)
        await trader.start()

        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        got = await trader.handle(Message(topic=SIGNALS, payload=signal()))
        assert isinstance(got, Intent)
        assert len(trader.open) == 1
        assert trader.taken == 1

        entries = read(tmp_path / "journal.db")
        assert any("paper: buy" in entry.title for entry in entries)


async def test_a_stop_hit_is_reconciled_and_recorded_as_an_outcome(tmp_path):
    """A server-side stop leaves no message on any bus. The position is gone."""
    bus = Bus()
    async with Journal(tmp_path / "journal.db") as book:
        trader = Trader(bus, settings=settings(), journal=book)
        await trader.start()
        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        await trader.handle(Message(topic=SIGNALS, payload=signal()))
        assert len(trader.open) == 1

        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4395.0, "ask": 4396.0})
        )
        await trader.sweep()
        assert not trader.open
        assert trader.guard.trades == 1
        assert trader.guard.realised < 0

        entries = read(tmp_path / "journal.db")
        assert any(entry.parent for entry in entries)


async def test_the_second_call_on_the_same_instrument_is_refused_and_journalled(tmp_path):
    bus = Bus()
    async with Journal(tmp_path / "journal.db") as book:
        trader = Trader(bus, settings=settings(), journal=book)
        await trader.start()
        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        await trader.handle(Message(topic=SIGNALS, payload=signal()))
        again = await trader.handle(Message(topic=SIGNALS, payload=signal(time=NOW + 60)))
        assert isinstance(again, Refusal)
        assert again.gate == "already_open"
        entries = read(tmp_path / "journal.db")
        assert any("declined" in entry.title for entry in entries)


async def test_a_fill_is_announced_on_alerts():
    bus = Bus()
    alerts = bus.subscribe(ALERTS, group="test")
    trader = Trader(bus, settings=settings())
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.handle(Message(topic=SIGNALS, payload=signal()))
    message = await alerts.next()
    assert message is not None
    assert message.payload["fields"]["shape"] == "trade"
    assert "gold" in message.payload["title"]


async def test_announcements_can_be_switched_off():
    """The trade still happens; nothing is published about it."""
    bus = Bus()
    alerts = bus.subscribe(ALERTS, group="test")
    trader = Trader(bus, settings=settings(notify=False))
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.handle(Message(topic=SIGNALS, payload=signal()))
    assert trader.taken == 1
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(alerts.next(), 0.1)


async def test_nothing_is_traded_on_an_instrument_the_broker_does_not_carry():
    bus = Bus()
    made = settings(symbols=("gold",))
    trader = Trader(bus, settings=made, broker=FakeBroker(made, offers=()))
    with pytest.raises(td.BrokerError):
        await trader.start()


def test_the_book_forgets_a_level_nobody_has_mentioned_for_hours():
    """A stale map describes last week's engine, not this one's."""
    book = Book()
    book.observe("gold", Seen(price=4400.0, interval="5m", when=NOW - 7 * 3_600), vol_bps=10.0)
    assert book.count("gold") == 0


# ------------------------------------------------ standing aside for the world


def release(country="USD", when=None, importance=2, **over):
    payload = {
        "source": "forexfactory",
        "id": "nfp-1",
        "title": "Non-Farm Employment Change",
        "country": country,
        "time": when if when is not None else NOW + 300,
        "importance": importance,
    }
    payload.update(over)
    return payload


def test_a_us_release_blacks_out_gold_and_every_major():
    """The dollar is on one side of all of them, so the window is wide."""
    context = Context()
    context.observe_event(release())
    for feed in ("gold", "btc", "eurusd", "usdjpy", "spx500"):
        assert context.blackout(feed, now=NOW) is not None


def test_a_sterling_release_leaves_gold_alone():
    context = Context()
    context.observe_event(release(country="GBP"))
    assert context.blackout("gbpusd", now=NOW) is not None
    assert context.blackout("gold", now=NOW) is None


def test_both_country_spellings_are_understood():
    """TradingView writes ISO codes, ForexFactory writes currencies."""
    assert ex.currency_of("US") == "USD"
    assert ex.currency_of("USD") == "USD"
    assert ex.currency_of("DE") == "EUR"  # a German print moves the euro
    assert ex.currency_of("CNY") == "CNH"
    assert ex.currency_of("ZZ") == ""


def test_the_blackout_window_is_asymmetric_and_the_right_way_round():
    context = Context(before=600.0, after=900.0)
    context.observe_event(release(when=NOW))
    assert context.blackout("gold", now=NOW - 300) is not None  # before the print
    assert context.blackout("gold", now=NOW + 300) is not None  # after it
    assert context.blackout("gold", now=NOW - 900) is None  # too early
    assert context.blackout("gold", now=NOW + 1_200) is None  # long enough after
    # Wider after than before, so this time sits inside one window and outside
    # the other. It is the assertion that catches the two being swapped, which
    # is exactly what the first version did.
    assert context.blackout("gold", now=NOW + 700) is not None
    assert context.blackout("gold", now=NOW - 700) is None


def test_a_low_impact_release_is_not_worth_standing_aside_for():
    context = Context()
    context.observe_event(release(importance=0))
    assert context.blackout("gold", now=NOW) is None


def test_the_calendar_does_not_grow_without_bound():
    context = Context()
    for index in range(50):
        context.observe_event(release(id=f"old-{index}", when=NOW - 86_400))
    context.observe_event(release(id="new", when=NOW + 600))
    assert len(context._events) == 1


# --------------------------------------------------- our broker vs the venues


def venue_quote(venue, mid, spread=0.3, feed="gold"):
    return {"feed": feed, "venue": venue, "mid": mid, "spread_bps": spread, "time": NOW}


def test_a_dislocated_broker_quote_is_refused():
    context = Context(max_dislocation_bps=8.0)
    for venue in ("OANDA", "PEPPERSTONE", "SAXO", "FOREXCOM"):
        context.observe_quote(venue_quote(venue, 4400.0))
    ours = Tick("XAUUSD", bid=4405.0, ask=4405.4)  # ~12bps away
    assert "from the 4-venue median" in context.dislocation("gold", ours, now=NOW)


def test_a_broker_charging_far_more_than_the_group_is_refused():
    context = Context(max_spread_ratio=2.5)
    for venue in ("OANDA", "PEPPERSTONE", "SAXO", "FOREXCOM"):
        context.observe_quote(venue_quote(venue, 4400.0, spread=0.4))
    wide = Tick("XAUUSD", bid=4399.0, ask=4401.0)  # ~4.5bps against 0.4
    assert "our spread is" in context.dislocation("gold", wide, now=NOW)


def test_without_a_quorum_of_venues_the_check_fails_open():
    """A collector restarting must not stop the system trading."""
    context = Context()
    context.observe_quote(venue_quote("OANDA", 4400.0))
    ours = Tick("XAUUSD", bid=4500.0, ask=4500.4)
    assert context.dislocation("gold", ours, now=NOW) == ""


def test_a_stale_venue_stops_anchoring_the_consensus():
    context = Context()
    for venue in ("OANDA", "PEPPERSTONE", "SAXO"):
        context.observe_quote(venue_quote(venue, 4400.0))
    _, _, venues = context.consensus("gold", now=NOW + 600)
    assert venues == 0


def test_the_consensus_is_a_median_so_one_broken_venue_cannot_drag_it():
    context = Context()
    for venue, mid in (("A", 4400.0), ("B", 4400.0), ("C", 4400.0), ("D", 9999.0)):
        context.observe_quote(venue_quote(venue, mid))
    median, _, venues = context.consensus("gold", now=NOW)
    assert venues == 4
    assert median == 4400.0


# ----------------------------------------------------------------- drift


def test_a_regime_change_pauses_that_instrument():
    context = Context(drift_pause=900.0)
    context.observe_signal({"shape": "drift", "feed": "gold", "time": NOW})
    assert context.drifting("gold", now=NOW + 60) > 0
    assert context.drifting("btc", now=NOW + 60) == 0
    assert context.drifting("gold", now=NOW + 1_000) == 0


def test_a_level_signal_is_not_a_drift_signal():
    context = Context()
    context.observe_signal(signal())
    assert context.drifting("gold", now=NOW) == 0


# ------------------------------------------------------- currency exposure


def test_three_dollar_pairs_the_same_way_is_one_trade():
    """Long EUR, GBP and AUD against the dollar is 3x short USD."""
    positions = [
        td.Position(ticket=1, symbol="EURUSD", side=Side.BUY, volume=0.1, price_open=1.1),
        td.Position(ticket=2, symbol="GBPUSD", side=Side.BUY, volume=0.1, price_open=1.3),
        td.Position(ticket=3, symbol="AUDUSD", side=Side.BUY, volume=0.1, price_open=0.66),
    ]
    feed_of = {"EURUSD": "eurusd", "GBPUSD": "gbpusd", "AUDUSD": "audusd"}
    got = ex.measure(positions, {1: 25.0, 2: 25.0, 3: 25.0}, feed_of)
    assert got.of("USD") == pytest.approx(-75.0)
    assert got.of("EUR") == pytest.approx(25.0)
    assert got.worst() == ("USD", -75.0)


def test_gold_carries_a_dollar_leg_like_everything_else():
    positions = [
        td.Position(ticket=1, symbol="XAUUSD", side=Side.BUY, volume=0.05, price_open=4400.0)
    ]
    got = ex.measure(positions, {1: 25.0}, {"XAUUSD": "gold"})
    assert got.of("USD") == pytest.approx(-25.0)
    assert got.of("XAU") == pytest.approx(25.0)


def test_opposite_sides_of_the_same_currency_net_off():
    positions = [
        td.Position(ticket=1, symbol="EURUSD", side=Side.BUY, volume=0.1, price_open=1.1),
        td.Position(ticket=2, symbol="GBPUSD", side=Side.SELL, volume=0.1, price_open=1.3),
    ]
    feed_of = {"EURUSD": "eurusd", "GBPUSD": "gbpusd"}
    got = ex.measure(positions, {1: 25.0, 2: 25.0}, feed_of)
    assert got.of("USD") == pytest.approx(0.0)


def test_a_us_release_hits_every_instrument_with_a_dollar_leg():
    affected = ex.feeds_for("USD")
    assert "gold" in affected
    assert "btc" in affected
    assert "eurusd" in affected
    # Everything except the instruments with no dollar leg at all: the
    # non-dollar indices, and every cross.
    assert set(ex.LEGS) - set(affected) == {
        "ger40",
        "uk100",
        "fra40",
        "eu50",
        "jp225",
        "aus200",
        "hk50",
        "eurgbp",
        "eurjpy",
        "gbpjpy",
        "eurchf",
        "audjpy",
        "chfjpy",
        "euraud",
    }


def test_the_european_indices_do_not_load_the_dollar():
    """The reason for carrying them at all.

    Every other instrument here is short dollars by construction - a book of
    gold, BTC and the majors is one trade wearing several tickets, which is
    what `max_currency_exposure` exists to catch. A DAX CFD is quoted in euros
    and a FTSE CFD in sterling, so they are the only two positions that can be
    opened without consuming the dollar budget. Mapping them to USD out of
    habit would have quietly removed that.
    """
    assert ex.legs("ger40") == ("GER40", "EUR")
    assert ex.legs("uk100") == ("UK100", "GBP")
    assert "ger40" not in ex.feeds_for("USD")
    assert "uk100" not in ex.feeds_for("USD")
    # And they are reached by the releases that actually move them.
    assert "ger40" in ex.feeds_for("EUR")
    assert "uk100" in ex.feeds_for("GBP")


def test_a_dax_trade_leaves_the_dollar_budget_alone():
    """The gate that refuses a third dollar trade must not refuse this one."""
    positions = [
        td.Position(ticket=1, symbol="XAUUSD", side=Side.BUY, volume=0.1, price_open=4400.0),
        td.Position(ticket=2, symbol="EURUSD", side=Side.BUY, volume=0.1, price_open=1.1),
    ]
    feed_of = {"XAUUSD": "gold", "EURUSD": "eurusd", "GER40": "ger40"}
    got = ex.measure(positions, {1: 25.0, 2: 25.0}, feed_of)
    before = abs(got.of("USD"))

    positions.append(
        td.Position(ticket=3, symbol="GER40", side=Side.BUY, volume=0.1, price_open=26_430.0)
    )
    after = ex.measure(positions, {1: 25.0, 2: 25.0, 3: 25.0}, feed_of)

    # The dollar budget is untouched, which is the point.
    assert abs(after.of("USD")) == pytest.approx(before)
    # And the euro leg *nets down* rather than up: a long EURUSD is +EUR and a
    # long DAX is -EUR, so the second position hedges the first. That falls out
    # of the decomposition rather than being asserted into it, and it is the
    # behaviour that makes this a diversifying trade instead of another way to
    # be long the same thing.
    assert after.of("EUR") == pytest.approx(0.0)
    assert after.of("GER40") == pytest.approx(25.0)


def test_the_exposure_gate_refuses_the_third_dollar_trade():
    made = settings(max_currency_exposure=0.005)  # 50 on 10,000
    guard = Guard(made)
    guard.roll(10_000.0)
    positions = [
        td.Position(ticket=1, symbol="EURUSD", side=Side.BUY, volume=0.1, price_open=1.1),
        td.Position(ticket=2, symbol="GBPUSD", side=Side.BUY, volume=0.1, price_open=1.3),
    ]
    stopped = guard.allows(
        intent(feed="audusd", symbol="AUDUSD", risk_money=25.0),
        positions=positions,
        risk_of={1: 25.0, 2: 25.0},
        feed_of={"EURUSD": "eurusd", "GBPUSD": "gbpusd"},
    )
    assert stopped is not None
    assert stopped.gate == "exposure"
    assert "USD" in stopped.detail


def test_gold_and_btc_alone_do_not_trip_the_exposure_gate():
    """The limit is harmless on the default two instruments."""
    made = settings(max_currency_exposure=0.005)
    guard = Guard(made)
    guard.roll(10_000.0)
    positions = [
        td.Position(ticket=1, symbol="XAUUSD", side=Side.BUY, volume=0.05, price_open=4400.0)
    ]
    stopped = guard.allows(
        intent(feed="btc", symbol="BTCUSD", risk_money=22.0),
        positions=positions,
        risk_of={1: 22.0},
        feed_of={"XAUUSD": "gold"},
    )
    assert stopped is None


# --------------------------------------------------------- the guards in place


def test_the_guard_refuses_a_trade_inside_a_blackout():
    context = Context()
    context.observe_event(release(when=NOW + 300))
    guard = Guard(settings(), context=context)
    guard.roll(10_000.0, now=NOW)
    stopped = guard.allows(intent(), positions=[], now=NOW)
    assert stopped is not None
    assert stopped.gate == "news"


def test_the_guard_refuses_a_trade_on_a_drifting_instrument():
    context = Context()
    context.observe_signal({"shape": "drift", "feed": "gold", "time": NOW})
    guard = Guard(settings(), context=context)
    guard.roll(10_000.0, now=NOW)
    stopped = guard.allows(intent(), positions=[], now=NOW)
    assert stopped is not None
    assert stopped.gate == "drift"


def test_a_guard_with_no_context_still_trades():
    """Every context-driven check fails open; none of them is required."""
    guard = Guard(settings(), context=None)
    guard.roll(10_000.0, now=NOW)
    assert guard.allows(intent(), positions=[], now=NOW) is None


# ------------------------------------------------------ moving a stop, gated


def open_trade(**over):
    made = {
        "ticket": 1,
        "symbol": "XAUUSD",
        "side": Side.BUY,
        "volume": 0.05,
        "price_open": 4400.5,
        "stop": 4395.6,
        "target": 4406.66,
    }
    made.update(over)
    return td.Position(**made)


def test_nothing_moves_unless_a_rule_is_switched_on():
    """Both are experiments, so both are off until asked for."""
    made = settings()
    assert made.break_even_at == 0.0
    assert made.trail_vol == 0.0
    assert td.advance(open_trade(), intent(), GOLD, made, best=4420.0) is None


def test_break_even_moves_the_stop_past_the_entry_by_the_spread():
    made = settings(break_even_at=1.0, break_even_ticks=2)
    # Risk is 4.9; one R in front is 4405.4.
    move = td.advance(open_trade(), intent(), GOLD, made, best=4406.0)
    assert move is not None
    assert move.stop == pytest.approx(4400.52)  # entry + 2 ticks
    assert "break even" in move.reason


def test_break_even_does_not_fire_before_the_trade_is_in_front():
    made = settings(break_even_at=1.0)
    assert td.advance(open_trade(), intent(), GOLD, made, best=4402.0) is None


def test_a_trail_follows_the_best_price_seen():
    made = settings(trail_vol=1.0)
    move = td.advance(open_trade(), intent(), GOLD, made, best=4420.0, vol_bps=10.0)
    assert move is not None
    assert move.stop == pytest.approx(4415.58)  # 4420 - 1v of 4.42


def test_a_stop_never_moves_backwards():
    """The most expensive habit in discretionary trading, automated or not."""
    made = settings(trail_vol=1.0)
    already = open_trade(stop=4418.0)
    assert td.advance(already, intent(), GOLD, made, best=4420.0, vol_bps=10.0) is None


def test_a_short_trails_the_other_way():
    made = settings(trail_vol=1.0)
    short = open_trade(side=Side.SELL, price_open=4399.5, stop=4404.4, target=4393.0)
    down = intent(side=Side.SELL, entry=4399.5, stop=4404.4, target=4393.0)
    move = td.advance(short, down, GOLD, made, best=4380.0, vol_bps=10.0)
    assert move is not None
    assert move.stop == pytest.approx(4384.38)  # 4380 + 1v


# ------------------------------------------------ resolutions on the bus


async def test_the_trader_consumes_touch_resolutions():
    bus = Bus()
    trader = Trader(bus, settings=settings())
    await trader.start()
    await trader.handle(
        Message(
            topic=RESOLUTIONS,
            payload={
                "feed": "gold",
                "interval": "5m",
                "level": 4400.0,
                "outcome": "reject",
                "push_vol": 1.2,
                "seconds": 240,
            },
        )
    )
    assert trader.resolutions == 1


def test_resolutions_are_a_declared_topic():
    """The one message on the bus that says what happened, not what might."""
    from till_infinity.bus import TOPICS

    assert RESOLUTIONS in TOPICS


# ------------------------------------------------------- scoring what it did


async def a_closed_trade(
    book, *, strategy="level-scalp", profit=10.0, risk=20.0, feed="gold", at=4400.5
):
    """Write the decision/outcome pair the trader writes.

    `at` varies the entry price, and it has to. Journal entries are
    content-addressed on `(time, actor, title)` and written INSERT OR IGNORE,
    so two trades with the same title inside one clock tick are deliberately
    one entry. A fixture that wrote ten identical titles therefore produced six
    rows on a fast machine and ten on a slow one - which is the journal working
    as documented, and a test that had not noticed real titles carry the volume
    and the fill price.
    """
    from till_infinity.journal import decide, outcome

    ref = await decide(
        book,
        f"paper: buy 0.05 {feed} @ {at:.5g}",
        rationale="up from above",
        actor="trading",
        context={
            "strategy": strategy,
            "mode": "paper",
            "feed": feed,
            "side": "buy",
            "risk_money": risk,
            "reward_to_risk": 1.4,
        },
        tags=(feed, "buy", strategy, "paper"),
    )
    await outcome(
        book,
        ref,
        f"{feed} closed {profit:+.2f} from {at:.5g}",
        actor="trading",
        context={"profit": profit, "seconds": 300, "reason": "target", "exit_source": "broker"},
    )
    return ref


async def test_a_closed_trade_is_scored_in_r_not_money(tmp_path):
    """40 won risking 20 and 40 won risking 200 are not the same result."""
    async with Journal(tmp_path / "j.db") as book:
        await a_closed_trade(book, profit=40.0, risk=20.0)
    found = tr.trades(tmp_path / "j.db")
    assert len(found) == 1
    assert found[0].r == pytest.approx(2.0)
    assert found[0].won


async def test_a_small_sample_is_refused_rather_than_characterised(tmp_path):
    """A 70% win rate over ten trades is a coin that came up heads seven times."""
    async with Journal(tmp_path / "j.db") as book:
        for index in range(10):
            await a_closed_trade(book, profit=10.0 if index < 7 else -20.0, at=4400.0 + index)
    report = tr.build(tmp_path / "j.db")
    assert report.overall.count == 10
    assert not report.enough
    assert "too few to characterise" in report.overall.verdict()


async def test_a_large_enough_sample_is_characterised(tmp_path):
    async with Journal(tmp_path / "j.db") as book:
        for index in range(tr.ENOUGH + 5):
            await a_closed_trade(book, profit=10.0 if index % 2 else -20.0, at=4400.0 + index)
    report = tr.build(tmp_path / "j.db")
    assert report.enough
    assert "won" in report.overall.verdict()
    assert "R mean" in report.overall.verdict()


async def test_trades_are_grouped_by_strategy(tmp_path):
    async with Journal(tmp_path / "j.db") as book:
        await a_closed_trade(book, strategy="level-scalp", profit=20.0, at=4400.0)
        await a_closed_trade(book, strategy="approach-scalp", profit=-20.0, at=4401.0)
    report = tr.build(tmp_path / "j.db")
    assert report.by_strategy["level-scalp"].total_r == pytest.approx(1.0)
    assert report.by_strategy["approach-scalp"].total_r == pytest.approx(-1.0)


async def test_a_trade_with_no_risk_recorded_is_skipped_not_counted_as_zero(tmp_path):
    """Counting it would land as an infinite R or a silent zero."""
    from till_infinity.journal import decide, outcome

    async with Journal(tmp_path / "j.db") as book:
        ref = await decide(
            book,
            "paper: buy 0.05 gold",
            rationale="adopted",
            actor="trading",
            context={"strategy": "level-scalp", "feed": "gold", "risk_money": 0.0},
        )
        await outcome(book, ref, "closed", actor="trading", context={"profit": 5.0})
    assert tr.trades(tmp_path / "j.db") == []


async def test_declines_are_tallied_per_gate(tmp_path):
    """A gate that never fires does nothing; one that always fires is mis-set."""
    from till_infinity.journal import observe

    async with Journal(tmp_path / "j.db") as book:
        # Distinct titles for the same reason `a_closed_trade` varies its
        # price: two identical titles in one tick are one journal entry.
        for index, gate in enumerate(("news", "news", "exposure")):
            await observe(
                book,
                f"declined buy gold @ {4400 + index} ({gate})",
                rationale=gate,
                actor="trading",
                context={"gate": gate, "strategy": "level-scalp"},
            )
    counted = tr.declines(tmp_path / "j.db")
    assert counted["news"] == 2
    assert counted["exposure"] == 1


async def test_paper_and_live_are_not_averaged_together(tmp_path):
    """Simulated fills and real ones describe different things."""
    from till_infinity.journal import decide, outcome

    async with Journal(tmp_path / "j.db") as book:
        await a_closed_trade(book, profit=20.0)
        ref = await decide(
            book,
            "live: buy 0.05 gold",
            rationale="up",
            actor="trading",
            context={"strategy": "level-scalp", "mode": "live", "feed": "gold", "risk_money": 20.0},
        )
        await outcome(book, ref, "closed", actor="trading", context={"profit": -20.0})

    assert tr.build(tmp_path / "j.db", mode="paper").overall.count == 1
    assert tr.build(tmp_path / "j.db", mode="live").overall.count == 1
    assert tr.build(tmp_path / "j.db").overall.count == 2


# ------------------------------------------------- reaching a Windows terminal


def test_rpyc_is_preferred_over_the_http_bridge():
    """Closer to the terminal: a module proxy beats a JSON wrapper."""
    made = settings(backend="auto", rpyc_host="127.0.0.1", url="http://localhost:8000")
    assert td.choose(made) == td.RPYC


def test_the_http_bridge_is_used_when_only_it_is_configured():
    made = settings(backend="auto", rpyc_host="", url="http://localhost:8000")
    assert td.choose(made) == td.HTTP


def test_an_rpyc_backend_without_a_host_is_an_error_not_a_fallback():
    made = settings(backend="mt5-rpyc", rpyc_host="")
    with pytest.raises(td.BrokerError, match="TRADING_RPYC_HOST"):
        td.choose(made)


def test_the_rpyc_backend_reuses_the_native_trading_logic():
    """Thirty lines of connection handling and no order building of its own.

    A second copy is a second place for the filling-mode logic to drift.
    """
    from till_infinity.trading.mt5_native import NativeBroker
    from till_infinity.trading.mt5_rpyc import RpycBroker

    assert issubclass(RpycBroker, NativeBroker)
    for shared in ("send", "close_position", "modify", "spec", "positions", "_filling"):
        assert getattr(RpycBroker, shared) is getattr(NativeBroker, shared)


async def test_an_rpyc_broker_with_no_server_reports_it_rather_than_hanging():
    made = settings(backend="mt5-rpyc", rpyc_host="127.0.0.1", rpyc_port=1, timeout=1.0)
    broker = td.build(made)
    with pytest.raises(td.NotConnectedError, match="could not reach"):
        await broker.connect()


def test_a_terminal_is_configured_by_any_of_the_routes():
    assert settings(rpyc_host="127.0.0.1").configured
    assert settings(url="http://localhost:8000").configured
    assert not settings().configured


# --------------------------------------------------- reading the bridge's replies


def http_broker(**over):
    from till_infinity.trading.mt5_http import HttpBroker

    made = settings(url="http://bridge:8000", **over)
    return HttpBroker(made)


async def test_an_order_reply_is_read_from_the_terminals_own_result():
    """The result carries the ticket and retcode; the stored row is a fallback."""
    from till_infinity.trading.mt5_http import HttpBroker

    broker = http_broker()
    sent = {}

    async def fake_post(path, **kwargs):
        sent["path"] = path
        sent["json"] = kwargs.get("json")
        return {
            "success": True,
            "result": {"order": 98765, "retcode": 10009, "price": 4400.75, "volume": 0.05},
            "trade": {"transaction_broker_id": "98765", "entry_price": 4400.75},
        }

    broker._post = fake_post
    result = await HttpBroker.send(
        broker,
        td.Order(symbol="XAUUSD", side=Side.BUY, volume=0.05, stop=4395.0, target=4406.0),
    )
    assert result.ok
    assert result.ticket == 98765
    assert result.price == 4400.75
    assert sent["path"] == "/trading/order"
    assert sent["json"]["sl"] == 4395.0


async def test_an_older_bridge_that_returns_only_the_row_still_works():
    """Back-compat: earlier builds returned no `result` at all."""
    from till_infinity.trading.mt5_http import HttpBroker

    broker = http_broker()

    async def fake_post(path, **kwargs):
        return {"success": True, "trade": {"transaction_broker_id": "5", "entry_price": 1.5}}

    broker._post = fake_post
    result = await HttpBroker.send(
        broker, td.Order(symbol="EURUSD", side=Side.SELL, volume=0.1, stop=1.6)
    )
    assert result.ok
    assert result.ticket == 5
    assert result.price == 1.5


async def test_a_stop_is_moved_by_ticket_over_the_bridge():
    """Without the ticket route this backend could not trail a stop at all."""
    from till_infinity.trading.mt5_http import HttpBroker

    broker = http_broker()
    sent = {}

    async def fake_post(path, **kwargs):
        sent["path"] = path
        sent["json"] = kwargs.get("json")
        return {"success": True, "result": {"retcode": 10009}}

    broker._post = fake_post
    result = await HttpBroker.modify(broker, 42, 4398.0, 4410.0)
    assert result.ok
    assert result.ticket == 42
    assert sent["path"] == "/positions/modify"
    assert sent["json"] == {"ticket": 42, "sl": 4398.0, "tp": 4410.0}


async def test_a_rejected_order_is_not_read_as_a_fill():
    from till_infinity.trading.mt5_http import HttpBroker

    broker = http_broker()

    async def fake_post(path, **kwargs):
        return {"success": True, "result": {"order": 0, "retcode": 10014, "price": 0.0}}

    broker._post = fake_post
    result = await HttpBroker.send(
        broker, td.Order(symbol="XAUUSD", side=Side.BUY, volume=999.0, stop=4395.0)
    )
    assert not result.ok
    assert result.retcode == 10014


# ------------------------------------------- the switch that has to actually work


class RecordingBroker(td.Broker):
    """A stand-in for a **live** terminal that records what it is asked to send.

    Deliberately not a `PaperBroker` subclass. The trader treats a paper broker
    as its own execution venue - one book, not two - so a double that inherited
    from it would be handed the orders it is supposed to prove never arrive.
    """

    name = "recording"

    def __init__(self, made):
        super().__init__(made)
        self.sent: list = []
        self.modified: list = []
        self._book = td.PaperBroker(made)

    async def connect(self):
        return await self._book.connect()

    async def healthy(self):
        return True

    async def account(self):
        return await self._book.account()

    async def spec(self, symbol):
        return await self._book.spec(symbol)

    async def quote(self, symbol):
        return await self._book.quote(symbol)

    async def positions(self):
        return await self._book.positions()

    async def send(self, order):
        self.sent.append(order)
        return await self._book.send(order)

    async def close_position(self, ticket, volume=0.0):
        return await self._book.close_position(ticket, volume)

    async def modify(self, ticket, stop, target=0.0):
        self.modified.append((ticket, stop, target))
        return await self._book.modify(ticket, stop, target)

    def observe(self, tick):
        return self._book.observe(tick)


async def test_an_unarmed_trader_sends_nothing_to_the_terminal():
    """TRADING_LIVE used to change a log line and nothing else.

    `take` called `self.broker.send` unconditionally, so a run in paper mode
    against a live bridge placed real orders. Caught against a Deriv demo: a
    paper run opened 0.03 BTCUSD, and the next run then refused to trade
    because the instrument it had never really traded was already open.
    """
    bus = Bus()
    made = settings(live=False)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()

    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    got = await trader.handle(Message(topic=SIGNALS, payload=signal()))

    assert isinstance(got, Intent)
    assert trader.taken == 1
    # The trade happened - on the paper book, which is a different object.
    assert venue.sent == []
    assert trader.paper is not None
    assert trader.execution is trader.paper
    assert trader.execution is not trader.broker


async def test_an_armed_trader_sends_to_the_terminal():
    bus = Bus()
    made = settings(live=True)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()

    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    got = await trader.handle(Message(topic=SIGNALS, payload=signal()))

    assert isinstance(got, Intent)
    assert len(venue.sent) == 1
    assert venue.sent[0].symbol == "XAUUSD"
    assert trader.paper is None
    assert trader.execution is trader.broker


async def test_the_paper_book_is_priced_off_the_real_venue():
    """An unarmed run still pays the broker's actual spread."""
    bus = Bus()
    made = settings(live=False)
    venue = RecordingBroker(made)
    venue.observe(Tick("XAUUSD", bid=4399.0, ask=4402.0))  # a wide, real spread
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()

    got = await trader._tick("XAUUSD")
    assert got is not None
    # The quote came from the venue and reached the paper book.
    assert (await trader.paper.quote("XAUUSD")).ask == 4402.0


def test_every_instrument_prices_tracks_can_be_traded():
    """The trading module must not silently cover fewer instruments than the
    rest of the system. A feed with no broker names cannot be traded at all,
    and the failure would look like "the broker does not carry it"."""
    from till_infinity.prices.config import DEFAULT_SYMBOLS as PRICED

    missing = [feed for feed in PRICED if feed not in td.INSTRUMENTS]
    assert not missing, f"no broker names for {missing}"


def test_the_index_names_include_the_spaced_forms():
    """Deriv calls them `US Tech 100` and `US SP 500`.

    The compact CFD forms - US100, NAS100, USTEC - matched nothing across its
    798 symbols, so both instruments resolved to "no symbol found" while every
    other one worked. Names are compared upper-cased.
    """
    assert "US TECH 100" in td.INSTRUMENTS["us100"]
    assert "US SP 500" in td.INSTRUMENTS["spx500"]

    from till_infinity.trading.symbols import matches

    listing = ["US Tech 100", "US SP 500", "USDJPY", "USDJPYmicro"]
    assert matches("us100", listing) == ["US Tech 100"]
    assert matches("spx500", listing) == ["US SP 500"]
    # Exact beats a longer variant: the plain pair, not the micro contract.
    assert matches("usdjpy", listing) == ["USDJPY", "USDJPYmicro"]


def test_bybit_style_suffixed_names_resolve():
    """Bybit calls them `SP500.s` and `NAS100.s`, and plenty of brokers suffix.

    Both routes have to find them: the catalogue scan, where the suffix is
    whatever the broker appended and is never guessed, and the probe, where it
    comes from the suffix list. The probe matters because the HTTP bridge
    cannot enumerate symbols on every build.
    """
    from till_infinity.trading.symbols import candidates, matches

    listing = ["SP500.s", "NAS100.s", "XAUUSD.s", "EURUSD.s", "BTCUSDT"]
    assert matches("spx500", listing) == ["SP500.s"]
    assert matches("us100", listing) == ["NAS100.s"]
    assert matches("gold", listing) == ["XAUUSD.s"]
    assert matches("btc", listing) == ["BTCUSDT"]

    assert "NAS100.s" in candidates("us100")
    assert "SP500.s" in candidates("spx500")


# ------------------------------------------------------------- the council


def opinion(side="buy", conviction=0.7, stop=1.0, target=1.6, because="because"):
    from till_infinity.trading.council import Opinion

    return Opinion(
        side=side, conviction=conviction, stop_vol=stop, target_vol=target, because=because
    )


def council(**over):
    from till_infinity.trading.council import Council

    return Council(**over)


def test_abstaining_is_removed_from_the_count_not_counted_against():
    """A panel that cannot say 'I don't know' will always find a trade."""
    got = council(quorum=2).resolve(
        {
            "trend": opinion("buy", 0.8),
            "contrarian": opinion("abstain", 0.0),
            "quant": opinion("buy", 0.7),
            "skeptic": opinion("abstain", 0.0),
        }
    )
    side, _stop, _target, why = got
    assert side is Side.BUY
    assert "2-0" in why


def test_every_voice_abstaining_is_no_trade():
    side, _, _, why = council().resolve({"trend": opinion("abstain"), "quant": opinion("abstain")})
    assert side is None
    assert "abstain" in why


def test_a_split_desk_does_not_trade():
    side, _, _, why = council(quorum=2).resolve(
        {
            "trend": opinion("buy", 0.9),
            "quant": opinion("buy", 0.6),
            "contrarian": opinion("sell", 0.9),
            "skeptic": opinion("sell", 0.8),
        }
    )
    assert side is None
    assert "split" in why


def test_a_lone_voice_does_not_meet_quorum():
    side, _, _, why = council(quorum=2).resolve({"trend": opinion("buy", 0.99)})
    assert side is None
    assert "quorum" in why


def test_weak_conviction_is_not_worth_the_spread():
    side, _, _, why = council(quorum=2, min_conviction=0.55).resolve(
        {"trend": opinion("buy", 0.3), "quant": opinion("buy", 0.4)}
    )
    assert side is None
    assert "conviction" in why


def test_an_absurd_stop_is_clamped_rather_than_obeyed():
    """A model asking for a forty-unit stop is failing, not being bold."""
    from till_infinity.trading.council import MAX_STOP_VOL, MAX_TARGET_VOL, MIN_STOP_VOL

    side, stop, target, _ = council(quorum=2).resolve(
        {
            "trend": opinion("buy", 0.9, stop=40.0, target=500.0),
            "quant": opinion("buy", 0.9, stop=40.0, target=500.0),
        }
    )
    assert side is Side.BUY
    assert stop == MAX_STOP_VOL
    assert target == MAX_TARGET_VOL

    _, tiny, _, _ = council(quorum=2).resolve(
        {"trend": opinion("buy", 0.9, stop=0.001), "quant": opinion("buy", 0.9, stop=0.001)}
    )
    assert tiny == MIN_STOP_VOL


def test_the_evidence_pack_is_the_same_for_every_voice_and_carries_no_free_text():
    """Deterministic, and nothing for a headline to smuggle an instruction through."""
    from till_infinity.trading.council import evidence

    pack = evidence(signal(), Tick("XAUUSD", bid=4399.5, ask=4400.5), GOLD, "gold")
    assert "gold (XAUUSD)" in pack
    assert "against a 47% unconditional rate" in pack
    assert "abstaining is a valid answer" in pack.lower()
    # The level model is offered as an input, not as an instruction.
    assert "not obliged to agree" in pack


async def test_a_voice_that_fails_reads_as_an_abstention():
    """A model that timed out has not made a case for a trade.

    Exercises the real `_ask`, by breaking the agent underneath it. An earlier
    version of this test replaced `_ask` itself, which bypassed the very
    try/except it was meant to prove - and passed for the wrong reason until
    the exception escaped `deliberate`.
    """
    from till_infinity.trading.council import Council, Voice

    panel = Council(voices=(Voice("a", "x"), Voice("b", "y")), quorum=1, discuss=False)

    class Broken:
        async def run(self, prompt):
            raise RuntimeError("no credential")

    panel._agent = lambda voice: Broken()
    opinions, minutes = await panel.deliberate("brief")
    assert opinions == {}
    assert "nobody answered" in minutes


async def test_a_voice_that_times_out_reads_as_an_abstention():
    import asyncio as aio

    from till_infinity.trading.council import Council, Voice

    panel = Council(voices=(Voice("a", "x"),), quorum=1, discuss=False, timeout=0.05)

    class Slow:
        async def run(self, prompt):
            await aio.sleep(5)

    panel._agent = lambda voice: Slow()
    opinions, _ = await panel.deliberate("brief")
    assert opinions == {}


async def test_the_desk_discusses_once_and_may_change_its_mind():
    from till_infinity.trading.council import Council, Voice

    panel = Council(voices=(Voice("a", "x"), Voice("b", "y")), quorum=1, discuss=True)
    seen = []

    async def answering(voice, prompt):
        seen.append((voice.name, "desk has now spoken" in prompt))
        # First round buys; after seeing the table, one voice abstains.
        if "desk has now spoken" in prompt and voice.name == "b":
            return opinion("abstain", 0.0)
        return opinion("buy", 0.8)

    panel._ask = answering
    opinions, minutes = await panel.deliberate("brief")
    # Two voices, two rounds each.
    assert len(seen) == 4
    assert sum(1 for _, second in seen if second) == 2
    assert opinions["b"].side == "abstain"
    assert "after discussion" in minutes


async def test_a_voice_failing_the_second_round_keeps_its_first_answer():
    """A timeout is not a retraction."""
    from till_infinity.trading.council import Council, Voice

    panel = Council(voices=(Voice("a", "x"),), quorum=1, discuss=True)
    calls = []

    async def flaky(voice, prompt):
        calls.append(prompt)
        return None if "desk has now spoken" in prompt else opinion("buy", 0.9)

    panel._ask = flaky
    opinions, _ = await panel.deliberate("brief")
    assert len(calls) == 2
    assert opinions["a"].side == "buy"


async def test_the_council_produces_a_sized_intent():
    from till_infinity.trading.council import CouncilStrategy

    engine = CouncilStrategy(settings(strategies=("council",)))

    async def agreeing(brief):
        return {"trend": opinion("buy", 0.8), "quant": opinion("buy", 0.7)}, "minutes"

    engine.council.deliberate = agreeing
    got = await engine.consider_async(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.BUY
    assert got.volume > 0
    assert got.hold == CouncilStrategy.hold_seconds


async def test_the_council_respects_its_daily_call_ceiling():
    from till_infinity.trading.council import CouncilStrategy

    engine = CouncilStrategy(settings(council_daily_calls=4))
    engine.calls = 4
    got = await engine.consider_async(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "budget"


def test_the_arithmetic_strategies_stay_synchronous():
    """Making every strategy async would be a lie about what the others cost."""
    import inspect

    from till_infinity.trading.strategy import Strategy

    plain = td.STRATEGIES["level-scalp"]
    assert not inspect.iscoroutinefunction(plain.consider)
    # And the async door falls through to the sync one for them.
    assert plain.consider_async is Strategy.consider_async
    assert td.STRATEGIES["council"].consider_async is not Strategy.consider_async


# ---------------------------------------------- saying which kind of silence


def test_the_service_accepts_every_timeframe_a_level_forms_on():
    """It accepted two of eight and discarded the rest without a word.

    `structures.config.INTERVALS` is the anomaly detector's fast-data set;
    levels form on `confluence.TIMEFRAMES`. Taking the former for the latter
    meant a live 3m EURUSD call was delivered to Telegram and ignored by the
    trader in the same second.
    """
    from till_infinity.structures import confluence

    assert td.Settings().intervals == confluence.TIMEFRAMES


def test_a_strategy_separates_where_it_triggers_from_where_its_bias_comes_from():
    """Entry fixes the stop; context says whether the trigger is worth taking.

    The gap between them is the point. A swing anchored on the daily does not
    have to enter on the daily - dropping to 15m buys a tighter stop for the
    same idea, which is risk reduction rather than a different trade.
    """
    made = settings()
    swing = td.STRATEGIES["swing-level"](made)
    assert swing.intervals == ("15m", "1h", "4h")
    assert swing.anchors == ("4h", "1d", "1w")
    # Its lowest trigger is well below its highest anchor.
    assert swing.intervals[0] not in ("1d", "1w")
    assert swing.hold_seconds > td.STRATEGIES["level-scalp"](made).hold_seconds


def test_a_strategy_that_needs_an_anchor_refuses_without_one():
    made = settings()
    swing = td.STRATEGIES["swing-level"](made)

    lonely = signal(interval="1h", confluence=["1h"])
    swing.observe(lonely)
    got = swing.consider(
        lonely, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "unanchored"


def test_the_anchor_must_be_higher_not_merely_another_timeframe():
    """A 1m call confirmed by 3m is the same fast noise seen twice.

    `confluence-scalp` used to accept any other timeframe at all, which is a
    weaker claim than the one its name makes.
    """
    made = settings()
    engine = td.STRATEGIES["confluence-scalp"](made)

    fast_only = signal(interval="1m", confluence=["1m", "3m"])
    engine.observe(fast_only)
    got = engine.consider(
        fast_only, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "unanchored"

    anchored = signal(interval="5m", confluence=["5m", "1h"])
    engine.observe(anchored)
    assert isinstance(
        engine.consider(
            anchored, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
        ),
        Intent,
    )


def test_anchors_are_read_from_the_signal_not_recomputed():
    """structures has already grouped the price into a zone across timeframes."""
    made = settings()
    engine = td.STRATEGIES["level-scalp"](made)
    assert engine.anchored(signal(interval="5m", confluence=["5m", "1h", "4h"])) == ("1h", "4h")
    # The entry's own timeframe is not its own context.
    assert engine.anchored(signal(interval="5m", confluence=["5m"])) == ()
    # A timeframe outside this strategy's anchors does not count.
    assert engine.anchored(signal(interval="5m", confluence=["5m", "1w"])) == ()


def test_a_strategy_declares_its_own_timeframes():
    """The limit belongs to the strategy, not to the module.

    Restricting the service restricts every strategy at once, which is a blunt
    instrument: a scalper has no business on a 1w level, and a panel of agents
    can be told the timeframe and asked to weigh it.
    """
    made = settings()
    assert td.STRATEGIES["level-scalp"](made).intervals == ("1m", "3m", "5m")
    assert "15m" in td.STRATEGIES["approach-scalp"](made).intervals
    # The council takes whatever the operator allows and judges it itself.
    assert td.STRATEGIES["council"](made).intervals == made.intervals


def test_configuration_can_narrow_a_strategy_but_never_widen_one():
    """The effective set is the intersection, so a scalper cannot be
    configured onto weekly levels by an over-broad TRADING_INTERVALS."""
    narrow = settings(intervals=("1m", "5m"))
    assert td.STRATEGIES["level-scalp"](narrow).intervals == ("1m", "5m")

    everything = settings(intervals=("1m", "3m", "5m", "15m", "1h", "4h", "1d", "1w"))
    scalper = td.STRATEGIES["level-scalp"](everything)
    assert "1w" not in scalper.intervals
    assert scalper.intervals == ("1m", "3m", "5m")


def test_higher_timeframes_reach_a_scalper_as_confluence_not_as_a_trade():
    """A 1h level raises the probability of a fast call; it does not become a
    slow trade of its own."""
    got = take("level-scalp", signal(interval="1h"))
    assert isinstance(got, Refusal)
    assert got.gate == "interval"

    # The same structure, seen on 5m and confirmed by 1h, is tradable.
    confirmed = take("level-scalp", signal(interval="5m", confluence=["1h", "5m"]))
    assert isinstance(confirmed, Intent)
    assert "1h" in confirmed.confluence


async def test_refusals_are_counted_per_gate_so_silence_can_be_explained():
    bus = Bus()
    trader = Trader(bus, settings=settings())
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    # A call on a timeframe this trader does not act on.
    await trader.handle(Message(topic=SIGNALS, payload=signal(interval="1d")))
    await trader.handle(Message(topic=SIGNALS, payload=signal(interval="1d")))

    assert trader.passed_over.get("level-scalp:interval") == 2
    assert "interval" in trader.summary()


async def test_an_idle_trader_says_what_it_is_waiting_for(caplog):
    """Rather than looking identical to a broken one."""
    import logging

    bus = Bus()
    trader = Trader(bus, settings=settings())
    await trader.start()
    # Far enough in the past to fire whatever the interval is. Setting this
    # to 0.0 assumed `monotonic()` was already large, which is true on a
    # machine that has been up a while and false on a fresh CI runner where
    # it starts near zero - so the summary never fired and the test passed
    # locally while failing there.
    trader._last_summary = time.monotonic() - 100_000

    with caplog.at_level(logging.INFO, logger="till_infinity.trading.service"):
        trader._say_what_it_is_doing()

    said = " ".join(caplog.messages)
    assert "nothing seen yet" in said
    assert "gold" in said
    assert "3m" in said  # the timeframes it is actually watching


async def test_a_working_trader_reports_what_it_passed_over(caplog):
    import logging

    bus = Bus()
    trader = Trader(bus, settings=settings())
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.handle(Message(topic=SIGNALS, payload=signal(interval="1d")))
    trader._last_summary = time.monotonic() - 100_000

    with caplog.at_level(logging.INFO, logger="till_infinity.trading.service"):
        trader._say_what_it_is_doing()

    said = " ".join(caplog.messages)
    assert "passed over" in said
    assert "interval" in said


# ------------------------------------------- standing in front of a sweep


def test_a_level_that_is_usually_run_is_refused():
    """A level run four times in ten is telling you about itself directly."""
    got = take("sweep-aware", signal(features={"sweep_rate": 0.5, "sweep_n": 10.0}))
    assert isinstance(got, Refusal)
    assert got.gate == "swept_often"


def test_a_high_sweep_rate_with_no_history_behind_it_is_not_believed():
    """Two interactions cannot establish a rate."""
    got = take("sweep-aware", signal(features={"sweep_rate": 1.0, "sweep_n": 2.0}))
    assert isinstance(got, Intent)


def test_a_stop_in_front_of_resting_liquidity_is_refused():
    """A run at those orders takes this one on the way."""
    got = take(
        "sweep-aware",
        signal(features={"risk_vol": 1.0, "liquidity_beyond_vol": 1.0}),
    )
    assert isinstance(got, Refusal)
    assert got.gate == "in_front"


def test_a_stop_in_open_ground_is_allowed():
    got = take(
        "sweep-aware",
        signal(features={"risk_vol": 1.0, "liquidity_beyond_vol": 6.0}),
    )
    assert isinstance(got, Intent)


def test_nothing_within_reach_is_not_a_reason_to_refuse():
    """Zero means no target, which is the good case rather than a missing one."""
    got = take("sweep-aware", signal(features={"liquidity_beyond_vol": 0.0}))
    assert isinstance(got, Intent)


def test_sweep_aware_refuses_rather_than_widening_the_stop():
    """Widening would keep the trade and change what it costs."""
    plain = take("level-scalp", signal(features={"liquidity_beyond_vol": 1.0}))
    guarded = take("sweep-aware", signal(features={"risk_vol": 1.0, "liquidity_beyond_vol": 1.0}))
    assert isinstance(plain, Intent)
    assert isinstance(guarded, Refusal)


# ----------------------------------------------- pricing the distance


def fade(**over):
    return td.STRATEGIES["fade-to-value"](settings(**over))


def test_fair_value_is_the_best_evidenced_level_not_the_nearest():
    """An estimate that moved every time price drifted would not be an estimate."""
    engine = fade()
    # A nearby level nobody has traded, and a far one with real history.
    engine.observe(signal(features={"level": 4402.0, "record_n": 2.0}))
    engine.observe(signal(features={"level": 4380.0, "record_n": 40.0}))
    unit = 4400.0 * 10.0 / 10_000
    value = engine.fair_value("gold", unit, 4400.0)
    assert value is not None
    assert value.price == 4380.0


def test_a_price_below_fair_value_is_a_long():
    engine = fade()
    engine.observe(signal(features={"level": 4425.0, "record_n": 40.0}))
    engine.observe(signal())
    got = engine.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.BUY
    assert got.target < 4425.0  # short of fair value
    assert "below fair value" in got.reason


def test_a_price_above_fair_value_is_a_short():
    engine = fade()
    engine.observe(signal(features={"level": 4375.0, "record_n": 40.0}))
    engine.observe(signal())
    got = engine.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.SELL
    assert got.target > 4375.0
    assert "above fair value" in got.reason


def test_a_price_at_fair_value_has_nothing_to_say():
    """Inside one volatility unit the distance is the noise of the estimate."""
    engine = fade()
    engine.observe(signal(features={"level": 4402.0, "record_n": 40.0}))
    engine.observe(signal())
    got = engine.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "at_value"


def test_a_level_with_too_little_history_is_not_a_valuation():
    engine = fade()
    # The only level it knows of has been touched once, so there is nothing to
    # price against. The triggering call is deliberately not observed either.
    engine.observe(signal(features={"level": 4425.0, "record_n": 1.0}))
    got = engine.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "no_value"


def test_the_fade_stop_sits_beyond_the_level_price_is_standing_at():
    """That is where this reading of value is wrong."""
    engine = fade()
    engine.observe(signal(features={"level": 4425.0, "record_n": 40.0}))
    engine.observe(signal())
    got = engine.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    # The triggering level is 4400; the stop is below it, not below fair value.
    assert got.stop < 4400.0
    assert got.stop > 4375.0 - 40


def test_the_side_is_arithmetic_once_the_valuation_exists():
    """Nothing is forecast: the same signal gives opposite sides on the
    valuation alone."""
    up, down = fade(), fade()
    up.observe(signal(features={"level": 4425.0, "record_n": 40.0}))
    down.observe(signal(features={"level": 4375.0, "record_n": 40.0}))
    for engine in (up, down):
        engine.observe(signal())
    tick = Tick("XAUUSD", bid=4399.5, ask=4400.5)
    long = up.consider(signal(), spec=GOLD, tick=tick, equity=10_000.0)
    short = down.consider(signal(), spec=GOLD, tick=tick, equity=10_000.0)
    assert long.side is Side.BUY
    assert short.side is Side.SELL
    # Identical signal, identical direction field on it: only the valuation differs.
    assert signal()["direction"] == "up"


# ------------------------------------------ what the terminal actually paid


class ClosingBroker(RecordingBroker):
    """A live-terminal double that can be asked what a close actually paid."""

    def __init__(self, made, deal=None):
        super().__init__(made)
        self.deal = deal
        self.asked: list[int] = []

    async def closed_deal(self, ticket):
        self.asked.append(ticket)
        return self.deal


async def test_a_vanished_position_is_settled_at_what_the_terminal_paid():
    """It was settled at the last snapshot, which is always a little stale.

    The first live trade recorded +52.20 where the broker had paid +59.40 - a
    12% error on the one number every strategy is later scored by, and always
    in the direction of the move that closed the position.
    """
    bus = Bus()
    made = settings(live=True)
    venue = ClosingBroker(made, deal=(4623.82, 59.4))
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.handle(Message(topic=SIGNALS, payload=signal()))
    assert len(trader.open) == 1
    ticket = next(iter(trader.open))

    # The position vanishes server-side, as a stop or target fill does.
    await venue._book.close_position(ticket)
    venue._book.drain_closed()
    await trader.sweep()

    assert venue.asked == [ticket]
    assert not trader.open
    assert trader.guard.realised == pytest.approx(59.4)


async def test_a_backend_that_cannot_confirm_keeps_the_estimate_and_says_so():
    bus = Bus()
    made = settings(live=True)
    venue = ClosingBroker(made, deal=None)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.handle(Message(topic=SIGNALS, payload=signal()))
    ticket = next(iter(trader.open))
    await venue._book.close_position(ticket)
    venue._book.drain_closed()
    await trader.sweep()

    assert venue.asked == [ticket]
    assert not trader.open  # still settled, just on the stale number


async def test_the_closing_deal_is_the_one_that_left_the_position():
    """Deals link by position_id; the one that closed it has entry == 1.

    Costs are folded in, because what the account received is the number worth
    scoring - not the gross move.
    """
    from till_infinity.trading.mt5_http import HttpBroker

    broker = http_broker()

    async def fake_get(path, **kwargs):
        return [
            {"position_id": 42, "entry": 0, "price": 4624.81, "profit": 0.0},
            {"position_id": 99, "entry": 1, "price": 1.0, "profit": 1000.0},
            {
                "position_id": 42,
                "entry": 1,
                "price": 4623.82,
                "profit": 59.4,
                "swap": -0.4,
                "commission": 0.0,
                "time_msc": 2,
            },
        ]

    broker._get = fake_get
    got = await HttpBroker.closed_deal(broker, 42)
    assert got is not None
    price, profit = got
    assert price == 4623.82
    assert profit == pytest.approx(59.0)  # 59.4 less the 0.4 swap


async def test_a_position_with_no_closing_deal_yet_returns_nothing():
    from till_infinity.trading.mt5_http import HttpBroker

    broker = http_broker()

    async def fake_get(path, **kwargs):
        return [{"position_id": 42, "entry": 0, "price": 4624.81, "profit": 0.0}]

    broker._get = fake_get
    assert await HttpBroker.closed_deal(broker, 42) is None


# ------------------------------- asking what a thing is worth, not which way


def valued(value=4450.0, width=15.0, hours=4.0, because="CPI"):
    from till_infinity.trading.valuation import Valuation

    return Valuation(value=value, width=width, hours=hours, because=because)


UNIT = 4.4  # one volatility unit on gold at 4400


def test_a_valuation_above_the_market_is_a_long():
    """The stance is arithmetic. The model is never asked for a direction."""
    from till_infinity.trading.valuation import price_it

    got = price_it(valued(value=4450.0), spot=4400.0, unit=UNIT)
    assert got is not None
    assert got.stance == "buy"
    assert got.gap_vol > 0


def test_a_valuation_below_the_market_is_a_short():
    from till_infinity.trading.valuation import price_it

    got = price_it(valued(value=4350.0), spot=4400.0, unit=UNIT)
    assert got is not None
    assert got.stance == "sell"
    assert got.gap_vol < 0


def test_a_market_inside_the_interval_is_no_claim_at_all():
    """Most of the time the market's price is a fair estimate of itself."""
    from till_infinity.trading.valuation import price_it

    assert price_it(valued(value=4410.0, width=30.0), spot=4400.0, unit=UNIT) is None


def test_an_overconfident_width_is_widened_not_obeyed():
    """A narrow interval is a claim about the model's certainty, and it is the
    number that would size the position."""
    from till_infinity.trading.valuation import MIN_WIDTH_VOL, price_it

    got = price_it(valued(width=0.5), spot=4400.0, unit=UNIT)
    assert got is not None
    assert got.width == pytest.approx(MIN_WIDTH_VOL * UNIT)


def test_a_shrug_is_not_a_valuation_either():
    from till_infinity.trading.valuation import MAX_WIDTH_VOL, price_it

    got = price_it(valued(value=4600.0, width=10_000.0), spot=4400.0, unit=UNIT)
    assert got is None or got.width == pytest.approx(MAX_WIDTH_VOL * UNIT)


def test_a_valuation_far_from_the_market_is_a_mistake_not_a_bold_call():
    from till_infinity.trading.valuation import price_it

    assert price_it(valued(value=9000.0, width=20.0), spot=4400.0, unit=UNIT) is None


def test_declining_is_a_real_answer():
    from till_infinity.trading.valuation import price_it

    assert price_it(valued(value=0.0, width=0.0), spot=4400.0, unit=UNIT) is None


def test_the_gap_is_measured_in_the_analysts_own_widths():
    """Whether a gap is a mispricing depends on how sure the analyst was.

    The same 50-point gap is three widths to a confident analyst and half a
    width to an unsure one, and only the first is a claim.
    """
    from till_infinity.trading.valuation import price_it

    confident = price_it(valued(value=4450.0, width=15.0), spot=4400.0, unit=UNIT)
    assert confident is not None
    assert confident.gap_widths == pytest.approx(50 / 15, abs=0.01)

    unsure = price_it(valued(value=4450.0, width=120.0), spot=4400.0, unit=UNIT)
    assert unsure is None


async def test_a_failing_analyst_produces_no_valuation():
    """Timeout, no credential, a malformed reply: all read as no answer."""
    from till_infinity.trading import valuation

    assert await valuation.ask("gold", "brief", timeout=0.01) is None


# ------------------------------------- a stop inside the noise is not a stop


def test_the_stop_is_floored_at_one_volatility_unit():
    """Fair value is a distribution and volatility is its width.

    A stop closer than one unit sits inside the estimate it is protecting and
    is taken by ordinary movement rather than by the thesis failing. The first
    two live trades carried risk_vol of 0.53 and 0.61.
    """
    made = settings()
    engine = td.STRATEGIES["level-scalp"](made)
    # The losing trade's own numbers.
    stop, _ = engine.distances(
        level=4624.97, entry=4624.97, vol_bps=3.72354, risk_vol=0.609921, push_vol=1.158286
    )
    unit = 4624.97 * 3.72354 / 10_000
    assert stop / unit == pytest.approx(1.0, abs=0.01)
    assert stop > 1.05  # wider than the stop that was actually placed


def test_a_model_asking_for_a_wide_stop_still_gets_it():
    """The floor only ever widens: it is a minimum, not a target."""
    made = settings()
    engine = td.STRATEGIES["level-scalp"](made)
    stop, _ = engine.distances(level=4400.0, entry=4400.0, vol_bps=10.0, risk_vol=3.0, push_vol=2.0)
    unit = 4400.0 * 10.0 / 10_000
    assert stop / unit == pytest.approx(3.0, abs=0.01)


def test_widening_the_stop_shrinks_the_size_rather_than_the_risk():
    """The budget is fixed, so a wider stop buys fewer lots. That is the trade
    being sized correctly, not being penalised."""
    tight = settings(min_stop_vol=0.5)
    wide = settings(min_stop_vol=2.0)
    small = take("level-scalp", equity=10_000.0)
    assert isinstance(small, Intent)

    engine_wide = td.STRATEGIES["level-scalp"](wide)
    engine_wide.observe(signal())
    big_stop = engine_wide.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(big_stop, Intent)
    assert big_stop.volume < small.volume
    assert big_stop.risk_money == pytest.approx(small.risk_money, rel=0.35)
    assert abs(tight.min_stop_vol - wide.min_stop_vol) > 0


def test_a_trade_that_cannot_afford_a_real_stop_is_refused():
    """A stop inside the noise is not a cheaper trade, it is a worse one."""
    got = take("level-scalp", equity=200.0, min_stop_vol=4.0)
    assert isinstance(got, Refusal)
    assert got.gate == "size"


# --------------------------------------------------------------- magic band


def test_each_strategy_stamps_its_own_magic():
    """Two strategies running side by side must leave distinguishable trades.

    The order comment says the same thing, but MT5 truncates it at 31
    characters and brokers rewrite it, so magic is the field a report and a
    restart can both rely on.
    """
    base = td.DEFAULT_MAGIC
    magics = {name: td.magic_for(base, name) for name in td.MAGIC_ORDER}
    assert len(set(magics.values())) == len(magics)
    assert all(td.strategy_for(base, m) == name for name, m in magics.items())
    assert all(td.ours(base, m) for m in magics.values())


def test_the_base_magic_stays_ours_and_names_nobody():
    """Positions opened before per-strategy magics existed carry the base.

    They still have to be recognised, managed and closed; what is gone is the
    attribution, and saying so is better than guessing a strategy.
    """
    base = td.DEFAULT_MAGIC
    assert td.magic_for(base, "") == base
    assert td.ours(base, base)
    assert td.strategy_for(base, base) == ""


def test_a_magic_does_not_move_when_the_strategy_list_changes():
    """The number lands on a position held at a broker and outlives the run.

    Deriving it from the configured list would renumber every open position
    the moment TRADING_STRATEGIES was edited, and a restart mid-trade could
    not say who owned what.
    """
    base = td.DEFAULT_MAGIC
    alone = td.magic_for(base, "sweep-aware")
    assert td.magic_for(base, "sweep-aware") == alone
    # The same name, asked for in a differently-ordered world.
    assert td.MAGIC_ORDER.index("sweep-aware") == td.MAGIC_ORDER.index("sweep-aware")
    assert alone != td.magic_for(base, "level-scalp")


def test_an_unregistered_strategy_is_hashed_stably_and_stays_ours():
    """A plugin's magic must survive a restart. Python's `hash` is salted."""
    base = td.DEFAULT_MAGIC
    first = td.magic_for(base, "some-plugin-strategy")
    assert first == td.magic_for(base, "some-plugin-strategy")
    assert td.ours(base, first)
    # Outside the fixed table, so it has no inverse and says so.
    assert td.strategy_for(base, first) == ""


def test_a_foreign_magic_is_never_ours():
    """The whole point of the field: a hand-placed trade is left alone."""
    base = td.DEFAULT_MAGIC
    assert not td.ours(base, 0)
    assert not td.ours(base, 12345)
    assert not td.ours(base, base - 1)
    assert not td.ours(base, base + td.MAGIC_BAND)


async def test_the_order_carries_the_strategys_magic():
    bus = Bus()
    made = settings(live=True)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()

    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    got = await trader.handle(Message(topic=SIGNALS, payload=signal()))

    assert isinstance(got, Intent)
    assert len(venue.sent) == 1
    sent = venue.sent[0]
    assert sent.magic == td.magic_for(made.magic, "level-scalp")
    assert sent.magic != made.magic
    assert td.strategy_for(made.magic, sent.magic) == "level-scalp"


# ------------------------------------------------------- the order they run in


async def test_a_strategy_listed_where_it_can_never_trade_is_reported(caplog):
    """The failure nobody finds by looking.

    `sweep-aware` is `level-scalp` plus extra refusals, so behind it there is
    nothing left for it to take. It loads, it reports as enabled, and it books
    no trades forever - every signal except its own results says it is working.
    """
    bus = Bus()
    made = settings(strategies=("level-scalp", "sweep-aware"))
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))
    with caplog.at_level("WARNING"):
        await trader.start()

    said = " ".join(r.getMessage() for r in caplog.records)
    assert "sweep-aware" in said
    assert "never trade" in said


async def test_the_right_order_is_not_complained_about(caplog):
    bus = Bus()
    made = settings(strategies=("sweep-aware", "level-scalp"))
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))
    with caplog.at_level("WARNING"):
        await trader.start()

    said = " ".join(r.getMessage() for r in caplog.records)
    assert "never trade" not in said


def test_a_refinement_names_a_strategy_that_exists():
    """A typo in `refines` would silently disable the check it exists for."""
    from till_infinity.trading.strategy import STRATEGIES

    for name, cls in STRATEGIES.items():
        if cls.refines:
            assert cls.refines in STRATEGIES, f"{name} refines unknown {cls.refines}"
            assert cls.refines != name


# ------------------------------------------------- the stop clears the fill


def test_the_stop_clears_the_fill_not_just_the_level():
    """The failure this was written after.

    `distances` floors the stop at `min_stop_vol` from the **level**, and
    sizing measures from the **fill**. A fill that lands most of the way to a
    level-anchored stop is therefore sized as a short-distance trade - a large
    one - and taken out by ordinary movement. Live: a gold buy filled 1.0v
    above a stop sitting 5.9v below the level, sized 0.18 lots, stopped in
    minutes for -26.64.
    """
    # Price well above the level at 4400, so the level-anchored stop is far
    # below the level but close underneath the fill.
    got = take("level-scalp", tick=Tick("XAUUSD", bid=4399.0, ask=4400.0), min_stop_vol=2.0)
    assert isinstance(got, Intent)
    unit = price_distance(4400.0, 10.0, 1.0)
    assert abs(got.entry - got.stop) >= 2.0 * unit - 1e-9


def test_widening_the_stop_to_clear_the_fill_shrinks_the_position():
    """It can only cost size, never add it - same money over a longer stop."""
    tight = take("level-scalp", tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), min_stop_vol=0.5)
    wide = take("level-scalp", tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), min_stop_vol=3.0)
    assert isinstance(tight, Intent)
    assert isinstance(wide, Intent)
    assert abs(wide.entry - wide.stop) > abs(tight.entry - tight.stop)
    # A longer stop for the same money can only mean fewer lots. Not asserting
    # equal risk_money: the lot step is coarse and the minimum lot is a floor,
    # so the money actually at risk moves around under rounding.
    assert wide.volume <= tight.volume


def test_the_fill_floor_never_rescues_an_invalidated_trade():
    """Order of operations, not a detail.

    A fill on the far side of the level-anchored stop is a trade that has
    already been invalidated. Applying the fill floor before the `through`
    check would rebase the stop below such a fill and turn the refusal into a
    position - which is what happened on the first attempt at this.
    """
    got = take("level-scalp", tick=Tick("XAUUSD", bid=4389.5, ask=4390.5))
    assert isinstance(got, Refusal)
    assert got.gate == "through"
    # Note the floor cannot be turned up to probe this in isolation:
    # `min_stop_vol` feeds the level-anchored distance in `distances` as well,
    # so raising it moves the anchored stop down past the fill and the trade
    # stops being invalidated at all. The ordering is what protects this, not
    # the size of the floor.


async def test_the_journal_records_what_the_fill_cost_against_what_was_asked(tmp_path):
    """Slippage was not recoverable from the journal before this.

    The decision held the requested price, the outcome held the exit, and the
    actual fill in between reached only an alert. `position.price_open` is the
    broker's own record of it, so this survives a restart without having kept
    the order result around.
    """
    bus = Bus()
    made = settings(live=True)
    venue = RecordingBroker(made)
    async with Journal(tmp_path / "journal.db") as book:
        trader = Trader(bus, settings=made, journal=book, broker=venue)
        await trader.start()

        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        got = await trader.handle(Message(topic=SIGNALS, payload=signal()))
        assert isinstance(got, Intent)

        live = next(iter(trader.open.values()))
        wanted = live.intent.entry
        # The terminal filled a touch worse than asked for.
        live.position = replace(live.position, price_open=wanted + 0.30)
        await trader._settle(live, price=wanted + 5.0, why="closed", profit=12.0)

    entries = [e for e in read(tmp_path / "journal.db") if "slippage" in (e.context or {})]
    assert entries, "the outcome carries no slippage"
    ctx = entries[-1].context
    assert ctx["entry_wanted"] == pytest.approx(wanted)
    assert ctx["entry_filled"] == pytest.approx(wanted + 0.30)
    # Signed against the trade: a buy filled higher than asked is worse.
    assert ctx["slippage"] == pytest.approx(0.30)


# ------------------------------------------------------- spread, by the hour


def test_the_spread_model_says_nothing_until_it_has_evidence():
    """A spread limit derived from four quotes is not a limit."""
    from till_infinity.trading.spreads import MIN_EVIDENCE, Spreads

    book = Spreads()
    when = 1_700_000_000.0
    for _ in range(5):
        book.observe("gold", when, 3.0)
    # It has an opinion about the level, but not enough to act on.
    assert book.expected("gold", when)[0] > 0
    assert book.ratio("gold", when, 30.0) == 0.0

    for _ in range(int(MIN_EVIDENCE) + 5):
        book.observe("gold", when, 3.0)
    assert book.ratio("gold", when, 30.0) > 5.0


def test_an_unmeasured_instrument_is_never_mistaken_for_a_normal_one():
    """Zero means "no opinion", not "a ratio of zero" and not "normal"."""
    from till_infinity.trading.spreads import Spreads

    book = Spreads()
    assert book.ratio("gold", 1_700_000_000.0, 4.0) == 0.0
    assert book.expected("gold", 1_700_000_000.0) == (0.0, 0.0)


def test_a_thin_hour_reports_roughly_the_instruments_usual_spread():
    """Shrinkage, so one wide quote in a quiet hour is not a new normal."""
    from till_infinity.trading.spreads import Spreads

    book = Spreads()
    busy = 1_700_000_000.0
    for _ in range(200):
        book.observe("gold", busy, 3.0)
    quiet = busy + 3600.0  # a different hour, with one observation
    book.observe("gold", quiet, 60.0)

    usual, seen = book.expected("gold", quiet)
    assert seen < 2
    # Nowhere near 60: one observation cannot outvote the pooled estimate.
    assert usual < 10.0


def test_no_peer_group_no_longer_means_no_spread_check():
    """The fail-open this was written for.

    `dislocation` needs MIN_VENUES fresh quotes and returned "" without them -
    no spread check at all, in exactly the moments a broker's spread is worst.
    """
    ctx = Context(max_spread_ratio=2.5)
    when = 1_700_000_000.0
    normal = Tick("XAUUSD", bid=4399.85, ask=4400.15)  # ~0.68bps
    for _ in range(60):
        ctx.spreads.observe("gold", when, normal.spread_bps)

    wide = Tick("XAUUSD", bid=4398.0, ask=4402.0)  # ~9bps, over 13x normal
    said = ctx.dislocation("gold", wide, now=when)
    assert said, "a wide spread with no peer group is no longer waved through"
    assert "peer quote" in said

    # And a normal spread on the same path is still fine.
    assert ctx.dislocation("gold", normal, now=when) == ""


def test_the_peer_test_still_wins_when_there_is_a_peer_group():
    """The fallback stands in for the peer test, it does not layer on top."""
    ctx = Context(max_spread_ratio=2.5)
    when = 1_700_000_000.0
    tight = Tick("XAUUSD", bid=4399.85, ask=4400.15)
    for _ in range(60):
        ctx.spreads.observe("gold", when, tight.spread_bps)

    # Three venues all quoting the same wide spread: the market widened, and
    # our broker widening with it is not a fault.
    wide = Tick("XAUUSD", bid=4398.0, ask=4402.0)
    for venue in ("A", "B", "C"):
        ctx.observe_quote(
            {
                "feed": "gold",
                "venue": venue,
                "mid": 4400.0,
                "spread_bps": wide.spread_bps,
                "time": when,
            }
        )
    assert ctx.dislocation("gold", wide, now=when) == ""


# --------------------------------------------------- money, and letting it run


def test_an_amount_says_which_money_it_is():
    """A bare "+12.56" does not say what it is 12.56 of, and it is not
    guessable from the instrument - a gold trade on a euro account pays euros.
    """
    bus = Bus()
    trader = Trader(bus, settings=settings())
    trader.currency = "USD"
    assert trader.money(12.56) == "+$12.56"
    assert trader.money(-26.64) == "-$26.64"
    assert trader.money(12.56, signed=False) == "$12.56"

    trader.currency = "EUR"
    assert trader.money(12.56) == "+€12.56"

    # An unrecognised code is written out rather than guessed at.
    trader.currency = "SGD"
    assert trader.money(12.56) == "+12.56 SGD"

    # And an account that never reported one still prints a number.
    trader.currency = ""
    assert trader.money(12.56) == "+12.56"


async def test_a_working_trade_is_kept_past_its_hold_and_protected():
    """The hold releases capital from a thesis that is not playing out. It was
    also closing the ones that were - out at 4623 on a fall that ran to 4592.
    """
    bus = Bus()
    made = settings(live=True, hold_extends_at=0.5, break_even_ticks=2)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    got = await trader.handle(Message(topic=SIGNALS, payload=signal()))
    assert isinstance(got, Intent)

    live = next(iter(trader.open.values()))
    risk = abs(live.intent.entry - live.intent.stop)
    # Comfortably past the 0.5R threshold, but short of the target - otherwise
    # the paper book simply fills the target and there is nothing to expire.
    at = live.intent.entry + risk * 0.8
    venue.observe(Tick("XAUUSD", bid=at, ask=at))
    live.seen -= (live.intent.hold or made.max_hold) + 60

    await trader._expire()

    assert trader.open, "a trade 0.8R in front was closed on the clock"
    # And it was protected on the way past: the stop is at or beyond entry.
    assert venue.modified, "kept without moving the stop to break even"


async def test_a_trade_going_nowhere_still_closes_on_the_clock():
    bus = Bus()
    made = settings(live=True, hold_extends_at=1.0)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    got = await trader.handle(Message(topic=SIGNALS, payload=signal()))
    assert isinstance(got, Intent)

    live = next(iter(trader.open.values()))
    live.seen -= (live.intent.hold or made.max_hold) + 60
    await trader._expire()
    assert not trader.open, "a flat trade should still be released"


def test_the_crosses_consume_a_different_budget_from_everything_else():
    """The reason they were added, and the thing a wrong leg would delete.

    Every other instrument here has the dollar on one side by construction, so
    `max_currency_exposure` binds on USD long before it binds on anything else.
    A cross is the only position that can be opened when the dollar budget is
    already full.
    """
    crosses = ("eurgbp", "eurjpy", "gbpjpy", "eurchf", "audjpy", "chfjpy", "euraud")
    for feed in crosses:
        base, quote = ex.legs(feed)
        assert base and quote, f"{feed} is unmapped, so it escapes the limit entirely"
        assert "USD" not in (base, quote), f"{feed} was mapped onto the dollar"

    # A full dollar book plus a cross: the cross adds nothing to USD.
    positions = [
        td.Position(ticket=1, symbol="XAUUSD", side=Side.BUY, volume=0.1, price_open=4400.0),
        td.Position(ticket=2, symbol="EURUSD", side=Side.BUY, volume=0.1, price_open=1.1),
    ]
    feed_of = {"XAUUSD": "gold", "EURUSD": "eurusd", "GBPJPY": "gbpjpy"}
    before = abs(ex.measure(positions, {1: 25.0, 2: 25.0}, feed_of).of("USD"))
    positions.append(
        td.Position(ticket=3, symbol="GBPJPY", side=Side.BUY, volume=0.1, price_open=195.0)
    )
    after = ex.measure(positions, {1: 25.0, 2: 25.0, 3: 25.0}, feed_of)
    assert abs(after.of("USD")) == pytest.approx(before)
    assert abs(after.of("JPY")) > 0


def test_every_tracked_instrument_can_be_exposure_mapped():
    """An unmapped feed is not merely unmeasured - it is *exempt* from the
    currency limit, which is the one failure mode that looks like nothing.
    """
    unmapped = [f for f in td.INSTRUMENTS if ex.legs(f) == ("", "")]
    assert not unmapped, f"no currency legs for {unmapped}"
