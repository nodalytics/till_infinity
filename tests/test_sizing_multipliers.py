"""The sizing-multiplier path, and the fact that it has never run.

`Profile.risk_scale` and `profile.spike_scale` both imported `scaling` as
`from ...risk import scaling` - **three dots**, which raises `ImportError:
attempted relative import beyond top-level package`. So every call raised, the
eight sizing reductions behind them never applied, and the only coverage was a
`hasattr` check, which a broken method passes just as well as a working one.

The import is fixed and the multipliers are **off**, because switching eight
reductions on with a one-character fix would change every position size on the
next deploy with no measurement of their joint effect and no baseline to
compare against. `refit-the-parameter-a-lever-multiplies` is what that costs:
a multiplier whose mean is not one changes the average too, and it once
reversed a +1192 result to -24.

So these tests pin two things: that the shipped answer is `1.0`, which is what
the desk has actually been trading, and that the import resolves when the
switch is on - the second being the part a `hasattr` could never check.
"""

from __future__ import annotations

import pytest

from till_infinity.strategies.profile import (
    MULTIPLIERS,
    MULTIPLIERS_ON,
    Profile,
    multipliers_on,
    spike_scale,
)


class Bare(Profile):
    """A profile with nothing on it, so only the gate can be under test."""

    name = "bare"


@pytest.fixture(autouse=True)
def _off(monkeypatch):
    monkeypatch.delenv(MULTIPLIERS_ON, raising=False)


def test_the_multipliers_are_off_as_shipped():
    """Which is not a default chosen here - it is what the desk has traded,
    because the path raised on every call until 2026-11-01."""
    assert multipliers_on() == frozenset()
    assert Bare.__new__(Bare).risk_scale({}, "eurusd") == 1.0
    assert spike_scale({}, object()) == 1.0


def test_an_unset_switch_is_not_an_error():
    """A gate that raised when unset would be the same bug in a new place: a
    sizing path that cannot be called is a sizing path nobody is using."""
    assert Bare.__new__(Bare).risk_scale({"tr_percentile": 0.99}, "eurusd") == 1.0


def test_an_empty_setting_leaves_everything_off(monkeypatch):
    """A blank value is what a hand-edited env file looks like, and it has to
    mean off rather than all."""
    monkeypatch.setenv(MULTIPLIERS_ON, "")
    assert multipliers_on() == frozenset()
    monkeypatch.setenv(MULTIPLIERS_ON, " , ")
    assert multipliers_on() == frozenset()


def test_all_turns_on_every_one(monkeypatch):
    monkeypatch.setenv(MULTIPLIERS_ON, "all")
    assert multipliers_on() == set(MULTIPLIERS)
    assert len(MULTIPLIERS) == 9, "eight reductions plus the structural share"


def test_the_import_actually_resolves_now(monkeypatch):
    """**The assertion a `hasattr` cannot make.** `risk_scale` existed and
    raised `ImportError` for as long as the path was dead, so the only test
    that distinguishes fixed from broken is one that reaches the import.

    `spike_scale` is the one of the two that needs nothing but its arguments,
    so it is the one that can be driven to the import without constructing a
    whole profile.
    """
    monkeypatch.setenv(MULTIPLIERS_ON, "spike")

    class Settings:
        spike_above = 0.0
        spike_floor = 0.5

    # Reaches `scaling.by_spike` and returns a real number rather than raising.
    assert spike_scale({"tr_percentile": 0.5}, Settings()) == pytest.approx(1.0)


def test_each_multiplier_can_be_switched_on_by_itself(monkeypatch):
    """**Eight at once is one trial with eight confounded parameters**, and at
    a target Sharpe of 1.5 a month of data supports about one trial. So they
    are named individually: `SIZING_MULTIPLIERS=spike` enables one."""
    monkeypatch.setenv(MULTIPLIERS_ON, "spike")
    assert multipliers_on() == {"spike"}
    monkeypatch.setenv(MULTIPLIERS_ON, "spike,crowding")
    assert multipliers_on() == {"spike", "crowding"}
    monkeypatch.setenv(MULTIPLIERS_ON, "all")
    assert multipliers_on() == set(MULTIPLIERS)


def test_a_typo_refuses_rather_than_silently_disabling_one(monkeypatch):
    """A name that matched nothing would leave a multiplier off while the
    config said it was on, and the failure is a position sized **larger** than
    intended - the wrong direction to be quiet about."""
    monkeypatch.setenv(MULTIPLIERS_ON, "spike,crowdding")
    with pytest.raises(ValueError, match="not a sizing multiplier"):
        multipliers_on()


def test_the_values_come_back_by_name(monkeypatch):
    """A product says a trade was made smaller; nine named numbers say which
    readings did it and by how much. The journal's whole value is the `why`,
    and a product discards exactly that.

    The keys are present whether or not a multiplier is enabled, so a reader
    comparing two decisions is not comparing two different shapes.
    """
    found = Bare.__new__(Bare).multipliers({}, "eurusd")
    assert set(found) == set(MULTIPLIERS)
    assert all(value == 1.0 for value in found.values())


def test_the_module_imports_scaling_from_one_level_up():
    """The literal regression. `strategies` and `risk` are siblings under
    `till_infinity`, so `..risk` is correct and `...risk` reaches past the
    top-level package - which is an `ImportError` at call time rather than at
    import time, and so invisible to anything that only imports the module.
    """
    from pathlib import Path

    import till_infinity.strategies.profile as module

    source = Path(module.__file__).read_text()
    # Import *statements* only - the prose above `MULTIPLIERS_ON` quotes the
    # broken form on purpose, and a substring search would match itself.
    statements = [
        line.strip() for line in source.splitlines() if line.strip().startswith("from ..")
    ]
    assert not [line for line in statements if line.startswith("from ...risk")]
    # Three: `spike_scale`, `risk_scale`'s product and `multipliers`' terms.
    assert statements.count("from ..risk import scaling") == 3
