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

#: A call the 1h and 4h already agree with, so the alignment gate is satisfied
#: and each test below exercises the one condition it is about.
UP = {"direction": "up", "feed": "v75", "interval": "15m", "confluence": ["1h", "4h"]}
DOWN = {"direction": "down", "feed": "v75", "interval": "15m", "confluence": ["1h", "4h"]}


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


class TestItRunsBesideThePlainTrade:
    def test_it_runs_beside_cycle_scalp_by_default(self):
        """The two the desk runs, and they do not overlap: `cycle-scalp` enters
        on 1m to 15m and this on 15m to 1h, so only 15m is shared - and there
        the two want opposite things, one a continuation and one a turn against
        it. The journal tells them apart by magic."""
        got = Settings().strategies
        assert "cycle-turn" in got
        assert "cycle-scalp" in got

    def test_it_has_a_magic_slot_so_its_trades_can_be_scored(self):
        """Without one it still trades, stamping a hash with no inverse, and
        every position closes as unattributed - which for a strategy gated on
        its own scored record would be circular as well as broken."""
        from till_infinity.trading.config import DEFAULT_MAGIC, magic_for, strategy_for

        magic = magic_for(DEFAULT_MAGIC, "cycle-turn")
        assert strategy_for(DEFAULT_MAGIC, magic) == "cycle-turn"


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
    def test_it_enters_on_the_middle_timeframes(self, strategy):
        """Fast enough that a stop means something, slow enough that the cycle
        reading on it is not one bar of noise."""
        assert strategy.entries == ("15m", "30m", "1h")

    def test_its_stop_is_wider_than_the_plain_level_trade(self, strategy):
        """Because it belongs to the 1h horizon rather than to the entry bar.
        A 15m call's stop is doubled; a 1h call's is unchanged."""
        assert strategy._horizon_scale("15m", strategy.STOP_HORIZON) > 1.0

    def test_a_call_with_no_direction_is_left_to_the_gate_that_owns_it(self, strategy):
        """`direction` is refused upstream; two refusals for one fault is
        worse than one."""
        payload = {"feed": "v75", "interval": "15m", "confluence": ["1h", "4h"]}
        assert strategy.accept(payload, reading()) is None


class TestAlignment:
    def aligned(self, *, interval="15m", confluence=("1h", "4h")):
        return {
            "direction": "up",
            "feed": "v75",
            "interval": interval,
            "confluence": list(confluence),
        }

    def test_it_needs_both_the_hour_and_the_four_hour(self, strategy):
        assert strategy.accept(self.aligned(), reading()) is None

    def test_one_of_the_two_is_not_enough(self, strategy):
        got = strategy.accept(self.aligned(confluence=("1h",)), reading())
        assert got.gate == "cycle_unaligned"
        assert "4h" in got.detail

    def test_neither_is_refused(self, strategy):
        got = strategy.accept(self.aligned(confluence=()), reading())
        assert got.gate == "cycle_unaligned"

    def test_a_timeframe_cannot_confirm_itself(self, strategy):
        """A 1h entry needs only the 4h, because `anchored` excludes the call's
        own interval and a timeframe agreeing with itself says nothing."""
        got = strategy.accept(self.aligned(interval="1h", confluence=("4h",)), reading())
        assert got is None

    def test_the_daily_is_recorded_and_never_required(self, strategy):
        """Making it mandatory would refuse most of what the 1h/4h pair already
        qualifies, and nothing has measured that it should."""
        without = self.aligned(confluence=("1h", "4h"))
        with_daily = self.aligned(confluence=("1h", "4h", "1d"))
        assert strategy.accept(without, reading()) is None
        assert strategy.accept(with_daily, reading()) is None
        assert not strategy.fully_aligned(without)
        assert strategy.fully_aligned(with_daily)


class TestHorizons:
    def test_a_faster_entry_is_stretched_further(self, strategy):
        """The stop belongs to the 1h horizon and the target to the 4h, so a
        15m call has to reach further for both than a 1h call does."""
        fast = strategy._horizon_scale("15m", strategy.STOP_HORIZON)
        slow = strategy._horizon_scale("1h", strategy.STOP_HORIZON)
        assert fast == pytest.approx(2.0)
        assert slow == pytest.approx(1.0)

    def test_the_target_reaches_further_than_the_stop(self, strategy):
        for tf in ("15m", "30m", "1h"):
            stop = strategy._horizon_scale(tf, strategy.STOP_HORIZON)
            target = strategy._horizon_scale(tf, strategy.TARGET_HORIZON)
            assert target > stop, tf

    def test_it_scales_as_the_square_root_of_time(self, strategy):
        """Not linearly. A diffusive move over T grows as sqrt(T), which is the
        convention `structures/vol` uses everywhere; linear scaling would ask a
        15m entry for a stop four times too wide."""
        assert strategy._horizon_scale("15m", strategy.STOP_HORIZON) == pytest.approx(2.0)
        assert strategy._horizon_scale("30m", strategy.STOP_HORIZON) == pytest.approx(2**0.5)

    def test_it_never_shrinks_a_distance(self, strategy):
        """A 1h entry must not end up with a tighter stop than a 15m entry of
        the same thesis."""
        assert strategy._horizon_scale("4h", strategy.STOP_HORIZON) == 1.0
        assert strategy._horizon_scale("", strategy.STOP_HORIZON) == 1.0

    def test_the_stretch_is_capped(self, strategy):
        """Uncapped, a fast entry aimed at a slow horizon asks for a target no
        market reaches and the reward-to-risk gate waves it through."""
        assert strategy._horizon_scale("1m", 86_400.0) == strategy.MAX_SCALE


class TestExit:
    def test_it_trails_like_ride(self, strategy):
        """The measured best of six exit policies over 31,820 replayed
        touches - 1.0 scored +0.228 against this one's +0.404, 2.0 went
        negative at -0.135."""
        assert strategy.trail_vol == pytest.approx(0.5)


class TestHold:
    def test_it_holds_for_days_not_minutes(self, strategy):
        """Its entry is 15m to 1h and its context is 4h and 1d, so the move it
        bets on takes days. At the scalp ceiling it would be closed by the
        clock at thirty minutes - `research/spending.md` measured that as how
        `snap` loses, ended by the timer rather than by being right or wrong."""
        for tf in strategy.entries:
            assert strategy.hold_for(tf) >= 24 * 3600, tf

    def test_it_asks_for_seventy_two_hours(self, strategy):
        assert strategy.hold_seconds == 72 * 3600

    def test_configuration_can_shorten_it(self, strategy):
        """The strategy asks and the ceiling decides, which is the contract
        `ceiling` exists for - a hold governed by a class body and reachable by
        no deployment is the defect that split these ceilings in the first
        place."""
        from till_infinity.trading import Settings
        from till_infinity.trading.strategies.strategy import STRATEGIES

        tight = Settings()
        tight.max_hold_position = 3_600.0
        assert STRATEGIES["cycle-turn"](settings=tight).hold_for("1h") <= 3_600.0

    def test_it_holds_longer_than_the_scalp_it_sits_beside(self, strategy):
        from till_infinity.trading import Settings
        from till_infinity.trading.strategies.strategy import STRATEGIES

        scalp = STRATEGIES["cycle-scalp"](settings=Settings())
        assert strategy.hold_for("15m") > scalp.hold_for("15m")
