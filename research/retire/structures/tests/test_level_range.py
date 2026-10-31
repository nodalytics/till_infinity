"""The two levels price is between, and how much room is on each side."""

from dataclasses import dataclass

import pytest

from till_infinity.structures.drawing.level_range import LevelRange, level_range_of


@dataclass
class _Zone:
    price: float


def _band(price, *, lower=None, upper=None, unit=1.0):
    return LevelRange(
        feed="gold",
        price=price,
        lower=_Zone(lower) if lower is not None else None,
        upper=_Zone(upper) if upper is not None else None,
        unit=unit,
    )


def test_the_nearest_zone_on_each_side_is_the_channel():
    zones = [_Zone(4300.0), _Zone(4324.0), _Zone(4334.0), _Zone(4400.0)]

    got = level_range_of(zones, price=4330.0, unit=1.0, feed="gold")

    # Not the outermost pair, and not any pair - the two that enclose price.
    assert got.lower.price == 4324.0
    assert got.upper.price == 4334.0
    assert got.bounded


def test_room_is_measured_in_volatility_units():
    """Points do not compare across instruments; volatility units do, which is
    the whole reason every other reading here is in them."""
    got = _band(4330.0, lower=4324.0, upper=4334.0, unit=2.0)

    assert got.room_up_vol == pytest.approx(2.0)
    assert got.room_down_vol == pytest.approx(3.0)
    assert got.width_vol == pytest.approx(5.0)


def test_position_says_where_in_the_range_price_sits():
    """Hard against a bound and mid-range are different trades, and no existing
    reading tells them apart."""
    assert _band(4324.0, lower=4324.0, upper=4334.0).position == pytest.approx(0.0)
    assert _band(4334.0, lower=4324.0, upper=4334.0).position == pytest.approx(1.0)
    assert _band(4329.0, lower=4324.0, upper=4334.0).position == pytest.approx(0.5)


def test_open_air_is_not_a_distant_ceiling():
    """The failure this shape exists to avoid. `None` says the target is
    unbounded by structure; a large number says it is far away, and putting one
    in place of the other makes them indistinguishable in the record."""
    got = level_range_of([_Zone(4324.0)], price=4330.0, unit=1.0)

    assert got.upper is None
    assert got.room_up_vol is None
    assert got.bounded is False
    assert got.position is None
    assert got.width_vol == 0.0


def test_an_absent_bound_is_omitted_rather_than_zeroed():
    """A missing key is a missing reading downstream; a zero is a claim that
    the ceiling is at the current price."""
    got = level_range_of([_Zone(4324.0)], price=4330.0, unit=1.0).features()

    assert "room_up_vol" not in got
    assert "range_width_vol" not in got
    assert "range_position" not in got
    assert got["room_down_vol"] == pytest.approx(6.0)


def test_the_features_are_the_readings_plus_the_bounds():
    """The four scale-free readings the model is fitted on, and the two bound
    prices, which exist for the alert - a person placing an entry wants the
    number to type, and "2v above" is not it."""
    got = level_range_of(
        [_Zone(4324.0), _Zone(4334.0)], price=4330.0, unit=2.0, feed="gold"
    ).features()

    assert got == {
        "room_up_vol": pytest.approx(2.0),
        "room_down_vol": pytest.approx(3.0),
        "range_width_vol": pytest.approx(5.0),
        "range_position": pytest.approx(0.6),
        "range_upper": pytest.approx(4334.0),
        "range_lower": pytest.approx(4324.0),
    }


def test_price_exactly_on_a_zone_sits_on_its_floor():
    """`Level.side_of` resolves the same tie the same way. The choice matters
    less than the two modules agreeing - disagreeing would put one touch on
    different sides of its own channel."""
    got = level_range_of([_Zone(4324.0), _Zone(4334.0)], price=4324.0, unit=1.0)

    assert got.lower.price == 4324.0
    assert got.room_down_vol == pytest.approx(0.0)


def test_a_zone_without_a_usable_price_is_skipped():
    """Zones arrive from `combine`, which is not this module's to trust."""
    got = level_range_of([_Zone(0.0), _Zone(None), _Zone(4334.0)], price=4330.0, unit=1.0)

    assert got.lower is None
    assert got.upper.price == 4334.0


def test_no_zones_at_all_is_a_channel_with_no_walls():
    """A quiet instrument, not a fault."""
    got = level_range_of([], price=4330.0, unit=1.0)

    assert got.features() == {}
    assert "open" in str(got)


def test_a_zero_volatility_unit_reports_nothing_rather_than_dividing():
    got = level_range_of([_Zone(4324.0), _Zone(4334.0)], price=4330.0, unit=0.0)

    assert got.room_up_vol is None
    assert got.room_down_vol is None
    assert got.width_vol == 0.0


