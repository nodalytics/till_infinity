"""Persistent storage — SQLite outbox underneath Redis.

Design: the persistent layer sits BELOW the primary backend as a
durable write-ahead log. It is not normally read from — it catches
writes that failed to reach the primary and replays them later.

Flow (send):
    1. Attempt primary.send(msg)
    2. If that succeeds, we're done
    3. If the primary raises (network down, Redis restart, etc.), stash
       the message in SQLite so it isn't lost
    4. A background replay task drains the SQLite buffer back to the
       primary when it recovers

Flow (recv):
    - Receives go straight through the primary (Redis Streams)
    - SQLite is not consulted on recv — it's a send-side safety net

This gives you Redis's read performance with local-disk
durability underneath, so a restart or transient outage doesn't drop
messages.

Usage:
    from channels import redis_channel
    tx, rx = redis_channel("market:ticks", persistent_path="/var/lib/terminal/outbox.db")

The persistent_path parameter on redis_channel()
wraps those channels with this outbox.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Outbox:
    """SQLite-backed durable outbox for failed primary sends.

    Thread-safe via a single connection in WAL mode. Methods are sync;
    callers are expected to run I/O in an executor if needed.
    """

    def __init__(self, path: str | Path, channel_name: str) -> None:
        self.path = str(path)
        self.channel = channel_name
        self._conn: sqlite3.Connection | None = None
        self._ready = False

    def _ensure(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        if not self._ready:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    ts REAL NOT NULL,
                    payload TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_outbox_channel_ts
                ON outbox(channel, ts)
            """)
            self._ready = True
        self._conn = conn
        return conn

    def stash(self, message: Any, error: str = "") -> int:
        conn = self._ensure()
        cur = conn.execute(
            "INSERT INTO outbox(channel, ts, payload, last_error) VALUES (?, ?, ?, ?)",
            (self.channel, time.time(), json.dumps(message, default=str), error),
        )
        return int(cur.lastrowid or 0)

    def peek(self, limit: int = 100) -> list[tuple[int, Any]]:
        conn = self._ensure()
        cur = conn.execute(
            "SELECT id, payload FROM outbox WHERE channel = ? ORDER BY ts LIMIT ?",
            (self.channel, limit),
        )
        return [(row[0], json.loads(row[1])) for row in cur.fetchall()]

    def ack(self, ids: list[int]) -> int:
        if not ids:
            return 0
        conn = self._ensure()
        placeholders = ",".join("?" * len(ids))
        cur = conn.execute(
            f"DELETE FROM outbox WHERE id IN ({placeholders})", ids,
        )
        return cur.rowcount

    def mark_attempt(self, ids: list[int], error: str) -> None:
        if not ids:
            return
        conn = self._ensure()
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE outbox SET attempts = attempts + 1, last_error = ? "
            f"WHERE id IN ({placeholders})",
            [error, *ids],
        )

    def pending_count(self) -> int:
        conn = self._ensure()
        cur = conn.execute(
            "SELECT COUNT(*) FROM outbox WHERE channel = ?", (self.channel,),
        )
        (n,) = cur.fetchone()
        return int(n)


