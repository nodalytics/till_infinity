"""One proposal on the bus, one order at the venue. The whole chain, once.

Every other test in this suite holds one link. This one runs the engine: a
quote feed into a `BacktestEngine`, an actor publishing a statespace proposal
onto `statespace.proposals`, a `SurpriseEdge` subscribed to it, and a venue at
the far end. Nothing is driven by hand - no handler is called directly, no
cache is pre-loaded, no method is stubbed.

**It would have failed on 2026-11-01 and the suite was green.** 2,227 tests
passed over a desk that could not place an order, for three reasons at once,
each of which looked like someone else's problem:

* nothing set `Intent.volume`, so a 5,136-bar replay accepted 25 intents and
  refused all 25 at `(desk):zero-volume`;
* `Profile.risk_scale` had no caller in `till_infinity/` at all;
* `Desk._spec` left the tick value on a dataclass default, so the money
  conversion was a coincidence that holds on the majors.

None of the three is visible from inside a unit test of the part that contains
it. The gates were tested and correct. The sizing arithmetic was tested and
correct. The adapter's routes were tested and correct. What nobody had asserted
was that the parts were connected, and they were not.

So this file is deliberately end to end, and deliberately small: two cases,
one where a trade is placed and one where it is refused for a reason that can
only come from the account. The engine's own account state is the thing being
leaned on - `portfolio.account(venue)` is `None` until a run starts, which is
why this cannot be done without `engine.run()` and is why it was never done.
"""

from __future__ import annotations

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig, BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, OrderStatus, PositionSide
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from till_infinity.strategies.config import Settings
from till_infinity.strategies.entries import EdgeEntryConfig
from till_infinity.strategies.surprise import SurpriseEdge
from till_infinity.utils.topics import PROPOSALS

VENUE = Venue("SIM")
EURUSD = TestInstrumentProvider.default_fx_ccy("EUR/USD", VENUE)
BAR_TYPE = BarType.from_str(f"{EURUSD.id}-1-HOUR-LAST-EXTERNAL")
SECOND = 1_000_000_000

#: Quotes before the proposal. Three, so the feed is warm and the proposal is
#: not racing the first tick into the cache - `_undealable` refuses on a
#: missing quote, and a test that happened to publish first would be asserting
#: that gate instead of this chain.
WARM = 3


class PitchConfig(ActorConfig, frozen=True):
    instrument_id: InstrumentId
    surprise: float = 4.2
    after: int = WARM


class Pitcher(Actor):
    """Stands in for `StatespaceActor`, publishing one proposal.

    The real actor is not used here on purpose. It would bring its own folds,
    its own warm-up and its own thresholds, and a failure anywhere in those
    would arrive looking like a failure of this chain. What this chain needs
    from a producer is one payload on one topic, which is all this sends - and
    it sends it through `msgbus.publish`, the same call `StatespaceActor`
    makes, so the subscription being tested is the real one.
    """

    def __init__(self, config: PitchConfig) -> None:
        super().__init__(config)
        self._seen = 0
        self.sent = 0

    def on_start(self) -> None:
        self.subscribe_quote_ticks(self.config.instrument_id)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self._seen += 1
        if self._seen != self.config.after:
            return
        self.sent += 1
        self.msgbus.publish(
            PROPOSALS,
            {
                "feed": "eurusd",
                "shape": "statespace",
                "interval": "5m",
                # The bar's own body, which is where the sign comes from - see
                # `statespace/proposing.py` on why it cannot come from the
                # variance fold.
                "direction": 1,
                "features": {
                    "surprise": self.config.surprise,
                    "vol_bps": 10.0,
                    "stop_vol": 2.0,
                    "target_r": 2.0,
                },
            },
        )


def quotes(count: int = 12) -> list[QuoteTick]:
    """A quiet, rising feed. The spread is half a point, which has to be well
    inside `Surprise`'s cost gate: the round trip may not exceed a tenth of the
    target, and at these numbers the target is 44 points."""
    return [
        QuoteTick(
            instrument_id=EURUSD.id,
            bid_price=Price(1.09995 + i * 1e-05, 5),
            ask_price=Price(1.10000 + i * 1e-05, 5),
            bid_size=Quantity(1_000_000, 0),
            ask_size=Quantity(1_000_000, 0),
            ts_event=i * SECOND,
            ts_init=i * SECOND,
        )
        for i in range(count)
    ]


