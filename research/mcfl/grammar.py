"""The grammar: production rules as data, and one matcher that reads them.

A rule names a head structure, the anchor it grows from, and slots. Each slot is a type, a count
and clauses - small (field, op, expression) triples evaluated against the entities already bound.
The canonical rule, with defaults that reproduce `zone_events.py`'s qualified zone (V = 1):

    ZONE_UP := ORIGIN_UP DISPLACE_UP VOID_UP+ BREAK_UP          (and mirrored for DOWN)

    BREAK     from this origin's leg, within 20 bars of it
    DISPLACE  from this origin's leg, at or before the break
    VOID+     between origin + 2 and the break, at least 0.1 ATR (the origin's ATR)

A candidate is decided when its horizon structure (the anchor's LEG) has closed. Until then it is
FORMING. When it is decided and a slot cannot be filled, the failure names the slot and the clause
that emptied it. Adding a production rule means adding a row to RULES, not an if.
"""
from __future__ import annotations

import bisect
import operator
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from mcfl.core import Dir, Entity, Failure, attrs_of, make_id

ZONE_BREAK_MAX = 20
"""Bars from the origin to the break, at most (zone_events: a BOS within 20 bars of the origin)."""
VOID_MIN = 0.1
"""Smallest VOID on the path, in the origin's ATR (zone_events' GAP_MIN)."""
VOID_PATH_START = 2
"""The first bar a gap can belong to the leg: it needs the origin bar as its bar k-2."""

OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, ">": operator.gt, "<": operator.lt}

# An expression is a number, a path "slot.field" into a bound entity, or ("+" | "*", expr, expr).
Expr = Any


@dataclass(frozen=True)
class Clause:
    field: str
    op: str
    rhs: Expr

    def text(self) -> str:
        def show(x: Expr) -> str:
            if isinstance(x, tuple):
                return f"({show(x[1])} {x[0]} {show(x[2])})"
            return str(x)
        return f"{self.field} {self.op} {show(self.rhs)}"


@dataclass(frozen=True)
class Slot:
    name: str
    type: str
    min: int = 1
    max: int | None = 1  # None: as many as match (the + in VOID+)
    where: tuple[Clause, ...] = ()


@dataclass(frozen=True)
class Rule:
    head: str  # the structure it builds
    anchor: str  # the slot it grows from, and the anchor's type
    horizon: str  # structure type, same id stem as the anchor, whose closing decides a candidate
    slots: tuple[Slot, ...]  # in binding order: a slot's clauses may read only earlier slots
    sequence: tuple[str, ...]  # the canonical order of the right-hand side, for print and spec

    def bnf(self, d: Dir) -> str:
        names = {s.name: s for s in self.slots}

        def tok(n: str) -> str:
            s = names[n]
            return f"{s.type}_{d.value}{'+' if s.max is None else ''}"
        return f"{self.head}_{d.value} := " + " ".join(tok(n) for n in self.sequence)


C = Clause
RULES: dict[str, Rule] = {
    "ZONE": Rule(
        head="ZONE", anchor="origin", horizon="LEG",
        slots=(
            Slot("origin", "ORIGIN"),
            Slot("break", "BREAK", where=(
                C("origin", "==", "origin.id"),
                C("at", "<=", ("+", "origin.at", ZONE_BREAK_MAX)))),
            Slot("displace", "DISPLACE", where=(
                C("origin", "==", "origin.id"),
                C("at", "<=", "break.at"))),
            Slot("void", "VOID", max=None, where=(
                C("at", ">=", ("+", "origin.at", VOID_PATH_START)),
                C("at", "<=", "break.at"),
                C("size", ">=", ("*", "origin.atr", VOID_MIN)))),
        ),
        sequence=("origin", "displace", "void", "break"),
    ),
}


def _eval(x: Expr, bound: dict[str, list[Entity]]) -> Any:
    if isinstance(x, tuple):
        op, l, r = x
        lv, rv = _eval(l, bound), _eval(r, bound)
        return lv + rv if op == "+" else lv * rv
    if isinstance(x, str) and "." in x:
        slot, f = x.split(".", 1)
        return bound[slot][0].field(f)
    return x


def _holds(e: Entity, c: Clause, bound: dict[str, list[Entity]]) -> bool:
    v = e.field(c.field)
    return v is not None and OPS[c.op](v, _eval(c.rhs, bound))


