"""Repeating structures (DTW) and multi-timeframe confluence."""

from __future__ import annotations

import math

import pytest

from till_infinity.structures import confluence, patterns
from till_infinity.structures.levels import Kalman, Level, Outcome, Side, State
from till_infinity.structures.patterns import Library, Shape, dtw, normalise
from till_infinity.structures.volatility import Volatility

PEAK = [1.0, 3.0, 5.0, 3.0, 1.0]
STRETCHED = [1.0, 2.0, 3.0, 4.0, 5.0, 4.5, 3.0, 2.0, 1.0]
INVERTED = [5.0, 3.0, 1.0, 3.0, 5.0]
RISING = [1.0, 2.0, 3.0, 4.0, 5.0]


def _shape(prices, **kw) -> Shape:
    return Shape(values=tuple(normalise(prices)), **kw)


def _vol() -> Volatility:
    vol, price = Volatility(), 4400.0
    for _ in range(60):
        price *= 1.0005
        vol.update(price)
    return vol


# ------------------------------------------------------------- normalising


def test_the_same_shape_at_any_price_is_the_same_shape():
    """A double top on gold and on BTC is one structure, not two."""
    assert normalise(PEAK) == pytest.approx(normalise([p * 1000 for p in PEAK]))


def test_scale_is_normalised_away_as_well_as_level():
    calm = normalise([100.0, 101.0, 102.0, 101.0, 100.0])
    wild = normalise([100.0, 130.0, 160.0, 130.0, 100.0])
    assert calm == pytest.approx(wild)


def test_a_flat_series_has_no_shape_rather_than_dividing_by_zero():
    assert normalise([5.0] * 6) == [0.0] * 6
    assert _shape([5.0] * 6).flat


# --------------------------------------------------------------------- dtw


def test_a_stretched_instance_is_the_same_shape():
    """The property Euclidean distance cannot express, and DTW exists for."""
    assert dtw(normalise(PEAK), normalise(STRETCHED)) < patterns.MATCH_DISTANCE


def test_an_inverted_shape_is_not_a_match():
    assert dtw(normalise(PEAK), normalise(INVERTED)) > patterns.MATCH_DISTANCE


def test_an_unrelated_shape_is_not_a_match():
    assert dtw(normalise(PEAK), normalise(RISING)) > patterns.MATCH_DISTANCE


def test_a_shape_matches_itself_exactly():
    assert dtw(normalise(PEAK), normalise(PEAK)) == 0.0


def test_distance_is_symmetric():
    a, b = normalise(PEAK), normalise(STRETCHED)
    assert dtw(a, b) == pytest.approx(dtw(b, a))


def test_an_empty_sequence_is_infinitely_far():
    assert dtw([], normalise(PEAK)) == math.inf


def test_the_band_constrains_how_far_a_warp_can_reach():
    """Unconstrained warping aligns almost anything to almost anything."""
    loose = dtw(normalise(PEAK), normalise(RISING), band=1.0)
    tight = dtw(normalise(PEAK), normalise(RISING), band=0.1)
    assert tight >= loose


# ----------------------------------------------------------------- library


def _stocked(peak_down: int = 6, peak_up: int = 2) -> Library:
    """A library where the peak shape mostly falls and rising is a coin flip."""
    library = Library()
    for i in range(peak_down + peak_up):
        key = library.add(_shape(PEAK))
        library.resolve(key, -1.5 if i < peak_down else +1.2)
    for i in range(8):
        key = library.add(_shape(RISING))
        library.resolve(key, +1.4 if i % 2 == 0 else -1.4)
    return library


def test_a_repeat_reports_what_followed_last_time():
    match = _stocked().match(_shape(PEAK))
    assert match.instances == 8
    assert match.probability_up < 0.5
    assert match.expected_move < 0


def test_a_stretched_repeat_finds_the_same_history():
    """The point of DTW: the same structure over a different number of bars."""
    match = _stocked().match(_shape(STRETCHED))
    assert match is not None
    assert match.instances == 8
    assert match.direction == "down"


def test_a_shape_with_no_edge_says_so():
    """Half up and half down is not a pattern, however often it appears."""
    match = _stocked().match(_shape(RISING))
    assert match.expected_move == pytest.approx(0.0, abs=0.2)
    assert not match.actionable


def test_an_unseen_shape_has_no_answer():
    assert _stocked().match(_shape(INVERTED)) is None


def test_a_flat_shape_is_never_recorded_or_matched():
    library = Library()
    assert library.add(_shape([5.0] * 5)) == -1
    assert library.match(_shape([5.0] * 5)) is None


def test_only_resolved_instances_count_as_evidence():
    library = Library()
    library.add(_shape(PEAK))  # recorded, never resolved
    assert library.match(_shape(PEAK)) is None
    assert library.resolved == 0


def test_an_outcome_is_recorded_once():
    library = Library()
    key = library.add(_shape(PEAK))
    assert library.resolve(key, -1.0)
    assert not library.resolve(key, +5.0)
    assert library.resolved == 1


