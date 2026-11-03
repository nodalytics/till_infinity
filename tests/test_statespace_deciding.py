"""The statespace strategy: that the two sides really can differ, end to end.

Statespace emits a reading and its own strategy acts on it, with asymmetric
entries and exits. The composition is `strategies/surprise.py`'s - a decision
mixin with no base, composed with an entry that supplies the Nautilus
`Strategy` - so what has to be asserted is that the shape holds and that the
asymmetry is real rather than decorative:

* the mixin has no base of its own, so it can be paired with any entry;
* a leaf refuses the other side's proposals in `wants`, which is what lets a
  long leaf and a short leaf run on one feed under different `strategy_id`s;
* the per-side exit policy reaches the `Intent`, where `exits.Exits` reads it.

**The numbers this file asserts differ by side are the test's own**, not the
shipped ones. `deciding.LongProfile` and `ShortProfile` carry identical numbers
because nothing here has measured a long/short asymmetry in a dispersion
trigger, and inventing one would be an unmeasured rule riding on a measured
one's reputation. The capability is what is tested.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from nautilus_trader.trading.strategy import Strategy

from till_infinity.domain.models import Intent, Refusal, Side, SymbolSpec, Tick
from till_infinity.statespace import deciding
from till_infinity.strategies.entries import ArrivalEntry, EdgeEntry, RestingEntry


#: A proposal in the signal contract `statespace.proposing` publishes.
def proposal(direction: int = 1, *, surprise: float = 4.0, feed: str = "eurusd") -> dict:
    return {
        "feed": feed,
        "interval": "1h",
        "shape": "statespace",
        "direction": direction,
        "features": {
            "surprise": surprise,
            "vol_bps": 8.0,
            "stop_vol": 2.0,
            "target_r": 2.0,
            "volume": 0.1,
        },
    }


class Host:
    """The two things `Desk` supplies that the mixin reads. Nothing else."""

    spread: ClassVar[float] = 0.00002

    def _tick(self) -> Tick | None:
        mid = 1.10
        return Tick(symbol="EURUSD", bid=mid - self.spread / 2, ask=mid + self.spread / 2)

    def _spec(self) -> SymbolSpec | None:
        return SymbolSpec(symbol="EURUSD")


class Quiet(Host):
    """A host with no quote, for the gate that needs one."""

    def _tick(self) -> Tick | None:
        return None


class Wide(Host):
    """A host whose round trip eats the target. The gate that decides this."""

    spread: ClassVar[float] = 0.01


class LongDecision(deciding.LongSide, Host):
    pass


class ShortDecision(deciding.ShortSide, Host):
    pass


class TestTheCompositionShape:
    """`Surprise.__mro__ == (Surprise, object)` is the pattern being matched."""

    def test_the_decision_is_a_mixin_with_no_base_of_its_own(self) -> None:
        """A decision that carried a base would fix the pairing in the wrong
        direction - the old shape was a `Strategy` ABC a runner consulted, with
        the decision, the parameters and the helpers in one hierarchy and the
        mechanism chosen elsewhere."""
        assert deciding.OneSided.__mro__ == (deciding.OneSided, object)
        assert not issubclass(deciding.OneSided, Strategy)

    def test_each_side_composes_with_each_entry_into_a_nautilus_strategy(self) -> None:
        """The point of the mixin: one decision across three mechanisms is
        three classes and no flags, and *which* mechanism took a trade is a
        fact Nautilus records on the `strategy_id` rather than something we
        remember to set."""
        made = []
        for side in (deciding.LongSide, deciding.ShortSide):
            for entry in (EdgeEntry, RestingEntry, ArrivalEntry):
                leaf = type(f"{side.__name__}{entry.__name__}", (side, entry), {})
                assert issubclass(leaf, Strategy)
                assert leaf.profile is side.profile
                made.append(leaf)
        assert len(made) == 6

    def test_the_two_sides_can_take_different_mechanisms(self) -> None:
        """**The asymmetry, at the level that matters.** The long side and the
        short side need not use the same mechanism, and in this pattern that is
        two leaves - because a leaf *is* a `Strategy` and a strategy has one
        `place`. A side flag inside one class would have produced one
        `strategy_id` across both mechanisms."""

        class LongEdge(deciding.LongSide, EdgeEntry):
            pass

        class ShortResting(deciding.ShortSide, RestingEntry):
            pass

        assert LongEdge.place is not ShortResting.place
        assert LongEdge.profile.side is Side.BUY
        assert ShortResting.profile.side is Side.SELL


class TestWantsRefusesTheOtherSide:
    def test_a_long_leaf_declines_a_short_proposal_before_deciding(self) -> None:
        """Checked in `wants` rather than in `decide`, so the other side's
        proposals cost nothing and are not counted as refusals - they were
        never this leaf's to decline. That is what lets both leaves run on one
        feed without either polluting the other's gate tally."""
        leaf = LongDecision()
        assert leaf.wants(proposal(direction=1))
        assert not leaf.wants(proposal(direction=-1))

    def test_a_short_leaf_is_the_mirror(self) -> None:
        leaf = ShortDecision()
        assert leaf.wants(proposal(direction=-1))
        assert not leaf.wants(proposal(direction=1))

    def test_a_doji_belongs_to_neither_side(self) -> None:
        """`proposing.direction_of` gives 0 for a bar whose open and close
        agree: it expressed no direction, and turning that into a trade would
        invent a conviction nobody had."""
        assert not LongDecision().wants(proposal(direction=0))
        assert not ShortDecision().wants(proposal(direction=0))

    def test_an_unset_profile_takes_no_side_at_all(self) -> None:
        """`SideProfile.side` is `None` on the base, so a leaf that forgot to
        name a side refuses everything rather than taking both."""

        class Unset(deciding.OneSided, Host):
            pass

        assert not Unset().wants(proposal(direction=1))
        got = Unset().decide(proposal(direction=1))
        assert isinstance(got, Refusal)
        assert got.gate == "side"

    def test_a_feed_outside_the_profile_is_declined(self) -> None:
        """`TRADING_SYMBOLS` is global, so naming a strategy would otherwise
        put it on every instrument the desk trades."""
        assert not LongDecision().wants(proposal(feed="dogecoin"))


