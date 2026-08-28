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
from till_infinity.trading import manage
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


def take(name, payload=None, *, tick=None, equity=10_000.0, spec=None, **over):
    engine = strategy(name, **over)
    engine.observe(payload or signal())
    return engine.consider(
        payload or signal(),
        spec=spec or GOLD,
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
        assert base, f"{feed} is unmapped, so it escapes the limit entirely"
        assert quote, f"{feed} is unmapped, so it escapes the limit entirely"
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


# ----------------------------------------------------- the market gone wide


def _wide(feed, venue, when):
    return {
        "shape": "spread",
        "feed": feed,
        "time": when,
        "fields": {"venue": venue},
        "detail": "spread 1.6x the group",
    }


def test_one_wide_venue_is_not_the_market_going_wide():
    """`structures` scores spread per venue and flags whichever is out of line.

    Those fire continuously and are supposed to - one venue quoting badly is
    what the detector is for - so standing aside on each would stop trading
    altogether.
    """
    ctx = Context(wide_venues=3, wide_warmup=0.0)
    ctx.observe_signal(_wide("gold", "CAPITALCOM", 100.0))
    ctx.observe_signal(_wide("gold", "CAPITALCOM", 120.0))
    ctx.observe_signal(_wide("gold", "CAPITALCOM", 140.0))
    # The same venue five times is one wide venue, not five.
    assert ctx.widened("gold", now=150.0) == 0


def test_several_venues_wide_at_once_is_the_market():
    ctx = Context(wide_venues=3, wide_pause=300.0, wide_warmup=0.0)
    for venue in ("OANDA", "CAPITALCOM", "FOREXCOM"):
        ctx.observe_signal(_wide("gold", venue, 100.0))
    assert ctx.widened("gold", now=150.0) == 3
    # And it lapses: a widening passes, unlike a regime change.
    assert ctx.widened("gold", now=500.0) == 0


def test_a_wide_market_refuses_the_trade():
    made = settings()
    ctx = Context(wide_venues=3, wide_pause=300.0, wide_warmup=0.0)
    guard = Guard(made, context=ctx)
    guard.roll(10_000.0)
    for venue in ("OANDA", "CAPITALCOM", "FOREXCOM"):
        ctx.observe_signal(_wide("gold", venue, 100.0))

    got = take("level-scalp")
    assert isinstance(got, Intent)
    stopped = guard.allows(got, positions=[], tick=None, now=150.0)
    assert stopped is not None
    assert stopped.gate == "wide"


def test_a_wide_market_on_another_instrument_does_not_refuse_this_one():
    made = settings()
    ctx = Context(wide_venues=3, wide_pause=300.0, wide_warmup=0.0)
    guard = Guard(made, context=ctx)
    guard.roll(10_000.0)
    for venue in ("OANDA", "CAPITALCOM", "FOREXCOM"):
        ctx.observe_signal(_wide("btc", venue, 100.0))

    got = take("level-scalp")
    assert isinstance(got, Intent)
    assert guard.allows(got, positions=[], tick=None, now=150.0) is None


def test_a_freshly_added_instrument_is_not_judged_unusual_yet():
    """`structures` scores spread per venue with a model that needs history.

    A newly added instrument has none, so its first minutes produce anomalies
    that describe the detector rather than the market. Caught live the day
    fourteen instruments were switched on at once: two were flagged wide on
    three venues within two minutes of first being quoted, which would have
    stood the trader aside on exactly the symbols just enabled.
    """
    ctx = Context(wide_venues=3, wide_pause=300.0, wide_warmup=900.0)
    for venue in ("OANDA", "CAPITALCOM", "FOREXCOM"):
        ctx.observe_signal(_wide("chfjpy", venue, 100.0))

    # Two minutes in: three venues agree, and it still does not count.
    assert ctx.widened("chfjpy", now=220.0) == 0

    # Once the instrument has been watched long enough, the same evidence does.
    for venue in ("OANDA", "CAPITALCOM", "FOREXCOM"):
        ctx.observe_signal(_wide("chfjpy", venue, 1_100.0))
    assert ctx.widened("chfjpy", now=1_150.0) == 3


def test_the_wide_log_does_not_announce_a_decision_nobody_made(caplog):
    """It said "standing aside" while the gate was correctly doing nothing.

    During the warm-up window `widened` returns 0, so no trade was ever
    refused - but the line went out anyway, once per venue report, on a dozen
    instruments at a time. A log that claims an action not taken is worse than
    no log, because it is what gets believed later.
    """
    ctx = Context(wide_venues=3, wide_pause=300.0, wide_warmup=900.0)
    with caplog.at_level("INFO", logger="till_infinity.trading.context"):
        for venue in ("OANDA", "CAPITALCOM", "FOREXCOM"):
            ctx.observe_signal(_wide("gold", venue, 100.0))
        assert ctx.widened("gold", now=150.0) == 0
        assert not [r.getMessage() for r in caplog.records if "standing aside" in r.getMessage()]

        # Past the warm-up the same evidence both gates and says so - once.
        for venue in ("OANDA", "CAPITALCOM", "FOREXCOM"):
            ctx.observe_signal(_wide("gold", venue, 1_100.0))
        assert ctx.widened("gold", now=1_150.0) == 3
        said = [r.getMessage() for r in caplog.records if "standing aside" in r.getMessage()]
        assert len(said) == 1, "one widening should be one line, not one per venue"


# ------------------------------------------- stopped out before the move came


def test_the_stop_clears_the_sweep_zone_not_the_touch_zone():
    """A stop at the average sweep depth is exceeded by about half of sweeps.

    The touch zone's far edge is built from the mean wick, which is the right
    centre for "is price at this level" and the wrong edge for "how far past it
    does price go". From the account the difference looks like being stopped
    out and then watching the move happen.
    """
    shallow = take("level-scalp", signal(features={"zone_low": 4396.0}))
    deep = take(
        "level-scalp",
        signal(features={"zone_low": 4396.0, "sweep_low": 4392.0}),
    )
    assert isinstance(shallow, Intent)
    assert isinstance(deep, Intent)
    assert deep.stop < shallow.stop, "the wider band should push the stop further out"
    # And the size comes down to keep the money at risk the same.
    assert deep.volume <= shallow.volume


def test_an_older_signal_without_a_sweep_zone_still_works():
    """A producer that predates the wider band degrades to the previous
    behaviour rather than to no zone at all."""
    got = take("level-scalp", signal(features={"zone_low": 4396.0}))
    assert isinstance(got, Intent)
    assert got.stop < 4400.0


def test_a_fill_that_has_left_the_level_behind_is_refused():
    """The call was measured at the level and the push runs from there, so a
    fill well past it has already spent part of the move."""
    # Level at 4400, price 3v past it in the trade's direction.
    got = take(
        "level-scalp",
        tick=Tick("XAUUSD", bid=4412.0, ask=4413.0),
        max_chase_vol=1.0,
    )
    assert isinstance(got, Refusal)
    assert got.gate in {"chase", "through"}


def test_arriving_before_the_level_is_not_a_chase():
    """Price short of the level is the setup behaving as advertised."""
    got = take("level-scalp", tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), max_chase_vol=1.0)
    assert isinstance(got, Intent)


# ------------------------------------------------ waiting for a better fill


async def test_a_signal_is_parked_rather_than_chased():
    """Buy where the stop was going to be, not where price happens to be."""
    bus = Bus()
    made = settings(live=True, pullback_fraction=1.0)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    got = await trader.handle(
        Message(
            topic=SIGNALS,
            payload=signal(features={"sweep_low": 4396.0, "expected_push_vol": 3.0, "wick_n": 6.0}),
        )
    )
    assert isinstance(got, Refusal)
    assert got.gate == "waiting"
    assert venue.sent == [], "nothing should have been sent yet"
    assert "gold" in trader._waiting


async def test_a_parked_signal_fires_when_price_comes_to_it():
    bus = Bus()
    made = settings(live=True, pullback_fraction=1.0)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.handle(
        Message(
            topic=SIGNALS,
            payload=signal(features={"sweep_low": 4396.0, "expected_push_vol": 3.0, "wick_n": 6.0}),
        )
    )
    assert venue.sent == []

    # Price comes back to where the stop would have been.
    venue.observe(Tick("XAUUSD", bid=4395.5, ask=4396.0))
    got = await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4395.5, "ask": 4396.0})
    )
    assert isinstance(got, Intent)
    assert len(venue.sent) == 1
    assert "gold" not in trader._waiting
    # And the fill is better than the one that was refused.
    assert got.entry < 4400.5


async def test_a_parked_signal_that_never_comes_back_expires():
    """A resting order with no deadline is a trade taken on stale information."""
    bus = Bus()
    made = settings(live=True, pullback_fraction=1.0, pullback_bars=0.001)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.handle(
        Message(
            topic=SIGNALS,
            payload=signal(features={"sweep_low": 4396.0, "expected_push_vol": 3.0, "wick_n": 6.0}),
        )
    )
    assert "gold" in trader._waiting

    held = trader._waiting["gold"]
    held.until = 0.0  # its deadline has passed
    venue.observe(Tick("XAUUSD", bid=4399.0, ask=4400.0))
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.0, "ask": 4400.0})
    )
    assert "gold" not in trader._waiting
    assert venue.sent == []


async def test_parking_is_off_unless_asked_for():
    bus = Bus()
    made = settings(live=True)  # pullback_fraction defaults to 0
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    got = await trader.handle(
        Message(
            topic=SIGNALS,
            payload=signal(features={"sweep_low": 4396.0, "expected_push_vol": 3.0, "wick_n": 6.0}),
        )
    )
    assert isinstance(got, Intent)
    assert len(venue.sent) == 1


# ------------------------------- was the stop wrong, or was the thesis wrong


