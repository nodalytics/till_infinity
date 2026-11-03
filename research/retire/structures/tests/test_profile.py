"""Busy bands, found as modes of a density rather than as tall histogram bins.

The tests that matter here are the two the histogram failed. It could not find
more than one band, because a share of the window relative to a *fair* share is
exactly one when the bands are equal; and it emitted one point per band at one
timestamp, so `levels.form`, which needs three turns within a volatility unit,
could never cluster anything. Three levels out of 1,808 in production.
"""

import random

from till_infinity.structures import levels as lv
from till_infinity.structures.drawing import pips
from till_infinity.structures.drawing.pips import Swing
from till_infinity.structures.drawing.profile import (
    BANDWIDTH_VOL,
    MODE_OF_PEAK,
    modes,
    nodes,
    points,
)
from till_infinity.structures.vol.volatility import Volatility


def warm(prices, steps=400):
    vol = Volatility()
    for p in prices[:steps] or prices:
        vol.update(p)
    return vol


def camps(homes, dwell=60, bars=500, noise=0.08, seed=7, step=300.0):
    """Price that lives at each of `homes` in turn - the shape a range is."""
    random.seed(seed)
    prices = [homes[(i // dwell) % len(homes)] + random.gauss(0, noise) for i in range(bars)]
    return [float(i) * step for i in range(bars)], prices


def series(shape, repeats=40):
    return [p for _ in range(repeats) for p in shape]


# ------------------------------------------------------------ finding a band


def test_a_band_price_keeps_returning_to_is_a_mode():
    """The whole claim: where a lot happened is a price the market has to get
    through."""
    shape = [100.0] * 8 + [104.0, 108.0, 104.0] + [100.0] * 8 + [96.0, 92.0, 96.0]
    prices = series(shape)
    found = nodes(prices, warm(prices))
    assert found
    best, share = found[0]
    assert 99.0 < best < 101.0
    assert share > 0.05


def test_several_equally_busy_bands_are_all_found():
    """The failure this replaces, stated as a test.

    A threshold relative to a *fair* share cannot admit equal bands: with n of
    them each peak holds exactly one nth, which is exactly fair, never several
    times it. Relative to the busiest mode they all pass, which is the point.
    """
    _times, prices = camps([100.0, 103.0, 106.0])
    found = modes(prices, warm(prices))
    assert len(found) == 3
    assert sorted(round(m.price) for m in found) == [100, 103, 106]
    # Equally busy, so none is much stronger than the others.
    assert min(m.strength for m in found) > MODE_OF_PEAK


def test_a_flat_series_has_no_band():
    """A local maximum alone would return the tallest bin of a flat profile,
    which is noise with a rank."""
    prices = [100.0 + (i % 40) * 0.5 for i in range(2000)]
    assert modes(prices, warm(prices)) == []


def test_two_peaks_closer_than_the_separation_are_one_band():
    _times, prices = camps([100.0, 100.02])
    found = modes(prices, warm(prices))
    assert len(found) == 1


def test_a_band_straddling_where_a_bin_edge_would_be_is_still_found():
    """Bins have edges and a kernel does not. A band split across one looked
    like two ordinary bins."""
    _times, prices = camps([100.0, 104.0])
    found = modes(prices, warm(prices))
    assert len(found) == 2
    _times, shifted = camps([100.017, 104.017])
    assert len(modes(shifted, warm(shifted))) == 2


def test_too_little_series_says_nothing():
    assert modes([100.0, 100.1], warm([100.0, 100.1])) == []


# ------------------------------------------- one point per visit, not per band


def test_a_band_is_emitted_once_per_visit():
    """`form` needs three turns within a unit, so one point per band could
    never make a cluster - the second reason this drew almost nothing."""
    times, prices = camps([100.0, 103.0, 106.0], dwell=60, bars=500)
    found = points(times, prices, warm(prices))
    # Three bands, each visited about three times in 500 bars at 60 a dwell.
    assert len(found) >= 6
    assert len({point.time for point in found}) == len(found)


def test_a_band_visited_once_forms_no_level():
    """And that is the right answer rather than a workaround. A price visited
    once is not a level whatever its density says."""
    random.seed(3)
    prices = [100.0 + random.gauss(0, 0.05) for _ in range(300)]
    prices += [110.0 + random.gauss(0, 0.05) for _ in range(60)]
    times = [float(i) * 300 for i in range(len(prices))]
    vol = warm(prices)
    found = points(times, prices, vol)
    at_110 = [p for p in found if abs(p.price - 110.0) < 1.0]
    assert len(at_110) <= 1


def test_the_visits_become_levels():
    """End to end, and the number production could not produce: bands that
    price kept coming back to become levels."""
    times, prices = camps([100.0, 103.0, 106.0])
    vol = warm(prices)
    made = lv.form("x", "5m", pips.turns(points(times, prices, vol)), vol, origin="profile")
    assert len(made) == 3
    assert sorted(round(level.price) for level in made) == [100, 103, 106]


def test_one_bar_of_noise_does_not_end_a_visit():
    """Otherwise a single camp becomes a dozen turns and manufactures a level
    out of one occasion."""
    prices = [100.0] * 40 + [100.5] + [100.0] * 40 + [95.0] * 40 + [100.0] * 40
    times = [float(i) * 300 for i in range(len(prices))]
    vol = warm(prices)
    found = [p for p in points(times, prices, vol) if abs(p.price - 100.0) < 0.4]
    assert len(found) <= 3


# ------------------------------------------------------------ what it carries


def test_a_band_has_no_side_so_it_takes_the_one_it_is_not_on():
    """Price can arrive at a band from either direction, and `form` accepts
    only HIGH and LOW."""
    times, prices = camps([100.0, 106.0])
    found = points(times, prices, warm(prices))
    spot = prices[-1]
    for point in found:
        assert point.swing in (Swing.HIGH, Swing.LOW)
        if point.swing is Swing.HIGH:
            assert point.price > spot - 1.0


def test_the_width_of_a_band_is_a_volatility_estimate_at_that_price():
    """A level price hugs within a quarter of a unit and one it swings a unit
    either side of are different objects, and everything downstream currently
    sizes their zones from one global number."""
    _times, tight = camps([100.0, 106.0], noise=0.02, seed=11)
    _times, loose = camps([100.0, 106.0], noise=0.20, seed=11)
    narrow = modes(tight, warm(tight))
    wide = modes(loose, warm(loose))
    assert narrow
    assert wide
    assert all(m.width_vol > 0 for m in narrow + wide)
    # Both are measured against their own volatility, so the comparison that
    # matters is that a width exists and is bounded by the bandwidth it was
    # gathered in - not that one number is larger in price terms.
    assert all(m.width_vol <= BANDWIDTH_VOL for m in narrow + wide)


def test_volume_is_used_where_it_is_given():
    _times, prices = camps([100.0, 106.0])
    heavy = [10.0 if abs(p - 106.0) < 1.0 else 1.0 for p in prices]
    found = modes(prices, warm(prices), weights=heavy)
    assert found
    assert abs(found[0].price - 106.0) < 1.0


def test_a_missing_volume_does_not_erase_the_bar():
    """A zero is an absent measurement, not evidence of no activity."""
    _times, prices = camps([100.0, 106.0])
    absent = [0.0] * len(prices)
    assert modes(prices, warm(prices), weights=absent)


def test_a_wrong_length_weight_list_is_ignored_rather_than_trusted():
    _times, prices = camps([100.0, 106.0])
    assert modes(prices, warm(prices), weights=[1.0, 2.0]) == modes(prices, warm(prices))
