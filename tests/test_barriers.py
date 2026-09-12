"""What a stop-and-target geometry is worth before anything is traded.

The forms are checked against the figures `research/deriving.md` measured on
86,411 bars a feed and `research/rebuilding.md` confirmed on the tick table, so
a change that breaks the agreement fails here rather than in a document nobody
re-runs.
"""

from __future__ import annotations

import pytest

from till_infinity.trading import barriers


def test_the_shift_is_the_published_constant_on_closes():
    """One observation a bar is the close-monitored case `deriving.md` published."""
    assert barriers.shift_for(1) == pytest.approx(0.5826)
    assert barriers.shift_for(0) == pytest.approx(0.5826), "a rate under one is still one look"


def test_the_shift_falls_as_the_square_root_of_the_look_rate():
    """`B` is 0.5826 of one *monitoring interval's* sigma, so watching a price
    thirty times a bar makes each interval a thirtieth of a bar and its sigma
    `1/sqrt(30)` of the bar's."""
    assert barriers.shift_for(30) == pytest.approx(0.1064, abs=5e-5)
    assert barriers.shift_for(4) == pytest.approx(barriers.SHIFT / 2)
    assert barriers.shift_for(100) == pytest.approx(barriers.SHIFT / 10)


def test_the_three_to_one_geometry_at_each_monitoring_rate():
    """The row that matters: a 3:1 is not a 25% shot, and it is not 30.7% either.

    Continuous is the textbook answer, 0.3064 is what `deriving.md` measured on
    one-minute closes over 174,501 trades, and 0.2626 is the tick-monitored
    prediction that `rebuilding.md` confirmed on the feed to within 0.61
    standard errors - disagreeing with the published close figure by up to 5.7.
    """
    assert barriers.probability(3, 1, ticks_per_bar=1) == pytest.approx(0.3064, abs=5e-4)
    assert barriers.probability(3, 1, ticks_per_bar=30) == pytest.approx(0.2626, abs=5e-4)
    # And the continuous form the correction replaces.
    assert barriers.probability(3, 1, ticks_per_bar=10**12) == pytest.approx(0.25, abs=1e-3)


def test_a_symmetric_geometry_is_a_coin_however_it_is_watched():
    """The correction pushes both walls out equally, so it cannot tilt a fair bet."""
    for rate in (1, 30, 276, 10_000):
        assert barriers.probability(5, 5, ticks_per_bar=rate) == pytest.approx(0.5)


def test_expected_duration_matches_the_measured_table():
    """`deriving.md`'s own rows: the continuous form is 178% out at one sigma and
    12% at ten, and the corrected one is 11% and 0.1%."""
    assert barriers.duration(1, 1, ticks_per_bar=1) == pytest.approx(2.505, abs=5e-3)
    assert barriers.duration(10, 10, ticks_per_bar=1) == pytest.approx(111.991, abs=5e-2)
    # The continuous answers those replace, for the size of the gap.
    assert barriers.duration(1, 1, ticks_per_bar=1) > 1.0
    assert barriers.duration(10, 10, ticks_per_bar=1) > 100.0


def test_the_barrier_odds_are_exactly_fair_once_both_overshoots_are_counted():
    """`P*(a+B) = (1-P)*(b+B)` is an identity, and `probability` is it rearranged.

    This is the check that the formula is not a fit. A driftless process cannot
    pay, so any geometry must come out to zero once the overshoot is credited on
    both sides - and if it does not, the probability is wrong.
    """
    for up, down in ((3, 1), (1, 1), (6, 1), (0.5, 2), (10, 3)):
        for rate in (1, 30, 276):
            hit = barriers.probability(up, down, ticks_per_bar=rate)
            shift = barriers.shift_for(rate)
            gross = hit * (up + shift) - (1 - hit) * (down + shift)
            assert gross == pytest.approx(0.0, abs=1e-12)