class TestTheGeometryAndTheGates:
    def test_a_long_intent_buys_the_ask_with_its_stop_below(self) -> None:
        """Buying lifts the ask and selling hits the bid - never the mid.
        Sizing a scalp off the mid understates the stop distance by half the
        spread on both sides."""
        got = LongDecision().decide(proposal(direction=1))
        assert isinstance(got, Intent)
        assert got.side is Side.BUY
        assert got.entry == pytest.approx(1.10 + Host.spread / 2)
        assert got.stop < got.entry < got.target
        assert got.volume == pytest.approx(0.1), "the size came from the sizer, not from here"

    def test_a_short_intent_sells_the_bid_with_its_stop_above(self) -> None:
        got = ShortDecision().decide(proposal(direction=-1))
        assert isinstance(got, Intent)
        assert got.side is Side.SELL
        assert got.entry == pytest.approx(1.10 - Host.spread / 2)
        assert got.target < got.entry < got.stop

    def test_the_stop_distance_is_the_folded_log_variance_and_not_a_spread_column(self) -> None:
        """`vol_bps` is `exp(value / 2)` in basis points off the fold. Nothing
        reads the spread *column*, whose conversion is a measured 476% error -
        EURUSD read a 476% round trip and the error reorders instruments by
        cost."""
        got = LongDecision().decide(proposal())
        assert isinstance(got, Intent)
        unit = 8.0 / 1e4 * got.entry
        assert got.entry - got.stop == pytest.approx(2.0 * unit)
        assert got.target - got.entry == pytest.approx(4.0 * unit)
        assert got.stop_vol == pytest.approx(2.0)

    def test_a_reading_below_the_trigger_is_refused_under_its_own_gate(self) -> None:
        """One gate per refusal, each naming itself, so declines can be counted
        per gate over a week without parsing prose."""
        got = LongDecision().decide(proposal(surprise=1.0))
        assert isinstance(got, Refusal)
        assert got.gate == "surprise"

    def test_a_round_trip_that_eats_the_target_is_refused(self) -> None:
        """**The gate that decides this strategy**, before the geometry and
        before sizing. On an exotic a round trip is 0.40 to 0.97 of a whole bar
        range, which ends most ideas before they are measured."""

        class WideLong(deciding.LongSide, Wide):
            pass

        got = WideLong().decide(proposal())
        assert isinstance(got, Refusal)
        assert got.gate == "cost"

    def test_a_missing_quote_is_refused_rather_than_guessed(self) -> None:
        class QuietLong(deciding.LongSide, Quiet):
            pass

        got = QuietLong().decide(proposal())
        assert isinstance(got, Refusal)
        assert got.gate == "no-quote"

    def test_an_unparseable_feature_is_a_refusal_and_not_an_exception(self) -> None:
        """A feature that is absent and one that is unparseable are the same
        thing to a threshold, and neither is a reason to raise on a live feed."""
        payload = proposal()
        payload["features"]["vol_bps"] = "wide"
        got = LongDecision().decide(payload)
        assert isinstance(got, Refusal)
        assert got.gate == "volatility"


