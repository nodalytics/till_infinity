"""Keeping what the models learned.

An online model that resets on restart has learned nothing. Everything about
this layer — a warmup before it will score, a quantile estimated from history,
a per-venue distribution built over hours — assumes continuity across restarts,
so persistence is part of the design rather than a convenience.

Pickle, because river models are ordinary Python objects with no serialisation
format of their own and no stable numeric export. That has one consequence
worth stating plainly: **a state file is only loadable by compatible versions
of river and Python.** So the file records the versions it was written with and
refuses to load into a mismatch, which costs a warmup and is the correct trade
— silently loading a half-restored model would give scores that look fine and
mean nothing.

The same applies to **our own classes**, and that one is easier to miss. These
are slotted dataclasses, so adding a field does not raise on unpickling: the
old objects come back without the new slot and fail later, at whatever line
first reads it. That happened — a `regime` feature was added and a running
service died hours afterwards on state written before the change, with a
message naming neither the field nor the cause.

So the fingerprint includes a hash of the field names of every class that gets
persisted. A field added, removed or renamed invalidates old state
automatically, which is better than a version constant somebody has to remember
to bump — nobody remembers, and the failure is silent until it is not.

Writes are atomic (temp file, then rename). A process killed mid-save leaves
the previous state intact rather than a truncated file that fails to load.
"""

from __future__ import annotations

import hashlib
import pickle
import sys
from pathlib import Path
from typing import Any

import river

from ..logging import get_logger

log = get_logger(__name__)

FORMAT = 2
STATE_FILE = "models.pkl"


def _schema() -> str:
    """A hash of the shape of everything we persist.

    Imported lazily: `store` is imported by the modules these classes live in,
    and asking for them at module scope would be a cycle.
    """
    from . import levels, patterns, reactions

    classes = (
        levels.Level,
        levels.Kalman,
        levels.SideStats,
        reactions.Features,
        reactions.Touch,
        patterns.Shape,
        patterns.Instance,
    )
    shape = ";".join(
        f"{cls.__name__}:{','.join(getattr(cls, '__slots__', ()) or ())}" for cls in classes
    )
    return hashlib.sha256(shape.encode()).hexdigest()[:16]


def _fingerprint() -> dict[str, Any]:
    return {
        "format": FORMAT,
        "river": river.__version__,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "schema": _schema(),
    }


def save(state: dict[str, Any], directory: Path | str) -> Path:
    """Write model state atomically. Returns the file written."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = target / STATE_FILE
    payload = {**_fingerprint(), "state": state}

    temp = path.with_suffix(".tmp")
    temp.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    temp.replace(path)  # atomic on POSIX
    log.debug("structures: saved model state to %s", path)
    return path


def load(directory: Path | str) -> dict[str, Any] | None:
    """Read model state back, or None if there is none we can trust.

    Never raises. A corrupt or mismatched file means starting cold, which is
    slow but correct; refusing to start at all would make a bad state file into
    an outage.
    """
    path = Path(directory) / STATE_FILE
    if not path.exists():
        return None
    try:
        payload = pickle.loads(path.read_bytes())
    except Exception as exc:
        log.warning("structures: could not read %s (%s) — starting cold", path, exc)
        return None

    if not isinstance(payload, dict):
        log.warning("structures: %s is not model state — starting cold", path)
        return None

    want = _fingerprint()
    for field in ("format", "river", "python", "schema"):
        if payload.get(field) != want[field]:
            log.warning(
                "structures: %s was written with %s %s, this is %s — starting cold",
                path,
                field,
                payload.get(field),
                want[field],
            )
            return None

    state = payload.get("state")
    return state if isinstance(state, dict) else None
