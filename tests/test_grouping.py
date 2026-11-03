"""Grouping candidate prices into levels, and the chaining it replaces.

The reason this module exists is a defect in `Levels._merge`, so the first
test is that defect: fed nine prices each inside the merge gap, with each
later one carrying more touches, the greedy pass returns **one** level
spanning nearly seven times the gap. It is not a hypothetical and it is not
rare - a later touch having seen more is the ordinary case.

The rest divides into three questions that get confused with each other. A
*cluster* is a partition with a bounded span and answers "which touches are
one level". A *mode* is a peak of the density and answers "where is the
agreement"; it has no bounded span, on purpose. And a *factor* decomposition
answers neither - it changes the series the levels are found in, which is the
only thing PCA can do here, since a one-dimensional cloud has exactly one
principal component and it is the price axis.
"""

from __future__ import annotations

import itertools
import math
import random

import pytest

from till_infinity.indicators import grouping
from till_infinity.indicators.levels import Level, Levels

#: Nine prices 0.30 apart: every adjacent pair is inside a 0.35 gap, and the
#: run spans 2.40 - 6.9 times it.
CHAIN = [100.0 + 0.30 * i for i in range(9)]
GAP = 0.35


class Fixed:
    """An estimator pinned at one price, so a merge test is about the merge."""

    def __init__(self, price: float, count: int) -> None:
        self.price = price
        self.count = count
        self.updated = 0.0

    def at(self, when: float) -> float:
        return self.price

    def sigma_at(self, when: float) -> float:
        return 0.1


def book(prices: list[float], touches: list[int], *, bounded: bool) -> Levels:
    """A `Levels` with its book set directly, bypassing the bar path."""
    made = Levels(bounded=bounded)
    made.when = 100.0
    made.levels = [
        Level(estimator=Fixed(price, count), side=1, from_below=count)
        for price, count in zip(prices, touches, strict=True)
    ]
    return made


# ----------------------------------------------------------- the defect itself


def test_the_greedy_merge_chains_when_a_later_level_has_more_touches():
    """**The measured defect.** Folding into the better-evidenced centre moves
    the anchor, so the next comparison is against the new price and the run
    collapses without limit. The surviving centre is the end of the run, a
    price only one of the nine touches sat at."""
    greedy = book(CHAIN, list(range(1, 10)), bounded=False)
    greedy._merge(1.0)

    assert len(greedy.levels) == 1
    held = greedy.levels[0].at(greedy.when)
    assert held == pytest.approx(102.4)
    assert (CHAIN[-1] - CHAIN[0]) / GAP == pytest.approx(6.857, abs=0.01)


def test_the_same_prices_with_equal_touches_do_not_chain():
    """Which makes the point that it is the touch counts and not the prices:
    with nothing to overtake the anchor, the same input gives five levels.
    A test of the prices alone would have missed the defect entirely."""
    greedy = book(CHAIN, [1] * 9, bounded=False)
    greedy._merge(1.0)
    assert len(greedy.levels) == 5


def test_the_bounded_merge_converges_instead_of_collapsing():
    """The replacement, on the input that breaks the original.

    **The guarantee is a bounded span, not a minimum separation between
    survivors**, and those are different properties. A group folds into its
    best-evidenced member, which can sit at the group's edge, so two survivors
    can end up closer than the width - and demanding otherwise would put the
    answer back at the mercy of the scan order.

    What matters is that repeated passes settle instead of eating the book.
    Nine levels become five, then four, then stay four; the greedy pass turns
    the same input into one.
    """
    bounded = book(CHAIN, list(range(1, 10)), bounded=True)
    counts = []
    for _ in range(4):
        bounded._merge(1.0)
        counts.append(len(bounded.levels))

    assert counts == [5, 4, 4, 4]


def test_the_bounded_merge_keeps_the_touches_it_folds():
    """A merge that lost touches would make a level look less evidenced than
    it is, and `touches` is what the ladder and the strongest-level query both
    rank on."""
    bounded = book(CHAIN, list(range(1, 10)), bounded=True)
    before = sum(x.from_below for x in bounded.levels)
    bounded._merge(1.0)
    assert sum(x.from_below for x in bounded.levels) == before


