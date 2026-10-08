"""The formations added beside `pip`, `run` and `origin`.

Three claims that fail differently, which is the whole reason for running them
together: equal extremes are about a price being reached twice, an imbalance is
about trade that did not happen, and a round number is about nothing that
happened at all. A level several of them agree on has been found by methods
whose mistakes are unrelated.
"""

import random

import pytest

from till_infinity.structures import levels as lv
from till_infinity.structures.drawing import displacement, equals, gaps, pips, rounds
from till_infinity.structures.drawing.pips import Point, Swing
from till_infinity.structures.engine import Engine
from till_infinity.structures.vol.volatility import Volatility


def warm(prices, steps=400):
    vol = Volatility()
    for p in prices[:steps] or prices:
        vol.update(p)
    return vol


def wander(base=4400.0, noise=4.0, bars=400, seed=1):
    random.seed(seed)
    return [base + random.gauss(0, noise) for _ in range(bars)]


def turn(price, when, side, index=0):
    return Point(
        index=index,
        time=int(when),
        price=price,
        swing=side,
        prominence_bps=100.0,
        confirmed=float(when),
    )


# --------------------------------------------------------------- equal highs


def test_two_extremes_at_one_price_are_a_pair():
    vol = warm(wander())
    found = equals.equals([turn(4400.0, 1, Swing.HIGH), turn(4400.2, 2, Swing.HIGH)], vol)
    assert len(found) == 1
    assert len(found[0]) == 2


def test_extremes_a_whole_unit_apart_are_not_equal():
    """`form` already clusters at a unit. This pass exists to ask the tighter
    question, so it must not answer the loose one."""
    prices = wander()
    vol = warm(prices)
    apart = vol.price_units(4400.0, 0.9)
    found = equals.equals([turn(4400.0, 1, Swing.HIGH), turn(4400.0 + apart, 2, Swing.HIGH)], vol)
    assert found == []


def test_a_high_and_a_low_at_one_price_are_not_a_double_top():
    """That is a price which has been both support and resistance - a different
    and already-modelled thing. Mixed in, it reports a level as twice-rejected
    when it was rejected once from each direction."""
    vol = warm(wander())
    found = equals.equals([turn(4400.0, 1, Swing.HIGH), turn(4400.1, 2, Swing.LOW)], vol)
    assert found == []


def test_a_lone_extreme_is_not_emitted():
    vol = warm(wander())
    assert equals.equals([turn(4400.0, 1, Swing.HIGH)], vol) == []


def test_more_twins_outrank_fewer():
    vol = warm(wander())
    many = [turn(4400.0 + i * 0.05, i, Swing.HIGH) for i in range(4)]
    pair = [turn(4500.0, 9, Swing.LOW), turn(4500.05, 10, Swing.LOW)]
    found = equals.equals(many + pair, vol)
    assert [len(group) for group in found] == [4, 2]


def test_a_double_top_becomes_points_that_keep_their_own_times():
    """They are real turns, not a synthesised average, so the outcome machinery
    sees the objects it always has."""
    prices = [4400.0 - i * 0.5 for i in range(30)]
    prices += [4400.0 - (29 - i) * 0.5 for i in range(30)] * 3
    times = [float(i) * 300 for i in range(len(prices))]
    vol = warm(prices)
    found = equals.points(times, prices, vol)
    assert all(point.time in {int(t) for t in times} for point in found)


# ----------------------------------------------------------- the imbalance


def gapped(size=40.0, bars=60, base=4400.0):
    """A three-bar move that leaves an untraded range, then price walks away."""
    highs = [base + 2.0] * bars
    lows = [base - 2.0] * bars
    at = 20
    highs[at], lows[at] = base + size, base + 2.0
    highs[at + 1], lows[at + 1] = base + size + 4.0, base + size - 2.0
    for i in range(at + 1, bars):
        highs[i], lows[i] = base + size + 6.0, base + size - 4.0
    return highs, lows


