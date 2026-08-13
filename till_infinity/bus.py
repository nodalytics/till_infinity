"""The message bus: how services talk to each other.

Collectors publish what they just stored, agents consume it and publish alerts,
notifications consume those. The SQLite stores stay the source of truth — the
bus carries *notice that something happened*, not the data itself, so a dropped
message costs latency rather than history.

    prices  ──┐                        ┌──▶ notifications
              ├──▶ bus ──▶ agents ──▶ bus
    news    ──┘

Backed by `till_infinity.channels`: in-memory by default, Redis Streams when a
URL is set — the same in-process-or-shared choice `--store` offers.

**Publishing fans out per subscriber group.** A channel's `recv()` is
work-sharing: two consumers of one channel split the messages between them
rather than each seeing all of them. That is right for scaling one consumer
across workers and wrong for two different services watching the same topic, so
each group gets its own channel and `publish()` writes to every one. It matches
Redis consumer-group semantics, which is what the Redis backend gives for free.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from .channels import ChannelClosed, ChannelFull, Receiver, Sender, bounded, redis_channel
from .logging import get_logger

log = get_logger(__name__)

#: What collectors announce.
BARS = "prices.bars"
QUOTES = "prices.quotes"
ARTICLES = "news.articles"
EVENTS = "news.events"
MACRO = "news.macro"
#: What the online models found. Agents consume it as evidence; an unambiguous
#: one goes straight to ALERTS without waiting for a model to agree.
SIGNALS = "structures.signals"
#: What agents ask for. Notifications is the consumer.
ALERTS = "alerts"
#: Decisions and their reasoning, on their way to the journal. Any service can
#: publish here; `journal listen` is what writes them down.
JOURNAL = "journal"

TOPICS: tuple[str, ...] = (BARS, QUOTES, ARTICLES, EVENTS, MACRO, SIGNALS, ALERTS, JOURNAL)

DEFAULT_CAPACITY = 1_000
DEFAULT_GROUP = "default"


@dataclass(frozen=True, slots=True)
class Message:
    """One announcement. `payload` is small and JSON-safe by construction."""

    topic: str
    payload: dict[str, Any]
    source: str = ""
    time: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "payload": self.payload,
            "source": self.source,
            "time": self.time,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Message | None:
        """Rebuild from the wire. Returns None rather than raising on junk."""
        if not isinstance(raw, dict) or not raw.get("topic"):
            return None
        payload = raw.get("payload")
        return cls(
            topic=str(raw["topic"]),
            payload=payload if isinstance(payload, dict) else {},
            source=str(raw.get("source") or ""),
            time=float(raw.get("time") or time.time()),
        )


class Bus:
    """Topic-addressed publish/subscribe over channels.

    A publisher that nobody subscribes to is a no-op, which is what makes the
    seam free: collectors call `publish()` unconditionally and pay nothing
    until an agent is listening.
    """

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        capacity: int = DEFAULT_CAPACITY,
        namespace: str = "till",
    ) -> None:
        self.redis_url = redis_url
        self.capacity = capacity
        self.namespace = namespace
        #: (topic, group) -> the channel that group reads
        self._channels: dict[tuple[str, str], tuple[Sender[Any], Receiver[Any]]] = {}
        self._closed = False

    @property
    def backend(self) -> str:
        return "redis" if self.redis_url else "memory"

    def key(self, topic: str) -> str:
        """The Redis stream name. One stream per topic — groups read it in parallel."""
        return f"{self.namespace}:{topic}"

    def _channel(self, topic: str, group: str) -> tuple[Sender[Any], Receiver[Any]]:
        existing = self._channels.get((topic, group))
        if existing is not None:
            return existing
        if self.redis_url:
            # Redis consumer groups already fan out: one group per subscriber.
            pair = redis_channel(self.key(topic), group=group, url=self.redis_url)
        else:
            pair = bounded(self.capacity)
        self._channels[(topic, group)] = pair
        return pair

    def groups(self, topic: str) -> list[str]:
        return [g for (t, g) in self._channels if t == topic]

    async def publish(self, topic: str, payload: dict[str, Any], *, source: str = "") -> int:
        """Announce something. Returns how many subscriber groups received it."""
        if self._closed:
            return 0
        message = Message(topic=topic, payload=payload, source=source)
        sent = 0
        for group in self.groups(topic):
            sender, _ = self._channel(topic, group)
            try:
                # try_send, not send: a slow consumer must never stall a
                # collector. A full channel drops the notice; the store keeps
                # the data, so the consumer can still catch up by querying.
                sender.try_send(message.to_dict())
                sent += 1
            except ChannelFull:
                log.warning("bus: %s full, dropped a message for %s", topic, group)
            except Exception as exc:  # a dead subscriber is not the publisher's problem
                log.warning("bus: publish to %s/%s failed: %s", topic, group, exc)
        return sent

    def subscribe(self, topic: str, group: str = DEFAULT_GROUP) -> Subscription:
        """Register a group's interest. Messages published from now on arrive."""
        self._channel(topic, group)
        return Subscription(self, topic, group)

    async def receive(self, topic: str, group: str = DEFAULT_GROUP) -> Message | None:
        _, receiver = self._channel(topic, group)
        raw = await receiver.recv()
        return Message.from_dict(raw)

    async def close(self) -> None:
        self._closed = True
        for sender, _ in self._channels.values():
            # Sender.close is a coroutine — awaiting it is what actually wakes
            # blocked receivers with ChannelClosed and ends their iteration.
            with suppress(Exception):
                await sender.close()
        self._channels.clear()


@dataclass(slots=True)
class Subscription:
    """One group's view of one topic — an async iterator of messages."""

    bus: Bus
    topic: str
    group: str = DEFAULT_GROUP

    def __aiter__(self) -> AsyncIterator[Message]:
        return self._messages()

    async def _messages(self) -> AsyncIterator[Message]:
        while True:
            try:
                message = await self.bus.receive(self.topic, self.group)
            except ChannelClosed:
                return
            if message is not None:
                yield message

    async def next(self) -> Message | None:
        return await self.bus.receive(self.topic, self.group)
