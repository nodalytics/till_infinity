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

import os
import pickle
import sys
from collections import deque
from pathlib import Path
from typing import Any

import river
from till_platform.logging import get_logger

log = get_logger(__name__)

FORMAT = 4
#: The current file. `.pkl` is kept as the name of the **old** one so a build
#: that has not migrated yet can still be rolled back to.
STATE_FILE = "models.msgpack"
LEGACY_FILE = "models.pkl"


def _schema() -> dict[str, str]:
    """The shape of everything we persist, class by class.

    See `structures-store.md` in research/docs.
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
    shapes: dict[str, str] = {}
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
                shapes[f"{found}.{name}"] = ",".join(cls.__slots__)
    return shapes


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


def _reshaped(saved: Any, current: dict[str, str]) -> list[str]:
    """Classes whose fields differ between the state and this build.

    See `structures-store.md` in research/docs.
    """
    if not isinstance(saved, dict):
        return []
    return [name for name, fields in saved.items() if name in current and current[name] != fields]


def _fingerprint() -> dict[str, Any]:
    return {
        "format": FORMAT,
        "river": river.__version__,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "schema": _schema(),
    }


def _stream(state: dict[str, Any], fingerprint: dict[str, Any], stream: Any) -> int:
    """Write the whole payload to `stream`, a node at a time.

    The outer map is written directly rather than through `codec.pack`, which
    is what `_encode` did too: the fingerprint is plain data and tagging it
    would change the format for no gain. Only `state` goes through the codec,
    and it goes through `pack_into` rather than `pack`.
    """
    import msgpack

    from .codec import pack_into

    packer = msgpack.Packer(use_bin_type=True)
    written = 0
    stream.write(packer.pack_map_header(len(fingerprint) + 1))
    for key, value in fingerprint.items():
        chunk = packer.pack(key) + packer.pack(value)
        stream.write(chunk)
        written += len(chunk)
    stream.write(packer.pack("state"))
    return written + pack_into(state, stream)


#: Recursion frames allowed while writing state. **River picks 980 and Python
#: allows 1,000.**
#:
#: `HoeffdingTreeRegressor(max_depth=None)` resolves to 980 inside river - chosen
#: there so river's own recursive traversals stay under the interpreter's default
#: limit. That leaves twenty frames for the splitter chains hanging off each
#: leaf, the leaf estimators, this module's own walk, and whatever stack the
#: caller is already holding. A tree river is willing to grow is therefore
#: unpicklable at the default limit, by construction, and the failure is a
#: `RecursionError` from inside `pickle` with nothing pointing at the cause.
#:
#: From 2026-09-23 to 2026-10-10 every save raised exactly that. The models are
#: capped well below this now (`vol/learned.MAX_TREE_DEPTH`), so this is the
#: second line rather than the first: it exists so the *next* structure that
#: grows deeper than someone expected costs a log line instead of a fortnight of
#: silent non-persistence.
#:
#: 4,000 rather than something enormous: `pickle` recurses on the C stack too,
#: and a limit a thread's stack cannot honour turns a failed save into a
#: segfault, which is strictly worse. Four times the default is far more than
#: any capped model needs and nowhere near a stack this size.
SAVE_RECURSION_LIMIT = 4_000

#: Nodes the failure diagnostic will visit before giving up, and how much of the
#: path it prints. Bounded because it runs on a 206MB object graph inside an
#: exception handler on a two-core box - and because the walk it bounds is the
#: one case where taking too long is worse than answering imprecisely: the save
#: has already failed, and the service still has to come back.
#:
#: 8,000,000 rather than 2,000,000: at the smaller budget it reported 21 levels
#: against a true 92 on production's own state, because breadth is what consumes
#: it and the deep branches had not been opened yet. An exhausted budget is now
#: reported rather than hidden, but a number that is usually right is worth more
#: than a caveat that is always there.
DIAGNOSTIC_NODES = 8_000_000
DIAGNOSTIC_PATH = 12


def deepest_path(root: Any) -> tuple[int, str]:
    """The deepest chain in `root`, as `(depth, path)`. For failure messages only.

    **Iterative on purpose.** This runs because something already exceeded the
    recursion limit, so a recursive walk would raise inside the handler and
    replace a useful message with a confusing one.

    Cycles are skipped by tracking the nodes on the current path rather than
    every node seen: a shared object reached twice by different routes is not a
    cycle and its depth is worth knowing, which a global visited-set would hide.

    **The depth is a lower bound and says so when it is one.** The walk stops
    after `DIAGNOSTIC_NODES` because the live graph is a million nodes on a
    two-core box, and it can stop before reaching the deepest branch: measured
    on production's own state it reported 21 against a true 92. A diagnostic
    that quietly under-reports is the fault it was written to find, so an
    exhausted budget is named in the returned path.
    """
    scalar = (type(None), bool, int, float, str, bytes, bytearray)
    best_depth, best_path = 0, ()
    budget = DIAGNOSTIC_NODES
    # (node, path, depth, ancestors) with an explicit stack.
    stack: list[tuple[Any, tuple, int, frozenset]] = [(root, (), 0, frozenset())]
    while stack and budget > 0:
        node, path, depth, seen = stack.pop()
        budget -= 1
        if depth > best_depth:
            best_depth, best_path = depth, path
        if isinstance(node, scalar) or id(node) in seen:
            continue
        here = seen | {id(node)}
        try:
            if isinstance(node, dict):
                kids = [(f"[{k!r}]", v) for k, v in list(node.items())[:2048]]
            elif isinstance(node, list | tuple | set | frozenset | deque):
                kids = [(f"[{i}]", v) for i, v in enumerate(list(node)[:2048])]
            else:
                kids = []
                held = getattr(node, "__dict__", None)
                if held:
                    kids += [(f".{k}", v) for k, v in held.items()]
                for name in getattr(type(node), "__slots__", ()) or ():
                    if hasattr(node, name):
                        kids.append((f".{name}", getattr(node, name)))
        except Exception:  # a diagnostic that raises is worse than no diagnostic
            continue
        for label, child in kids:
            stack.append((child, (*path, label), depth + 1, here))
    tail = "".join(best_path[-DIAGNOSTIC_PATH:])
    lead = "..." if len(best_path) > DIAGNOSTIC_PATH else ""
    # Budget gone means branches were never opened, so the depth is a floor.
    cut = " (truncated - depth is a lower bound)" if budget <= 0 and stack else ""
    return best_depth, f"{lead}{tail}{cut}"


def save(state: dict[str, Any], directory: Path | str) -> Path:
    """Write model state atomically. Returns the file written.

    See `structures-store.md` in research/docs.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = target / STATE_FILE

    temp = path.with_suffix(".tmp")
    # **Room to pickle, and the old limit back afterwards.** See
    # `SAVE_RECURSION_LIMIT` for why the default is not enough for a structure
    # river is willing to build.
    was = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(max(was, SAVE_RECURSION_LIMIT))
        written = _write(state, temp)
    except RecursionError:
        # The one failure that says nothing about itself. Report where the depth
        # is before re-raising, or the caller logs "maximum recursion depth
        # exceeded" and nobody can act on it.
        try:
            depth, where = deepest_path(state)
            log.error(
                "structures: state is %d levels deep at %s - too deep to pickle "
                "even at a limit of %d; the model caps in vol/learned.py are what "
                "bound this",
                depth,
                where,
                max(was, SAVE_RECURSION_LIMIT),
            )
        except Exception as exc:  # never let the diagnostic replace the error
            log.warning("structures: could not measure the state's depth: %s", exc)
        raise
    finally:
        sys.setrecursionlimit(was)
    temp.replace(path)  # atomic on POSIX
    log.debug("structures: saved %d bytes of model state to %s", written, path)
    return path


