"""Managing a position after the trade is on.

The policy itself is `manage.py` and is tested by `test_manage.py`. What these
tests are for is the part that was tangled up in `Trader`: the tracking, the
ordering, and the two rules that are about *whether a rule applies at all*.
"""

from __future__ import annotations

import pytest
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from till_infinity.domain.models import Intent, Side
from till_infinity.strategies.config import Settings
from till_infinity.strategies.exits import Exits, closing_side

EURUSD = InstrumentId.from_str("EUR/USD.SIM")


def intent(**kwargs) -> Intent:
    base = {
        "feed": "eurusd",
        "symbol": "EUR/USD",
        "side": Side.BUY,
        "volume": 100_000.0,
        "entry": 1.1000,
        "stop": 1.0950,
        "target": 1.1100,
    }
    return Intent(**(base | kwargs))


def quote(bid: float, ask: float) -> QuoteTick:
    return QuoteTick(
        instrument_id=EURUSD,
        bid_price=Price(bid, 5),
        ask_price=Price(ask, 5),
        bid_size=Quantity(1_000_000, 0),
        ask_size=Quantity(1_000_000, 0),
        ts_event=0,
        ts_init=0,
    )


def exits(**kwargs) -> Exits:
    return Exits(settings=Settings.from_env(), **kwargs)


# ------------------------------------------------------------- the tracking


def test_the_best_price_is_the_side_the_position_closes_at():
    """A long is closed at the bid, so the best a long has seen is the highest
    **bid**. Using the wrong side flatters every trailing stop by one spread.
    """
    book = exits()
    book.opened("p1", intent(side=Side.BUY), when=0.0)
    book.observe("p1", quote(1.10500, 1.10520))
    held = book.held("p1")
    assert held.best == pytest.approx(1.10500), "the bid, not the ask"

    book.opened("p2", intent(side=Side.SELL, entry=1.1000), when=0.0)
    book.observe("p2", quote(1.09480, 1.09500))
    assert book.held("p2").best == pytest.approx(1.09500), "a short closes at the ask"


def test_the_best_price_never_moves_backwards():
    book = exits()
    book.opened("p1", intent(), when=0.0)
    book.observe("p1", quote(1.10500, 1.10520))
    book.observe("p1", quote(1.10100, 1.10120))
    assert book.held("p1").best == pytest.approx(1.10500)


def test_quotes_are_counted_since_the_position_opened():
    """`Trader` distinguished three causes of an untracked position, and this
    is the one that needed a count - a busy morning proves nothing about now.
    """
    book = exits()
    book.opened("p1", intent(), when=0.0)
    for _ in range(5):
        book.observe("p1", quote(1.10000, 1.10010))
    assert book.held("p1").quotes == 5


def test_a_quote_for_an_unknown_position_is_ignored():
    """It belongs to another strategy, and this component cannot reach it."""
    book = exits()
    book.observe("not-ours", quote(1.10000, 1.10010))
    assert book.tracking == 0


def test_closing_returns_what_was_known_and_forgets_it():
    book = exits()
    book.opened("p1", intent(), when=0.0)
    held = book.closed("p1")
    assert held is not None
    assert book.tracking == 0
    assert book.closed("p1") is None, "and closing twice is not an error"


# -------------------------------------------------------------- the staleness


def test_staleness_is_off_entirely_for_a_strategy_whose_thesis_is_duration():
    """**Not scaled to the declared hold - off.**

    The rule exists because a level touch resolves in eighteen seconds at the
    median and 84% inside five minutes; that premise is true of a scalp and
    false of a swing, at any length of clock. Scaling it was the first attempt
    and it was a half-measure: it made a rule proportional when the rule does
    not apply.
    """
    book = exits()
    book.settings.stale_after = 600.0
    book.opened("scalp", intent(), when=0.0)
    book.opened("swing", intent(stale_exempt=True), when=0.0)
    assert book.stale_after("scalp") > 0.0
    assert book.stale_after("swing") == 0.0
    assert book.is_stale("swing", now=10_000.0) is False


def test_the_minimum_hold_floors_staleness_or_it_is_defeated():
    """An expiry rule would keep a young trade and this would close it anyway.
    Both early closures have to respect the band the edge was measured in."""
    book = exits()
    book.settings.stale_after = 60.0
    book.settings.min_hold = 300.0
    book.opened("p1", intent(), when=0.0)
    assert book.stale_after("p1") == pytest.approx(300.0)
    assert book.is_stale("p1", now=120.0) is False, "inside the floor"
    assert book.is_stale("p1", now=400.0) is True


