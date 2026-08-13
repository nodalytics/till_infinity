"""Recording decisions, and closing the loop on them later.

A decision journalled without what happened next is not something anyone can
learn from — it is half a training example. So `decide()` returns the entry's
id and `outcome()` takes it, which is the only structure a later model needs to
pair the two.

Journalling must never be able to break the thing it is observing. Every helper
here logs and returns on failure rather than raising: a full disk should cost
you the record, not the collector.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..bus import Bus
from ..logging import get_logger
from . import bus as journal_bus
from .models import Entry, Kind
from .store import DEFAULT_DB, Journal, get

log = get_logger(__name__)


async def record(journal: Journal | None, entry: Entry, bus: Bus | None = None) -> str:
    """Append one entry. Returns its id, or "" if nothing was written.

    With a bus, the entry is published for whichever process writes the journal
    and this returns immediately. Without one it is written here. A caller that
    passes both gets the bus, because the point of the bus is a single writer.
    """
    if bus is not None and await journal_bus.publish(bus, entry):
        return entry.id
    if journal is None:
        return ""
    try:
        await journal.write(entry)
    except Exception as exc:  # never take down the caller
        log.warning("journal: could not record %r: %s", entry.title, exc)
        return ""
    return entry.id


async def decide(
    journal: Journal | None,
    title: str,
    *,
    rationale: str,
    actor: str = "",
    context: dict[str, Any] | None = None,
    tags: Sequence[str] = (),
    confidence: float | None = None,
    bus: Bus | None = None,
) -> str:
    """Record a choice and the reasoning behind it.

    `context` should be the state the choice was made *from*, copied in — the
    numbers as they read at that moment, not a pointer to a table that will
    have moved on by the time anyone reads this back.
    """
    return await record(
        journal,
        Entry(
            title=title,
            kind=Kind.DECISION,
            actor=actor,
            rationale=rationale,
            context=dict(context or {}),
            tags=tuple(tags),
            confidence=confidence,
        ),
        bus,
    )


async def observe(
    journal: Journal | None,
    title: str,
    *,
    rationale: str = "",
    actor: str = "",
    context: dict[str, Any] | None = None,
    tags: Sequence[str] = (),
    bus: Bus | None = None,
) -> str:
    """Record something noticed but not acted on.

    Worth as much as a decision, and often more: a model trained only on the
    times we acted learns nothing about when not to.
    """
    return await record(
        journal,
        Entry(
            title=title,
            kind=Kind.OBSERVATION,
            actor=actor,
            rationale=rationale,
            context=dict(context or {}),
            tags=tuple(tags),
        ),
        bus,
    )


async def outcome(
    journal: Journal | None,
    parent: str,
    title: str,
    *,
    rationale: str = "",
    actor: str = "",
    context: dict[str, Any] | None = None,
    tags: Sequence[str] = (),
    bus: Bus | None = None,
) -> str:
    """Record what happened after an earlier entry. This is the label."""
    if not parent:
        log.warning("journal: an outcome without a parent cannot be paired; skipping")
        return ""
    return await record(
        journal,
        Entry(
            title=title,
            kind=Kind.OUTCOME,
            actor=actor,
            rationale=rationale,
            context=dict(context or {}),
            tags=tuple(tags) or _inherited_tags(journal, parent),
            parent=parent,
        ),
        bus,
    )


def _inherited_tags(journal: Journal | None, parent: str) -> tuple[str, ...]:
    """Take the decision's tags when the outcome was not given its own.

    Without this an outcome is invisible to a tag filter, which loses exactly
    the entry an analyst most needs — the one saying the thing it is looking at
    resolved itself last time.
    """
    if journal is None:
        return ()
    try:
        entry = get(journal.path, parent)
    except Exception:  # the parent may not be readable yet; tags are a bonus
        return ()
    return entry.tags if entry else ()


async def note(
    journal: Journal | None,
    title: str,
    *,
    rationale: str = "",
    actor: str = "human",
    tags: Sequence[str] = (),
    bus: Bus | None = None,
) -> str:
    """Human context — why a threshold changed, what a run was for."""
    return await record(
        journal,
        Entry(title=title, kind=Kind.NOTE, actor=actor, rationale=rationale, tags=tuple(tags)),
        bus,
    )


def open_journal(path: Path | str | None) -> Journal | None:
    """Build a journal, or None when journalling is switched off.

    None rather than a no-op object so the cost of not journalling is a `None`
    check rather than a SQLite connection nobody wanted.
    """
    if path is None:
        return None
    return Journal(Path(path) if path else DEFAULT_DB)
