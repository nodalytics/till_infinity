"""State written by field name, not by import path.

## The problem this exists for

`store` persisted with pickle, and **pickle records the module path of every
class it holds**. Reading the 58MB state file showed
`till_infinity.structures.learning.anomaly` embedded in the bytes. That makes the
directory layout part of the file format: moving `anomaly.py` into a
subpackage - the ordinary housekeeping `trading/` had done to it on the same
day - would make weeks of learned levels, the break model and every volatility
estimator unloadable.

It also makes the file opaque. The only way to see what is in it is to unpickle
it with the exact code that wrote it, so a question as simple as "what does the
break model weigh" needs the whole package importable at the right version.

## What replaces it

Every persisted class is a dataclass, and `Restorable.__setstate__` already
restores one from a **mapping of field names**, defaulting whatever the state
predates. That is half of a codec; this is the other half.

An object becomes `{"~": "breaking.Breaks", "f": {field: ...}}` - keyed by the
module's **basename** and the class name, resolved through a registry built by
walking the package.

The basename is the whole trick. `structures/anomaly.py` moving to
`structures/detect/anomaly.py` keeps the key `anomaly.Detector`, so the
package can be reorganised freely - which is the thing pickle made unsafe.
Only *renaming the file* breaks it, and that is a deliberate act with an
obvious remedy: add the old key to `ALIASES`.

A bare class name would have been simpler and does not work: walking the
package finds `Ensemble` in two modules, `Book` in three, and `Reading` and
`Consensus` in two each. Keyed on the name alone, state for one would restore
as the other, and the failure would be wrong numbers rather than a traceback.

## What still has to be pickled, and why that is fine

`anomaly.py` holds live **river** objects - `GaussianScorer`, a `MinMaxScaler`
pipeline - which have no serialisation format and no stable numeric export.
Those are wrapped as opaque `{"~": "raw", "b": <pickle bytes>}`.

The distinction is the point. Pickling *river's* classes records *river's*
paths, and this project does not move those. Pickling *our* classes recorded
*ours*, which is what made a refactor unsafe. So the fragility that remains is
tied to a dependency's version - which `store`'s fingerprint already checks
and refuses on - rather than to our own file layout.
"""

from __future__ import annotations

import dataclasses
import io
import pickle
from collections import deque
from functools import cache
from typing import Any

from ..logging import get_logger
from .state import restore_enum, restore_number

log = get_logger(__name__)

#: The marker key. `~` because msgpack maps are string-keyed and no dataclass
#: field is named that, so a tagged object can never collide with a plain one.
TAG = "~"
RAW = "raw"


#: Keys that used to name a class whose file has since been renamed. Empty
#: today; the alternative to keeping this is invalidating everything a rename
#: touches, which for a 58MB state is a warm-up nobody chose.
ALIASES: dict[str, str] = {}


def key_for(cls: type) -> str:
    """The stable name for a persisted class: `module basename . class`."""
    return f"{cls.__module__.rsplit('.', 1)[-1]}.{cls.__name__}"


def registry(package: Any = None) -> dict[str, type]:
    """Every persisted class in the package, by its stable key.

    Walked rather than listed, for the reason `store._schema` gives about the
    hand-written list it replaced: a list is a thing somebody has to remember
    to update, and the person who adds a class is exactly the person who does
    not know it exists.

    Recurses into subpackages, so this keeps working when `structures` is
    eventually organised into folders - which is the entire point of the
    exercise.

    `package` walks somewhere else instead, which is what lets `trading` keep
    its own state in the same format. **Each package gets its own registry
    rather than one shared across both**: keys are `basename.ClassName`, and
    `config.Settings` exists in each - a shared map would silently resolve one
    package's state into the other's class.
    """
    import importlib
    import pkgutil

    if package is None:
        raise ValueError(
            "registry() needs the package to walk. It used to default to "
            "`structures` because it lived there; now that it is shared, a "
            "default would silently hand one service another's classes - and "
            "keys are `basename.ClassName`, with `config.Settings` in every "
            "service, so the failure would be a restore into the wrong class "
            "rather than an error."
        )
    where = package.__path__
    prefix = f"{package.__name__}."
    found: dict[str, type] = {}
    for module_info in sorted(m.name for m in pkgutil.walk_packages(where, prefix=prefix)):
        try:
            module = importlib.import_module(module_info)
        except Exception as exc:  # a module that will not import is not state
            log.debug("codec: skipping %s while building the registry (%s)", module_info, exc)
            continue
        for name in dir(module):
            cls = getattr(module, name)
            if (
                isinstance(cls, type)
                and dataclasses.is_dataclass(cls)
                and cls.__module__ == module.__name__
            ):
                found[key_for(cls)] = cls
    return found


def pack(value: Any) -> Any:
    """Turn state into something msgpack can write."""
    if value is None or isinstance(value, bool | int | float | str | bytes):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            TAG: key_for(type(value)),
            "f": {f.name: pack(getattr(value, f.name, None)) for f in dataclasses.fields(value)},
        }
    if isinstance(value, deque):
        # The bound travels with it. A deque restored as an unbounded one grows
        # until the box runs out, which is how this project has been OOM-killed.
        return {TAG: "deque", "n": value.maxlen, "v": [pack(v) for v in value]}
    if isinstance(value, dict):
        # Keys are often tuples here - `(feed, venue, interval)` - which msgpack
        # cannot express, so the whole mapping is carried as pairs.
        return {TAG: "map", "v": [[pack(k), pack(v)] for k, v in value.items()]}
    if isinstance(value, tuple):
        return {TAG: "tuple", "v": [pack(v) for v in value]}
    if isinstance(value, set | frozenset):
        return {TAG: "set", "v": [pack(v) for v in value]}
    if isinstance(value, list):
        return [pack(v) for v in value]
    # Anything else - river models, mostly. Opaque, and deliberately so.
    return {TAG: RAW, "b": pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)}