class Index:
    """Entities by (type, dir), sorted by bar, so a slot scans only its own kind."""

    def __init__(self, entities: Iterable[Entity]) -> None:
        self.by: dict[tuple[str, Dir], list[Entity]] = {}
        self.ids: dict[str, Entity] = {}
        for e in entities:
            self.by.setdefault((e.type, e.dir), []).append(e)
            self.ids[e.id] = e
        for v in self.by.values():
            v.sort(key=lambda e: (e.at, e.id))
        self.ats = {k: [e.at for e in v] for k, v in self.by.items()}

    def narrow(self, slot: Slot, d: Dir, bound: dict[str, list[Entity]], upto: int) -> tuple[list[Entity], str]:
        """Apply the slot's clauses in order to what is known by `upto`; a clause on the bar is a
        binary search. Returns what survives, and the clause that left fewer than the slot's
        minimum (or ""). The grammar sees only what was known when it decides - otherwise even
        the reason for a failure could depend on the future."""
        full = self.by.get((slot.type, d), [])
        pool = full[:bisect.bisect_right(self.ats[(slot.type, d)], upto)] if full else full
        pool = [e for e in pool if e.known_at <= upto]
        for c in slot.where:
            if c.field == "at" and c.op in (">=", "<="):
                ats = [e.at for e in pool]
                v = _eval(c.rhs, bound)
                pool = pool[bisect.bisect_left(ats, v):] if c.op == ">=" else pool[:bisect.bisect_right(ats, v)]
            else:
                pool = [e for e in pool if _holds(e, c, bound)]
            if len(pool) < slot.min:
                return pool, c.text()
        return pool, "" if len(pool) >= slot.min else "exists"


def match(rule: Rule, anchor: Entity, idx: Index, upto: int) -> tuple[dict[str, list[Entity]] | None, Slot | None, str]:
    """Bind every slot for this anchor from what is known by `upto` (the horizon's known_at), or
    say which slot and clause could not be filled."""
    bound: dict[str, list[Entity]] = {rule.anchor: [anchor]}
    for slot in rule.slots:
        if slot.name == rule.anchor:
            continue
        pool, why = idx.narrow(slot, anchor.dir, bound, upto)
        if why:
            return None, slot, why
        bound[slot.name] = pool if slot.max is None else pool[:slot.max]
    return bound, None, ""


def apply(entities: list[Entity], rules: dict[str, Rule] | None = None) -> tuple[list[Entity], list[Failure], list[str]]:
    """Every anchor of every rule: the structures accepted, the failures, and the ids still forming."""
    rules = RULES if rules is None else rules
    idx = Index(entities)
    built, failed, pending = [], [], []
    for name, rule in rules.items():
        anchor_type = next(s.type for s in rule.slots if s.name == rule.anchor)
        for d in Dir:
            for anc in idx.by.get((anchor_type, d), []):
                stem = anc.id.split(".", 1)[1]  # "U.57": the horizon shares the anchor's stem
                hz = idx.ids.get(f"{rule.horizon}.{stem}")
                if hz is None:
                    pending.append(anc.id)
                    continue
                upto = max(hz.known_at, anc.known_at)
                bound, slot, why = match(rule, anc, idx, upto)
                rname = f"{name}_{d.value}"
                if bound is None:
                    failed.append(Failure(anc.id, rname, slot.name, why, upto))
                    continue
                parts = [e for n in rule.sequence for e in bound[n]]
                built.append(_build(rule, anc, bound, parts))
    return built, failed, pending


def _build(rule: Rule, anc: Entity, bound: dict[str, list[Entity]], parts: list[Entity]) -> Entity:
    known = max(e.known_at for e in parts)
    attrs: dict[str, Any] = {"rule": f"{rule.head}_{anc.dir.value}"}
    if rule.head == "ZONE":
        brk = bound["break"][0]
        attrs.update(far=anc.get("far"), near=anc.get("near"), band=anc.get("band"), atr=anc.get("atr"),
                     break_at=brk.at, level=brk.get("level"), n_voids=len(bound["void"]),
                     magnitude=brk.force.magnitude if brk.force else None)
    return Entity(make_id(rule.head, anc.dir, anc.at), rule.head, anc.dir, anc.at, known,
                  attrs_of(attrs), parts=tuple(e.id for e in parts))
