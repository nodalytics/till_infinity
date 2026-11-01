"""The seam that let `guard` and `plans` move into `risk/`, held in place.

`risk` may not import `strategies` - risk applies across strategies, so a
second strategy package could not share a `risk` that reached into the first -
and the two modules that most obviously belong in `risk` by subject both
needed the strategies configuration object. `guard.py` read nineteen fields of
`Settings` and five methods of the context; `plans.py` wrote twelve fields
into it. `tests/test_service_boundaries.py` records `guard.py` being placed
there once and sent back with that import as the symptom.

`risk/envelope.py` is what replaced the reach: twenty-two numbers, frozen,
projected by `Settings.envelope()` on the far side of the boundary and handed
in as an argument. This file is what keeps that projection honest, and
`tests/` is the right place for it because this is the one directory allowed
to import both packages - which is also why the cross-layer invariant that
used to be `plans._fields_are_covered` is a test in `test_plans.py` now.

**The gate names are in here as data on purpose.** The refusal reasons are the
journal's whole value: a renamed gate does not break anything that runs, it
breaks reading the record back, and it does so silently and retrospectively.
"""

from __future__ import annotations

import ast
import re
from dataclasses import MISSING, fields
from pathlib import Path

import pytest

from till_infinity.risk import plans
from till_infinity.risk.envelope import Envelope
from till_infinity.risk.guard import ACCOUNT_LEVEL, PER_STRATEGY, Conditions, Guard, Limits
from till_infinity.strategies.config import Settings
from till_infinity.strategies.context import Context

GUARD = Path(__file__).resolve().parent.parent / "till_infinity" / "risk" / "guard.py"

#: Every gate name that can reach the journal, sorted. Eighteen, from
#: seventeen `_no()` call sites: `fx_window` supplies two of them through one.
GATES = (
    "already_open",
    "cooldown",
    "dislocated",
    "drift",
    "exposure",
    "fx_quiet_hour",
    "fx_sunday_open",
    "halted",
    "max_positions",
    "news",
    "quiet_hour",
    "release_in_hold",
    "reward_to_risk",
    "size",
    "spread",
    "spread_risk",
    "swap",
    "wide",
)

#: The order `Guard.allows` applies them in, which decides which gate gets
#: named when several would refuse. Cheapest and most decisive first: a halted
#: day and a blackout need no arithmetic, the arithmetic comes before anything
#: touching the book, and exposure is last because it is the only one that
#: needs the trade to have been sized.
#:
#: `fx_window` and `swap` appear under their own names because they refuse
#: from a helper - the first returns one of two gate names, the second returns
#: a whole `Refusal`.
ORDER = (
    "halted",
    "quiet_hour",
    "fx_window",
    "news",
    "release_in_hold",
    "drift",
    "wide",
    "dislocated",
    "max_positions",
    "already_open",
    "cooldown",
    "reward_to_risk",
    "spread",
    "spread_risk",
    "swap",
    "size",
    "exposure",
)


def allows_source() -> str:
    """The body of `Guard.allows`, by parse rather than by eyeball."""
    tree = ast.parse(GUARD.read_text(), filename=str(GUARD))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "allows":
            return ast.get_source_segment(GUARD.read_text(), node) or ""
    raise AssertionError("Guard.allows is gone")


class TestTheRefusalsComeOutUnchanged:
    """The one thing a move of this file must not change."""

    def test_every_gate_name_is_the_one_it_was(self):
        source = GUARD.read_text()
        named = set(re.findall(r'_no\(\s*"([a-z_]+)"', source))
        # `fx_window` returns the gate name rather than refusing itself.
        named |= set(re.findall(r'^\s+"(fx_[a-z_]+)",$', source, re.M))
        assert tuple(sorted(named)) == GATES, (
            f"the gate names changed: {sorted(named)}. The refusal reasons are "
            f"what the journal is for, and a renamed gate breaks reading the "
            f"record back rather than breaking anything that runs."
        )

    def test_the_gates_are_applied_in_the_recorded_order(self):
        """A refusal names one gate, so the order decides which one."""
        body = allows_source()
        found = tuple(
            match.group(1) or ("fx_window" if match.group(2) else None) or match.group(3)
            for match in re.finditer(
                r'_no\(\s*"([a-z_]+)"|_no\((fx_closed\[0\])|self\._(swap_refusal|exposure)\(',
                body,
            )
        )
        found = tuple("swap" if name == "swap_refusal" else name for name in found)
        assert found == ORDER, f"the gate order changed: {found}"

    def test_the_scan_would_notice(self):
        """Power, before the two assertions above are believed.

        A name scan that matched nothing would pass both of them, and this
        repository has four recorded instances of a guard going quiet when its
        subject moved.
        """
        assert len(GATES) == 18
        assert len(ORDER) == 17
        assert set(ORDER) - {"fx_window", "swap"} < set(GATES)