def test_a_three_bar_move_leaves_a_gap():
    highs, lows = gapped()
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    vol = warm(closes)
    found = gaps.gaps(highs, lows, vol)
    assert found
    _index, low, high, size = found[0]
    assert low < high
    assert size >= gaps.MIN_GAP_VOL


def test_a_gap_smaller_than_the_noise_is_two_bars():
    highs, lows = gapped(size=2.05)
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    assert gaps.gaps(highs, lows, warm(closes)) == []


def test_a_filled_gap_is_finished_business():
    """Emitting it would claim the opposite of what the idea says."""
    highs, lows = gapped()
    # Price comes all the way back through the range afterwards.
    highs[-1], lows[-1] = 4460.0, 4395.0
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    assert gaps.gaps(highs, lows, warm(closes)) == []


def test_a_gap_is_confirmed_by_the_third_bar_not_the_middle_one():
    """It does not exist until the third bar has printed - that is what makes
    it a gap - so `confirmed` must not be a bar earlier than the evidence."""
    highs, lows = gapped()
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    times = [float(i) * 300 for i in range(len(closes))]
    found = gaps.points(times, highs, lows, closes, warm(closes))
    assert found
    for point in found:
        assert point.confirmed > point.time


def test_a_gap_takes_the_side_it_is_not_on():
    highs, lows = gapped()
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    times = [float(i) * 300 for i in range(len(closes))]
    spot = closes[-1]
    for point in gaps.points(times, highs, lows, closes, warm(closes)):
        assert point.swing is (Swing.HIGH if point.price > spot else Swing.LOW)


def test_a_flat_series_has_no_imbalance():
    flat = [4400.0 + (i % 3) for i in range(200)]
    highs = [p + 1.0 for p in flat]
    lows = [p - 1.0 for p in flat]
    assert gaps.gaps(highs, lows, warm(flat)) == []


# ------------------------------------------------- the rest of the family


def bodies(highs, lows, up=True):
    """Opens and closes filling each bar's range, so bodies are whole bars."""
    if up:
        return list(lows), list(highs)
    return list(highs), list(lows)


def test_a_body_gap_inside_overlapping_ranges_is_a_volume_imbalance():
    """The distinction `fvg` cannot draw: price was quoted here and barely
    traded, which is a weaker claim than a hole in the range."""
    bars, base = 60, 4400.0
    highs = [base + 2.0] * bars
    lows = [base - 2.0] * bars
    opens = [base - 1.0] * bars
    closes = [base + 1.0] * bars
    at = 20
    # Bar `at` closes at +12 and the next opens at +30, while their wicks still
    # overlap - so the ranges touch and the bodies do not.
    highs[at], lows[at], opens[at], closes[at] = base + 32.0, base - 2.0, base, base + 12.0
    highs[at + 1], lows[at + 1] = base + 40.0, base + 10.0
    opens[at + 1], closes[at + 1] = base + 30.0, base + 38.0
    for i in range(at + 2, bars):
        highs[i], lows[i] = base + 46.0, base + 40.0
        opens[i], closes[i] = base + 41.0, base + 45.0
    found = gaps.volume_imbalances(opens, highs, lows, closes, warm(closes))
    assert found
    assert found[0].kind == "vi"
    assert found[0].up is True
    # the wicks overlap, which is what makes it a `vi` rather than an `og`
    assert lows[at + 1] <= highs[at]
    assert gaps.opening_gaps(highs, lows, warm(closes)) == []


def test_bars_that_do_not_touch_at_all_are_an_opening_gap():
    bars, base = 60, 4400.0
    highs = [base + 2.0] * bars
    lows = [base - 2.0] * bars
    at = 20
    for i in range(at + 1, bars):
        highs[i], lows[i] = base + 46.0, base + 40.0
    found = gaps.opening_gaps(
        highs, lows, warm([(h + low) / 2 for h, low in zip(highs, lows, strict=True)])
    )
    assert found
    assert found[0].kind == "og"
    assert found[0].up is True
    assert found[0].low == highs[at]
    assert found[0].high == lows[at + 1]


