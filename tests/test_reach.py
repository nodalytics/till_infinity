"""Entry depth and stop distance, read as quantiles of what actually happened."""

from __future__ import annotations

from till_infinity.structures.reach import FEWEST, WINDOW, Reach, Reaches


def _fed(values):
    r = Reach()
    for v in values:
        r.observe(float(v))
    return r


def test_it_answers_nothing_until_it_has_a_sample():
    """A quantile of four observations is not a quantile."""
    assert _fed([1.0] * (FEWEST - 1)).at(0.5) is None
    assert _fed([1.0] * FEWEST).at(0.5) is not None


def test_it_reads_the_quantile_asked_for():
    got = _fed(range(1, 101))
    assert got.at(0.5) == 51.0
    assert got.at(0.9) == 91.0
    assert got.at(0.5) < got.at(0.9)


def test_distance_is_taken_by_magnitude():
    """Both quantities arrive signed by which side of the level they were on,
    which is a fact about the approach rather than about how far price went."""
    assert _fed([-2.0] * FEWEST).at(0.5) == 2.0


def test_zero_is_not_a_distance():
    r = _fed([0.0] * FEWEST)
    assert r.at(0.5) is None


def test_the_window_forgets():
    """A quantile of the recent past, not of a year of touches."""
    r = _fed([1.0] * WINDOW + [9.0] * WINDOW)
    assert r.at(0.5) == 9.0


# ------------------------------------------------------------------ the book


def _book(depths, excursions, feed="gold", interval="3m"):
    book = Reaches()
    for d, e in zip(depths, excursions, strict=False):
        book.observe(feed, interval, d, e)
    return book


def test_a_deeper_entry_fills_less_often():
    """The trade-off an entry is, made explicitly rather than by a constant."""
    book = _book([float(i) for i in range(1, 61)], [1.0] * 60)
    assert book.entry_at("gold", "3m", 0.25) < book.entry_at("gold", "3m", 0.75)


def test_the_stop_clears_most_of_what_has_gone_wrong():
    book = _book([1.0] * 60, [float(i) for i in range(1, 61)])
    lenient = book.stop_at("gold", "3m", share=0.5)
    strict = book.stop_at("gold", "3m", share=0.95)
    assert strict > lenient


def test_the_risk_distance_is_added_not_maxed():
    """The level model's risk describes the structure; the excursion quantile
    describes what price has done to trades there. Different evidence about
    the same question, so a stop clearing both is the sum."""
    book = _book([1.0] * 60, [2.0] * 60)
    plain = book.stop_at("gold", "3m")
    with_risk = book.stop_at("gold", "3m", risk_vol=1.5)
    assert with_risk == plain + 1.5


def test_a_negative_risk_cannot_pull_the_stop_in():
    book = _book([1.0] * 60, [2.0] * 60)
    assert book.stop_at("gold", "3m", risk_vol=-5.0) == book.stop_at("gold", "3m")


def test_an_unseen_series_says_nothing():
    """Rather than a number with no observations behind it."""
    book = _book([1.0] * 60, [2.0] * 60)
    assert book.entry_at("brent", "5m") is None
    assert book.stop_at("brent", "5m") is None
