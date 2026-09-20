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
is what let this through - `Volatility` was not on it.

This module is the second. The schema stops bad state being *loaded*; this
stops a *crash* if any ever is - a pickle that arrives by some other path, a
schema that is itself wrong, a class the walk cannot see. Neither subsumes the
other, and this one is cheap.
"""

from __future__ import annotations

import collections
import dataclasses
import enum
import functools
import typing
from typing import Any


@functools.cache
def _enum_fields(cls: type) -> dict[str, type]:
    """Field name -> enum type, for the fields declared as one.

    Cached because it resolves annotations, which is not free and never
    changes for a class.
    """
    try:
        hints = typing.get_type_hints(cls)
    except Exception:  # a forward reference this build cannot resolve
        return {}
    found = {}
    for field in dataclasses.fields(cls):
        hint = hints.get(field.name)
        if isinstance(hint, type) and issubclass(hint, enum.Enum):
            found[field.name] = hint
    return found


@functools.cache
def _number_fields(cls: type) -> dict[str, type]:
    """Field name -> `float` or `int`, for the fields declared as one.

    Cached for the reason `_enum_fields` is: resolving annotations is not free
    and never changes for a class.

    `bool` is excluded although it is a subclass of `int`. A flag restored from
    a string is a different problem with a different right answer, and
    `float("true")` is not it.
    """
    try:
        hints = typing.get_type_hints(cls)
    except Exception:  # a forward reference this build cannot resolve
        return {}
    found = {}
    for field in dataclasses.fields(cls):
        hint = hints.get(field.name)
        if hint in (float, int) and hint is not bool:
            found[field.name] = hint
    return found


def restore_number(cls: type, name: str, value: Any) -> Any:
    """Put a numeric field back to a number, or leave the value alone.

    See `shared-state.md` in research/docs.
    """
    kind = _number_fields(cls).get(name)
    if kind is None or type(value) is kind:
        return value
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return kind(value)
    if isinstance(value, str):
        try:
            return kind(float(value))
        except ValueError:
            return value
    return value


@functools.cache
def _deque_bounds(cls: type) -> dict[str, int]:
    """Field name -> `maxlen`, for fields whose default is a bounded deque.

    The bound is in the `default_factory`, not the annotation, so the only way
    to read it is to build one. Gated on the annotation first so this never
    calls an unrelated factory - `Learned._model` builds a river pipeline, and
    introspection has no business doing that. Cached like its neighbours.
    """
    try:
        hints = typing.get_type_hints(cls)
    except Exception:  # a forward reference this build cannot resolve
        return {}
    found = {}
    for field in dataclasses.fields(cls):
        hint = hints.get(field.name)
        if typing.get_origin(hint) is not collections.deque and hint is not collections.deque:
            continue
        if field.default_factory is dataclasses.MISSING:
            continue
        try:
            made = field.default_factory()
        except Exception:  # a factory that needs arguments it cannot get here
            continue
        if isinstance(made, collections.deque) and made.maxlen is not None:
            found[field.name] = made.maxlen
    return found


def restore_deque(cls: type, name: str, value: Any) -> Any:
    """Put a bounded deque field back inside its bound.

    **A bound that only the default carries is not a bound.** Pickle stores a
    deque's contents, and this restores by assigning the stored value straight
    onto the field, so a state written as a `list` - or written while the field
    still *was* a list - lands as a list and `maxlen` is gone. The field then
    grows for the life of the process while the declaration says it cannot.

    That is not hypothetical. `Cusum.events` was an unbounded list and reached
    350,672 live objects, about 1,100 a second, which was the growth behind the
    container's OOM kills; bounding the field alone would have been undone by
    the first restore. Every `deque(maxlen=...)` field in the codebase had the
    same hole, which is why this is here rather than in `Cusum`.

    Longer states keep their **newest** entries, which is what a deque with a
    `maxlen` would have kept had it been bounded all along.

    A stored deque is left exactly as it is, because pickle preserves `maxlen`
    and the stored bound is the more trustworthy of the two: `Zma._prices` is
    sized from the instance's `period`, so the factory's number is a placeholder
    for a default-constructed object and not this one's bound. Forcing the
    factory's cap onto it resized a restored window from 20 to 50. The factory
    is therefore only a fallback, for a value that arrives carrying no bound of
    its own - which is precisely the `list` case this exists for.
    """
    cap = _deque_bounds(cls).get(name)
    if cap is None:
        return value
    if isinstance(value, collections.deque):
        return value if value.maxlen is not None else collections.deque(value, maxlen=cap)
    if isinstance(value, list | tuple):
        return collections.deque(value, maxlen=cap)
    return value


def restore_enum(cls: type, name: str, value: Any) -> Any:
    """Put an enum field back to its enum, or leave the value alone.

    See `shared-state.md` in research/docs.
    """
    kind = _enum_fields(cls).get(name)
    if kind is None or isinstance(value, kind):
        return value
    try:
        return kind(value)
    except (ValueError, KeyError):
        # A member this build no longer has. The raw value is more useful than
        # an exception here - the caller sees something wrong at the point of
        # use rather than losing the whole file.
        return value


class Restorable:
    """Fills fields the saved state predates, rather than leaving them absent.

    See `shared-state.md` in research/docs.
    """

    __slots__ = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Take back `__setstate__` from the one `dataclasses` generates.

        See `shared-state.md` in research/docs.
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
            # values in field order** - that is what `_dataclass_getstate`
            # produces - not as a mapping. Missing this took production down:
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
                # mutable default - the bug this factory exists to prevent.
                value = field.default_factory()
            else:
                # A required field genuinely absent from the state. Defaulting
                # it would invent data; leaving it missing keeps the failure
                # loud and attributable, which for a required field is right.
                continue
            value = restore_enum(type(self), field.name, value)
            value = restore_number(type(self), field.name, value)
            value = restore_deque(type(self), field.name, value)
            # `object.__setattr__`, so this works on frozen dataclasses too.
            object.__setattr__(self, field.name, value)
