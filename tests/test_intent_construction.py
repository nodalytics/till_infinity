"""Every `Intent(...)` in the strategies package passes every required field.

**Why a structural test rather than a behavioural one.** On 2026-11-20 the live
desk ran four `IdentityEdge` desks that could not produce a single verdict:
`identity.py` built an `Intent` without `target`, which has no default, so every
`on_data` raised

    TypeError: Intent.__init__() missing 1 required positional argument: 'target'

inside `Desk.guarded()`. A contained exception is not a crash, so the node read
healthy, the handler reported armed, and the family was dead on every bar for as
long as it had been deployed. `venue-faults-hide-below-the-strategy` is the
standing form of this: a rule that never fires and a rule that cannot fire read
identically from outside.

A test that exercised each `decide()` would have caught it and needs a tick, a
profile, a feature dictionary and a configured instrument per family - which is
why no such test existed for this path. Reading the call sites needs none of
that, catches exactly this class of defect for every family at once, and cannot
go stale: `REQUIRED` is derived from the dataclass rather than written down.

It deliberately checks only **keyword** completeness at literal call sites. A
`replace()` or a `**kwargs` spread is a different construction and is out of
scope; `test_counterfactual` and the per-strategy suites cover those.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from till_infinity.domain.models import Intent

STRATEGIES = Path(__file__).resolve().parents[1] / "till_infinity" / "strategies"

#: Fields with no default, derived from the dataclass so this cannot drift.
REQUIRED = frozenset(
    field.name
    for field in dataclasses.fields(Intent)
    if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING  # type: ignore[misc]
)


def _calls() -> list[tuple[Path, int, frozenset[str], bool]]:
    """Every literal `Intent(...)` call site: (path, line, keywords, spreads)."""
    found = []
    for path in sorted(STRATEGIES.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name != "Intent":
                continue
            spreads = any(kw.arg is None for kw in node.keywords) or bool(node.args)
            keywords = frozenset(kw.arg for kw in node.keywords if kw.arg is not None)
            found.append((path, node.lineno, keywords, spreads))
    return found


def test_the_required_fields_are_discovered_at_all() -> None:
    """A guard on the guard.

    If `REQUIRED` came out empty - a refactor giving every field a default, or
    a `dataclasses` API change - every assertion below would pass vacuously and
    this file would be worth nothing while still reading green.
    """
    assert "target" in REQUIRED, f"target is no longer required: {sorted(REQUIRED)}"
    assert {"feed", "symbol", "side", "volume", "entry", "stop"} <= REQUIRED


def test_there_are_intent_call_sites_to_check() -> None:
    """The same guard for the parser: a rename of `Intent` would empty this."""
    sites = _calls()
    assert len(sites) >= 5, f"only {len(sites)} Intent call sites found under {STRATEGIES}"


@pytest.mark.parametrize(("path", "line", "keywords", "spreads"), _calls())
def test_every_intent_names_every_required_field(
    path: Path, line: int, keywords: frozenset[str], spreads: bool
) -> None:
    if spreads:
        pytest.skip("positional or **spread construction, out of scope")
    missing = REQUIRED - keywords
    assert not missing, (
        f"{path.name}:{line} builds an Intent without {sorted(missing)} - "
        f"a TypeError on every call, contained by guarded() and therefore silent"
    )
