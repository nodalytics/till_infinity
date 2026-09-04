"""Keeping what the models learned.

An online model that resets on restart has learned nothing. Everything about
this layer - a warmup before it will score, a quantile estimated from history,
a per-venue distribution built over hours - assumes continuity across restarts,
so persistence is part of the design rather than a convenience.

Pickle, because river models are ordinary Python objects with no serialisation
format of their own and no stable numeric export. That has one consequence
worth stating plainly: **a state file is only loadable by compatible versions
of river and Python.** So the file records the versions it was written with and
refuses to load into a mismatch, which costs a warmup and is the correct trade
- silently loading a half-restored model would give scores that look fine and
mean nothing.

The same applies to **our own classes**, and that one is easier to miss. These
are slotted dataclasses, so adding a field does not raise on unpickling: the
old objects come back without the new slot and fail later, at whatever line
first reads it. That happened - a `regime` feature was added and a running
service died hours afterwards on state written before the change, with a
message naming neither the field nor the cause.

So the fingerprint includes a hash of the field names of every class that gets
persisted. A field added, removed or renamed invalidates old state
automatically, which is better than a version constant somebody has to remember
to bump - nobody remembers, and the failure is silent until it is not.

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

FORMAT = 3
#: The current file. `.pkl` is kept as the name of the **old** one so a build
#: that has not migrated yet can still be rolled back to.
STATE_FILE = "models.msgpack"
LEGACY_FILE = "models.pkl"


def _schema() -> str:
    """A hash of the shape of everything we persist.

    Found by walking the package, because the hand-written list this replaces
    *was* the bug. It named seven classes and `Volatility` was not among them,
    so adding `_tick`, `_steps` and `_grid` to it left the hash unchanged. The
    old state was therefore accepted as compatible, and the service then
    crashed reading a field the save predated - `AttributeError` on a
    `slots=True` dataclass, which has no `__dict__` to fall back on, so an
    absent field is missing rather than defaulted.

    The throw landed inside the structures consumer, so nothing crashed
    outright: the container stayed healthy at 11% CPU and simply stopped
    producing for four hours, across twelve deploys, each one restoring the
    same stale state and dying the same way.

    A list is the wrong shape for this. Anyone adding a field to a persisted
    class would have to know the list exists, and the person who added those
    three did not. Walking means the guard covers classes nobody thought to
    register - including ones added later.

    The cost of a change here is a cold start, which is the policy `load`
    already states: slow but correct. That is the trade this hash exists to
    make, and it is a far better one than a silent stop.

    Imported lazily: `store` is imported by the modules these classes live in,
    and asking for them at module scope would be a cycle.
    """
    import importlib
    import pkgutil
    from dataclasses import is_dataclass

    from . import __path__ as package_path

    # `walk_packages` and a **basename** key, both deliberately.
    #
    # The walk, because `iter_modules` is flat and the package grew subpackages
    # on 2026-09-04: it went on finding the eleven modules left at the top and
    # silently stopped covering the other thirty-five, so a new field on one of
    # them would not have invalidated saved state and the restore would have
    # crashed instead of starting cold - which is the exact failure this hash
    # exists to prevent.
    #
    # The basename, because the fingerprint must not change when a module
    # moves. Hashing the dotted path would have made this reorganisation
    # invalidate 58MB of learned state - every level, the break model, weeks of
    # touches - for a change that alters no field of anything. It is the same
    # rule `codec.key_for` follows, for the same reason. Sorting on the
    # basename too, so the order is the one the flat walk produced.
    shapes: list[str] = []
    modules = {}
    for info in pkgutil.walk_packages(package_path, prefix=f"{__package__}."):
        modules[info.name.rsplit(".", 1)[-1]] = info.name
    for found in sorted(modules):
        module = importlib.import_module(modules[found])
        for name in sorted(dir(module)):
            cls = getattr(module, name)
            # Defined here rather than imported into here, or a class would be
            # hashed once per module that mentions it and the order would
            # depend on import bookkeeping.
            if (
                isinstance(cls, type)
                and is_dataclass(cls)
                and cls.__module__ == module.__name__
                and getattr(cls, "__slots__", None) is not None
            ):
                shapes.append(f"{found}.{name}:{','.join(cls.__slots__)}")
    return hashlib.sha256(";".join(shapes).encode()).hexdigest()[:16]


def _encode(payload: dict[str, Any]) -> bytes:
    """msgpack, with our own classes already reduced to tagged mappings.

    `codec.pack` is what buys path independence; msgpack is only the container.
    That separation is deliberate - it means the guarantee does not depend on
    which serialiser is installed, and a fallback container cannot quietly take
    it away.
    """
    import msgpack

    from .codec import pack

    return msgpack.packb({**payload, "state": pack(payload.get("state") or {})}, use_bin_type=True)


def _decode(raw: bytes) -> dict[str, Any]:
    import msgpack

    from .codec import unpack

    payload = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    if isinstance(payload, dict):
        payload["state"] = unpack(payload.get("state") or {})
    return payload


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
    temp.write_bytes(_encode(payload))
    temp.replace(path)  # atomic on POSIX
    log.debug("structures: saved model state to %s", path)
    return path


def load(directory: Path | str) -> dict[str, Any] | None:
    """Read model state back, or None if there is none we can trust.

    Never raises. A corrupt or mismatched file means starting cold, which is
    slow but correct; refusing to start at all would make a bad state file into
    an outage.
    """
    root = Path(directory)
    path = root / STATE_FILE
    legacy = root / LEGACY_FILE
    if not path.exists() and not legacy.exists():
        return None
    from_legacy = not path.exists()
    try:
        if path.exists():
            payload = _decode(path.read_bytes())
        else:
            # One-way migration. The old file is left where it is: the next
            # save writes the new one beside it, and a rollback needs the old
            # one to still be there.
            log.info("structures: reading %s and migrating to %s", legacy, STATE_FILE)
            payload = pickle.loads(legacy.read_bytes())
    except Exception as exc:
        log.warning("structures: could not read state (%s) - starting cold", exc)
        return None

    if not isinstance(payload, dict):
        log.warning("structures: %s is not model state - starting cold", path)
        return None

    want = _fingerprint()
    # `format` describes the **container**, and migration is exactly the case
    # where it differs - so the legacy file is allowed to carry the format that
    # wrote it. Checking it here discarded the 58MB state this migration exists
    # to preserve, on the first deploy, with the message "format 2, this is 3 -
    # starting cold". The fields that follow are about whether the *contents*
    # can be trusted, and those still apply to both files.
    checks = (
        ("river", "python", "schema") if from_legacy else ("format", "river", "python", "schema")
    )
    if from_legacy and payload.get("format") not in (FORMAT, FORMAT - 1):
        log.warning(
            "structures: %s is format %s, too old to migrate into %s - starting cold",
            legacy,
            payload.get("format"),
            FORMAT,
        )
        return None
    for field in checks:
        if payload.get(field) != want[field]:
            log.warning(
                "structures: %s was written with %s %s, this is %s - starting cold",
                path,
                field,
                payload.get(field),
                want[field],
            )
            return None

    state = payload.get("state")
    return state if isinstance(state, dict) else None
