"""Displacement, imbalance, and the ways a lurch can be mis-read."""

from __future__ import annotations

import math

import pytest

from till_infinity.strategies.candles import Bar
from till_infinity.strategies.impulse import (
    MIN_GAP_VOL,
    SPAN,
    card_line,
    displacement,
    features,
    gaps,
)


def bars(rows):
    """`rows` of (open, high, low, close), or of (low, high) for a plain bar."""
    out = []
    for r in rows:
        if len(r) == 2:
            lo, hi = r
            out.append(Bar(open=lo, high=hi, low=lo, close=hi))
        else:
            o, h, lo_, c = r
            out.append(Bar(open=o, high=h, low=lo_, close=c))
    return out


def flat(n, lo=10.0, hi=11.0):
    return bars([(lo, hi)] * n)


# ------------------------------------------------------------------ displacement


def test_a_rising_window_displaces_up_and_a_falling_one_down():
    """Signed, and that is the point. `efficiency` went in unsigned and this
    repo's own note on it says the obvious way to trade it would have had the
    sign backwards."""
    up, took, age = displacement(bars([(10 + i, 11 + i) for i in range(5)]))
    assert up > 0
    assert took == 4
    assert age == 0
    down, took, age = displacement(bars([(10 - i, 11 - i) for i in range(5)]))
    assert down < 0
    assert took == 4
    assert age == 0


def test_the_leg_is_read_in_the_order_it_happened():
    """Up then back down is a *down* leg: the high came before the low, so the
    move that got us here is the fall, not the rise that preceded it."""
    rows = [(10, 11), (12, 13), (14, 15), (12, 13), (8, 9)]
    move, took, age = displacement(bars(rows))
    assert move < 0, "the high at bar 2 precedes the low at bar 4"
    assert took == 2
    assert age == 0


def test_an_older_leg_reports_its_age():
    rows = [(10, 11), (14, 15), (13, 14), (13, 14), (13, 14)]
    move, _took, age = displacement(bars(rows))
    assert move > 0
    assert age == 3, "three bars have closed since the high"


def test_a_window_with_nothing_in_it_has_no_leg():
    move, took, age = displacement(flat(5))
    assert math.isnan(move)
    assert (took, age) == (0, 0)
    assert math.isnan(displacement(bars([(10, 11)]))[0])


# ---------------------------------------------------------------------- imbalance


def test_a_three_bar_gap_is_found_with_its_edges():
    # bar 1 displaces: bar 2's low (14) clears bar 0's high (11).
    found = gaps(bars([(10, 11), (12, 16), (14, 18)]))
    assert len(found) == 1
    assert found[0].side == 1
    assert (found[0].low, found[0].high) == (11.0, 14.0)
    assert found[0].size == 3.0
    assert found[0].far == 14.0


def test_a_gap_down_is_found_the_same_way():
    found = gaps(bars([(14, 18), (12, 16), (10, 11)]))
    assert len(found) == 1
    assert found[0].side == -1
    assert (found[0].low, found[0].high) == (11.0, 14.0)
    assert found[0].far == 11.0


def test_overlapping_bars_leave_no_gap():
    assert gaps(bars([(10, 12), (11, 14), (11.5, 15)])) == []


def test_a_gap_price_has_traded_back_into_is_not_reported():
    """Unfilled is the whole claim. A hole price has come back through is
    history, and reporting it would put a level where there is none."""
    open_ = bars([(10, 11), (12, 16), (14, 18), (15, 19)])
    assert len(gaps(open_)) == 1
    filled = bars([(10, 11), (12, 16), (14, 18), (12, 19)])
    assert gaps(filled) == []


def test_a_gap_is_checked_against_the_whole_rest_of_the_window():
    """Not just the next bar: the question is "is that hole still there", not
    "was it skipped once"."""
    later = bars([(10, 11), (12, 16), (14, 18), (15, 19), (16, 20), (12.5, 20)])
    assert gaps(later) == []


def test_tick_sized_gaps_are_dropped_when_there_is_a_scale():
    tiny = bars([(10, 11.0), (12, 16), (11.01, 18)])
    assert len(gaps(tiny)) == 1, "no scale means every gap counts"
    # One unit is 10.0, so the 0.01 gap is far under MIN_GAP_VOL.
    assert gaps(tiny, unit=10.0) == []
    assert MIN_GAP_VOL > 0


# ----------------------------------------------------------------------- features


