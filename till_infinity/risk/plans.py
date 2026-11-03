"""Risk management plans: the limits, as named bundles rather than loose knobs.

Ten separate numbers control how much this can lose. Set individually they are
ten chances to be inconsistent - a 2% per-trade risk under a 3% daily stop
halts the day on the second loss, which is not a plan, it is two settings that
have not been read together. So the numbers that have to agree are grouped and
named, and the name is what gets chosen.

    TRADING_RISK_PLAN=conservative

**A plan is a floor, not a cage.** Any individual `TRADING_*` variable that is
actually set wins over the plan's value, because the plans cannot anticipate
every account - a prop-firm evaluation with a hard 4% daily ceiling wants
`standard` with one number changed, not a fourth plan. What a plan guarantees
is that the numbers you *didn't* set are consistent with the ones you did.

**The edge floors all sit above the upstream gate.** `reactions.MIN_EDGE` is
0.10 and every signal on the bus has cleared it, so a plan setting anything at
or below that would be configuring a gate that cannot fire. The three sit at
0.11, 0.15 and 0.22 - just above it, comfortably above it, and up in the band
[edge.md](../../docs/edge.md) measures as the strongest.

**The differences between the plans are ratios, not opinions.** Each one keeps
the same relationship between per-trade risk and the daily stop - roughly a
dozen consecutive losses to reach it - so that moving between them changes how
much is at stake without changing how the account behaves on a bad run. What
actually varies is how selective the entry is: the conservative plan demands a
higher probability and a better reward-to-risk, and therefore trades less.

## Nothing applies these today, and that is a live gap

`TRADING_RISK_PLAN` is read into `Settings.risk_plan` by `from_env` and then
nothing acts on it. The applier is `strategies.config.apply_plan` and it has
no caller: the one that existed was the CLI, which is retired to
`research/retire/bus/`, and the node has not taken it over. So whichever plan
is named, the desk trades the defaults the `Settings` dataclass declares - and
those are `standard`'s numbers, which is why it has not been noticed.

This is worth stating here rather than only in a report, because the shape is
the one this repository keeps finding: a setting that is read, printed at
start-up and never applied looks from the outside exactly like a setting that
works.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from .envelope import Envelope

#: Each tunable, and the environment variable that sets it directly. A plan
#: only fills in what the environment has not, so this table is the authority
#: on which is which - a field missing from here is one a plan cannot touch.
CONTROLS: Mapping[str, str] = {
    "risk_fraction": "TRADING_RISK_FRACTION",
    "max_risk_money": "TRADING_MAX_RISK_MONEY",
    "max_positions": "TRADING_MAX_POSITIONS",
    "max_per_symbol": "TRADING_MAX_PER_SYMBOL",
    "daily_loss_fraction": "TRADING_DAILY_LOSS_FRACTION",
    "min_reward_to_risk": "TRADING_MIN_RR",
    "max_spread_fraction": "TRADING_MAX_SPREAD_FRACTION",
    "min_probability": "TRADING_MIN_PROBABILITY",
    "min_edge": "TRADING_MIN_EDGE",
    "loss_cooldown": "TRADING_LOSS_COOLDOWN_S",
    "max_hold": "TRADING_MAX_HOLD_S",
    "max_currency_exposure": "TRADING_MAX_CURRENCY_EXPOSURE",
}


@dataclass(frozen=True, slots=True)
class Plan:
    """One coherent set of limits."""

    name: str
    description: str
    risk_fraction: float
    max_positions: int
    max_per_symbol: int
    daily_loss_fraction: float
    min_reward_to_risk: float
    max_spread_fraction: float
    min_probability: float
    min_edge: float
    loss_cooldown: float
    max_hold: float
    max_currency_exposure: float
    max_risk_money: float = 0.0

    @property
    def losses_to_halt(self) -> float:
        """Consecutive full-risk losses before the daily stop. The sanity check."""
        return self.daily_loss_fraction / self.risk_fraction if self.risk_fraction else 0.0

    def values(self, environ: Mapping[str, str] | None = None) -> dict[str, float]:
        """What this plan sets, as field -> value, with the overrides left out.

        **This used to write straight into the strategies `Settings` object**,
        and that is what kept this file out of `risk/`: a writer into a
        configuration object has to be able to see one, and this package may
        not import the layer that owns it.

        The mutation is still the right shape and still happens - `Settings`
        is what every other part of the desk already holds a reference to by
        the time a plan is chosen, so handing back a second one would leave
        the first in service, configured differently, with nothing to say so.
        What changed is **who** performs it: `strategies.config.apply_plan`
        does the `setattr`, because that is the layer that owns the object.
        This returns the numbers and knows nothing about where they land.
        """
        env = os.environ if environ is None else environ
        return {
            field: getattr(self, field)
            for field, variable in CONTROLS.items()
            if variable not in env
        }

    def __str__(self) -> str:
        return (
            f"{self.name}: {self.risk_fraction:.2%}/trade, {self.daily_loss_fraction:.1%}/day "
            f"({self.losses_to_halt:.0f} losses), {self.max_positions} open, "
            f"p>{self.min_probability:.0%}, RR>{self.min_reward_to_risk:.1f}"
        )


def overridden(environ: Mapping[str, str] | None = None) -> list[str]:
    """The `CONTROLS` fields the environment has set, so a plan cannot."""
    env = os.environ if environ is None else environ
    return [field for field, variable in CONTROLS.items() if variable in env]


def describe_effective(envelope: Envelope, environ: Mapping[str, str] | None = None) -> str:
    """The risk envelope the desk will actually trade with, not the plan's own.

    `str(plan)` prints the named plan, and every field the environment
    overrides is then wrong on screen: `trading doctor` reported `0.25%/trade,
    4 open, p>58%` for a desk running 0.5%, 34 open and no probability floor.
    That is the one readout somebody checks before trusting the limits, so it
    has to describe the limits after the plan and the environment have both
    been applied - and say which of the two each number came from.

    It takes an `Envelope` rather than the plan because that is the projection
    of what was actually resolved, and it is why `risk_fraction`,
    `min_probability` and `risk_plan` are in that object at all: a plan exists
    to keep size, the daily stop and selectivity consistent, so the readout
    that checks the consistency has to see all three.
    """
    risk = envelope.risk_fraction
    halt = envelope.daily_loss_fraction / risk if risk else 0.0
    text = (
        f"{envelope.risk_plan}: {risk:.2%}/trade, {envelope.daily_loss_fraction:.1%}/day "
        f"({halt:.0f} losses), {envelope.max_positions} open, "
        f"{envelope.max_per_symbol} per symbol, p>{envelope.min_probability:.0%}, "
        f"RR>{envelope.min_reward_to_risk:.1f}"
    )
    kept = overridden(environ)
    if kept:
        text += f" (from the environment: {', '.join(kept)})"
    return text


PLANS: dict[str, Plan] = {
    plan.name: plan
    for plan in (
        Plan(
            name="conservative",
            description=(
                "For an account that must survive a bad week more than it must "
                "catch a good day. Trades roughly a third as often as standard."
            ),
            risk_fraction=0.001,
            max_positions=2,
            max_per_symbol=1,
            daily_loss_fraction=0.012,
            min_reward_to_risk=0.0,
            max_spread_fraction=0.15,
            min_probability=0.62,
            min_edge=0.22,
            loss_cooldown=1_800.0,
            max_hold=1_200.0,
            max_currency_exposure=0.002,
        ),
        Plan(
            name="standard",
            description=(
                "The default. A quarter percent a trade under a three percent "
                "day, which is about twelve consecutive losses to a halt."
            ),
            risk_fraction=0.0025,
            max_positions=4,
            max_per_symbol=1,
            daily_loss_fraction=0.03,
            min_reward_to_risk=0.0,
            max_spread_fraction=0.25,
            min_probability=0.58,
            min_edge=0.15,
            loss_cooldown=900.0,
            max_hold=1_800.0,
            max_currency_exposure=0.005,
        ),
        Plan(
            name="aggressive",
            description=(
                "More size and a looser entry, on an account whose drawdown is "
                "affordable. The same twelve-loss shape, further from zero."
            ),
            risk_fraction=0.005,
            max_positions=6,
            max_per_symbol=1,
            daily_loss_fraction=0.06,
            min_reward_to_risk=0.0,
            max_spread_fraction=0.35,
            min_probability=0.55,
            min_edge=0.11,
            loss_cooldown=600.0,
            max_hold=2_700.0,
            max_currency_exposure=0.01,
        ),
    )
}

DEFAULT_PLAN = "standard"


def get(name: str) -> Plan:
    """Look a plan up by name, or say what the choices are."""
    found = PLANS.get(name.strip().lower())
    if found is None:
        raise ValueError(f"unknown risk plan {name!r} (have: {', '.join(PLANS)})")
    return found


def catalogue() -> dict[str, Plan]:
    return dict(PLANS)


# **`_fields_are_covered` left with the move, and it was never wired up.** It
# asserted that every `CONTROLS` key is a field of the strategies `Settings`
# dataclass - a real invariant, because a plan that silently stops setting
# something is found by a live account behaving unexpectedly - and its own
# docstring said it was "called by the tests rather than at import". Nothing
# called it, here or in `tests/`. It cannot live in this package now (it took
# `dataclasses.fields` to a class upstairs) and it should not have been a
# private function in the first place, so it is a test:
# `test_plans.py::test_every_control_is_a_settings_field`, which also checks
# the environment variable each one names.
