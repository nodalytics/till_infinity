"""Alerts out, as a Nautilus Actor.

A sink, which is why this is an Actor and not an adapter: adapters bring
external data *in* and this takes our own events *out*. There is no
`ExecutionClient` for Telegram.

**It must not be able to stop the node.** A notifier that raises inside a
handler takes the handler down with it, and the handler is on the path that
decides trades - so every send is wrapped, every failure is counted, and a
destination that is down produces a tally rather than an exception. An alert
is worth less than the desk it is about.

**Sending is not awaited on the hot path.** Telegram is a network call of
unknown duration and Actor handlers run in the node's event loop, so a send
is scheduled and the handler returns. `notifications.service.notify` already
retries with backoff; this does not reimplement that.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig

#: Levels, mirroring `notifications.models.Level` without importing it at
#: module scope - the package is a separate concern and an Actor that cannot
#: be constructed without it is harder to test than it needs to be.
INFO, WARNING, CRITICAL = 0, 1, 2


class NotifierConfig(ActorConfig, frozen=True):
    """What to send, and what not to.

    `minimum_level` exists because an alert per event is an alert nobody
    reads. The bus carries a notice per touched bar; a person wants the ones
    that change what they would do.
    """

    topics: tuple[str, ...] = ("alerts",)
    minimum_level: int = WARNING
    #: Drop a repeat of the same title within this many seconds. A feed that
    #: has stopped produces one alert per poll otherwise, which is how an
    #: alerting channel becomes something people mute.
    dedupe_seconds: float = 300.0


class Notifier(Actor):
    """Subscribes to our own topics and sends what passes the filters."""

    def __init__(self, config: NotifierConfig) -> None:
        super().__init__(config)
        self._cfg = config
        #: title -> when it was last sent
        self._seen: dict[str, float] = {}
        self._sent = 0
        self._dropped = 0
        self._failed: dict[str, int] = {}
        self._send: Callable[[Any], Any] | None = None

    def on_start(self) -> None:
        # Imported here: a node that sends nowhere should still start, and a
        # missing destination configuration is not a reason the desk cannot
        # trade.
        from till_infinity.notifications import notify

        self._send = notify
        for topic in self._cfg.topics:
            self.subscribe_data_dict(topic)
            self.log.info(f"notifying on {topic}")

    def on_stop(self) -> None:
        self.log.info(
            f"notifications: {self._sent} sent, {self._dropped} dropped"
            + (f", failures {self._failed}" if self._failed else "")
        )

    def on_data_dict(self, topic: str, payload: dict[str, Any]) -> None:
        """One bus message. Never raises, whatever the payload looks like."""
        try:
            if not self._wanted(payload):
                self._dropped += 1
                return
            self._schedule(topic, payload)
        except Exception as exc:
            self._failed["prepare"] = self._failed.get("prepare", 0) + 1
            self.log.warning(f"notifications: could not prepare an alert: {exc}")

    def _wanted(self, payload: dict[str, Any]) -> bool:
        level = int(payload.get("level") or INFO)
        if level < self._cfg.minimum_level:
            return False
        title = str(payload.get("title") or "")
        if not title:
            return False
        now = self._clock_seconds()
        last = self._seen.get(title)
        if last is not None and (now - last) < self._cfg.dedupe_seconds:
            return False
        self._seen[title] = now
        return True

    def _clock_seconds(self) -> float:
        return self.clock.timestamp_ns() / 1e9

    def _schedule(self, topic: str, payload: dict[str, Any]) -> None:
        """Hand the send to a task so the handler returns immediately."""
        if self._send is None:
            return
        self.create_task(self._deliver(topic, payload))

    async def _deliver(self, topic: str, payload: dict[str, Any]) -> None:
        from till_infinity.notifications import Level, Notification

        try:
            message = Notification(
                title=str(payload.get("title") or topic),
                body=str(payload.get("body") or payload.get("detail") or ""),
                level=Level(int(payload.get("level") or INFO)),
                source=str(payload.get("source") or topic),
                # The event's own time where the payload carries one. A
                # delivery delayed by a retry would otherwise be stamped with
                # the retry rather than the event.
                at=float(payload.get("at") or self._clock_seconds()),
            )
            await self._send(message)  # type: ignore[misc]
            self._sent += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            kind = type(exc).__name__
            self._failed[kind] = self._failed.get(kind, 0) + 1
            # Counted and logged occasionally rather than per failure: a
            # destination that is down would otherwise fill the log with the
            # same line, which is the pattern `_note_drop` exists to avoid.
            if self._failed[kind] in (1, 10, 100) or self._failed[kind] % 100 == 0:
                self.log.warning(f"notifications: {self._failed[kind]} failure(s) of {kind}: {exc}")

    @property
    def tally(self) -> dict[str, int]:
        """Sent, dropped and failed - the reading a report wants."""
        return {"sent": self._sent, "dropped": self._dropped, **self._failed}
