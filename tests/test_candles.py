"""Candlestick confirmation, and the ways a pattern can lie."""

from __future__ import annotations

from till_infinity.trading.candles import Bar, confirms, engulfing, hammer, shooting_star


def bar(o, h, lo, c):
    return Bar(open=o, high=h, low=lo, close=c)


# --------------------------------------------------------------- the shapes


def test_a_hammer_is_a_long_tail_and_a_small_body_up_top():
    assert hammer(bar(100, 100.5, 96, 100.2))


def test_a_hammer_need_not_close_up():
    """Its message is in the tail - down, no takers, back - and whether the
    close finished a tick either side of the open is where it opened, not what
    happened inside it."""
    assert hammer(bar(100.2, 100.5, 96, 100.0))


def test_a_long_tail_with_the_body_in_the_middle_is_not_a_hammer():
    """That is indecision, not rejection."""
    assert not hammer(bar(98, 100.5, 96, 98.4))


def test_a_bar_with_two_long_wicks_is_not_a_hammer():
    assert not hammer(bar(100, 104, 96, 100.2))


def test_a_body_of_almost_nothing_is_the_strongest_hammer_not_a_refused_one():
    """A dragonfly doji at a level is the pattern at its most complete - price
    left and came all the way back. A body-relative rule would have to refuse
    it to avoid dividing by nothing, which is the wrong shape to refuse."""
    assert hammer(bar(100, 100.5, 96, 100.001))


def test_a_bar_with_no_range_is_not_a_pattern():
    assert not hammer(bar(100, 100, 100, 100))
    assert not shooting_star(bar(100, 100, 100, 100))


def test_a_shooting_star_is_the_mirror():
    assert shooting_star(bar(100, 104, 99.5, 99.8))
    assert not shooting_star(bar(100, 100.5, 96, 100.2))


def test_engulfing_is_about_bodies_not_ranges():
    """A bar whose range covers the previous range but whose body does not is
    a wider bar, not a reversal."""
    previous = bar(100, 101, 99, 99.5)  # small down body 99.5-100
    wide_range = bar(99.6, 102, 98, 99.9)  # range covers, body does not
    assert engulfing(previous, wide_range) == ""
    real = bar(99.4, 102, 99.3, 100.5)  # body 99.4-100.5 covers it
    assert engulfing(previous, real) == "up"


def test_engulfing_must_reverse_the_direction():
    """Two down bars, the second larger, is continuation."""
    previous = bar(100, 100.2, 99, 99.5)
    bigger = bar(100.5, 100.6, 98, 98.5)
    assert engulfing(previous, bigger) == ""


# ------------------------------------------------------- confirmation at a level


def test_a_pattern_away_from_the_level_does_not_count():
    """A hammer in open space is a bar with a long tail. The level is what
    makes it a level being defended."""
    bars = [bar(100, 101, 99, 100), bar(100, 100.5, 96, 100.2)]
    assert confirms(bars, level=90.0, want_up=True) == ""


def test_a_hammer_at_the_level_confirms_a_buy():
    bars = [bar(100, 101, 99, 100), bar(100, 100.5, 96, 100.2)]
    assert confirms(bars, level=96.5, want_up=True) == "hammer"


def test_a_wick_through_the_level_that_closes_below_it_is_not_support_holding():
    """It is support breaking, drawn in a shape that looks reassuring. This is
    the single most important check in the module."""
    # Long lower tail, but the close is under the level it should have held.
    bars = [bar(100, 101, 99, 100), bar(99, 99.2, 95, 98.9)]
    assert confirms(bars, level=99.5, want_up=True) == ""


def test_the_mirror_holds_for_a_sell():
    bars = [bar(100, 100.2, 99, 99.8), bar(100, 104, 99.5, 99.8)]
    assert confirms(bars, level=103.5, want_up=False) == "shooting-star"
    # Closing above the level it should have been rejected from: not a sell.
    assert confirms(bars, level=99.0, want_up=False) == ""


def test_confirmation_needs_two_bars():
    """Engulfing needs a previous bar, and having one is cheaper to require
    than to special-case."""
    assert confirms([bar(100, 100.5, 96, 100.2)], level=96.5, want_up=True) == ""