def test_the_two_merges_are_told_apart_by_the_indicator_identity():
    """Two books merged differently are two different indicators. They shared
    a repr before, and this desk has already had two modules resolve to one
    persistence key and silently shadow each other."""
    assert repr(Levels()) != repr(Levels(bounded=True))
    assert "greedy" in repr(Levels())
    assert "bounded" in repr(Levels(bounded=True))


# --------------------------------------------------------------- the clustering


def test_a_group_never_exceeds_the_width():
    """The property the whole module is for, on a run that would chain."""
    for group in grouping.cluster(CHAIN, GAP, weights=list(range(1, 10))):
        assert group.span <= GAP + 1e-12


def test_the_answer_does_not_depend_on_the_order():
    """Complete linkage is a property of the set. The greedy pass is a
    property of the scan, which is how the same book came to collapse
    differently read upwards and downwards."""
    straight = [round(g.centre, 9) for g in grouping.cluster(CHAIN, GAP)]
    for seed in range(5):
        shuffled = CHAIN[:]
        random.Random(seed).shuffle(shuffled)
        assert [round(g.centre, 9) for g in grouping.cluster(shuffled, GAP)] == straight


def test_the_answer_does_not_depend_on_the_weights():
    """Weights move a group's centre and must not move its membership - the
    membership depending on them is exactly what chains."""
    plain = [(g.members, round(g.span, 9)) for g in grouping.cluster(CHAIN, GAP)]
    heavy = [
        (g.members, round(g.span, 9))
        for g in grouping.cluster(CHAIN, GAP, weights=[100.0**i for i in range(9)])
    ]
    assert plain == heavy


def test_the_centre_is_where_the_evidence_is():
    """A weighted mean, not the midpoint: a level's price is where the touches
    are, and a midpoint moves with whichever straggler sits at the edge."""
    found = grouping.cluster([100.0, 100.3], 0.35, weights=[9.0, 1.0])
    assert len(found) == 1
    assert found[0].centre == pytest.approx(100.03)


def test_a_zero_width_groups_nothing():
    """The honest reading of "nothing is close enough to anything", rather
    than one group holding the book."""
    assert len(grouping.cluster(CHAIN, 0.0)) == len(CHAIN)


def test_a_weight_paired_with_the_wrong_price_is_refused():
    """It would move a level towards the wrong evidence, silently."""
    with pytest.raises(ValueError, match="wrong price"):
        grouping.cluster(CHAIN, GAP, weights=[1.0, 2.0])


def test_an_empty_book_groups_to_nothing():
    assert grouping.cluster([], GAP) == []


# ------------------------------------------------------------------- the modes


def test_two_humps_give_two_modes():
    """A mode is where the agreement is. Both humps are tighter than the
    bandwidth and far apart, so this is the case a density estimate must get
    right before any harder one is asked of it."""
    found = grouping.modes([100.0, 100.05, 100.1, 100.08, 103.0, 103.05, 102.95], 0.3)
    assert [round(m.centre, 1) for m in found] == [100.1, 103.0]


def test_a_broad_shelf_is_one_mode_where_a_width_would_cut_it():
    """The difference between the two estimators, stated as a test. The shelf
    spans 1.2 units at a width of 0.35, so `cluster` returns several groups
    and `modes` returns one - and for watchedness the one is the right
    answer, because the touches do agree, loosely."""
    shelf = [100.0 + 0.2 * i for i in range(7)]
    assert len(grouping.cluster(shelf, GAP)) > 1
    assert len(grouping.modes(shelf, 1.0)) == 1


def test_a_mode_carries_the_weight_that_found_it():
    """Watchedness is a count of agreeing turns, so the weight has to survive
    - a mode's position without its weight cannot be ranked against another."""
    found = grouping.modes([100.0, 100.02, 103.0], 0.2, weights=[5.0, 5.0, 1.0])
    heaviest = max(found, key=lambda m: m.weight)
    assert heaviest.centre == pytest.approx(100.01, abs=0.05)
    assert heaviest.weight == pytest.approx(10.0)


