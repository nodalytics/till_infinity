"""The overnight swap: priced over a trade's planned hold, refused when it eats the target."""

from __future__ import annotations

import datetime as dt

import pytest

from till_infinity.strategies import Settings
from till_infinity.strategies import swap as sw
from till_infinity.strategies.models import Intent, Side, SymbolSpec
from till_infinity.strategies.risk import Guard


def utc(text: str) -> float:
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC).timestamp()


TUE = utc("2026-07-14 14:00")  # New York is UTC-4: the rollover is 21:00 UTC
WED = utc("2026-07-15 14:00")
FRI = utc("2026-07-17 14:00")
HOUR, DAY = 3600.0, 86_400.0

EURUSD = SymbolSpec(
    symbol="EURUSD",
    digits=5,
    point=1e-5,
    swap_long=-11.42,
    swap_short=2.66,
    swap_mode=1,
    swap_triple_day=3,
)
BOOM = SymbolSpec(
    symbol="Boom 1000 Index",
    digits=4,
    point=1e-4,
    swap_long=-36.0,
    swap_short=-36.0,
    swap_mode=5,
    swap_triple_day=7,
)


class TestNights:
    def test_an_intraday_hold_crosses_none(self):
        assert sw.nights(TUE, 2 * HOUR, 3) == 0.0

    def test_one_rollover_is_one_night(self):
        assert sw.nights(TUE, DAY, 3) == 1.0

    def test_the_triple_day_counts_three(self):
        assert sw.nights(WED, DAY, 3) == 3.0

    def test_fx_does_not_roll_at_the_weekend(self):
        # Friday's roll, then nothing until Monday 21:00 UTC, past the end
        assert sw.nights(FRI, 3 * DAY, 3) == 1.0

    def test_a_24_7_symbol_rolls_every_night(self):
        assert sw.nights(FRI, 3 * DAY, 7) == 3.0


class TestExpected:
    def test_points_are_priced_by_the_point(self):
        got = sw.expected(EURUSD, "eurusd", Side.BUY, 1.10, TUE, DAY)
        assert got == pytest.approx(11.42e-5)

    def test_a_credited_side_costs_nothing(self):
        assert sw.expected(EURUSD, "eurusd", Side.SELL, 1.10, TUE, DAY) == 0.0

    def test_interest_is_an_annual_rate_on_the_price(self):
        # Boom 1000: 36% a year is about 9.9 bps a night, either side
        got = sw.expected(BOOM, "boom_1000_index", Side.SELL, 10_000.0, TUE, DAY)
        assert got == pytest.approx(10_000.0 * 0.36 / 365)

    def test_the_deriv_table_stands_in_when_the_broker_says_nothing(self):
        bare = SymbolSpec(symbol="Boom 1000 Index")
        got = sw.expected(bare, "boom_1000_index", Side.BUY, 10_000.0, TUE, DAY)
        assert got == pytest.approx(10_000.0 * 0.36 / 365)

    def test_an_unknown_symbol_costs_nothing(self):
        assert sw.expected(None, "spx500", Side.BUY, 5000.0, TUE, 3 * DAY) == 0.0

    def test_intraday_costs_nothing(self):
        assert sw.expected(BOOM, "boom_1000_index", Side.BUY, 10_000.0, TUE, 2 * HOUR) == 0.0


def desk(**over) -> Guard:
    made = Settings()
    for k, v in over.items():
        setattr(made, k, v)
    guard = Guard(made, currency="USD")
    guard.roll(10_000.0, now=TUE - HOUR)
    return guard


def boom_intent() -> Intent:
    return Intent(
        feed="boom_1000_index",
        symbol="Boom 1000 Index",
        side=Side.BUY,
        volume=0.2,
        entry=10_000.0,
        stop=9_990.0,
        target=10_020.0,
        interval="1h",
        risk_money=2.0,
    )


def gate(guard: Guard, hold: float, spec=BOOM) -> str | None:
    got = guard.allows(boom_intent(), positions=[], now=TUE, hold=hold, spec=spec)
    return None if got is None else got.gate


class TestTheGate:
    def test_a_deriv_hold_across_nights_is_refused(self):
        # two nights of ~9.9 a night against a 20 target
        assert gate(desk(), 2 * DAY) == "swap"

    def test_an_intraday_hold_is_untouched(self):
        assert gate(desk(), 2 * HOUR) != "swap"

    def test_no_planned_hold_is_not_looked_at(self):
        assert gate(desk(), 0.0) != "swap"

    def test_switched_off_changes_nothing(self):
        off = desk(max_swap_fraction=0.0)
        on_intraday = desk()
        assert gate(off, 2 * DAY) == gate(on_intraday, 2 * HOUR)
