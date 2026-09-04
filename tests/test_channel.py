"""The two levels price is between, and how much room is on each side."""

from dataclasses import dataclass

import pytest

from till_infinity.structures.drawing.channel import Channel, channel_of


@dataclass
class _Zone:
    price: float


def _band(price, *, lower=None, upper=None, unit=1.0):
    return Channel(
        feed="gold",
        price=price,
        lower=_Zone(lower) if lower is not None else None,
        upper=_Zone(upper) if upper is not None else None,
        unit=unit,
    )


def test_the_nearest_zone_on_each_side_is_the_channel():
    zones = [_Zone(4300.0), _Zone(4324.0), _Zone(4334.0), _Zone(4400.0)]

    got = channel_of(zones, price=4330.0, unit=1.0, feed="gold")

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
    got = channel_of([_Zone(4324.0)], price=4330.0, unit=1.0)

    assert got.upper is None
    assert got.room_up_vol is None
    assert got.bounded is False
    assert got.position is None
    assert got.width_vol == 0.0


def test_an_absent_bound_is_omitted_rather_than_zeroed():
    """A missing key is a missing reading downstream; a zero is a claim that
    the ceiling is at the current price."""
    got = channel_of([_Zone(4324.0)], price=4330.0, unit=1.0).features()

    assert "room_up_vol" not in got
    assert "channel_width_vol" not in got
    assert "channel_position" not in got
    assert got["room_down_vol"] == pytest.approx(6.0)


def test_the_features_are_the_four_readings():
    got = channel_of(
        [_Zone(4324.0), _Zone(4334.0)], price=4330.0, unit=2.0, feed="gold"
    ).features()

    assert got == {
        "room_up_vol": pytest.approx(2.0),
        "room_down_vol": pytest.approx(3.0),
        "channel_width_vol": pytest.approx(5.0),
        "channel_position": pytest.approx(0.6),
    }


def test_price_exactly_on_a_zone_sits_on_its_floor():
    """`Level.side_of` resolves the same tie the same way. The choice matters
    less than the two modules agreeing - disagreeing would put one touch on
    different sides of its own channel."""
    got = channel_of([_Zone(4324.0), _Zone(4334.0)], price=4324.0, unit=1.0)

    assert got.lower.price == 4324.0
    assert got.room_down_vol == pytest.approx(0.0)


def test_a_zone_without_a_usable_price_is_skipped():
    """Zones arrive from `combine`, which is not this module's to trust."""
    got = channel_of([_Zone(0.0), _Zone(None), _Zone(4334.0)], price=4330.0, unit=1.0)

    assert got.lower is None
    assert got.upper.price == 4334.0


def test_no_zones_at_all_is_a_channel_with_no_walls():
    """A quiet instrument, not a fault."""
    got = channel_of([], price=4330.0, unit=1.0)

    assert got.features() == {}
    assert "open" in str(got)


def test_a_zero_volatility_unit_reports_nothing_rather_than_dividing():
    got = channel_of([_Zone(4324.0), _Zone(4334.0)], price=4330.0, unit=0.0)

    assert got.room_up_vol is None
    assert got.room_down_vol is None
    assert got.width_vol == 0.0
