"""An in-memory `Carrier`, for tests that exercise publish and subscribe.

**Written when `bus.py` was retired**, so the twenty-three tests that drove a
service through its transport kept their coverage. They were testing the
services' behaviour - what gets published, in what shape, on which topic - and
none of that was about the bus. They named `Bus` because it was the only
carrier there was.

Deliberately simple, and deliberately *not* a reimplementation. It satisfies
`till_infinity.carrier.Carrier` and nothing else: no capacity, no drops, no
groups fanning out over a stream. A test that needs those is testing a
transport, and the transport is Nautilus's now.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from till_infinity.carrier import Message


class _Subscription:
    """One group's view of one topic, backed by a queue."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[Message] = asyncio.Queue()
        self._closed = False

    def __aiter__(self) -> AsyncIterator[Message]:
        return self._messages()

    async def _messages(self) -> AsyncIterator[Message]:
        while True:
            message = await self.next()
            if message is None:
                return
            yield message

    async def next(self) -> Message | None:
        if self._closed and self.queue.empty():
            return None
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=0.25)
        except TimeoutError:
            return None if self._closed else await self.next()

    def close(self) -> None:
        self._closed = True


class FakeCarrier:
    """Publishes to whoever subscribed, and remembers everything.

    `published` is the point: a test asserts on the shape a service put on the
    wire, which is what the contract tests check against the JSON schemas.
    """

    def __init__(self, **_ignored: Any) -> None:
        self._subs: dict[tuple[str, str], _Subscription] = {}
        #: Every message, in order, whether anybody was listening.
        self.published: list[Message] = []
        self._closed = False

    async def publish(self, topic: str, payload: dict[str, Any], *, source: str = "") -> int:
        if self._closed:
            return 0
        message = Message(topic=topic, payload=payload, source=source)
        self.published.append(message)
        sent = 0
        for (subject, _group), sub in self._subs.items():
            if subject == topic:
                sub.queue.put_nowait(message)
                sent += 1
        return sent

    def subscribe(self, topic: str, group: str = "default") -> _Subscription:
        return self._subs.setdefault((topic, group), _Subscription())

    def groups(self, topic: str) -> list[str]:
        return [g for (t, g) in self._subs if t == topic]

    async def receive(self, topic: str, group: str = "default") -> Message | None:
        return await self.subscribe(topic, group).next()

    async def close(self) -> None:
        self._closed = True
        for sub in self._subs.values():
            sub.close()

    @property
    def backend(self) -> str:
        return "fake"

    def key(self, topic: str) -> str:
        return f"till:{topic}"

    def payloads(self, topic: str) -> list[dict[str, Any]]:
        """Just the payloads on one topic, which is what most tests want."""
        return [m.payload for m in self.published if m.topic == topic]
