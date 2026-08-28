"""The hold-time estimator, and the properties that make it worth having."""

from __future__ import annotations

import math

from till_infinity.structures.holds import FEWEST, Book, Holds


def _fed(values, **over):
    h = Holds(**over)
    for v in values:
        h.observe(float(v))
    return h


def test_it_offers_nothing_until_it_has_seen_enough():
    """Extrapolating from two observations is a guess with less behind it than
    the constant it would replace."""
    assert _fed([10] * (FEWEST - 1)).expected is None
    assert _fed([10] * FEWEST).expected is not None


def test_it_estimates_the_geometric_centre():
    """The distribution is long-tailed enough that one slow touch dominates an
    arithmetic mean. Ten tens and a sixty should read near ten, not fifteen."""
    got = _fed([10] * 10 + [60])
    assert got.expected is not None
    assert 10.0 <= got.expected <= 14.0


def test_a_faster_regime_moves_the_estimate():
    """Persistence is lag-1, so recent evidence has to actually count."""
    slow = _fed([300] * 12)
    then_fast = _fed([300] * 12 + [5] * 20)
    assert then_fast.expected < slow.expected


def test_an_impossible_duration_is_ignored_not_clamped():
    """Clamping folds a fault into the estimate at the boundary, which is how a
    broken number becomes a slightly wrong one nobody notices. The push
    estimator taught this repository that lesson."""
    clean = _fed([10] * FEWEST)
    poisoned = _fed([10] * FEWEST + [10**9, -5, 0])
    assert poisoned.seen == clean.seen
    assert poisoned.expected == clean.expected


def test_the_estimate_is_in_seconds_not_log_seconds():
    """It is multiplied into a stop distance downstream; the unit matters."""
    got = _fed([100] * FEWEST)
    assert got.expected is not None
    assert abs(got.expected - 100.0) < 1.0
    assert abs(got.log_mean - math.log(100.0)) < 0.01


# ------------------------------------------------------------------- the book


def test_a_series_answers_for_itself_once_it_can():
    book = Book()
    for _ in range(FEWEST):
        book.observe("gold", "1m", 10.0)
    for _ in range(FEWEST):
        book.observe("us30", "1m", 400.0)
    assert book.expected("gold", "1m") < book.expected("us30", "1m")


def test_an_unseen_series_falls_back_to_the_pool():
    """A feed nobody has seen resolve is the common case after a restart. A
    poor pooled estimate still beats a constant chosen by hand."""
    book = Book()
    for _ in range(FEWEST):
        book.observe("gold", "1m", 10.0)
    assert book.expected("brent", "5m") is not None


def test_an_empty_book_offers_nothing():
    """Silence rather than a number with nothing behind it."""
    assert Book().expected("gold", "1m") is None


def test_the_pool_does_not_drown_a_series_that_can_answer():
    book = Book()
    for _ in range(200):
        book.observe("us30", "1m", 600.0)
    for _ in range(FEWEST):
        book.observe("gold", "1m", 5.0)
    assert book.expected("gold", "1m") < 60.0
