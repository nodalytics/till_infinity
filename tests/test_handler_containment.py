"""A handler that raises refuses its own message and the node keeps running.

**Measured cost of the alternative: 13 restarts in seven hours.** On
2026-11-11 `profile.multipliers` raised `AttributeError` on every sized intent
from `zones` and `structure`; the exception left `on_bar`, reached Nautilus,
the node exited cleanly and `restart: unless-stopped` brought it back. Each
restart drops the in-memory bracket legs, so a position opened between two of
them runs naked - which is what was found by hand the night before. **One
desk's bug cost thirty desks their stops.**

The containment is deliberately loud. `screening.py` and the refusal gates are
written on the principle that a gate quietly admitting everything reads the
same as one that works; in reverse, a desk refusing every bar because of a
defect must not read as a quiet market.
"""

from __future__ import annotations

from types import SimpleNamespace

from till_infinity.strategies.desk import guarded


class Stub:
    """Enough of a desk for the decorator: a counter and a log."""

    def __init__(self) -> None:
        self.passed_over: dict[str, int] = {}
        self.errors: list[str] = []
        self.log = SimpleNamespace(error=self.errors.append, warning=self.errors.append)
        self.calls = 0

    def _count(self, key: str) -> None:
        self.passed_over[key] = self.passed_over.get(key, 0) + 1

    @guarded("on_bar")
    def boom(self, which: str = "a") -> str:
        self.calls += 1
        raise ValueError(f"broken {which}")

    @guarded("on_bar")
    def fine(self, value: int) -> int:
        self.calls += 1
        return value * 2


def test_a_working_handler_is_untouched():
    """**The control.** A guard that changed the normal path would be worse
    than no guard: every handler on the desk runs through this."""
    stub = Stub()
    assert stub.fine(21) == 42
    assert stub.calls == 1
    assert stub.passed_over == {}
    assert stub.errors == []


def test_a_raising_handler_returns_none_rather_than_propagating():
    """The node survives, which is the whole point: a sizing bug should cost
    one trade, not every open position's protection."""
    stub = Stub()
    assert stub.boom() is None
    assert stub.calls == 1


def test_the_failure_is_counted_under_a_key_no_refusal_uses():
    """`(bug):` separates "broken" from "no signal" in the tally and in
    `tis.sh refusals`. A desk refusing every bar for a defect that read as a
    quiet market is the failure this naming prevents."""
    stub = Stub()
    for _ in range(3):
        stub.boom()
    assert stub.passed_over == {"(bug):on_bar": 3}
    assert all(not key.startswith("(desk)") for key in stub.passed_over)


def test_the_traceback_is_logged_once_per_distinct_message():
    """**A per-bar traceback across a 38-desk book buries every other line**,
    which is what the 13 restarts did to the log. So the first occurrence of
    each distinct message carries its traceback and repeats are counted only -
    and a *different* failure is never swallowed by an earlier one's quota.
    """
    stub = Stub()
    for _ in range(5):
        stub.boom("a")
    assert len(stub.errors) == 1, "a repeat was logged again"
    assert "broken a" in stub.errors[0]
    assert "Traceback" in stub.errors[0], "the traceback is what makes it placeable"
    assert "(bug):on_bar" in stub.errors[0]

    stub.boom("b")
    assert len(stub.errors) == 2, "a new failure was hidden by the first one's quota"
    assert "broken b" in stub.errors[1]
    assert stub.passed_over == {"(bug):on_bar": 6}


def test_every_per_message_handler_on_the_traded_path_is_guarded():
    """The join, because a guard is worth exactly the handlers it is on.

    Checked through `__wrapped__`, which `functools.wraps` sets and nothing
    else here does - so this fails if a decorator is dropped from any one of
    them. An earlier version of this test compared source strings in a way
    that was true whenever the decorator appeared *anywhere* in the class, and
    that is the vacuous shape `CLAUDE.md` says to delete rather than keep.

    `on_start` is deliberately unguarded: a desk that cannot build should fail
    at boot rather than trade half-constructed, and that is a failure a deploy
    gate can see. It is asserted *unwrapped* here, so "guarded everything"
    fails too.
    """
    from till_infinity.strategies import bands, desk, identity, origins, structure, zones

    for owner, name in (
        (desk.Desk, "on_bar"),
        (desk.Desk, "on_data"),
        (desk.Desk, "on_quote_tick"),
        (zones.Zones, "on_bar"),
        (origins.Origins, "on_bar"),
        (structure.Structure, "on_bar"),
        (bands.Bands, "on_bar"),
        (identity.Identity, "on_bar"),
    ):
        fn = owner.__dict__.get(name)
        assert fn is not None, f"{owner.__name__}.{name} is not defined there any more"
        assert hasattr(fn, "__wrapped__"), f"{owner.__name__}.{name} carries no @guarded"

    on_start = desk.Desk.__dict__.get("on_start")
    assert on_start is not None
    assert not hasattr(on_start, "__wrapped__"), "on_start must fail loudly, not be contained"


def test_the_decorator_is_what_sets_wrapped_so_the_join_above_can_fail():
    """The control for the control: an undecorated method has no `__wrapped__`,
    so the check above is not satisfied by every function in the module."""

    class Plain:
        def bare(self) -> None:
            return None

    assert not hasattr(Plain.__dict__["bare"], "__wrapped__")
    assert hasattr(Stub.__dict__["boom"], "__wrapped__")