def test_the_base_rate_sits_beside_every_conditional():
    """A shape whose P(up) equals the base rate has told you nothing."""
    library = _stocked()
    match = library.match(_shape(PEAK))
    assert match.base_rate_up == pytest.approx(library.base_rate_up)
    assert match.edge == pytest.approx(match.probability_up - match.base_rate_up)


@pytest.mark.parametrize(
    ("instances", "edge_prob", "move"),
    [(2, 0.95, 3.0), (30, 0.45, 3.0), (30, 0.90, 0.1)],
)
def test_all_three_guards_are_needed(instances, edge_prob, move):
    match = patterns.Match(
        instances=instances,
        probability_up=edge_prob,
        expected_move=move,
        move_sigma=0.1,
        base_rate_up=0.5,
        nearest=0.05,
    )
    assert not match.actionable


def test_the_library_is_bounded():
    library = Library(capacity=10)
    for _ in range(50):
        key = library.add(_shape(PEAK))
        library.resolve(key, -1.0)
    assert len(library) == 10
    assert library.resolved == 10


def test_a_shape_needs_enough_points_to_be_one():
    assert Shape.of([]) is None


# -------------------------------------------------------------- confluence


def _level(price: float, interval: str, variance: float, touches: int = 0) -> Level:
    level = Level(feed="gold", interval=interval, filter=Kalman(mean=price, variance=variance))
    for i in range(touches):
        level.record(Side.ABOVE, Outcome.REJECT, 1.0, 1_000_000.0 + i)
    return level


def test_the_finer_timeframe_decides_where_the_level_is():
    """Inverse-variance fusion: 'lower is more precise' falls out of the maths."""
    coarse = _level(4400.0, "4h", variance=4.0)
    fine = _level(4402.0, "15m", variance=0.04)
    price, _ = confluence.fuse([coarse, fine])
    assert price == pytest.approx(4402.0, abs=0.1)


def test_agreeing_timeframes_are_more_certain_than_any_one_of_them():
    members = [_level(4400.0, tf, variance=1.0) for tf in ("4h", "1h", "15m")]
    _, sigma = confluence.fuse(members)
    assert sigma < min(level.filter.sigma for level in members)


def test_levels_at_one_price_across_timeframes_become_one_zone():
    vol = _vol()
    levels = [_level(4400.0 + i * 0.02, tf, 0.5) for i, tf in enumerate(("4h", "1h", "15m"))]
    zones = confluence.combine(levels, vol)
    assert len(zones) == 1
    assert zones[0].depth == 3
    assert zones[0].span == "4h"  # how significant
    assert zones[0].precision == "15m"  # how precisely placed


def test_levels_far_apart_stay_separate():
    vol = _vol()
    zones = confluence.combine([_level(4400.0, "1h", 0.5), _level(4600.0, "1h", 0.5)], vol)
    assert len(zones) == 2


def test_a_timeframe_outside_the_span_is_not_fused_in():
    """A 1m wiggle would drag the price toward precision about the wrong thing."""
    vol = _vol()
    zones = confluence.combine([_level(4400.0, "1m", 0.001), _level(4400.0, "1h", 0.5)], vol)
    assert len(zones) == 1
    assert zones[0].timeframes == ("1h",)


def test_touch_history_is_pooled_across_timeframes():
    """Evidence at three resolutions of one price is evidence about that price."""
    vol = _vol()
    levels = [_level(4400.0, tf, 0.5, touches=3) for tf in ("4h", "1h", "15m")]
    zone = confluence.combine(levels, vol)[0]
    assert zone.sides()[Side.ABOVE].touches > 8.0


def test_confluence_lifts_strength_rather_than_averaging_it():
    """Averaging would let a weak 15m level drag down a strong 4h one."""
    vol = _vol()
    strong = _level(4400.0, "4h", 0.5, touches=10)
    weak = _level(4400.0, "15m", 0.5, touches=1)
    zone = confluence.combine([strong, weak], vol)[0]
    assert zone.strength(1_000_100.0, vol) >= strong.strength(1_000_100.0, vol)


def test_significance_comes_from_the_highest_timeframe():
    """A 15m level breaking inside a 4h level that holds is an ordinary morning."""
    vol = _vol()
    coarse = _level(4400.0, "4h", 0.5, touches=6)
    fine = _level(4400.0, "15m", 0.5, touches=2)
    fine.state = State.BROKEN
    assert confluence.combine([coarse, fine], vol)[0].state is not State.BROKEN


def test_timeframes_are_ranked_coarsest_last():
    assert confluence.rank("15m") < confluence.rank("1h") < confluence.rank("4h")
    assert confluence.rank("nonsense") == len(confluence.ORDER)


def test_zones_near_a_price_are_nearest_first():
    vol = _vol()
    zones = confluence.combine(
        [_level(4400.0, "1h", 0.5), _level(4450.0, "1h", 0.5), _level(4500.0, "1h", 0.5)], vol
    )
    assert len(zones) == 3
    near = confluence.at(zones, 4448.0, vol, within_vol=500.0)
    assert near[0].price == pytest.approx(4450.0, abs=0.5)


def test_no_levels_means_no_zones():
    assert confluence.combine([], _vol()) == []