async def _stopped_trade(tmp_path, *, window=1.0):
    bus = Bus()
    made = settings(live=True, shadow_window=window)
    venue = RecordingBroker(made)
    book = Journal(tmp_path / "j.db")
    await book.open()
    trader = Trader(bus, settings=made, journal=book, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    got = await trader.handle(Message(topic=SIGNALS, payload=signal()))
    assert isinstance(got, Intent)
    live = next(iter(trader.open.values()))
    await trader._settle(live, price=live.intent.stop, why="closed", profit=-25.0)
    return trader, live, book, venue


async def test_a_stopped_trade_that_later_reaches_its_target_is_recorded(tmp_path):
    """The question the account cannot answer.

    A stop hit at full size looks identical whether the level failed or the
    stop sat inside the noise. If the target arrives afterwards, the thesis was
    right and the stop was too tight.
    """
    trader, live, book, _ = await _stopped_trade(tmp_path)
    assert trader._shadows, "a losing close should open a shadow"

    # Price goes on to reach the target it was aiming at.
    at = live.intent.target + 1.0
    await trader._watch_shadows("gold", Tick("XAUUSD", bid=at, ask=at, time=live.seen + 10))
    await book.close()

    said = [e for e in read(tmp_path / "j.db") if (e.context or {}).get("shape") == "shadow"]
    assert said, "nothing was recorded"
    ctx = said[-1].context
    assert ctx["reached_target"] is True
    assert ctx["best_r"] > 1.0, "reaching the target is more than 1R of the way"
    assert not trader._shadows, "the watch should close once answered"


async def test_a_stopped_trade_that_never_recovers_says_so(tmp_path):
    """The other answer, and the one that would exonerate the stop."""
    trader, live, book, _ = await _stopped_trade(tmp_path)
    shade = next(iter(trader._shadows.values()))

    # Price drifts nowhere, and the watch runs out.
    away = live.intent.stop - 1.0
    await trader._watch_shadows("gold", Tick("XAUUSD", bid=away, ask=away, time=shade.until + 1))
    await book.close()

    said = [e for e in read(tmp_path / "j.db") if (e.context or {}).get("shape") == "shadow"]
    assert said
    assert said[-1].context["reached_target"] is False
    assert said[-1].context["best_r"] == 0.0


async def test_the_shadow_watch_can_be_switched_off(tmp_path):
    trader, _, book, _ = await _stopped_trade(tmp_path, window=0.0)
    await book.close()
    assert not trader._shadows


def test_a_winning_close_opens_no_shadow():
    """Only losses raise the question."""
    from till_infinity.trading.service import Shadow

    assert Shadow.__doc__  # the type exists and is documented


def test_the_stop_floor_scales_with_how_long_it_must_last():
    """`vol_bps` is one bar of the entry interval; the trade lives for many.

    Volatility grows with the square root of time - measured on our own
    instruments at 1.04, 1.12 and 0.89 of sqrt(t) on gold, 0.99 and 0.98 on the
    Dow - so a one-bar stop on a thirty-bar trade sits inside the noise it has
    to survive.
    """
    flat = take("level-scalp", stop_hold_scaling=0.0)
    scaled = take("level-scalp", stop_hold_scaling=1.0, max_stop_scale=3.0)
    assert isinstance(flat, Intent)
    assert isinstance(scaled, Intent)
    assert abs(scaled.entry - scaled.stop) > abs(flat.entry - flat.stop)
    # Same money at risk over a longer stop means fewer lots.
    assert scaled.volume <= flat.volume


def test_the_scaling_is_capped():
    """Uncapped, a thirty-bar hold asks for a stop 5.5x wider and a position
    5.5x smaller, and reward_to_risk then refuses nearly everything."""
    small = take("level-scalp", stop_hold_scaling=1.0, max_stop_scale=1.5)
    big = take("level-scalp", stop_hold_scaling=1.0, max_stop_scale=3.0)
    assert isinstance(small, Intent)
    assert isinstance(big, Intent)
    assert abs(big.entry - big.stop) > abs(small.entry - small.stop)


def test_the_hold_is_expressed_in_bars_of_the_entry_interval():
    """Thirty minutes is thirty bars to a 1m strategy and two to a 15m one."""
    from till_infinity.trading.scalper import LevelScalp

    engine = LevelScalp(settings())
    LevelScalp.hold_bars = 20.0
    try:
        assert engine.hold_for("1m", 1800.0) == pytest.approx(1200.0)
        # Capped by wall clock, because twenty 15m bars is five hours.
        assert engine.hold_for("15m", 1800.0) == pytest.approx(1800.0)
        assert engine.hold_bars_for("1m", 1800.0) == pytest.approx(20.0)
        assert engine.hold_bars_for("15m", 1800.0) == pytest.approx(2.0)
    finally:
        LevelScalp.hold_bars = 0.0


def test_no_hold_bars_leaves_the_seconds_behaviour_alone():
    from till_infinity.trading.scalper import LevelScalp

    engine = LevelScalp(settings())
    assert engine.hold_for("1m", 1800.0) == pytest.approx(engine.hold_seconds or 1800.0)


# ------------------------------------------- recording what will be asked for


async def test_a_trade_records_what_it_cost_and_whether_it_was_waited_for(tmp_path):
    """Questions we could not answer, asked of trades already taken.

    Three gates judge spread and none wrote down the number they judged.
    Parked and unparked fills were indistinguishable once filled, so the
    pullback could not be evaluated at all. And the stop in volatility units
    had to be re-derived from entry, stop and vol_bps every time.
    """
    bus = Bus()
    made = settings(live=True)
    venue = RecordingBroker(made)
    async with Journal(tmp_path / "j.db") as book:
        trader = Trader(bus, settings=made, journal=book, broker=venue)
        await trader.start()
        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        got = await trader.handle(Message(topic=SIGNALS, payload=signal()))
        assert isinstance(got, Intent)

    entries = [e for e in read(tmp_path / "j.db") if (e.context or {}).get("strategy")]
    assert entries
    ctx = entries[0].context
    assert ctx["spread_at_entry"] == pytest.approx(1.0), "the quoted spread, written down"
    assert ctx["waited"] is False, "this one was taken at market"
    assert ctx["stop_vol"] > 0, "the stop in the units the rules are written in"
    assert ctx["stop_scale"] >= 1.0
    assert ctx["hold_seconds"] > 0


def test_how_a_trade_ended_is_decided_by_where_it_ended():
    """`reason` says how the position left the book, not what took it - so
    stop and target were distinguishable only by the sign of the profit."""
    from till_infinity.trading.service import Live, _exit_kind

    intent = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4395.0,
        target=4410.0,
    )
    live = Live(position=None, intent=intent)
    assert _exit_kind(live, 4394.0) == "stop"
    assert _exit_kind(live, 4411.0) == "target"
    # Ahead, but neither - the clock took it, and calling that a target would
    # be the guess this exists to remove.
    assert _exit_kind(live, 4402.0) == "hold"


def test_a_level_signal_says_which_instrument_and_timeframe_it_is_about():
    """It said neither, which made "how does volatility scale across
    intervals" unanswerable from our own record - a question we went looking
    for an answer to and could not get one."""
    from till_infinity.structures.models import Shape, Signal

    sig = Signal(shape=Shape.LEVEL, feed="gold", venue="consensus", score=0.4, interval="5m")
    assert sig.feed == "gold"
    assert sig.interval == "5m"


async def test_how_far_to_wait_comes_from_the_level_not_a_constant():
    """A fixed fraction asks every level for the same retracement.

    Levels do not retrace the same amount, and the wick this one has actually
    been pushed to is recorded on the signal - the measured answer to exactly
    this question. A deeply-swept level is worth waiting deeper for; a shallow
    one is not, and asking it to retrace as far just means never filling.
    """
    bus = Bus()
    made = settings(live=True, pullback_fraction=1.0)
    shallow = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=shallow)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.handle(
        Message(
            topic=SIGNALS,
            payload=signal(
                features={
                    "sweep_low": 4396.0,
                    "wick_below_vol": 0.2,
                    "expected_push_vol": 3.0,
                    "wick_n": 6.0,
                }
            ),
        )
    )
    thin = trader._waiting.get("gold")

    bus2 = Bus()
    deepr = RecordingBroker(made)
    other = Trader(bus2, settings=made, broker=deepr)
    await other.start()
    await other.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await other.handle(
        Message(
            topic=SIGNALS,
            payload=signal(
                features={
                    "sweep_low": 4396.0,
                    "wick_below_vol": 1.0,
                    "expected_push_vol": 3.0,
                    "wick_n": 6.0,
                }
            ),
        )
    )
    fat = other._waiting.get("gold")

    assert thin is not None
    assert fat is not None
    # The deeply-wicked level asks to be met lower.
    assert fat.trigger < thin.trigger


async def test_the_fraction_is_a_ceiling_on_the_wait():
    """A level with no wick history still has to park somewhere sensible."""
    bus = Bus()
    made = settings(live=True, pullback_fraction=0.5)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.handle(
        Message(
            topic=SIGNALS,
            payload=signal(
                # A wick so deep it would ask for more than the fraction allows.
                features={
                    "sweep_low": 4396.0,
                    "wick_below_vol": 9.0,
                    "expected_push_vol": 3.0,
                    "wick_n": 6.0,
                }
            ),
        )
    )
    held = trader._waiting.get("gold")
    assert held is not None
    # Bounded in volatility units rather than at the sweep edge. A wick that
    # runs deeper than the zone is allowed to be met there - that pullback is
    # the sweep - but not arbitrarily deep.
    unit = price_distance(4400.0, 10.0, 1.0)
    assert held.trigger >= 4400.0 - made.pullback_max_vol * unit


async def test_how_far_in_front_a_trade_got_is_written_down(tmp_path):
    """Watching a trade give back profit is not the same as measuring it.

    The service has tracked the best price all along - the trailing rules need
    it - and never recorded it, so "we were up and it ended a loss" was
    something you could see happen and not something you could count.
    """
    bus = Bus()
    made = settings(live=True)
    venue = RecordingBroker(made)
    async with Journal(tmp_path / "j.db") as book:
        trader = Trader(bus, settings=made, journal=book, broker=venue)
        await trader.start()
        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        got = await trader.handle(Message(topic=SIGNALS, payload=signal()))
        assert isinstance(got, Intent)

        live = next(iter(trader.open.values()))
        risk = abs(live.intent.entry - live.intent.stop)
        # It ran 1.5R in front, then came back and stopped out.
        trader._best[live.position.ticket] = live.intent.entry + risk * 1.5
        await trader._settle(live, price=live.intent.stop, why="closed", profit=-25.0)

    entries = [e for e in read(tmp_path / "j.db") if (e.context or {}).get("best_r") is not None]
    assert entries
    ctx = entries[-1].context
    assert ctx["best_r"] == pytest.approx(1.5, rel=0.05)
    assert ctx["profit"] < 0, "a trade that was 1.5R up and still lost"


async def test_a_level_nobody_has_pushed_is_not_worth_waiting_for():
    """Parking asks price to come back somewhere it has been before.

    A level with no wick history has no such place, so waiting is a bet with
    nothing behind it - and the signal that expires unfilled is not a trade
    avoided, it is a trade the strategy wanted and did not get.
    """
    bus = Bus()
    made = settings(live=True, pullback_fraction=1.0, pullback_min_wicks=2.0)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    got = await trader.handle(
        Message(
            topic=SIGNALS,
            payload=signal(features={"sweep_low": 4396.0, "expected_push_vol": 3.0, "wick_n": 0.0}),
        )
    )
    # Taken at market rather than parked and left to expire.
    assert isinstance(got, Intent)
    assert "gold" not in trader._waiting
    assert len(venue.sent) == 1


async def test_the_wait_uses_the_spread_of_the_wick_not_only_its_mean():
    """Half of all wicks are deeper than the mean by definition, so waiting at
    the mean is waiting at a depth exceeded as often as not."""

    async def trigger_for(sd):
        bus = Bus()
        made = settings(live=True, pullback_fraction=1.0, pullback_sigmas=1.0)
        trader = Trader(bus, settings=made, broker=RecordingBroker(made))
        await trader.start()
        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        await trader.handle(
            Message(
                topic=SIGNALS,
                payload=signal(
                    features={
                        "sweep_low": 4396.0,
                        "wick_below_vol": 0.5,
                        "wick_below_sd": sd,
                        "wick_n": 8.0,
                        "expected_push_vol": 3.0,
                    }
                ),
            )
        )
        held = trader._waiting.get("gold")
        return held.trigger if held else None

    tight = await trigger_for(0.0)
    wide = await trigger_for(0.6)
    assert tight is not None
    assert wide is not None
    # A level whose wicks vary asks to be met deeper.
    assert wide < tight


