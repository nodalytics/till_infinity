"""Does the meta-learner actually see what the desk does?

Two defects made it mostly blind. `_credit` had one caller, inside the shadow
path, so real closes taught it nothing. And shadows come only from
`_also_wanted`, which `on_signal` skips whenever `parallel` is on - so on the
live desk the ledgers learned from parked signals alone.
"""

from __future__ import annotations

from till_infinity.bus import Bus
from till_infinity.trading import Settings
from till_infinity.trading.service import Trader
from till_infinity.trading.strategies.policy import family_of


def desk(**over) -> Trader:
    made = {"live": False, "parallel": True}
    made.update(over)
    return Trader(Bus(), settings=Settings(**made))


class TestARealCloseTeachesThePolicy:
    """**971 trades closed with real fills and the learner never heard.**

    A real outcome is the better evidence of the two: a shadow is followed on the
    quote stream and assumes its stop fills at the level, while a real one paid
    the spread, the slippage and whatever the broker gave.
    """

    def test_settling_a_trade_credits_both_ledgers(self):
        import asyncio

        from till_infinity.trading import service as svc
        from till_infinity.trading.models import Intent, Position, Side

        trader = desk()
        intent = Intent(
            feed="gold",
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.05,
            entry=4400.0,
            stop=4390.0,
            target=4420.0,
            interval="15m",
            risk_money=22.0,
        )
        position = Position(
            ticket=11, symbol="XAUUSD", side=Side.BUY, volume=0.05, price_open=4400.0
        )
        live = svc.Live(position=position, intent=intent, by="sweep-aware")

        asyncio.run(trader._settle(live, 4420.0, "target", profit=100.0))

        # The shape ledger, keyed by geometry.
        assert trader.policy.ledger.cells, "the shape policy learned nothing"
        # And the entry ledger, keyed by the strategy.
        arms = trader.entries.ledger.arms(family_of("gold"))
        assert "sweep-aware" in arms, sorted(arms)
        # +2R: the target was twice the risk away.
        assert arms["sweep-aware"].mean > 0, arms["sweep-aware"].mean

    def test_an_unattributed_close_credits_nothing(self):
        """A position adopted from the broker has no strategy to credit, and
        guessing one would put another strategy's record against it."""
        import asyncio

        from till_infinity.trading import service as svc
        from till_infinity.trading.models import Intent, Position, Side

        trader = desk()
        intent = Intent(
            feed="gold",
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.05,
            entry=4400.0,
            stop=4390.0,
            target=4420.0,
            interval="15m",
        )
        position = Position(
            ticket=12, symbol="XAUUSD", side=Side.BUY, volume=0.05, price_open=4400.0
        )
        live = svc.Live(position=position, intent=intent, by="")

        asyncio.run(trader._settle(live, 4420.0, "target", profit=100.0))

        assert not trader.entries.ledger.cells, "an unattributed close credited a strategy"


class TestParallelModeStillCollectsTheCounterfactual:
    def test_an_intent_refused_in_parallel_is_still_followed(self):
        """The three branches of `_take_all` that drop a formed intent - a slot,
        a guard, a size - each have to keep it. Otherwise enabling parallel to
        compare strategies is what stops the comparison."""
        from till_infinity.trading.models import Intent, Side

        trader = desk()

        class Engine:
            name = "level-scalp"

            def hold_for(self, interval):
                return 900.0

        intent = Intent(
            feed="gold",
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.05,
            entry=4400.0,
            stop=4390.0,
            target=4420.0,
            interval="15m",
        )

        class Quote:
            time = 1_700_000_000.0

        payload = {"feed": "gold", "interval": "15m", "features": {"regime": 1.0}}
        trader._shadow_unfilled(payload, Quote(), Engine(), intent)

        kept = trader._untaken.get("gold") or []
        assert len(kept) == 1, kept
        assert kept[0].by == "level-scalp"
        assert kept[0].hold == 900.0
        assert kept[0].interval == "15m"

    def test_every_dropped_branch_shadows(self):
        """Structural: a branch added later that drops an intent without keeping
        it would silently shrink the training set again."""
        import inspect

        from till_infinity.trading import service as svc

        body = inspect.getsource(svc.Trader._take_all)
        # Each `continue` that follows a formed Intent must be preceded by a
        # shadow. Count them rather than parse: three drops, three shadows.
        assert body.count("_shadow_unfilled") == 3, body.count("_shadow_unfilled")
