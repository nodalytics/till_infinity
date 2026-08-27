"""Trend context: the measure, and the ordering that makes it a prediction."""

from __future__ import annotations

from till_infinity.structures.trend import Trend


def _fed(prices, window=12):
    t = Trend(window=window)
    for p in prices:
        t.observe(float(p))
    return t


def test_a_straight_climb_is_perfectly_efficient():
    assert _fed([100, 101, 102, 103, 104]).efficiency == 1.0


def test_a_straight_fall_is_too():
    """Direction is not the question. Trending is."""
    assert _fed([104, 103, 102, 101, 100]).efficiency == 1.0


def test_an_oscillation_is_inefficient():
    assert _fed([100, 101, 100, 101, 100, 101]).efficiency < 0.25


def test_no_opinion_without_enough_history():
    """Two points is one step, which is trivially perfect and says nothing."""
    assert _fed([100]).efficiency is None
    assert _fed([100, 101]).efficiency is None


def test_no_opinion_when_price_has_not_moved():
    """Zero distance travelled would divide by zero, and a flat feed is not a
    trend however hard the arithmetic is squinted at."""
    assert _fed([100, 100, 100, 100]).efficiency is None


def test_the_window_forgets():
    """A trend that ended should stop reading as one."""
    trending = _fed([100, 101, 102, 103], window=4)
    assert trending.efficiency == 1.0
    for p in (102, 103, 102, 103):
        trending.observe(p)
    assert trending.efficiency < 0.5


# --------------------------------------------------------------------- sizing


def test_a_trend_sizes_up_and_chop_sizes_down():
    assert _fed([100, 101, 102, 103, 104]).scale(0.3) == 1.3
    assert _fed([100, 101, 100, 101, 100, 101]).scale(0.3) < 1.0


def test_sizing_is_bounded_by_its_span():
    """0.34R between extreme deciles justifies leaning, not doubling."""
    for prices in ([100, 101, 102, 103], [100, 101, 100, 101, 100]):
        assert 0.7 <= _fed(prices).scale(0.3) <= 1.3


def test_no_opinion_means_no_adjustment():
    """A feed without history sizes exactly as it did before this existed."""
    assert Trend().scale(0.3) == 1.0
    assert _fed([100, 100, 100]).scale(0.3) == 1.0


def test_sizing_is_off_when_the_span_is_zero():
    assert _fed([100, 101, 102, 103]).scale(0.0) == 1.0


# ------------------------------------------------------------ the ordering


def test_the_level_being_judged_is_not_in_its_own_window():
    """Read before observe. If the current level joined the window first, the
    measure would describe the decision instead of predicting it - the trap
    `push_vol` fell into, where a quantity signed by the outcome was scored
    against the outcome.
    """
    import inspect

    from till_infinity.trading import service as svc

    source = inspect.getsource(svc.Trader._hand_over_trend)
    assert source.index("context.efficiency") < source.index("context.observe(")
