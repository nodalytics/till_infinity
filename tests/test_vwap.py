"""Fair value by the other definition, and the volume it needs to exist."""

from __future__ import annotations

import math

import pytest

from till_infinity.structures.drawing import vwap
from till_infinity.structures.vol.volatility import Volatility


def _vol(prices):
    got = Volatility()
    for price in prices:
        got.update(price)
    return got


def _series(n=192, base=100.0):
    """Price sweeping smoothly either side of 100, so it crosses its own mean.

    A square wave between 98 and 102 would *not* - its mean is 100 and it is
    never there - which is a fair thing for the touch check to refuse and a
    poor fixture for testing anything else.
    """
    times = [float(i * 60) for i in range(n)]
    closes = [base + 2.0 * math.sin(i * math.pi / 12) for i in range(n)]
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    return times, highs, lows, closes


def test_the_typical_price_is_not_the_close():
    """Business was done across the bar's range, not at the price it happened
    to finish on - the same reason `wick` exists."""
    assert vwap.typical(110.0, 90.0, 100.0) == 100.0
    assert vwap.typical(110.0, 90.0, 106.0) == pytest.approx(102.0)


def test_no_volume_draws_no_level():
    """A mean of the prices would be a different object wearing VWAP's name and
    indistinguishable downstream. Half the book here has no real volume."""
    times, highs, lows, closes = _series()
    nothing = [math.nan] * len(closes)

    assert vwap.points(times, highs, lows, closes, nothing, _vol(closes)) == []


def test_too_few_weighted_bars_draws_no_level():
    times, highs, lows, closes = _series()
    sparse = [1.0 if i % 40 == 0 else math.nan for i in range(len(closes))]

    assert vwap.points(times, highs, lows, closes, sparse, _vol(closes)) == []


def test_a_visited_vwap_becomes_a_point():
    times, highs, lows, closes = _series()
    volume = [100.0] * len(closes)

    found = vwap.points(times, highs, lows, closes, volume, _vol(closes), span=96)

    assert found
    for point in found:
        assert 99.0 < point.price < 101.0


def test_the_point_is_dated_when_the_average_could_be_computed():
    """A VWAP is knowable only once the bars it averages have closed. Dating it
    from the anchor's start would draw a level at a price nobody could yet
    compute, which is the look-ahead every formation here is built against."""
    times, highs, lows, closes = _series()
    volume = [100.0] * len(closes)

    found = vwap.points(times, highs, lows, closes, volume, _vol(closes), span=96)

    for point in found:
        assert point.confirmed == point.time
        assert point.time >= times[95]


def test_a_vwap_price_never_visited_is_a_statistic_not_a_level():
    """Levels are made of interactions. A line price never came near did not
    turn anything away."""
    times = [float(i * 60) for i in range(192)]
    # Price steps away and never returns, so each anchor's mean sits behind it.
    closes = [100.0 + i for i in range(192)]
    highs = [c + 0.1 for c in closes]
    lows = [c - 0.1 for c in closes]
    volume = [100.0] * len(closes)

    found = vwap.points(times, highs, lows, closes, volume, _vol(closes), span=96)

    assert found == []


def test_a_short_series_draws_nothing():
    times, highs, lows, closes = _series(n=40)
    volume = [100.0] * len(closes)

    assert vwap.points(times, highs, lows, closes, volume, _vol(closes)) == []


def test_mismatched_inputs_are_refused_rather_than_zipped_short():
    times, highs, lows, closes = _series()
    volume = [100.0] * (len(closes) - 3)

    assert vwap.points(times, highs, lows, closes, volume, _vol(closes)) == []


def test_the_anchor_does_not_move_when_the_window_rolls():
    """The module note said "anchored, not rolling" and the code did the other.

    Anchors were blocks of `span` bars counted from the start of the array, and
    the array is a rolling window - so every bar that aged out shifted every
    boundary by one and moved every VWAP with it. A level at a different price
    on every reform is a volume-weighted moving average wearing the name.
    """
    n = 500
    # Aligned to the epoch so the buckets are the ones production would see.
    times = [float(1_780_000_000 - 1_780_000_000 % 300 + i * 300) for i in range(n)]
    closes = [100.0 + 2.0 * math.sin(i * math.pi / 37) for i in range(n)]
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    volumes = [100.0 + (i % 17) for i in range(n)]
    vol = _vol(closes)

    whole = {
        (int(point.time), round(point.price, 9))
        for point in vwap.points(times, highs, lows, closes, volumes, vol)
    }
    assert whole, "the fixture has to produce anchors for this to mean anything"

    for dropped in range(1, 8):
        rolled = vwap.points(
            times[dropped:],
            highs[dropped:],
            lows[dropped:],
            closes[dropped:],
            volumes[dropped:],
            vol,
        )
        # Anchors still wholly inside the shortened window keep their exact
        # price. Ones the roll cut into simply stop being published.
        for point in rolled:
            assert (int(point.time), round(point.price, 9)) in whole


def test_the_bar_interval_is_read_off_the_stamps():
    assert vwap.step_of([0.0, 60.0, 120.0, 180.0]) == 60.0
    # A weekend, a gap and a repeat must not change what interval this is on.
    assert vwap.step_of([0.0, 300.0, 600.0, 600.0, 300_000.0, 300_300.0]) == 300.0
    assert vwap.step_of([]) == 0.0
    assert vwap.step_of([5.0]) == 0.0


def test_an_anchor_still_filling_does_not_publish():
    """Its mean moves with the next bar, so a price from it is not yet a price."""
    span = 96
    step = 300.0
    n = span + span // 2  # one whole bucket and half of the next
    start = 1_780_000_000 - 1_780_000_000 % int(span * step)
    times = [float(start + i * step) for i in range(n)]
    closes = [100.0 + 2.0 * math.sin(i * math.pi / 23) for i in range(n)]
    found = vwap.points(
        times, [c + 0.2 for c in closes], [c - 0.2 for c in closes], closes,
        [100.0] * n, _vol(closes),
    )
    assert len(found) == 1
    assert found[0].time == times[span - 1]