class DurableSender:
    """Wraps a primary Sender with SQLite outbox durability.

    On send failure, messages are stashed locally. A background replay
    coroutine drains the outbox whenever the primary is reachable.
    After max_attempts retries, messages are parked in the DLQ.

    Accepts optional backoff policy and metrics hook.
    """

    def __init__(
        self,
        primary,                        # type: ignore[no-untyped-def]
        outbox: Outbox,
        replay_interval: float = 5.0,
        backoff=None,                   # BackoffPolicy or None → default
        dlq=None,                       # DeadLetterQueue or None
        max_attempts: int = 10,
        metrics=None,                   # MetricsHook or None → default
        channel_name: str | None = None,
    ) -> None:
        from .backoff import DEFAULT_BACKOFF
        from .metrics import get_default_metrics
        self._primary = primary
        self._outbox = outbox
        self._replay_interval = replay_interval
        self._backoff = backoff or DEFAULT_BACKOFF
        self._dlq = dlq
        self._max_attempts = max_attempts
        self._metrics = metrics or get_default_metrics()
        self._channel_name = channel_name or getattr(outbox, "channel", "unknown")
        self._replay_task: asyncio.Task | None = None

    async def send(self, message: Any) -> None:
        import time
        t0 = time.perf_counter()
        try:
            await self._primary.send(message)
            self._metrics.send(self._channel_name, time.perf_counter() - t0)
        except Exception as e:
            self._metrics.error(self._channel_name, "send", str(e))
            self._metrics.stash(self._channel_name)
            logger.warning("[channels] primary send failed, stashing to outbox: %s", e)
            await asyncio.get_event_loop().run_in_executor(
                None, self._outbox.stash, message, str(e),
            )
            self._ensure_replay()

    def try_send(self, message: Any) -> None:
        try:
            self._primary.try_send(message)
        except Exception as e:
            self._metrics.error(self._channel_name, "try_send", str(e))
            self._metrics.stash(self._channel_name)
            logger.warning("[channels] primary try_send failed, stashing: %s", e)
            self._outbox.stash(message, str(e))

    async def close(self) -> None:
        await self._primary.close()
        if self._replay_task:
            self._replay_task.cancel()

    @property
    def is_closed(self) -> bool:
        return self._primary.is_closed

    def __len__(self) -> int:
        return len(self._primary) + self._outbox.pending_count()

    # ──── replay loop ────
    def _ensure_replay(self) -> None:
        if self._replay_task is None or self._replay_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._replay_task = loop.create_task(self._replay_loop())
            except RuntimeError:
                pass

    async def _replay_loop(self) -> None:
        loop = asyncio.get_event_loop()
        attempt = 0
        while True:
            pending = await loop.run_in_executor(None, self._outbox.peek, 100)
            if not pending:
                return
            drained: list[int] = []
            for row_id, payload in pending:
                try:
                    await self._primary.send(payload)
                    drained.append(row_id)
                    attempt = 0  # reset on success
                except Exception as e:
                    # Check attempt count; if over max, park in DLQ
                    attempts_now = await loop.run_in_executor(
                        None, self._attempt_count, row_id,
                    )
                    if attempts_now >= self._max_attempts:
                        if self._dlq is not None:
                            await loop.run_in_executor(
                                None, self._dlq.park, payload, str(e),
                            )
                            drained.append(row_id)  # remove from outbox
                            logger.warning(
                                "[channels] parked to DLQ after %d attempts: %s",
                                attempts_now, e,
                            )
                        else:
                            # No DLQ configured — leave in outbox, skip
                            await loop.run_in_executor(
                                None, self._outbox.mark_attempt, [row_id], str(e),
                            )
                    else:
                        await loop.run_in_executor(
                            None, self._outbox.mark_attempt, [row_id], str(e),
                        )
                    break  # stop on first failure — primary is flaky
            if drained:
                await loop.run_in_executor(None, self._outbox.ack, drained)
                self._metrics.drain(self._channel_name, len(drained))
                logger.info("[channels] drained %d messages from outbox", len(drained))
            await asyncio.sleep(self._backoff.delay(attempt))
            attempt += 1

    def _attempt_count(self, row_id: int) -> int:
        conn = self._outbox._ensure()
        cur = conn.execute(
            "SELECT attempts FROM outbox WHERE id = ?", (row_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


def wrap_with_outbox(
    sender,
    path: str | Path,
    channel_name: str,
    dlq: bool | "DeadLetterQueue" = False,
    max_attempts: int = 10,
    backoff=None,
    metrics=None,
):
    """Decorate a Sender with a persistent outbox underneath.

    Args:
        sender:        the primary Sender to wrap
        path:          SQLite file for the outbox
        channel_name:  used to namespace outbox/DLQ rows
        dlq:           True → auto-create DLQ at same path,
                       or pass a DeadLetterQueue instance, or False to skip
        max_attempts:  how many retries before parking in DLQ
        backoff:       BackoffPolicy for replay spacing (default: exponential)
        metrics:       MetricsHook (default: process-wide default)
    """
    outbox = Outbox(path, channel_name)
    dlq_obj = None
    if dlq is True:
        from .dlq import DeadLetterQueue
        dlq_obj = DeadLetterQueue(path, channel_name)
    elif dlq is not False and dlq is not None:
        dlq_obj = dlq
    return DurableSender(
        sender, outbox,
        backoff=backoff,
        dlq=dlq_obj,
        max_attempts=max_attempts,
        metrics=metrics,
        channel_name=channel_name,
    )
