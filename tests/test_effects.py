"""Whether a feature that is switched on has ever actually run.

**Six defects in one week shared one shape**: code that was enabled, correct,
and reached by nothing. Every one passed its own suite, because a test proves
the code computes the right answer and nothing proves it ran. The clearest was
a forecaster deferral that shipped, was verified against a freshly constructed
object, and stayed inert for an afternoon - production **restores** rather than
constructs, and the field it needed came back empty.

This file was deleted on 2026-11-01, in the commit that retired `till_platform`
and moved this module to `till_infinity/utils/effects.py`. Nothing about it had
stopped being true; the one line that stopped working was
`from till_platform import effects`. So the module built to catch features that
are enabled and reached by nothing spent the interval with no test that it does
so, which is the defect it exists for, one level up. `utils/effects.py` still
says in its own docstring that this file asserts the firing paths reach their
declarations - a sentence that was false for as long as the file was gone.

What came back is the ledger: the eleven tests that only ever needed this
module. What did not is the wiring half, for two reasons. Three of its five
subjects retired with `structures/` and `strategies/service.py`, and the two
that remain were asserted with `assert 'declare("x")' in inspect.getsource(mod)`
- which holds for a line that exists and never runs, and is the shape of check
that let an eight-multiplier sizing path stay dead for weeks. The pairing it was
reaching for is below, by parse instead.
"""

from __future__ import annotations

import ast
import pathlib
import time

import pytest

from till_infinity.utils import effects

