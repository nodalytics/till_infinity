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

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / "till_infinity"

#: Services that have left the package and stand on their own, with the
#: distribution each one installs as.
#:
#: **Named, not discovered, and that is the point.** When `statespace` moved to
#: `services/` this file still passed - `imports_of("statespace")` looked in
#: `till_infinity/`, found no directory, and returned an empty set, so the test
#: that says it owes nothing passed by asking nothing. A guard that goes quiet
#: when its subject moves is worse than no guard, because it reports success.
STANDALONE = {"statespace": "statespace"}

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
    "news": frozenset({"prices"}),
    "structures": frozenset({"journal", "prices", "trading"}),
    "trading": frozenset({"journal", "prices", "structures"}),
}

#: Services retired into `research/retire/`, which must no longer be importable.
RETIRED = ("agents",)

#: `models` is still a package - it ships the `*.json` models that
#: `shared/frozen.py` reads - but it holds no Python any more, so it owes
#: nothing and is not in `RETIRED` either.


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


@pytest.mark.parametrize("name", RETIRED)
def test_a_retired_package_is_not_importable(name):
    """`research/retire/README.md`: "a retired service that still sits on the
    import graph is not retired, it is dormant, and dormant code gets restarted
    by accident."

    **This caught a real one.** `git mv` moved every `.py` out of
    `till_infinity/agents/` and left `__pycache__` behind - and Python treats a
    bare directory as a namespace package, so `from till_infinity import agents`
    still succeeded. `test_stack.py`'s entry-point check went on passing against
    a package whose every module had been moved out from under it.
    """
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f"till_infinity.{name}")


@pytest.mark.parametrize("name", sorted(STANDALONE))
def test_a_standalone_service_is_where_it_says_it_is(name):
    """A service that has left the package must be found in `services/`.

    This is the guard against the failure described on `STANDALONE`: without
    it, a service that moves again stops being checked and every test about it
    passes vacuously.
    """
    package = REPO / "services" / name / STANDALONE[name]
    assert package.is_dir(), f"{name} is not at {package}"
    assert (REPO / "services" / name / "pyproject.toml").is_file(), (
        f"{name} has no manifest, so it does not install on its own"
    )


@pytest.mark.parametrize("name", sorted(STANDALONE))
def test_a_standalone_service_does_not_import_the_desk(name):
    """The strong form of the boundary: not impoliteness but installability.

    `till_infinity` is not a dependency of these packages, so an import of it
    would not resolve where the service is installed alone - which is the thing
    `uv run --project services/<name>` proves and this keeps true.
    """
    package = REPO / "services" / name / STANDALONE[name]
    offenders = {}
    for path in sorted(package.rglob("*.py")):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            if re.match(r"(from|import) till_infinity\b", stripped):
                offenders.setdefault(path.name, []).append(stripped)
    assert not offenders, f"{name} imports the desk: {offenders}"


@pytest.mark.parametrize("name", sorted(STANDALONE))
def test_a_standalone_service_owns_its_top_level_name(name):
    """A standalone service's name is global, and `research/` is full of names.

    Moving a package out of `till_infinity` promotes its name from
    `till_infinity.statespace` to plain `statespace` - and a plain name can be
    taken. `research/harness/` holds 375 single-word modules, one of them
    `statespace.py`, and three test files used to put that directory at the
    *front* of `sys.path` to reach one module each. Whichever of them pytest
    collected first then decided what `from statespace import ...` meant for
    the rest of the session: the suite passed when run on its own files and
    died on `import numba` when run whole.

    So the import is checked against its origin, not merely attempted. A test
    that only does `import statespace` passes on the research harness too.
    """
    module = __import__(STANDALONE[name])
    origin = Path(module.__file__).resolve()
    expected = REPO / "services" / name / STANDALONE[name]
    assert origin.parent == expected, (
        f"`import {STANDALONE[name]}` resolved to {origin}, not the service at "
        f"{expected} - something is ahead of it on sys.path"
    )


def test_no_test_puts_a_research_directory_ahead_of_installed_packages():
    """`sys.path.insert(0, ...)` in a test file is a session-wide mutation.

    It outlives the test, the module and the file, and it silently outranks
    every installed distribution - including the services in `services/`, which
    install as editable workspace members and so have no directory in
    `site-packages` to make the clash visible.

    Appending is the fix where a research directory genuinely has to be flat on
    the path, which is the case when its modules import siblings by bare name.
    """
    offenders = {}
    for path in sorted((REPO / "tests").rglob("*.py")):
        if path.name == Path(__file__).name:
            continue  # this file names the pattern in order to forbid it
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # a comment explaining the rule is not a breach
            if "sys.path.insert" in stripped and "research" in stripped:
                offenders.setdefault(path.name, []).append(number)
    assert not offenders, (
        f"prepend a research directory: {offenders} - use sys.path.append, or "
        f"import by package path (research.harness.x)"
    )


def test_statespace_owes_nothing():
    """The exemplar. Every other service is meant to end up here.

    It is no longer in `till_infinity/` at all, so this asserts the registry
    agrees rather than measuring an empty directory.
    """
    assert "statespace" in STANDALONE
    assert "statespace" not in DEBTS
    assert "statespace" not in services(), "it left the package; the scan should not find it"


def test_the_image_carries_every_python_workspace_member():
    """A member the Dockerfile forgets is missing from production only.

    This is the shape that hid `shared/contracts/` for a day: the tests pass
    because the files are on disk here, and the container is built from a
    narrower copy list. So the copy list is asserted rather than trusted -
    twice over, because a uv workspace needs each member's manifest at the
    lockfile step *and* its code later, and forgetting the first fails the
    build loudly while forgetting the second ships an image that imports the
    desk and then cannot find a service.
    """
    import tomllib

    root = tomllib.loads((REPO / "pyproject.toml").read_text())
    workspace = root["tool"]["uv"]["workspace"]
    excluded = set(workspace.get("exclude", []))

    members = []
    for pattern in workspace["members"]:
        for path in sorted(REPO.glob(pattern)):
            rel = path.relative_to(REPO).as_posix()
            if path.is_dir() and rel not in excluded:
                members.append(rel)
    assert members, "the workspace declares no members"

    dockerfile = (REPO / "Dockerfile").read_text()
    for rel in members:
        assert f"COPY {rel}/pyproject.toml" in dockerfile, (
            f"{rel}'s manifest is not copied before `uv sync --frozen`, which resolves it"
        )
        assert f"COPY {rel}/ " in dockerfile, f"{rel}'s code is not copied into the image"


def test_the_go_service_is_excluded_rather_than_broken():
    """uv refuses a glob member with no manifest, so the Go service is named.

    Asserted because the exclusion is easy to delete and the failure it
    prevents - `uv sync` refusing to resolve at all - would look like a
    lockfile problem rather than a layout one.
    """
    import tomllib

    root = tomllib.loads((REPO / "pyproject.toml").read_text())
    excluded = root["tool"]["uv"]["workspace"].get("exclude", [])
    for rel in excluded:
        path = REPO / rel
        assert path.is_dir(), f"{rel} is excluded but does not exist"
        assert not (path / "pyproject.toml").is_file(), (
            f"{rel} has a manifest now, so it should be a member rather than excluded"
        )