def test_features_need_a_volatility_unit():
    """Price-unit numbers under volatility-unit names would put one journal
    column in two scales, which is the failure this desk keeps finding."""
    rising = bars([(10 + i, 11 + i) for i in range(10)])
    assert features(rising, unit=0.0) == {}
    assert features(rising, unit=float("nan")) == {}
    assert features(rising, unit=-1.0) == {}
    assert features(rising, unit=1.0)


def test_features_are_in_volatility_units_and_signed():
    rising = bars([(10 + i, 11 + i) for i in range(10)])
    got = features(rising, unit=2.0)
    # Low 10 at bar 0 to high 20 at bar 9 is 10 price, 5 units, over 9 bars.
    assert got["displacement_vol"] == pytest.approx(5.0)
    assert got["displacement_bars"] == 9.0
    assert got["displacement_speed_vol"] == pytest.approx(5.0 / 9.0)
    assert got["displacement_age"] == 0.0
    falling = features(bars([(10 - i, 11 - i) for i in range(10)]), unit=2.0)
    assert falling["displacement_vol"] == pytest.approx(-5.0)


def test_the_same_shape_reads_the_same_at_any_price_level():
    """Scale invariance, like every other distance on this desk."""
    small = features(bars([(1.0 + 0.1 * i, 1.1 + 0.1 * i) for i in range(10)]), unit=0.2)
    big = features(bars([(1000 + 100 * i, 1100 + 100 * i) for i in range(10)]), unit=200.0)
    assert small["displacement_vol"] == pytest.approx(big["displacement_vol"])
    assert small["displacement_speed_vol"] == pytest.approx(big["displacement_speed_vol"])


def test_imbalances_are_reported_above_and_below_price_separately():
    # A gap up, then price settles back below it without filling it.
    rows = [(10, 11), (12, 16), (14, 18), (14.5, 15)]
    got = features(bars(rows), unit=1.0)
    assert got["imbalance_n"] == 1.0
    # Spot is the last close, 15.0; the gap sits 11..14, which is below it.
    assert "imbalance_below_vol" in got
    assert got["imbalance_below_vol"] == pytest.approx(1.0)
    assert got["imbalance_below_size_vol"] == pytest.approx(3.0)
    assert got["imbalance_below_age"] == 2.0
    assert "imbalance_above_vol" not in got


def test_the_nearest_and_the_furthest_imbalance_are_both_reported():
    """ "Past the imbalance" and "way past the imbalance" are different targets."""
    rows = [(10, 11), (12, 16), (14, 18), (20, 24), (26, 30), (27, 28)]
    got = features(bars(rows), unit=1.0)
    assert got["imbalance_n"] >= 2
    assert got["imbalance_below_vol"] < got["imbalance_below_far_vol"]


def test_a_window_with_no_gaps_still_says_so():
    """Zero open imbalances is a reading. An absent key would be read later as
    "we did not look"."""
    got = features(bars([(10 + i * 0.1, 11 + i * 0.1) for i in range(10)]), unit=1.0)
    assert got["imbalance_n"] == 0.0
    assert "imbalance_above_vol" not in got
    assert "imbalance_below_vol" not in got


def test_too_few_bars_say_nothing_at_all():
    assert features(bars([(10, 11), (11, 12)]), unit=1.0) == {}
    assert features([], unit=1.0) == {}


def test_only_the_last_span_bars_are_read():
    """A displacement is a local event; a hundred bars of context would bury the
    one that just happened."""
    old = bars([(1000 + i, 1001 + i) for i in range(10)])
    recent = bars([(10 + i * 0.01, 11 + i * 0.01) for i in range(SPAN)])
    got = features(old + recent, unit=1.0)
    assert got["displacement_vol"] < 2.0, "the old thousand-point leg is out of the window"


# --------------------------------------------------------------------- the card


def test_the_card_names_the_direction_and_the_gaps():
    rows = [(10, 11), (12, 16), (14, 18), (14.5, 15)]
    got = card_line(features(bars(rows), unit=1.0))
    assert len(got) == 1
    assert "displaced" in got[0]
    assert "up" in got[0]
    assert "imbalance" in got[0]


def test_the_card_is_empty_without_a_reading():
    assert card_line({}) == []
    assert card_line({"displacement_vol": float("nan")}) == []


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
    from till_infinity.bus import Bus
    from till_infinity.strategies.config import Settings
    from till_infinity.strategies.service import Trader

    trader = Trader(Bus(), settings=Settings(symbols=("gold",)))
    trader.paper = _Bars(candles)
    trader._vol_bps["gold"] = 10.0
    return trader


def _intent():
    from till_infinity.strategies.models import Intent, Side

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