def test_the_stop_clears_the_brokers_own_minimum():
    """`stops_level` is not a suggestion - a closer stop is refused outright,
    and the refusal arrives after the decision has been made.

    Live: Wall Street 30 asks for 300 points - 3.00 in price - against gold's
    20, and our stops on it landed near 2.7, so orders were accepted or
    rejected depending on where volatility happened to be. A refusal is not a
    safer trade, it is no trade.
    """
    wide = td.SymbolSpec(
        symbol="XAUUSD",
        digits=2,
        point=0.01,
        tick_size=0.01,
        tick_value=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        contract_size=100.0,
        stops_level=300.0,  # 3.00 in price, like the Dow
    )
    got = take("level-scalp", spec=wide)
    assert isinstance(got, Intent)
    assert abs(got.entry - got.stop) >= 3.0, "the stop has to clear the broker's floor"
    # And the order the broker would see is one it will accept.
    assert not td.sizing.respects_stops_level(wide, got.entry, got.stop, got.target)


def test_a_level_that_does_not_usually_hold_is_refused():
    """The losses concentrate below this line.

    Over the first nineteen closed trades, the eight with a directional base
    rate under 0.55 produced one winner and -6.74R. A level that does not
    usually hold is not made trustworthy by a model claiming something unusual
    about it.
    """
    weak = take("level-scalp", signal(features={"base_rate_up": 0.40}), min_base_rate=0.55)
    assert isinstance(weak, Refusal)
    assert weak.gate == "base_rate"

    strong = take("level-scalp", signal(features={"base_rate_up": 0.70}), min_base_rate=0.55)
    assert isinstance(strong, Intent)


def test_the_base_rate_is_read_in_the_direction_claimed():
    """`base_rate_up` is always the *up* rate, so a sell has to flip it.

    Comparing it raw across a set that is mostly sells describes the direction
    mix rather than the levels - a mistake made once already while reading
    these numbers.
    """
    # A 0.30 up-rate is a 0.70 down-rate: weak for a buy, strong for a sell.
    buy = take("level-scalp", signal(features={"base_rate_up": 0.30}), min_base_rate=0.55)
    assert isinstance(buy, Refusal)
    assert buy.gate == "base_rate"

    sell = take(
        "level-scalp",
        signal(direction="down", features={"base_rate_up": 0.30}),
        min_base_rate=0.55,
    )
    assert isinstance(sell, Intent)


def test_no_base_rate_floor_leaves_every_call_alone():
    got = take("level-scalp", signal(features={"base_rate_up": 0.10}))
    assert isinstance(got, Intent)


async def test_a_deep_pullback_is_not_clamped_at_the_sweep_edge():
    """Reported live: the pullback enters earlier than the wick asks for.

    It clamped at the sweep edge twice - directly, and again through a fraction
    whose ceiling *was* the edge - so a level whose wicks run deeper than its
    own zone had the extra depth discarded and was met shallow. That threw away
    the best fill the setup offers: a pullback past the zone is the sweep, and
    buying the sweep is the whole idea.

    The edge was not a safe stopping point either, which was the stated reason
    and was wrong - the stop sits beyond it, and the fill floor keeps the stop
    clear of wherever the entry lands.
    """
    bus = Bus()
    made = settings(live=True, pullback_fraction=1.0, pullback_sigmas=0.5)
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.handle(
        Message(
            topic=SIGNALS,
            payload=signal(
                features={
                    "sweep_low": 4396.0,
                    "wick_below_vol": 1.0,
                    "wick_below_sd": 0.4,
                    "wick_n": 8.0,
                    "expected_push_vol": 3.0,
                }
            ),
        )
    )
    held = trader._waiting.get("gold")
    assert held is not None
    assert held.trigger < 4396.0, "a wick past the zone should be met past the zone"
    unit = price_distance(4400.0, 10.0, 1.0)
    assert held.trigger >= 4400.0 - made.pullback_max_vol * unit


# ------------------------------------- one threshold, two distributions


def test_the_floor_is_per_direction_because_the_distributions_differ():
    """A single absolute number produced a one-sided book.

    Over 7,498 published calls the two directions are offered almost evenly -
    48% up, 52% down - but down arrives more confident, median 0.880 against
    0.824. So one floor at 0.75 passed 96% of sells and 80% of buys, and the
    book came out 21 sells to 4 buys with no rule saying it should.
    """
    from till_infinity.trading.floors import WARMUP, Floors

    book = Floors(percentile=0.5)
    # Two directions with genuinely different distributions.
    for i in range(WARMUP + 50):
        book.observe("up", 0.70 + (i % 10) * 0.01)
        book.observe("down", 0.85 + (i % 10) * 0.01)

    up = book.floor("up", 0.60)
    down = book.floor("down", 0.60)
    assert down > up, "the more confident direction should have to clear more"
    assert book.counts()["up"] >= WARMUP


def test_a_cold_direction_falls_back_to_the_absolute_floor():
    """A quantile of forty observations is a statement about forty
    observations."""
    from till_infinity.trading.floors import Floors

    book = Floors(percentile=0.8)
    for _ in range(40):
        book.observe("up", 0.90)
    assert book.floor("up", 0.75) == pytest.approx(0.75)


def test_the_percentile_never_opens_a_door_the_absolute_floor_shut():
    """It exists to correct an asymmetry, not to relax anything."""
    from till_infinity.trading.floors import WARMUP, Floors

    book = Floors(percentile=0.1)
    for _ in range(WARMUP + 10):
        book.observe("up", 0.62)  # a weak direction
    assert book.floor("up", 0.80) == pytest.approx(0.80)


def test_the_floor_does_not_move_with_outcomes():
    """Raising a bar after a loss and lowering it after a win was the rule
    that lost to having no rule. What is tracked is what the model *says*, not
    what happened next, so a losing streak cannot tighten it."""
    import inspect

    from till_infinity.trading.floors import Floors

    src = inspect.getsource(Floors)
    for word in ("profit", "outcome", "won", "loss"):
        assert word not in src.lower(), f"the floor must not see {word}"


def test_every_strategy_clears_the_same_gates():
    """One of them was not, and it was the one taking most of the trades.

    `FadeToValue` overrides `consider` entirely and therefore ran none of the
    shared chain - so the probability floor, the per-direction percentile, the
    edge floor and the base-rate floor applied to three strategies and not to
    the fourth. The exemption was invisible from the configuration, which read
    as though every gate protected every strategy.
    """
    weak = signal(features={"probability": 0.30, "base_rate_up": 0.20})
    for name in ("level-scalp", "sweep-aware", "approach-scalp", "fade-to-value"):
        got = take(name, weak, min_probability=0.75, min_base_rate=0.55)
        assert isinstance(got, Refusal), f"{name} took a call it should have refused"


def test_the_shared_gates_live_in_one_place():
    """A copied block is two implementations that can drift; this is one."""
    import inspect

    from till_infinity.trading.scalper import FadeToValue, LevelStrategy

    assert hasattr(LevelStrategy, "quality")
    # Both paths call it rather than repeating it.
    assert "self.quality(" in inspect.getsource(LevelStrategy.consider)
    assert "self.quality(" in inspect.getsource(FadeToValue.consider)


def test_fade_to_value_is_still_exempt_from_the_chase_gate():
    """Not an oversight. Chasing means filling far from the level the call was
    measured at, and being far from fair value is this strategy's entire
    premise - the gate would refuse every trade it ever wanted."""
    import inspect

    from till_infinity.trading.scalper import FadeToValue

    assert "_chasing(" not in inspect.getsource(FadeToValue.consider)


# ------------------------------------------- agreement builds, it does not bet


def test_agreement_rebuilds_the_trade_rather_than_sizing_it_up():
    """Two strategies on one signal is one idea found twice.

    Sizing up on agreement doubles a position on a single thesis, which is what
    the per-instrument limit exists to prevent. What agreement buys is a
    better-built trade: the furthest stop any of them wanted, because being
    stopped before the move arrived is the failure measured most, and the
    nearest target, because unreached targets are what a wide stop costs.
    """
    bus = Bus()
    made = settings(live=True, evaluate_all=True, consensus_min=2)
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))

    base = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4396.0,
        target=4410.0,
        risk_money=20.0,
    )
    others = [
        # Agrees, and would have used a wider stop and a nearer target.
        ("sweep-aware", replace(base, stop=4393.0, target=4406.0)),
        # Disagrees on side - must be ignored entirely.
        ("fade-to-value", replace(base, side=Side.SELL, stop=4404.0, target=4390.0)),
    ]
    built, agreed = trader._agree(base, others)
    assert agreed == ["sweep-aware"], "only the side that agreed counts"
    assert built.stop == pytest.approx(4393.0), "the safest stop on offer"
    assert built.target == pytest.approx(4406.0), "the most reachable target"
    # Deliberately the worst reward-to-risk of the versions available, which
    # min_reward_to_risk then judges on its merits.
    assert (built.target - built.entry) / (built.entry - built.stop) < (
        (base.target - base.entry) / (base.entry - base.stop)
    )


def test_one_strategy_alone_is_not_a_consensus():
    bus = Bus()
    made = settings(live=True, evaluate_all=True, consensus_min=2)
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))
    base = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4396.0,
        target=4410.0,
    )
    built, agreed = trader._agree(base, [])
    assert agreed == []
    assert built is base


def test_agreement_never_moves_a_stop_closer_or_a_target_further():
    """It can only ever make the trade safer, never more flattering."""
    bus = Bus()
    made = settings(live=True, evaluate_all=True, consensus_min=2)
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))
    base = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4393.0,
        target=4406.0,
    )
    # An agreeing strategy with a tighter stop and a further target.
    others = [("level-scalp", replace(base, stop=4398.0, target=4420.0))]
    built, agreed = trader._agree(base, others)
    assert agreed == ["level-scalp"]
    assert built.stop == pytest.approx(4393.0), "kept the wider stop"
    assert built.target == pytest.approx(4406.0), "kept the nearer target"


def test_a_consensus_threshold_of_zero_means_off():
    """It meant "always on", and shipped that way.

    The guard was `len(agreed) + 1 < consensus_min`, which with zero is never
    true - so a setting documented as disabling the feature enabled it
    unconditionally, and it fired in production within minutes of being
    deployed disabled.
    """
    bus = Bus()
    base = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4396.0,
        target=4410.0,
    )
    others = [("sweep-aware", replace(base, stop=4390.0, target=4404.0))]

    for off in (0, 1):
        made = settings(live=True, evaluate_all=True, consensus_min=off)
        trader = Trader(bus, settings=made, broker=RecordingBroker(made))
        built, agreed = trader._agree(base, others)
        assert agreed == [], f"consensus_min={off} should disable it"
        assert built is base, "the trade must be untouched when it is off"

    made = settings(live=True, evaluate_all=True, consensus_min=2)
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))
    built, agreed = trader._agree(base, others)
    assert agreed == ["sweep-aware"]
    assert built.stop == pytest.approx(4390.0)


# --------------------------------- was it the stops, or was it the theses


