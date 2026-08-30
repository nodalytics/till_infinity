"""Levels where a lot of supply changed hands."""

from till_infinity.structures.pips import Swing
from till_infinity.structures.profile import BIN_VOL, NODE_CONCENTRATION, nodes, points
from till_infinity.structures.volatility import Volatility


def warm(prices, steps=400):
    vol = Volatility()
    for p in prices[:steps] or prices:
        vol.update(p)
    return vol


def series(shape, repeats=40):
    return [p for _ in range(repeats) for p in shape]


def test_a_band_price_keeps_returning_to_is_a_node():
    """The whole claim: where a lot happened is a price the market has to get
    through."""
    # Most of the time near 100, with excursions either side.
    shape = [100.0] * 8 + [104.0, 108.0, 104.0] + [100.0] * 8 + [96.0, 92.0, 96.0]
    prices = series(shape)
    found = nodes(prices, warm(prices))
    assert found
    best, share = found[0]
    assert 99.0 < best < 101.0
    assert share > 0.05


def test_a_flat_profile_has_no_node():
    """A local maximum alone would return the tallest bin of a flat profile,
    which is noise with a rank."""
    prices = [100.0 + (i % 40) * 0.5 for i in range(2000)]
    assert nodes(prices, warm(prices)) == []


def test_the_threshold_is_relative_to_how_many_bins_there_are():
    """A fixed share means a different thing per window.

    Measured over 339 warm series at the engine's 500-bar window: the median
    window holds 59 bins, and 5% is three fair shares at 60 - so the old
    threshold was calibrated for the median by accident, and was too strict on
    a wide-ranging window and too loose on a narrow one.
    """
    assert NODE_CONCENTRATION > 1.0
    # A window that ranges widely and concentrates in one place still finds it,
    # which a fixed share cannot do once the range is wide enough.
    wide = [100.0 + (i % 200) * 0.5 for i in range(400)] + [100.0] * 1600
    found = nodes(wide, warm(wide))
    assert found
    assert abs(found[0][0] - 100.0) < 2.0


def test_volume_is_used_where_it_is_given():
    """Volume is the right weight where it means contracts. Bitcoin is the one
    instrument here whose volume means what the word usually means."""
    prices = series([100.0] * 4 + [110.0] * 4)
    heavy = [1.0 if p < 105 else 50.0 for p in prices]
    by_time = nodes(prices, warm(prices))
    by_volume = nodes(prices, warm(prices), weights=heavy)
    assert by_time
    assert by_volume
    # Time says the two bands are equal; volume says the upper one dominates.
    assert by_volume[0][0] > 105.0


def test_a_missing_volume_does_not_erase_the_bar():
    """Zero volume is an absent measurement, not evidence of no activity.
    Counting it as zero would delete 43% of stored eurusd bars."""
    prices = series([100.0] * 4 + [110.0] * 4)
    absent = [0.0] * len(prices)
    assert nodes(prices, warm(prices), weights=absent)


def test_mismatched_weights_are_ignored_rather_than_trusted():
    prices = series([100.0] * 4 + [110.0] * 4)
    assert nodes(prices, warm(prices), weights=[1.0, 2.0]) == nodes(prices, warm(prices))


def test_a_node_takes_the_side_it_is_not_on():
    """A band has no side of its own - price can arrive from either direction -
    so one above the last price behaves like resistance and one below like
    support, which is how a cost-basis shelf is read."""
    shape = [100.0] * 8 + [104.0, 108.0, 104.0] + [100.0] * 8 + [96.0, 92.0, 96.0]
    prices = [*series(shape), 130.0]
    made = points([float(i) for i in range(len(prices))], prices, warm(prices))
    assert made
    # Every node sits below the last price, so every one reads as support.
    assert all(p.swing is Swing.LOW for p in made)


def test_confirmation_is_the_end_of_the_window():
    """A profile is a statement about a window and is not knowable before the
    window ends."""
    shape = [100.0] * 8 + [104.0, 108.0, 104.0] + [100.0] * 8 + [96.0, 92.0, 96.0]
    prices = series(shape)
    times = [float(i) for i in range(len(prices))]
    made = points(times, prices, warm(prices))
    assert made
    assert all(p.confirmed == times[-1] for p in made)


def test_bins_are_scale_free():
    """A fixed price width would give btc four bins and eurusd four thousand."""
    assert BIN_VOL > 0
    small = series([1.1000] * 8 + [1.1040, 1.1080, 1.1040] + [1.1000] * 8)
    big = [p * 100_000 for p in small]
    assert len(nodes(small, warm(small))) == len(nodes(big, warm(big)))


def test_too_little_history_says_nothing():
    assert nodes([100.0], warm([100.0, 101.0])) == []
    assert points([1.0], [100.0], warm([100.0, 101.0])) == []
