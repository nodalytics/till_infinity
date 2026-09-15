"""Which instruments this account cannot afford, before one is signalled.

`sizing.lots` already refuses a trade whose minimum lot breaches the risk
budget, and it refuses **rather than rounding up**. So the per-trade guard is
sound and none of this is about that. What is tested here is the **catalogue**:
that refusal arrives one signal at a time, so without it an instrument nobody
can afford is watched, modelled, signalled and refused for ever, with nothing
anywhere saying "this feed is not tradeable at this equity".

Three things multiply into a verdict and only the first is obvious - the
minimum lot, the narrowest stop the broker will accept, and what a stop
actually costs once slippage is counted - so each has a test that would fail if
it were dropped.
"""

from __future__ import annotations

import pytest

from till_infinity.trading import affordable as af
from till_infinity.trading.models import SymbolSpec


def spec(
    symbol: str = "EURUSD",
    *,
    volume_min: float = 0.01,
    volume_step: float = 0.01,
    tick_size: float = 0.00001,
    tick_value: float = 0.1,
    stops_level: float = 0.0,
    digits: int = 5,
) -> SymbolSpec:
    return SymbolSpec(
        symbol=symbol,
        digits=digits,
        point=tick_size,
        tick_size=tick_size,
        tick_value=tick_value,
        volume_min=volume_min,
        volume_max=100.0,
        volume_step=volume_step,
        stops_level=stops_level,
    )


class TestOneInstrument:
    def test_a_normal_instrument_is_affordable(self):
        got = af.judge(
            spec(),
            feed="eurusd",
            equity=10_000.0,
            risk_fraction=0.0025,
            price=1.08,
            vol_bps=8.0,
        )
        assert got.verdict == "affordable"
        assert got.tradeable
        assert got.volume > 0.01

    def test_an_account_too_small_for_the_minimum_lot_is_refused(self):
        """The refusal `sizing.lots` already makes, named once instead of per signal."""
        got = af.judge(
            spec(), feed="eurusd", equity=50.0, risk_fraction=0.0025, price=1.08, vol_bps=8.0
        )
        assert got.verdict == "unaffordable"
        assert not got.tradeable
        assert "minimum" in got.reason

    def test_a_budget_that_buys_only_the_minimum_is_its_own_verdict(self):
        """Sizing has stopped being a lever: every trade is the same size
        whatever the conviction, which is worth knowing and is not a refusal."""
        # A 2v stop on EURUSD at 8bps costs 17.28 a lot, so the budget has to
        # land between one and two minimum lots: 100 x 0.25% = 0.25, which buys
        # 0.0145 and rounds down to the 0.01 floor.
        got = af.judge(
            spec(), feed="eurusd", equity=100.0, risk_fraction=0.0025, price=1.08, vol_bps=8.0
        )
        assert got.verdict == "minimum only"
        assert got.volume == pytest.approx(0.01)

    def test_a_position_that_can_take_a_fifth_of_the_account_is_unaffordable(self):
        """Even where the budget permits it. A single position that large is a
        different kind of risk from a budget overrun, and the budget is not
        always set with that in mind."""
        big = spec("Boom 1000 Index", volume_min=1.0, tick_size=0.01, tick_value=1.0)
        got = af.judge(
            big,
            feed="boom_1000",
            equity=2_000.0,
            risk_fraction=0.9,
            price=8_000.0,
            vol_bps=40.0,
        )
        assert got.verdict == "unaffordable"
        assert "of equity" in got.reason
        assert got.share_of_equity >= af.CATASTROPHIC

    def test_the_broker_s_own_minimum_stop_widens_the_trade(self):
        """A strategy stop inside `stops_level` is not the stop that gets
        placed, so pricing the instrument on it would call something affordable
        that is not."""
        tight = af.judge(
            spec(),
            feed="eurusd",
            equity=1_000.0,
            risk_fraction=0.0025,
            price=1.08,
            vol_bps=1.0,
            stop_units=1.0,
        )
        forced = af.judge(
            spec(stops_level=200.0),
            feed="eurusd",
            equity=1_000.0,
            risk_fraction=0.0025,
            price=1.08,
            vol_bps=1.0,
            stop_units=1.0,
        )
        assert forced.min_lot_risk > tight.min_lot_risk

    def test_slippage_makes_a_stop_cost_more_than_it_is_drawn_at(self):
        """A broker stop is a market order once triggered and fills through the
        spread. Sizing against the stop placed rather than the stop got breaches
        the budget on every loss, quietly and by a constant."""
        drawn = af.judge(
            spec(),
            feed="eurusd",
            equity=10_000.0,
            risk_fraction=0.0025,
            price=1.08,
            vol_bps=8.0,
            slippage=0.0,
        )
        real = af.judge(
            spec(),
            feed="eurusd",
            equity=10_000.0,
            risk_fraction=0.0025,
            price=1.08,
            vol_bps=8.0,
            slippage=0.087,
        )
        assert real.min_lot_risk > drawn.min_lot_risk
        assert real.volume <= drawn.volume

    def test_an_instrument_the_broker_prices_at_nothing_is_unknown_not_affordable(self):
        got = af.judge(
            spec(tick_value=0.0),
            feed="odd",
            equity=10_000.0,
            risk_fraction=0.0025,
            price=1.08,
            vol_bps=8.0,
        )
        assert got.verdict == "unaffordable"

    def test_no_stop_distance_is_unknown_rather_than_a_guess(self):
        got = af.judge(
            spec(),
            feed="eurusd",
            equity=10_000.0,
            risk_fraction=0.0025,
            price=1.08,
            vol_bps=0.0,
        )
        assert got.verdict == "unknown"

    def test_no_equity_is_unknown(self):
        got = af.judge(
            spec(), feed="eurusd", equity=0.0, risk_fraction=0.0025, price=1.08, vol_bps=8.0
        )
        assert got.verdict == "unknown"