class TestTheEnvelopeIsTheConfigurationSubset:
    """Exactly the fields `risk/` reads, and nothing it does not."""

    def test_every_field_is_a_settings_field_with_the_same_value(self):
        """The projection is the only place the two can disagree."""
        shipped = Settings()
        made = shipped.envelope()
        for field in fields(Envelope):
            assert hasattr(shipped, field.name), (
                f"Envelope.{field.name} is not a Settings field - the projection "
                f"cannot fill it from the configuration"
            )
            assert getattr(made, field.name) == getattr(shipped, field.name), (
                f"Settings.envelope() put the wrong number in {field.name}"
            )

    def test_it_carries_no_defaults_of_its_own(self):
        """**The substantive decision in `envelope.py`.**

        A default here would give every number two homes - `Settings` and that
        file - with nothing to notice when they diverged, which is the failure
        this repository keeps writing down. Without defaults there is exactly
        one way to obtain an `Envelope`, and a field added to it is a
        `TypeError` at the projection until the projection names it.
        """
        defaulted = [
            f.name
            for f in fields(Envelope)
            if f.default is not MISSING or f.default_factory is not MISSING
        ]
        assert not defaulted, (
            f"{defaulted} now default in Envelope as well as in Settings. Two "
            f"homes for one number is how a limit drifts from the limit that "
            f"was configured."
        )

    def test_the_fields_are_the_fields_the_package_reads(self):
        """Both directions, because each catches a different mistake.

        A field read and not declared is an `AttributeError` on a slotted
        frozen class - loud, and only at the moment a gate runs. A field
        declared and not read is the quieter one: it says this package needs
        something of the desk's configuration that it does not, and the next
        reader believes it.
        """
        read = set()
        for path in sorted(GUARD.parent.glob("*.py")):
            # Parsed, not matched: `envelope.py` is written in three
            # docstrings, and a regex reads that as a field called `py`.
            for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
                if not isinstance(node, ast.Attribute):
                    continue
                owner = node.value
                name = getattr(owner, "id", None) or getattr(owner, "attr", None)
                if name == "envelope":
                    read.add(node.attr)
        declared = {f.name for f in fields(Envelope)}
        assert read == declared, (
            f"read and not declared: {sorted(read - declared)}; declared and "
            f"never read: {sorted(declared - read)}"
        )

    def test_it_is_frozen(self):
        made = Settings().envelope()
        with pytest.raises(Exception, match=r"cannot assign|frozen"):
            made.max_positions = 99  # type: ignore[misc]


class TestTheContextArrivesAsAProtocol:
    """The other half of the reach, and the one with no projection to check."""

    def test_the_implementation_still_answers_all_five(self):
        """`Guard` holds its context optional and **every check it drives fails
        open**, so a method that stopped existing would be a silently missing
        gate rather than a traceback. This is the only place that can notice,
        because it is the only one allowed to import both.
        """
        assert isinstance(Context(), Conditions)

    def test_the_protocol_names_exactly_what_the_guard_calls(self):
        asked = set(re.findall(r"self\.context\.([a-z_]+)\(", GUARD.read_text()))
        named = {name for name in dir(Conditions) if not name.startswith("_")}
        assert asked == named, (
            f"the guard asks {sorted(asked)} and the protocol names "
            f"{sorted(named)} - a question not in the contract is a question "
            f"the implementation can stop answering without anything failing"
        )

    def test_a_context_missing_one_method_is_not_one(self):
        """Power for the conformance check above."""

        class Half:
            def blackout(self, feed, now=None):
                return None

        assert not isinstance(Half(), Conditions)


class TestTheAccountsLimitsStayTheAccounts:
    """`PER_STRATEGY` and `ACCOUNT_LEVEL` said "so a test can assert" and no
    test did - the same shape as `plans._fields_are_covered`. Two dangling
    guards in two files that moved together, which is why both are written
    here rather than noted.

    The failure they describe is specific and expensive: give seventeen
    strategies a daily loss budget each and the account can lose seventeen
    times the limit it was configured with.
    """

    def test_a_strategy_can_only_govern_the_per_trade_gates(self):
        tunable = {f.name for f in fields(Limits)} - {"by"}
        assert tunable == set(PER_STRATEGY), (
            f"Limits exposes {sorted(tunable)} and PER_STRATEGY names {sorted(PER_STRATEGY)}"
        )

    def test_no_account_level_limit_can_be_overridden_by_one(self):
        reachable = {f.name for f in fields(Limits)}
        assert not (ACCOUNT_LEVEL & reachable), sorted(ACCOUNT_LEVEL & reachable)

    def test_both_sets_name_real_limits(self):
        declared = {f.name for f in fields(Envelope)}
        assert declared >= PER_STRATEGY, sorted(PER_STRATEGY - declared)
        assert declared >= ACCOUNT_LEVEL, sorted(ACCOUNT_LEVEL - declared)


def test_the_guard_takes_its_limits_rather_than_reaching_for_them():
    """The shape of the fix, asserted rather than described.

    `Guard` holds an `Envelope` and never a `Settings`, so there is no path
    from a gate back to the configuration object - which is what a
    `TYPE_CHECKING`-guarded import would have left behind, and what the
    boundary scan matches indented imports in order to catch.
    """
    held = {f.name: f.type for f in fields(Guard)}
    assert held["envelope"] in ("Envelope", Envelope)
    assert not any("Settings" in str(t) for t in held.values())


def test_a_plan_knows_its_numbers_and_not_where_they_go():
    """`Plan.values` is the half of `Plan.apply` that could come here."""
    values = plans.get("standard").values(environ={})
    assert set(values) == set(plans.CONTROLS)
    # The configuration class is not in this module's namespace at all, so
    # nothing here can write into one by reaching for it.
    assert not hasattr(plans, "Settings")
    assert not hasattr(plans.Plan, "apply")
