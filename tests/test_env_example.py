"""`.env.example` against the readers, in both directions.

**A shipped configuration that names a variable nothing reads is worse than one
that omits it**, because it reads as a supported knob: someone sets it, nothing
happens, and the setting looks broken rather than absent. The file had rotted
both ways before this test existed - 72 variables the node reads were
undocumented, 79 documented ones were read by nothing (`PRICES_*`, `STRUCTURES_*`
and the retired bus's, left behind when those services retired), and one entry
had been generated into the literal text `PRICES_SOURCES= chosen = tuple(n.strip(`.

`test_entrypoints.py` already pins the *values* of two keys against the rule
registry, which is the other half: a name can be live and its value dead.
"""

from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "till_infinity"

#: The helpers each settings module wraps `os.environ` in. Matched by name,
#: because a bare `.get("OBS_VALUE")` is a dict read and not a setting - the
#: first version of this walk accepted any `.get` and put seven SDMX field
#: names from the IMF adapter into the example file.
HELPERS = frozenset(
    {"_flag", "_float", "_int", "_str", "_list", "_csv", "_name", "_seconds", "_text"}
)

#: Names built at runtime from an interval, so no literal exists to find.
#: `desks.symbols_for` reads `TRADING_SYMBOLS_<INTERVAL>` and `rules_for` reads
#: `TRADING_STRATEGIES_<INTERVAL>`, and both are deployed - the 5m scope is
#: live. Listed rather than inferred, so adding a scope to the example is a
#: deliberate line here and not an accident.
RUNTIME_BUILT = frozenset({"TRADING_SYMBOLS_5M", "TRADING_STRATEGIES_5M"})

KEY = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=")


def _is_environ(node: ast.AST) -> bool:
    """`os.environ`, `environ`, or `os.environ.get`'s receiver."""
    if isinstance(node, ast.Attribute):
        return node.attr == "environ"
    return isinstance(node, ast.Name) and node.id == "environ"


def read_by_the_code() -> set[str]:
    keys: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            if isinstance(func, ast.Name):
                named = func.id in HELPERS or func.id == "getenv"
            elif isinstance(func, ast.Attribute):
                named = (func.attr == "get" and _is_environ(func.value)) or func.attr == "getenv"
            else:
                continue
            first = node.args[0]
            if named and isinstance(first, ast.Constant) and isinstance(first.value, str):
                keys.add(first.value)
    return {k for k in keys if k.isupper() and k.replace("_", "").isalnum()}


def documented() -> set[str]:
    text = (ROOT / ".env.example").read_text()
    return {m.group(1) for line in text.splitlines() if (m := KEY.match(line.strip()))}


def test_the_walk_finds_the_settings_it_is_supposed_to():
    """**The control, and without it the rest of this file passes vacuously.**
    A walk that found nothing would satisfy both directions below."""
    found = read_by_the_code()
    assert len(found) > 150, f"only {len(found)} settings found; the walk is broken"
    for name in ("TRADING_LIVE", "TRADING_STRATEGIES", "STATESPACE_WARM_BARS", "NOTIFY_SHAPES"):
        assert name in found, f"{name} is read by the node and the walk missed it"


def test_the_walk_does_not_mistake_a_dict_read_for_a_setting():
    """`sources/imf.py` reads `row.get("OBS_VALUE")` on an SDMX record. The
    first version of this accepted any `.get` with an upper-case literal and
    documented seven of those as environment variables."""
    found = read_by_the_code()
    for name in (
        "OBS_VALUE",
        "TIME_PERIOD",
        "FREQUENCY",
        "COUNTRY",
        "SECTOR",
        "SCALE",
        "INDICATOR",
    ):
        assert name not in found, f"{name} is a data field, not a setting"


def test_every_setting_the_node_reads_is_in_the_example():
    """A setting that never reaches the example is one an operator cannot know
    about: the default is then not a choice, it is whatever the code happened
    to resolve."""
    missing = sorted(read_by_the_code() - documented())
    assert not missing, f".env.example documents none of {missing}, which the node reads"


def test_the_example_names_nothing_the_node_ignores():
    """The direction that rots quietly. A retired service's settings stay
    readable in the example long after the service goes, and they read as
    supported - so setting one does nothing and looks broken rather than
    absent."""
    extra = sorted(documented() - read_by_the_code() - RUNTIME_BUILT)
    assert not extra, f".env.example names {extra}, which nothing in till_infinity reads"


def test_no_default_carries_the_machine_it_was_resolved_on():
    """**This file is public.** `CORPUS_DIR` defaults to `Path.home()`, so a
    generated example wrote a developer's home directory into the repository."""
    text = (ROOT / ".env.example").read_text()
    for leak in ("/home/", "/Users/", "C:\\Users"):
        assert leak not in text, f"{leak} reached .env.example"
