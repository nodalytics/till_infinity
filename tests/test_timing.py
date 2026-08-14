"""First-passage timing: how long until price reaches a level."""

from __future__ import annotations

import pytest

from till_infinity.structures import timing
from till_infinity.structures.levels import Kalman, Level, Side
from till_infinity.structures.volatility import Volatility


def _vol(bps: float = 5.0) -> Volatility:
    vol, price = Volatility(), 4400.0
    for _ in range(60):
        price *= 1 + bps / 10_000
        vol.update(price)
    return vol


def test_time_goes_as_the_square_of_distance():
    """Twice as far is four times as long, which is not what intuition offers."""
    near = timing.bars_to_reach(1.0)
    far = timing.bars_to_reach(2.0)
    assert far == pytest.approx(4 * near, rel=1e-6)


def test_the_median_matches_the_known_constant():
    """Median first passage for Brownian motion is 2.198 (d/sigma)^2.

    Given a distance in *sigmas*. What this module is handed is a distance in
    volatility units, and `Volatility.bps` is a mean absolute deviation, so the
    argument has to be converted before the constant applies. It was not, which
    understated every probability by a quarter of a distance — quietly, and in
    one direction.
    """
    one_sigma = 1.0 / timing.MAD_TO_SIGMA
    assert timing.bars_to_reach(one_sigma) == pytest.approx(2.198, abs=0.01)


def test_a_distance_is_read_as_mean_absolute_deviations_not_sigmas():
    """The unit the rest of the project measures distance in.

    Against 22,219 bars of realised excursions the uncorrected form quoted 7.4%
    at eight volatility units where the truth is 17.4%. The null was right and
    the unit handed to it was not.
    """
    assert pytest.approx(0.7979, abs=1e-4) == timing.MAD_TO_SIGMA
    # A MAD is the smaller unit, so a distance counted in them is fewer sigmas,
    # and therefore reached sooner and more often than the raw number implies.
    assert timing.bars_to_reach(1.0) < 2.198
    assert timing.probability_within(8.0, 20.0) > 0.15


def test_a_slower_quantile_is_further_out():
    assert timing.bars_to_reach(2.0, 0.9) > timing.bars_to_reach(2.0, 0.5)


def test_somewhere_price_already_is_takes_no_time():
    assert timing.bars_to_reach(0.0) == 0.0
    assert timing.probability_within(0.0, 1) == 1.0


def test_direction_does_not_change_the_time():
    """A walk is symmetric; above and below are the same distance problem."""
    assert timing.bars_to_reach(-3.0) == timing.bars_to_reach(3.0)


def test_the_probability_falls_with_distance_and_rises_with_time():
    assert timing.probability_within(1.0, 24) > timing.probability_within(5.0, 24)
    assert timing.probability_within(3.0, 100) > timing.probability_within(3.0, 10)


def test_probability_stays_a_probability():
    for n in (0.1, 1.0, 20.0):
        for bars in (1, 24, 10_000):
            assert 0.0 <= timing.probability_within(n, bars) <= 1.0


def test_no_time_means_no_chance():
    assert timing.probability_within(3.0, 0) == 0.0


def test_the_two_forms_agree_with_each_other():
    """P(within the median time) should be about a half — that is what median means."""
    median = timing.bars_to_reach(2.0, 0.5)
    assert timing.probability_within(2.0, median) == pytest.approx(0.5, abs=0.01)


def test_the_same_distance_is_minutes_or_months_depending_on_the_clock():
    fast = timing.estimate(3.0, "5m")
    slow = timing.estimate(3.0, "1w")
    assert fast.median_bars == pytest.approx(slow.median_bars)
    assert slow.median_seconds > 1000 * fast.median_seconds


def test_a_far_estimate_is_bounded_rather_than_absurd():
    assert timing.bars_to_reach(500.0) <= timing.MAX_BARS


def test_soon_means_better_than_even_odds_in_the_window():
    assert timing.estimate(0.5, "5m").soon
    assert not timing.estimate(20.0, "5m").soon


def test_an_approach_reads_as_a_duration():
    found = timing.estimate(3.0, "1h")
    assert found.median.endswith(("m", "h", "d", "w"))
    assert "away" in str(found)


def test_levels_are_ordered_by_time_not_distance():
    """A far level on a fast clock beats a near one on a slow clock."""
    vol = _vol()
    near_slow = Level(feed="g", interval="1w", filter=Kalman(mean=4402.0, variance=0.5))
    far_fast = Level(feed="g", interval="5m", filter=Kalman(mean=4410.0, variance=0.5))

    order = timing.next_levels([near_slow, far_fast], 4400.0, vol)
    assert order[0][0] is far_fast


def test_the_side_reported_is_the_side_price_would_arrive_from():
    vol = _vol()
    above = Level(feed="g", interval="5m", filter=Kalman(mean=4390.0, variance=0.5))
    ((_, _, side),) = timing.next_levels([above], 4400.0, vol, limit=1)
    assert side is Side.ABOVE


def test_a_clamped_slow_case_says_beyond_rather_than_a_number():
    """A ceiling printed as a duration reads as a finding when it is not one."""
    far = timing.estimate(60.0, "5m")
    assert far.capped
    assert far.slow == "beyond"


def test_an_ordinary_slow_case_is_a_duration():
    near = timing.estimate(1.0, "5m")
    assert not near.capped
    assert near.slow != "beyond"
