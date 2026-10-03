"""A parsed chart as a sentence of tokens, as readable text, and as JSON that round-trips exactly.

The chart sentence is every L2 event plus a ZONE token when a zone qualifies, ordered by
`known_at`: the order a reader watching the bars live would have learned them. ORIGIN and LEG are
left out of it - an ORIGIN is an EXTREME seen again, a LEG the span between tokens already there.
`episode()` gives one zone's own sentence, ORIGIN included, in the order its parts happened.

Two legs from different origins can break the same reference on the same bar, or displace on the
same bar; the sentence prints one token per (type, direction, bar) and keeps the longest leg's.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from mcfl.core import Chart, Dir, Entity, Failure, Force, Relation, Transition, freeze, sort_key

SENTENCE_TYPES = ("EXTREME", "BREACH_REVERT", "VOID", "DISPLACE", "BREAK", "ZONE",
                  "REVISIT", "REJECT", "ACCEPT", "FAIL", "EXPIRE")

FORCE_BINS = ((2.0, "weak"), (4.0, "mid"), (float("inf"), "strong"))
"""BREAK magnitude (ATR, origin to the leg's furthest point): under 2 weak, 2-4 mid, 4+ strong."""
VOID_BINS = ((0.25, "s"), (0.75, "m"), (float("inf"), "l"))
"""VOID size in ATR at its own bar: under 0.25 small, 0.25-0.75 medium, 0.75+ large."""


def _bin(x: float | None, bins: tuple) -> str:
    if x is None:
        return "na"
    return next(name for edge, name in bins if x < edge)


def token(e: Entity, bins: bool = False) -> str:
    t = f"{e.type}{e.dir.arrow}"
    if not bins:
        return t
    if e.type == "BREAK" and e.force is not None:
        return f"{t}[force:{_bin(e.force.magnitude, FORCE_BINS)}]"
    if e.type == "VOID":
        return f"{t}[size:{_bin(e.get('size_atr'), VOID_BINS)}]"
    if e.type == "REVISIT":
        k = e.get("count")
        return f"{t}[n:{k if k < 3 else '3+'}]"
    return t


def sentence(chart: Chart, types: tuple[str, ...] = SENTENCE_TYPES) -> list[Entity]:
    """The chart's entities that make its sentence, one per (type, direction, bar), by known_at."""
    seen, out = set(), []
    # the longest leg first: an earlier origin sorts first among same-bar BREAKs and DISPLACEs
    for e in sorted((e for e in chart.entities if e.type in types),
                    key=lambda e: (*sort_key(e)[:4], _origin_at(e))):
        k = (e.type, e.dir, e.at)
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out


def _origin_at(e: Entity) -> int:
    o = e.get("origin")
    return int(o.split(".")[2]) if o else -1


def tokens(chart: Chart, bins: bool = False, types: tuple[str, ...] = SENTENCE_TYPES) -> list[str]:
    return [token(e, bins) for e in sentence(chart, types)]


def episode(chart: Chart, zone_id: str, bins: bool = False) -> list[str]:
    """One zone's sentence: its parts in the order they happened, then its lifecycle."""
    ids = chart.by_id()
    z = ids[zone_id]
    parts = sorted((ids[p] for p in z.parts), key=lambda e: (e.at, sort_key(e)))
    life = sorted((e for e in chart.entities if e.get("zone") == zone_id), key=sort_key)
    return [token(e, bins) for e in parts + life]


def to_text(chart: Chart, bins: bool = False, verbose: bool = False) -> str:
    """The sentence on one line, or one token a line with its bars, id and attributes."""
    ents = sentence(chart)
    if not verbose:
        return " ".join(token(e, bins) for e in ents)
    lines = [f"# MCFL v0  bars={chart.n}  tokens={len(ents)}", "# known_at  at  token  id  attributes"]
    for e in ents:
        extra = " ".join(f"{k}={_fmt(v)}" for k, v in e.attrs)
        if e.force is not None:
            extra += " force=" + ",".join(f"{k}:{_fmt(v)}" for k, v in asdict(e.force).items())
        lines.append(f"{e.known_at:>6} {e.at:>6}  {token(e, bins):<22} {e.id:<26} {extra}")
    return "\n".join(lines)


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, tuple):
        return "(" + ",".join(_fmt(x) for x in v) + ")"
    return str(v)


# ---------------------------------------------------------------- JSON

def to_dict(chart: Chart) -> dict:
    def ent(e: Entity) -> dict:
        d = {"id": e.id, "type": e.type, "dir": e.dir.value, "at": e.at, "known_at": e.known_at,
             "attrs": {k: v for k, v in e.attrs}}
        if e.force is not None:
            d["force"] = asdict(e.force)
        if e.parts:
            d["parts"] = list(e.parts)
        return d
    return {"mcfl": 0, "n": chart.n,
            "entities": [ent(e) for e in chart.entities],
            "relations": [asdict(r) for r in chart.relations],
            "failures": [asdict(f) for f in chart.failures],
            "transitions": [asdict(t) for t in chart.transitions],
            "states": dict(chart.states), "pending": list(chart.pending)}


def from_dict(d: dict) -> Chart:
    def ent(x: dict) -> Entity:
        return Entity(x["id"], x["type"], Dir(x["dir"]), x["at"], x["known_at"],
                      tuple(sorted((k, freeze(v)) for k, v in x["attrs"].items())),
                      Force(**x["force"]) if "force" in x else None, tuple(x.get("parts", ())))
    return Chart(n=d["n"], entities=tuple(ent(x) for x in d["entities"]),
                 relations=tuple(Relation(**r) for r in d["relations"]),
                 failures=tuple(Failure(**f) for f in d["failures"]),
                 transitions=tuple(Transition(**t) for t in d["transitions"]),
                 states=tuple(sorted(d["states"].items())), pending=tuple(d["pending"]))


def dumps(chart: Chart, **kw: Any) -> str:
    return json.dumps(to_dict(chart), ensure_ascii=False, allow_nan=False, **kw)


def loads(s: str) -> Chart:
    return from_dict(json.loads(s))
