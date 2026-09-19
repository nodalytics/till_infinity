"""`trading doctor` has to print the risk the desk will actually trade with."""

from __future__ import annotations

import re

from till_infinity.trading import Settings, plans


def effective() -> Settings:
    """A desk whose environment has overridden the standard plan."""
    made = Settings()
    made.risk_plan = "standard"
    made.risk_fraction = 0.005
    made.daily_loss_fraction = 0.25
    made.max_positions = 34
    made.max_per_symbol = 17
    made.min_probability = 0.0
    made.min_reward_to_risk = 0.0
    return made


class TestTheDoctorPrintsWhatWillActuallyTrade:
    """**`trading doctor` reported `0.25%/trade, 4 open, p>58%`.**

    The desk was running 0.5%, 34 open and no probability floor, because the
    environment had overridden the plan and the doctor printed the plan. It is
    the one readout somebody checks before trusting the limits.
    """

    def test_it_prints_the_settings_not_the_named_plan(self):
        said = plans.describe_effective(effective(), environ={})
        assert "0.50%/trade" in said, said
        assert "34 open" in said, said
        assert "17 per symbol" in said, said
        assert "p>0%" in said, said
        # Word boundaries: "4 open" is a substring of "34 open".
        assert not re.search(r"\b0\.25%", said), said
        assert not re.search(r"\b4 open", said), said

    def test_it_says_which_numbers_came_from_the_environment(self):
        env = {"TRADING_MAX_POSITIONS": "34", "TRADING_RISK_FRACTION": "0.005"}
        said = plans.describe_effective(effective(), environ=env)
        assert "from the environment" in said, said
        assert "max_positions" in said, said
        assert "risk_fraction" in said, said

    def test_nothing_is_claimed_as_overridden_when_nothing_was(self):
        said = plans.describe_effective(effective(), environ={})
        assert "from the environment" not in said, said

    def test_the_halt_count_follows_the_effective_numbers(self):
        """25% a day at 0.5% a trade is fifty losses, not the plan's twelve."""
        said = plans.describe_effective(effective(), environ={})
        assert "(50 losses)" in said, said