class TestSurvey:
    @pytest.fixture
    def book(self):
        return {
            "eurusd": spec("EURUSD"),
            "boom_1000": spec("Boom 1000 Index", volume_min=1.0, tick_size=0.01, tick_value=1.0),
        }

    def test_every_instrument_is_judged_at_every_stop_width(self, book):
        got = af.survey(
            book,
            equity=5_000.0,
            risk_fraction=0.0025,
            prices={"eurusd": 1.08, "boom_1000": 8_000.0},
            vols={"eurusd": 8.0, "boom_1000": 40.0},
        )
        assert len(got) == len(book) * len(af.STOPS)

    def test_worst_first(self, book):
        """The question this exists to answer is whether one loss is survivable,
        not what the average outcome is."""
        got = af.survey(
            book,
            equity=5_000.0,
            risk_fraction=0.0025,
            prices={"eurusd": 1.08, "boom_1000": 8_000.0},
            vols={"eurusd": 8.0, "boom_1000": 40.0},
        )
        shares = [v.share_of_equity for v in got]
        assert shares == sorted(shares, reverse=True)

    def test_an_instrument_with_no_quote_is_skipped_not_guessed(self, book):
        got = af.survey(
            book,
            equity=5_000.0,
            risk_fraction=0.0025,
            prices={"eurusd": 1.08},
            vols={"eurusd": 8.0, "boom_1000": 40.0},
        )
        assert {v.feed for v in got} == {"eurusd"}

    def test_an_instrument_with_no_volatility_reading_is_skipped(self, book):
        """An assumed volatility is how an instrument gets called affordable
        that is not."""
        got = af.survey(
            book,
            equity=5_000.0,
            risk_fraction=0.0025,
            prices={"eurusd": 1.08, "boom_1000": 8_000.0},
            vols={"eurusd": 8.0},
        )
        assert {v.feed for v in got} == {"eurusd"}


class TestUnaffordable:
    def test_a_feed_refused_at_every_width_is_named(self):
        book = {"boom": spec("Boom 1000 Index", volume_min=5.0, tick_size=0.01, tick_value=1.0)}
        got = af.survey(
            book,
            equity=200.0,
            risk_fraction=0.0025,
            prices={"boom": 8_000.0},
            vols={"boom": 40.0},
        )
        assert af.unaffordable(got) == ["boom"]

    def test_affordable_at_one_width_is_not_named(self):
        """Any rather than all: an instrument affordable only at a four-sigma
        stop is affordable only for trades nobody wants to take, but it is not
        unaffordable, and calling it so would drop a feed the desk can use."""
        book = {"eurusd": spec("EURUSD")}
        got = af.survey(
            book,
            equity=10_000.0,
            risk_fraction=0.0025,
            prices={"eurusd": 1.08},
            vols={"eurusd": 8.0},
        )
        assert af.unaffordable(got) == []

    def test_nothing_surveyed_names_nothing(self):
        assert af.unaffordable([]) == []


class TestPublished:
    def test_a_verdict_serialises_to_plain_numbers(self):
        got = af.judge(
            spec(),
            feed="eurusd",
            equity=10_000.0,
            risk_fraction=0.0025,
            price=1.08,
            vol_bps=8.0,
        ).to_dict()
        assert got["feed"] == "eurusd"
        assert isinstance(got["share_of_equity"], float)
        assert got["verdict"] in {"affordable", "minimum only", "unaffordable", "unknown"}

    def test_it_is_not_the_other_verdict(self):
        """`trading.models.Verdict` is whether a *trade* passed its gates. Two
        objects with one name in a package is how a reader ends up sure they
        know what an import means."""
        from till_infinity.trading import models

        assert af.Affordability is not getattr(models, "Verdict", None)
