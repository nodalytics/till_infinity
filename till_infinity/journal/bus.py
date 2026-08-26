"""The journal as a service.

Everything else here talks over the bus, and the journal was the exception: it
was a library each service called in-process, so `agents` and `structures` each
held their own connection to the same SQLite file. That works - WAL tolerates
several writers - but it means only processes on this machine can record
anything, and the writer count grows with the service count.

Publishing entries instead makes the journal an ordinary consumer:

    agents ─────┐
    structures ─┼──▶ journal ──▶ journal listen ──▶ journal.db
    anything ───┘

One writer, and a service anywhere can record a decision.

**The direct path stays.** `Journal.write` is still there and is still what the
tests and one-off scripts use, because a bus is a dependency and recording a
decision should not require one to be running. `publish()` is the same call
routed differently, not a replacement.

**Nothing off the bus is trusted.** An entry arrives as a plain dict from a
process we did not write, so `Entry.from_message` validates rather than
assumes, and returns None on anything it cannot make sense of. A malformed
entry is dropped with a warning; it never becomes a half-written row.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..bus import JOURNAL, Bus
from ..logging import get_logger
from .models import Entry, Kind
from .store import Journal

log = get_logger(__name__)

DEFAULT_GROUP = "journal"


def to_message(entry: Entry) -> dict[str, Any]:
    """An entry as it goes on the wire."""
    return entry.to_dict()


def from_message(payload: Any) -> Entry | None:
    """Rebuild an entry from a bus message, or None if it cannot be trusted.

    The `id` on the wire is ignored rather than honoured: it is derived from
    the content, so recomputing it locally means a sender cannot claim an id
    that does not match what it sent, and two services publishing the same
    decision still collapse to one row.
    """
    if not isinstance(payload, dict):
        return None
    title = str(payload.get("title") or "").strip()
    if not title:
        return None

    context = payload.get("context")
    tags = payload.get("tags")
    confidence = payload.get("confidence")
    return Entry(
        title=title,
        kind=Kind.parse(payload.get("kind")),
        actor=str(payload.get("actor") or ""),
        rationale=str(payload.get("rationale") or ""),
        context=dict(context) if isinstance(context, dict) else {},
        tags=tuple(str(tag) for tag in tags) if isinstance(tags, list | tuple) else (),
        confidence=float(confidence) if isinstance(confidence, int | float) else None,
        parent=str(payload.get("parent") or ""),
        time=float(payload.get("time") or time.time()),
    )


async def publish(bus: Bus | None, entry: Entry) -> bool:
    """Send one entry to whichever process is writing the journal.

    Returns False when there is no bus, so a caller can fall back to writing
    directly rather than silently losing the entry.
    """
    if bus is None:
        return False
    try:
        await bus.publish(JOURNAL, to_message(entry), source=entry.actor or "journal")
    except Exception as exc:  # journalling must never break its caller
        log.warning("journal: could not publish %r: %s", entry.title, exc)
        return False
    return True


async def listen(
    bus: Bus,
    journal: Journal,
    *,
    group: str = DEFAULT_GROUP,
    limit: int | None = None,
    on_entry: Callable[[Entry, bool], None] | None = None,
) -> int:
    """Write down everything published to `journal`. Returns entries written.

    Runs until the bus closes, or until `limit` entries have been handled. A
    bad entry is logged and skipped - one malformed message from one service
    must not stop the next service's decision being recorded.
    """
    written = 0
    async for message in bus.subscribe(JOURNAL, group=group):
        entry = from_message(message.payload)
        if entry is None:
            log.warning("journal: dropped an unusable entry from %s", message.source or "?")
            continue
        try:
            fresh = await journal.write(entry) == 1
        except Exception as exc:
            log.error("journal: could not record %r: %s", entry.title, exc)
            continue
        written += fresh
        if on_entry is not None:
            on_entry(entry, fresh)
        if limit is not None and written >= limit:
            return written
    return written