def test_a_bar_that_is_nearly_all_body_is_a_void():
    """The desk's displacement rule as a formation, and its band is the body."""
    bars, base = 60, 4400.0
    highs = [base + 2.0] * bars
    lows = [base - 2.0] * bars
    opens = [base - 1.0] * bars
    closes = [base + 1.0] * bars
    at = 20
    highs[at], lows[at] = base + 41.0, base - 1.0
    opens[at], closes[at] = base, base + 40.0
    for i in range(at + 1, bars):
        highs[i], lows[i] = base + 46.0, base + 40.0
        opens[i], closes[i] = base + 41.0, base + 45.0
    found = gaps.voids(opens, highs, lows, closes, warm(closes))
    assert found
    assert found[0].kind == "void"
    assert found[0].low == opens[at]
    assert found[0].high == closes[at]


def test_a_wick_heavy_bar_is_not_a_void():
    """Body share is the whole test: the same range, mostly wick."""
    bars, base = 60, 4400.0
    highs = [base + 2.0] * bars
    lows = [base - 2.0] * bars
    opens = [base - 1.0] * bars
    closes = [base + 1.0] * bars
    at = 20
    highs[at], lows[at] = base + 41.0, base - 1.0
    opens[at], closes[at] = base + 10.0, base + 20.0  # body is a quarter of the range
    for i in range(at + 1, bars):
        highs[i], lows[i] = base + 46.0, base + 40.0
        opens[i], closes[i] = base + 41.0, base + 45.0
    assert gaps.voids(opens, highs, lows, closes, warm(closes)) == []


def test_a_gap_closed_through_inverts():
    """`gaps` drops it and `inversions` is the kind that wants it."""
    highs, lows = gapped()
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    # Price closes back below the gap's low, which breaks it rather than
    # testing it.
    closes[-1] = 4300.0
    lows[-1] = 4295.0
    vol = warm(closes)
    assert gaps.gaps(highs, lows, vol) == []
    found = gaps.inversions(highs, lows, closes, vol)
    assert found
    assert found[0].kind == "ifvg"
    # it was left by a move up and now reads the other way
    assert found[0].up is False


def test_an_untested_gap_does_not_invert():
    highs, lows = gapped()
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    assert gaps.inversions(highs, lows, closes, warm(closes)) == []


def test_opposing_gaps_that_overlap_are_a_balanced_range():
    bars, base = 80, 4400.0
    highs = [base + 2.0] * bars
    lows = [base - 2.0] * bars
    up_at = 20
    for i in range(up_at + 1, bars):
        highs[i], lows[i] = base + 46.0, base + 40.0
    # and back down through the same band, leaving a gap the other way
    down_at = 40
    for i in range(down_at + 1, bars):
        highs[i], lows[i] = base + 3.0, base - 3.0
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    found = gaps.balanced_ranges(highs, lows, warm(closes))
    assert found  # or the loop below asserts nothing at all
    for one in found:
        assert one.kind == "bpr"
        assert one.low < one.high


def test_the_family_is_one_sorted_list():
    highs, lows = gapped()
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    opens = list(closes)
    found = gaps.imbalances(opens, highs, lows, closes, warm(closes))
    assert [g.index for g in found] == sorted(g.index for g in found)
    assert {g.kind for g in found} <= set(gaps.KINDS)


def test_the_body_kinds_are_skipped_without_opens():
    """A body inferred from the range is a different object wearing the name."""
    highs, lows = gapped()
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    times = [float(i) * 300 for i in range(len(closes))]
    vol = warm(closes)
    without = gaps.points(times, highs, lows, closes, vol)
    assert without == gaps.points(
        times, highs, lows, closes, vol, kinds=("fvg", "og", "ifvg", "bpr")
    )