@cache
def _homes() -> dict[str, str]:
    """Module basename -> where that module lives now.

    Built the same way `registry` is built, and cached for the same reason:
    walking the package on every raw blob would be paid thousands of times
    reading one state file.

    **`structures` by name, and not by accident.** This map exists for one
    historical event - the day `structures` was organised into folders and
    every raw pickle blob in a 58MB state file went on pointing at
    `till_infinity.structures.anomaly`, which no longer existed. It repairs
    that one package's history. Walking whatever package this module happens
    to live in would have quietly become `shared` the moment this file moved,
    and the symptom would have been the same cold start it was written to
    prevent.

    Imported inside the function rather than at the top, because `structures`
    imports this module and the cycle would be real at import time and is not
    at call time.
    """
    import pkgutil

    from .. import structures

    return {
        info.name.rsplit(".", 1)[-1]: info.name
        for info in pkgutil.walk_packages(structures.__path__, prefix=f"{structures.__name__}.")
    }


class _Relocating(pickle.Unpickler):
    """An unpickler that follows a module to its new folder.

    The gap in this codec's own reasoning, found the hard way. The docstring
    above says raw blobs pickle *river's* classes and this project does not
    move those - so a reorganisation was safe. It is not quite true: at least
    one blob referenced `till_infinity.structures.anomaly`, and after that
    module moved into `learning/` the whole 59MB file failed to read with
    `No module named 'till_infinity.structures.anomaly'` and structures
    started cold.

    So the basename rule that protects the *named* classes has to protect the
    pickled ones too. `find_class` maps any `till_infinity.structures.X` to
    wherever X lives now, which is the `find_class` override
    `research/handoff.md` listed as the only migration that ends clean.
    """

    #: The package whose history this repairs, named rather than taken from
    #: `__package__`. It was `__package__` while this file lived in
    #: `structures`, and the moment the file moved that silently became
    #: `till_infinity.shared` - so every old blob pointing at
    #: `till_infinity.structures.anomaly` stopped matching and stopped being
    #: relocated. The test that proves the relocation works is what caught it,
    #: which is the second time in this move that `__package__` meant "wherever
    #: this file happens to be" when the intent was "structures".
    HOME = "till_infinity.structures"

    def find_class(self, module: str, name: str) -> Any:
        if module.startswith(f"{self.HOME}."):
            home = _homes().get(module.rsplit(".", 1)[-1])
            if home is not None and home != module:
                module = home
        return super().find_class(module, name)


def _unpickle(blob: bytes) -> Any:
    return _Relocating(io.BytesIO(blob)).load()


def unpack(value: Any, known: dict[str, type]) -> Any:
    """Rebuild state written by `pack`.

    `known` is required. It used to default to this package's registry, which
    was right while this lived in `structures` and is a trap now: keys are
    `basename.ClassName` and `config.Settings` exists in every service, so a
    guessed registry resolves one service's state into another's class without
    raising. `structures.codec.unpack` supplies the old default.
    """
    if isinstance(value, list):
        return [unpack(v, known) for v in value]
    if not isinstance(value, dict):
        return value
    kind = value.get(TAG)
    if kind is None:
        return {k: unpack(v, known) for k, v in value.items()}

    # A table rather than a chain of returns - the chain had reached eleven and
    # every container type added one.
    containers: dict[str, Any] = {
        "map": lambda v: {unpack(k, known): unpack(x, known) for k, x in v["v"]},
        "tuple": lambda v: tuple(unpack(x, known) for x in v["v"]),
        "set": lambda v: {unpack(x, known) for x in v["v"]},
        "deque": lambda v: deque((unpack(x, known) for x in v["v"]), maxlen=v.get("n")),
        RAW: lambda v: _unpickle(v["b"]),
    }
    build = containers.get(str(kind))
    if build is not None:
        return build(value)

    name = str(kind)
    cls = known.get(name) or known.get(ALIASES.get(name, ""))
    fields = {k: unpack(v, known) for k, v in value.get("f", {}).items()}
    if cls is None:
        # A class the current build no longer has. Returning the fields rather
        # than raising keeps one removed model from costing the whole file, and
        # the caller sees a dict where it expected an object - loud at the
        # point of use rather than silent.
        log.warning("codec: no class called %r in this build", kind)
        return fields

    made = cls.__new__(cls)
    setter = getattr(made, "__setstate__", None)
    if setter is not None:
        # The same defaulting `Restorable.__setstate__` does, and for the same
        # reason: state written before a field existed must not leave it
        # missing.
        setter(fields)
        return made
    for field in dataclasses.fields(cls):
        if field.name in fields:
            # Enums come back as their raw value - `Side` is a `StrEnum` and
            # serialises as a plain string - and nothing notices until
            # something asks for a member. See `state.restore_enum`. Numbers
            # have the same problem one type along: a price restored as the
            # string "1.2345" took trading down on 2026-09-08, because
            # `Intent.reward` subtracts it. See `state.restore_number`.
            #
            # An exact duplicate of this loop used to follow the `return`
            # below, unreachable, so a fix applied to one copy would have
            # looked applied and done nothing.
            value = restore_enum(cls, field.name, fields[field.name])
            object.__setattr__(made, field.name, restore_number(cls, field.name, value))
    return made
