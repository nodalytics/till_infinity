"""Everything we call on a Nautilus base class, checked against the real one.

**This file is a sweep, and it exists because three separate modules called a
method Nautilus does not have.** `Actor.publish_data_dict`,
`Actor.subscribe_data_dict` and `Actor.on_data_dict` were used in
`statespace/actor.py`, `notifications/actor.py` and `strategies/basket.py`, and
every test passed - because each stubbed the name, and assigning an attribute
*creates* it. A node would have raised on its first publish.

A sweep found two more of the same shape: `Notifier(Actor).create_task`, which
is on `LiveExecutionClient` and not on `Actor`, and
`MT5ExecutionClient._uuid4`, which is on neither.

The lesson is narrow and worth keeping: **a plausible-looking method name on a
framework class is a guess until something asserts it.** `hasattr` on our own
object cannot tell, because we might have set it. So this asserts against the
framework's class.
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

#: The Nautilus bases we subclass, by the name a module imports them as.
BASES: dict[str, str] = {
    "Actor": "nautilus_trader.common.actor",
    "Strategy": "nautilus_trader.trading.strategy",
    "Indicator": "nautilus_trader.indicators.base",
    "LiveDataClient": "nautilus_trader.live.data_client",
    "LiveMarketDataClient": "nautilus_trader.live.data_client",
    "LiveExecutionClient": "nautilus_trader.live.execution_client",
}

#: Names that look like framework methods and are not. Kept so the sweep's own
#: finding is a test rather than a memory.
NOT_THERE: dict[str, tuple[str, ...]] = {
    "Actor": ("publish_data_dict", "subscribe_data_dict", "on_data_dict", "create_task"),
    "Strategy": ("publish_data_dict", "subscribe_data_dict", "on_data_dict"),
    "LiveExecutionClient": ("_uuid4",),
}

ROOT = pathlib.Path(__file__).resolve().parent.parent / "till_infinity"


def _loaded() -> dict[str, type]:
    return {name: getattr(importlib.import_module(mod), name) for name, mod in BASES.items()}


def _nautilus_bases(tree: ast.Module, names: list[str], loaded: dict[str, type]) -> list[type]:
    """Only bases this file imported from `nautilus_trader`.

    Resolved through the imports rather than by name, because this repo has its
    own `Strategy` - a decision contract that places no orders - and matching
    on the bare word would check our ABC against the framework's class.
    """
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("nautilus_trader"):
            for alias in node.names:
                imported[alias.asname or alias.name] = alias.name
    return [loaded[imported[n]] for n in names if n in imported and imported[n] in loaded]


def _declared(node: ast.ClassDef) -> set[str]:
    """Every name the class defines itself: methods, and `self.x = ...`."""
    out: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef):
            out.add(inner.name)
        elif isinstance(inner, ast.Assign):
            for target in inner.targets:
                if isinstance(target, ast.Attribute) and _is_self(target):
                    out.add(target.attr)
                elif isinstance(target, ast.Name):
                    out.add(target.id)
        elif isinstance(inner, ast.AnnAssign):
            target = inner.target
            if isinstance(target, ast.Attribute) and _is_self(target):
                out.add(target.attr)
            elif isinstance(target, ast.Name):
                out.add(target.id)
    return out


def _is_self(node: ast.Attribute) -> bool:
    return isinstance(node.value, ast.Name) and node.value.id == "self"


def _missing() -> list[str]:
    """`self.x()` calls on a Nautilus subclass that neither we nor it define."""
    loaded = _loaded()
    found: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a file we cannot parse is not a finding
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names = [b.id for b in node.bases if isinstance(b, ast.Name)]
            bases = _nautilus_bases(tree, names, loaded)
            if not bases:
                continue
            base = bases[0]
            ours = _declared(node)
            for inner in ast.walk(node):
                if not (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)):
                    continue
                if not _is_self(inner.func):
                    continue
                name = inner.func.attr
                if name in ours or name.startswith("__") or hasattr(base, name):
                    continue
                found.append(f"{path.name}: {node.name}({base.__name__}).self.{name}()")
    return sorted(set(found))


def test_nothing_calls_a_nautilus_method_that_does_not_exist():
    """The sweep. Walks every class in the tree that subclasses a Nautilus
    base and checks each `self.x()` against the framework's own class."""
    missing = _missing()
    assert not missing, "calls a method the Nautilus base does not provide:\n  " + "\n  ".join(
        missing
    )


@pytest.mark.parametrize(
    ("base_name", "name"),
    [(b, n) for b, names in NOT_THERE.items() for n in names],
)
def test_the_names_the_sweep_found_still_do_not_exist(base_name, name):
    """A regression guard pointing the other way.

    If Nautilus adds one of these, this fails and somebody decides whether to
    use it - rather than a module quietly calling it again because the name
    reads plausibly. `Actor.create_task` is the instructive one: it exists on
    `LiveExecutionClient`, so the name is real and the class was wrong.
    """
    base = _loaded()[base_name]
    assert not hasattr(base, name), (
        f"{base_name} gained {name}: revisit the call sites that work around it"
    )


def test_there_is_no_longer_a_competing_strategy_class():
    """The hazard this guarded against is gone, which is why it inverted.

    This repo used to have its own `Strategy` - a decision contract that
    placed no orders - so a sweep matching on the bare word would check our
    ABC against the framework's class and report nonsense. The ABC retired on
    2026-11-01: its measured helpers are `strategies/profile.py` and its
    decision is a mixin composed into a Nautilus `Strategy`.

    So the assertion is now that nothing in the tree shadows the name. If
    something does again, the sweep's import-resolution matters once more and
    this test says so.
    """
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("till_infinity.strategies.strategies.strategy")

    from nautilus_trader.trading.strategy import Strategy

    from till_infinity.strategies.surprise import Surprise, SurpriseEdge

    # The decision is a mixin with no base, and the leaf is the framework's.
    assert Surprise.__mro__ == (Surprise, object)
    assert issubclass(SurpriseEdge, Strategy)


def test_orderside_has_no_to_position_side():
    """The same trap on an enum, which the `self.x()` sweep cannot see.

    `MT5ExecutionClient._generate_position_status_reports` calls
    `side.to_position_side()` on an `OrderSide`. The name reads as obviously
    right and the enum does not have it, so the first real position raises
    `AttributeError`. If Nautilus adds it, this fails and the call site can
    stop translating by hand.
    """
    from nautilus_trader.model.enums import OrderSide

    assert not hasattr(OrderSide, "to_position_side")
    assert not hasattr(OrderSide.BUY, "to_position_side")
