"""The turn model's exit, scored against the one the trade actually took.

A counterfactual is usually unfalsifiable because the level is chosen after the
fact. This one is not: `turn_price` is on the signal that opened the position,
so it is fixed before the trade exists, and whether it was reached is read from
the path the service already tracks for `best_r`. What it cannot know is the
fill, so every scored row is an **upper bound** and says so.
"""

from __future__ import annotations

import math

import pytest

from till_infinity.trading import turning as tn
from till_infinity.trading.models import Side


def ride(*, side=Side.BUY, entry=100.0, risk=2.0, suggested=103.0, **kw):
    """`entry` is the fill and `risk` is what the trade was sized for.

    The same two the service supplies, so the fixture cannot drift from the
    caller - and both `ahead` and `best_r` end up on one denominator, which is
    the whole reason the comparison is done in R rather than in prices.
    """
    return tn.TurnExit(feed="v75", side=side, entry=entry, risk=risk, suggested=suggested, **kw)


class TestGeometry:
    def test_ahead_is_measured_in_the_trade_s_own_risk(self):
        assert ride(entry=100.0, risk=2.0, suggested=103.0).ahead == pytest.approx(1.5)

    def test_a_short_measures_the_other_way(self):
        got = ride(side=Side.SELL, entry=100.0, risk=2.0, suggested=97.0)
        assert got.ahead == pytest.approx(1.5)

    def test_a_suggestion_behind_the_entry_is_negative_and_not_scorable(self):
        """The model saying the move is already over is information about the
        model, not an exit."""
        got = ride(suggested=99.0)
        assert got.ahead < 0
        assert not got.scorable

    def test_an_absurd_extrapolation_is_recorded_and_not_scored(self):
        """A linear head on bounded features can extrapolate; a target at forty
        times the risk is a fault, and averaging it in lets one row own the
        comparison."""
        assert not ride(suggested=100.0 + 2.0 * (tn.MAX_R + 5)).scorable

    def test_no_risk_is_not_scorable(self):
        assert not ride(risk=0.0).scorable


class TestReading:
    def test_a_silent_model_suggests_nothing(self):
        """Absent is the common case: the head stays quiet until it has settled
        two hundred turns. A made-up exit scored against a real one is worse
        than no comparison."""
        assert tn.suggestion_from({}, Side.BUY) == 0.0

    def test_a_nonsense_price_suggests_nothing(self):
        for bad in (0.0, -1.0, float("nan"), float("inf"), "103", None):
            assert tn.suggestion_from({"turn_price": bad}, Side.BUY) == 0.0

    def test_it_reads_the_published_price(self):
        assert tn.suggestion_from({"turn_price": 103.5}, Side.BUY) == 103.5

    def test_a_suggestion_pointing_the_other_way_is_refused(self):
        """The model disagreeing with the trade is a refusal to suggest, not an
        exit behind the entry."""
        got = tn.suggestion_from({"turn_price": 103.0, "turn_side": -1.0}, Side.BUY)
        assert got == 0.0

    def test_agreement_is_honoured_on_both_sides(self):
        assert tn.suggestion_from({"turn_price": 103.0, "turn_side": 1.0}, Side.BUY) == 103.0
        assert tn.suggestion_from({"turn_price": 97.0, "turn_side": -1.0}, Side.SELL) == 97.0


class TestScoring:
    def test_a_suggestion_the_path_reached_would_have_banked_it(self):
        got = tn.score(ride(suggested=103.0), best_r=1.75, took_r=0.4)
        assert got.reached
        assert got.suggested_r == pytest.approx(1.5)
        assert got.gained == pytest.approx(1.1)

    def test_a_suggestion_the_path_never_reached_changes_nothing(self):
        """Not reached means the order never triggered, so the trade ended
        however it actually ended - not at a level it never saw."""
        got = tn.score(ride(suggested=103.0), best_r=0.5, took_r=-1.0)
        assert not got.reached
        assert got.suggested_r == pytest.approx(-1.0)
        assert got.gained == pytest.approx(0.0)

    def test_it_can_be_worse_than_what_the_trade_took(self):
        """Exiting early at the suggestion gives up the rest of a winner."""
        got = tn.score(ride(suggested=101.0), best_r=2.5, took_r=2.5)
        assert got.reached
        assert got.gained < 0

    def test_a_short_scores_the_same_way(self):
        got = tn.score(
            ride(side=Side.SELL, entry=100.0, risk=2.0, suggested=97.0),
            best_r=1.75,
            took_r=0.2,
        )
        assert got.reached
        assert got.suggested_r == pytest.approx(1.5)

    def test_an_unscorable_ride_is_neutral_and_says_why(self):
        got = tn.score(ride(suggested=99.0), best_r=2.5, took_r=2.0)
        assert got.suggested_r == got.took
        assert got.reason
        assert not got.reached

    def test_every_row_admits_it_is_an_upper_bound(self):
        assert tn.score(ride(), best_r=2.0, took_r=1.0).optimistic
        assert tn.score(ride(), best_r=2.0, took_r=1.0).to_dict()["optimistic"] is True


