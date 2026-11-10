"""The origin zone as a rule: what nominates one, and what each rule trades.

**One hypothesis, two nominators.** `indicators/levels.Origin` records that an
order block, a displacement origin and a supply/demand zone are the same candle
under three names, so `displacement-zones` and `smc-zones` must differ in what
has to have happened for a candle to count - not in what they then trade. These
tests pin that difference, and pin the sign, which is the thing that would
still print if it were backwards.
"""

from __future__ import annotations

import pytest

from till_infinity.indicators.levels import Origin
from till_infinity.strategies import origins
from till_infinity.strategies.crossing import NEEDS_HISTORY, side_of


def origin_of(side: int, *, low: float = 100.0, high: float = 110.0, when: float = 1.0) -> Origin:
    """One origin. `side` is the direction of the leg that left it."""
    return Origin(
        side=side,
        low=low,
        high=high,
        line=(low + high) / 2.0,
        when=when,
        rank=1,
        move=side * 25.0,
        bars=3,
    )


# ------------------------------------------------------------------- the sign


def test_an_up_leg_leaves_a_demand_zone_below_price():
    """**The inversion that would trade every one of these backwards.**

    `Origin.side` is the direction of the *leg*, so an up leg leaves a candle
    below price that price may return to and bounce from - demand, which is
    support. Reading `side > 0` as resistance would invert both the reject and
    the break reading, and the sign would still print.
    """
    assert origins.Zone.of(origin_of(+1), 1.0).resistance is False
    assert origins.Zone.of(origin_of(-1), 1.0).resistance is True


def test_a_demand_origin_rejecting_is_a_buy_and_breaking_is_a_sell():
    """The two signs, through the same shared scorer `zones` uses, so a reading
    taken here is comparable with one taken there."""
    zone = origins.Zone.of(origin_of(+1), atr=1.0)
    # Left a demand zone upward: it held, so this is a buy.
    assert side_of(zone, "reject", was=True, now=False, close=111.0, seen=False) == +1
    # Closed through a demand zone from below: it failed, so this is a sell.
    assert side_of(zone, "break", was=False, now=False, close=99.0, seen=False) == -1


def test_the_band_is_the_candle_and_the_line_is_where_it_closed():
    """Both are the desk's own later specification, recorded in `Origin`'s
    docstring: the band is drawn high to low rather than body-high, and the
    line sits where the origin closed."""
    zone = origins.Zone.of(origin_of(+1, low=100.0, high=110.0), atr=2.5)
    assert (zone.bottom, zone.top) == (100.0, 110.0)
    assert zone.level == 105.0
    assert zone.atr == 2.5


# ----------------------------------------------- the two modes that are refused


def test_a_mode_needing_a_break_history_is_refused_and_not_approximated(monkeypatch):
    """**`Origin` does not track having been broken.**

    `Zone.flipped` here is always False, so `retest` would return zero on every
    bar - a rule that validates, runs, and reports a cell nothing computed,
    which is the defect `zones.py` has on record. Inventing a second derivation
    of "broken" would make a `retest` cell from this rule incomparable with the
    one `zones` reports under the same name, so it raises instead.
    """
    assert NEEDS_HISTORY, "nothing is being asserted if the set is empty"
    for mode in sorted(NEEDS_HISTORY):
        monkeypatch.setenv("TRADING_ORIGIN_MODE", mode)
        with pytest.raises(ValueError, match="remembers having been broken"):
            origins.Tuning.read()


def test_both_signs_are_offered_so_the_rule_is_not_asserting_one(monkeypatch):
    """`reject` is the reversal and `break` the continuation, and they are exact
    opposites - a rule shipping one would be asserting the sign of the family.
    The control for the test above: refusing two modes is not refusing all."""
    assert set(origins.MODES) == {"reject", "break"}
    for mode in origins.MODES:
        monkeypatch.setenv("TRADING_ORIGIN_MODE", mode)
        assert origins.Tuning.read().mode == mode


