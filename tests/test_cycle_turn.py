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

import math

import pytest

from till_infinity.trading import Settings
from till_infinity.trading.strategies.strategy import STRATEGIES

#: A call the 1h and 4h already agree with, so the alignment gate is satisfied
#: and each test below exercises the one condition it is about.
UP = {"direction": "up", "feed": "v75", "interval": "15m", "confluence": ["1h", "4h"]}
DOWN = {"direction": "down", "feed": "v75", "interval": "15m", "confluence": ["1h", "4h"]}


def reading(
    *,
    agrees=1.0,
    calls=400.0,
    hit=0.60,
    entry_calls=400.0,
    entry_hit=0.60,
    broke=None,
    break_price=99.0,
):
    """A published reading. `calls`/`hit` are the **4h** record, which is what
    licenses the trade; `entry_calls`/`entry_hit` are the entry bar's own, which
    deliberately does not. `broke` is the side the last change of character
    turned, defaulting to agreeing with the cycle - the ordinary case, so each
    test below exercises the one condition it is about."""
    found = {}
    if broke is None:
        broke = agrees or 1.0
    if broke:
        found = {"break_side": float(broke), "break_price": break_price, "break_age": 600.0}
    return {
        **found,
        "zma_agrees": agrees,
        "zma_edge_calls": entry_calls,
        "zma_edge_right": entry_calls * entry_hit,
        "zma_anchor_edge_calls": calls,
        "zma_anchor_edge_right": calls * hit,
        "zma_z": -2.0 if agrees > 0 else 2.0,
        "zma_strong": 1.0,
    }


@pytest.fixture
def strategy():
    return STRATEGIES["cycle-turn"](settings=Settings())


class TestItRunsBesideThePlainTrade:
    def test_it_runs_beside_cycle_scalp_by_default(self):
        """The two the desk runs. **They overlap on every fast timeframe**, and
        they want opposite things there - one a continuation, one a turn
        against it - so which of them trades a shared call is decided by the
        order in `TRADING_STRATEGIES`, where the first taker wins. The journal
        tells their trades apart by magic."""
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
        assert "10 scored 4h calls" in got.detail

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

    def test_the_bar_is_the_one_configuration_sets(self, strategy):
        """The same two settings the veto reads, so nobody has to maintain two
        ideas of what "earned a say" means - applied to the record of this
        trade's own horizon rather than to the veto's."""
        settings = strategy.settings
        assert settings.zma_min_calls > 0
        assert settings.zma_min_accuracy > 0.5
        just_under = reading(hit=settings.zma_min_accuracy)
        assert strategy.accept(UP, just_under).gate == "cycle_poor"

    def test_the_entry_bar_s_record_does_not_license_the_trade(self, strategy):
        """**A minute of evidence cannot license a three-day position.**

        `zma_edge_calls` on a 1m series counts one-minute-ahead calls, and the
        1m series are where the record looks best - 0.83 on usdcnh, 0.82 on
        eurgbp. This trade is stopped on the hour and targeted at four hours,
        so that record is not evidence about it however much it reads like
        permission. The faster the entry the louder the mistake, which is why
        it is refused here rather than sized down.
        """
        perfect_minute = reading(calls=0.0, entry_calls=4000.0, entry_hit=0.83)
        got = strategy.accept(UP, perfect_minute)
        assert got.gate == "cycle_unproven"
        assert "4h" in got.detail

    def test_a_feed_with_no_anchor_record_at_all_is_refused(self, strategy):
        """The absence of the number is the absence of the evidence. A 4h
        series that has not scored anything yet trades nothing, which is what
        every feed looks like on the day this ships."""
        bare = {
            "zma_agrees": 1.0,
            "zma_z": -2.0,
            "zma_strong": 1.0,
            "break_side": 1.0,
            "break_price": 99.0,
        }
        assert strategy.accept(UP, bare).gate == "cycle_unproven"


class TestTheBreakComesFirst:
    """A change point with no broken structure behind it is a turn with nothing
    under it. The order is the claim: a run of higher lows fails, and *then* the
    cycle rolls over."""

    def test_a_turn_with_nothing_broken_is_refused(self):
        strategy = STRATEGIES["cycle-turn"](settings=Settings())
        got = strategy.accept(UP, reading(broke=0))
        assert got.gate == "no_break"

    def test_a_break_the_other_way_is_refused(self, strategy):
        """A market that just broke *up* is not the one to sell a stretched
        reading into - the structure and the cycle are telling opposite
        stories, and this trades the one where they agree."""
        got = strategy.accept(DOWN, reading(agrees=-1.0, broke=1.0))
        assert got.gate == "break_against"
        assert "up" in got.detail

    def test_the_agreeing_break_is_taken(self, strategy):
        assert strategy.accept(DOWN, reading(agrees=-1.0, broke=-1.0)) is None

    def test_a_break_with_no_line_cannot_be_entered(self, strategy):
        """The line is the whole point of it: support that failed is tested as
        resistance when price comes back, and without the price there is
        nowhere to put the entry."""
        got = strategy.accept(UP, reading(break_price=0.0))
        assert got.gate == "break_priceless"