def test_staleness_can_be_switched_off_for_the_whole_component():
    book = exits(stale=False)
    book.settings.stale_after = 60.0
    book.opened("p1", intent(), when=0.0)
    assert book.stale_after("p1") == 0.0


def test_a_scaled_position_is_exempt_from_staleness():
    """It has already proved something."""
    book = exits()
    book.settings.stale_after = 60.0
    book.settings.min_hold = 0.0
    book.opened("p1", intent(), when=0.0)
    assert book.is_stale("p1", now=120.0) is True
    book.banked("p1")
    assert book.is_stale("p1", now=120.0) is False


def test_a_zero_stale_setting_means_off_rather_than_immediate():
    book = exits()
    book.settings.stale_after = 0.0
    book.settings.min_hold = 0.0
    book.opened("p1", intent(), when=0.0)
    assert book.stale_after("p1") == 0.0
    assert book.is_stale("p1", now=1e9) is False


# ------------------------------------------------------------- the banking


def test_a_decline_to_bank_says_which_of_the_five_reasons_it_was():
    """`partial` returned a bare None from five places, and `scale_out_at` sat
    at 1.0 for the life of the desk without a single scale-out firing - the
    shape `research/inert.md` catalogues: configured, correct and inert."""
    book = exits()
    book.opened("p1", intent(), when=0.0)
    take, why = book.bank_for("p1", position=None, spec=None)
    assert take is None
    assert why, "a decline with no reason is the bug this replaced"


def test_banking_an_already_scaled_position_declines_and_says_so():
    book = exits()
    book.opened("p1", intent(), when=0.0)
    book.banked("p1")
    take, why = book.bank_for("p1", position=None, spec=None)
    assert take is None
    assert why == "already scaled"


# ------------------------------------------------------------- the conflict


def test_a_trailing_order_is_reported_as_a_conflict():
    """Three things can trail a stop here - the bridge's twenty-second handler,
    Nautilus's native trailing order, and `advance` - and exactly one may.
    Two moving the same stop on different clocks is not a policy.
    """

    class Order:
        def __init__(self, name, oid):
            self.order_type = type("T", (), {"name": name})()
            self.client_order_id = oid

    found = Exits.conflicts(
        [
            Order("MARKET", "o1"),
            Order("TRAILING_STOP_MARKET", "o2"),
            Order("STOP_MARKET", "o3"),
        ]
    )
    assert found == ["o2"]
    assert Exits.conflicts([Order("MARKET", "o1")]) == []


def test_the_closing_side_is_the_other_one():
    assert closing_side(Side.BUY) is OrderSide.SELL
    assert closing_side(Side.SELL) is OrderSide.BUY


# --------------------------------------------------------------- the basket


def test_the_basket_is_an_actor_and_not_a_strategy():
    """Every other exit is the opening strategy's, because one that could close
    another strategy's position is the magic number bug wearing a new hat. This
    is the exception that proves it: its whole subject is *other strategies'*
    positions, so it cannot be any one strategy's.
    """
    from nautilus_trader.common.actor import Actor
    from nautilus_trader.trading.strategy import Strategy

    from till_infinity.strategies.basket import BasketConfig, BasketExit

    actor = BasketExit(BasketConfig(venue="SIM"))
    assert isinstance(actor, Actor)
    assert not isinstance(actor, Strategy)


def test_the_basket_publishes_a_close_rather_than_submitting_one():
    """An Actor submitting would do it under its own identity, and the
    position's `strategy_id` would stop naming what opened *and* closed it -
    which is the whole property this carve-up was for.
    """
    from till_infinity.strategies.basket import BasketConfig, BasketExit

    actor = BasketExit(BasketConfig(venue="SIM"))
    published: list[tuple[str, dict]] = []
    actor.publish_data_dict = lambda topic, payload: published.append((topic, payload))

    position = type(
        "P",
        (),
        {
            "id": "P-1",
            "strategy_id": "EdgeEntry-000",
            "instrument_id": "EUR/USD.SIM",
        },
    )()
    actor._close(position)

    assert len(published) == 1
    topic, payload = published[0]
    assert topic == "basket.close"
    assert payload["position_id"] == "P-1"
    assert payload["strategy_id"] == "EdgeEntry-000", "the owner is named, so it acts"
    assert not hasattr(actor, "order_factory"), "an actor has no order factory"


