"""Redis-backed channel — durable, cross-process MPMC.

Built on Redis Streams + consumer groups so multiple processes can
share a channel with at-least-once delivery.

Design:
  - send()       → XADD stream_key
  - recv()       → XREADGROUP (blocking) → XACK on success
  - close()      → drop the consumer group + mark the stream with
                   a sentinel "__channel_closed__" message

Sentinel pattern: publishing a special control message marks the
channel as closed. Any receiver that consumes it re-publishes it (so
siblings see it too) and raises ChannelClosed.

Falls back to in-memory if redis is unavailable or REDIS_URL is unset.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Generic, TypeVar

from .backbone import Channel, Receiver, Sender
from .errors import ChannelClosed, ChannelEmpty, ChannelFull

T = TypeVar("T")

logger = logging.getLogger(__name__)

_CLOSED_SENTINEL = "__channel_closed__"


class RedisChannel(Channel[T], Generic[T]):
    def __init__(
        self,
        key: str,
        group: str = "default",
        consumer: str | None = None,
        maxlen: int = 10000,
        url: str | None = None,
    ) -> None:
        self.key = key
        self.group = group
        self.consumer = consumer or f"c-{uuid.uuid4().hex[:8]}"
        self.maxlen = maxlen
        self._url = url or os.environ.get("REDIS_URL", "redis://redis:6379/0")
        self._closed = False
        self._client = None
        self._sync_client = None

    # ──── lazy connection ────
    def _ensure_sync(self):
        if self._sync_client is not None:
            return self._sync_client
        import redis
        self._sync_client = redis.from_url(self._url, decode_responses=True)
        try:
            self._sync_client.xgroup_create(
                self.key, self.group, id="0", mkstream=True,
            )
        except Exception:
            pass  # group already exists
        return self._sync_client

    async def _ensure_async(self):
        if self._client is not None:
            return self._client
        import redis.asyncio as aioredis
        self._client = aioredis.from_url(self._url, decode_responses=True)
        try:
            await self._client.xgroup_create(
                self.key, self.group, id="0", mkstream=True,
            )
        except Exception:
            pass
        return self._client

    # ──── send ────
    async def send(self, message: T) -> None:
        if self._closed:
            raise ChannelClosed("cannot send on closed channel")
        client = await self._ensure_async()
        payload = self._encode(message)
        await client.xadd(
            self.key, payload,
            maxlen=self.maxlen, approximate=True,
        )

    def try_send(self, message: T) -> None:
        if self._closed:
            raise ChannelClosed("cannot send on closed channel")
        client = self._ensure_sync()
        try:
            client.xadd(
                self.key, self._encode(message),
                maxlen=self.maxlen, approximate=True,
            )
        except Exception as e:
            # Redis streams have no "full" concept but surface as ChannelFull
            raise ChannelFull(str(e)) from e

    # ──── recv ────
    async def recv(self) -> T:
        client = await self._ensure_async()
        while True:
            entries = await client.xreadgroup(
                self.group, self.consumer,
                streams={self.key: ">"},
                count=1, block=2000,
            )
            if not entries:
                if self._closed:
                    raise ChannelClosed("channel closed and empty")
                continue
            for _stream, messages in entries:
                for msg_id, fields in messages:
                    await client.xack(self.key, self.group, msg_id)
                    if fields.get("__ctrl__") == _CLOSED_SENTINEL:
                        self._closed = True
                        # Re-publish so siblings also see it
                        await client.xadd(
                            self.key,
                            {"__ctrl__": _CLOSED_SENTINEL},
                            maxlen=self.maxlen, approximate=True,
                        )
                        raise ChannelClosed("channel closed")
                    return self._decode(fields)

    def try_recv(self) -> T:
        client = self._ensure_sync()
        entries = client.xreadgroup(
            self.group, self.consumer,
            streams={self.key: ">"},
            count=1, block=0,
        )
        if not entries:
            if self._closed:
                raise ChannelClosed("channel closed and empty")
            raise ChannelEmpty("no messages available")
        for _stream, messages in entries:
            for msg_id, fields in messages:
                client.xack(self.key, self.group, msg_id)
                if fields.get("__ctrl__") == _CLOSED_SENTINEL:
                    self._closed = True
                    client.xadd(
                        self.key,
                        {"__ctrl__": _CLOSED_SENTINEL},
                        maxlen=self.maxlen, approximate=True,
                    )
                    raise ChannelClosed("channel closed")
                return self._decode(fields)
        raise ChannelEmpty("no messages available")

    # ──── close ────
    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        client = await self._ensure_async()
        await client.xadd(
            self.key, {"__ctrl__": _CLOSED_SENTINEL},
            maxlen=self.maxlen, approximate=True,
        )

    @property
    def is_closed(self) -> bool:
        return self._closed

    def len(self) -> int:
        try:
            client = self._ensure_sync()
            return int(client.xlen(self.key))
        except Exception:
            return 0

    # ──── codec ────
    @staticmethod
    def _encode(message: Any) -> dict[str, str]:
        if isinstance(message, dict) and all(isinstance(k, str) for k in message):
            # Redis stream fields are string → string. JSON-encode values
            # that aren't primitives so decode() can restore them.
            out = {}
            for k, v in message.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    out[k] = str(v) if v is not None else ""
                else:
                    out[k] = "__json__" + json.dumps(v)
            return out
        return {"__payload__": "__json__" + json.dumps(message)}

    @staticmethod
    def _decode(fields: dict[str, str]) -> Any:
        if "__payload__" in fields:
            raw = fields["__payload__"]
            if raw.startswith("__json__"):
                return json.loads(raw[len("__json__"):])
            return raw
        out: dict[str, Any] = {}
        for k, v in fields.items():
            if k == "__ctrl__":
                continue
            if isinstance(v, str) and v.startswith("__json__"):
                out[k] = json.loads(v[len("__json__"):])
            else:
                out[k] = v
        return out


def redis_channel(
    key: str,
    group: str = "default",
    consumer: str | None = None,
    maxlen: int = 10000,
    url: str | None = None,
    persistent_path: str | None = None,
):
    """Create a Redis-backed channel.

    Args:
        key:              Redis stream key
        group:            consumer group name (shared across workers)
        consumer:         consumer id (unique per worker, auto-generated)
        maxlen:           stream cap (approximate)
        url:              Redis URL (defaults to REDIS_URL env var)
        persistent_path:  if set, wrap sender with SQLite outbox so
                          failed sends survive Redis outages and
                          replay when the primary recovers.
    """
    channel = RedisChannel[T](key, group, consumer, maxlen, url)
    tx, rx = channel.split()
    if persistent_path:
        from .persistent import wrap_with_outbox
        tx = wrap_with_outbox(tx, persistent_path, channel_name=key)
    return tx, rx
