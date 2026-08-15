"""Restoring pickled state that predates a field.

Everything in this package that survives a restart is a `slots=True` dataclass,
and a slots class has no `__dict__` to fall back on. So a field added after a
state file was written is not *defaulted* on restore, it is **missing**, and
every read of it raises `AttributeError`.

That is not a theoretical migration problem. Production saves these models and
restores them on every start, so a new field is a restart-time crash. It has
happened twice: `_touch_eras` on `Engine`, and `_tick`, `_steps` and `_grid` on
`Volatility` hours later.

Worse, it fails quietly. The throw lands inside the structures consumer, so
nothing crashes: the container stays healthy, the bus fills, and the pipeline
stops producing. Four hours at 11% CPU with an empty error log, across twelve
deploys, each one restoring the same stale state and dying the same way.

## Two guards, and why both

[`store._schema`](store.py) is the first and the more important: it hashes the
shape of every persisted dataclass, so a changed field invalidates the file and
the service starts cold. Cold is slow and correct. That guard now derives its
list by walking the package, because the version with seven hand-written names
is what let this through — `Volatility` was not on it.

This module is the second. The schema stops bad state being *loaded*; this
stops a *crash* if any ever is — a pickle that arrives by some other path, a
schema that is itself wrong, a class the walk cannot see. Neither subsumes the
other, and this one is cheap.
"""

from __future__ import annotations

import dataclasses
from typing import Any


class Restorable:
    """Fills fields the saved state predates, rather than leaving them absent.

    `__slots__ = ()` is load-bearing. A base class without it gives every
    subclass instance a `__dict__`, which would silently undo the `slots=True`
    these classes are declared with — turning a memory fix into a memory
    regression on a box that has been OOM-killed five times.

    Not a dataclass itself, so a frozen subclass stays legal: dataclasses only
    object to a frozen class inheriting from a non-frozen *dataclass*.
    """

    __slots__ = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Take back `__setstate__` from the one `dataclasses` generates.

        A `frozen=True, slots=True` dataclass gets a `_dataclass_setstate`
        written onto the class itself, and a method on the class beats one
        inherited from a base. So merely listing this mixin does nothing for
        every frozen value object here — `Features`, `Inference`, `Point`,
        `Approach`, `Signal` — which is most of them, and it does nothing
        *silently*, which is the failure this whole module exists to stop.

        The generated version copies what is in the state and no more, so a
        field added after the save stays missing. Replacing it keeps pickle's
        contract and adds the defaulting.

        Only the generated one is replaced. A class that writes its own is
        making a deliberate choice and keeps it.
        """
        super().__init_subclass__(**kwargs)
        existing = cls.__dict__.get("__setstate__")
        if existing is not None and getattr(existing, "__name__", "") != "_dataclass_setstate":
            return
        cls.__setstate__ = Restorable.__setstate__  # type: ignore[method-assign]

    def __setstate__(self, state: Any) -> None:
        # Pickle hands a slots class `(None, {slot: value})`; a class with both
        # a dict and slots gets both halves populated. Older or hand-rolled
        # states may be a plain mapping.
        fields = dataclasses.fields(self)
        values: dict[str, Any] = {}
        if isinstance(state, list):
            # A `frozen=True, slots=True` dataclass pickles as a **list of
            # values in field order** — that is what `_dataclass_getstate`
            # produces — not as a mapping. Missing this took production down:
            # every frozen value object restored with an empty mapping, so
            # optional fields silently took defaults and required ones were
            # skipped entirely, leaving `Features` with no `side` at all.
            #
            # Zipping is also exactly the migration wanted. A state written
            # before a field existed is shorter, `zip` stops at the shorter,
            # and the fields beyond it fall through to their defaults below.
            values = dict(zip((f.name for f in fields), state, strict=False))
        elif isinstance(state, tuple):
            # Slots without frozen: `(None, {slot: value})`. A class with both
            # a dict and slots fills in both halves.
            for part in state:
                if isinstance(part, dict):
                    values.update(part)
        elif isinstance(state, dict):
            values = state

        for field in fields:
            if field.name in values:
                value = values[field.name]
            elif field.default is not dataclasses.MISSING:
                value = field.default
            elif field.default_factory is not dataclasses.MISSING:
                # Called per instance, so two restored objects never share a
                # mutable default — the bug this factory exists to prevent.
                value = field.default_factory()
            else:
                # A required field genuinely absent from the state. Defaulting
                # it would invent data; leaving it missing keeps the failure
                # loud and attributable, which for a required field is right.
                continue
            # `object.__setattr__`, so this works on frozen dataclasses too.
            object.__setattr__(self, field.name, value)
