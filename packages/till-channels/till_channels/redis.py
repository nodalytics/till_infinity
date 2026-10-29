"""Redis-backed channel - durable, cross-process MPMC.

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

import contextlib
import json
import logging
import os
import uuid
from typing import Any, Generic, TypeVar

from .backbone import Channel
from .errors import ChannelClosed, ChannelEmpty, ChannelFull

T = TypeVar("T")

logger = logging.getLogger(__name__)

#: Where a **brand new** consumer group starts reading.
#:
#: **This was `"0"`, the beginning of the stream, and it replayed history as
#: though it were live.** Measured: a group joining a stream that already held
#: three messages was handed the first one as its first read. For this bus that
#: is wrong in a specific way - a message here is a *notice*, not the data.
#: `prices` says so itself: "a subscriber that hears about a bar can always go
#: and read it." Replaying ten thousand stale notices makes a service act on
#: quotes from hours ago on the day it is deployed.
#:
#: An existing group is unaffected: `xgroup_create` fails for a group that is
#: already there, so a service that restarts resumes from its own
#: last-delivered-id and still catches up on what it missed. Only a group that
#: has never existed skips the backlog, which is exactly the case that should.
NEW_GROUP_STARTS_AT = "$"

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

    # ──── the group anchor ────
    def ensure_group(self) -> None:
        """Create this channel's consumer group **now**, not at first read.

        **`NEW_GROUP_STARTS_AT` is only correct if the group exists by the time
        anything is published.** Group creation used to happen inside
        `_ensure_sync`/`_ensure_async`, so it ran on the first send or receive
        - and a subscriber that registered and then waited had no group in
        Redis at all. Anchored at `$`, the group was created at the stream's
        end *when the reader first called recv*, so everything published
        between `subscribe()` and that first read was never delivered to it.
        The symptom is a test that hangs rather than fails, which is how it was
        found.

        `Bus.subscribe` is synchronous, so this is too: a short-lived client,
        used once and closed, rather than an idle connection held for the life
        of a service that may only ever use the async path.

        Missing Redis is left to the caller's first send or receive, as before -
        this is about *where the group starts*, not about failing early.
        """
        import redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            # Raises if the group already exists, which is the normal case and
            # the one that makes a restart resume where it left off.
            with contextlib.suppress(Exception):
                client.xgroup_create(self.key, self.group, id=NEW_GROUP_STARTS_AT, mkstream=True)
        finally:
            with contextlib.suppress(Exception):
                client.close()

    # ──── lazy connection ────
    def _ensure_sync(self):
        if self._sync_client is not None:
            return self._sync_client
        import redis

        self._sync_client = redis.from_url(self._url, decode_responses=True)
        # Raises if the group already exists, which is the normal case.
        with contextlib.suppress(Exception):
            self._sync_client.xgroup_create(
                self.key,
                self.group,
                id=NEW_GROUP_STARTS_AT,
                mkstream=True,
            )
        return self._sync_client

    async def _ensure_async(self):
        if self._client is not None:
            return self._client
        import redis.asyncio as aioredis

        self._client = aioredis.from_url(self._url, decode_responses=True)
        with contextlib.suppress(Exception):
            await self._client.xgroup_create(
                self.key,
                self.group,
                id=NEW_GROUP_STARTS_AT,
                mkstream=True,
            )
        return self._client

    # ──── send ────
    async def send(self, message: T) -> None:
        if self._closed:
            raise ChannelClosed("cannot send on closed channel")
        client = await self._ensure_async()
        payload = self._encode(message)
        await client.xadd(
            self.key,
            payload,
            maxlen=self.maxlen,
            approximate=True,
        )

    def try_send(self, message: T) -> None:
        if self._closed:
            raise ChannelClosed("cannot send on closed channel")
        client = self._ensure_sync()
        try:
            client.xadd(
                self.key,
                self._encode(message),
                maxlen=self.maxlen,
                approximate=True,
            )
        except Exception as e:
            # Redis streams have no "full" concept but surface as ChannelFull
            raise ChannelFull(str(e)) from e

    # ──── recv ────
    async def recv(self) -> T:
        client = await self._ensure_async()
        while True:
            entries = await client.xreadgroup(
                self.group,
                self.consumer,
                streams={self.key: ">"},
                count=1,
                block=2000,
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
                            maxlen=self.maxlen,
                            approximate=True,
                        )
                        raise ChannelClosed("channel closed")
                    return self._decode(fields)

    def try_recv(self) -> T:
        client = self._ensure_sync()
        entries = client.xreadgroup(
            self.group,
            self.consumer,
            streams={self.key: ">"},
            count=1,
            block=0,
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
                        maxlen=self.maxlen,
                        approximate=True,
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
            self.key,
            {"__ctrl__": _CLOSED_SENTINEL},
            maxlen=self.maxlen,
            approximate=True,
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
        """Every value as JSON, so `_decode` is an exact inverse.

        **Redis stream fields are string -> string, and the previous version
        leaned on `str()` for anything primitive.** That is not reversible.
        `1` came back as `"1"`, `4008.0` as `"4008.0"`, and `None` as `""`;
        worst of all, `False` came back as the string `"False"`, which is
        *truthy*, so a boolean in a payload inverted over Redis while reading
        correctly on the in-process bus. Nothing caught it because the Redis
        path had never been run: the only test constructed a `Bus` and
        asserted on `backend` and `key`.

        JSON for every value costs quotes around strings in `redis-cli` and
        buys an exact round trip for everything JSON can represent. The
        declared bus contracts say `"type": "number"` for prices, so the old
        behaviour did not merely lose types - it produced messages that fail
        their own schema.
        """
        if isinstance(message, dict) and all(isinstance(k, str) for k in message):
            return {k: json.dumps(v) for k, v in message.items()}
        return {"__payload__": json.dumps(message)}

    @staticmethod
    def _decode(fields: dict[str, str]) -> Any:
        if "__payload__" in fields:
            return json.loads(fields["__payload__"])
        out: dict[str, Any] = {}
        for k, v in fields.items():
            if k == "__ctrl__":
                continue
            out[k] = json.loads(v)
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

    See `channels-redis.md` in research/docs.
    """
    channel = RedisChannel[T](key, group, consumer, maxlen, url)
    # Anchor the group before anyone can publish to the stream. See
    # `ensure_group`: deferring this to the first read loses every message
    # sent in between.
    with contextlib.suppress(Exception):
        channel.ensure_group()
    tx, rx = channel.split()
    if persistent_path:
        from .persistent import wrap_with_outbox

        tx = wrap_with_outbox(tx, persistent_path, channel_name=key)
    return tx, rx
