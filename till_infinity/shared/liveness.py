"""Does a field carry anything, and does anybody ask.

## Why this exists

Across the last 20,000 production `structures` outcomes, `run_vol` and `pivot`
are **identically zero on every row**. They are published on every level call,
journalled on every outcome, and carried into the models that consume those
features. A model weighting a constant learns nothing from it and spends
capacity doing so; a research cut on it finds nothing and cannot say whether the
effect is absent or the column is dead.

Neither is new. Both have been zero for as long as the journal reaches, and
nothing noticed until somebody cut by them by hand.

The same fault, one step earlier, nearly cost a month: a collector for option
gamma was being planned on Yahoo's `openInterest`, which returns **zero on 366
of 366 SPY contracts** while `volume` on the same chain reads 1,587,783.
`prices/options.py` already names the failure mode - *"not a number nothing
reads, but a number read as more than it is"* - and it happened anyway, because
nothing systematically asks.

This asks. One question, mechanically: **does it vary?**

## Three states, because they want different actions

* **constant** - one distinct value across the sample. Dead.
* **near-constant** - above `NEAR` share on a single value. Alive by the letter,
  useless in practice, and the shape a field takes while it is dying.
* **absent** - the key is not on the rows at all. A different fault from being
  present and zero, and currently indistinguishable in every cut this project
  makes.

## What it deliberately ignores

Strings and booleans. This asks whether a *number* varies; reporting `side` as
constant because every row is a buy would bury the numeric answers under noise,
and a flag that is always true is a different conversation from a feature that
is always zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

#: Share of rows on a single value above which a field is near-constant. It
#: still varies, so `constant` is None - but a feature that moves on one row in
#: two hundred is not carrying information, it is decaying.
NEAR = 0.99


@dataclass(slots=True)
class Reading:
    """What one numeric field did across a sample."""

    seen: int = 0
    distinct: int = 0
    #: The single value, when there is only one. `None` means it varies - and
    #: `None` rather than a sentinel because zero is the value this most often
    #: takes, so any numeric sentinel would be ambiguous with a real answer.
    constant: float | None = None
    #: Share of rows holding the most common value.
    share_top: float = 0.0
    share_zero: float = 0.0
    _counts: dict[float, int] = field(default_factory=dict, repr=False)

    @property
    def near_constant(self) -> bool:
        """Varies, but barely. Alive by the letter; dying in practice."""
        return self.constant is None and self.share_top >= NEAR

    @property
    def alive(self) -> bool:
        return self.constant is None and not self.near_constant

    def describe(self) -> str:
        if self.constant is not None:
            return f"constant {self.constant:g} across {self.seen}"
        if self.near_constant:
            return f"{self.share_top:.1%} on one value across {self.seen}"
        return f"{self.distinct} values across {self.seen}"


def _numeric(value: Any) -> bool:
    """A number, and not a flag. `True` is an `int` and is not a measurement."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def survey(rows: Iterable[Mapping[str, Any]], within: str | None = None) -> dict[str, Any]:
    """Every numeric key, and whether it carries information.

    `within` groups first, returning `stratum -> field -> Reading`. That matters
    because a field can be dead in one producer and alive overall - which is
    exactly the shape `run_vol` would take if only one of its writers were
    broken, and the pooled survey would call it alive and be useless.
    """
    if within is not None:
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row.get(within, "unknown")), []).append(row)
        return {name: survey(part) for name, part in grouped.items()}

    found: dict[str, Reading] = {}
    for row in rows:
        for key, value in row.items():
            if not _numeric(value):
                continue
            reading = found.get(key)
            if reading is None:
                reading = found[key] = Reading()
            reading.seen += 1
            number = float(value)
            reading._counts[number] = reading._counts.get(number, 0) + 1

    for reading in found.values():
        counts = reading._counts
        reading.distinct = len(counts)
        top = max(counts.values())
        reading.share_top = top / reading.seen if reading.seen else 0.0
        reading.share_zero = counts.get(0.0, 0) / reading.seen if reading.seen else 0.0
        reading.constant = next(iter(counts)) if len(counts) == 1 else None
    return found


def assert_alive(rows: Iterable[Mapping[str, Any]], *keys: str) -> None:
    """Raise if any named key is constant or absent across `rows`.

    For a harness to call on the columns it is about to cut by, so a dead field
    is a loud failure rather than a flat table somebody then tries to explain.
    """
    got = survey(rows)
    dead = []
    for key in keys:
        reading = got.get(key)
        if reading is None:
            dead.append(f"{key} (absent)")
        elif reading.constant is not None:
            dead.append(f"{key} ({reading.describe()})")
    if dead:
        raise ValueError(
            "these fields carry no information and cannot be cut by: " + ", ".join(dead)
        )


def report(rows: Iterable[Mapping[str, Any]], within: str | None = None) -> str:
    """The dead and the dying, as a line somebody will actually read.

    Empty when everything varies, so it can be logged unconditionally without
    becoming noise - the tallies in `structures.service` take the same line, and
    for the same reason: a check nobody reads settles nothing.
    """
    got = survey(rows, within)
    if within is not None:
        parts = [
            f"{name}: {inner}"
            for name, part in sorted(got.items())
            for inner in (_line(part),)
            if inner
        ]
        return "; ".join(parts)
    return _line(got)


def _line(readings: dict[str, Reading]) -> str:
    dead = sorted(k for k, v in readings.items() if v.constant is not None)
    dying = sorted(k for k, v in readings.items() if v.near_constant)
    parts = []
    if dead:
        parts.append(f"{len(dead)} constant ({', '.join(dead)})")
    if dying:
        parts.append(f"{len(dying)} near-constant ({', '.join(dying)})")
    return ", ".join(parts)