class TestTally:
    def test_the_headline_is_r_a_trade(self):
        tally = tn.TurnTally()
        tally.add(tn.score(ride(suggested=103.0), best_r=1.75, took_r=0.5))
        tally.add(tn.score(ride(suggested=103.0), best_r=1.75, took_r=-1.0))
        assert tally.scored == 2
        assert tally.reached == 2
        # 1.5 against 0.5 and 1.5 against -1.0: +1.0 and +2.5, so +1.75 a trade.
        assert tally.gained_per_trade == pytest.approx(1.75)

    def test_unscorable_rides_are_counted_but_not_averaged(self):
        tally = tn.TurnTally()
        tally.add(tn.score(ride(suggested=99.0), best_r=2.5, took_r=2.0))
        assert tally.rides == 1
        assert tally.scored == 0
        assert math.isnan(tally.gained_per_trade)

    def test_nothing_scored_reports_nothing_rather_than_zero(self):
        got = tn.TurnTally().to_dict()
        assert got["gained_r_per_trade"] is None
        assert got["scored"] == 0


class TestReportAggregation:
    """The durable answer lives in the journal, not in a running tally.

    A per-process tally is reset by every restart and by every deploy, and this
    desk deploys several times a day. The report reads the per-close comparison
    back out of closed trades, so the question can be asked of any window and
    survives the thing that answers it being restarted.
    """

    def trade(self, *, suggested, took, scored=True):
        from till_infinity.trading.report import Trade

        return Trade(
            strategy="cycle-scalp",
            feed="v75",
            side="BUY",
            mode="paper",
            profit=0.0,
            risk_money=100.0,
            seconds=60.0,
            reason="target",
            exit_source="broker",
            reward_to_risk=1.0,
            opened=0.0,
            turn_suggested_r=suggested,
            turn_took_r=took,
            turn_scored=scored,
        )

    def test_it_averages_only_the_scored_rows(self):
        from till_infinity.trading.report import compare_turn_exits

        got = compare_turn_exits(
            [
                self.trade(suggested=1.5, took=0.5),
                self.trade(suggested=1.5, took=-1.0),
                self.trade(suggested=0.0, took=0.0, scored=False),
            ]
        )
        assert got.scored == 2
        assert got.gained_r == pytest.approx(1.75)

    def test_a_worse_suggestion_shows_negative(self):
        from till_infinity.trading.report import compare_turn_exits

        got = compare_turn_exits([self.trade(suggested=0.5, took=2.5)])
        assert got.gained_r == pytest.approx(-2.0)

    def test_nothing_scored_is_nan_rather_than_zero(self):
        from till_infinity.trading.report import compare_turn_exits

        got = compare_turn_exits([self.trade(suggested=0.0, took=0.0, scored=False)])
        assert got.scored == 0
        assert math.isnan(got.gained_r)

    def test_the_summary_refuses_to_read_a_thin_sample(self):
        from till_infinity.trading.report import ENOUGH, compare_turn_exits

        got = compare_turn_exits([self.trade(suggested=1.5, took=0.5)])
        assert "too few" in got.summary()
        assert str(ENOUGH) in got.summary()

    def test_the_summary_says_it_is_an_upper_bound(self):
        from till_infinity.trading.report import ENOUGH, compare_turn_exits

        got = compare_turn_exits([self.trade(suggested=1.5, took=0.5) for _ in range(ENOUGH)])
        assert "upper bound" in got.summary()