class TestTheExitsCanDifferPerSide:
    """`Intent` already carries the per-trade exit policy, so no change in
    `strategies/` is needed for an asymmetric exit."""

    def test_the_intent_carries_every_field_the_exits_read_off_it(self) -> None:
        """`exits.Exits` and `manage` read `break_even_at`, `trail_vol`,
        `trail_levels`, `hold` and `stale_exempt` from the intent rather than
        from the strategy - the field comments say why: by the time a stop is
        being moved, the strategy that wanted the trade is a name in a log
        line. So a per-side policy is a per-side set of numbers here."""

        class Patient(deciding.SideProfile):
            side: ClassVar[Side | None] = Side.BUY
            name: ClassVar[str] = "test-patient"
            break_even_at: ClassVar[float] = 1.5
            trail_vol: ClassVar[float] = 3.0
            trail_levels: ClassVar[bool] = True
            hold: ClassVar[float] = 7_200.0
            stale_exempt: ClassVar[bool] = True

        class PatientLong(deciding.OneSided, Host):
            profile: ClassVar[type[deciding.SideProfile]] = Patient

        got = PatientLong().decide(proposal(direction=1))
        assert isinstance(got, Intent)
        assert got.break_even_at == pytest.approx(1.5)
        assert got.trail_vol == pytest.approx(3.0)
        assert got.trail_levels is True
        assert got.hold == pytest.approx(7_200.0)
        assert got.stale_exempt is True

    def test_two_sides_with_different_profiles_produce_different_geometry(self) -> None:
        """The asymmetry proved rather than described: a wider stop, a nearer
        target, a different trail and a different risk share on one side than
        the other, through one code path."""

        class Patient(deciding.SideProfile):
            side: ClassVar[Side | None] = Side.BUY
            name: ClassVar[str] = "test-patient"
            stop_vol: ClassVar[float] = 4.0
            target_r: ClassVar[float] = 3.0
            trail_vol: ClassVar[float] = 3.0
            risk_share: ClassVar[float] = 1.0

        class Quick(deciding.SideProfile):
            side: ClassVar[Side | None] = Side.SELL
            name: ClassVar[str] = "test-quick"
            stop_vol: ClassVar[float] = 1.0
            target_r: ClassVar[float] = 1.2
            trail_vol: ClassVar[float] = 0.0
            hold: ClassVar[float] = 900.0
            risk_share: ClassVar[float] = 0.5

        class PatientLong(deciding.OneSided, Host):
            profile: ClassVar[type[deciding.SideProfile]] = Patient

        class QuickShort(deciding.OneSided, Host):
            profile: ClassVar[type[deciding.SideProfile]] = Quick

        # The proposal names no `stop_vol` or `target_r`, so each side falls
        # back to its own. A proposal that names them overrides both equally,
        # which is the producer's right and is tested above.
        bare = proposal(direction=1)
        bare["features"].pop("stop_vol")
        bare["features"].pop("target_r")
        long_got = PatientLong().decide(bare)
        short_bare = proposal(direction=-1)
        short_bare["features"].pop("stop_vol")
        short_bare["features"].pop("target_r")
        short_got = QuickShort().decide(short_bare)

        assert isinstance(long_got, Intent)
        assert isinstance(short_got, Intent)
        assert long_got.stop_vol == pytest.approx(4.0)
        assert short_got.stop_vol == pytest.approx(1.0)
        long_risk = long_got.entry - long_got.stop
        short_risk = short_got.stop - short_got.entry
        assert long_risk > 3.0 * short_risk, f"{long_risk} against {short_risk}"
        assert long_got.trail_vol != short_got.trail_vol
        assert long_got.hold != short_got.hold
        assert long_got.features["risk_share"] == pytest.approx(1.0)
        assert short_got.features["risk_share"] == pytest.approx(0.5)

    def test_the_shipped_profiles_are_deliberately_identical(self) -> None:
        """**The asymmetry is a capability, not a claim.** Nothing on this desk
        has measured a long/short asymmetry in a dispersion trigger, and
        `strategies/surprise.py` states the rule this follows: a rule invented
        here would be an unmeasured one riding on a measured one's reputation.

        This test fails the day somebody sets one side's number without a
        measurement, which is the point of it.
        """
        shared = (
            "least_surprise",
            "cost_share",
            "stop_vol",
            "target_r",
            "break_even_at",
            "trail_vol",
            "trail_levels",
            "hold",
            "stale_exempt",
            "risk_share",
            "feeds",
        )
        for field in shared:
            assert getattr(deciding.LongProfile, field) == getattr(deciding.ShortProfile, field), (
                f"{field} differs by side with no measurement behind it"
            )
        assert deciding.LongProfile.side is not deciding.ShortProfile.side
        assert deciding.LongProfile.name != deciding.ShortProfile.name


