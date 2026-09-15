"""A strategy that opens on the cycle reading, and the record it must earn first.

Every other use of this reading on the desk can only **remove** a trade. This
one opens positions, which is a much stronger claim, and the measurements are
against it: AUC 0.5031 on real outrights, 0.493 to 0.504 on the synthetics, and
a 0.119 to 0.164 hit rate on Boom and Crash where it is an anti-signal with a
known mechanism. The only place it works is a constructed spread this account
cannot hold.

So the condition is not a threshold on the reading. It is a threshold on the
reading's **record on that feed** - the same bar `zma_gate` defers to. On a
family where it is an anti-signal the record never clears and this never trades
it, with nobody maintaining a list of which families those are.
"""

from __future__ import annotations

import pytest

from till_infinity.trading import Settings
from till_infinity.trading.strategies.strategy import STRATEGIES

UP = {"direction": "up", "feed": "v75"}
DOWN = {"direction": "down", "feed": "v75"}


def reading(*, agrees=1.0, calls=400.0, hit=0.60):
    return {
        "zma_agrees": agrees,
        "zma_edge_calls": calls,
        "zma_edge_right": calls * hit,
        "zma_z": -2.0 if agrees > 0 else 2.0,
        "zma_strong": 1.0,
    }


@pytest.fixture
def strategy():
    return STRATEGIES["cycle-turn"](settings=Settings())


class TestItIsOffUntilAskedFor:
    def test_it_is_not_in_the_default_strategy_set(self):
        """A strategy this well evidenced against should be run deliberately."""
        assert "cycle-turn" not in Settings().strategies

    def test_but_it_is_registered_so_it_can_be_named(self):
        assert "cycle-turn" in STRATEGIES


class TestTheReading:
    def test_it_takes_a_call_the_cycle_agrees_with(self, strategy):
        assert strategy.accept(UP, reading(agrees=1.0)) is None

    def test_it_refuses_when_the_cycle_is_quiet(self, strategy):
        """Displacement alone is not a claim - the thresholds are percentiles,
        so something is always extreme."""
        got = strategy.accept(UP, reading(agrees=0.0))
        assert got is not None
        assert got.gate == "cycle_quiet"

    def test_it_refuses_when_the_cycle_points_the_other_way(self, strategy):
        got = strategy.accept(UP, reading(agrees=-1.0))
        assert got is not None
        assert got.gate == "cycle_against"

    def test_it_narrows_rather_than_invents(self, strategy):
        """It only ever takes a call the model already made, on the side the
        call already states - so it cannot open a trade nothing else wanted."""
        assert strategy.accept(DOWN, reading(agrees=-1.0)) is None
        assert strategy.accept(DOWN, reading(agrees=1.0)).gate == "cycle_against"


class TestTheRecordDecides:
    def test_an_unproven_feed_is_refused(self, strategy):
        got = strategy.accept(UP, reading(calls=10.0))
        assert got.gate == "cycle_unproven"
        assert "10 scored calls" in got.detail

    def test_a_feed_where_the_reading_is_a_coin_is_refused(self, strategy):
        got = strategy.accept(UP, reading(hit=0.50))
        assert got.gate == "cycle_poor"

    def test_a_feed_where_the_reading_is_an_anti_signal_is_refused(self, strategy):
        """0.119 is what Boom measured. This must never trade there, and it must
        not need a list of families to know it."""
        got = strategy.accept(UP, reading(hit=0.119))
        assert got.gate == "cycle_poor"
        assert "12%" in got.detail

    def test_a_feed_that_has_earned_it_is_taken(self, strategy):
        assert strategy.accept(UP, reading(calls=400.0, hit=0.60)) is None

    def test_the_bar_is_the_same_one_the_veto_uses(self, strategy):
        """Two places deferring to one record, so they cannot disagree about
        whether a feed has earned a say."""
        settings = strategy.settings
        assert settings.zma_min_calls > 0
        assert settings.zma_min_accuracy > 0.5
        just_under = reading(hit=settings.zma_min_accuracy)
        assert strategy.accept(UP, just_under).gate == "cycle_poor"


class TestGeometry:
    def test_it_stops_tighter_than_the_plain_level_trade(self, strategy):
        """A reversion trade is wrong quickly or not at all: the agreement
        condition is about a turn that has already begun, so a wide stop buys
        nothing but time to be wrong in."""
        plain = STRATEGIES["level-scalp"]
        assert strategy.stop_multiple < plain.stop_multiple

    def test_it_only_runs_where_the_reading_is_computed(self, strategy):
        """`structures/cycles.py` runs 1m as its fast stream, so a call on a
        slower entry would be judged by a reading from bars it does not
        contain."""
        assert "1m" in strategy.entries
        assert "30m" not in strategy.entries

    def test_a_call_with_no_direction_is_left_to_the_gate_that_owns_it(self, strategy):
        assert strategy.accept({"feed": "v75"}, reading()) is None