def test_the_geometry_costs_the_overshoot_it_gives_up_on_its_wins():
    """A limit fills **at** its price; a stop fills **past** it.

    So the trade collects no overshoot on a win and pays it in full on a loss,
    and the whole asymmetry is `P * B` - the overshoot foregone on the wins.
    """
    for up, down in ((3, 1), (1, 1), (6, 1), (0.5, 1)):
        for rate in (1, 30, 276):
            hit = barriers.probability(up, down, ticks_per_bar=rate)
            expected = hit * barriers.shift_for(rate) / down
            assert barriers.overshoot_cost(up, down, ticks_per_bar=rate) == pytest.approx(expected)


def test_a_near_target_pays_more_for_being_watched_discretely():
    """Not obvious, and it is the reason to have the number: a near target wins
    more often and therefore gives up the overshoot more often."""
    costs = [barriers.overshoot_cost(rr, 1, ticks_per_bar=30) for rr in (0.5, 1, 2, 3, 6)]
    assert costs == sorted(costs, reverse=True), costs
    assert costs[0] == pytest.approx(0.0687, abs=5e-4)
    assert costs[-1] == pytest.approx(0.0163, abs=5e-4)


def test_no_geometry_has_a_positive_expectancy():
    """`deriving.md` proves `E[net] = -(c/2) * turnover` for every stop, target,
    trail and filter on a martingale. A positive number here would be an
    arithmetic error reported as an edge, which is the failure this repository
    keeps cataloguing."""
    for up in (0.25, 0.5, 1, 2, 3, 6, 12):
        for rate in (1, 30, 276):
            assert barriers.expectancy(up, 1, ticks_per_bar=rate) < 0.0
    # And the spread only makes it worse.
    bare = barriers.expectancy(3, 1, ticks_per_bar=30)
    assert barriers.expectancy(3, 1, ticks_per_bar=30, cost_units=0.2) < bare


def test_the_monitoring_rate_can_be_read_off_the_desks_own_stops():
    """`spending.md` measured real-market stops at -102.7% of risk over 42
    closes. That 2.7% excess **is** the overshoot, so it names the rate - and it
    says the synthetic default of thirty is far too coarse for a liquid feed.
    """
    rate = barriers.ticks_from_slippage(0.027, 1.3)
    assert rate == pytest.approx(276, rel=0.02)
    assert rate > barriers.DEFAULT_TICKS_PER_BAR * 5, "liquid feeds are watched far more finely"
    # Round trip: that rate reproduces the excess it was inferred from.
    assert barriers.shift_for(rate) / 1.3 == pytest.approx(0.027, rel=1e-3)


def test_a_stop_that_beats_its_own_price_is_not_a_monitoring_rate():
    """A non-positive excess is a measurement to distrust, not a finer clock."""
    assert barriers.ticks_from_slippage(0.0, 1.3) == 0.0
    assert barriers.ticks_from_slippage(-0.05, 1.3) == 0.0
    assert barriers.ticks_from_slippage(0.027, 0.0) == 0.0


def test_barriers_inside_the_volatility_estimates_own_error_are_declined():
    assert barriers.reachable(1.0, 1.0)
    assert not barriers.reachable(0.05, 3.0)
    assert not barriers.reachable(3.0, 0.01)


def test_price_distances_become_volatility_units_in_one_place():
    # 4400 at 10bps is a 4.40 unit; 8.80 of price is two of them.
    assert barriers.units_for(8.80, 4400.0, 10.0) == pytest.approx(2.0)
    assert barriers.units_for(8.80, 0.0, 10.0) == 0.0
    assert barriers.units_for(8.80, 4400.0, 0.0) == 0.0


def test_degenerate_geometries_do_not_raise():
    """These are read off live intents, and an arithmetic guard is cheaper than
    a trading loop that dies on a zero."""
    assert barriers.probability(0, 0) == pytest.approx(0.5)
    assert barriers.expectancy(3, 0) == 0.0
    assert barriers.overshoot_cost(3, 0) == 0.0
    assert barriers.duration(0, 0) > 0.0
