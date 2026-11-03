"""The cost of holding overnight, which neither spread gate can see.

`research/docs/carry.md` measured what this broker charges to hold a position
across the 17:00 New York rollover. On FX it is about the interbank
differential plus a markup, quoted in points: EURUSD pays -11.42 a night long
and is credited 2.66 short. On the 24/7 synthetics it is an **annual interest
rate charged on both sides** - Boom 1000 at 36% a year, about 9.9 basis points
a night - so there is no side of that market you can hold for free.

The numbers are small per night and the targets are small too, which is the
whole problem. A Boom 1000 trade aiming at 20 points and planning to hold two
nights pays about 19.7 of them in swap, so the geometry the strategy sized was
not the geometry it traded, and nothing in the spread gates or the risk
envelope was looking at the difference.

Three things are checked here, because the cost is a product of three and
getting any one wrong gives a plausible answer: how many rollovers a hold
crosses, what a night costs on each quoting convention, and that the gate
refuses the trade rather than merely recording the number.
"""

from __future__ import annotations

import datetime as dt

import pytest

from till_infinity.domain import swap as sw
from till_infinity.domain.models import Intent, Side, SymbolSpec
from till_infinity.risk.guard import Guard
from till_infinity.strategies import Settings


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
        """Spot settles two business days out, so Wednesday's rollover carries
        the weekend as well. A hold over one Wednesday night costs what three
        ordinary nights cost, and pricing it as one understates the whole
        trade by two."""
        assert sw.nights(WED, DAY, 3) == 3.0

    def test_fx_does_not_roll_at_the_weekend(self):
        # Friday's roll, then nothing until Monday 21:00 UTC, past the end
        assert sw.nights(FRI, 3 * DAY, 3) == 1.0

    def test_a_24_7_symbol_rolls_every_night(self):
        """The same three days that cost an FX pair one night cost a synthetic
        three. Both conventions live in one function because both are traded
        here, and the broker distinguishes them only by `swap_rollover3days`
        reading 7."""
        assert sw.nights(FRI, 3 * DAY, 7) == 3.0


class TestExpected:
    def test_points_are_priced_by_the_point(self):
        """`swap_long` is a count of the broker's points and not an amount of
        money, so a reading that skips the point is wrong by whatever the
        point happens to be - 100,000x on a 5-digit pair."""
        got = sw.expected(EURUSD, "eurusd", Side.BUY, 1.10, TUE, DAY)
        assert got == pytest.approx(11.42e-5)

    def test_a_credited_side_costs_nothing(self):
        """A positive swap is money paid to hold, and it is deliberately not
        counted. Carry is not an edge this desk has measured, and folding a
        credit in would let the gate pass a trade *because* it is held
        longer."""
        assert sw.expected(EURUSD, "eurusd", Side.SELL, 1.10, TUE, DAY) == 0.0

    def test_interest_is_an_annual_rate_on_the_price(self):
        # Boom 1000: 36% a year is about 9.9 bps a night, either side
        got = sw.expected(BOOM, "boom_1000_index", Side.SELL, 10_000.0, TUE, DAY)
        assert got == pytest.approx(10_000.0 * 0.36 / 365)

    def test_the_deriv_table_stands_in_when_the_broker_says_nothing(self):
        """A spec with no swap terms is the terminal being unhelpful, not a
        free position. Reading absence as zero would switch the gate off on
        exactly the symbols that cost the most to hold, so the table measured
        from this broker on 2026-09-30 stands in."""
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
    guard = Guard(made.envelope(), currency="USD")
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
        """The trade this file exists for. Boom 1000 at 36% a year is about
        9.9 points a night, so two nights cost about 19.7 against a target
        20.0 out - the strategy sized a 2R geometry and would have traded
        something close to flat."""
        assert gate(desk(), 2 * DAY) == "swap"

    def test_an_intraday_hold_is_untouched(self):
        """Most of what this desk trades closes the same session and pays no
        swap at all. A gate that charged them anyway would refuse the majority
        of the book over a cost it does not incur."""
        assert gate(desk(), 2 * HOUR) != "swap"

    def test_no_planned_hold_is_not_looked_at(self):
        """A strategy that declares no hold has not said it will keep the
        position, and guessing one would make the gate's answer depend on a
        number nobody set."""
        assert gate(desk(), 0.0) != "swap"

    def test_switched_off_changes_nothing(self):
        """Both halves, on the one hold that distinguishes them.

        The fraction is the only lever an operator has over this gate, so what
        has to hold is that the same trade is refused with it set and allowed
        with it at zero. Comparing the switched-off answer against some other
        scenario's would pass just as well if the gate had been deleted.
        """
        assert gate(desk(), 2 * DAY) == "swap"
        assert gate(desk(max_swap_fraction=0.0), 2 * DAY) is None