# ------------------------------------------------------- what a person reads


def _signal(**features):
    from till_infinity.structures.models import Shape, Signal

    base = {"level": 4330.0, "probability_up": 0.7}
    base.update(features)
    return Signal(
        shape=Shape.LEVEL,
        feed="gold",
        venue="consensus",
        score=0.3,
        direction="up",
        features=base,
    )


def _body(**features):
    from till_infinity.structures.service import alert_payload

    return alert_payload(_signal(**features))["body"]


def test_the_push_to_risk_line_says_which_is_which():
    """Two earlier labels - "2.4 to 1" and "2.4x risk" - were both read
    backwards, as carrying 2.4x the risk for 1 reward. The push is the subject
    of the sentence now, and the dispersion sits beside the mean because a
    large mean with a larger sigma is not a call."""
    got = _body(
        level=6063.9,
        expected_push_vol=1.47,
        push_sigma_vol=2.10,
        risk_vol=0.62,
    )

    assert "push is 2.4x the risk" in got
    assert "± 2.10v on average" in got


def test_the_alert_shows_the_range_and_the_room_on_each_side():
    """The pair of numbers an entry and a target are actually made of - the far
    bound is a target the market drew rather than one the sizer did."""
    got = _body(
        range_upper=4340.0,
        range_lower=4320.0,
        range_width_vol=4.0,
        range_position=0.5,
        room_up_vol=2.0,
        room_down_vol=2.0,
    )

    assert "range 4,320 .. 4,340" in got
    assert "4.0v wide" in got
    assert "price 50% of floor-to-ceiling" in got
    # Named far/near rather than up/down: the far wall is the target and the
    # near one is what is in the way, and which is which depends on the call.
    assert "2.00v to the far side" in got
    assert "2.00v back to the near one" in got


def test_the_room_is_named_by_the_call_not_by_the_compass():
    """A short's target is the floor. Reporting "to the ceiling" for it would
    put the number the reader wants under the wrong word."""
    from till_infinity.structures.models import Shape, Signal
    from till_infinity.structures.service import alert_payload

    common = {
        "level": 4330.0,
        "range_upper": 4340.0,
        "range_lower": 4320.0,
        "range_width_vol": 4.0,
        "room_up_vol": 1.0,
        "room_down_vol": 3.0,
    }
    down = alert_payload(
        Signal(
            shape=Shape.LEVEL,
            feed="gold",
            venue="consensus",
            score=0.3,
            direction="down",
            features=common,
        )
    )["body"]

    # Falling: the floor is the target, three units away.
    assert "3.00v to the far side" in down
    assert "1.00v back to the near one" in down
    # And rising, the same numbers swap sides.
    assert "1.00v to the far side" in _body(**common)


def test_the_alert_names_the_wall_the_model_expects_first():
    got = _body(
        range_upper=4340.0,
        range_lower=4320.0,
        range_width_vol=4.0,
        range_position=0.8,
        room_up_vol=0.8,
        room_down_vol=3.2,
        up_first=0.74,
    )

    assert "ceiling first 74%" in got


def test_the_wall_named_is_the_one_actually_favoured():
    """0.26 for the ceiling is 74% for the floor, and reporting "ceiling 26%"
    would read as a weak call for the ceiling rather than a strong one against
    it."""
    got = _body(
        range_upper=4340.0,
        range_lower=4320.0,
        range_width_vol=4.0,
        range_position=0.2,
        room_up_vol=3.2,
        room_down_vol=0.8,
        up_first=0.26,
    )

    assert "floor first 74%" in got


def test_a_cold_race_model_adds_no_line_rather_than_saying_fifty():
    """Silence rather than 50%, for the same reason `predict` returns None."""
    got = _body(
        range_upper=4340.0,
        range_lower=4320.0,
        range_width_vol=4.0,
        range_position=0.5,
        room_up_vol=2.0,
        room_down_vol=2.0,
    )

    assert "range 4,320 .. 4,340" in got
    assert "first" not in got.split("range ")[1]


def test_an_unbounded_range_adds_nothing_to_the_alert():
    """One wall is not a channel, and half a box is not worth a line."""
    got = _body(room_down_vol=2.0)

    assert "range " not in got
    assert "ceiling" not in got


def test_the_bound_prices_are_not_model_inputs():
    """`racing` reads `NAMES` only. A raw price among standardised ratios would
    dominate any linear fit given it."""
    from till_infinity.structures.learning.racing import NAMES, Races

    got = level_range_of([_Zone(4324.0), _Zone(4334.0)], price=4330.0, unit=2.0).features()

    assert "range_upper" not in NAMES
    assert "range_lower" not in NAMES
    assert len(Races.inputs(got)) == len(NAMES)


