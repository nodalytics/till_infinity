"""What the service keeps across a restart, and what it deliberately does not.

## The package declares itself unpersisted, and that is not an oversight

`__init__.py` sets `CODEC_UNPERSISTED = True`, and the comment above it gives
the reason: `shared.codec.registry()` builds a state file's schema by **walking
every module and collecting every dataclass**, by discovery rather than by
import. Forty-odd modules here hold slotted dataclasses that do not subclass
`Restorable`, so flipping that flag would put all of them into the persistence
fingerprint, make adding a field to any of them a schema change, and end the
property the package was written for - that it is deletable.

So this service does not pickle its member graph. It persists a **declared**
record of its own progress, and warms the numeric state by replaying bars.

## Replay rather than restore, which is what the desk already does

`structures` arms its handlers after a backfill, not on boot: `armed=0` right
after a deploy is the normal reading, and the handlers come up as history is
replayed. The members here are cheap to re-warm for the same reason they are
cheap to run - `DEFAULT_WARM_BARS` bars per feed and interval - and a replayed
member is identical to a restored one, where a half-restored one is not.

The trap this avoids is a measured one. A capped `deque` field came back
**unbounded** after a restore on this desk, because the bound lives on the
class and the restored object was built from data; `shared.state.restore_deque`
fixes that for a direct field, and `Desk._residuals` is a `dict` *of* deques,
which it does not reach. `applied()` rebuilds every window at its declared
`maxlen` rather than trusting what was written, and a test asserts the bound on
the restored object rather than reading the declaration.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..shared.state import Restorable, restore_enum

__all__ = ["Progress", "Restorable", "Seen", "restore_enum", "snapshot"]


@dataclass(slots=True)
class Seen(Restorable):
    """One feed and interval's progress. Counters, not model state."""

    feed: str = ""
    interval: str = ""
    #: Bars folded since this record was created. Decides `armed`.
    bars: int = 0
    #: The last bar time folded, so a replay can resume rather than restart.
    at: float = 0.0
    #: The last published value and spread, for diagnostics after a restart
    #: that has not yet re-warmed. Never fed back into a member.
    value: float = 0.0
    spread: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        return (self.feed, self.interval)


@dataclass(slots=True)
class Progress(Restorable):
    """The whole of what survives a restart."""

    #: Bumped when the meaning of a field here changes. `store.FORMAT` covers
    #: the file; this covers the record.
    version: int = 1
    seen: dict[str, Seen] = field(default_factory=dict)
    saved_at: float = 0.0
    #: Bars folded over this process's life, for the log line that says whether
    #: the service is doing anything at all.
    folded: int = 0

    @staticmethod
    def name(feed: str, interval: str) -> str:
        """The map key. A string, because msgpack maps cannot be tuple-keyed.

        `Desk` keys its own dicts by `(feed, interval)`, which is the right
        shape in memory and unwritable on the wire. One place converts.
        """
        return f"{feed}\t{interval}"

    def of(self, feed: str, interval: str) -> Seen:
        key = self.name(feed, interval)
        got = self.seen.get(key)
        if got is None:
            got = self.seen[key] = Seen(feed=feed, interval=interval)
        return got

    def armed(self, warm_bars: int) -> int:
        """How many feed-intervals have enough bars to publish."""
        return sum(1 for s in self.seen.values() if s.bars >= warm_bars)


def snapshot(progress: Progress, *, at: float) -> dict[str, Any]:
    """`progress` as plain data: msgpack-safe, tuple-free, no class graph."""
    return {
        "version": int(progress.version),
        "saved_at": float(at),
        "folded": int(progress.folded),
        "seen": [
            {
                "feed": s.feed,
                "interval": s.interval,
                "bars": int(s.bars),
                "at": float(s.at),
                "value": float(s.value),
                "spread": float(s.spread),
            }
            for s in progress.seen.values()
        ],
    }


def applied(raw: Any) -> Progress:
    """Rebuild a `Progress` from `snapshot` output. Junk returns an empty one."""
    out = Progress()
    if not isinstance(raw, dict):
        return out
    out.version = int(raw.get("version") or 1)
    out.saved_at = float(raw.get("saved_at") or 0.0)
    out.folded = int(raw.get("folded") or 0)
    for entry in raw.get("seen") or ():
        if not isinstance(entry, dict):
            continue
        feed = str(entry.get("feed") or "")
        interval = str(entry.get("interval") or "")
        if not feed or not interval:
            continue
        got = out.of(feed, interval)
        got.bars = int(entry.get("bars") or 0)
        got.at = float(entry.get("at") or 0.0)
        got.value = float(entry.get("value") or 0.0)
        got.spread = float(entry.get("spread") or 0.0)
    return out


def window(values: Any, maxlen: int) -> deque:
    """A bounded window rebuilt from written data.

    The bound is passed and applied here rather than inherited from whatever
    the data came back as. A restore that drops `maxlen` leaves a window that
    grows without limit, looks correct on every read, and changes a quantile
    estimate slowly enough that nothing notices.
    """
    out: deque = deque(maxlen=max(int(maxlen), 1))
    if isinstance(values, (list, tuple)):
        for v in values:
            if isinstance(v, (int, float)):
                out.append(float(v))
    return out