def _write(state: dict[str, Any], temp: Path) -> int:
    """The bytes, flushed and on the platter before anyone renames over them."""
    with temp.open("wb") as handle:
        written = _stream(state, _fingerprint(), handle)
        # The state is worth more than the latency. Without this the rename can
        # publish a file whose bytes are still in the page cache, and a machine
        # that loses power between the two comes back to a truncated state that
        # passes every check in `load` until it fails mid-parse.
        handle.flush()
        os.fsync(handle.fileno())
    return written


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
    # `schema` is compared separately below, key by key, because it is now a
    # map and `!=` on the whole thing is the blunt check this is replacing.
    checks = ("river", "python") if from_legacy else ("format", "river", "python")
    # Both readers accept the format before this one, for the same reason the
    # legacy path does: a container change is exactly the case a migration
    # exists for, and rejecting it here discards the state the migration is
    # meant to carry. Checking the new number against the old file is the
    # mistake that threw away 58MB on the first msgpack deploy.
    if payload.get("format") not in (FORMAT, FORMAT - 1):
        log.warning(
            "structures: %s is format %s, too old to migrate into %s - starting cold",
            legacy,
            payload.get("format"),
            FORMAT,
        )
        return None
    for field in checks:
        if field == "format":
            continue  # handled above, where the migration window is stated
        if payload.get(field) != want[field]:
            log.warning(
                "structures: %s was written with %s %s, this is %s - starting cold",
                path,
                field,
                payload.get(field),
                want[field],
            )
            return None

    # **Reported, not fatal**, and the third revision of this check in a day.
    #
    # It was one hash over the package, so adding a class discarded everything.
    # It became a per-class map, so adding two fields to one small model -
    # `racing.Races` gaining its control counters - discarded everything
    # instead: 59MB of levels, the break model and weeks of touches, thrown
    # away for a change no restore could have tripped over.
    #
    # Because `Restorable.__setstate__` restores **by field name**. It defaults
    # what the save predates and ignores what the build has dropped, so both
    # directions of a field-set change are handled by design - and that is the
    # failure this fingerprint was written for, back when the state was pickled
    # and a slots class got no defaulting at all.
    #
    # What it cannot see is a field keeping its name and changing *meaning*,
    # which is what each model's `RECIPE` exists for and where that guard
    # belongs: per model, dropping one model's statistics rather than the file.
    #
    # So the shape is still computed and still said out loud, because knowing
    # which classes moved is worth having. It no longer costs the state.
    changed = _reshaped(payload.get("schema"), want["schema"])
    if changed:
        log.info(
            "structures: %s changed shape since %s was written - restoring anyway, "
            "fields are matched by name and defaulted where the save predates them",
            ", ".join(sorted(changed)),
            path,
        )

    state = payload.get("state")
    return state if isinstance(state, dict) else None
