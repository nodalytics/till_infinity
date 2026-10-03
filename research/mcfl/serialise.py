"""A parsed chart as sentences, as readable text, and as JSON that round-trips exactly.

Three sentences:
- the bar sentence (`bar_words`): one L1 word a bar, `BULL(L,T,N,S)/HH`;
- the event sentence (`tokens`, v0's): every v0 L2 event plus a ZONE token when a zone qualifies,
  ordered by `known_at`, the order a reader watching the bars live would have learned them. ORIGIN
  and LEG are left out of it - an ORIGIN is an EXTREME seen again, a LEG the span between tokens
  already there. `episode()` gives one zone's own sentence, ORIGIN included;
- the interleaved view (`interleaved`): the bar words with the L2/L3 events (v0's and the candle
  productions) placed after the word of the bar at which they became known.
`derivation()` prints any entity's tree through `parts`, down to the candle words.

Two legs from different origins can break the same reference on the same bar, or displace on the
same bar; the sentence prints one token per (type, direction, bar) and keeps the longest leg's.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from mcfl.candles import word
from mcfl.core import Chart, Dir, Entity, Failure, Force, Relation, Transition, freeze, sort_key

SENTENCE_TYPES = ("EXTREME", "BREACH_REVERT", "VOID", "DISPLACE", "BREAK", "ZONE",
                  "REVISIT", "REJECT_PATH", "ACCEPT", "FAIL", "EXPIRE")
"""v0's event sentence (v0's REJECT is v1's REJECT_PATH)."""
CANDLE_EVENTS = ("PIN", "ENGULF", "INSIDE_BREAK", "STAR", "DISPLACE_C", "DELIVERY_SHIFT", "REJECT")
"""The candle-level productions."""
V1_TYPES = SENTENCE_TYPES + CANDLE_EVENTS

FORCE_BINS = ((2.0, "weak"), (4.0, "mid"), (float("inf"), "strong"))
"""BREAK magnitude (ATR, origin to the leg's furthest point): under 2 weak, 2-4 mid, 4+ strong."""
VOID_BINS = ((0.25, "s"), (0.75, "m"), (float("inf"), "l"))
"""VOID size in ATR at its own bar: under 0.25 small, 0.25-0.75 medium, 0.75+ large."""
AGE_BINS = ((10, "young"), (20, "mid"), (float("inf"), "old"))
"""BREAK ref_age in bars (break bar - the broken EXTREME's bar): under 10 young, 10-19 mid, 20+ old.
On four 5,000-bar walks (1,584 breaks) the median is 11 bars, the 90th percentile 22: about 45%
young, 41% mid, 14% old."""
TOOK_BINS = ((1, "0"), (2, "1"), (3, "2"), (float("inf"), "3+"))
"""BREAK swings_taken: 0, 1, 2, 3+ standing swing levels the break close cleared at once."""


def _bin(x: float | None, bins: tuple) -> str:
    if x is None:
        return "na"
    return next(name for edge, name in bins if x < edge)


def token(e: Entity, bins: bool = False) -> str:
    t = f"{e.type}{e.dir.arrow}"
    if not bins:
        return t
    if e.type == "BREAK" and e.force is not None:
        return (f"{t}[force:{_bin(e.force.magnitude, FORCE_BINS)},age:{_bin(e.get('ref_age'), AGE_BINS)},"
                f"took:{_bin(e.get('swings_taken'), TOOK_BINS)}]")
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
    lines = [f"# MCFL v1  bars={chart.n}  tokens={len(ents)}", "# known_at  at  token  id  attributes"]
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


# ---------------------------------------------------------------- v1: the bar sentence and the interleaved view

def _by_bar(chart: Chart) -> tuple[dict[int, Entity], dict[int, Entity]]:
    c = {e.at: e for e in chart.entities if e.type == "CANDLE"}
    r = {e.at: e for e in chart.entities if e.type == "BAR_RELATION"}
    return c, r


def bar_words(chart: Chart) -> list[str]:
    """One word a bar: `BULL(L,T,N,S)/HH` - direction(size, body, upper wick, lower wick)/relation
    to the previous bar (IN, OUT, HH, LL; +E when the body engulfs). The first bar has no relation;
    warm-up bars print their classes as W."""
    c, r = _by_bar(chart)
    return [word(c.get(t), r.get(t)) for t in range(chart.n)]


def bar_sentence(chart: Chart) -> str:
    return " ".join(bar_words(chart))


def interleaved(chart: Chart, types: tuple[str, ...] = V1_TYPES, bins: bool = False) -> list[str]:
    """The bar words with every L2/L3 event of `types` placed after the word of the bar at which it
    became known (its known_at), in the event sentence's order - so a reader sees an EXTREME three
    words after its own bar, when it could first have been known."""
    ws = bar_words(chart)
    at: dict[int, list[str]] = {}
    for e in sentence(chart, types):
        at.setdefault(e.known_at, []).append(token(e, bins))
    out = []
    for t, w in enumerate(ws):
        out.append(w)
        out += at.get(t, [])
    return out


def interleaved_text(chart: Chart, types: tuple[str, ...] = V1_TYPES, bins: bool = False,
                     lo: int = 0, hi: int | None = None) -> str:
    """One bar a line: bar, word, then the events known at that bar."""
    ws = bar_words(chart)
    at: dict[int, list[str]] = {}
    for e in sentence(chart, types):
        at.setdefault(e.known_at, []).append(token(e, bins))
    hi = chart.n if hi is None else hi
    return "\n".join(f"{t:>6}  {ws[t]:<22} {' '.join(at.get(t, []))}".rstrip() for t in range(lo, hi))


def derivation(chart: Chart, eid: str, depth: int = 0, ids: dict[str, Entity] | None = None) -> str:
    """An entity's derivation tree through `parts`, down to the candle words. A ZONE prints its
    ORIGIN (and the EXTREME under it), DISPLACE, VOIDs and BREAK, each over the tokens it consumed."""
    ids = chart.by_id() if ids is None else ids
    e = ids[eid]
    if e.type in ("CANDLE", "BAR_RELATION"):
        label = word(e) if e.type == "CANDLE" else f"BAR_RELATION {e.get('rel')}" + (
            f" engulf {e.get('engulf')}" if e.get("engulf") != "NONE" else "")
        return f"{'  ' * depth}{label}  [{e.id}]"
    lines = [f"{'  ' * depth}{e.type}{e.dir.arrow}  [{e.id}  at {e.at}  known {e.known_at}]"]
    for p in e.parts:
        lines.append(derivation(chart, p, depth + 1, ids))
    return "\n".join(lines)


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
    return {"mcfl": 1, "n": chart.n,
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
