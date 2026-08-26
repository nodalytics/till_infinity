"""What a journal entry is.

The field that matters is `rationale`: not what was decided but **why, at that
moment**, with what was known then. A decision recorded without its reasoning
is only a log line, and a log line teaches nobody anything later.

`context` is the other half of that. It holds the state the decision was made
from - the spreads as they read *then*, the calendar as it stood *then* -
copied in rather than referenced. That is deliberate and it is the whole point:
the stores keep moving. Bars get corrected, an event's `actual` lands, a quote
is superseded a second later. A journal entry that said "see the quotes table"
would, a month on, describe a world that no longer exists, and any model
trained on it would be learning from information the decision never had.

Point-in-time correctness is not a nicety here. It is the difference between a
dataset and a leak.
"""

from __future__ import annotations

import hashlib
import json
import time as _time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Kind(StrEnum):
    """What sort of thing is being recorded."""

    #: We chose to do or say something. Carries a rationale.
    DECISION = "decision"
    #: We noticed something and did not act. Useful as a negative example.
    OBSERVATION = "observation"
    #: What happened after an earlier entry. Links to it by `parent`.
    OUTCOME = "outcome"
    #: Human context - why a threshold was changed, what a run was for.
    NOTE = "note"

    @classmethod
    def parse(cls, value: str | None) -> Kind:
        try:
            return cls(str(value or "").strip().lower())
        except ValueError:
            return cls.NOTE


def _digest(when: float, actor: str, title: str) -> str:
    """A content id, so writing the same entry twice is not two entries.

    Deterministic on purpose: a watcher that restarts and re-judges the same
    window should not double-record the decision it already recorded.
    """
    raw = f"{when:.3f}|{actor}|{' '.join(title.lower().split())}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Entry:
    """One thing worth remembering, and the state it was decided from."""

    title: str
    kind: Kind = Kind.NOTE
    actor: str = ""
    rationale: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    confidence: float | None = None
    parent: str = ""
    time: float = field(default_factory=_time.time)

    @property
    def id(self) -> str:
        return _digest(self.time, self.actor, self.title)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "time": self.time,
            "kind": str(self.kind),
            "actor": self.actor,
            "title": self.title,
            "rationale": self.rationale,
            "context": self.context,
            "tags": list(self.tags),
            "confidence": self.confidence,
            "parent": self.parent,
        }

    @classmethod
    def from_row(cls, row: Any) -> Entry:
        """Rebuild from a stored row. Tolerates junk in the JSON columns."""
        return cls(
            title=row["title"],
            kind=Kind.parse(row["kind"]),
            actor=row["actor"] or "",
            rationale=row["rationale"] or "",
            context=_loads(row["context"], {}),
            tags=tuple(_loads(row["tags"], [])),
            confidence=row["confidence"],
            parent=row["parent"] or "",
            time=row["time"],
        )

    def __str__(self) -> str:
        mark = {"decision": "→", "outcome": "✓", "observation": "·"}.get(str(self.kind), "-")
        who = f" [{self.actor}]" if self.actor else ""
        return f"{mark} {self.title}{who}"


def _loads(raw: Any, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return fallback
    return value if type(value) is type(fallback) else fallback
