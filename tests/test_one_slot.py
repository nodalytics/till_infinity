"""One position per strategy per instrument, on every path to an order.

The rule lived only in `_take_all`. Three other paths reach `take`: the
non-parallel branch through `_agree`, a parked entry released when price comes back
to it, and a re-armed setup. Parking is the one that bit - the rule is applied when
the entry is parked and nothing checks again when it fills.

Found on the record for 09-15: `cycle-scalp` held step_index twice,
volatility_50_1s twice and jump_10 twice, each pair on the same interval with
different geometry (R:R 4.91 against 4.75, 0.57 against 0.62), so two separate
signals each became a position.
"""

from __future__ import annotations

import pytest

from till_infinity.bus import Bus
from till_infinity.trading import Settings
from till_infinity.trading.models import Intent, Position, Side
from till_infinity.trading.service import Live, Trader


def desk() -> Trader:
    trader = Trader(Bus(), settings=Settings(live=False))
    trader.guard.roll(10_000.0, now=1_000.0)
    trader.equity = 10_000.0
    return trader


def intent(feed: str = "gold", **over) -> Intent:
    made = {
        "feed": feed,
        "symbol": "XAUUSD",
        "side": Side.BUY,
        "volume": 0.05,
        "entry": 4400.0,
        "stop": 4390.0,
        "target": 4420.0,
        "interval": "15m",
        "risk_money": 22.0,
    }
    made.update(over)
    return Intent(**made)


def hold(trader: Trader, ticket: int, feed: str, by: str) -> None:
    trader.open[ticket] = Live(
        position=Position(
            ticket=ticket, symbol="XAUUSD", side=Side.BUY, volume=0.05, price_open=4400.0
        ),
        intent=intent(feed),
        by=by,
    )


class TestTakeRefusesADuplicate:
    async def test_the_same_strategy_cannot_hold_one_feed_twice(self):
        trader = desk()
        hold(trader, 1, "gold", "cycle-scalp")

        got = await trader.take(intent("gold"), "cycle-scalp")

        assert got.__class__.__name__ == "Refusal", got
        assert got.gate == "already_open", got.gate
        assert "cycle-scalp" in got.detail, got.detail
        assert "gold" in got.detail, got.detail

    async def test_a_different_strategy_on_the_same_feed_is_allowed(self):
        """**Deliberately.** `parallel` exists so every strategy that wants a
        signal takes it; the rule is one slot each, not one slot in total.
        `max_per_symbol` is the limit that counts positions regardless of who
        opened them."""
        trader = desk()
        hold(trader, 1, "gold", "cycle-scalp")

        got = await trader.take(intent("gold"), "sweep-aware")

        assert got.__class__.__name__ != "Refusal" or got.gate != "already_open", got

    async def test_the_same_strategy_on_a_different_feed_is_allowed(self):
        trader = desk()
        hold(trader, 1, "gold", "cycle-scalp")

        got = await trader.take(intent("btc"), "cycle-scalp")

        assert got.__class__.__name__ != "Refusal" or got.gate != "already_open", got

    async def test_an_unattributed_take_is_not_blocked(self):
        """A copy or a manual order has no strategy to compare, and refusing it on
        an empty name would block every one of them against the first position
        whose `by` was also empty."""
        trader = desk()
        hold(trader, 1, "gold", "")

        got = await trader.take(intent("gold"), "")

        assert got.__class__.__name__ != "Refusal" or got.gate != "already_open", got

    async def test_the_refusal_is_counted_so_it_is_visible(self):
        trader = desk()
        hold(trader, 1, "gold", "cycle-scalp")

        await trader.take(intent("gold"), "cycle-scalp")
        await trader.take(intent("gold"), "cycle-scalp")

        assert trader.passed_over.get("cycle-scalp:already_open") == 2, trader.passed_over


def test_the_rule_is_at_the_chokepoint_not_in_one_branch():
    """Structural, and it is the whole point of the fix. `take` is the single
    funnel every path to an order passes through, so a path added later cannot
    reintroduce the duplicate by forgetting to check."""
    import inspect

    from till_infinity.trading import service as svc

    body = inspect.getsource(svc.Trader.take)
    assert "already_open" in body, "take() must hold the rule itself"

    # And every caller of take() reaches it, so none of them needs its own copy.
    whole = inspect.getsource(svc)
    assert whole.count("await self.take(") >= 2, "expected several paths into take()"


@pytest.mark.parametrize("by", ["cycle-scalp", "thesis-only", "sweep-aware", "inverse"])
async def test_it_holds_for_the_strategies_that_actually_duplicated(by: str):
    """These four are the ones the record shows holding a feed twice."""
    trader = desk()
    hold(trader, 1, "volatility_25_index", by)

    got = await trader.take(intent("volatility_25_index"), by)

    assert got.gate == "already_open", (by, got)