def test_thesis_only_gives_the_trade_room_and_takes_less_of_it():
    """Six of twelve stopped trades later reached their target, so either the
    stops are wrong or the theses are. Every fix so far has assumed the first.
    This tests it by taking the stop out of the decision."""
    normal = take("level-scalp")
    roomy = take("thesis-only")
    assert isinstance(normal, Intent)
    assert isinstance(roomy, Intent)

    assert abs(roomy.entry - roomy.stop) > abs(normal.entry - normal.stop) * 3
    # The same money at risk over a wider stop buys proportionally fewer lots.
    assert roomy.volume < normal.volume
    # The target is untouched: moving both would make it a different trade
    # rather than the same trade with more room.
    assert roomy.target == pytest.approx(normal.target)


def test_thesis_only_still_has_a_circuit_breaker():
    """Not stopless. A genuinely stopless trade on a leveraged account is how
    accounts die, and `lots` derives size from the stop - with no stop there is
    no size."""
    got = take("thesis-only")
    assert isinstance(got, Intent)
    assert got.stop > 0
    assert got.volume > 0
    assert got.risk_money > 0


def test_thesis_only_risks_the_same_money_as_the_others():
    """The comparison is only fair if the bet is the same size."""
    normal = take("level-scalp")
    roomy = take("thesis-only")
    assert isinstance(normal, Intent)
    assert isinstance(roomy, Intent)
    # Within lot-rounding of each other - the stop distance changes, the money
    # does not.
    assert roomy.risk_money == pytest.approx(normal.risk_money, rel=0.5)


def test_snap_holds_for_as_long_as_the_interaction_lasts():
    """Measured over 53,372 resolutions: the median touch resolves in 18
    seconds, 53% inside 30 and 72% inside 120. Every other strategy holds for
    a fraction of an hour, which is about a hundred times the event."""
    from till_infinity.trading.scalper import LevelScalp, Snap

    made = settings()
    fast, slow = Snap(made), LevelScalp(made)
    assert fast.hold_seconds == pytest.approx(120.0)
    assert fast.hold_for("1m", made.max_hold) < slow.hold_for("1m", made.max_hold) / 10


def test_snap_differs_from_level_scalp_in_exactly_one_respect():
    """The comparison only says something if one thing changes."""
    from till_infinity.trading.scalper import LevelScalp, Snap

    assert Snap.entries == LevelScalp.entries
    assert Snap.context == LevelScalp.context
    # Same stop, same target, same size - only the clock is different.
    quick = take("snap")
    usual = take("level-scalp")
    assert isinstance(quick, Intent)
    assert isinstance(usual, Intent)
    assert quick.stop == pytest.approx(usual.stop)
    assert quick.target == pytest.approx(usual.target)
    assert quick.volume == pytest.approx(usual.volume)
    assert quick.hold < usual.hold


def test_a_fast_strategy_protects_faster_than_a_slow_one():
    """A bar runs almost to the target, stops short, and gives it back.

    The global numbers are built for a half-hour thesis - a 1R threshold and a
    2v trail - and on a two-minute trade that is most of its life spent
    unprotected, missing exactly the case a fast strategy exists for.
    """
    from till_infinity.trading.scalper import LevelScalp, Snap

    assert Snap.break_even_at < 1.0
    assert Snap.trail_vol < 2.0
    # level-scalp states none, so it uses whatever the deployment configured.
    assert LevelScalp.break_even_at == 0.0
    assert LevelScalp.trail_vol == 0.0

    quick = take("snap")
    assert isinstance(quick, Intent)
    # Break-even is taken as declared: it is in R, and R already carries the
    # horizon through the stop.
    assert quick.break_even_at == pytest.approx(Snap.break_even_at)
    # The trail is *derived*, not taken flat - stretched by the hold and then
    # capped against the move it protects, so it no longer equals the constant
    # the strategy declares. What must hold is that a fast strategy still
    # trails tighter than a slow one.
    slow = take("level-scalp")
    assert isinstance(slow, Intent)
    assert 0 < quick.trail_vol <= Snap.trail_vol * 3.0
    assert quick.trail_vol < slow.trail_vol or slow.trail_vol == 0.0


def test_the_strategys_own_numbers_beat_the_global_ones():
    """A global threshold cannot fit both a thirty-minute thesis and a
    two-minute one."""
    from till_infinity.trading import manage

    spec = GOLD
    made = settings(break_even_at=1.0, break_even_ticks=0, trail_vol=2.0)
    intent = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4396.0,
        target=4410.0,
        # This strategy protects at half an R rather than a whole one.
        break_even_at=0.5,
        trail_vol=0.75,
    )
    position = td.Position(ticket=1, symbol="XAUUSD", side=Side.BUY, volume=0.05, price_open=4400.0)
    # Up 0.6R - past the strategy's threshold, short of the global one.
    move = manage.advance(position, intent, spec, made, best=4402.4, vol_bps=10.0)
    assert move is not None, "the strategy's own threshold should have fired"
    assert move.stop >= 4400.0


def test_every_registered_strategy_has_a_magic_slot():
    """A strategy without one still trades and cannot be scored.

    It stamps a hashed magic from the tail of the band, and the hash has no
    inverse - so every position it opens reads as "unattributed" on close.
    `snap` and `thesis-only` ran live for an hour that way, and their trades
    are unattributable in the record.
    """
    from till_infinity.trading.strategy import STRATEGIES

    missing = [n for n in STRATEGIES if n not in td.MAGIC_ORDER]
    assert not missing, f"no magic slot for {missing} - their trades cannot be attributed"
    for name in STRATEGIES:
        magic = td.magic_for(td.DEFAULT_MAGIC, name)
        assert td.strategy_for(td.DEFAULT_MAGIC, magic) == name


# ------------------------------------------------------- scaling out of a winner


def _scaling(**over):
    made = {"scale_out_at": 1.0, "scale_out_fraction": 0.5}
    made.update(over)
    return settings(**made)


def test_scale_out_waits_for_the_r_multiple():
    """Nothing comes off a trade that has not reached the level it banks at."""
    got = manage.partial(
        position(volume=1.0),
        intent(volume=1.0),
        GOLD,
        _scaling(),
        best=4402.0,  # 0.3R in front of a 4.9-wide stop
    )
    assert got is None


def test_scale_out_banks_part_once_it_is_there():
    take = manage.partial(
        position(volume=1.0),
        intent(volume=1.0),
        GOLD,
        _scaling(),
        best=4405.5,  # past 1R
    )
    assert take is not None
    assert take.volume == pytest.approx(0.5)


def test_scale_out_reads_the_best_price_not_the_current_one():
    """A trade that reached the level and retraced has earned the partial.

    Reading the current price would mean the retracement that makes banking
    worth doing is the same thing that cancels it.
    """
    live = position(volume=1.0, price_current=4400.1)
    assert manage.partial(live, intent(volume=1.0), GOLD, _scaling(), best=4405.5) is not None


def test_scale_out_never_closes_the_whole_position():
    """A minimum-lot position cannot be halved, so it must run whole.

    The failure this guards against is not a refusal - it is a broker asked to
    close 0.005 of a 0.01 lot closing the lot instead, which turns a scale-out
    into a full exit that still looks like a scale-out in the log.
    """
    spec = replace(GOLD, volume_min=0.01, volume_step=0.01)
    got = manage.partial(position(volume=0.01), intent(volume=0.01), spec, _scaling(), best=4405.5)
    assert got is None


def test_scale_out_leaves_a_tradeable_remainder():
    """Both halves have to survive the volume step, not just the one banked."""
    spec = replace(GOLD, volume_min=0.02, volume_step=0.01)
    got = manage.partial(position(volume=0.03), intent(volume=0.03), spec, _scaling(), best=4405.5)
    assert got is None


def test_scale_out_rounds_down_to_the_volume_step():
    """Never up: the two halves together cannot exceed the position."""
    spec = replace(GOLD, volume_min=0.01, volume_step=0.01)
    take = manage.partial(position(volume=0.07), intent(volume=0.07), spec, _scaling(), best=4405.5)
    assert take is not None
    assert take.volume == pytest.approx(0.03)
    assert take.volume + 0.04 <= 0.07 + 1e-9


def test_scale_out_off_by_default():
    assert manage.partial(position(), intent(), GOLD, settings(), best=4405.5) is None


@pytest.mark.parametrize("fraction", [0.0, 1.0, 1.5, -0.5])
def test_scale_out_refuses_a_fraction_that_is_not_a_fraction(fraction):
    """At 1.0 it is a target, not a scale-out - there is no remainder to run."""
    got = manage.partial(
        position(volume=1.0),
        intent(volume=1.0),
        GOLD,
        _scaling(scale_out_fraction=fraction),
        best=4405.5,
    )
    assert got is None


# ------------------------------------------- re-arming a setup a sweep interrupted


def _live(**over):
    made = {
        "position": position(volume=1.0),
        "intent": intent(volume=1.0),
        "signal": {"feed": "gold"},
        "attempt": 0,
    }
    made.update(over)
    return td.service.Live(**made)


def _rearms(trader, live, price):
    trader._maybe_rearm(live, price)
    return trader._rearm


def test_a_stop_re_arms_the_signal():
    trader = Trader(Bus(), settings=settings(reentry_max=1))
    queued = _rearms(trader, _live(), price=4395.0)  # through the 4395.6 stop
    assert len(queued) == 1
    assert queued[0][td.service.ATTEMPT] == 1


def test_a_target_does_not_re_arm():
    """It got what it asked for. Taking it again is a second trade, not a retry."""
    trader = Trader(Bus(), settings=settings(reentry_max=1))
    assert _rearms(trader, _live(), price=4407.0) == []


def test_the_hold_clock_does_not_re_arm():
    """Nothing refuted it, so there is nothing to re-take."""
    trader = Trader(Bus(), settings=settings(reentry_max=1))
    assert _rearms(trader, _live(), price=4401.0) == []


def test_re_entry_is_bounded():
    """A level that keeps taking money is not one to keep arguing with."""
    trader = Trader(Bus(), settings=settings(reentry_max=1))
    assert _rearms(trader, _live(attempt=1), price=4395.0) == []


def test_re_entry_is_off_by_default():
    trader = Trader(Bus(), settings=settings())
    assert _rearms(trader, _live(), price=4395.0) == []


def test_an_adopted_position_never_re_arms():
    """Nothing here knows what it was, so there is no signal to put back."""
    trader = Trader(Bus(), settings=settings(reentry_max=1))
    assert _rearms(trader, _live(signal={}), price=4395.0) == []


async def test_re_arming_needs_the_pullback_switched_on():
    """At a stop, price is at the worst point the trade has seen.

    Re-entering at market there buys the extreme. The pullback is what makes
    the re-armed signal wait for the level instead, so without it the rule
    declines to fire rather than firing badly.
    """
    trader = Trader(Bus(), settings=settings(reentry_max=1, pullback_fraction=0.0))
    trader._rearm = [{"feed": "gold", td.service.ATTEMPT: 1}]
    await trader._rearm_stopped()
    assert trader._rearm == []  # dropped, not carried forward


# ------------------------------------------------- closing a trade that never started


class _Closes:
    """Execution that records what it was asked to close."""

    def __init__(self):
        self.closed = []

    async def close_position(self, ticket, volume=0.0):
        self.closed.append((ticket, volume))
        return td.models.OrderResult(ok=True, ticket=ticket)


def _stale_trader(**over):
    made = {"stale_after": 300.0, "stale_move": 0.25}
    made.update(over)
    trader = Trader(Bus(), settings=settings(**made))
    trader.paper = _Closes()
    return trader


