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

import ast
import re
import sys
import tomllib
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
#: `bus` is the link ADR 0002 names, so importing it is how a service stays
#: decoupled rather than a way around it.
#:
#: **This list used to have four entries and three of them had gone dead.**
#: `logging` and `shared` left for `packages/till-platform` and `channels` for
#: `packages/till-channels`, and an allowance for a module that no longer
#: exists permits nothing while reading as though it does - the same shape as
#: the vacuous scan described on `STANDALONE`, and the third instance of it in
#: one day. `test_every_infrastructure_entry_is_real` is what makes the next
#: one fail instead of lingering.
INFRASTRUCTURE = frozenset({"bus"})

#: The Nautilus layers, and what each is allowed to import.
#:
#: **These are not debts and must not go in `DEBTS`.** That table exists to
#: shrink: every entry is coupling we intend to remove. A node importing an
#: adapter and an actor is not coupling to be paid off, it is what a node *is*.
#:
#: The direction is the rule, and it is worth asserting because the wrong
#: direction is easy to write and hard to see: an adapter that imports a
#: strategy has made the venue depend on what trades on it, which is how a
#: second venue becomes impossible.
#:
#:     node     -> everything below it
#:     actors   -> adapters (for conversion constants), never strategies
#:     strategies -> adapters, actors
#:     adapters -> nothing above them
LAYERS: dict[str, frozenset[str]] = {
    "node": frozenset({"adapters", "actors", "strategies", "trading"}),
    "actors": frozenset({"adapters"}),
    "strategies": frozenset({"adapters", "actors"}),
    "adapters": frozenset(),
}

#: Libraries in `packages/`, as distribution name -> import name.
#:
#: **Prefixed on purpose.** `channels` is Django Channels on PyPI and
#: `statespace` collided with one of the 375 single-word modules in
#: `research/harness/` the day it became a top-level name. A bare name is a
#: name anyone can take, so these carry the `till_` prefix and
#: `test_a_package_owns_its_import_name` checks where the import *resolved*
#: rather than that it resolved - a bare `import channels` would have passed
#: on Django's.
PACKAGES = {"till-platform": "till_platform", "till-channels": "till_channels"}

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
    allowed = INFRASTRUCTURE | DEBTS.get(service, frozenset()) | LAYERS.get(service, frozenset())
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
    offenders = desk_imports(package)
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