def test_a_zero_bandwidth_finds_no_modes():
    """Rather than one mode per price, which would say every touch is its own
    agreement."""
    assert grouping.modes(CHAIN, 0.0) == []


# --------------------------------------------------------- nearest neighbours


def test_the_nearest_are_returned_closest_first():
    assert grouping.nearest(101.0, [100.0, 103.0, 100.5], 2) == [(0.5, 100.5), (1.0, 100.0)]


def test_a_tie_above_and_below_resolves_the_same_way_every_time():
    """The common tie, and an unstable order would make a nearest-level
    feature flicker between two prices without either moving."""
    first = grouping.nearest(100.0, [99.5, 100.5], 1)
    for _ in range(5):
        assert grouping.nearest(100.0, [100.5, 99.5], 1) == first


def test_crowding_is_larger_where_the_turns_agree():
    """The watchedness reading. Carries the occupancy confound named in the
    module docstring - it is large where price spent time, whether or not
    anybody is computing that price - so it is a feature, not a signal."""
    cloud = [100.0, 100.05, 100.1, 100.08, 103.0]
    assert grouping.crowding(100.05, cloud, 3) > grouping.crowding(110.0, cloud, 3)


def test_crowding_on_an_empty_book_is_zero_not_an_infinity():
    """So a caller comparing feeds does not have to special-case it."""
    assert grouping.crowding(100.0, [], 3) == 0.0
    assert grouping.crowding(100.0, [100.0], 3, unit=0.0) == 0.0


def test_a_neighbour_at_the_price_itself_is_capped():
    """ "Closer than a hundredth of a unit" and "exactly here" are the same
    statement about a level, and one of them is not a larger number."""
    assert grouping.crowding(100.0, [100.0], 1) == pytest.approx(100.0)


# ----------------------------------------------- the factor path, with control


def planted(seed: int = 7, n: int = 600):
    """A panel with a known common factor and per-instrument noise."""
    rng = random.Random(seed)
    factor = [rng.gauss(0.0, 1.0) for _ in range(n)]
    panel = [[b * f + rng.gauss(0.0, 0.5) for f in factor] for b in (1.0, 0.8, -0.6, 1.2, 0.4)]
    return factor, panel


def correlation(a, b) -> float:
    top = sum(x * y for x, y in zip(a, b, strict=True))
    bottom = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return top / bottom if bottom > 0.0 else 0.0


def test_the_planted_factor_is_recovered():
    """The positive control. A decomposition that cannot find a factor put
    there on purpose says nothing about one that was not."""
    factor, panel = planted()
    assert abs(correlation(grouping.common(panel), factor)) > 0.9


def test_the_residual_has_the_factor_removed():
    """What the factor path is actually for: a level in here is specific to
    this instrument rather than a price its whole panel passed through
    together."""
    _, panel = planted()
    found = grouping.common(panel)
    path = grouping.residual(panel[0], found)
    steps = [b - a for a, b in itertools.pairwise(path)]

    assert abs(correlation(panel[0], found)) > 0.8, "the raw series carries the factor"
    assert abs(correlation(steps, found[1:])) < 0.05, "the residual does not"


def test_the_residual_is_a_path_a_level_book_can_be_fed():
    """Returns in, prices out, one per input bar - a level book wants a price
    series, not a return series."""
    _, panel = planted(n=50)
    path = grouping.residual(panel[0], grouping.common(panel), start=1.25)
    assert len(path) == 50
    assert path[0] == pytest.approx(1.25 + panel[0][0], abs=1.0)


def test_a_panel_of_one_has_no_common_factor():
    """And the leading component of a single series is that series, which is
    not a factor and must not be returned as one."""
    assert grouping.common([[1.0, 2.0, 3.0]]) == []
    assert grouping.common([]) == []


def test_rows_of_different_lengths_are_refused():
    """The alignment error this desk has already made: align the series, then
    difference, or every session gap becomes a one-bar return."""
    with pytest.raises(ValueError, match="align the series"):
        grouping.common([[1.0, 2.0, 3.0], [1.0, 2.0]])