def test_the_original_three_bar_gap_still_draws_what_it_did():
    """The `gap` pass is live, so the family must not move the level it drew."""
    highs, lows = gapped()
    closes = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    times = [float(i) * 300 for i in range(len(closes))]
    vol = warm(closes)
    only_fvg = gaps.points(times, highs, lows, closes, vol, kinds=("fvg",))
    assert only_fvg
    assert [(p.index, p.price) for p in only_fvg] == [
        (index, (low + high) / 2.0) for index, low, high, _ in gaps.gaps(highs, lows, vol)
    ]


# --------------------------------------------------------- the round number


@pytest.mark.parametrize(
    ("base", "noise", "want"),
    [(4400.0, 4.0, 100.0), (1.1000, 0.0009, 0.01), (78_000.0, 400.0, 10_000.0)],
)
def test_the_step_comes_from_the_instrument_rather_than_a_table(base, noise, want):
    """A table is what this repository keeps finding bugs in: an instrument
    arrives, nobody adds a row, and the formation silently draws nothing."""
    vol = warm(wander(base, noise))
    assert rounds.step_for(base, vol) == pytest.approx(want)


def test_whole_numbers_outrank_halves():
    prices = wander()
    found = rounds.levels_near(4400.0, warm(prices))
    by_price = dict(found)
    assert by_price[4400.0] > by_price.get(4450.0, 0.0)


def test_nothing_beyond_reach_is_emitted():
    """A round number thirty units away is not a level anything reaches inside
    a hold, and emitting it costs a level slot for nothing."""
    prices = wander()
    vol = warm(prices)
    reach = vol.price_units(4400.0, rounds.REACH_VOL)
    for at, _ in rounds.levels_near(4400.0, vol):
        assert abs(at - 4400.0) <= reach + 1e-9


def test_a_round_level_needs_no_history():
    """The only formation here that does not read the window - which is why it
    is measured rather than assumed."""
    prices = wander()
    vol = warm(prices)
    times = [float(i) * 300 for i in range(len(prices))]
    assert rounds.points(times, prices, vol)


# ------------------------------------------------------------ the wiring


def test_every_formation_is_reachable_by_name():
    """A pass the engine cannot be asked for is a pass that does not exist, and
    `origin` shipped exactly that way once."""
    for name in Engine.FORMATIONS:
        assert Engine(formation=name).passes == (name,)


def test_the_new_formations_compose_with_the_old():
    engine = Engine(formation="pip,run,origin,profile,equal,gap,round")
    assert len(engine.passes) == 7


def test_an_unknown_formation_names_the_ones_that_exist():
    with pytest.raises(ValueError, match="equal"):
        Engine(formation="candles")


def test_each_formation_returns_points_form_can_take():
    """The contract that lets `agree` work: every pass emits the same `Point`,
    so nothing downstream can tell which found a level."""
    prices = wander(bars=300)
    times = [float(i) * 300 for i in range(len(prices))]
    vol = warm(prices)
    for name in ("equal", "round"):
        found = (equals if name == "equal" else rounds).points(times, prices, vol)
        made = lv.form("gold", "5m", pips.turns(found), vol, origin=name)
        assert isinstance(made, list)


# ------------------------------------------------------- the displacement


def displaced(bars=60, base=4400.0, body=0.9, run=2, step=30.0):
    """An origin bar, then `run` one-sided bars away from it."""
    opens = [base - 1.0] * bars
    closes = [base + 1.0] * bars
    highs = [base + 2.0] * bars
    lows = [base - 2.0] * bars
    at = 20
    # the origin: a small bar - body a quarter of its range - colour irrelevant
    opens[at], closes[at] = base + 0.5, base - 0.5
    highs[at], lows[at] = base + 2.0, base - 2.0
    price = base
    for k in range(1, run + 1):
        i = at + k
        opens[i] = price
        closes[i] = price + step
        pad = step * (1.0 - body) / 2.0
        lows[i], highs[i] = price - pad, price + step + pad
        price += step
    for i in range(at + run + 1, bars):
        opens[i], closes[i] = price, price + 1.0
        lows[i], highs[i] = price - 1.0, price + 2.0
    return opens, highs, lows, closes


