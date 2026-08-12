"""In-memory MPMC channel — bounded or unbounded.

Thin asyncio.Queue wrapper with close semantics matching Rust
async-channel: once closed, sends raise ChannelClosed and pending
receives drain the buffer then raise.
"""

from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

from .backbone import Channel, Receiver, Sender
from .errors import ChannelClosed, ChannelEmpty, ChannelFull

T = TypeVar("T")


class MemoryChannel(Channel[T], Generic[T]):
    def __init__(self, capacity: int | None = None) -> None:
        # capacity=0 would block forever — treat as unbounded
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=capacity or 0)
        self._closed = False
        self._capacity = capacity

    async def send(self, message: T) -> None:
        if self._closed:
            raise ChannelClosed("cannot send on closed channel")
        await self._queue.put(message)

    def try_send(self, message: T) -> None:
        if self._closed:
            raise ChannelClosed("cannot send on closed channel")
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull as e:
            raise ChannelFull("channel is full") from e

    async def recv(self) -> T:
        while True:
            if not self._queue.empty():
                return self._queue.get_nowait()
            if self._closed:
                raise ChannelClosed("channel is closed and empty")
            # Wait for something to arrive — or the channel to close.
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except TimeoutError:
                continue

    def try_recv(self) -> T:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty as e:
            if self._closed:
                raise ChannelClosed("channel is closed and empty") from e
            raise ChannelEmpty("channel is empty") from e

    async def close(self) -> None:
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed

    def len(self) -> int:
        return self._queue.qsize()


def bounded(capacity: int) -> tuple[Sender[T], Receiver[T]]:
    """Create a bounded in-memory channel with the given capacity."""
    if capacity <= 0:
        raise ValueError("capacity must be > 0 (use unbounded() for no limit)")
    return MemoryChannel[T](capacity).split()


def unbounded() -> tuple[Sender[T], Receiver[T]]:
    """Create an unbounded in-memory channel."""
    return MemoryChannel[T](None).split()