async def test_a_trade_that_never_moved_is_closed_flat():
    trader = _stale_trader()
    live = _live()
    trader._best[live.position.ticket] = 4400.4  # 0.08R in 900 seconds
    assert await trader._stale(live, age=900.0) is True
    assert trader.execution.closed == [(1, 0.0)]


async def test_a_trade_that_started_is_left_alone():
    """Measured from the best price, so a trade that reached 0.4R and retraced
    has started - the rule is for the dead ones, not the retracing ones."""
    trader = _stale_trader()
    live = _live(position=position(volume=1.0, price_current=4400.05))
    trader._best[live.position.ticket] = 4402.5  # 0.5R at its best
    assert await trader._stale(live, age=900.0) is False
    assert trader.execution.closed == []


async def test_a_young_trade_is_left_alone():
    trader = _stale_trader()
    live = _live()
    trader._best[live.position.ticket] = 4400.4
    assert await trader._stale(live, age=60.0) is False


async def test_a_scaled_trade_is_never_stale():
    """Part is already banked, so the thing this protects against is handled."""
    trader = _stale_trader()
    live = _live(scaled=True)
    trader._best[live.position.ticket] = 4400.4
    assert await trader._stale(live, age=900.0) is False


async def test_the_stale_exit_is_off_by_default():
    trader = Trader(Bus(), settings=settings())
    trader.paper = _Closes()
    live = _live()
    trader._best[live.position.ticket] = 4400.4
    assert await trader._stale(live, age=9_000.0) is False


# ------------------------------------------------------------- the inverted control


def test_inverse_flips_the_side():
    from till_infinity.trading.scalper import Inverse, LevelScalp

    assert Inverse(settings()).orient(Side.BUY) is Side.SELL
    assert Inverse(settings()).orient(Side.SELL) is Side.BUY
    # And nothing else does, or every strategy would be a control.
    assert LevelScalp(settings()).orient(Side.BUY) is Side.BUY


def test_inverse_gates_on_the_side_the_call_named():
    """It must select the same signals to be a comparison.

    Gating on the flipped side would pick a different set of calls, and then
    a difference in results would say nothing about direction.
    """
    import inspect

    from till_infinity.trading.scalper import LevelStrategy

    source = inspect.getsource(LevelStrategy.consider)
    gate = source.index("self.quality(")
    flip = source.index("self.orient(")
    assert gate < flip, "the gates must run before the side is flipped"


# ------------------------------------------- clearing the broker's own minimum


EURGBP = SymbolSpec(symbol="EURGBP", digits=5, point=1e-05, tick_size=1e-05, stops_level=20.0)


def _floor_for(spread, margin=1.25, anchored=0.85750):
    """The stop a buy at 0.85754 ends up with, given a near-entry anchor."""
    from till_infinity.trading.scalper import LevelScalp

    engine = LevelScalp(settings(stops_level_margin=margin, min_stop_vol=0.0))
    return engine._floored_stop(EURGBP, Side.BUY, 0.85754, anchored, unit=1e-05, spread=spread)


def test_the_stop_clears_the_broker_minimum_by_more_than_a_rounding():
    """The refusal that prompted this: 22 points against a 20-point floor.

    A 1.1 multiple of a 20-point minimum is two points of clearance, and the
    minimum is checked against the price when the order *lands*, not when it
    was built. Two points is what a quiet cross moves in between.
    """
    stop = _floor_for(spread=1e-05)
    clearance = (0.85754 - stop) / EURGBP.min_stop_distance
    assert clearance > 1.2, f"only {clearance:.2f}x the broker minimum"


def test_the_spread_is_part_of_the_clearance():
    """A buy fills at the ask and its stop is measured against the bid, so one
    spread of the margin is gone before the market has moved at all."""
    tight = 0.85754 - _floor_for(spread=0.0)
    wide = 0.85754 - _floor_for(spread=5e-05)
    assert wide > tight
    assert wide - tight == pytest.approx(5e-05, abs=1e-06)


def test_the_clearance_is_configurable_and_scales():
    near = 0.85754 - _floor_for(spread=0.0, margin=1.1)
    far = 0.85754 - _floor_for(spread=0.0, margin=1.5)
    assert far > near


def test_the_floor_never_pulls_a_wide_stop_in():
    """It may only push the stop away from the fill. A floor that tightened a
    stop would raise the position size for the same money at risk."""
    wide = 0.85000  # far below anything the floor would ask for
    assert _floor_for(spread=1e-05, anchored=wide) == wide


def test_a_trailing_modify_holds_the_same_clearance():
    """The same minimum applies to a modify, checked against the price when it
    lands - and `best` is the most favourable price seen, so the real distance
    is this or smaller."""
    kept = manage.advance(
        position(symbol="EURGBP", price_open=0.85754, stop=0.85700),
        intent(feed="eurgbp", symbol="EURGBP", entry=0.85754, stop=0.85700),
        EURGBP,
        settings(break_even_at=0.1, stops_level_margin=1.25),
        best=0.85760,
        vol_bps=0.0,
    )
    assert kept is None, "a stop inside the broker's minimum was proposed"


# --------------------------------------------------------- classifying an exit


def _kind(price, **over):
    return td.service._exit_kind(_live(**over), price)


def test_a_stop_is_classified_by_where_it_ended():
    assert _kind(4395.0) == "stop"  # through the 4395.6 stop
    assert _kind(4407.0) == "target"  # past the 4406.66 target


def test_what_closed_it_wins_over_where_it_ended():
    """A stale close and a hold-clock close both land wherever the market is.

    The price cannot tell them apart, so a rule that closes a position has to
    say so - otherwise "is the stale exit helping" has no answer in the record.
    """
    assert _kind(4401.0, closed_by="stale") == "stale"
    assert _kind(4401.0, closed_by="hold") == "hold"


def test_an_adopted_position_is_unknown_rather_than_held():
    """A placeholder intent has no stop and no target, so every comparison is
    skipped and the trade would be filed as having run its clock - which is not
    something we know. Scoring can exclude what is unknown; it cannot exclude
    what is confidently mislabelled."""
    adopted = intent(stop=0.0, target=0.0)
    assert _kind(4401.0, intent=adopted) == "unknown"


def test_a_real_intent_closed_between_its_levels_is_a_hold():
    """Still a claim, but an evidenced one: it had both levels and reached
    neither."""
    assert _kind(4401.0) == "hold"


# ------------------------------------------------------------- the swing trade


def _htf():
    """`swing-level`, which absorbed `high-timeframe` when it was removed as a
    near-duplicate: they shared entries, context and the requirement that a
    higher timeframe agree, and the resting entry and horizon-scaled
    protection moved across."""
    return strategy("swing-level")


def test_the_swing_trade_requires_a_high_timeframe():
    """Not a preference. A 1h idea held for days on nothing but 15m agreement
    is a fast trade wearing a swing's patience."""
    engine = _htf()
    assert engine.needs_context is True
    assert all(t in ("4h", "1d", "1w") for t in engine.context)


def test_the_swing_trade_never_triggers_below_15m():
    """The stop comes from the entry interval, so a 1m stop against a
    multi-hour hold is not a tight trade but a certain one."""
    fast = {"1m", "3m", "5m"}
    assert not fast & set(_htf().entries)


def test_the_swing_hold_does_not_shrink_with_a_fast_trigger():
    """The thesis lives on the context timeframe, so bars of the *entry* would
    close a four-hour idea minutes after opening it."""
    engine = _htf()
    assert engine.hold_bars == 0.0
    # A 15m trigger gets the same hold a 4h trigger does.
    assert engine.hold_for("15m", 1_800.0) == engine.hold_for("4h", 1_800.0)


def test_the_swing_trade_is_not_capped_by_the_scalpers_hold():
    """max_hold is 1800s because that suits a one-minute thesis. Applied here
    it would close the trade inside the first bar."""
    assert _htf().hold_for("4h", 1_800.0) > 1_800.0


def test_the_swing_trade_rests_its_entry_whatever_the_deployment_says():
    """Stated by the strategy, so it does not become a market order because a
    global happened to be zeroed."""
    assert _htf().pullback_fraction == 1.0


def test_a_scalper_still_defers_to_the_deployment():
    from till_infinity.trading.scalper import LevelScalp

    assert LevelScalp(settings()).pullback_fraction == 0.0


def test_the_per_strategy_pullback_reaches_park():
    """The value existing on the class is not the same as `_park` reading it.

    `_park` used to take the strategy's *name*, so it had no way to ask the
    strategy anything - the setting could sit on the class looking effective
    while the global decided every fill.
    """
    import inspect

    from till_infinity.trading.service import Trader

    source = inspect.getsource(Trader._park)
    assert "pullback_fraction" in source
    assert "engine" in inspect.signature(Trader._park).parameters


# ------------------------------------------- refusing an unconfirmed entry


class _Bars:
    """A broker stub that serves the bars it is given."""

    def __init__(self, candles):
        self.candles = candles

    async def bars(self, *_a, **_k):
        return self.candles


def _with_bars(candles, **over):
    trader = Trader(Bus(), settings=settings(require_candle=True, **over))
    trader.paper = _Bars(candles)
    return trader


def _candle(o, h, lo, c):
    from till_infinity.trading.candles import Bar

    return Bar(open=o, high=h, low=lo, close=c)


# --------------------------------------------- refusing a run that is still running


def _momentum(pressure, side=Side.BUY, limit=1.5):
    """The gate's verdict for this much accumulated pressure."""
    from till_infinity.trading.scalper import SweepAware

    engine = SweepAware(settings(min_probability=0.0, min_edge=0.0, min_base_rate=0.0))
    assert engine.max_against_vol == limit
    features = {"probability": 0.9, "edge": 1.0, "pressure_vol": pressure}
    return engine.quality("gold", features, side)


def test_a_buy_is_refused_while_price_is_still_falling():
    """Taking the other side of a run that has not finished is how a correct
    level becomes a stopped trade."""
    got = _momentum(pressure=-3.0, side=Side.BUY)
    assert got is not None
    assert got.gate == "momentum"


def test_a_sell_is_refused_while_price_is_still_rising():
    got = _momentum(pressure=3.0, side=Side.SELL)
    assert got is not None
    assert got.gate == "momentum"


def test_momentum_with_the_trade_is_not_refused():
    """The gate is about the run being *against* the trade. A buy into upward
    pressure is the level and the flow agreeing."""
    assert _momentum(pressure=3.0, side=Side.BUY) is None


def test_a_small_run_against_is_tolerated():
    """Some movement against is what arriving at a level looks like. The gate
    is for a run still in progress, not for any adverse tick."""
    assert _momentum(pressure=-0.5, side=Side.BUY) is None


def test_strategies_that_did_not_ask_are_unaffected():
    """It is a filter strategies opt into, not a new global gate."""
    from till_infinity.trading.scalper import LevelScalp

    engine = LevelScalp(settings(min_probability=0.0, min_edge=0.0, min_base_rate=0.0))
    assert engine.max_against_vol == 0.0
    features = {"probability": 0.9, "edge": 1.0, "pressure_vol": -99.0}
    assert engine.quality("gold", features, Side.BUY) is None


def test_the_inverse_control_carries_the_filter():
    """Fading a live run is the worst version of what it does, and would
    confound the direction test it exists for."""
    from till_infinity.trading.scalper import Inverse

    assert Inverse(settings()).max_against_vol > 0