def test_two_one_sided_bars_leave_an_origin():
    opens, highs, lows, closes = displaced()
    found = displacement.displacements(opens, highs, lows, closes, warm(closes))
    assert found
    one = found[0]
    assert one.up is True
    # the band is the origin bar's whole range
    assert one.low == lows[20]
    assert one.high == highs[20]
    # and the line is the body's bottom, which for this red origin is its close
    assert one.line == closes[20]


def test_the_origin_colour_does_not_matter():
    """The desk tested it and said it does not, so nothing may look at it."""
    opens, highs, lows, closes = displaced()
    red = displacement.displacements(opens, highs, lows, closes, warm(closes))
    opens[20], closes[20] = closes[20], opens[20]  # same band, flipped colour
    green = displacement.displacements(opens, highs, lows, closes, warm(closes))
    assert [(g.low, g.high, g.line) for g in red] == [(g.low, g.high, g.line) for g in green]


def test_an_origin_that_travelled_is_not_one():
    """The desk said the origin is "normally a small candle", and without that
    this pass drew three to four times what every other formation draws."""
    opens, highs, lows, closes = displaced()
    at = 20
    # same range, but now the bar itself travelled most of it
    opens[at], closes[at] = highs[at] - 0.1, lows[at] + 0.1
    assert displacement.displacements(opens, highs, lows, closes, warm(closes)) == []


def test_a_doji_origin_is_not_a_small_candle():
    """It is an undecided one - the body edge this pass emits would be an
    arbitrary point inside a range nobody defended."""
    opens, highs, lows, closes = displaced()
    at = 20
    opens[at] = closes[at] = (highs[at] + lows[at]) / 2.0
    assert displacement.displacements(opens, highs, lows, closes, warm(closes)) == []


def test_a_wicky_push_is_not_a_displacement():
    opens, highs, lows, closes = displaced(body=0.4)
    assert displacement.displacements(opens, highs, lows, closes, warm(closes)) == []


def test_one_bar_is_not_a_push():
    """`PUSH_N` is two, and one decisive bar is a common and ordinary shape."""
    opens, highs, lows, closes = displaced(run=1)
    assert displacement.displacements(opens, highs, lows, closes, warm(closes)) == []


def test_the_leg_floor_is_what_makes_it_mean_a_move_started():
    """Body share says the bars were one-sided and nothing at all about size,
    so `MIN_LEG_VOL` is the constant carrying that half of the claim."""
    opens, highs, lows, closes = displaced()
    vol = warm(closes)
    assert displacement.displacements(opens, highs, lows, closes, vol)
    far = displacement.displacements(opens, highs, lows, closes, vol, minimum_vol=1e6)
    assert far == []


def test_bars_of_two_colours_are_not_a_push():
    opens, highs, lows, closes = displaced(run=2)
    # flip the second push bar's direction, keeping its body share
    opens[22], closes[22] = closes[22], opens[22]
    assert displacement.displacements(opens, highs, lows, closes, warm(closes)) == []


def test_an_origin_is_not_knowable_before_its_push_prints():
    """The whole look-ahead question for this formation."""
    opens, highs, lows, closes = displaced()
    times = [float(i) * 300 for i in range(len(closes))]
    found = displacement.points(times, opens, highs, lows, closes, warm(closes))
    assert found
    for point in found:
        assert point.confirmed > point.time


def test_the_point_is_the_body_edge_not_the_middle():
    opens, highs, lows, closes = displaced()
    times = [float(i) * 300 for i in range(len(closes))]
    found = displacement.points(times, opens, highs, lows, closes, warm(closes))
    assert found
    middle = (lows[20] + highs[20]) / 2.0
    assert found[0].price != middle
    assert found[0].price == closes[20]


def test_a_flat_series_has_no_displacement():
    flat = [4400.0 + (i % 3) for i in range(200)]
    opens = list(flat)
    closes = [p + 0.1 for p in flat]
    highs = [p + 1.0 for p in flat]
    lows = [p - 1.0 for p in flat]
    assert displacement.displacements(opens, highs, lows, closes, warm(flat)) == []
