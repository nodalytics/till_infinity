"""`cycle-turn` one tier down, and one condition looser.

The strategy it is named after requires `zma_agrees` - displacement *and*
momentum pointing the same way - which fires on about 1.5% of the calls this
desk publishes and is why it has never traded. Stricter is not better: the
desk's own measurement has the continuous displacement call beating the
agreement flag by 2.5 to 7.8 points at an identical bet count, and the record
both are licensed by scores the continuous call rather than the flag.

So displacement gates and agreement sizes.
"""

from __future__ import annotations

import pytest

from till_infinity.trading import Settings
from till_infinity.trading.models import Side
from till_infinity.trading.strategies.strategy import STRATEGIES

#: A 1m call the 1h and 30m already agree with, so the alignment gate is
#: satisfied and each test exercises the one condition it is about.
UP = {"direction": "up", "feed": "v75", "interval": "1m", "confluence": ["30m", "1h"]}
DOWN = {"direction": "down", "feed": "v75", "interval": "1m", "confluence": ["30m", "1h"]}


def reading(
    *,
    stretched=1.0,
    agrees=None,
    calls=400.0,
    hit=0.60,
    broke=None,
    break_price=99.0,
):
    """A published reading. `stretched` is what gates; `agrees` is what sizes,
    defaulting to confirming. `calls`/`hit` are the **entry bar's** record,
    which is what licenses a scalp."""
    if agrees is None:
        agrees = stretched
    if broke is None:
        broke = stretched or 1.0
    found = {}
    if broke:
        found = {"break_side": float(broke), "break_price": break_price, "break_age": 600.0}
    return {
        **found,
        "level": 100.0,
        "vol_bps": 100.0,
        "zma_stretched": float(stretched),
        "zma_agrees": float(agrees),
        "zma_edge_calls": calls,
        "zma_edge_right": calls * hit,
        "zma_z": -2.0 if stretched > 0 else 2.0,
        "zma_strong": 1.0,
    }


@pytest.fixture
def strategy():
    return STRATEGIES["cycle-turn-scalp"](settings=Settings())


class TestItRunsBesideTheOthers:
    def test_it_is_in_the_default_set_ahead_of_the_scalp(self):
        """All three overlap on the fast timeframes and the turns want the
        opposite of what the scalp wants there. The first taker wins, so the
        turns lead - listed last they would only ever see what the scalp had
        already declined."""
        got = Settings().strategies
        assert got.index("cycle-turn-scalp") < got.index("cycle-scalp")

    def test_it_has_its_own_magic_slot(self):
        """Without one it still trades, stamping a hash with no inverse, and
        every position closes as unattributed - which for a strategy meant to
        earn a record is circular as well as broken."""
        from till_infinity.trading.config import DEFAULT_MAGIC, magic_for, strategy_for

        magic = magic_for(DEFAULT_MAGIC, "cycle-turn-scalp")
        assert strategy_for(DEFAULT_MAGIC, magic) == "cycle-turn-scalp"
        assert magic != magic_for(DEFAULT_MAGIC, "cycle-turn")


class TestDisplacementGates:
    def test_a_stretched_reading_is_taken(self, strategy):
        assert strategy.accept(UP, reading()) is None

    def test_a_reading_inside_its_band_is_refused(self, strategy):
        got = strategy.accept(UP, reading(stretched=0.0))
        assert got.gate == "cycle_flat"

    def test_it_does_not_need_momentum_to_agree(self, strategy):
        """**The whole point of this strategy.** `cycle-turn` refuses here, and
        refusing here is why it has never traded."""
        assert strategy.accept(UP, reading(stretched=1.0, agrees=0.0)) is None

    def test_a_reading_against_the_call_is_refused(self, strategy):
        got = strategy.accept(DOWN, reading(stretched=1.0, broke=1.0))
        assert got.gate == "cycle_against"


class TestAgreementSizes:
    def test_momentum_confirming_gets_full_risk(self, strategy):
        assert strategy.conviction_scale(reading(agrees=1.0), Side.BUY) == 1.0

    def test_displacement_alone_gets_less(self, strategy):
        """The same trade with less behind it, not a different one."""
        got = strategy.conviction_scale(reading(agrees=0.0), Side.BUY)
        assert got == strategy.UNCONFIRMED_RISK
        assert got < 1.0

    def test_momentum_pointing_the_other_way_gets_less(self, strategy):
        assert strategy.conviction_scale(reading(agrees=-1.0), Side.BUY) < 1.0

    def test_it_can_never_enlarge(self, strategy):
        """A multiplier that enlarged would be a way past `max_risk_money` and
        every other cap, through a setting nobody reads as a risk setting."""
        for agrees in (-1.0, 0.0, 1.0):
            for side in (Side.BUY, Side.SELL):
                assert strategy.conviction_scale(reading(agrees=agrees), side) <= 1.0