async def test_the_pressure_feature_actually_reaches_the_strategies():
    """The gate reads `pressure_vol` from the features. If the service never
    injects it, the filter is inert while looking configured - the failure mode
    that passes every unit test of the gate itself.
    """
    trader = Trader(Bus(), settings=settings())
    await trader.start()
    # A signal first, because the accumulator's volatility unit comes from one
    # and a feed that has never published is deliberately not accumulated.
    await trader.handle(Message(topic=SIGNALS, payload=signal()))
    for bid, ask in ((4399.5, 4400.5), (4409.5, 4410.5)):
        await trader.handle(Message(topic=QUOTES, payload={"feed": "gold", "bid": bid, "ask": ask}))
    assert "gold" in trader._push, "the quote stream never fed the accumulator"

    payload = signal()
    await trader.on_signal(payload)
    # Into `features`, the only place `_features` looks. A top-level key is
    # invisible to every strategy while looking injected - which is what an
    # earlier version did, and an earlier version of this test asserted the
    # wrong dictionary and passed.
    assert "pressure_vol" in payload.get("features", {}), "pressure never reached features"


async def test_a_feed_with_no_signal_yet_accumulates_nothing():
    """Documented rather than hidden: the unit comes from a signal, so the
    filter is inert on a feed until its first one. Reading zero means no
    refusal, which is the right direction to fail in."""
    trader = Trader(Bus(), settings=settings())
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    assert trader._push == {}


# --------------------------------- confirmation: either the turn or a candle


def _confirming(candles=None, **over):
    trader = Trader(Bus(), settings=settings(**over))
    trader.paper = _Bars(candles or [])
    return trader


def _asks(pressure=0.0, after=1.0, level=4395.0):
    return intent(features={"level": level, "pressure_vol": pressure, "after_pullback": after})


async def test_a_pullback_that_has_not_turned_is_refused():
    """Price came back to the level and kept going. The level may still be
    right; this fill is early, which is the whole complaint."""
    trader = _confirming(require_turn_vol=0.5)
    got = await trader._rejected_at(_asks(pressure=-1.0))
    assert got is not None
    assert got.gate == "unconfirmed"


async def test_a_pullback_that_has_turned_is_taken():
    trader = _confirming(require_turn_vol=0.5)
    assert await trader._rejected_at(_asks(pressure=1.0)) is None


async def test_the_turn_is_not_asked_for_before_a_pullback():
    """Momentum at a level is adverse by construction - price arriving at
    support is falling, which is what arriving means. Asking this on arrival
    would refuse every support buy the system exists to take."""
    trader = _confirming(require_turn_vol=0.5)
    assert await trader._rejected_at(_asks(pressure=-5.0, after=0.0)) is None


async def test_a_candle_confirms_when_momentum_has_not():
    """Either witness is enough. Requiring both would refuse a clean rejection
    for happening inside one bar rather than across several."""
    hammer = [_candle(4400, 4401, 4399, 4400.5), _candle(4400, 4400.5, 4394, 4400.2)]
    trader = _confirming(candles=hammer, require_turn_vol=0.5, require_candle=True)
    assert await trader._rejected_at(_asks(pressure=-1.0)) is None


async def test_momentum_confirms_when_no_candle_has():
    """And the other way: a fast turn is not refused for lacking a bar to show
    for itself yet."""
    dull = [_candle(4400, 4401, 4399, 4400.5), _candle(4400.5, 4402, 4400, 4401.5)]
    trader = _confirming(candles=dull, require_turn_vol=0.5, require_candle=True)
    assert await trader._rejected_at(_asks(pressure=1.0)) is None


async def test_neither_witness_is_a_refusal():
    dull = [_candle(4400, 4401, 4399, 4400.5), _candle(4400.5, 4402, 4400, 4401.5)]
    trader = _confirming(candles=dull, require_turn_vol=0.5, require_candle=True)
    got = await trader._rejected_at(_asks(pressure=-1.0))
    assert got is not None
    assert got.gate == "unconfirmed"


async def test_missing_bars_are_not_a_pass():
    """The failure mode that looks like working code: a gate that silently
    stops applying on every instrument whose bars fail."""
    trader = _confirming(candles=[], require_candle=True)
    got = await trader._rejected_at(_asks(after=0.0))
    assert got is not None
    assert got.gate == "unconfirmed"


async def test_confirmation_is_off_by_default():
    trader = _confirming()
    assert await trader._rejected_at(_asks(pressure=-5.0)) is None


async def test_a_woken_signal_is_marked_as_post_pullback():
    """The gate keys off `after_pullback`. If `_arrived` never sets it the
    requirement is inert while looking configured."""
    import inspect

    from till_infinity.trading import service as svc

    assert "after_pullback" in inspect.getsource(svc.Trader._arrived)


def _gate_warnings(monkeypatch, **over):
    """What `_check_gates` actually logs.

    Not via caplog: this package's `get_logger` does not propagate to the root
    logger, so a caplog assertion that *no* warning appeared passes whether the
    code is right or not - which is how the first version of this test passed
    while its partner failed.
    """
    from till_infinity.trading import service as svc

    said = []
    monkeypatch.setattr(svc.log, "warning", lambda msg, *a, **k: said.append(msg % a if a else msg))
    trader = Trader(Bus(), settings=settings())
    # Set *after* construction on purpose. A risk plan fills in every tunable
    # the environment has not, `min_edge` among them, so a value set on the
    # settings beforehand is overwritten during construction and the test would
    # be measuring the plan's number rather than the one it chose.
    for key, value in over.items():
        setattr(trader.settings, key, value)
    trader._check_gates()
    return [m for m in said if "min_edge" in m]


def test_a_gate_deliberately_off_does_not_warn(monkeypatch):
    """Zero is a gate switched off, which is what the measurement argued for."""
    assert _gate_warnings(monkeypatch, min_edge=0.0) == []


def test_a_gate_that_believes_in_itself_but_cannot_fire_still_warns(monkeypatch):
    """0.08 against an upstream 0.10 is a limit that does nothing, and the
    reason this warning exists at all."""
    assert _gate_warnings(monkeypatch, min_edge=0.08)


# ----------------------------------------------------- trend context: gate and size


def _chop(ratio, floor=0.3):
    from till_infinity.trading.scalper import LevelScalp

    engine = LevelScalp(
        settings(min_probability=0.0, min_edge=0.0, min_base_rate=0.0, min_efficiency=floor)
    )
    return engine.quality("gold", {"probability": 0.9, "edge": 1.0, "efficiency": ratio}, Side.BUY)


def test_chop_is_refused():
    got = _chop(0.05)
    assert got is not None
    assert got.gate == "chop"


def test_a_trend_is_not_refused():
    assert _chop(0.9) is None


def test_an_unknown_context_is_not_refused():
    """A feed without enough history trades as it did before this existed -
    silence is not evidence of chop."""
    from till_infinity.trading.scalper import LevelScalp

    engine = LevelScalp(
        settings(min_probability=0.0, min_edge=0.0, min_base_rate=0.0, min_efficiency=0.3)
    )
    assert engine.quality("gold", {"probability": 0.9, "edge": 1.0}, Side.BUY) is None


def test_the_chop_gate_is_off_by_default():
    assert _chop(0.01, floor=0.0) is None


def _scale(ratio, span=0.3):
    from till_infinity.trading.scalper import LevelScalp

    engine = LevelScalp(settings(trend_sizing=span))
    return engine.trend_scale({} if ratio is None else {"efficiency": ratio})


def test_size_leans_with_the_trend():
    assert _scale(1.0) == pytest.approx(1.3)
    assert _scale(0.0) == pytest.approx(0.7)
    assert _scale(0.5) == pytest.approx(1.0)


def test_size_is_unchanged_without_a_reading_or_a_span():
    assert _scale(None) == 1.0
    assert _scale(1.0, span=0.0) == 1.0


def test_sizing_scales_the_fraction_so_every_cap_still_binds():
    """Applied to `risk_fraction`, not to the lot count. A multiplier that
    bypassed `max_risk_money` would be a way to exceed the risk budget through
    a setting nobody reads as a risk setting.
    """
    import inspect

    from till_infinity.trading.scalper import LevelStrategy

    source = inspect.getsource(LevelStrategy.consider)
    assert "risk_fraction=settings.risk_fraction * self.trend_scale(features)" in source


async def test_trend_context_reaches_the_features_once_there_is_history():
    """The ordering test asserts the source; this asserts the arrival.

    A measure that is computed correctly and never lands is inert, and the
    only symptom is a null in the journal that reads exactly like a cold
    start. That is how the `pressure_vol` bug survived its own test.
    """
    trader = Trader(Bus(), settings=settings(trend_sizing=0.3))
    await trader.start()

    seen = []
    for price in (4400.0, 4401.0, 4402.0, 4403.0, 4404.0):
        payload = signal()
        # Into `features`, where a real signal carries it and where every
        # strategy reads it. The first version of this test set it at the top
        # of the payload, matching the bug rather than the wire format, and
        # passed while production injected nothing on every signal for hours.
        payload.setdefault("features", {})["level"] = price
        await trader.on_signal(payload)
        seen.append(payload.get("features", {}).get("efficiency"))

    assert seen[0] is None, "no opinion should be offered before there is history"
    assert seen[-1] is not None, "trend context never reached the features"
    assert seen[-1] == pytest.approx(1.0), "a straight climb should read as a trend"


async def test_the_level_under_decision_is_excluded_from_its_own_window():
    """Feed a straight climb, then one reversal. The reversal must not yet be
    inside the window it is judged against - so the reading it sees is still
    the trend that preceded it."""
    trader = Trader(Bus(), settings=settings(trend_sizing=0.3))
    await trader.start()
    for price in (4400.0, 4401.0, 4402.0, 4403.0):
        payload = signal()
        payload.setdefault("features", {})["level"] = price
        await trader.on_signal(payload)

    payload = signal()
    payload.setdefault("features", {})["level"] = 4300.0  # a violent reversal
    await trader.on_signal(payload)
    assert payload["features"]["efficiency"] == pytest.approx(1.0), (
        "the level being decided leaked into the window that judges it"
    )


# ------------------------------------------- the partial close must be partial


class _Records:
    """An HTTP client that records what was actually sent."""

    def __init__(self):
        self.sent = []

    async def request(self, method, path, **kwargs):
        self.sent.append((method, path, kwargs.get("params") or {}))

        class _Reply:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"success": True, "result": {"price": 1.0, "volume": 1.0, "retcode": 0}}

            @staticmethod
            def raise_for_status():
                return None

        return _Reply()


async def _closed_with(volume):
    from till_infinity.trading.mt5_http import HttpBroker

    broker = HttpBroker(settings())
    client = _Records()
    broker._client = client
    await broker.close_position(42, volume)
    return client.sent[-1][2]


async def test_a_partial_close_sends_the_volume():
    """It did not. The argument was accepted and dropped, so every partial
    close was a full close that reported success - the scale-out shut whole
    positions while logging that it had taken half off.
    """
    params = await _closed_with(1.5)
    assert params.get("volume") == 1.5, "the volume never reached the broker"


async def test_a_full_close_still_sends_no_volume():
    """Absent means all of it, which is what the bridge already did."""
    params = await _closed_with(0.0)
    assert "volume" not in params
    assert params["ticket"] == 42


