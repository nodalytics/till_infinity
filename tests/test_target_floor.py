"""Giving every accepted intent a target, without rewriting the rules.

**Three live rules ship no target on purpose.** `structure.py`, `zones.py` and
`origins.py` all set `target=0.0` with the same comment - "a target invented
here would be a different rule with better arithmetic" - and
`smc_bos_c_L50|M15|N20|time` names its exit in the rule itself: the `time` is a
16-bar clock, not a price. A live `AUDNZD` position carried `sl=1.22639 tp=0.0`
and that was the rule working as specified.

So the floor is a **policy applied after the decision**, not a correction
applied inside it. Every rule's own code path is identical when the floor is
off, which is what keeps the measured baseline reachable - each of those rules
was measured on a stop-or-clock exit, and a target changes the exit and
therefore the expectancy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from till_infinity.domain.models import Intent, Side
from till_infinity.strategies.desk import Desk


def intent(side: Side, entry: float, stop: float, target: float = 0.0, **extra) -> Intent:
    return Intent(
        feed="eurusd",
        symbol="EURUSD",
        volume=0.1,
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        reason="a test",
        interval="15m",
        features=extra.pop("features", {}),
        hold=0.0,
        **extra,
    )


def floored(got: Intent, r: float) -> Intent:
    """`Desk._floor_target` on a stub, which reads only `settings.target_r`."""
    return Desk._floor_target(SimpleNamespace(settings=SimpleNamespace(target_r=r)), got)


def test_a_buy_gets_its_target_above_and_a_sell_below():
    """**The sign, because it is the half that still prints when it is wrong.**
    A target placed on the stop's side of the entry is not a target, it is a
    second stop, and the position would close at a loss on the leg meant to
    bank it."""
    buy = floored(intent(Side.BUY, 1.1000, 1.0990), 2.0)
    assert buy.target == pytest.approx(1.1020), "two risks above the entry"
    assert buy.target > buy.entry > buy.stop

    sell = floored(intent(Side.SELL, 1.1000, 1.1010), 2.0)
    assert sell.target == pytest.approx(1.0980), "two risks below the entry"
    assert sell.target < sell.entry < sell.stop


def test_it_is_measured_in_the_rules_own_risk_and_not_in_a_price():
    """Expressed in R so it scales with whatever stop each rule chose. A fixed
    price distance would be 11 pips of a 15m FX stop and a rounding error on
    `Crash 500 Index`, whose round trip is a whole bar range."""
    tight = floored(intent(Side.BUY, 100.0, 99.0), 3.0)
    wide = floored(intent(Side.BUY, 100.0, 90.0), 3.0)
    assert tight.target == pytest.approx(103.0)
    assert wide.target == pytest.approx(130.0)


def test_a_rule_that_chose_its_own_target_keeps_it():
    """The floor is a floor. A rule with an opinion about where to bank is not
    overridden, and nothing marks it as floored."""
    kept = floored(intent(Side.BUY, 1.1000, 1.0990, target=1.1500), 2.0)
    assert kept.target == 1.1500
    assert "target_floored" not in kept.features


def test_off_is_exactly_a_no_op():
    """**The control, and it is the one that protects the measurements.** Each
    of these rules was measured without a target, so a deploy that has not
    opted in must be bit-identical to one before this existed."""
    same = intent(Side.BUY, 1.1000, 1.0990)
    for off in (0.0, -1.0):
        got = floored(same, off)
        assert got.target == 0.0
        assert got.features == {}
        assert got is same, "the intent was rebuilt for nothing"


def test_a_floored_intent_says_so_in_its_features():
    """The exit has changed, so the journal has to carry it. A later study that
    pooled floored trades with the rule's own stop-or-clock exits would be
    averaging two different rules, and `pooled-medians-invert-subgroups` is
    what that costs - a pooled median there agreed with a claim every subgroup
    refuted."""
    got = floored(intent(Side.BUY, 1.1000, 1.0990, features={"bos_swing": 1.0}), 2.5)
    assert got.features["target_floored"] == 2.5
    assert got.features["bos_swing"] == 1.0, "the rule's own features survive"


def test_an_entry_equal_to_its_stop_is_left_alone():
    """Zero risk, so there is nothing to multiply. `sizes.size` has already
    sized from the same distance and the trade is refused downstream; putting a
    target on a zero would price nothing at all."""
    got = floored(intent(Side.BUY, 1.1000, 1.1000), 2.0)
    assert got.target == 0.0
    assert "target_floored" not in got.features


def test_the_reward_to_risk_is_the_number_that_was_asked_for():
    """Asserted through `Intent.reward` and `Intent.risk` - the properties a
    journal row and a notification actually read - rather than through the
    arithmetic this method just did."""
    got = floored(intent(Side.SELL, 2000.0, 2010.0), 1.5)
    assert got.risk == pytest.approx(10.0)
    assert got.reward == pytest.approx(15.0)
    assert got.reward / got.risk == pytest.approx(1.5)


def test_the_setting_is_off_by_default():
    """So the measured baseline is what a deploy gets until it says otherwise."""
    from till_infinity.strategies.config import Settings

    assert Settings().target_r == 0.0
