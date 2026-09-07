"""The codec, with the default this package used to supply.

The machinery moved to `shared/codec.py` when `trading` turned out to be
importing it from here - a service reaching into another service for its
persistence layer, which is the shape the shared folder exists to end.

What stayed behind is the **default**. `registry()` walked this package when it
lived here, and dozens of call sites rely on that; the shared version refuses
to guess, because keys are `basename.ClassName` and `config.Settings` exists in
every service, so a wrong default resolves one service's state into another's
class rather than raising.
"""

from __future__ import annotations

from typing import Any

from ..shared.codec import ALIASES, RAW, TAG, _homes, _Relocating, _unpickle, key_for, pack
from ..shared.codec import registry as _registry
from ..shared.codec import unpack as _unpack

# `_homes`, `_Relocating` and `_unpickle` are private and re-exported anyway:
# the relocation they implement is *this* package's history - the day it was
# organised into folders and 58MB of raw blobs went on pointing at
# `till_infinity.structures.anomaly` - so this is where they are reached for
# and tested from.
__all__ = [
    "ALIASES",
    "RAW",
    "TAG",
    "_Relocating",
    "_homes",
    "_unpickle",
    "key_for",
    "pack",
    "registry",
    "unpack",
]


def registry(package: Any = None) -> dict[str, type]:
    """Every persisted class in `package`, defaulting to `structures`."""
    if package is None:
        from .. import structures

        package = structures
    return _registry(package)


def unpack(value: Any, known: dict[str, type] | None = None) -> Any:
    """Rebuild state written by `pack`, defaulting to this package's classes."""
    return _unpack(value, registry() if known is None else known)