class TestItClaimsNoDirection:
    def test_the_side_comes_from_the_proposal_and_not_from_the_reading(self) -> None:
        """This service folds **log variance**, so a side derived from its own
        reading would be the side of a volatility move published as a price
        claim - the category error already corrected twice in this package,
        where `side` became `variance_side` and the alert kind `break` became
        `surprise`.

        `proposing.py` takes the side from the triggering bar's own body, which
        is continuation - the only directional thing measured to work here, at
        +0.1436R +/- 0.0485 over 905 trades.
        """
        up = LongDecision().decide(proposal(direction=1))
        assert isinstance(up, Intent)
        assert up.side is Side.BUY
        down = ShortDecision().decide(proposal(direction=-1))
        assert isinstance(down, Intent)
        assert down.side is Side.SELL
        # The same reading, the same magnitude, opposite sides: the decision
        # reads the proposal's `direction` and never the surprise's sign.
        #
        # `rel=1e-3` and not exact, and the residual is not noise: the
        # volatility unit is `vol_bps / 1e4 * entry`, and the two sides enter
        # at the ask and the bid, so the risk differs by the spread's share of
        # the price - 1.8e-5 relative here. That is the only asymmetry the
        # shipped profiles have, and it comes from the quote.
        assert abs(up.entry - up.stop) == pytest.approx(abs(down.stop - down.entry), rel=1e-3)

    def test_a_textual_direction_is_read_the_same_way(self) -> None:
        """The signal contract carries both shapes across producers -
        `structures` sends "up"/"down" and `proposing` sends +1/-1 - and
        `Side.from_direction` is what reads the first."""
        payload = proposal()
        payload["direction"] = "up"
        assert LongDecision().wants(payload)
        payload["direction"] = "down"
        assert ShortDecision().wants(payload)
        payload["direction"] = "sideways"
        assert not LongDecision().wants(payload)
        assert not ShortDecision().wants(payload)