class TestTheHourIsTheMother:
    def aligned(self, *, interval="1m", confluence=("30m", "1h")):
        return {
            "direction": "up",
            "feed": "v75",
            "interval": interval,
            "confluence": list(confluence),
        }

    def test_the_hour_and_one_other_is_the_agreement(self, strategy):
        assert strategy.accept(self.aligned(), reading()) is None

    def test_the_fifteen_can_be_the_other_one(self, strategy):
        assert strategy.accept(self.aligned(confluence=("15m", "1h")), reading()) is None

    def test_without_the_hour_nothing_else_counts(self, strategy):
        got = strategy.accept(self.aligned(confluence=("15m", "30m")), reading())
        assert got.gate == "cycle_no_mother"
        assert "1h" in got.detail

    def test_the_hour_may_not_agree_alone(self, strategy):
        got = strategy.accept(self.aligned(confluence=("1h",)), reading())
        assert got.gate == "cycle_alone"

    def test_a_fifteen_minute_entry_is_anchored_on_the_thirty_and_the_hour(self, strategy):
        """A timeframe cannot confirm itself, so the 15m drops out of its own
        supporting set."""
        alone = strategy.accept(self.aligned(interval="15m", confluence=("15m", "1h")), reading())
        assert alone.gate == "cycle_alone"
        both = self.aligned(interval="15m", confluence=("30m", "1h"))
        assert strategy.accept(both, reading()) is None


class TestTheBreakAndItsLine:
    def test_a_turn_with_nothing_broken_is_refused(self, strategy):
        assert strategy.accept(UP, reading(broke=0)).gate == "no_break"

    def test_a_break_the_other_way_is_refused(self, strategy):
        assert strategy.accept(UP, reading(stretched=1.0, broke=-1.0)).gate == "break_against"

    def test_a_call_far_from_the_line_is_refused(self, strategy):
        assert strategy.accept(UP, reading(break_price=50.0)).gate == "break_far"

    def test_the_resting_price_is_the_broken_line(self, strategy):
        assert strategy.resting_price(reading(break_price=99.0)) == 99.0


class TestTheEntryBarsOwnRecordLicensesIt:
    def test_an_unproven_feed_is_refused(self, strategy):
        got = strategy.accept(UP, reading(calls=10.0))
        assert got.gate == "cycle_unproven"

    def test_a_feed_where_the_reading_is_a_coin_is_refused(self, strategy):
        assert strategy.accept(UP, reading(hit=0.50)).gate == "cycle_poor"

    def test_it_reads_the_entry_bar_not_the_mother_cycle(self, strategy):
        """**The opposite choice from `cycle-turn`, for the same reason.** That
        strategy is stopped on the hour and targeted at four, so it is licensed
        by the 4h record; a scalp's horizon is the entry bar, so it is licensed
        by the entry bar's. Which is also where the evidence is: 28 of the 1m
        series clear the bar, against none at 4h before a backfill."""
        anchored_only = {**reading(), "zma_edge_calls": 0.0, "zma_edge_right": 0.0}
        anchored_only["zma_anchor_edge_calls"] = 4000.0
        anchored_only["zma_anchor_edge_right"] = 3000.0
        assert strategy.accept(UP, anchored_only).gate == "cycle_unproven"


class TestItIsAScalp:
    def test_it_enters_from_a_minute_to_a_quarter_hour(self, strategy):
        assert strategy.entries == ("1m", "3m", "5m", "15m")

    def test_it_is_held_like_a_scalp(self, strategy):
        """A scalp that aims at a slower horizon is a position trade with a
        scalp's stop."""
        assert strategy.style == "scalp"
        assert strategy.hold_seconds <= 4 * 3600.0


class TestTheClockIsTheOperatorsToSet:
    """A class body could only ever cut the setting, never reach it.

    `hold_for` takes the *smaller* of `hold_seconds` and the configured scalp
    ceiling. This strategy named fifteen minutes, so when `TRADING_MAX_HOLD_S`
    was raised to 2,700s it went on closing at 900 - while `cycle-scalp`,
    which names no hold, took the full forty-five. The setting looked applied
    and was not.
    """

    def test_it_holds_for_as_long_as_the_scalp_ceiling_allows(self):
        settings = Settings(max_hold=2_700.0)
        strategy = STRATEGIES["cycle-turn-scalp"](settings=settings)
        assert strategy.hold_for("1m") == 2_700.0

    def test_it_tracks_the_ceiling_rather_than_a_number_of_its_own(self):
        """Lower the setting and it follows - which is the whole point."""
        strategy = STRATEGIES["cycle-turn-scalp"](settings=Settings(max_hold=600.0))
        assert strategy.hold_for("1m") == 600.0

    def test_it_agrees_with_the_scalp_it_runs_beside(self):
        settings = Settings(max_hold=2_700.0)
        turn = STRATEGIES["cycle-turn-scalp"](settings=settings)
        scalp = STRATEGIES["cycle-scalp"](settings=settings)
        assert turn.hold_for("1m") == scalp.hold_for("1m"), "two scalps, one configured ceiling"
