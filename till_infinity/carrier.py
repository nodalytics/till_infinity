"""What a service needs of a message bus, and nothing more.

**The seam that let `bus.py` be retired without rewriting five services.**
They did not need the bus; they needed something to publish to and subscribe
from, and they annotated it as `Bus` because that was the only one there was.
Stated as a protocol, the same code runs against Nautilus's `MessageBus`
through a thin adapter, against a fake in a test, and against nothing at all.

Two methods, because that is genuinely all of it. A service that needs more
than this from its transport has coupled itself to a transport.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Subscription(Protocol):
    """One group's view of one topic."""

    def __aiter__(self) -> AsyncIterator[Any]: ...

    async def next(self) -> Any | None: ...


@runtime_checkable
class Carrier(Protocol):
    """Somewhere to publish, and something to subscribe to."""

    async def publish(self, topic: str, payload: dict[str, Any], *, source: str = "") -> int: ...

    def subscribe(self, topic: str, group: str = "default") -> Subscription: ...


@dataclass(frozen=True, slots=True)
class Message:
    """One thing that was published, as a subscriber receives it.

    Kept when `bus.py` was retired because it is a *shape* the services pass
    around rather than part of the transport: a topic, a payload and who sent
    it. Nautilus carries its own typed events, and an adapter between the two
    maps this onto them - but a service that only needs these three fields
    should not have to name an engine's type to say so.
    """

    topic: str
    payload: dict[str, Any]
    source: str = ""
    at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "payload": self.payload,
            "source": self.source,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Message:
        return cls(
            topic=str(raw.get("topic") or ""),
            payload=dict(raw.get("payload") or {}),
            source=str(raw.get("source") or ""),
            at=float(raw.get("at") or 0.0),
        )
