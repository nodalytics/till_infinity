"""Alerts out, as a Nautilus Actor.

A sink, which is why this is an Actor and not an adapter: adapters bring
external data *in* and this takes our own events *out*. There is no
`ExecutionClient` for Telegram.

**It must not be able to stop the node.** A notifier that raises inside a
handler takes the handler down with it, and the handler is on the path that
decides trades - so every send is wrapped, every failure is counted, and a
destination that is down produces a tally rather than an exception. An alert
is worth less than the desk it is about. That is also why delivery failure
reaches `degrade()` and never `fault()`: DEGRADED is where a component says it
has stopped working, and a desk that halts because Telegram is down has the
priority backwards.

**Sending is not awaited on the hot path.** Telegram is a network call of
unknown duration and Actor handlers run in the node's event loop, so a send
is scheduled and the handler returns. `notifications.delivery.notify` already
retries with backoff; this does not reimplement that.

**Nothing here sleeps or starts a thread.** The cooldown and the hourly
ceiling are read off `self.clock` when a message arrives rather than counted
down by a timer, which is what makes them behave in a backtest: a window
measured against `time.time()` inside a 2019 replay is a window that never
closes, and every alert looks like the first of its kind.

**This replaced `notifications/service.py:listen`**, retired to
`research/retire/notifications/` on 2026-11-01. What the loop did besides
looping came here rather than retiring with it - `Filter`, `from_message` and
the `notifications.delivered` effect - because each one was the only thing
standing between a trading alarm and nobody reading it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig

from till_infinity.utils import effects, topics

if TYPE_CHECKING:
    from .filters import Filter
    from .models import Delivery

#: Levels, mirroring `notifications.models.Level` without importing it at
#: module scope - the package is a separate concern and an Actor that cannot
#: be constructed without it is harder to test than it needs to be.
INFO, WARNING, CRITICAL = 0, 1, 2

#: Always on. Every trading alarm this desk raised was dropped before delivery
#: for weeks, and nothing said so. Declared where the per-alert path runs,
#: which is here: `delivery.notify` is also callable by hand, so a firing
#: there would not mean the bus path works.
effects.declare("notifications.delivered", enabled=True)

#: The `on_save` key holding the cooldown window.
STATE_DEDUPE = "dedupe"


class NotifierConfig(ActorConfig, frozen=True):
    """What to send, and what not to.

    Every field is a scalar or a tuple of them, so the config survives
    `ImportableActorConfig` - a `TradingNodeConfig` carries an importable
    config and not an instance, and an actor that can only be built by hand
    cannot go in one.

    `minimum_level` exists because an alert per event is an alert nobody
    reads. The bus carries a notice per touched bar; a person wants the ones
    that change what they would do.
    """

    topics: tuple[str, ...] = ("alerts",)
    minimum_level: int = WARNING
    #: Drop a repeat of the same finding within this many seconds. A feed that
    #: has stopped produces one alert per poll otherwise, which is how an
    #: alerting channel becomes something people mute.
    #:
    #: This sets `Filter.cooldown`, and overrides `NOTIFY_COOLDOWN_S`, because
    #: a node that assembles the actor should not also have to set an
    #: environment variable to say how quiet it wants to be. One memory rather
    #: than two: this actor used to keep its own title-keyed `_seen` dict
    #: beside the filter's own, which is two answers to one question - and the
    #: dict had no bound, so a node running for a month held every alert title
    #: it had ever sent.
    dedupe_seconds: float = 300.0
    #: Consecutive alerts where **no** channel accepted delivery before the
    #: actor degrades. Three rather than one: `send_one` already retries a
    #: transient failure, so one undelivered alert is a provider having a bad
    #: minute and three in a row is a path that is down.
    degrade_after: int = 3


class Notifier(Actor):
    """Subscribes to our own topics and sends what passes the filters."""

    def __init__(self, config: NotifierConfig) -> None:
        super().__init__(config)
        self._cfg = config
        self._sent = 0
        self._dropped = 0
        self._failed: dict[str, int] = {}
        #: Alerts in a row that reached nobody. Drives `degrade`/`resume`.
        self._undelivered = 0
        self._send: Callable[[Any], Any] | None = None
        self._filter: Filter | None = None
        #: One bound handler per topic, built once. **`msgbus.subscribe`
        #: deduplicates on `(topic, handler, priority)` and a fresh
        #: `partial` is never equal to the last one**, so building these in
        #: `on_start` meant a stop/start cycle subscribed twice and every
        #: later alert was delivered twice.
        self._handlers: dict[str, Callable[[Any], None]] = {
            topic: partial(self.on_alert, topic) for topic in config.topics
        }

    # ------------------------------------------------------------- lifecycle

    def on_start(self) -> None:
        # Imported here: a node that sends nowhere should still start, and a
        # missing destination configuration is not a reason the desk cannot
        # trade.
        from . import Filter, Settings, notify

        # The credentials are read once and bound to the sender. `notify`
        # reads the environment itself when it is handed nothing, which on
        # this path meant one parse per alert - and with `TELEGRAM_AUTO_CHATS`
        # set, one extra `getUpdates` round trip per alert, because discovery
        # caches into the `Settings` object it was given and that object was
        # thrown away each time.
        self._send = partial(notify, settings=Settings.from_env())
        # The delivery policy `listen` carried. It is here rather than
        # reimplemented because `Filter` is what lets a `critical` past the
        # shape and instrument gates, and those gates silently discarded every
        # trading alarm this desk raised until 2026-09-12.
        if self._filter is None:  # `on_load` may have restored one already
            self._filter = replace(Filter.from_env(), cooldown=self._cfg.dedupe_seconds)
        self.log.info(f"notifications: accepting {self._filter.describe()}")
        for topic in self._cfg.topics:
            # `topics.subscribe` is `msgbus.subscribe`. The first version
            # called `self.subscribe_data_dict`, **which is not a Nautilus
            # method** - this actor would have raised on start, and nothing
            # caught it because nothing started one.
            #
            # The bus hands the handler the payload alone, so the topic is
            # bound into the handler rather than passed.
            topics.subscribe(self, topic, self._handlers[topic])
            self.log.info(f"notifying on {topic}")

    def on_stop(self) -> None:
        """Say what was done with the alerts.

        The subscription is left in place. It belongs to the bus rather than
        to a data engine, so nothing unsubscribes it on our behalf - and
        `on_alert` refuses to deliver unless the component is running or
        degraded, which is the same guard an engine would apply and does not
        depend on a stop hook having run.
        """
        self.log.info(
            f"notifications: {self._sent} sent, {self._dropped} dropped"
            + (f", failures {self._failed}" if self._failed else "")
        )

    def on_resume(self) -> None:
        """Nothing to redo.

        The subscription survived the degrade - the actor kept receiving and
        kept trying, which is how it noticed delivery had come back. Declared
        rather than inherited because the inherited one logs a warning saying
        resume is not implemented, and an alerting path that warns about
        itself every time it recovers is noise over the thing it is for.
        """

    def on_degrade(self) -> None:
        """Nothing to tear down; `_reconcile` has already said why."""

    def on_reset(self) -> None:
        """Forget the tally and the cooldown window.

        A reset is "pretend this never ran", and a window kept across one
        would suppress the first alert of the next run for up to
        `dedupe_seconds`.
        """
        self._sent = 0
        self._dropped = 0
        self._undelivered = 0
        self._failed.clear()
        self._filter = None

    def on_dispose(self) -> None:
        """Nothing to release.

        Deliberate, and the reason is the design: `notify` opens an
        `httpx.AsyncClient` per send and closes it in the same `async with`,
        so this actor owns no socket, no session and no thread. The executor
        it queues onto is the kernel's and the kernel disposes of it.
        """

    # ----------------------------------------------------------- persistence

    def on_save(self) -> dict[str, bytes]:
        """The cooldown window, so a restart is not a reason to re-alert.

        A node that restart-loops forgets what it has already said and sends
        the same alarm on every boot, which is how an alerting channel becomes
        one people mute - the failure the cooldown exists for, arriving by a
        different road.

        JSON of plain rows rather than a packed dataclass, which is the point
        worth keeping: `utils/codec.py` keys persisted state on module
        basename plus class name, so persisting `Filter` would put
        `filters.Filter` in the schema and an entry in `ALIASES` the day this
        file moves. Nothing here names a class, so nothing needs one.

        The tally is not saved. It answers "what has this run done", and a
        counter that survives a restart cannot say whether the process did.
        """
        if self._filter is None:
            return {}
        rows = [[*key, when] for key, when in self._filter._sent.items()]
        return {STATE_DEDUPE: json.dumps(rows).encode()}

    def on_load(self, state: dict[str, bytes]) -> None:
        """Restore the cooldown window written by `on_save`.

        Never raises. A state file this cannot read is a reason to start with
        an empty window - which costs one repeated alert - and not a reason
        the node cannot start.
        """
        from collections import OrderedDict

        from . import Filter

        raw = state.get(STATE_DEDUPE)
        if not raw:
            return
        try:
            rows = json.loads(raw.decode())
            window = OrderedDict(
                (tuple(str(part) for part in row[:-1]), float(row[-1])) for row in rows
            )
        except (ValueError, TypeError, IndexError, AttributeError) as exc:
            self.log.warning(f"notifications: could not read the saved cooldown window: {exc}")
            return
        self._filter = replace(Filter.from_env(), cooldown=self._cfg.dedupe_seconds, _sent=window)
        self.log.info(f"notifications: restored {len(window)} finding(s) in the cooldown window")

    # -------------------------------------------------------------- delivery

    def on_alert(self, topic: str, payload: dict[str, Any]) -> None:
        """One bus message. Never raises, whatever the payload looks like."""
        try:
            self._reconcile()
            if not (self.is_running or self.is_degraded):
                # Still subscribed while stopped: this subscription is the
                # bus's own rather than a data engine's, so nothing else
                # checks the component's state before calling us.
                self._dropped += 1
                return
            if not self._wanted(payload):
                self._dropped += 1
                return
            self._schedule(topic, payload)
        except Exception as exc:
            self._failed["prepare"] = self._failed.get("prepare", 0) + 1
            self.log.warning(f"notifications: could not prepare an alert: {exc}")

    def _reconcile(self) -> None:
        """Make the component state say whether delivery is working.

        **On the bus thread, not in `_deliver`.** `_deliver` runs on the
        kernel's `ThreadPoolExecutor`, and a component state transition from a
        pool thread is a write to the node's own state machine that nothing
        else is synchronised against. The counter is written there and read
        here, which is the one direction that is safe.

        `degrade`, never `fault`. FAULTED is where a component goes when the
        node should stop trusting it; a dead Telegram webhook is not that, and
        DEGRADED leaves the actor running - which is what lets it notice that
        delivery came back.
        """
        if self._undelivered >= self._cfg.degrade_after and self.is_running:
            self.log.error(f"notifications: {self._undelivered} alert(s) reached nobody")
            self.degrade()
        elif self._undelivered == 0 and self.is_degraded:
            self.log.info("notifications: delivery recovered")
            self.resume()

    def _wanted(self, payload: dict[str, Any]) -> bool:
        """Decided on the handler, in arrival order.

        The filters are stateful - a cooldown and an hourly ceiling - so they
        run where the messages are still ordered, and only the send goes to
        the executor.
        """
        if not str(payload.get("title") or "").strip():
            return False
        if self._level(payload) < self._cfg.minimum_level:
            return False
        # Interest, repeats and the hourly ceiling, on the clock the node is
        # running on: `Filter` falls back to `time.time()`, which in a
        # backtest is the wrong decade and makes every alert the first one.
        return self._filter is None or self._filter.accept(payload, when=self._clock_seconds())

    def _level(self, payload: dict[str, Any]) -> int:
        """The payload's level as a number.

        **The bus carries the level as a word, not an integer.**
        `Notification.to_dict` writes `"level": "CRITICAL"` and every trading
        alarm publishes `"critical"`, so the `int(payload["level"])` this used
        to do raised `ValueError` on every real alert. Measured against a
        started actor on a real `MessageBus`: publishing `{"title": "x",
        "level": "critical"}` gave `tally == {"sent": 0, "dropped": 0,
        "prepare": 1}` - the alarm counted as a parsing failure and gone.

        `models.read_level` and not `Level.parse`, and the same call
        `from_message` makes, so this gate and the message that gets built
        cannot disagree about what a payload says. The first fix was here
        alone, and an unreadable level then passed this gate and raised
        `ValueError` inside `from_message` on the executor instead: the drop
        moved one method along and the tally changed from `prepare` to
        `ValueError`.
        """
        from .models import read_level

        return int(read_level(payload.get("level")))

    def _clock_seconds(self) -> float:
        return self.clock.timestamp_ns() / 1e9

    def _schedule(self, topic: str, payload: dict[str, Any]) -> None:
        """Hand the send to the executor so the handler returns immediately.

        **`queue_for_executor`, not `create_task`.** `Actor` has no
        `create_task` - that is on `LiveExecutionClient` - so the first version
        of this would have raised `AttributeError` on the first alert. The
        executor takes a *sync* callable and runs it sequentially, which is why
        `_deliver` is not a coroutine: a send that blocks for an unknown time
        belongs off the event loop either way, and the executor is where
        Nautilus puts that work.

        In a backtest it runs immediately, which is the right behaviour - a
        measurement should not depend on whether an alert was delivered. A
        live kernel registers a `ThreadPoolExecutor` before it starts the
        actors, so in production the send is on a pool thread with no event
        loop of its own, which is what makes `_emit`'s `asyncio.run` safe.
        """
        if self._send is None:
            return
        self.queue_for_executor(self._deliver, (topic, payload))

    def _deliver(self, topic: str, payload: dict[str, Any]) -> None:
        """Build the notification and send it. Off the handler's thread.

        `from_message` rather than a hand-built `Notification`, which is the
        gap this closed: the hand-built one carried title, body, level and
        source and dropped `fields`, `url` and `image` on the floor - so an
        alert's instrument, its link and its chart never left the bus, and the
        untrusted-payload checks on the picture had no caller.
        """
        from . import from_message

        try:
            message = from_message(payload)
            if message is None:  # pragma: no cover - `_wanted` requires a title
                return
            message = replace(
                message,
                # The event's own time where the payload carries one. A
                # delivery delayed by a retry would otherwise be stamped with
                # the retry rather than the event.
                at=float(payload.get("at") or self._clock_seconds()),
                # `listen` took this from the bus message's own source;
                # Nautilus's bus does not carry one, so the topic is the
                # nearest true thing and beats an empty string.
                source=message.source or topic,
            )
            self._record(self._emit(message))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._note(type(exc).__name__, str(exc))

    def _record(self, deliveries: list[Delivery]) -> None:
        """Count what the fan-out actually achieved.

        **It used to count the attempt.** `_emit` discarded `notify`'s return
        value, so an alert whose every channel reported a dead webhook landed
        in the tally as `sent` - the reading that is supposed to say whether
        anybody was told said yes, and `degrade` could never trip.
        """
        if not deliveries:
            # No channel is configured, or none takes this level. A desk with
            # no Telegram set up is deliberately quiet rather than broken, so
            # this is a drop and not a failure.
            self._dropped += 1
            return
        if any(d.ok for d in deliveries):
            self._sent += 1
            self._undelivered = 0
            effects.fired("notifications.delivered")
            return
        self._note("undelivered", "; ".join(d.detail for d in deliveries if d.detail))

    def _note(self, kind: str, detail: str) -> None:
        """Record a failure, loudly the first time and rarely after that."""
        self._undelivered += 1
        self._failed[kind] = self._failed.get(kind, 0) + 1
        # Counted and logged occasionally rather than per failure: a
        # destination that is down would otherwise fill the log with the same
        # line, which is the pattern the cooldown exists to avoid.
        if self._failed[kind] in (1, 10, 100) or self._failed[kind] % 100 == 0:
            self.log.warning(f"notifications: {self._failed[kind]} failure(s) of {kind}: {detail}")

    @property
    def tally(self) -> dict[str, int]:
        """Sent, dropped and failed - the reading a report wants."""
        return {"sent": self._sent, "dropped": self._dropped, **self._failed}

    def _emit(self, message: object) -> list[Delivery]:
        """Send one notification, awaiting the sender if it is a coroutine.

        The destinations are async - a webhook is a network call - and the
        executor is sync, so the coroutine is driven here. `asyncio.run` rather
        than a shared loop, because this runs on an executor thread that has no
        loop of its own and a loop borrowed from the node would be the node's
        loop doing a blocking network call.
        """
        import inspect

        sent = self._send(message)  # type: ignore[misc]
        if inspect.isawaitable(sent):
            sent = asyncio.run(sent)
        return list(sent or [])