def run(equity: float = 100_000.0, **pitch: object) -> tuple[SurpriseEdge, Pitcher]:
    """One backtest, from the quote feed to the venue's fills."""
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
        starting_balances=[Money(equity, USD)],
    )
    engine.add_instrument(EURUSD)
    engine.add_data(quotes())
    strategy = SurpriseEdge(EdgeEntryConfig(instrument_id=EURUSD.id, bar_type=BAR_TYPE))
    engine.add_strategy(strategy)
    pitcher = Pitcher(PitchConfig(instrument_id=EURUSD.id, **pitch))  # type: ignore[arg-type]
    engine.add_actor(pitcher)
    engine.run()
    return strategy, pitcher


def test_a_published_proposal_becomes_an_order_at_the_venue():
    """**The first trade.** Twenty-five accepted intents and no orders was the
    state this replaces, and the gate tally is asserted empty because the
    failure it is guarding against was a refusal rather than an error: the desk
    did everything right, counted a reason, and placed nothing."""
    strategy, pitcher = run()

    assert pitcher.sent == 1, "the producer never published"
    assert strategy.taken == 1
    assert strategy.refused == 0
    assert strategy.passed_over == {}, "a gate refused a trade this test expects taken"

    orders = strategy.cache.orders(strategy_id=strategy.id)
    assert len(orders) == 3, "a bracket is the entry and its two exits, as one order list"
    entry = next(o for o in orders if o.side == OrderSide.BUY)
    assert entry.status == OrderStatus.FILLED
    assert entry.quantity > 0


def test_the_position_risks_the_fraction_of_equity_it_was_sized_for():
    """The one number in the chain that has to be right to the cent.

    Asserted against the **stop the venue is holding** rather than against the
    sizer's own arithmetic, because the sizer agreeing with itself is what the
    unit tests already cover. What this adds is that the quantity which reached
    the venue and the stop which reached the venue multiply out to the budget -
    0.25% of 100,000 is 250 - so a rounding or a conversion lost between the
    two would show up here and nowhere else.
    """
    strategy, _ = run(equity=100_000.0)
    orders = strategy.cache.orders(strategy_id=strategy.id)
    entry = next(o for o in orders if o.side == OrderSide.BUY)
    stop = next(o for o in orders if o.side == OrderSide.SELL and o.trigger_price is not None)

    quantity = float(entry.quantity)
    distance = abs(float(entry.avg_px) - float(stop.trigger_price))
    # Loose by a dollar: the entry filled at the ask after three ticks of
    # drift, so the budget was divided by a slightly different stop distance
    # than the fill ended up being. A tolerance tight enough to catch a
    # conversion error and loose enough not to re-assert the fill price.
    assert quantity * distance == pytest.approx(100_000.0 * Settings().risk_fraction, abs=1.0)


def test_the_bracket_puts_the_stop_and_the_target_at_the_venue():
    """`Trader._protect` set them in a second call and had to handle the window
    where a position existed with no stop. A bracket has no such window, and
    the assertion is that both legs are live at the venue rather than held
    here: a stop this process is remembering is a stop that dies with it."""
    strategy, _ = run()
    orders = strategy.cache.orders(strategy_id=strategy.id)
    exits = [o for o in orders if o.side == OrderSide.SELL]
    assert len(exits) == 2
    assert all(o.status == OrderStatus.ACCEPTED for o in exits)
    held = strategy.cache.positions_open(strategy_id=strategy.id)
    assert [p.side for p in held] == [PositionSide.LONG]


def test_an_account_too_small_for_the_minimum_lot_places_nothing():
    """The affordability rail, from the account to the refusal.

    An equity of 100 risks 0.25 at 0.25%, and the minimum deal on this
    instrument is 1,000 units with a 22-point stop - so the smallest trade
    available costs nearly ten times the budget. Refused, and **not rounded
    up**: nudging it to the minimum would place a trade at forty times the risk
    anybody authorised, on an account that cannot absorb it.

    This is the one gate that cannot be reached without a real account, which
    is why it is here rather than in `test_sizes.py`.
    """
    strategy, pitcher = run(equity=100.0)

    assert pitcher.sent == 1
    assert strategy.taken == 0
    assert strategy.passed_over == {"(desk):unsized": 1}
    assert not strategy.cache.orders(strategy_id=strategy.id)


def test_a_proposal_below_the_threshold_is_declined_rather_than_placed():
    """The control for the two above. A chain that places an order whatever it
    is sent is not a chain under test - it is a chain with its decision
    removed, and both of the cases above would pass on one."""
    strategy, _ = run(surprise=1.0)

    assert strategy.taken == 0
    assert strategy.refused == 1
    assert strategy.passed_over == {"statespace-surprise:surprise": 1}
    assert not strategy.cache.orders(strategy_id=strategy.id)
