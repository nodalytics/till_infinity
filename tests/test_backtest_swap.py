"""The overnight financing a backtest charges, which it charged nowhere.

The catalogue's only cost is in its quotes: one per bar at the bar's close,
straddled by the feed's measured median spread. That is the round-trip cost
and it is the whole cost a run has ever paid - so a rule that holds for a week
was measured as though holding were free, while the live desk pays
`domain/swap.py`'s rates and `Guard` already refuses a trade whose expected
swap would take a quarter of its target.

`swap-does-not-cancel-in-a-long-short-basket` is the result that makes this
worth charging rather than noting: both legs of a market-neutral CFD basket
pay, so market-neutral is not carry-neutral.

**On top of the spread and not instead of it.** A 15-minute rule crosses no
rollover and owes nothing, which is the right answer and is also why swap
alone would make every intraday rule read as free.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from nautilus_trader.model.enums import PositionSide

from till_infinity.node import backtest
from till_infinity.node.corpus import instrument_for

DAY = 86_400.0
#: Tuesday 12:00 New York, so a one-day hold crosses exactly one 17:00
#: rollover and a 15-minute one crosses none. Stated rather than `time.time()`
#: because a test whose answer depends on the day it runs is not a test.
NOON = 1_762_866_000.0

#: A Deriv index, because the fallback table covers those and the catalogue
#: carries no broker swap for anything else - see `Swaps.unknown`.
SYNTHETIC = instrument_for("volatility_75_index", "SIM")
PAIR = instrument_for("eurusd", "SIM")


def _closed(instrument, held_s: float, side, quantity: float = 1.0, px: float = 100.0):
    return SimpleNamespace(
        side=side,
        ts_opened=int(NOON * 1e9),
        ts_closed=int((NOON + held_s) * 1e9),
        quantity=quantity,
        avg_px_open=px,
        instrument_id=instrument.id,
    )


def _engine(positions, instrument):
    return SimpleNamespace(
        cache=SimpleNamespace(
            positions_closed=lambda: list(positions),
            instrument=lambda _id: instrument,
        )
    )


def test_a_fifteen_minute_hold_crosses_no_rollover_and_owes_nothing():
    """**What makes this a cost of time and not of trading.** The spread is
    the round-trip cost and is already in the catalogue's quotes."""
    found = backtest.swap_charged(
        _engine([_closed(SYNTHETIC, 900.0, PositionSide.LONG)], SYNTHETIC)
    )
    assert found.positions == 1
    assert found.overnight == 0
    assert found.unknown == 0, "a hold that crossed nothing was blamed on a missing rate"
    assert found.charged == pytest.approx(0.0)


def test_an_overnight_hold_is_charged_at_the_measured_rate():
    """Volatility 75 runs 7.5% a year on **both** sides, measured off this
    broker on 2026-09-30: one night on one unit at 100 is 100 * 0.075 / 365."""
    found = backtest.swap_charged(_engine([_closed(SYNTHETIC, DAY, PositionSide.LONG)], SYNTHETIC))
    assert found.overnight == 1
    assert found.charged == pytest.approx(100.0 * 7.5 / 100.0 / 365.0)


def test_both_sides_pay_so_a_neutral_basket_is_not_carry_neutral():
    """`swap-does-not-cancel-in-a-long-short-basket`. A model that netted the
    legs would make a market-neutral CFD basket look carry-neutral, and it is
    not: the synthetics charge an annual rate on both sides."""
    one = backtest.swap_charged(_engine([_closed(SYNTHETIC, DAY, PositionSide.LONG)], SYNTHETIC))
    both = backtest.swap_charged(
        _engine(
            [
                _closed(SYNTHETIC, DAY, PositionSide.LONG),
                _closed(SYNTHETIC, DAY, PositionSide.SHORT),
            ],
            SYNTHETIC,
        )
    )
    assert both.overnight == 2
    assert both.charged == pytest.approx(one.charged * 2), "the short leg was credited"


def test_the_charge_scales_with_the_position_and_the_nights():
    big = backtest.swap_charged(
        _engine([_closed(SYNTHETIC, DAY, PositionSide.LONG, quantity=10.0)], SYNTHETIC)
    )
    small = backtest.swap_charged(
        _engine([_closed(SYNTHETIC, DAY, PositionSide.LONG, quantity=1.0)], SYNTHETIC)
    )
    assert big.charged == pytest.approx(small.charged * 10.0)

    week = backtest.swap_charged(
        _engine([_closed(SYNTHETIC, 7 * DAY, PositionSide.LONG)], SYNTHETIC)
    )
    assert week.charged == pytest.approx(small.charged * 7.0), "a synthetic rolls every night"


def test_a_pair_with_no_rate_is_counted_rather_than_read_as_free():
    """**The two readings of a zero.** The catalogue's instruments are
    Nautilus's standard conventions and carry no broker swap, so every rate
    comes from the Deriv fallback table and an FX pair has none. That is a
    missing number, not a free hold, and a total cannot tell them apart.
    """
    found = backtest.swap_charged(_engine([_closed(PAIR, DAY, PositionSide.LONG)], PAIR))
    assert found.charged == pytest.approx(0.0)
    assert found.overnight == 0
    assert found.unknown == 1, "a missing rate was reported as a free hold"
    assert "no rate" in str(found)


def test_an_emptied_cache_reports_no_positions_rather_than_no_swap():
    """`dispose_on_completion=True` empties the cache, and a run whose records
    were dropped must not read like a run that owed nothing."""
    assert backtest.swap_charged(_engine([], SYNTHETIC)).positions == 0
    assert backtest.swap_charged(SimpleNamespace(cache=None)).positions == 0


def test_the_charge_is_on_by_default_and_can_be_turned_off(monkeypatch):
    """On, because the cost is real and was charged nowhere. Off is for
    reproducing a number measured before it existed."""
    monkeypatch.delenv("BACKTEST_SWAP", raising=False)
    assert backtest.charges() is True
    monkeypatch.setenv("BACKTEST_SWAP", "0")
    assert backtest.charges() is False
