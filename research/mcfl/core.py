"""MCFL's types: every entity is frozen, has an identity, a direction, the bar it happened at and
the first bar at which it could have been known.

`known_at` is mandatory because it is the one field that keeps the language honest. A swing low at
bar p is not a swing low until three bars later; anything that reads it before then is reading the
future. The truncation test in `tests/test_causality.py` holds every entity to it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: The layer each type lives in. L0 is the bars themselves and L1 the geometric facts computed
#: from them (true range, gaps, bodies); neither is an entity.
LAYER = {
    "EXTREME": 2, "VOID": 2, "DISPLACE": 2, "BREAK": 2, "BREACH_REVERT": 2,
    "REVISIT": 2, "REJECT": 2, "ACCEPT": 2, "FAIL": 2, "EXPIRE": 2,
    "ORIGIN": 3, "LEG": 3, "ZONE": 3,
}
EVENT_TYPES = tuple(k for k, v in LAYER.items() if v == 2)
STRUCTURE_TYPES = tuple(k for k, v in LAYER.items() if v == 3)
RELATIONS = ("BEFORE", "AFTER", "TOUCH", "CROSS", "CONTAIN", "INVALIDATE")
#: tie-break inside one bar: what is observed comes before what is interpreted from it
ORDER = {t: i for i, t in enumerate(
    ("EXTREME", "BREACH_REVERT", "VOID", "DISPLACE", "BREAK", "ORIGIN", "LEG", "ZONE",
     "REVISIT", "REJECT", "ACCEPT", "FAIL", "EXPIRE"))}


class Dir(str, Enum):
    UP = "UP"
    DOWN = "DOWN"

    @property
    def arrow(self) -> str:
        return "↑" if self is Dir.UP else "↓"

    @property
    def letter(self) -> str:
        return "U" if self is Dir.UP else "D"

    def flip(self) -> Dir:
        return Dir.DOWN if self is Dir.UP else Dir.UP

    @staticmethod
    def of(side: int) -> Dir:
        return Dir.UP if side > 0 else Dir.DOWN


def make_id(kind: str, d: Dir, at: int, suffix: str = "") -> str:
    """Ids are built from content, not counters, so the same event parsed from a truncated series
    gets the same id."""
    return f"{kind}.{d.letter}.{at}{'.' + suffix if suffix else ''}"


def freeze(x: Any) -> Any:
    """Lists (from JSON) back to tuples, numpy scalars to Python ones, so entities stay hashable."""
    if isinstance(x, (list, tuple)):
        return tuple(freeze(v) for v in x)
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        return x.item()
    return x


def attrs_of(d: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted((k, freeze(v)) for k, v in d.items()))


@dataclass(frozen=True)
class Force:
    """How a leg got through the structure it broke. Units: ATR at the origin, bars."""
    magnitude: float  # (furthest price of the leg through the break - origin extreme) / ATR
    speed: float  # magnitude / duration, ATR per bar
    efficiency: float | None  # net close move / summed |close-to-close| moves, origin to break
    penetration: float  # break close past the reference / ATR
    surprise: float | None  # the leg's mean true range / the mean of the 20 bars before the origin
    duration: int  # bars from origin to break


@dataclass(frozen=True)
class Entity:
    """One event (L2) or structure (L3). Attributes are a sorted tuple of pairs so the dataclass
    stays frozen and hashable; read them with `get`."""
    id: str
    type: str
    dir: Dir
    at: int
    known_at: int
    attrs: tuple[tuple[str, Any], ...] = ()
    force: Force | None = None
    parts: tuple[str, ...] = ()  # constituent ids, for structures

    def __post_init__(self) -> None:
        if self.known_at < self.at:
            raise ValueError(f"{self.id}: known_at {self.known_at} before at {self.at}")

    @property
    def layer(self) -> int:
        return LAYER[self.type]

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self.attrs:
            if k == key:
                return v
        return default

    def field(self, key: str) -> Any:
        """A field or an attribute by name - what the grammar's clauses read."""
        if key in ("id", "type", "dir", "at", "known_at"):
            return getattr(self, key)
        return self.get(key)


@dataclass(frozen=True)
class Relation:
    kind: str
    src: str
    dst: str
    known_at: int


@dataclass(frozen=True)
class Failure:
    """A candidate the grammar refused, and why. Reported, never silently dropped."""
    candidate: str
    rule: str
    slot: str
    clause: str
    known_at: int


@dataclass(frozen=True)
class Transition:
    zone: str
    src: str
    dst: str
    at: int
    known_at: int
    event: str  # the entity whose arrival caused it


@dataclass(frozen=True)
class Chart:
    """A parsed series. `states` is each zone's state at the last bar - a property of where the
    series stops, so unlike everything else it has no `known_at` and is not prefix-invariant."""
    n: int
    entities: tuple[Entity, ...]
    relations: tuple[Relation, ...] = ()
    failures: tuple[Failure, ...] = ()
    transitions: tuple[Transition, ...] = ()
    states: tuple[tuple[str, str], ...] = ()
    pending: tuple[str, ...] = field(default=())  # candidates still FORMING at the last bar

    def by_id(self) -> dict[str, Entity]:
        return {e.id: e for e in self.entities}

    def of(self, *types: str) -> list[Entity]:
        return [e for e in self.entities if e.type in types]


def sort_key(e: Entity) -> tuple:
    """By known_at; within a bar, observations before what is built from them (ORDER), then by bar."""
    return (e.known_at, ORDER[e.type], e.at, e.dir.value, e.id)


# relations computed on demand: the temporal pair is too many to materialise
def before(a: Entity, b: Entity) -> bool:
    """BEFORE(a, b): a happened at an earlier bar than b."""
    return a.at < b.at


def after(a: Entity, b: Entity) -> bool:
    """AFTER(a, b): the converse of BEFORE."""
    return a.at > b.at
