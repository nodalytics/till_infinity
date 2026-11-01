"""`trading doctor` has to print the risk the desk will actually trade with."""

from __future__ import annotations

import re
from dataclasses import fields

from till_infinity.risk import plans
from till_infinity.risk.envelope import Envelope
from till_infinity.strategies import Settings


def effective() -> Envelope:
    """A desk whose environment has overridden the standard plan.

    Projected through `Settings.envelope()` rather than built as an `Envelope`
    directly, because the readout's whole job is to describe what was actually
    resolved - and the projection is now part of that path.
    """
    made = Settings()
    made.risk_plan = "standard"
    made.risk_fraction = 0.005
    made.daily_loss_fraction = 0.25
    made.max_positions = 34
    made.max_per_symbol = 17
    made.min_probability = 0.0
    made.min_reward_to_risk = 0.0
    return made.envelope()


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


class TestThePlanStillLinesUpWithTheSettingsItWritesInto:
    """**`_fields_are_covered` was a private function nothing ever called.**

    It lived in `plans.py`, asserted that every `CONTROLS` key is a field of
    `Settings`, and its own docstring said it was "called by the tests rather
    than at import". No test called it, so a plan could have silently stopped
    setting something and the only report would have been a live account
    behaving unexpectedly.

    It could not travel with `plans.py` to `risk/` - it took
    `dataclasses.fields` to a class in the layer above - and this is where it
    belonged all along: `tests/` may import both packages, which is exactly
    why a cross-layer invariant is a test and not a helper.
    """

    def test_every_control_is_a_settings_field(self):
        known = {f.name for f in fields(Settings)}
        missing = sorted(set(plans.CONTROLS) - known)
        assert not missing, (
            f"{missing} is in CONTROLS and not in Settings - a plan that sets a "
            f"field nobody reads is a limit that is configured and inert"
        )

    def test_every_control_names_the_variable_from_env_reads(self):
        """The other half, and the half a rename actually breaks.

        A plan only fills in what the environment has *not* set, so the table
        maps each field to the variable that overrides it. If that variable is
        not the one `from_env` reads, the plan writes over a number the
        operator set by hand - which is the opposite of the documented rule
        that an individual `TRADING_*` wins.
        """
        read = {c for c in Settings.from_env.__func__.__code__.co_consts if isinstance(c, str)}
        wrong = sorted(
            f"{field}={variable}"
            for field, variable in plans.CONTROLS.items()
            if variable not in read
        )
        assert not wrong, f"CONTROLS names variables `Settings.from_env` does not read: {wrong}"

    def test_a_plan_sets_nothing_the_environment_has_set(self):
        env = {"TRADING_MAX_POSITIONS": "34", "TRADING_RISK_FRACTION": "0.005"}
        values = plans.get("standard").values(environ=env)
        assert "max_positions" not in values
        assert "risk_fraction" not in values
        assert values["daily_loss_fraction"] == 0.03
        assert sorted(plans.overridden(environ=env)) == ["max_positions", "risk_fraction"]

    def test_the_applier_writes_the_plan_and_leaves_the_overrides(self, monkeypatch):
        """The write `Plan.apply` used to do, now done by the layer that owns
        the object it writes into."""
        from till_infinity.strategies.config import apply_plan

        monkeypatch.setenv("TRADING_MAX_POSITIONS", "34")
        made = Settings()
        made.max_positions = 34
        plan = apply_plan(made, "conservative")
        assert plan.name == "conservative"
        assert made.risk_plan == "conservative"
        assert made.risk_fraction == 0.001
        assert made.max_positions == 34, "the environment's number was overwritten"
