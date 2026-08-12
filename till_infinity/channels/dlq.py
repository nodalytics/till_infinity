"""Dead Letter Queue — catch poison messages after max retries.

After a message has been retried `max_attempts` times without success,
it gets shunted to the DLQ instead of infinitely blocking the outbox.
Operators can inspect the DLQ and decide whether to re-queue or drop.

Reuses the SQLite outbox schema (with channel suffixed "-dlq").
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .persistent import Outbox

logger = logging.getLogger(__name__)


class DeadLetterQueue:
    """Quarantine for messages that have failed too many times."""

    def __init__(self, path: str | Path, channel_name: str) -> None:
        self._store = Outbox(path, f"{channel_name}-dlq")
        self.channel_name = channel_name

    def park(self, message: Any, last_error: str = "") -> int:
        """Move a poison message to the DLQ."""
        logger.warning(
            "[channels] message parked in DLQ channel=%s error=%s",
            self.channel_name,
            last_error,
        )
        return self._store.stash(message, last_error)

    def list(self, limit: int = 100) -> list[tuple[int, Any]]:
        return self._store.peek(limit)

    def requeue(self, ids: list[int]) -> int:
        """Remove IDs from the DLQ (caller is responsible for re-sending)."""
        return self._store.ack(ids)

    def size(self) -> int:
        return self._store.pending_count()
