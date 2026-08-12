"""Backbone — abstract channel interface.

All channel backends (in-memory, Redis, etc.) implement this protocol.
Users generally create channels via the top-level helpers (bounded,
unbounded, redis_channel) and interact with Sender/Receiver halves.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Generic, TypeVar

T = TypeVar("T")


class Backbone(ABC, Generic[T]):
    """Low-level transport — a single backbone services many channels."""

    @abstractmethod
    async def send(self, channel: str, message: T) -> None: ...

    @abstractmethod
    async def recv(self, channel: str) -> T: ...

    @abstractmethod
    def try_send(self, channel: str, message: T) -> None: ...

    @abstractmethod
    def try_recv(self, channel: str) -> T: ...

    @abstractmethod
    async def close(self, channel: str) -> None: ...

    @abstractmethod
    def is_closed(self, channel: str) -> bool: ...

    @abstractmethod
    def len(self, channel: str) -> int: ...


class Sender(Generic[T]):
    """Send half of a channel."""

    def __init__(self, channel: "Channel[T]") -> None:
        self._channel = channel

    async def send(self, message: T) -> None:
        await self._channel.send(message)

    def try_send(self, message: T) -> None:
        self._channel.try_send(message)

    async def close(self) -> None:
        await self._channel.close()

    @property
    def is_closed(self) -> bool:
        return self._channel.is_closed

    def __len__(self) -> int:
        return self._channel.len()


class Receiver(Generic[T]):
    """Receive half of a channel."""

    def __init__(self, channel: "Channel[T]") -> None:
        self._channel = channel

    async def recv(self) -> T:
        return await self._channel.recv()

    def try_recv(self) -> T:
        return self._channel.try_recv()

    @property
    def is_closed(self) -> bool:
        return self._channel.is_closed

    def __len__(self) -> int:
        return self._channel.len()

    def __aiter__(self) -> AsyncIterator[T]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[T]:
        from .errors import ChannelClosed
        while True:
            try:
                yield await self.recv()
            except ChannelClosed:
                return


class Channel(ABC, Generic[T]):
    """Full-duplex channel object — source of Sender / Receiver pairs."""

    @abstractmethod
    async def send(self, message: T) -> None: ...

    @abstractmethod
    async def recv(self) -> T: ...

    @abstractmethod
    def try_send(self, message: T) -> None: ...

    @abstractmethod
    def try_recv(self) -> T: ...

    @abstractmethod
    async def close(self) -> None: ...

    @property
    @abstractmethod
    def is_closed(self) -> bool: ...

    @abstractmethod
    def len(self) -> int: ...

    def split(self) -> tuple[Sender[T], Receiver[T]]:
        """Return (sender, receiver) handles sharing this channel."""
        return Sender(self), Receiver(self)
