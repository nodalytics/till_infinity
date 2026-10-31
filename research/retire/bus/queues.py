"""A bounded in-process queue, which is all `bus.py` still needs.

**This replaces a 1,133-line transport.** `till-channels` carried Redis
streams, a SQLite outbox and a dead-letter queue, and it is retired to
`research/retire/till-channels` with the four bugs that were found in its
Redis path on the way out. Nautilus owns the bus now - Rust-native, with its
own optional Redis backing - so what remains here serves only the legacy
single-process path, until `stack.py` and the `prices` CLI group go with it.

Deliberately small. `try_send` that drops rather than blocks is the one
behaviour `bus.publish` depends on: a slow consumer must never stall a
collector, because the store keeps the data and the consumer can catch up by
querying. The notice is not the data.
"""

from __future__ import annotations

import asyncio
from typing import Any, Generic, TypeVar

T = TypeVar("T")

#: Default depth. One thousand notices is several minutes of the busiest
#: topic, which is far longer than any consumer should be behind.
DEFAULT_CAPACITY = 1_000


class ChannelClosed(RuntimeError):
    """The channel is closed; no more will arrive."""


class ChannelFull(RuntimeError):
    """The queue is at capacity and the caller asked not to wait."""


class ChannelEmpty(RuntimeError):
    """Nothing to take, and the caller asked not to wait."""


class _Queue(Generic[T]):
    """The shared state behind a sender and a receiver."""

    __slots__ = ("_closed", "_queue")

    def __init__(self, capacity: int) -> None:
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=max(1, capacity))
        self._closed = False

    def try_send(self, item: T) -> None:
        if self._closed:
            raise ChannelClosed("cannot send on a closed channel")
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull as exc:
            raise ChannelFull("channel at capacity") from exc

    async def send(self, item: T) -> None:
        if self._closed:
            raise ChannelClosed("cannot send on a closed channel")
        await self._queue.put(item)

    async def recv(self) -> T:
        while True:
            # **Not a bare `await get()`.** A receiver blocked on an empty
            # queue has to notice a close, and waiting forever on a channel
            # nobody will write to again is how a shutdown hangs rather than
            # ends.
            if self._closed and self._queue.empty():
                raise ChannelClosed("channel closed and empty")
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=0.25)
            except TimeoutError:
                continue

    def try_recv(self) -> T:
        if self._closed and self._queue.empty():
            raise ChannelClosed("channel closed and empty")
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty as exc:
            raise ChannelEmpty("nothing available") from exc

    async def close(self) -> None:
        """Mark it closed. A blocked receiver wakes within the poll interval.

        No sentinel is written, which is the lesson from the package this
        replaces: a close marker in a *shared* stream let one process end
        every reader in every other one, and the reader that saw it
        re-published it so the stream stayed fatal to anyone joining later.
        """
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed

    def __len__(self) -> int:
        return self._queue.qsize()


class Sender(Generic[T]):
    """The write half."""

    __slots__ = ("_channel",)

    def __init__(self, channel: _Queue[T]) -> None:
        self._channel = channel

    def try_send(self, item: T) -> None:
        self._channel.try_send(item)

    async def send(self, item: T) -> None:
        await self._channel.send(item)

    async def close(self) -> None:
        await self._channel.close()

    @property
    def is_closed(self) -> bool:
        return self._channel.is_closed


class Receiver(Generic[T]):
    """The read half."""

    __slots__ = ("_channel",)

    def __init__(self, channel: _Queue[T]) -> None:
        self._channel = channel

    async def recv(self) -> T:
        return await self._channel.recv()

    def try_recv(self) -> T:
        return self._channel.try_recv()

    @property
    def is_closed(self) -> bool:
        return self._channel.is_closed

    def __len__(self) -> int:
        return len(self._channel)


def bounded(capacity: int = DEFAULT_CAPACITY) -> tuple[Sender[Any], Receiver[Any]]:
    """A sender and a receiver over one bounded queue."""
    channel: _Queue[Any] = _Queue(capacity)
    return Sender(channel), Receiver(channel)


def unbounded() -> tuple[Sender[Any], Receiver[Any]]:
    """A very deep bounded queue.

    Not actually unbounded: a queue that cannot refuse hides a consumer that
    has stopped reading until the process runs out of memory, and a drop
    counter is a better signal than an OOM.
    """
    return bounded(1_000_000)