def test_one_leg_refusing_does_not_strand_the_rest():
    """An index in its daily break cannot be closed while the others still can,
    and leaving them open because of it is the opposite of what was asked for.
    """
    from till_infinity.strategies.basket import BasketConfig, BasketExit

    actor = BasketExit(BasketConfig(venue="SIM"))
    # The real policy, made to fire rather than stubbed: `Guard.basket` is
    # read-only, and a basket stop of 1% on a 100k book trips at -1,000.
    actor.settings.basket_stop_fraction = 0.01
    actor.guard.opening_equity = 100_000.0
    actor._equity = lambda: 100_000.0

    def positions():
        # Each leg is 500 down, so three of them are past the 1,000 stop.
        return [
            type(
                "P",
                (),
                {
                    "id": f"P-{i}",
                    "instrument_id": "EUR/USD.SIM",
                    "unrealized_pnl": lambda s, price: -500.0,
                },
            )()
            for i in range(3)
        ]

    calls: list[object] = []

    def closing(position):
        calls.append(position)
        if len(calls) == 2:
            raise RuntimeError("market closed")

    actor._close = closing
    actor.judge(positions(), lambda iid: 1.1)

    assert len(calls) == 3, "every leg was attempted"
    assert actor.closed == 2
    assert actor.failed == 1


def test_a_quiet_book_is_not_looked_at_twice():
    from till_infinity.strategies.basket import BasketConfig, BasketExit

    actor = BasketExit(BasketConfig(venue="SIM"))
    actor.judge([], lambda iid: 1.1)
    assert actor.looks == 1
    assert actor.closed == 0


def test_a_book_priced_at_its_own_opening_price_would_never_trip():
    """Pins the bug this replaced.

    The first version priced every position at its own `avg_px_open`, which
    makes `unrealized_pnl` zero by definition and the basket stop unreachable -
    configured, correct and inert, the exact shape `research/inert.md`
    catalogues. The pricer is required now, and this is why.
    """
    from till_infinity.strategies.basket import BasketConfig, BasketExit

    actor = BasketExit(BasketConfig(venue="SIM"))
    actor.settings.basket_stop_fraction = 0.01
    actor.guard.opening_equity = 100_000.0
    actor._equity = lambda: 100_000.0
    published: list[object] = []
    actor.publish_data_dict = lambda topic, payload: published.append(payload)

    def position(pnl_at):
        return type(
            "P",
            (),
            {
                "id": "P-1",
                "instrument_id": "EUR/USD.SIM",
                "strategy_id": "EdgeEntry-000",
                "unrealized_pnl": lambda s, price: pnl_at(price),
            },
        )()

    # Priced at the open, the loss is zero and nothing trips.
    actor.judge([position(lambda price: 0.0)], lambda iid: 1.1)
    assert not published

    # Priced at the market, the same book is 2,000 down and trips the 1% stop.
    actor.judge([position(lambda price: -2_000.0)], lambda iid: 1.09)
    assert published, "a book 2% down must trip a 1% basket stop"


def test_a_position_that_has_not_quoted_is_skipped_and_said_out_loud():
    """Zero is a number and "unknown" is not: counting an unpriced leg at zero
    would judge the book on the wrong total and say nothing about it."""
    from till_infinity.strategies.basket import BasketConfig, BasketExit

    actor = BasketExit(BasketConfig(venue="SIM"))
    actor.settings.basket_stop_fraction = 0.01
    actor.guard.opening_equity = 100_000.0
    actor._equity = lambda: 100_000.0
    actor.publish_data_dict = lambda topic, payload: None

    def leg(name):
        return type(
            "P",
            (),
            {
                "id": name,
                "instrument_id": name,
                "strategy_id": "EdgeEntry-000",
                "unrealized_pnl": lambda s, price: -2_000.0,
            },
        )()

    actor.judge([leg("quoted"), leg("silent")], lambda iid: 1.09 if iid == "quoted" else None)
    assert actor.unpriced == 1, "the skip is countable, not only loggable"

    # And the count is per look, not cumulative: a book that quotes next time
    # must not still report a stale skip.
    actor.judge([leg("quoted")], lambda iid: 1.09)
    assert actor.unpriced == 0