# --------------------------------------------- the bounds have to be comparable


class _Zoned:
    """A zone with the two ends the filter reads: how big it is, and how
    precisely it is placed. A single-timeframe stub is both."""

    def __init__(self, price, span, precision=None):
        self.price = price
        self.span = span
        self.precision = precision or span


def test_a_ceiling_from_1h_and_a_floor_from_5m_is_not_a_range():
    """The two bounds have to be the same kind of object. A 5m zone is a place
    price paused for a few bars; a 1h zone is a place it turned; the distance
    between one of each is a number with nothing behind it."""
    from till_infinity.structures.drawing.level_range import level_range_of

    zones = [_Zoned(4320.0, "5m"), _Zoned(4300.0, "1h"), _Zoned(4340.0, "1h")]

    got = level_range_of(zones, price=4330.0, unit=1.0, interval="1h")

    # The 5m floor at 4320 is nearer, and is refused for being finer.
    assert got.lower.price == 4300.0
    assert got.upper.price == 4340.0


def test_a_coarser_zone_is_kept_because_higher_is_the_safe_direction():
    """A 4h zone is a real boundary for a 15m trade; a 15m zone is noise inside
    a 4h one."""
    from till_infinity.structures.drawing.level_range import within

    zones = [_Zoned(1.0, "5m"), _Zoned(2.0, "15m"), _Zoned(3.0, "4h"), _Zoned(4.0, "1d")]

    kept = {z.span for z in within(zones, "15m")}

    assert kept == {"15m", "4h", "1d"}


def test_no_timeframe_means_take_them_all():
    """What a caller without one wants, and what the older tests assume."""
    from till_infinity.structures.drawing.level_range import within

    zones = [_Zoned(1.0, "5m"), _Zoned(2.0, "4h")]

    assert len(within(zones, "")) == 2


def test_a_zone_with_no_span_cannot_be_shown_to_belong():
    from till_infinity.structures.drawing.level_range import within

    zones = [_Zoned(1.0, ""), _Zoned(2.0, "4h")]

    assert [z.span for z in within(zones, "1h")] == ["4h"]


def test_a_daily_zone_nothing_finer_agrees_with_is_context_not_a_wall():
    """A box the daily draws takes weeks to cross, so a trade held for a day is
    aiming at a target it cannot reach. The daily says the level is real; it
    does not get to say where the trade is going."""
    from till_infinity.structures.drawing.level_range import within

    zones = [_Zoned(1.0, "1w", "daily"), _Zoned(2.0, "daily", "daily")]

    assert within(zones, "4h", placed_by="4h") == []


def test_the_daily_earns_a_wall_by_agreeing_with_the_4h():
    """And then the wall sits where the 4h places it - significance from the
    higher timeframe, placement from the lower, which is what confluence is."""
    from till_infinity.structures.drawing.level_range import within

    zone = _Zoned(1.0, "daily", "4h")

    assert within([zone], "4h", placed_by="4h") == [zone]


def test_a_zone_too_small_to_be_a_wall_is_still_refused():
    """The other end of the same pair: 4h is a floor as well as a ceiling."""
    from till_infinity.structures.drawing.level_range import within

    zones = [_Zoned(1.0, "1h", "15m"), _Zoned(2.0, "15m", "5m")]

    assert within(zones, "4h", placed_by="4h") == []


def test_the_swing_box_is_drawn_between_origins():
    """The wall a swing aims at has to be a price somebody defended. A
    confluence zone is a price several timeframes drew a level at, which is a
    different claim - and measured at 4h it gives a box 385bps wide against
    the origin box's 71bps, five times too wide for a day-long trade."""
    from till_infinity.structures.drawing.level_range import between_origins

    got = between_origins(1.3400, 1.3600, 1.3450, 0.0010, feed="usdcad")

    assert got.bounded
    assert (got.lower.price, got.upper.price) == (1.3400, 1.3600)
    assert got.room_up_vol == pytest.approx(15.0)
    assert got.room_down_vol == pytest.approx(5.0)
    assert got.position == pytest.approx(0.25)


def test_an_origin_missing_on_one_side_is_open_air():
    """Not a distant wall, and the difference has to survive into the features:
    a zero would claim the ceiling is at the current price."""
    from till_infinity.structures.drawing.level_range import between_origins

    got = between_origins(None, 1.36, 1.345, 0.001, feed="x")

    assert got.bounded is False
    assert got.room_down_vol is None
    assert got.room_up_vol == pytest.approx(15.0)
    assert "swing_room_down_vol" not in got.features(prefix="swing_")
