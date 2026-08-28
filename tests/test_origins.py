"""What the origin model must get right, and the ways it can quietly not."""

from __future__ import annotations

from till_infinity.structures.origins import Origin, Origins


def _series(prices):
    return list(range(len(prices))), [float(p) for p in prices]


def test_the_origin_is_where_the_move_began_not_where_it_ended():
    """The whole point. Recording the low of a drop would record the price
    everyone already knows about instead of the one that has not been traded
    through."""
    # Flat at 100, then a fast drop to 90.
    times, prices = _series([100] * 7 + [99, 97, 94, 90] + [90] * 7)
    got = Origins().observe(times, prices, unit=1.0)
    assert got, "no origin found in an obvious 10-unit drop"
    drop = [o for o in got if o.launched == "down"]
    assert drop
    assert drop[0].price == 100.0


def test_a_rally_origin_is_the_low_it_left_from():
    times, prices = _series([100] * 7 + [101, 103, 106, 110] + [110] * 7)
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "up"]
    assert got
    assert got[0].price == 100.0


def test_a_drift_is_not_an_origin():
    """Same total distance, spread over far more bars. The claim is about
    displacement fast enough that resting interest was not refilled."""
    times, prices = _series([100 + i * 0.4 for i in range(25)])
    assert Origins().observe(times, prices, unit=1.0, bars=4) == []


def test_the_threshold_is_in_volatility_units():
    """A 10-point move is an event on a quiet instrument and a normal bar on a
    loud one. The same series must give different answers at different vol."""
    times, prices = _series([100] * 7 + [99, 97, 94, 90] + [90] * 7)
    assert Origins().observe(times, prices, unit=1.0) != []
    assert Origins().observe(times, prices, unit=20.0) == []


def test_one_impulse_is_recorded_once():
    """A move visible from several offsets is one event, not several."""
    times, prices = _series([100] * 7 + [99, 97, 94, 90] + [90] * 10)
    got = Origins().observe(times, prices, unit=1.0)
    downs = [o for o in got if o.launched == "down"]
    assert len(downs) == 1, f"one drop recorded {len(downs)} times"


def test_direction_backs_the_side_it_should():
    """The opposite convention is equally sayable and would silently invert
    every gate built on this."""
    sell_side = Origin(price=100, low=99, high=100, launched="down", size_vol=4.0, when=0)
    assert sell_side.supports(want_up=False) is True
    assert sell_side.supports(want_up=True) is False


def test_a_revisited_origin_is_counted_as_such():
    """The claim is unfilled interest; each return trades some of it away."""
    times, prices = _series(
        [100] * 7 + [99, 97, 94, 90] + [92, 96, 100, 96, 92] + [96, 100, 96] + [90] * 3
    )
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "down"]
    assert got
    assert got[0].revisits >= 1


def test_a_fresh_origin_has_no_revisits():
    times, prices = _series([100] * 7 + [99, 97, 94, 90] + [90] * 7)
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "down"]
    assert got[0].revisits == 0


def test_the_zone_is_a_band_not_a_price():
    """Resting interest sat across a range, so price entering the band has
    reached it."""
    o = Origin(price=100, low=99.5, high=100.0, launched="down", size_vol=4.0, when=0)
    assert o.holds(99.7)
    assert not o.holds(99.0)


def test_nothing_is_found_without_a_volatility_unit():
    """A zero unit would make every move infinitely large in vol terms."""
    times, prices = _series([100] * 7 + [99, 97, 94, 90] + [90] * 7)
    assert Origins().observe(times, prices, unit=0.0) == []


def test_the_target_side_is_the_opposing_origin():
    """For a buy, the origin of the last violent rally *above* here - where the
    previous advance was stopped."""
    o = Origins()
    o.found = [
        Origin(price=90, low=90, high=90.5, launched="up", size_vol=4.0, when=0),
        Origin(price=110, low=109.5, high=110, launched="down", size_vol=4.0, when=0),
    ]
    target = o.opposing(price=95.0, want_up=True)
    assert target is not None
    assert target.price == 110
    # And the entry side is the other one.
    assert o.nearest(price=95.0, want_up=True).price == 90


# ------------------------- the zone is the last leg the other way, measured


def test_the_zone_is_the_last_opposing_leg():
    """A rally from 96 to 100, then a drop. The zone is 96-100 - the leg
    itself - not the high padded by a constant somebody chose.
    """
    times, prices = _series([96, 97, 98, 99, 100] + [99, 97, 94, 90] + [90] * 8)
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "down"]
    assert got
    assert got[0].price == 100.0
    assert got[0].low == 96.0
    assert got[0].high == 100.0


def test_the_zone_widens_with_the_leg_that_made_it():
    """Its width is observed. A longer run into the turn leaves a bigger band,
    because the interest placed during it sat across more price.

    The approach is deliberately gradual in both: a brisk one would qualify as
    an impulse in its own right and the series would carry two origins, which
    is correct behaviour and not what this is measuring.
    """
    short = _series([99.5, 100] + [99, 97, 94, 90] + [90] * 8)
    long_ = _series([98, 98.5, 99, 99.5, 100] + [99, 97, 94, 90] + [90] * 8)
    a = [o for o in Origins().observe(*short, unit=1.0) if o.launched == "down"][0]
    b = [o for o in Origins().observe(*long_, unit=1.0) if o.launched == "down"][0]
    assert (b.high - b.low) > (a.high - a.low)


def test_a_rally_origin_is_the_selling_leg_before_it():
    times, prices = _series([104, 103, 102, 101, 100] + [101, 103, 106, 110] + [110] * 8)
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "up"]
    assert got
    assert got[0].price == 100.0
    assert got[0].low == 100.0
    assert got[0].high == 104.0


def test_an_impulse_from_a_flat_still_gets_a_band():
    """No opposing leg to measure - the fallback, and the weaker case."""
    times, prices = _series([100] * 6 + [99, 97, 94, 90] + [90] * 8)
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "down"]
    assert got
    assert got[0].high > got[0].low
