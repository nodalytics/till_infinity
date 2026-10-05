"""What the service must remember across a restart.

Four things, and nothing learned - so JSON rather than the pickled models the
structures service keeps, and readable by `cat` when someone asks why an alert
did or did not go out:

* `last` - per series, the newest bar already processed. A bar is processed
  once, which is the first half of not alerting twice.
* `sent` - the dedupe keys of alerts already published (rule, symbol,
  timeframe, bar time), bounded to the newest `SENT_MEMORY`. The second half:
  two sources carrying one coin produce one alert.
* `trades` - the frozen trades still open, so their exits are alerted after a
  restart exactly as they would have been without one.
* the market mirror's bookkeeping: open M1 and B positions, the alts that
  signalled on each daily close, and BTC's last daily close for reference.

Written atomically (a temp file, then a rename), so a process killed mid-save
leaves the previous state rather than half of one.
"""

from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from ..logging import get_logger

log = get_logger(__name__)

VERSION = 1
SENT_MEMORY = 5_000


@dataclass(slots=True)
class State:
    last: dict[str, int] = field(default_factory=dict)
    sent: deque[str] = field(default_factory=lambda: deque(maxlen=SENT_MEMORY))
    trades: dict[str, dict] = field(default_factory=dict)
    mirrors: dict[str, dict] = field(default_factory=dict)
    breadth: dict[str, list[str]] = field(default_factory=dict)
    holds: dict[str, dict] = field(default_factory=dict)
    btc: dict[str, float] = field(default_factory=dict)
    adopted: dict[str, str] = field(default_factory=dict)

    def seen(self, key: str) -> bool:
        return key in self._sent_set()

    def mark(self, key: str) -> None:
        if not self.seen(key):
            self.sent.append(key)

    def _sent_set(self) -> set[str]:
        # Rebuilt per call: the deque is a few thousand short strings and is
        # asked a handful of times per closed bar.
        return set(self.sent)

    def to_dict(self) -> dict:
        return {
            "version": VERSION,
            "last": self.last,
            "sent": list(self.sent),
            "trades": self.trades,
            "mirrors": self.mirrors,
            "breadth": self.breadth,
            "holds": self.holds,
            "btc": self.btc,
            "adopted": self.adopted,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> State:
        return cls(
            last={str(k): int(v) for k, v in (raw.get("last") or {}).items()},
            sent=deque((str(x) for x in raw.get("sent") or ()), maxlen=SENT_MEMORY),
            trades=dict(raw.get("trades") or {}),
            mirrors=dict(raw.get("mirrors") or {}),
            breadth={str(k): list(v) for k, v in (raw.get("breadth") or {}).items()},
            holds=dict(raw.get("holds") or {}),
            btc=dict(raw.get("btc") or {}),
            adopted=dict(raw.get("adopted") or {}),
        )

    def prune(self, now: float, keep: float = 30 * 86_400) -> None:
        """Forget breadth days older than `keep` seconds."""
        for day in [d for d in self.breadth if int(d) < now - keep]:
            del self.breadth[day]


def load(path: Path) -> State:
    """The saved state, or an empty one (said once) if there is none or it is unreadable."""
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return State()
    except Exception as exc:  # a corrupt file starts cold rather than not at all
        log.warning("mcfl: could not read %s (%s) - starting cold", path, exc)
        return State()
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        log.warning("mcfl: %s is not a version %d state - starting cold", path, VERSION)
        return State()
    return State.from_dict(raw)


def save(state: State, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state.to_dict(), separators=(",", ":")))
    os.replace(temp, path)
