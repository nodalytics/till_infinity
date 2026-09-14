"""Whether a feature that is switched on has ever actually run.

**Six defects in one week shared one shape**: code that was enabled, correct,
and reached by nothing. Every one passed its own suite, because a test proves the
code computes the right answer and nothing proves it ran. The clearest was a
forecaster deferral that shipped, was verified against a freshly constructed
object, and stayed inert for an afternoon - production **restores** rather than
constructs, and the field it needed came back empty.

These tests are about the ledger itself. The wiring tests - that each of the four
sites actually calls `fired` - are at the bottom, and they are the ones that
matter, because a ledger nothing reports to has the same failure as the features
it was built to catch.
"""

from __future__ import annotations

import time

import pytest

from till_infinity.shared import effects


@pytest.fixture(autouse=True)
def clean():
    effects.reset()
    yield
    effects.reset()


def test_a_feature_that_is_off_is_never_reported():
    """Off is not a fault, and reporting it would make the list unreadable -
    which is how an alarm stops being read."""
    effects.declare("thing", enabled=False)
    assert effects.inert(grace=0.0) == []


def test_a_feature_that_fires_is_not_inert():
    effects.declare("thing", enabled=True)
    effects.fired("thing")
    assert effects.inert(grace=0.0) == []
    assert effects.report()["thing"]["count"] == 1


def test_a_feature_that_is_on_and_silent_is_named():
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
    none - `_shout` carries the same note."""
    monkeypatch.setattr(effects, "_EFFECTS", None)  # type: ignore[arg-type]
    effects.declare("thing", enabled=True)
    effects.fired("thing")


def test_the_declared_clock_starts_at_declaration_not_at_first_firing():
    effects.declare("thing", enabled=True)
    time.sleep(0.01)
    assert effects.report()["thing"]["declared_s"] >= 0.0


# --------------------------------------------------- the wiring, which is the
# --------------------------------------------------- part that actually failed


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("till_infinity.structures.engine", "structures.projection"),
        ("till_infinity.trading.service", "trading.reachable_check"),
        ("till_infinity.structures.vol.har", "structures.stated_forecast"),
        ("till_infinity.notifications.service", "notifications.delivered"),
    ],
)
def test_each_site_declares_and_fires(module: str, name: str):
    """Each site must both declare its effect and contain a call that fires it.

    **Static, and deliberately so after a first version was worse.** That one
    called `importlib.reload` to force the declaration to re-run against a reset
    ledger - which replaces the module's classes and breaks identity for every
    test that runs afterwards. It passed alone and took four persistence tests
    down in the full suite, which is a sharper lesson than the one it was
    testing for.

    A source check is the weak half of this discipline and it is not relied on
    alone: `test_har_cj.py` drives a real `Book` and asserts the published
    deferral reaches a restored object, and `test_broker_alarm.py` drives the
    reachability alarm through its own thresholds. This pins that the call sites
    exist and are named consistently; those pin that they run.
    """
    import importlib
    import inspect

    mod = importlib.import_module(module)
    source = inspect.getsource(mod)
    assert f'declare("{name}"' in source, f"{module} does not declare {name}"
    assert f'fired("{name}")' in source, f"{module} never fires {name}"


def test_the_published_deferral_actually_fires_the_ledger(monkeypatch):
    """The behavioural half for the one that shipped inert.

    `structures.stated_forecast` is the effect whose feature was deployed,
    verified against a freshly built object, and reached nothing for an
    afternoon. This drives the real path and asserts the ledger saw it.
    """
    from till_infinity.structures.vol import har as har_mod

    monkeypatch.setattr(har_mod.stated, "ENABLED", True)
    effects.reset()
    model = har_mod.Har(feed="volatility_75_index", interval_seconds=3600.0)
    assert model.published() is not None
    assert effects.report()["structures.stated_forecast"]["count"] >= 1


def test_an_unnamed_feed_does_not_fire_the_deferral(monkeypatch):
    """Firing on a feed that publishes nothing would make the count meaningless
    - it would say the feature ran when it had declined to."""
    from till_infinity.structures.vol import har as har_mod

    monkeypatch.setattr(har_mod.stated, "ENABLED", True)
    effects.reset()
    assert har_mod.Har(feed="gold", interval_seconds=3600.0).published() is None
    assert "structures.stated_forecast" not in effects.report()
