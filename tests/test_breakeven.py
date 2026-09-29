"""The break-even study's arithmetic, because a risk decision rests on it.

`research/docs/breakeven.md` argues from three numbers: how many trades a trigger
arms, what an armed loser saves, and how much armed-winner R is exposed to being
scratched. Each is a few lines of code, and each is the kind of few lines that is
wrong by a sign or an off-by-one and still produces a plausible table.
"""

from __future__ import annotations

import math

from research.harness.breakeven import (
    MAX_CREDIBLE_BEST_R,
    applied,
    payoff,
    usable,
)


def trade(best: float, final: float, adverse: float = 0.0) -> dict:
    return {"best_r": best, "r_multiple": final, "adverse_r": adverse}


# ------------------------------------------------------------------- usable


def test_an_implausible_excursion_is_discarded():
    """`best_r` reaches 1,771 on the record, from a malformed target.

    A trade is **armed** on `best_r`, so an inflated value arms one that never
    qualified and inflates the gain it is credited with.
    """
    assert usable(trade(1.5, 0.5))
    assert not usable(trade(MAX_CREDIBLE_BEST_R + 0.01, 0.5))
    assert not usable(trade(1771.0, -1.0))


def test_a_missing_or_unparseable_field_is_discarded():
    assert not usable({"r_multiple": 0.5})
    assert not usable({"best_r": 1.0})
    assert not usable(trade(float("nan"), 0.5))
    assert not usable(trade(1.0, float("inf")))


def test_the_boundary_itself_is_kept():
    """Exactly at the limit is a credible trade, not a broken input."""
    assert usable(trade(MAX_CREDIBLE_BEST_R, 0.5))


# ------------------------------------------------------------------- payoff


def test_the_payoff_ratio_is_mean_win_over_mean_loss():
    rate, mean_win, mean_loss, ratio = payoff([2.0, 2.0, -1.0, -1.0])
    assert rate == 0.5
    assert mean_win == 2.0
    assert mean_loss == 1.0
    assert ratio == 2.0


def test_a_book_with_no_losses_has_no_payoff_ratio():
    """Dividing by it would report an infinite edge as a number."""
    assert all(math.isnan(x) for x in payoff([1.0, 2.0]))
    assert all(math.isnan(x) for x in payoff([-1.0, -2.0]))


def test_scratches_do_not_count_as_wins():
    """A break-even exit is 0R, and counting it as a win would flatter the rate."""
    rate, _w, _l, _r = payoff([1.0, 0.0, 0.0, -1.0])
    assert rate == 0.25


# ------------------------------------------------------------------ applied


def test_only_trades_that_reached_the_trigger_are_armed():
    rows = [trade(0.4, -1.0), trade(0.6, -1.0)]
    got = applied(rows, 0.5)
    assert got["losers"] == 1
    assert got["saved"] == 1.0
    # The unarmed loser keeps its own result.
    assert sorted(got["after"]) == [-1.0, 0.0]


def test_an_armed_loser_exits_at_zero_and_the_gain_is_its_whole_loss():
    got = applied([trade(1.2, -0.8)], 1.0)
    assert got["after"] == [0.0]
    assert got["saved"] == 0.8


def test_a_winner_that_never_went_below_entry_is_not_exposed():
    """It cannot be scratched by a stop sitting at entry, whatever the ordering."""
    got = applied([trade(1.5, 1.2, adverse=0.0)], 1.0)
    assert got["winners"] == 1
    assert got["exposed"] == 0
    assert got["exposed_cost"] == 0.0
    assert got["safe_win"] == 1.2


def test_a_winner_that_dipped_below_entry_is_exposed():
    got = applied([trade(1.5, 1.2, adverse=0.3)], 1.0)
    assert got["exposed"] == 1
    assert got["exposed_cost"] == 1.2
    assert got["safe_win"] == 0.0


def test_an_armed_winner_keeps_its_result_in_the_optimistic_case():
    """`after` is the best case for the change; the cost is reported separately."""
    got = applied([trade(1.5, 1.2, adverse=0.3)], 1.0)
    assert got["after"] == [1.2]


def test_a_trade_with_no_adverse_field_is_treated_as_untouchable():
    """Absent is not evidence of a dip, and inventing one would overstate the cost."""
    got = applied([{"best_r": 1.5, "r_multiple": 1.2}], 1.0)
    assert got["exposed"] == 0


def test_the_gain_and_the_exposure_are_counted_over_different_trades():
    """One armed loser and one armed exposed winner, kept apart."""
    got = applied([trade(1.2, -0.8), trade(1.5, 1.2, adverse=0.3)], 1.0)
    assert got["losers"] == 1
    assert got["winners"] == 1
    assert got["saved"] == 0.8
    assert got["exposed_cost"] == 1.2
    # The worst case the doc quotes: the optimistic total, less every exposed winner.
    assert math.isclose(sum(got["after"]) - got["exposed_cost"], 0.0, abs_tol=1e-9)
