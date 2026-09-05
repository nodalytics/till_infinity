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

    assert "range 4320 .. 4340" in got
    assert "4.0v wide" in got
    assert "price 50% up it" in got
    assert "2.00v to the ceiling" in got
    assert "2.00v to the floor" in got


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

    assert "range 4320 .. 4340" in got
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