def test_a_residual_needs_both_series_for_the_same_bars():
    with pytest.raises(ValueError, match="only defined where both"):
        grouping.residual([1.0, 2.0, 3.0], [1.0, 2.0])


def test_a_constant_panel_has_no_factor_rather_than_a_spurious_one():
    """Zero variance is the degenerate case a power iteration can divide by,
    and a factor invented from it would be regressed out of real series."""
    assert grouping.common([[1.0] * 20, [2.0] * 20, [3.0] * 20]) == []


# ------------------------------------------------- which price in a group is it


def test_a_floor_is_the_lowest_touch_and_a_ceiling_the_highest():
    """**A floor is where price stopped, not the average of where it
    stopped.** The lowest touch of a support cluster is the price that held;
    the weighted mean sits inside the body of touches, which is a price price
    has already traded through."""
    group = grouping.cluster([99.80, 99.95, 100.00, 100.02], GAP, weights=[1, 3, 4, 2])[0]

    assert group.price(grouping.Anchor.FLOOR) == pytest.approx(99.80)
    assert group.price(grouping.Anchor.CEILING) == pytest.approx(100.02)
    assert group.price(grouping.Anchor.CENTRE) == pytest.approx(99.969)


def test_a_stop_at_the_centre_of_a_support_sits_inside_the_cluster():
    """Which is the reason the anchor exists. A stop below the mean of a
    support cluster is still above its lowest touch, so the level has to be
    broken before the stop is even reached - the opposite of its purpose."""
    group = grouping.cluster([99.80, 99.95, 100.00, 100.02], GAP, weights=[1, 3, 4, 2])[0]
    assert group.price(grouping.Anchor.CENTRE) > group.price(grouping.Anchor.FLOOR)


def test_the_sided_anchor_follows_the_pivot_that_formed_the_level():
    """`levels.Level.side` is +1 resistance and -1 support, and it is the side
    that *formed* the level rather than where it sits relative to price now -
    which is the stable thing to key on, since the latter flips as price
    moves."""
    group = grouping.cluster([99.80, 100.02], GAP)[0]
    assert group.price(grouping.Anchor.SIDED, side=-1) == pytest.approx(99.80)
    assert group.price(grouping.Anchor.SIDED, side=1) == pytest.approx(100.02)


def test_a_sideless_level_falls_back_to_the_centre():
    """An unformed side is an absence, and picking the floor for it would make
    every sideless level a support."""
    group = grouping.cluster([99.80, 100.02], GAP)[0]
    assert group.price(grouping.Anchor.SIDED, side=0) == pytest.approx(group.centre)


def test_the_anchor_takes_its_own_name_as_a_string():
    """So a config can carry it without importing the enum."""
    group = grouping.cluster([99.80, 100.02], GAP)[0]
    assert group.price("floor") == group.price(grouping.Anchor.FLOOR)
    with pytest.raises(ValueError, match="floor"):
        group.price("middle")


def test_a_one_touch_group_reads_the_same_under_every_anchor():
    """The degenerate case, and worth pinning: a level with one touch has no
    edge distinct from its centre, so nothing should move."""
    group = grouping.cluster([100.0], GAP)[0]
    prices = {group.price(a) for a in grouping.Anchor}
    assert prices == {100.0}


def test_an_extreme_is_the_noisier_estimate():
    """The honest trade-off, as a test rather than only a docstring. One spike
    moves an edge and nothing averages it out, where the centre is an estimate
    over the whole group - so the extreme is the better definition and the
    worse estimator."""
    clean = grouping.cluster([100.0, 100.05, 100.1], GAP, weights=[5, 5, 5])[0]
    spiked = grouping.cluster([99.78, 100.0, 100.05, 100.1], GAP, weights=[1, 5, 5, 5])[0]

    moved_floor = abs(spiked.price(grouping.Anchor.FLOOR) - clean.price(grouping.Anchor.FLOOR))
    moved_centre = abs(spiked.centre - clean.centre)
    assert moved_floor > moved_centre
