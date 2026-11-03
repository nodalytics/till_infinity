"""Writing the service's progress down, and refusing to read it back wrong.

Small, by design. `structures/store.py` carries a 128MB pickle of river models
and all the machinery that implies - a recursion limit, a node budget, a
version fingerprint that refuses to load into a mismatch. This file holds
counters, so it needs none of that, and the reason is in `state.py`: the member
graph is **re-warmed by replay** rather than restored.

What it does keep from that module is the two habits that were learned the hard
way there.

* **A format number, checked on read.** A file from a future format is not read
  as if it were this one. The cost of refusing is one warmup; the cost of
  loading a changed meaning is numbers that look fine.
* **An atomic write.** Written beside the target and renamed, so a process
  killed mid-save leaves the previous file intact rather than a truncated one.
  A desk that is OOM-killed three times a fortnight gets this wrong otherwise.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .state import Progress, applied, snapshot

log = logging.getLogger(__name__)

#: Bumped when the file's layout changes. `Progress.version` covers the record
#: inside it; this covers the envelope.
FORMAT = 1

STATE_FILE = "progress.msgpack"

__all__ = ["FORMAT", "STATE_FILE", "load", "path_for", "save"]


def path_for(state_dir: Path | str) -> Path:
    return Path(state_dir) / STATE_FILE


def save(progress: Progress, state_dir: Path | str, *, at: float) -> int:
    """Write `progress`. Returns bytes written, or 0 if nothing was written."""
    import msgpack

    target = path_for(state_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"format": FORMAT, "state": snapshot(progress, at=at)}
    raw = msgpack.packb(payload, use_bin_type=True)
    if not raw:
        return 0
    beside = target.with_suffix(target.suffix + ".new")
    beside.write_bytes(raw)
    os.replace(beside, target)
    progress.saved_at = float(at)
    return len(raw)


def load(state_dir: Path | str) -> Progress:
    """Read what `save` wrote. A missing, unreadable or newer file is empty.

    Empty rather than raising: an unreadable progress file costs a warmup, and
    a service that will not start because of one is worse than a service that
    comes up cold.
    """
    import msgpack

    target = path_for(state_dir)
    if not target.is_file():
        return Progress()
    try:
        raw = msgpack.unpackb(target.read_bytes(), raw=False, strict_map_key=False)
    except Exception as exc:
        log.warning("statespace: progress at %s will not decode (%s); starting cold", target, exc)
        return Progress()
    if not isinstance(raw, dict):
        return Progress()
    found = int(raw.get("format") or 0)
    if found != FORMAT:
        log.warning(
            "statespace: progress at %s is format %s, this is %s; starting cold",
            target,
            found,
            FORMAT,
        )
        return Progress()
    got: Any = raw.get("state")
    return applied(got)