class TestGeometry:
    def test_it_enters_anywhere_from_a_minute_to_an_hour(self, strategy):
        """The entry timeframe decides when the trade is noticed, not what it
        is: all of them are stopped on the 1h horizon and targeted on the 4h.
        What keeps a fast entry from being one bar of noise is the 1h/4h
        agreement it still has to carry, not the size of the bar."""
        assert strategy.entries == ("1m", "3m", "5m", "15m", "30m", "1h")

    def test_no_declared_entry_is_capped(self, strategy):
        """**The cap must not bind on a timeframe this actually trades.**

        `MAX_SCALE` is there for a horizon far enough past the entry that no
        market reaches it. When it binds inside the declared range the damage
        is silent and uneven: at 4.0 a 1m entry wanted 7.7 and 15.5 and got 4
        and 4, which does not tighten the trade - it flattens the ratio between
        stop and target, so the fast entries alone carry half the
        reward-to-risk of the slow ones while claiming the same design.

        Fails if a faster entry or a longer horizon is added without revisiting
        the cap, which is the only reason it is written this way.
        """
        from till_infinity.structures.levels import SECONDS

        for interval in strategy.entries:
            for horizon in (strategy.STOP_HORIZON, strategy.TARGET_HORIZON):
                want = math.sqrt(horizon / SECONDS[interval])
                got = strategy._horizon_scale(interval, horizon)
                assert got == pytest.approx(max(want, 1.0)), (
                    f"{interval} at {horizon:.0f}s wanted {want:.2f} and was capped to {got:.2f}"
                )

    def test_every_entry_aims_at_the_same_two_distances(self, strategy):
        """Stop on the 1h horizon and target on the 4h means the target is
        twice the stop *whatever* bar the call arrived on - `sqrt(4)`. If that
        ratio moves with the entry timeframe the timeframes are not comparable
        and neither are their records."""
        for interval in strategy.entries:
            stop = strategy._horizon_scale(interval, strategy.STOP_HORIZON)
            target = strategy._horizon_scale(interval, strategy.TARGET_HORIZON)
            assert target / stop == pytest.approx(2.0)

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

    def test_the_mother_and_one_other_is_the_agreement(self, strategy):
        assert strategy.accept(self.aligned(confluence=("1h", "4h")), reading()) is None

    def test_the_daily_can_be_the_other_one(self, strategy):
        """1d is an anchor now, not a note in the margin: it stands in for the
        1h when the 1h has nothing to say."""
        assert strategy.accept(self.aligned(confluence=("4h", "1d")), reading()) is None

    def test_without_the_mother_nothing_else_counts(self, strategy):
        """**The one that ends it.** A 1h and a 1d agreeing with each other
        while the 4h does not are two timeframes agreeing about something the
        cycle they sit inside has already turned away from."""
        got = strategy.accept(self.aligned(confluence=("1h", "1d")), reading())
        assert got.gate == "cycle_no_mother"
        assert "4h" in got.detail

    def test_the_mother_may_not_agree_alone(self, strategy):
        """One reading is not an agreement, however senior the timeframe."""
        got = strategy.accept(self.aligned(confluence=("4h",)), reading())
        assert got.gate == "cycle_alone"

    def test_nothing_agreeing_is_refused_as_a_missing_mother(self, strategy):
        got = strategy.accept(self.aligned(confluence=()), reading())
        assert got.gate == "cycle_no_mother"

    def test_a_timeframe_cannot_confirm_itself(self, strategy):
        """`anchored` excludes the call's own interval, so a 1h entry is
        anchored on the 4h and the 1d - the 1h agreeing with itself says
        nothing, and cannot be the one other anchor the 4h needs."""
        alone = strategy.accept(self.aligned(interval="1h", confluence=("4h",)), reading())
        assert alone.gate == "cycle_alone"
        anchored = self.aligned(interval="1h", confluence=("4h", "1d"))
        assert strategy.accept(anchored, reading()) is None

    def test_fully_aligned_means_every_anchor(self, strategy):
        """Gating takes the mother plus one; the record keeps the difference
        between that and all three, which is what a later comparison needs."""
        part = self.aligned(confluence=("1h", "4h"))
        whole = self.aligned(confluence=("1h", "4h", "1d"))
        assert strategy.accept(part, reading()) is None
        assert strategy.accept(whole, reading()) is None
        assert not strategy.fully_aligned(part)
        assert strategy.fully_aligned(whole)


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
