"""The alert sink as a Nautilus Actor, against the framework's own classes.

**The actor had no tests at all**, and two defects lived in it for that reason.
The first is the one `utils/topics.py` is shaped around: `on_start` called
`self.subscribe_data_dict`, a method Nautilus does not have. The second only a
real bus could find - publishing `{"title": "x", "level": "critical"}`, which
is what `Notification.to_dict` writes and what every trading alarm sends, gave
`tally == {"sent": 0, "dropped": 0, "prepare": 1}`: `int("critical")` raised
`ValueError`, `on_alert` swallowed it, and the alarm was gone.

A third was in the tally rather than the path. `_emit` discarded what `notify`
returned, so an alert whose every channel reported a dead webhook was counted
as `sent` - the one reading that is supposed to say whether anybody was told.

So every test here publishes through `nautilus_trader`'s own `MessageBus` and
reads what came out of the sender. **Nothing assigns a method to the actor**,
which is what made the first defect invisible: assigning an attribute *creates*
it, so a stub stood in for an API that was never there. The sender is replaced
on the module the actor imports it from, before the actor starts, which is the
same binding production uses.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import json
import pathlib
import threading
from dataclasses import dataclass, field
from typing import Any

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import TestClock
from nautilus_trader.common.config import ActorFactory
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from till_infinity.notifications import Delivery
from till_infinity.notifications.actor import Notifier, NotifierConfig
from till_infinity.utils import effects

PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 200

#: A plausible address that cannot reach anything. No real chat id or webhook
#: goes in this repository.
OPS = "telegram[ops]"


@dataclass
class Sender:
    """A stand-in for `delivery.notify` that records and can be made to fail.

    It returns a list of `Delivery` because that is the contract the actor now
    reads: the version that ignored the return value counted an undelivered
    alert as sent.
    """

    outcome: bool = True
    raises: BaseException | None = None
    seen: list[Any] = field(default_factory=list)
    #: Set when nothing is configured, which is a quiet desk and not a fault.
    nothing_configured: bool = False
    #: Blocks the send until released, for the "off the handler" test.
    hold: threading.Event | None = None
    started: threading.Event = field(default_factory=threading.Event)
    threads: list[str] = field(default_factory=list)

    async def __call__(self, message: Any, **_: Any) -> list[Delivery]:
        self.threads.append(threading.current_thread().name)
        self.started.set()
        if self.hold is not None:
            self.hold.wait(5.0)
        if self.raises is not None:
            raise self.raises
        self.seen.append(message)
        if self.nothing_configured:
            return []
        return [Delivery(OPS, ok=self.outcome, detail="" if self.outcome else "HTTP 404")]


def build(
    monkeypatch: pytest.MonkeyPatch,
    sender: Sender | None = None,
    *,
    clock: Any = None,
    start: bool = True,
    **config: Any,
) -> tuple[Notifier, Any, Sender]:
    """A registered actor on a real `MessageBus`, the bus, and its sender.

    `minimum_level=0` by default so a test about one gate is not silently
    decided by another one.
    """
    sender = sender or Sender()
    monkeypatch.setattr("till_infinity.notifications.notify", sender)
    config.setdefault("minimum_level", 0)
    actor = Notifier(NotifierConfig(**config))
    msgbus = TestComponentStubs.msgbus()
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=msgbus,
        cache=TestComponentStubs.cache(),
        clock=clock or TestComponentStubs.clock(),
    )
    if start:
        actor.start()
    return actor, msgbus, sender


def alert(**kw: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"title": "live: AutoTrading is off", "level": "critical"}
    payload.update(kw)
    return payload


# ------------------------------------------------------- the framework's shapes


def test_the_actor_can_be_built_from_a_node_config(monkeypatch):
    """A `TradingNodeConfig` carries an `ImportableActorConfig`, not an actor.

    `node/live.py::_actors` constructs instances today, which works for a live
    node assembled in Python and not for a serialised backtest run config. An
    actor whose config cannot round-trip through `ActorFactory` can go in
    neither, and the failure shows up as a config the node cannot load rather
    than as anything in this package.
    """
    original = Notifier(NotifierConfig(topics=("alerts",), minimum_level=2, degrade_after=7))
    rebuilt = ActorFactory.create(original.to_importable_config())
    assert isinstance(rebuilt, Notifier)
    assert rebuilt._cfg.minimum_level == 2
    assert rebuilt._cfg.degrade_after == 7
    assert rebuilt._cfg.topics == ("alerts",)


@pytest.mark.parametrize(
    "hook",
    ["on_start", "on_stop", "on_reset", "on_dispose", "on_resume", "on_degrade"],
)
def test_the_lifecycle_hooks_are_the_frameworks_own(hook):
    """Asserted on `Actor`, so a plausible name we invented cannot pass.

    This is the shape that bit three modules: `subscribe_data_dict` reads like
    a framework method and is not one. A hook we define that Nautilus does not
    call is the same defect - code that is enabled, correct and reached by
    nothing.
    """
    assert hasattr(Actor, hook), f"Actor has no {hook}: nothing would call ours"
    assert hook in vars(Notifier), f"{hook} is not overridden here"


def test_saved_state_is_the_shape_nautilus_persists(monkeypatch):
    """`dict[str, bytes]`, and **anything else is silently not saved** - no
    exception, no warning, just a cooldown window that is empty on every boot.

    Asserted on an actor that has something to save. The version of this test
    before it looped over the state of a *fresh* actor, which is `{}` by
    design, so the loop body never ran and the shape was never checked at all.
    `on_save` is declared on `Actor` and not invented here, which is the half
    a type claim cannot cover.
    """
    assert hasattr(Actor, "on_save")
    assert hasattr(Actor, "on_load")

    unstarted = Notifier(NotifierConfig())
    assert unstarted.on_save() == {}, "nothing to save before a start"

    actor, msgbus, _sender = build(monkeypatch, dedupe_seconds=600.0)
    msgbus.publish(topic="alerts", msg=alert(fields={"shape": "trade", "instrument": "gold"}))
    state = actor.on_save()
    assert state, "a sent alert leaves a cooldown window to persist"
    for key, value in state.items():
        assert isinstance(key, str)
        assert isinstance(value, bytes)


def test_the_node_owns_the_clock_cache_and_bus(monkeypatch):
    """Read-only on the Cython class, which is why tests pass arguments.

    Worth asserting rather than remembering: a test that *could* replace
    `actor.cache` would be testing a parallel copy of the engine's state, and
    the whole reason to read from `self.cache` is that there is only one.
    """
    actor, _bus, _sender = build(monkeypatch)
    for name in ("cache", "clock", "log", "msgbus", "portfolio"):
        with pytest.raises(AttributeError):
            setattr(actor, name, None)


def test_nothing_in_the_actor_sleeps_or_starts_a_thread():
    """A source scan, because absence is what is being asserted.

    A rate limit implemented as `asyncio.sleep` blocks the node's loop, and
    one implemented on a thread of our own is invisible to the kernel's
    shutdown. Both windows here are read off `self.clock` when a message
    arrives, which is also the only version that behaves in a backtest.
    """
    source = (
        pathlib.Path(__file__).resolve().parent.parent
        / "till_infinity"
        / "notifications"
        / "actor.py"
    ).read_text()
    for banned in ("asyncio.sleep", "time.sleep", "threading.", "Thread("):
        assert banned not in source, f"{banned} in notifications/actor.py"


def test_the_subscription_is_registered_on_nautilus_own_bus(monkeypatch):
    """A stub cannot satisfy this: the subscription is read back off
    `MessageBus.subscriptions`, which only `msgbus.subscribe` writes to.

    `subscribe_data_dict` would have raised here, and the test that was
    supposed to cover it assigned the name instead - which creates it.
    """
    actor, msgbus, _sender = build(monkeypatch)
    handlers = [sub.handler for sub in msgbus.subscriptions("alerts")]
    assert handlers == [actor._handlers["alerts"]]


def test_a_restart_does_not_subscribe_twice(monkeypatch):
    """**The handlers are built in `__init__` for this reason.**

    `msgbus.subscribe` deduplicates on `(topic, handler, priority)`, and a
    fresh `functools.partial` is never equal to the last one - so building the
    handler inside `on_start` meant a stop/start cycle left two subscriptions
    and every later alert went out twice.

    `resume`, not a second `start`, because the framework's table has no
    `STOPPED -> START`: a stopped component comes back with `RESUME`. Which is
    why `on_resume` is declared - the inherited one logs a warning saying
    resume is not implemented, on a path whose entire job is to be quiet
    until something matters.
    """
    actor, msgbus, sender = build(monkeypatch)
    actor.stop()
    actor.resume()
    assert actor.is_running
    assert len(msgbus.subscriptions("alerts")) == 1
    msgbus.publish(topic="alerts", msg=alert())
    assert len(sender.seen) == 1


def test_the_cooldown_runs_on_the_node_clock(monkeypatch):
    """The reason the window is not a timer, and the reason it is not
    `time.time()`.

    A cooldown measured against the wall clock inside a 2019 replay is a
    window that never closes, so every alert in the backtest looks like the
    first of its kind and a repeat-suppression study measures nothing. Here
    the clock is moved and the same finding becomes sendable again.
    """
    clock = TestClock()
    clock.set_time(1_700_000_000_000_000_000)
    _actor, msgbus, sender = build(monkeypatch, clock=clock, dedupe_seconds=600.0)

    msgbus.publish(topic="alerts", msg=alert())
    msgbus.publish(topic="alerts", msg=alert())
    assert len(sender.seen) == 1, "the repeat is inside the cooldown"

    clock.set_time(clock.timestamp_ns() + 601 * 1_000_000_000)
    msgbus.publish(topic="alerts", msg=alert())
    assert len(sender.seen) == 2


# ----------------------------------------------------------------- the message


def test_an_alert_whose_level_is_a_word_is_delivered(monkeypatch):
    """The measured defect. `int("critical")` raised, `on_alert` counted a
    prepare failure, and the tally read `{"sent": 0, "dropped": 0,
    "prepare": 1}` - for the exact payload every trading alarm publishes and
    `Notification.to_dict` writes."""
    _actor, msgbus, sender = build(monkeypatch, dedupe_seconds=0.0)
    msgbus.publish(topic="alerts", msg=alert(level="critical"))
    msgbus.publish(topic="alerts", msg=alert(title="b", level="CRITICAL"))
    msgbus.publish(topic="alerts", msg=alert(title="c", level=2))
    assert [m.title for m in sender.seen] == ["live: AutoTrading is off", "b", "c"]
    assert all(int(m.level) == 2 for m in sender.seen)


def test_an_unreadable_level_still_reaches_someone(monkeypatch):
    """A publisher that misspells its level is a bug in the publisher.

    Losing the alarm over it would be this package's bug, and the failure this
    package exists around is alerts discarded in silence. It arrives as
    `WARNING`: INFO would be dropped by any channel configured for warnings
    and up, and claiming CRITICAL on the strength of a typo is crying wolf.

    `minimum_level=1` is production's own setting, so this is the gate the
    live actor applies and not a lenient one chosen for the test.
    """
    from till_infinity.notifications.models import Level

    _actor, msgbus, sender = build(monkeypatch, minimum_level=1)
    msgbus.publish(topic="alerts", msg=alert(level="criticl"))
    assert [m.level for m in sender.seen] == [Level.WARNING]


def test_the_alert_arrives_whole(monkeypatch):
    """`from_message`, not a hand-built `Notification`.

    The hand-built one carried title, body, level and source and dropped
    `fields`, `url` and `image` - so an alert's instrument, its link and its
    chart never left the bus, and the untrusted-payload checks on the picture
    had no caller at all.
    """
    _actor, msgbus, sender = build(monkeypatch)
    msgbus.publish(
        topic="alerts",
        msg=alert(
            body="nine hours of rejected orders",
            fields={"instrument": "gold", "shape": "trade"},
            url="https://example.com/x",
            at=1787059920.0,
            image={"name": "chart.png", "data": base64.b64encode(PNG).decode()},
        ),
    )
    (message,) = sender.seen
    assert message.fields == {"instrument": "gold", "shape": "trade"}
    assert message.url == "https://example.com/x"
    assert message.body == "nine hours of rejected orders"
    assert message.image == PNG
    assert message.at == 1787059920.0
    # Nautilus's bus carries no source, so the topic is the nearest true thing.
    assert message.source == "alerts"


def test_a_message_with_no_title_is_dropped(monkeypatch):
    """An empty alert is worse than none: it occupies the channel and says
    nothing, and `from_message` returns `None` for one anyway."""
    _actor, msgbus, sender = build(monkeypatch)
    msgbus.publish(topic="alerts", msg={"level": "critical", "body": "x"})
    assert sender.seen == []


def test_an_alert_below_the_minimum_level_is_dropped(monkeypatch):
    """An alert per event is an alert nobody reads."""
    _actor, msgbus, sender = build(monkeypatch, minimum_level=2)
    msgbus.publish(topic="alerts", msg=alert(level="warning"))
    assert sender.seen == []


# -------------------------------------------------------------- not the desk


def test_a_telegram_outage_does_not_halt_the_desk(monkeypatch):
    """The handler is on the path that decides trades.

    A sender that raises inside a bus handler takes the handler down with it,
    and then the next alert - and in a node, whatever else that dispatch was
    going to do. So the exception is counted, the component stays usable, and
    the following alert still goes out. An alert is worth less than the desk
    it is about.
    """
    actor, msgbus, sender = build(monkeypatch, dedupe_seconds=0.0)
    sender.raises = RuntimeError("telegram is unreachable")

    msgbus.publish(topic="alerts", msg=alert(title="first"))
    assert actor.tally["RuntimeError"] == 1
    assert actor.is_running

    sender.raises = None
    msgbus.publish(topic="alerts", msg=alert(title="second"))
    assert [m.title for m in sender.seen] == ["second"]


def test_a_payload_that_is_not_a_dict_is_counted_rather_than_raised(monkeypatch):
    """Another service wrote it, so nothing here trusts its shape."""
    actor, msgbus, _sender = build(monkeypatch)
    msgbus.publish(topic="alerts", msg="not a payload")
    assert actor.tally["prepare"] == 1
    assert actor.is_running


async def test_the_send_happens_off_the_handler_thread(monkeypatch):
    """Telegram is a network call of unknown duration.

    `queue_for_executor` and a *sync* `_deliver`, which is why `_deliver` was
    changed from a coroutine: `Actor` has no `create_task` - that is on
    `LiveExecutionClient` - and the executor a live kernel registers is a
    `ThreadPoolExecutor`, so a blocking send belongs on it. This test holds the
    send open and asserts the handler has already returned, on a different
    thread.
    """
    sender = Sender(hold=threading.Event())
    actor, msgbus, sender = build(monkeypatch, sender, start=False)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        actor.register_executor(asyncio.get_running_loop(), pool)
        actor.start()
        msgbus.publish(topic="alerts", msg=alert())
        # The handler has returned - we are running again - while the send is
        # still inside `hold.wait`.
        for _ in range(200):
            if sender.started.is_set():
                break
            await asyncio.sleep(0.01)
        assert sender.started.is_set(), "the send never reached the executor"
        assert actor.tally["sent"] == 0, "the handler waited for the send to finish"
        assert sender.threads[0] != threading.current_thread().name, (
            "the send ran on the thread that dispatches the message bus"
        )
    finally:
        if sender.hold is not None:
            sender.hold.set()
        pool.shutdown(wait=True)


# ------------------------------------------------------- saying it is broken


def test_an_alert_that_reached_nobody_is_not_counted_as_sent(monkeypatch):
    """`_emit` used to discard what `notify` returned.

    So an alert whose every channel answered "HTTP 404 unknown webhook" was
    tallied as `sent`, and the only reading that says whether anybody was told
    said yes. A silent alerting path looks exactly like a quiet market.
    """
    actor, msgbus, sender = build(monkeypatch, dedupe_seconds=0.0)
    sender.outcome = False
    msgbus.publish(topic="alerts", msg=alert())
    assert actor.tally["sent"] == 0
    assert actor.tally["undelivered"] == 1


def test_sustained_failure_degrades_the_actor_and_recovery_resumes_it(monkeypatch):
    """`degrade()`, not a swallowed exception and not `fault()`.

    DEGRADED is how a component says it has stopped working, and it is
    visible to anything watching component state - which a counter inside this
    object is not. `fault()` is deliberately not used: FAULTED is where a
    component goes when the node should stop trusting it, and a desk that
    halts because Telegram is down has the priority backwards.

    The transition happens on the next handler call rather than inside the
    send, because the send runs on a pool thread and the component state
    machine is the node's.
    """
    actor, msgbus, sender = build(monkeypatch, dedupe_seconds=0.0, degrade_after=2)
    sender.outcome = False
    for n in range(3):
        msgbus.publish(topic="alerts", msg=alert(title=f"t{n}"))
    assert actor.is_degraded
    assert not actor.is_running

    sender.outcome = True
    msgbus.publish(topic="alerts", msg=alert(title="back"))
    msgbus.publish(topic="alerts", msg=alert(title="back again"))
    assert actor.is_running
    assert not actor.is_degraded


def test_a_desk_with_no_channel_configured_is_quiet_rather_than_degraded(monkeypatch):
    """`notify` returns no deliveries when nothing is set up, and that is a
    choice somebody made rather than a fault. Degrading on it would mean every
    node without a Telegram token reported a broken alerting path."""
    actor, msgbus, sender = build(monkeypatch, dedupe_seconds=0.0, degrade_after=1)
    sender.nothing_configured = True
    for n in range(3):
        msgbus.publish(topic="alerts", msg=alert(title=f"t{n}"))
    assert actor.tally == {"sent": 0, "dropped": 3}
    assert actor.is_running


def test_an_alert_arriving_while_the_actor_is_stopped_is_not_sent(monkeypatch):
    """The subscription is the bus's, not a data engine's.

    So nothing checks the component's state before calling the handler, and a
    stopped actor would go on delivering - which on a stop/start is how one
    alert becomes two.
    """
    actor, msgbus, sender = build(monkeypatch)
    actor.stop()
    msgbus.publish(topic="alerts", msg=alert())
    assert sender.seen == []
    assert actor.tally["dropped"] == 1


def test_the_delivered_effect_fires_on_the_bus_path(monkeypatch):
    """A feature that is on and reached by nothing is the shape
    `utils/effects.py` exists for, and this path is the instance that wrote it:
    every trading alarm was dropped before delivery for weeks and nothing said
    so. The declaration is on the actor and not on `delivery.notify`, because a
    firing from a hand-written call would not mean the bus path works."""
    before = effects.report()["notifications.delivered"]["count"]
    _actor, msgbus, _sender = build(monkeypatch)
    msgbus.publish(topic="alerts", msg=alert())
    assert effects.report()["notifications.delivered"]["count"] == before + 1


# ------------------------------------------------------------ across a restart


def test_the_cooldown_window_survives_a_restart(monkeypatch):
    """A node that restart-loops forgets what it has already said.

    It then sends the same alarm on every boot, which is how an alerting
    channel becomes one people mute - the failure the cooldown exists for,
    arriving by a different road.
    """
    actor, msgbus, sender = build(monkeypatch, dedupe_seconds=600.0)
    msgbus.publish(topic="alerts", msg=alert(fields={"shape": "trade", "instrument": "gold"}))
    assert len(sender.seen) == 1
    state = actor.on_save()
    assert json.loads(state["dedupe"].decode())[0][:2] == ["trade", "gold"]

    revived, bus, fresh = build(monkeypatch, dedupe_seconds=600.0, start=False)
    revived.on_load(state)
    revived.start()
    bus.publish(topic="alerts", msg=alert(fields={"shape": "trade", "instrument": "gold"}))
    assert fresh.seen == [], "the restarted node re-sent an alarm it had already sent"


def test_an_unreadable_saved_window_does_not_stop_the_actor_starting(monkeypatch):
    """One repeated alert is the cost of an unreadable state file. Refusing to
    start is the cost of treating it as fatal, and a node that cannot start is
    a desk that cannot trade."""
    actor, msgbus, sender = build(monkeypatch, start=False)
    actor.on_load({"dedupe": b"{not json"})
    actor.start()
    msgbus.publish(topic="alerts", msg=alert())
    assert len(sender.seen) == 1
    assert actor.is_running


def test_the_cooldown_memory_is_bounded(monkeypatch):
    """A long-running node must not grow a dict forever.

    The version this replaced kept its own `self._seen` of alert *titles* with
    no bound at all, so a node up for a month held every title it had ever
    sent. `Filter` caps its memory at `MEMORY`, and this asserts the actor
    uses that memory rather than a second one beside it.
    """
    from till_infinity.notifications.filters import MEMORY

    monkeypatch.setenv("NOTIFY_MAX_PER_HOUR", "0")  # the hourly cap is a different test
    actor, msgbus, _sender = build(monkeypatch, dedupe_seconds=600.0)
    for n in range(MEMORY + 100):
        msgbus.publish(topic="alerts", msg=alert(fields={"ref": str(n)}))
    assert len(actor._filter._sent) == MEMORY
    assert not hasattr(actor, "_seen")


def test_a_delivery_is_reported_and_not_only_counted(monkeypatch):
    """**A successful send logged nothing.**

    `_record` counts it and returns; only a failure logs. `on_stop` reports
    the tally and a live desk never stops. So sent, dropped and failed were
    indistinguishable from each other and from no alert at all - and on
    2026-11-06 one statespace proposal produced no log line anywhere, with no
    way to tell whether Telegram had been told or the filter refused it first.
    """
    from till_infinity.notifications.actor import tally_reading

    actor, msgbus, _sender = build(monkeypatch, dedupe_seconds=0.0)
    msgbus.publish(topic="alerts", msg=alert())

    assert actor.tally["sent"] == 1
    said = tally_reading(actor.tally["sent"], actor.tally["dropped"], {})
    assert said is not None, "the delivery was silent"
    line, urgent = said
    assert "1 sent" in line
    assert urgent is False


def test_alerts_refused_before_any_destination_are_a_warning():
    """The case worth seeing: the desk raised something and nobody was told.

    An alert dropped by the filter never reaches a destination, so no failure
    is recorded and the tally reads zero sent - which is exactly how
    `NOTIFY_SHAPES` once discarded every statespace alert while the path
    itself worked.
    """
    from till_infinity.notifications.actor import tally_reading

    said = tally_reading(0, 3, {})

    assert said is not None
    line, urgent = said
    assert urgent is True
    assert "refused before a destination" in line


def test_a_quiet_desk_says_nothing():
    """The control. Reporting every five minutes on a desk that raised no
    alert would make the tally the log rather than a reading in it."""
    from till_infinity.notifications.actor import tally_reading

    assert tally_reading(0, 0, {}) is None
