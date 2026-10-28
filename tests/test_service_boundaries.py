"""No service may import another one, except where it already does.

[ADR 0002](../docs/adr/0002-services-are-self-contained.md) says a service
lives in its own package, talks over the bus, and does not reach into another
service. That rule is worth nothing as prose: the coupling it forbids is 54
import sites deep in this repository already, and it got there one convenient
import at a time.

So this file holds the **current** coupling as data. `DEBTS` is what each
service imports from another service today, and two tests sit either side of
it: one fails when a service gains an import the list does not allow, and one
fails when an entry in the list has been paid off and not deleted. The list can
only shrink.

`statespace` is the exemplar and owes nothing. `TestVendoredCusum` in
`test_statespace.py` has asserted that for one package since before this file
existed, with the same exemption for `shared` - "it travels with the package
rather than being a model the package depends on". This generalises it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / "till_infinity"

#: Imported freely, because none of it is a service.
#:
#: `bus` is the link ADR 0002 names and `channels` is its transport, so
#: importing them is how a service stays decoupled rather than a way around it.
#: `logging` is a logger factory. `shared` holds contracts and travels with
#: each package.
INFRASTRUCTURE = frozenset({"bus", "channels", "logging", "shared"})

#: What each service imports from another service **today**, and nothing more.
#:
#: Every entry is a debt, not a permission. Clearing them is the work ADR 0002
#: describes; until then they are written down so the next one is visible.
#:
#: **`structures` importing `trading` makes the dependency a cycle** -
#: `trading` imports `structures` as well - which is the clearest single
#: argument for the retirement in progress. It is listed rather than fixed
#: because the package is leaving.
DEBTS: dict[str, frozenset[str]] = {
    "agents": frozenset({"journal", "news", "structures"}),
    "models": frozenset({"prices", "structures"}),
    "news": frozenset({"prices"}),
    "structures": frozenset({"journal", "prices", "trading"}),
    "trading": frozenset({"agents", "journal", "prices", "structures"}),
}


def services() -> list[str]:
    """The service packages: a directory under `till_infinity` with an init."""
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir() and (p / "__init__.py").exists())


def imports_of(service: str) -> set[str]:
    """Which other top-level packages or modules `service` imports.

    Relative imports are counted only at the depth that reaches
    `till_infinity` itself, so `from .state import x` inside a subpackage is
    this service's own business and does not appear.
    """
    found: set[str] = set()
    for file in (ROOT / service).rglob("*.py"):
        depth = len(file.relative_to(ROOT).parts) - 1
        source = file.read_text()
        for dots, name in re.findall(r"^\s*from (\.+)([A-Za-z_]\w*)?", source, re.M):
            if name and len(dots) == depth + 1 and name != service:
                found.add(name)
        for name in re.findall(r"^\s*from till_infinity\.([A-Za-z_]\w*)", source, re.M):
            if name != service:
                found.add(name)
    return found


@pytest.mark.parametrize("service", services())
def test_no_service_gains_a_new_cross_service_import(service):
    """A new reach into another service fails here, not in a later audit."""
    allowed = INFRASTRUCTURE | DEBTS.get(service, frozenset())
    gained = sorted(imports_of(service) - allowed)
    assert not gained, (
        f"{service} imports {', '.join(gained)}. ADR 0002: a service talks over the bus. "
        f"If this is deliberate, add it to DEBTS with the reason."
    )


@pytest.mark.parametrize("service", sorted(DEBTS))
def test_a_paid_debt_is_deleted(service):
    """The list can only shrink, so a stale entry is a failure too.

    Without this, `DEBTS` becomes a record of what the coupling once was and
    stops describing anything. An entry that no longer corresponds to a real
    import has been paid, and saying so is the point of the exercise.
    """
    stale = sorted(DEBTS[service] - imports_of(service))
    assert not stale, f"{service} no longer imports {', '.join(stale)} - delete it from DEBTS."


def test_statespace_owes_nothing():
    """The exemplar. Every other service is meant to end up here."""
    assert imports_of("statespace") <= INFRASTRUCTURE
    assert "statespace" not in DEBTS
