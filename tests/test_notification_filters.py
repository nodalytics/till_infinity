"""What reaches a channel, and what is quietly dropped."""

from __future__ import annotations

import pytest

from till_infinity.notifications import Filter
from till_infinity.notifications.filters import DEFAULT_MAX_PER_HOUR


def alert(shape: str = "level", instrument: str = "gold", venue: str = "consensus") -> dict:
    return {
        "title": f"{instrument} {shape}",
        "fields": {"shape": shape, "instrument": instrument, "venue": venue},
    }


def test_nothing_configured_lets_everything_through():
    """The default must not be a filter nobody asked for."""
    passing = Filter()
    assert passing.accept(alert("stale", "btc"))
    assert passing.accept(alert("spread", "eurusd"))
    assert passing.accept(alert("level", "gold"))


def test_a_shape_allowlist_drops_the_shapes_not_named():
    only_levels = Filter(shapes=frozenset({"level"}))
    assert only_levels.accept(alert("level"))
    assert not only_levels.accept(alert("stale"))
    assert not only_levels.accept(alert("spread"))


def test_an_instrument_allowlist_drops_the_rest():
    metals = Filter(feeds=frozenset({"gold"}))
    assert metals.accept(alert(instrument="gold"))
    assert not metals.accept(alert(instrument="eurusd"))


def test_an_alert_with_no_instrument_survives_an_instrument_allowlist():
    """A filter on instruments must not silently eat things that have none."""
    metals = Filter(feeds=frozenset({"gold"}))
    assert metals.accept({"title": "agents are down", "fields": {"shape": "health"}})


def test_the_same_finding_is_suppressed_inside_the_cooldown():
    """A stale feed is one situation, not one per second."""
    quiet = Filter(cooldown=900)
    assert quiet.accept(alert("stale", "btc"), when=0.0)
    assert not quiet.accept(alert("stale", "btc"), when=60.0)
    assert not quiet.accept(alert("stale", "btc"), when=899.0)
    assert quiet.accept(alert("stale", "btc"), when=901.0)


def test_the_cooldown_is_per_finding_not_global():
    quiet = Filter(cooldown=900)
    assert quiet.accept(alert("level", "gold"), when=0.0)
    assert quiet.accept(alert("level", "btc"), when=1.0)
    assert quiet.accept(alert("stale", "gold"), when=2.0)
    assert not quiet.accept(alert("level", "gold"), when=3.0)


def test_the_hourly_ceiling_holds_whatever_else_got_through():
    capped = Filter(cooldown=0, max_per_hour=3)
    for n in range(3):
        assert capped.accept(alert("level", f"sym{n}"), when=float(n))
    assert not capped.accept(alert("level", "late"), when=4.0)


def test_the_ceiling_rolls_rather_than_resetting_on_the_hour():
    """An hour from each alert, not a bucket that empties at :00."""
    capped = Filter(cooldown=0, max_per_hour=2)
    assert capped.accept(alert("level", "a"), when=0.0)
    assert capped.accept(alert("level", "b"), when=100.0)
    assert not capped.accept(alert("level", "c"), when=200.0)
    # The first has aged out; one slot opens, not both.
    assert capped.accept(alert("level", "c"), when=3_601.0)
    assert not capped.accept(alert("level", "d"), when=3_602.0)


def test_a_rejected_alert_does_not_consume_a_slot():
    """Otherwise a shape nobody wants would still crowd out one that is."""
    capped = Filter(shapes=frozenset({"level"}), cooldown=0, max_per_hour=2)
    for n in range(50):
        capped.accept(alert("stale", f"sym{n}"), when=float(n))
    assert capped.accept(alert("level", "gold"), when=100.0)
    assert capped.accept(alert("level", "btc"), when=101.0)
    assert not capped.accept(alert("level", "eurusd"), when=102.0)


def test_rejects_says_why_and_accept_agrees_with_it():
    picky = Filter(shapes=frozenset({"level"}), cooldown=900)
    assert "not in" in picky.rejects(alert("stale"))
    assert picky.rejects(alert("level"), when=0.0) == ""
    picky.accept(alert("level"), when=0.0)
    assert "same finding" in picky.rejects(alert("level"), when=10.0)


def test_rejects_does_not_decide_anything_by_itself():
    """Asking why must not consume the slot the answer describes."""
    capped = Filter(cooldown=0, max_per_hour=1)
    for _ in range(5):
        assert capped.rejects(alert("level"), when=0.0) == ""
    assert capped.accept(alert("level"), when=0.0)


