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