PACKAGE = pathlib.Path(effects.__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clean():
    effects.reset()
    yield
    effects.reset()


# ----------------------------------------------------------------- the ledger


def test_a_feature_that_is_off_is_never_reported():
    """Off is not a fault, and reporting it would make the list unreadable -
    which is how an alarm stops being read."""
    effects.declare("thing", enabled=False)
    assert effects.inert(grace=0.0) == []


def test_a_feature_that_fires_is_not_inert():
    """The control. Without it, an `inert` that always answered empty would
    satisfy every refusal in this file."""
    effects.declare("thing", enabled=True)
    effects.fired("thing")
    assert effects.inert(grace=0.0) == []
    assert effects.report()["thing"]["count"] == 1


def test_a_feature_that_is_on_and_silent_is_named():
    """The whole purpose, in three lines. The name has to reach the summary
    string too, because that is the part a healthcheck prints and the only
    part anybody reads."""
    effects.declare("thing", enabled=True)
    assert effects.inert(grace=0.0) == ["thing"]
    assert "NEVER FIRED: thing" in effects.summary(grace=0.0)


def test_the_grace_period_keeps_start_up_quiet():
    """Before the grace period, silence is indistinguishable from waiting for a
    first bar - and a feature keyed to a daily bar waits hours. An alarm that
    cries wolf at start-up is one nobody reads."""
    effects.declare("thing", enabled=True)
    assert effects.inert(grace=3600.0) == []
    assert effects.inert(grace=0.0) == ["thing"]


def test_a_feature_that_worked_and_stopped_is_still_visible():
    """The same failure arriving later. `last_s` is what shows it, since the
    count alone says it once worked and nothing about now."""
    effects.declare("thing", enabled=True)
    effects.fired("thing")
    got = effects.report()["thing"]
    assert got["count"] == 1
    assert got["last_s"] is not None
    assert got["first_s"] is not None


def test_declaring_twice_updates_the_flag_and_keeps_the_record():
    """`declare` runs where the flag is read, so it runs repeatedly - once per
    pass through the gate in `risk/guard.py`. Resetting the count there would
    make every feature permanently inert."""
    effects.declare("thing", enabled=False)
    effects.fired("thing")
    effects.declare("thing", enabled=True)
    assert effects.report()["thing"]["count"] == 1, "the firing survives"
    assert effects.report()["thing"]["enabled"] is True


def test_firing_something_undeclared_still_records_it():
    """A call site that forgot to declare must not vanish; the point is to see
    what ran, and a silent drop here would be the bug in the instrument."""
    effects.fired("surprise")
    assert effects.report()["surprise"]["count"] == 1


def test_nothing_here_raises(monkeypatch):
    """A diagnostic that can fail during the fault it describes is worse than
    none. Both calls below would raise on a `None` ledger if the `except` in
    each were removed, and they are on the hot path of a live gate."""
    monkeypatch.setattr(effects, "_EFFECTS", None)  # type: ignore[arg-type]
    effects.declare("thing", enabled=True)
    effects.fired("thing")


def test_the_declared_clock_starts_at_declaration_not_at_first_firing():
    """Which is what makes the grace period mean anything: timed from the first
    firing, a feature that never fires has no age and can never be reported."""
    effects.declare("thing", enabled=True)
    time.sleep(0.01)
    assert effects.report()["thing"]["declared_s"] >= 0.0


def test_the_summary_counts_the_enabled_and_not_the_declared():
    """A disabled feature in the firing count would make the one number an
    operator reads unrelated to what the desk is doing."""
    effects.declare("on", enabled=True)
    effects.declare("off", enabled=False)
    effects.fired("on", 3)
    effects.fired("off", 99)
    assert "1 enabled" in effects.summary(grace=0.0)
    assert "3 firings" in effects.summary(grace=0.0)


def test_reset_clears_the_ledger_so_one_test_cannot_see_another():
    """The ledger is process-wide by design, so without this the autouse
    fixture above would be the only thing keeping these eleven tests
    independent - and a leaked declaration reads as a feature that fired."""
    effects.declare("thing", enabled=True)
    effects.fired("thing")
    effects.reset()
    assert effects.report() == {}


# ------------------------------------------------- the declarations and fires


def _named(attribute: str) -> dict[str, set[str]]:
    """Every `effects.<attribute>("name")` in the package, by literal name.

    Parsed and not matched. A text search for `declare("x"` reads the same
    string out of a docstring explaining the mechanism - which
    `test_journal_actor.ACTOR_TREE` records being caught by, having called a
    paragraph that ruled out `asyncio.sleep` a breach of it.

    Only literal first arguments are collected. A name built at run time would
    be missed, and deliberately: this asserts a pairing between written call
    sites, and a computed name has no written counterpart to pair with.
    """
    found: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != attribute or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.setdefault(first.value, set()).add(
                    path.relative_to(PACKAGE).as_posix(),
                )
    return found


def test_every_declared_effect_has_somewhere_that_fires_it():
    """**A declaration nothing can fire is this defect wearing a badge saying
    it is not.** It reports the feature as never having run, which is true, and
    makes it indistinguishable from a feature that is merely waiting - so the
    one list an operator checks grows an entry that can never clear.

    This is the assertion the retired wiring test was reaching for, held
    across the whole package rather than against a hand-kept roster of five
    module paths. Three entries on that roster had retired with their subjects
    and the test had not noticed.
    """
    declared = _named("declare")
    fired = _named("fired")
    assert declared, "nothing declares an effect, so this asserts nothing"

    orphans = {name: sorted(where) for name, where in declared.items() if name not in fired}
    assert not orphans, f"declared and never fired from anywhere: {orphans}"


def test_every_fired_effect_is_declared_somewhere():
    """The other direction, and the worse one.

    `fired` on an unknown name creates the entry with `enabled=True`, so the
    feature appears in the report the moment it works and is invisible until
    then. That is exactly backwards: the case this module exists to show is
    the feature that never works.
    """
    declared = _named("declare")
    fired = _named("fired")
    assert fired, "nothing fires an effect, so this asserts nothing"

    undeclared = {name: sorted(where) for name, where in fired.items() if name not in declared}
    assert not undeclared, f"fired without being declared anywhere: {undeclared}"


def test_the_pairing_scan_can_tell_a_call_from_a_mention():
    """Power for the two above, and the reason they parse rather than match.

    The string below is what a docstring explaining the mechanism looks like.
    A text search would collect `docs.only` from it and demand a firing path
    for a feature that does not exist.
    """
    mention = ast.parse('"""Call effects.declare("docs.only") where the flag is read."""')
    calls = [
        node
        for node in ast.walk(mention)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert calls == []
    assert "docs.only" not in _named("declare")


# The behavioural half - that each firing path is actually reached when the
# feature does its work - is not here, because it belongs with the subject.
# `test_release_in_hold.test_it_declares_and_fires_its_effect` drives the gate
# and asserts the ledger saw it, which is the model. The other four
# (`notifications.delivered`, `trading.turn_exit`, `trading.spike_switch`,
# `trading.unaffordable_refusal`) have no such test, and the pairing above is
# weaker than one: it proves a firing call is written, not that anything
# reaches it. Noted rather than written, because three of the four live under
# `till_infinity/strategies/` and `till_infinity/risk/`.