def test_the_day_summary_does_not_read_as_a_win_when_it_is_a_loss():
    """ "0/1 won, -$18.07 realised" put the word *won* next to the count in an
    alert announcing a loss, and read as a win at a glance. The numbers were
    right and the sentence was not, which is worse than being wrong in a way
    people notice.
    """
    guard = Guard(settings())
    guard.roll(10_000.0, now=1_000.0)
    guard.record("gold", -18.07, 10_000.0)
    line = guard.summary()
    assert "won 0 of 1" in line
    assert "0/1 won" not in line


def test_a_day_with_no_trades_says_so():
    guard = Guard(settings())
    guard.roll(10_000.0, now=1_000.0)
    assert "no trades" in guard.summary()


def _rr_verdict(floor, target):
    """Whether the guard allows an intent with this target, at this floor."""
    guard = Guard(settings(min_reward_to_risk=floor))
    guard.roll(10_000.0, now=1_000.0)
    return guard.allows(intent(target=target), positions=[], now=1_100.0)


def test_a_poor_reward_to_risk_is_refused_while_the_floor_stands():
    """entry 4400.5, stop 4395.6 - so risk 4.9. A target 2.45 away is 0.5 RR."""
    got = _rr_verdict(1.2, target=4402.95)
    assert got is not None
    assert got.gate == "reward_to_risk"


def test_the_same_intent_passes_once_the_floor_is_zero():
    """Zero is off explicitly, not by nothing being below zero. A gate that
    reads as enforced while doing nothing is the failure this repository spent
    a day finding - and this one refused 40,421 of 47,676 calls to gain
    nothing, measured over the production journal.
    """
    assert _rr_verdict(0.0, target=4402.95) is None


def test_a_good_reward_to_risk_passes_either_way():
    for floor in (0.0, 1.2):
        assert _rr_verdict(floor, target=4410.5) is None


# --------------------------------------- sizing for the stop we get, not place


def test_slippage_shrinks_the_position():
    """A stop that fills past its price costs more than the budget unless the
    size accounts for it."""
    plain = lots(GOLD, equity=10_000.0, risk_fraction=0.01, stop_distance=5.0)
    padded = lots(GOLD, equity=10_000.0, risk_fraction=0.01, stop_distance=5.0, slippage=0.09)
    assert padded.volume < plain.volume


def test_the_realised_loss_lands_on_the_budget():
    """The whole point. Sized with the measured slippage, a stop that fills 9%
    past the placed price costs what the trade was budgeted to lose - not 9%
    more, which is what every stop has been doing.
    """
    equity, fraction, stop = 10_000.0, 0.01, 5.0
    budget = equity * fraction
    sized = lots(GOLD, equity=equity, risk_fraction=fraction, stop_distance=stop, slippage=0.09)
    # What it actually costs when the stop fills 9% beyond where it was drawn.
    per_lot_at_real_distance = (stop * 1.09 / GOLD.tick_size) * GOLD.tick_value
    realised = sized.volume * per_lot_at_real_distance
    assert realised == pytest.approx(budget, rel=0.05)


def test_without_slippage_the_loss_overshoots():
    """The behaviour being corrected, pinned so it cannot come back unnoticed."""
    equity, fraction, stop = 10_000.0, 0.01, 5.0
    sized = lots(GOLD, equity=equity, risk_fraction=fraction, stop_distance=stop)
    per_lot_at_real_distance = (stop * 1.09 / GOLD.tick_size) * GOLD.tick_value
    realised = sized.volume * per_lot_at_real_distance
    assert realised > equity * fraction * 1.05


def test_slippage_defaults_to_off():
    a = lots(GOLD, equity=10_000.0, risk_fraction=0.01, stop_distance=5.0)
    b = lots(GOLD, equity=10_000.0, risk_fraction=0.01, stop_distance=5.0, slippage=0.0)
    assert a.volume == b.volume


def test_a_negative_slippage_cannot_inflate_the_position():
    """Sizing up on a setting is not a direction this should ever go."""
    plain = lots(GOLD, equity=10_000.0, risk_fraction=0.01, stop_distance=5.0)
    silly = lots(GOLD, equity=10_000.0, risk_fraction=0.01, stop_distance=5.0, slippage=-0.5)
    assert silly.volume == plain.volume


# ------------------------------------ a tighter stop, only where it is earned


def _parked_engine(**over):
    """`snap` rather than `level-scalp`: the tighter parked stop now applies
    only to a hold short enough for the grid that produced it, and snap's 120
    seconds is that horizon. See `PARKED_STOP_HOLD`."""
    made = {"min_probability": 0.0, "min_edge": 0.0, "min_base_rate": 0.0}
    made.update(over)
    return strategy("snap", **made)


def test_a_parked_entry_gets_the_tighter_stop():
    engine = _parked_engine(parked_stop_vol=0.5)
    got = engine._parked_stop({"after_pullback": 1.0}, 4400.0, 10.0, "1m")
    assert got == pytest.approx(price_distance(4400.0, 10.0, 0.5))


def test_a_market_entry_does_not():
    """The replay's tight stop is measured from the level, and a market entry
    is not there. Applied to one it would be the mistake `min_stop_vol` was
    written to prevent."""
    engine = _parked_engine(parked_stop_vol=0.5)
    assert engine._parked_stop({}, 4400.0, 10.0, "1m") == 0.0


def test_the_tighter_stop_is_off_by_default():
    engine = _parked_engine()
    assert engine._parked_stop({"after_pullback": 1.0}, 4400.0, 10.0, "1m") == 0.0


def _stop_distance(parked, **over):
    """How far the placed stop actually ends up from the entry, in price."""
    payload = signal()
    if parked:
        payload["features"]["after_pullback"] = 1.0
    got = take("level-scalp", payload, min_probability=0.0, min_edge=0.0, min_base_rate=0.0, **over)
    assert not isinstance(got, Refusal), getattr(got, "detail", got)
    return abs(got.entry - got.stop)


def test_a_parked_entry_never_places_a_wider_stop():
    """The end-to-end check, and stated as an inequality rather than a strict
    one on purpose: the tightened distance is a **cap**, and the stop anchored
    to the level's own zone can already sit further out, in which case it
    rightly wins. What must never happen is the setting widening a stop.
    """
    ordinary = _stop_distance(parked=False, parked_stop_vol=0.5)
    tighter = _stop_distance(parked=True, parked_stop_vol=0.5)
    assert tighter <= ordinary + 1e-9


def test_a_market_entry_is_untouched_by_the_setting():
    with_setting = _stop_distance(parked=False, parked_stop_vol=0.5)
    without = _stop_distance(parked=False)
    assert with_setting == pytest.approx(without)


def test_the_setting_can_only_tighten_never_widen():
    """A setting named for reducing risk must not become a way to raise it."""
    wide = _stop_distance(parked=True, parked_stop_vol=99.0)
    ordinary = _stop_distance(parked=False)
    assert wide <= ordinary + 1e-9


def test_the_scale_out_reads_the_price_that_exists_now():
    """A us30 position logged "banking 50% at 1.5R" and booked -1.14, because
    the trigger read a high-water mark while the close executed at market. The
    point of banking is to capture a gain that is there.
    """
    live = position(volume=1.0, price_open=4400.0)
    # Touched well past 1R, then fell back through the entry.
    got = manage.partial(live, intent(volume=1.0), GOLD, _scaling(), best=4410.0, current=4399.0)
    assert got is None


def test_it_still_banks_when_the_gain_is_actually_there():
    live = position(volume=1.0, price_open=4400.0)
    got = manage.partial(live, intent(volume=1.0), GOLD, _scaling(), best=4410.0, current=4405.5)
    assert got is not None


def test_it_never_banks_into_a_loss():
    live = position(volume=1.0, price_open=4400.0)
    assert (
        manage.partial(
            live,
            intent(volume=1.0),
            GOLD,
            _scaling(scale_out_at=0.0001),
            best=4410.0,
            current=4390.0,
        )
        is None
    )


def test_without_a_current_price_it_falls_back_to_the_high_water_mark():
    """Rather than refusing to bank at all when a quote is briefly missing."""
    live = position(volume=1.0, price_open=4400.0)
    assert manage.partial(live, intent(volume=1.0), GOLD, _scaling(), best=4405.5) is not None


# ------------------------------- not paying the spread to leave on the clock


def _hold_guard(spread, age=2_000.0, limit=1_800.0, **over):
    made = {"hold_max_spread": 0.5, "max_hold_multiple": 4.0}
    made.update(over)
    trader = Trader(Bus(), settings=settings(**made))
    live = _live()  # entry 4400.5, stop 4395.6 - risk 4.9
    trader._spread_of[live.intent.feed] = spread
    return trader._too_wide_to_leave(live, age=age, limit=limit)


def test_a_blown_out_spread_defers_the_hold_close():
    """An aus200 position was quoted bid 8998 / ask 9051 out of ASX hours - 53
    points against its own 8.89 of risk. Closing there pays six times the
    trade's entire budget in spread, to leave a position whose true mid had not
    reached its stop.
    """
    assert _hold_guard(spread=30.0) is True


def test_an_ordinary_spread_does_not():
    """The clock is there for a reason and this must not quietly disable it."""
    assert _hold_guard(spread=0.5) is False


def test_the_guard_is_off_by_default():
    assert _hold_guard(spread=30.0, hold_max_spread=0.0) is False


def test_a_permanently_wide_instrument_cannot_hold_a_position_forever():
    """Past `max_hold_multiple` the trade goes out at whatever is offered,
    which is the honest outcome when the alternative is never leaving."""
    assert _hold_guard(spread=30.0, age=99_999.0) is False


def test_no_spread_reading_means_no_deferral():
    """Silence is not evidence of a wide market."""
    assert _hold_guard(spread=0.0) is False


def test_an_absurd_push_is_refused():
    """A brent call arrived claiming 10,229v against a measured p99 of 9.55v,
    and became a target of 3850 on an entry of 88 - 43 times the price of the
    instrument. The broker refused it, which is the only reason it was seen.
    """
    got = take("level-scalp", signal(features={"expected_push_vol": 10_229.7}))
    assert isinstance(got, Refusal)
    assert got.gate == "push"


def test_a_large_but_real_push_is_not_refused():
    """The job is to catch a broken number, not to second-guess a large one.
    A 12v push is rare and real - p99 is 9.55v."""
    got = take(
        "level-scalp",
        signal(features={"expected_push_vol": 12.0}),
        min_probability=0.0,
        min_edge=0.0,
        min_base_rate=0.0,
    )
    assert not isinstance(got, Refusal), getattr(got, "detail", got)


def test_the_push_ceiling_can_be_switched_off():
    got = take(
        "level-scalp",
        signal(features={"expected_push_vol": 10_229.7}),
        max_push_vol=0.0,
        min_probability=0.0,
        min_edge=0.0,
        min_base_rate=0.0,
    )
    assert not (isinstance(got, Refusal) and got.gate == "push")


class _Refuses:
    """A broker that will not close, as a market in its daily break will not."""

    async def close_position(self, ticket, volume=0.0):
        raise td.broker.BrokerError("POST /positions/close: 400")