def desk_imports(root: Path) -> dict[str, list[str]]:
    """Every real import of `till_infinity` under `root`, by file.

    **Parsed, not matched.** The line form of this check read
    `from till_infinity.logging import get_logger` out of a *docstring* in
    `till-platform` and called it a breach. A docstring that shows an import
    is not an import, and only a parser knows the difference.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == "till_infinity" or name.startswith("till_infinity."):
                    found.setdefault(path.name, []).append(name)
    return found


def test_every_lint_exemption_points_at_files_that_exist():
    """A path-scoped ruff ignore stops applying when the path moves.

    `per-file-ignores` kept an entry for `till_infinity/channels/*` after
    channels left for `packages/`. That one failed loudly - the exemptions
    stopped covering the code and `ruff check` reported four errors - which is
    the lucky case. An exemption that goes dead over code nobody is currently
    linting into would just sit there reading like a rule.

    This is the fourth thing in one day to survive the move that should have
    deleted it, after `INFRASTRUCTURE`, the boundary scan and two globs in
    `test_statespace.py`. The pattern is a path written down in one place and
    changed in another.
    """
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]
    dead = [pattern for pattern in ignores if not any(REPO.glob(pattern))]
    assert not dead, (
        f"per-file-ignores matches nothing: {dead} - delete the entry, or "
        f"point it at where the code went"
    )


#: Import names that do not match the distribution that provides them.
PROVIDED_BY = {
    "dotenv": "python-dotenv",
    "httpx_ws": "httpx-ws",
    "MetaTrader5": "MetaTrader5",
    "pandas": "river",  # arrives as river[pandas], an extra of a declared dep
    "uvloop": "uvloop",
}


def third_party_imports(home: Path) -> dict[str, set[str]]:
    """Top-level non-stdlib, non-local modules imported under `home`."""
    local = {"till_infinity", "till_platform", "till_channels", "statespace"}
    found: dict[str, set[str]] = {}
    for path in sorted(home.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] if node.level == 0 else []
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top and top not in sys.stdlib_module_names and top not in local:
                    found.setdefault(top, set()).add(path.name)
    return found


def test_every_third_party_import_is_declared():
    """An import that works only because something else happened to pull it in.

    **This is what broke the suite on 2026-10-31.** Dropping `anthropic` and
    `pydantic-ai-slim` - whose only callers are retired - took `pydantic` with
    them, and `trading/valuation.py` imports `pydantic` directly. A module with
    nothing to do with agents stopped importing because an agent library left.
    `numpy` was in the same position behind `river[pandas]`.

    The same shape had already appeared one level down: `till-platform`
    declared `orjson` alone while importing `rich` at module level, and it only
    worked because the desk pulls `rich` in. It was found by installing the
    package somewhere the desk was not.

    So: every top-level third-party import must be named in the manifest, as a
    dependency or as an extra. Transitively satisfied is not declared, and the
    difference only shows up when something unrelated is removed.
    """
    manifest = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    declared = " ".join(manifest["dependencies"])
    declared += " " + " ".join(
        dep for group in manifest.get("optional-dependencies", {}).values() for dep in group
    )

    undeclared = {}
    for module, files in sorted(third_party_imports(ROOT).items()):
        name = PROVIDED_BY.get(module, module)
        if name in declared or name.replace("_", "-") in declared:
            continue
        undeclared[module] = sorted(files)[:3]
    assert not undeclared, (
        f"imported but not declared: {undeclared} - add it to pyproject.toml, or "
        f"to PROVIDED_BY if the distribution is named differently"
    )


@pytest.mark.parametrize("layer", sorted(LAYERS))
def test_a_layer_only_imports_what_is_below_it(layer):
    """The direction, which is the whole content of the rule.

    An adapter that imports a strategy makes the venue depend on what trades
    on it. The symptom arrives much later, when a second venue is wanted and
    cannot be added without the first one's strategies coming too.
    """
    home = ROOT / layer
    if not home.is_dir():
        pytest.skip(f"{layer} does not exist yet")
    reaching = imports_of(layer) - INFRASTRUCTURE - {layer}
    forbidden = {name for name in reaching if name in LAYERS and name not in LAYERS[layer]}
    assert not forbidden, (
        f"{layer} imports {sorted(forbidden)}, which is not below it. Allowed: "
        f"{sorted(LAYERS[layer]) or 'nothing'}"
    )


def test_every_infrastructure_entry_is_real():
    """An allowance for a module that does not exist is not an allowance.

    It reads as a rule and enforces nothing, and it survives exactly the event
    that should have deleted it: the module moving somewhere else.
    """
    missing = [
        name
        for name in sorted(INFRASTRUCTURE)
        if not (ROOT / name).is_dir() and not (ROOT / f"{name}.py").is_file()
    ]
    assert not missing, (
        f"INFRASTRUCTURE names modules that are not in till_infinity/: {missing} - "
        f"delete the entry, or the import it permits is unchecked"
    )


@pytest.mark.parametrize("dist", sorted(PACKAGES))
def test_a_package_is_where_it_says_it_is(dist):
    """A library in `packages/` carries its own manifest, like a service."""
    home = REPO / "packages" / dist
    assert (home / PACKAGES[dist]).is_dir(), f"{dist} has no {PACKAGES[dist]}/ in {home}"
    assert (home / "pyproject.toml").is_file(), (
        f"{dist} has no manifest, so it does not install on its own"
    )


@pytest.mark.parametrize("dist", sorted(PACKAGES))
def test_a_package_owns_its_import_name(dist):
    """Where the import resolved, not merely that it resolved."""
    module = __import__(PACKAGES[dist])
    origin = Path(module.__file__).resolve()
    expected = REPO / "packages" / dist / PACKAGES[dist]
    assert origin.parent == expected, (
        f"`import {PACKAGES[dist]}` resolved to {origin}, not {expected} - "
        f"something is ahead of it on sys.path"
    )


@pytest.mark.parametrize("dist", sorted(PACKAGES))
def test_a_package_does_not_import_the_desk(dist):
    """A library the desk depends on cannot depend on the desk."""
    home = REPO / "packages" / dist / PACKAGES[dist]
    offenders = desk_imports(home)
    assert not offenders, f"{dist} imports the desk: {offenders}"


@pytest.mark.parametrize("dist", sorted(PACKAGES))
def test_a_package_declares_the_siblings_it_imports(dist):
    """Importing a sibling package without naming it in the manifest resolves
    here, because the workspace installs them all, and fails wherever the
    package is installed on its own."""
    home = REPO / "packages" / dist
    manifest = (home / "pyproject.toml").read_text()
    siblings = {PACKAGES[other]: other for other in PACKAGES if other != dist}
    undeclared = {}
    for path in sorted((home / PACKAGES[dist]).rglob("*.py")):
        for line in path.read_text().splitlines():
            for module, other in siblings.items():
                if (
                    re.match(rf"\s*(from {module}\b|import {module}\b)", line)
                    and other not in manifest
                ):
                    undeclared.setdefault(other, []).append(path.name)
    assert not undeclared, f"{dist} imports but does not declare: {undeclared}"


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


def test_the_dependency_layer_does_not_try_to_build_the_members():
    """`--no-install-project` is not enough once there is a workspace.

    **Three deploys failed on this and the suite was green for all of them.**
    The test above asserts that each member is copied, and each was - on the
    line *after* the one that needed it. A copy list says nothing about order.

    `--no-install-project` skips only the root project, so uv still builds
    every member the root depends on; at the lockfile layer a member is a
    `pyproject.toml` with no module beside it, and the build stops with
    "Expected a Python module at: packages/till-platform/till_platform/
    __init__.py". `--no-install-workspace` skips the members too, which is
    what that layer is for: third-party wheels, keyed on the lock.

    Asserted on the text because building the image takes minutes and this
    takes none. The build itself remains the real check; this is the one that
    fails in the pull request instead of after the merge.
    """
    dockerfile = (REPO / "Dockerfile").read_text()
    caching = [
        line for line in dockerfile.splitlines() if "uv sync" in line and "--no-install" in line
    ]
    assert caching, "no dependency-only `uv sync` layer in the Dockerfile"
    for line in caching:
        assert "--no-install-workspace" in line, (
            f"{line.strip()!r} would build the workspace members at a layer that "
            f"has only their manifests - use --no-install-workspace"
        )


def test_the_image_says_where_the_contracts_are():
    """The contracts were shipped and unfindable for this image's whole life.

    `till_platform.contracts` counted parent directories from its own
    `__file__`. Installed, that is `site-packages/till_platform/`, so it
    looked in `/app/.venv/lib/shared/contracts/bus` while the files sat in
    `/app/shared/contracts/bus` - and `declared()` returned `()`, so the
    container reported that the bus declares nothing rather than failing.

    Two things keep it fixed, and the second is the one that would have caught
    it: the image declares the directory, and the build asks the *installed*
    package whether it found the schemas, from `/` so that WORKDIR cannot
    answer by accident.
    """
    dockerfile = (REPO / "Dockerfile").read_text()
    assert "ENV TILL_CONTRACTS_DIR=" in dockerfile, "the image does not say where the contracts are"
    assert "contracts.missing()" in dockerfile, (
        "the build does not ask the installed package whether it found the schemas"
    )


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