def test_an_unknown_mode_raises_rather_than_falling_back(monkeypatch):
    monkeypatch.setenv("TRADING_ORIGIN_MODE", "sideways")
    with pytest.raises(ValueError, match="is not a mode"):
        origins.Tuning.read()


# ------------------------------------------------------- the two nominators


def test_the_two_rules_differ_in_their_nominator_and_not_their_zone():
    """**The claim the pair exists to test.** Same zone model, same scorer, same
    shape of trade; `smc-zones` additionally requires that structure broke in
    the zone's direction. If these two ever stop differing only here, they are
    one rule registered twice."""
    assert origins.SmcZones.confirms is True
    assert origins.Origins.confirms is False
    assert origins.StructureProfile.shape != origins.OriginProfile.shape, (
        "two rules on one shape would each count the other's proposals as their own"
    )
    # The zone adapter and the scorer are literally the same objects, not two
    # copies that could drift.
    assert origins.SmcZones._payload is origins.Origins._payload
    assert origins.SmcZones.decide is origins.Origins.decide


def test_the_structure_gate_reads_the_same_fold_smc_bos_causal_trades():
    """A second derivation of "the trend is up" - a slope, a moving average -
    would make this rule's results incomparable with `smc-bos-causal`'s, which
    is the one other rule here written in the structure vocabulary."""
    from till_infinity.strategies.structure import Fold

    assert origins.Fold is Fold


def test_an_unestablished_trend_is_a_refusal_and_not_a_pass():
    """`Fold.trend` is 0 before either trend has been established. The whole
    claim of the frameworks this borrows from is that the higher-level bias is
    what makes the conjunction worth taking, so "no bias yet" must not pass."""
    from types import SimpleNamespace

    stub = SimpleNamespace(fold=SimpleNamespace(trend=0))
    assert origins.Origins._confirmed(stub, +1) is False
    assert origins.Origins._confirmed(stub, -1) is False

    agrees = SimpleNamespace(fold=SimpleNamespace(trend=+1))
    assert origins.Origins._confirmed(agrees, +1) is True
    assert origins.Origins._confirmed(agrees, -1) is False


# ------------------------------------------------------------- the registration


def test_both_rules_are_registered_and_in_no_default():
    """Registered so `TRADING_STRATEGIES=displacement-zones` is runnable at all -
    `desks.build` refuses an unregistered name - and in no default, because the
    measurement that would license trading these crossings does not exist."""
    from till_infinity.node import desks
    from till_infinity.strategies.config import Settings

    assert "displacement-zones" in desks.RULES
    assert "smc-zones" in desks.RULES
    assert desks.rules() == ("statespace-surprise",), "a default deploy must not pick these up"
    assert "displacement-zones" not in Settings().strategies
    assert "smc-zones" not in Settings().strategies


def test_every_entry_of_both_rules_can_decide_and_exit(monkeypatch):
    """`Desk.decide` raises by design, so inheriting it *is* the bug: every desk
    the node registered once raised `NotImplementedError` on its first
    proposal, and nothing said so because a node that judges nothing looks
    exactly like a quiet market."""
    from till_infinity.node import desks
    from till_infinity.strategies.desk import Desk
    from till_infinity.strategies.exits import ExitMechanism

    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD")
    monkeypatch.setenv("TRADING_ENTRIES", "edge resting arrival")
    monkeypatch.setenv("TRADING_STRATEGIES", "displacement-zones,smc-zones")
    built, clipped = desks.build("MT5")
    assert len(built) == 6, "two rules x three entries on one symbol"
    assert not clipped
    for strategy in built:
        name = type(strategy).__name__
        assert type(strategy).decide is not Desk.decide, f"{name} has no decision"
        assert isinstance(strategy, ExitMechanism), f"{name} has no exit"
        assert strategy.label != name, f"{name} has no profile to name itself by"
    tags = [s.order_id_tag for s in built]
    assert len(set(tags)) == len(tags), f"two desks on one order-id namespace: {tags}"