def test_the_memory_of_past_findings_is_bounded():
    """A long-running service must not grow a key per instrument forever."""
    from till_infinity.notifications.filters import MEMORY

    forgetful = Filter(cooldown=1e9, max_per_hour=0)
    for n in range(MEMORY * 2):
        forgetful.accept(alert("level", f"sym{n}"), when=float(n))
    assert len(forgetful._sent) <= MEMORY


def test_falls_back_to_source_when_there_is_no_shape():
    """Agent-written alerts carry a source rather than a structures shape."""
    quiet = Filter(cooldown=900)
    payload = {"title": "gold looks stretched", "source": "agents"}
    assert quiet.accept(payload, when=0.0)
    assert not quiet.accept(payload, when=10.0)


def test_env_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOTIFY_SHAPES", "level, drift")
    monkeypatch.setenv("NOTIFY_FEEDS", "GOLD")
    monkeypatch.setenv("NOTIFY_COOLDOWN_S", "60")
    monkeypatch.setenv("NOTIFY_MAX_PER_HOUR", "5")
    configured = Filter.from_env()
    assert configured.shapes == {"level", "drift"}
    assert configured.feeds == {"gold"}  # case is not the operator's problem
    assert configured.cooldown == 60
    assert configured.max_per_hour == 5


def test_unset_env_is_the_permissive_default(monkeypatch: pytest.MonkeyPatch):
    for name in ("NOTIFY_SHAPES", "NOTIFY_FEEDS", "NOTIFY_COOLDOWN_S", "NOTIFY_MAX_PER_HOUR"):
        monkeypatch.delenv(name, raising=False)
    default = Filter.from_env()
    assert not default.shapes
    assert not default.feeds
    assert default.max_per_hour == DEFAULT_MAX_PER_HOUR
    assert default.accept(alert("anything", "whatever"))


def test_nonsense_env_falls_back_rather_than_crashing(monkeypatch: pytest.MonkeyPatch):
    """A typo in a config value must not take the notifier down on start."""
    monkeypatch.setenv("NOTIFY_MAX_PER_HOUR", "lots")
    monkeypatch.setenv("NOTIFY_COOLDOWN_S", "")
    assert Filter.from_env().max_per_hour == DEFAULT_MAX_PER_HOUR


async def test_the_filter_is_actually_wired_into_the_listener(monkeypatch: pytest.MonkeyPatch):
    """The filter working alone proves nothing if `listen` never calls it."""
    from till_infinity import notifications as nt
    from till_infinity.bus import ALERTS, Bus

    sent: list[str] = []

    async def record(notification, **_kwargs):
        sent.append(notification.title)
        return []

    monkeypatch.setattr(nt.service, "notify", record)

    bus = Bus()
    bus.subscribe(ALERTS, group="notifications")
    for payload in (alert("stale", "btc"), alert("level", "gold"), alert("spread", "eurusd")):
        await bus.publish(ALERTS, payload, source="structures")

    # Bounded by `limit` rather than by closing the bus: a dropped alert does
    # not count toward it, so reaching 1 is itself the assertion that the two
    # either side of it were filtered out.
    handled = await nt.listen(bus, limit=1, alert_filter=Filter(shapes=frozenset({"level"})))
    assert sent == ["gold level"]
    assert handled == 1


async def test_an_unconfigured_listener_still_delivers_everything(monkeypatch: pytest.MonkeyPatch):
    """The wiring must not become a filter by default."""
    from till_infinity import notifications as nt
    from till_infinity.bus import ALERTS, Bus

    for name in ("NOTIFY_SHAPES", "NOTIFY_FEEDS", "NOTIFY_COOLDOWN_S", "NOTIFY_MAX_PER_HOUR"):
        monkeypatch.delenv(name, raising=False)

    sent: list[str] = []

    async def record(notification, **_kwargs):
        sent.append(notification.title)
        return []

    monkeypatch.setattr(nt.service, "notify", record)

    bus = Bus()
    bus.subscribe(ALERTS, group="notifications")
    for shape in ("stale", "level", "spread"):
        await bus.publish(ALERTS, alert(shape, shape), source="structures")

    assert await nt.listen(bus, limit=3) == 3
    assert len(sent) == 3
