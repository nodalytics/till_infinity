"""Bringing a node up, and what a stop does to a book."""

from __future__ import annotations

import pytest

from till_infinity.node.lifecycle import (
    Check,
    Step,
    Stop,
    plan_stop,
    retire_strategy,
    wait_until_up,
)


def clock():
    """A clock that advances a second per reading, so no test sleeps."""
    state = {"t": 0.0}

    def tick() -> float:
        state["t"] += 1.0
        return state["t"]

    return tick


class TestUpMeansEveryClaimInOrder:
    async def test_all_satisfied_reports_up(self):
        checks = [
            Check(Step.PROCESS, lambda: True),
            Check(Step.VENUE, lambda: True, source="venue"),
            Check(Step.ARMED, lambda: True),
        ]
        report = await wait_until_up(checks, interval=0, now=clock())
        assert report.up is True
        assert report.stalled_on is None
        assert "up:" in report.summary()

    async def test_a_stall_names_the_step_rather_than_failing(self):
        """ "Failed to start" is not an answer: a bridge that is down, a
        backfill that is slow and a strategy that never armed take different
        actions."""
        checks = [
            Check(Step.PROCESS, lambda: True),
            Check(Step.VENUE, lambda: False, source="venue"),
            Check(Step.ARMED, lambda: True),
        ]
        report = await wait_until_up(checks, deadline=3, interval=0, now=clock())
        assert report.up is False
        assert report.stalled_on is Step.VENUE
        assert "venue answered" in report.summary()

    async def test_later_steps_are_not_attempted_after_a_stall(self):
        """A node whose data flows but whose venue never answered is not
        three-quarters up, it is misleading."""
        reached = []
        checks = [
            Check(Step.VENUE, lambda: False, source="venue"),
            Check(Step.ARMED, lambda: reached.append("armed") or True),
        ]
        await wait_until_up(checks, deadline=2, interval=0, now=clock())
        assert reached == []

    async def test_a_probe_that_raises_has_simply_not_passed_yet(self):
        """The bridge refusing a connection is a normal state during startup,
        not a reason to abandon the launch."""
        calls = {"n": 0}

        def flaky() -> bool:
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("bridge not up yet")
            return True

        report = await wait_until_up(
            [Check(Step.VENUE, flaky, source="venue")], deadline=10, interval=0, now=clock()
        )
        assert report.up is True
        assert calls["n"] == 3

    async def test_the_venue_is_the_source_that_counts(self):
        """Recorded per check, because three deploys passed their own checks
        while running none of the code they claimed - every probe read our
        side of the wire."""
        checks = [Check(Step.VENUE, lambda: True, source="venue")]
        report = await wait_until_up(checks, interval=0, now=clock())
        assert "[venue]" in report.lines()[0]


class TestStoppingSaysWhatHappensToTheBook:
    def test_leave_does_not_touch_positions_or_orders(self):
        """A restart for a code change must not realise a position."""
        steps = plan_stop(Stop.LEAVE)
        assert not any("close_all_positions" in s for s in steps)
        assert not any("cancel_all_orders" in s for s in steps)
        assert steps[-2:] == ["node.stop", "node.dispose"]

    def test_cancel_clears_resting_orders_and_keeps_positions(self):
        steps = plan_stop(Stop.CANCEL)
        assert any("cancel_all_orders" in s for s in steps)
        assert not any("close_all_positions" in s for s in steps)

    def test_flatten_closes_everything_and_is_never_implicit(self):
        steps = plan_stop(Stop.FLATTEN)
        assert any("close_all_positions" in s for s in steps)
        # Orders go before positions: closing first would leave a resting
        # order that could reopen what was just closed.
        assert steps.index("cancel_all_orders") < steps.index("close_all_positions")

    @pytest.mark.parametrize("policy", list(Stop))
    def test_every_policy_confirms_with_the_venue_before_coming_down(self, policy):
        """A stop that leaves a resting order nobody supervises is worse than
        no stop, and our own record is not evidence about the broker."""
        steps = plan_stop(policy)
        confirm = next(i for i, s in enumerate(steps) if "confirm with the venue" in s)
        assert confirm < steps.index("node.stop")

    def test_reducing_is_the_engines_own_wind_down(self):
        assert Stop.FLATTEN.trading_state == "REDUCING"
        assert Stop.CANCEL.trading_state == "REDUCING"
        assert Stop.LEAVE.trading_state == "ACTIVE"


class TestRetiringOneStrategy:
    def test_it_stops_before_it_removes(self):
        """Removing first leaves the strategy's orders unowned."""
        steps = retire_strategy("refuted")
        assert steps.index("trader.stop_strategy") < steps.index("trader.remove_strategy")

    def test_nothing_is_resting_before_it_is_removed(self):
        steps = retire_strategy("refuted")
        confirm = next(i for i, s in enumerate(steps) if "confirm nothing is resting" in s)
        assert confirm < steps.index("trader.remove_strategy")

    def test_the_reason_is_carried_into_the_plan(self):
        assert "refuted" in retire_strategy("refuted")[0]
