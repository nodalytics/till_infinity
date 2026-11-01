"""The impulse features reaching the journal through `service.Trader`.

Split out of `tests/test_impulse.py` when `strategies/service.py` retired.
The features themselves are still tested there; what moved here is the
three tests that drove them through the retired runner.
"""

from __future__ import annotations

# ------------------------------------------- reaching the journal, through the service


class _Bars:
    """A broker stub that serves the bars it is given."""

    def __init__(self, candles):
        self.candles = candles
        self.asked = []

    async def bars(self, *a, **k):
        self.asked.append((a, k))
        return self.candles


def _trader(candles):
    from fake_carrier import FakeCarrier as Bus
    from till_infinity.strategies.service import Trader

    from till_infinity.strategies.config import Settings

    trader = Trader(Bus(), settings=Settings(symbols=("gold",)))
    trader.paper = _Bars(candles)
    trader._vol_bps["gold"] = 10.0
    return trader


def _intent():
    from till_infinity.domain.models import Intent, Side

    return Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.1,
        entry=4400.0,
        stop=4390.0,
        target=4420.0,
        interval="5m",
        features={},
    )


def _climb(n=260, step=4.0):
    """A rising series that gaps on every bar, so it displaces and leaves holes."""
    return [
        Bar(open=10 + step * i, high=11 + step * i, low=10 + step * i, close=11 + step * i)
        for i in range(n)
    ]


def test_a_decision_carries_the_displacement_and_the_imbalances():
    import asyncio

    trader = _trader(_climb())
    intent = _intent()
    asyncio.run(trader._read_the_trend(intent))
    assert intent.features["displacement_vol"] > 0
    assert intent.features["displacement_bars"] > 0
    assert "imbalance_n" in intent.features
    # And the channel it shares the fetch with is there too.
    assert "regression_slope_vol" in intent.features


def test_both_readings_come_from_one_fetch():
    """Two round trips to the broker for two readings of one series would be the
    only expensive part of either."""
    import asyncio

    trader = _trader(_climb())
    asyncio.run(trader._read_the_trend(_intent()))
    assert len(trader.paper.asked) == 1


def test_a_feed_with_no_volatility_unit_publishes_no_impulse_either():
    import asyncio

    trader = _trader(_climb())
    trader._vol_bps.pop("gold", None)
    intent = _intent()
    asyncio.run(trader._read_the_trend(intent))
    assert not [k for k in intent.features if k.startswith(("displacement", "imbalance"))]
