"""What a forecast has to beat before it means anything.

Computed and written down **before** the comparison, because a floor chosen after
seeing the result is not a floor. Half the bid/ask spread as a fraction of mark is
what a round trip costs; a forecast that beats `mark_iv` by less than that is a
forecast that loses money being right.
"""

from __future__ import annotations

import math

from research.harness.implied_floor import cost_fraction, floor


def test_half_the_spread_over_mark():
    # bid 0.0120, ask 0.0126 -> half-spread 0.0003, mark 0.0123
    got = cost_fraction(0.0120, 0.0126, 0.0123)
    assert got is not None
    assert math.isclose(got, 0.0003 / 0.0123, rel_tol=1e-9)


def test_a_zero_mark_has_no_cost_fraction():
    """Dividing by it would report an infinite or absurd cost as a number."""
    assert cost_fraction(0.0, 0.0, 0.0) is None


def test_a_crossed_book_is_refused():
    """ask below bid is bad data, not a negative cost."""
    assert cost_fraction(0.0126, 0.0120, 0.0123) is None


def test_a_non_finite_input_is_refused():
    """A CSV round trip turns a missing value into nan, not into an exception."""
    assert cost_fraction(float("nan"), 0.0126, 0.0123) is None
    assert cost_fraction(0.0120, float("inf"), 0.0123) is None


def test_a_touching_book_costs_nothing():
    """bid == ask is a zero spread, which is a real answer and not an error."""
    assert cost_fraction(0.0123, 0.0123, 0.0123) == 0.0


def test_an_empty_surface_does_not_divide_by_zero():
    """A delisted or brand-new currency returns nothing, which is an answer."""
    got = floor([])
    assert got["n"] == 0
    assert math.isnan(got["median_cost"])


def test_the_floor_reports_a_median_and_a_count():
    rows = [
        {"bid_price": 0.010, "ask_price": 0.012, "mark_price": 0.011},
        {"bid_price": 0.020, "ask_price": 0.024, "mark_price": 0.022},
        {"bid_price": None, "ask_price": None, "mark_price": 0.030},
    ]
    got = floor(rows)
    assert got["n"] == 2
    assert got["median_cost"] > 0


def test_volatility_points_use_mark_iv_and_not_a_bare_hundred():
    """The key has to implement its own stated derivation.

    It claimed to convert a cost fraction into the volatility points `mark_iv` is
    quoted in, using `points = c * mark_iv`, and then returned `c * 100` - which
    never reads `mark_iv` at all and was 1.9x off on real data. Worse, `main` printed
    the same digits twice under two different labels, once as a percentage of premium
    and once as volatility points, which is the tell.
    """
    rows = [
        {"bid_price": 0.010, "ask_price": 0.012, "mark_price": 0.011, "mark_iv": 50.0},
        {"bid_price": 0.020, "ask_price": 0.024, "mark_price": 0.022, "mark_iv": 50.0},
    ]
    got = floor(rows)
    assert math.isclose(got["iv_points_needed"], got["median_cost"] * 50.0, rel_tol=1e-9)
    # And the two are genuinely different numbers, so the mistake cannot recur silently.
    assert not math.isclose(got["iv_points_needed"], got["median_cost"] * 100.0)


def test_volatility_points_are_nan_without_a_mark_iv():
    """Analysis feeds this by hand, and a column that is absent is not a 100."""
    rows = [{"bid_price": 0.010, "ask_price": 0.012, "mark_price": 0.011}]
    got = floor(rows)
    assert got["n"] == 1
    assert math.isnan(got["iv_points_needed"])


def test_the_cost_percentage_is_reported_under_its_own_name():
    """`main` printed one number as two units; each now has a key of its own."""
    rows = [{"bid_price": 0.010, "ask_price": 0.012, "mark_price": 0.011, "mark_iv": 50.0}]
    got = floor(rows)
    assert math.isclose(got["cost_percent_of_premium"], got["median_cost"] * 100.0)


def test_the_floor_reads_strings_because_the_store_is_csv():
    """Every recorded row arrives from `csv.DictReader`, so every value is a string."""
    rows = [{"bid_price": "0.010", "ask_price": "0.012", "mark_price": "0.011"}]
    got = floor(rows)
    assert got["n"] == 1
    assert math.isclose(got["median_cost"], 0.001 / 0.011, rel_tol=1e-9)


def test_an_empty_string_is_skipped_not_crashed_on():
    """A dropped column round-trips through CSV as '' rather than as None."""
    rows = [{"bid_price": "", "ask_price": "", "mark_price": "0.011"}]
    assert floor(rows)["n"] == 0


def test_the_p90_is_at_least_the_median():
    rows = [
        {"bid_price": 0.0100, "ask_price": 0.0102, "mark_price": 0.0101},
        {"bid_price": 0.0100, "ask_price": 0.0110, "mark_price": 0.0105},
        {"bid_price": 0.0100, "ask_price": 0.0200, "mark_price": 0.0150},
    ]
    got = floor(rows)
    assert got["p90_cost"] >= got["median_cost"]