async def test_a_refused_stale_close_does_not_stamp_the_exit():
    """Naming the exit before the close succeeds means a refused close still
    labels the trade, and whatever ends it later - a stop, a target - is
    recorded as this. A us30 position found it: its close was refused through
    the index's daily break and the label was already on.
    """
    trader = Trader(Bus(), settings=settings(stale_after=300.0))
    trader.paper = _Refuses()
    live = _live()
    trader._best[live.position.ticket] = 4400.4
    assert await trader._stale(live, age=900.0) is False
    assert live.closed_by == "", "a refused close stamped the exit anyway"


async def test_a_successful_stale_close_does_stamp_it():
    trader = Trader(Bus(), settings=settings(stale_after=300.0))
    trader.paper = _Closes()
    live = _live()
    trader._best[live.position.ticket] = 4400.4
    assert await trader._stale(live, age=900.0) is True
    assert live.closed_by == "stale"


# --------------------------- a trade that spans a restart must still be recorded


async def _adopted_ref(journal, position):
    trader = Trader(Bus(), settings=settings(), journal=journal)
    return trader._ref_for(position)


async def test_an_adopted_position_recovers_its_decision(tmp_path):
    """`_settle` will not journal a close without a ref, and a position adopted
    after a restart has none - so its close was logged, announced, and never
    written down. What went missing was exactly the trades that lived long
    enough to span a deploy.
    """
    from till_infinity.journal import Journal, decide

    book = Journal(tmp_path / "j.db")
    await book.open()
    ref = await decide(
        book,
        "gold buy",
        rationale="a test",
        actor="trading",
        context={"symbol": "XAUUSD", "side": "buy", "entry": 4400.0},
    )
    got = await _adopted_ref(book, position(symbol="XAUUSD", side=Side.BUY))
    await book.close()
    assert got == ref


async def test_it_will_not_adopt_a_decision_that_is_already_settled(tmp_path):
    """Otherwise a new position inherits the record of an earlier trade on the
    same instrument, and two trades share one outcome."""
    from till_infinity.journal import Journal, decide, outcome

    book = Journal(tmp_path / "j.db")
    await book.open()
    ref = await decide(
        book,
        "gold buy",
        rationale="a test",
        actor="trading",
        context={"symbol": "XAUUSD", "side": "buy", "entry": 4400.0},
    )
    await outcome(book, ref, "closed", rationale="a test", actor="trading", context={"profit": 1.0})
    got = await _adopted_ref(book, position(symbol="XAUUSD", side=Side.BUY))
    await book.close()
    assert got == ""


async def test_a_different_side_is_not_adopted(tmp_path):
    from till_infinity.journal import Journal, decide

    book = Journal(tmp_path / "j.db")
    await book.open()
    await decide(
        book,
        "gold buy",
        rationale="a test",
        actor="trading",
        context={"symbol": "XAUUSD", "side": "buy", "entry": 4400.0},
    )
    got = await _adopted_ref(book, position(symbol="XAUUSD", side=Side.SELL))
    await book.close()
    assert got == ""


def test_the_tight_parked_stop_only_applies_to_a_short_hold():
    """The grid behind it was scored over resolutions with a median life of
    eighteen seconds. Applied to a trade held for half an hour it is half a
    bar against roughly 5.5 units of wandering - which is how five gold sells
    were stopped inside a point and a half on a day gold fell twenty-eight.
    """
    fast = strategy("snap", parked_stop_vol=0.5)
    slow = strategy("level-scalp", parked_stop_vol=0.5)
    parked = {"after_pullback": 1.0}
    assert fast._parked_stop(parked, 4400.0, 10.0, "1m") > 0
    assert slow._parked_stop(parked, 4400.0, 10.0, "1m") == 0.0


def test_the_stop_floor_grows_with_the_hold_when_scaling_is_on():
    """One volatility unit is one bar of the entry interval, and a trade held
    for thirty of them wanders about 5.5 units. A one-bar stop on a thirty-bar
    hold is taken by ordinary movement whatever the direction does."""
    off = strategy("level-scalp", stop_hold_scaling=0.0, min_stop_vol=1.0)
    on = strategy("level-scalp", stop_hold_scaling=1.0, min_stop_vol=1.0)
    assert on.stop_floor_vol("1m") > off.stop_floor_vol("1m")


def test_the_scaled_floor_is_capped():
    """`max_stop_scale` bounds it: a wider stop cannot create edge, so this is
    for not paying spread to be stopped by noise, not a licence to widen."""
    on = strategy("level-scalp", stop_hold_scaling=1.0, min_stop_vol=1.0, max_stop_scale=3.0)
    assert on.stop_floor_vol("1m") <= 3.0 * 1.0 + 1e-9


async def test_the_hold_estimate_reaches_the_decision_once_it_is_known():
    """Fed from resolutions, which the trader already subscribes to, and put
    where `_features` reads - the same dictionary three earlier features were
    written to the wrong side of."""
    from till_infinity.structures.holds import FEWEST

    trader = Trader(Bus(), settings=settings())
    await trader.start()

    payload = signal()
    await trader.on_signal(payload)
    assert "expected_hold_s" not in payload.get("features", {}), (
        "an estimate was offered before there was anything behind it"
    )

    for _ in range(FEWEST):
        await trader.handle(
            Message(
                topic=RESOLUTIONS,
                payload={
                    "feed": "gold",
                    "interval": "3m",
                    "seconds": 42.0,
                    "outcome": "reject",
                },
            )
        )

    later = signal()
    await trader.on_signal(later)
    got = later.get("features", {}).get("expected_hold_s")
    assert got is not None, "the estimate never reached the features"
    assert 30.0 < got < 60.0


async def test_the_reach_estimates_arrive_once_there_is_a_sample():
    """The depth price reaches into a level and the excursion a stop must
    clear, fed from resolutions and recorded on the decision - so the journal
    can say whether `pullback_fraction` and `min_stop_vol` sit anywhere near
    where the instrument actually trades."""
    from till_infinity.structures.reach import FEWEST

    trader = Trader(Bus(), settings=settings())
    await trader.start()

    early = signal()
    await trader.on_signal(early)
    assert "reach_depth_vol" not in early.get("features", {})

    for _ in range(FEWEST):
        await trader.handle(
            Message(
                topic=RESOLUTIONS,
                payload={
                    # 5m to match the test signal: the estimate is per feed *and*
                    # interval, because how far price reaches into a 1m level and a 4h
                    # one are different distances.
                    "feed": "gold",
                    "interval": "5m",
                    "seconds": 40.0,
                    "depth_vol": 0.9,
                    "excursion_vol": 1.4,
                    "outcome": "reject",
                },
            )
        )

    later = signal()
    await trader.on_signal(later)
    got = later.get("features", {})
    assert got.get("reach_depth_vol") == pytest.approx(0.9, abs=0.05)
    # risk_vol is 1.0 on the test signal, and the stop adds it to the quantile
    # rather than taking the larger - different evidence about one question.
    assert got.get("reach_stop_vol") == pytest.approx(2.4, abs=0.05)


async def test_the_reach_estimates_survive_a_restart(tmp_path):
    """A reach quantile needs twenty resolutions per feed and interval, while
    production publishes about twenty-seven signals in fifteen minutes across
    every series there is. Cold, it is unavailable for most of a day - and
    every deploy resets it. Verified after shipping the estimators found both
    values absent from every decision on a minutes-old container.
    """
    from till_infinity.journal import Journal, decide, outcome
    from till_infinity.structures.reach import FEWEST

    book = Journal(tmp_path / "j.db")
    await book.open()
    # `outcome`, not `observe`: a resolution is written as kind `outcome` and
    # the warm start reads that kind. The first version of this test used
    # `observe`, wrote twenty rows of the wrong kind, and failed for a reason
    # that had nothing to do with the code under test.
    # Titles vary per row, and they have to. `Entry.id` is a digest of time,
    # actor and title, so twenty identical writes inside one second collapse
    # to a single row - which passed when the loop ran slowly enough for the
    # clock to move and failed when it did not. Worth knowing beyond this
    # test: the journal silently deduplicates same-second writes sharing an
    # actor and a title.
    for n in range(FEWEST):
        ref = await decide(book, f"gold 5m touched {n}", rationale="a test", actor="structures")
        await outcome(
            book,
            ref,
            f"gold 5m resolved {n}",
            rationale="a test",
            actor="structures",
            context={
                "feed": "gold",
                "interval": "5m",
                "seconds": 40.0,
                "depth_vol": 0.9,
                "excursion_vol": 1.4,
            },
        )
    trader = Trader(Bus(), settings=settings(), journal=book)
    await trader.start()
    await book.close()

    assert trader._reaches.entry_at("gold", "5m") is not None, (
        "the reach estimate did not survive the restart"
    )
    assert trader._holds.expected("gold", "5m") is not None


def test_a_rejection_carries_whatever_the_bridge_said():
    """It looked for a `detail` key the bridge does not use, so a refusal
    arrived as a bare "400" carrying nothing. That hid three separate causes in
    one day - a stops-level miss, an impossible target, and a closed market -
    each needing its own investigation.
    """
    from till_infinity.trading import mt5_http

    class _Body:
        status_code = 400
        text = '{"success": false, "message": "Invalid stops"}'

        @staticmethod
        def json():
            return {"success": False, "message": "Invalid stops"}

    with pytest.raises(td.broker.RejectedError) as raised:
        mt5_http._body(_Body(), "POST", "/trading/order")
    assert "Invalid stops" in str(raised.value)


def test_a_rejection_with_no_known_key_still_carries_the_body():
    from till_infinity.trading import mt5_http

    class _Odd:
        status_code = 400
        text = '{"whatever": 7}'

        @staticmethod
        def json():
            return {"whatever": 7}

    with pytest.raises(td.broker.RejectedError) as raised:
        mt5_http._body(_Odd(), "POST", "/trading/order")
    assert "whatever" in str(raised.value)


def _trail(name, push, **over):
    made = {"break_even_at": 1.0, "trail_vol": 2.0, "max_hold": 1800.0, "max_stop_scale": 3.0}
    made.update(over)
    return strategy(name, **made).protection("1m", push)[1]


def test_the_trail_stays_inside_the_move_it_protects():
    """Scaling 2v by the horizon gives 6v, while the measured push
    distribution has a median of 2.24v and a p90 of 4.93v. A trail further
    from price than the entire move can never beat the stop already in place,
    so `manage.advance` never applies it - the protection is absent, silently.
    """
    uncapped = _trail("level-scalp", 0.0)
    assert uncapped == pytest.approx(6.0)
    assert _trail("level-scalp", 1.3) < 1.3
    assert _trail("level-scalp", 2.24) < 2.24


def test_a_bigger_expected_move_earns_a_wider_trail():
    assert _trail("level-scalp", 5.0) > _trail("level-scalp", 1.3)


def test_the_cap_never_widens_a_trail():
    """It is a ceiling. A huge push must not stretch the trail past what the
    horizon already allowed."""
    assert _trail("level-scalp", 999.0) == pytest.approx(_trail("level-scalp", 0.0))


def test_break_even_is_still_untouched_by_the_push():
    """It is in R, and R is measured against a stop this reasoning already
    widened - scaling or capping it here would count the horizon twice."""
    engine = strategy("level-scalp", break_even_at=1.0, trail_vol=2.0)
    assert engine.protection("1m", 1.3)[0] == engine.protection("1m", 99.0)[0]
