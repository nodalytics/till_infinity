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
from till_infinity.structures.drawing import equals, gaps, pips, rounds
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
