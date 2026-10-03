"""The grammar: production rules as data, and the matchers that read them.

Two kinds of rule, both tables:

WORDS - productions over a fixed window of L1 tokens, the bars' own words. A word names the token
cells it consumes (offsets from the event bar) and clauses over their fields, `"k.field"` for the
token k bars from the event. Clauses are usually written with the qualifier syntax, compiled by
`q()` and `run()`:

    qualified := "CANDLE[" qual ("," qual)* "]"
    run       := "RUN[" "k" ("≥" | "=") INT ("," qual)* "]"     K consecutive tokens that all qualify,
                                                                at the K-th (once per run)
    qual      := key op value | NAME | "not" NAME
    op        := "=" | "!=" | "≥" | ">=" | "≤" | "<=" | ">" | "<"
    key       := "dir" | "size" | "body" | "upper" | "lower"          fuzzy classes (body also takes grades)
               | "conv" | "force" | "wick.up" | "wick.low"            strength grades
               | "wick.up.share" | "wick.low.share"                   strength grades of the wick share
               | "wick.up.body" | "wick.low.body"                     the rejection ratio, a number
               | "close"                                              Q1..Q4
               | "rel" | "engulf" | "beyond"                          the BAR_RELATION token
    NAME      := a named point relation (OPEN_GAP_UP, HIGH_AT_PREV_HIGH, ...) or its alias

`body` with a grade (WEAK..DOMINANT) reads the body's force grade (body_atr); with a class
(NONE..TREND) the fuzzy class. Ordered values compare by rank (`body≥STRONG` is STRONG or DOMINANT);
`≥` against WARMUP never holds. A clause on classes or grades is a pattern; a clause on the lexeme's
prices (`"0.low" > "-2.high"`) is the semantic condition of an attributed rule. Each word is written
for the up side and run on the token table and on the flipped one (`candles.frame`). Words are
evaluated over all bars at once.

    EXTREME_UP     := C-3 C-2 C-1 C0 C+1 C+2 C+3   where C-k.high < C0.high, C+k.high <= C0.high
    VOID_UP        := C-2 C-1 C0                   where C0.low > C-2.high
    PIN_UP         := CANDLE[wick.low≥STRONG, body≤MODERATE, close≥Q3, wick.up≤WEAK]
    ENGULF_UP      := CANDLE[dir=BEAR] CANDLE[dir=BULL, engulf=BULL]
    INSIDE_BREAK_UP:= CANDLE[rel=INSIDE] CANDLE[beyond=ABOVE]     the close beyond the mother bar
    STAR_UP        := CANDLE[dir=BEAR, body≥LARGE] CANDLE[body≤SMALL] CANDLE[dir=BULL, body≥LARGE]
    DISPLACE_C_UP  := RUN[k≥2, dir=BULL, body≥STRONG, close=Q4]
                    | CANDLE[dir=BULL, size=EXTREMELY_LARGE, body≥DOMINANT, close=Q4]

SCANS - productions over a variable run of tokens, written as code with their syntax and condition
alongside (like the level rules in parse.py):

    DELIVERY_SHIFT_UP := CANDLE[dir=BEAR]+ CANDLE[dir≠BEAR]{0,2} CANDLE[dir=BULL]
                         where the BULL close > the open of the run's first BEAR token
                         and the BULL token is at most 3 bars after the run's last one
                         (the desk's CISD, `research/ideas/zones.py::_cisd`, exactly)

RULES - productions over entities: a head, an anchor slot, and slots, each a type, a count and
clauses (field, op, expression) over the slots already bound. A candidate is decided when its
horizon structure has closed (ZONE: the anchor's LEG) or its window has (REJECT: `decide`). Clauses
read entities through `core.view`, so they too are written for the up side. The canonical rule,
with defaults that reproduce `zone_events.py`'s qualified zone (V = 1):

    ZONE_UP := ORIGIN_UP DISPLACE_UP VOID_UP+ BREAK_UP          (and mirrored for DOWN)

    BREAK     from this origin's leg, within 20 bars of it
    DISPLACE  from this origin's leg, at or before the break
    VOID+     between origin + 2 and the break, at least 0.1 ATR (the origin's ATR)

    REJECT_UP := REVISIT_UP CANDLE[wick.low≥STRONG]     the first CANDLE in the revisit's reaction
                                         window with a strong wick toward the zone and a close above
                                         the zone's near edge, before any FAIL of the zone

When a ZONE candidate is decided and a slot cannot be filled, the failure names the slot and the
clause that emptied it. Pattern rules do not report failures: a bar that is not a PIN is not a
failed candidate. Adding a production means adding a row, not an if.
"""
from __future__ import annotations

import bisect
import operator
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np

from mcfl.candles import BODY, GRADE, QUARTILES, REL_FIELDS, SIZE, WGRADE, WICK, Table, frame
from mcfl.core import (COMPOSITE_POINTS, NAMED_POINTS, NEG_FIELD, POINT_ALIASES, SIDES, Dir, Entity, Failure,
                       attrs_of, make_id, swap_key, view)

ZONE_BREAK_MAX = 20
"""Bars from the origin to the break, at most (zone_events: a BOS within 20 bars of the origin)."""
VOID_MIN = 0.1
"""Smallest VOID on the path, in the origin's ATR (zone_events' GAP_MIN)."""
VOID_PATH_START = 2
"""The first bar a gap can belong to the leg: it needs the origin bar as its bar k-2."""
SWING = 3
"""Bars left and right of an EXTREME (a 3/3 pivot), as in `zone_events.py`. Known SWING bars later."""
REACTION_BARS = 3
"""A REJECT's window: the REVISIT bar and the next REACTION_BARS - 1 bars."""

OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, "!=": operator.ne, ">": operator.gt, "<": operator.lt,
       "in": lambda a, b: a in b}

# An expression is a number, a string constant, a frozenset (for `in`), a path "slot.field" into a
# bound entity (or "k.field" into a token cell), or ("+" | "*", expr, expr).
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
            if isinstance(x, frozenset):
                return "{" + ",".join(sorted(x)) + "}"
            return str(x)
        return f"{self.field} {self.op} {show(self.rhs)}"


C = Clause

# ---------------------------------------------------------------- WORDS: fixed windows of tokens

@dataclass(frozen=True)
class Word:
    head: str  # the event it produces
    cells: tuple[int, ...]  # CANDLE offsets consumed, from the event bar
    where: tuple[Clause, ...]  # all must hold
    rels: tuple[int, ...] = ()  # BAR_RELATION offsets consumed
    unless: tuple[Clause, ...] = ()  # a context that must not hold as a whole (cells it reads may be absent)
    attrs: Callable[[Table, int, int], dict] | None = None  # semantic action: (frame, bar, side) -> attributes

    @property
    def span(self) -> int:
        """Bars after the event bar the word reads: its known_at is the bar plus this."""
        return max((*self.cells, *self.rels, 0))


def _px(side: int, v: float) -> float:
    return float(side * v)


def _extreme_attrs(F: Table, t: int, side: int) -> dict:
    return {"price": _px(side, F["high"][t]), "swing": SWING}


def _void_attrs(F: Table, t: int, side: int) -> dict:
    lo, hi = F["high"][t - 2], F["low"][t]
    g, a = float(hi - lo), F["atr"][t]
    return {"band": (_px(side, lo), _px(side, hi)) if side > 0 else (_px(side, hi), _px(side, lo)),
            "size": g, "size_atr": float(g / a) if a > 0 else None}


_KEYS = {"dir": ("dir", None), "size": ("size", SIZE), "upper": ("upper", WICK), "lower": ("lower", WICK),
         "conv": ("conv_g", GRADE), "force": ("force_g", GRADE),
         "wick.up": ("upper_g", WGRADE), "wick.low": ("lower_g", WGRADE),
         "wick.up.share": ("upper_share_g", WGRADE), "wick.low.share": ("lower_share_g", WGRADE),
         "wick.up.body": ("upper_body", "num"), "wick.low.body": ("lower_body", "num"),
         "close": ("close_q", QUARTILES), "rel": ("rel", None), "engulf": ("engulf", None),
         "beyond": ("beyond", None)}
_OPS = (("≥", ">="), ("≤", "<="), (">=", ">="), ("<=", "<="), ("!=", "!="), ("≠", "!="), ("=", "=="),
        (">", ">"), ("<", "<"))


def _key(key: str, value: str) -> tuple[str, Any]:
    if key == "body":
        return ("force_g", GRADE) if value in GRADE else ("body", BODY)
    if key not in _KEYS:
        raise ValueError(f"unknown qualifier key {key!r}")
    return _KEYS[key]


def _qual(item: str, cell: int | None) -> Clause:
    item = item.strip()
    pre = "" if cell is None else f"{cell}."
    neg = item.startswith("not ")
    name = POINT_ALIASES.get(item[4:].strip() if neg else item, item[4:].strip() if neg else item)
    if name in NAMED_POINTS or name in COMPOSITE_POINTS:
        return C(pre + name, "==", not neg)
    for sym, op in _OPS:
        if sym in item:
            key, value = (x.strip() for x in item.split(sym, 1))
            col, order = _key(key, value)
            if order == "num":
                return C(pre + col, op if op != "==" else "==", float(value))
            if order is None or op in ("==", "!="):
                if op == "!=":
                    every = order if order is not None else ("BULL", "BEAR", "NONE")
                    return C(pre + col, "in", frozenset(x for x in every if x != value))
                return C(pre + col, "==", value)
            i = order.index(value)
            keep = {">=": order[i:], "<=": order[:i + 1], ">": order[i + 1:], "<": order[:i]}[op]
            return C(pre + col, "in", frozenset(keep))
    raise ValueError(f"cannot read qualifier {item!r}")


def _items(spec: str, head: str) -> list[str]:
    spec = spec.strip()
    if not (spec.startswith(head + "[") and spec.endswith("]")):
        raise ValueError(f"expected {head}[...]: {spec!r}")
    body = spec[len(head) + 1:-1].strip()
    return [x for x in body.split(",") if x.strip()] if body else []


def q(spec: str, cell: int | None = None) -> tuple[Clause, ...]:
    """`CANDLE[dir=BULL, body≥STRONG, close=Q4, wick.up≤WEAK]` as clauses on token cell `cell`
    (a word) or on the slot's own entity (`cell=None`, a rule)."""
    return tuple(_qual(x, cell) for x in _items(spec, "CANDLE"))


ENTITY_ORDERS: dict[str, tuple[str, tuple[str, ...]]] = {}
"""v2: ordered attribute values for entity qualifiers, `key -> (attribute, values in order)`; each
module registers its own (retrace: depth -> depth_bin SHALLOW < HALF < DEEP < BEYOND)."""


def qe(spec: str) -> tuple[Clause, ...]:
    """v2: an entity qualifier, `TYPE[key op value, ...]`, as clauses on a rule slot's entity. A
    number compares with the attribute itself (`PULLBACK[depth≥0.5]`); a value of a registered order
    compares by rank (`PULLBACK[depth≥HALF]` is HALF, DEEP or BEYOND); anything else is (in)equality
    with the attribute (`PULLBACK[phase=INSIDE]`)."""
    head = spec.split("[", 1)[0].strip()
    out = []
    for item in _items(spec, head):
        item = item.strip()
        for sym, op in _OPS:
            if sym in item:
                key, value = (x.strip() for x in item.split(sym, 1))
                break
        else:
            raise ValueError(f"cannot read qualifier {item!r}")
        try:
            out.append(C(key, op, float(value)))
            continue
        except ValueError:
            pass
        if key in ENTITY_ORDERS and value in ENTITY_ORDERS[key][1]:
            col, order = ENTITY_ORDERS[key]
            if op in ("==", "!="):
                out.append(C(col, op, value))
            else:
                i = order.index(value)
                keep = {">=": order[i:], "<=": order[:i + 1], ">": order[i + 1:], "<": order[:i]}[op]
                out.append(C(col, "in", frozenset(keep)))
        else:
            out.append(C(key, op, value))
    return tuple(out)


def run(spec: str) -> tuple[tuple[int, ...], tuple[Clause, ...], tuple[Clause, ...]]:
    """`RUN[k≥2, quals]`: the cells, clauses and `unless` of a word that completes when the K-th
    consecutive token qualifies - once per run, at its K-th token. With `k=K` the token before the
    run must not qualify either, which is the same thing: a run is counted where it reaches K."""
    items = _items(spec, "RUN")
    k = int(items[0].replace("≥", "=").replace(">=", "=").split("=")[1])
    quals = ",".join(items[1:])
    cells = tuple(range(-(k - 1), 1))
    where = tuple(c for j in cells for c in q(f"CANDLE[{quals}]", j))
    return cells, where, q(f"CANDLE[{quals}]", -k)


def _strength(cells: tuple[int, ...]) -> Callable[[Table, int, int], dict]:
    """The derived strength of what a word consumed: the mean and max body_atr of its tokens."""
    def attrs(F: Table, t: int, side: int) -> dict:
        x = np.array([F["body_atr"][t + k] for k in cells], float)
        x = x[np.isfinite(x)]
        return {"strength_mean": float(x.mean()) if len(x) else None,
                "strength_max": float(x.max()) if len(x) else None}
    return attrs


def _named(name: str, extra: Callable | None = None) -> Callable[[Table, int, int], dict]:
    def attrs(F: Table, t: int, side: int) -> dict:
        return {"rule": name, **(extra(F, t, side) if extra else {})}
    return attrs


_RUN = run("RUN[k≥2, dir=BULL, body≥STRONG, close=Q4]")

WORDS: dict[str, Word] = {
    # level words: a window of tokens and a predicate on their prices
    "EXTREME": Word("EXTREME", tuple(range(-SWING, SWING + 1)), tuple(
        [C(f"{k}.high", "<", "0.high") for k in range(-SWING, 0)]
        + [C(f"{k}.high", "<=", "0.high") for k in range(1, SWING + 1)]), attrs=_extreme_attrs),
    "VOID": Word("VOID", (-2, -1, 0), (C("0.low", ">", "-2.high"),), attrs=_void_attrs),
    # pattern words: classes and grades only
    "PIN": Word("PIN", (0,), q("CANDLE[wick.low≥STRONG, body≤MODERATE, close≥Q3, wick.up≤WEAK]", 0)),
    "ENGULF": Word("ENGULF", (-1, 0), q("CANDLE[dir=BEAR]", -1) + q("CANDLE[dir=BULL, engulf=BULL]", 0),
                   rels=(0,)),
    "INSIDE_BREAK": Word("INSIDE_BREAK", (-1, 0), q("CANDLE[rel=INSIDE]", -1) + q("CANDLE[beyond=ABOVE]", 0),
                         rels=(-1, 0)),
    "STAR": Word("STAR", (-2, -1, 0), q("CANDLE[dir=BEAR, body≥LARGE]", -2) + q("CANDLE[body≤SMALL]", -1)
                 + q("CANDLE[dir=BULL, body≥LARGE]", 0)),
    "DISPLACE_C_RUN": Word("DISPLACE_C", _RUN[0], _RUN[1], unless=_RUN[2],
                           attrs=_named("DISPLACE_C_RUN", _strength(_RUN[0]))),
    "DISPLACE_C_BAR": Word("DISPLACE_C", (0,), q("CANDLE[dir=BULL, size=EXTREMELY_LARGE, body≥DOMINANT, close=Q4]", 0),
                           attrs=_named("DISPLACE_C_BAR", _strength((0,)))),
}
LEVEL_WORDS = ("EXTREME", "VOID")
PATTERN_WORDS = tuple(k for k in WORDS if k not in LEVEL_WORDS)


def _path(x: Any) -> tuple[int, str] | None:
    if isinstance(x, str) and "." in x:
        k, f = x.split(".", 1)
        try:
            return int(k), f
        except ValueError:
            return None
    return None


def _col(F: Table, x: Expr, t: np.ndarray) -> tuple[Any, np.ndarray]:
    """A word expression's values at every bar t, and where they exist."""
    n = len(t)
    if isinstance(x, tuple):
        op, a, b = x
        (va, ma), (vb, mb) = _col(F, a, t), _col(F, b, t)
        return (va + vb if op == "+" else va * vb), ma & mb
    p = _path(x)
    if p is None:
        return x, np.ones(n, bool)
    k, f = p
    i = t + k
    ok = (i >= 0) & (i < n)
    ic = np.clip(i, 0, max(n - 1, 0))
    if f in REL_FIELDS:
        ok &= F["rel_valid"][ic]
    return F[f][ic], ok


def _clause_mask(F: Table, c: Clause, t: np.ndarray) -> np.ndarray:
    lv, lm = _col(F, c.field, t)
    if c.op == "in":
        return lm & np.isin(lv, list(c.rhs))
    rv, rm = _col(F, c.rhs, t)
    with np.errstate(invalid="ignore"):
        return lm & rm & np.asarray(OPS[c.op](lv, rv), bool)


def word_mask(w: Word, F: Table) -> np.ndarray:
    """The bars at which word `w` is complete, in frame F."""
    n = len(F["close"])
    t = np.arange(n)
    m = np.ones(n, bool)
    for k in w.cells:
        m &= (t + k >= 0) & (t + k < n)
    for k in w.rels:
        i = t + k
        ok = (i >= 0) & (i < n)
        m &= ok & F["rel_valid"][np.clip(i, 0, max(n - 1, 0))]
    for c in w.where:
        m &= _clause_mask(F, c, t)
    if w.unless:
        u = np.ones(n, bool)
        for c in w.unless:
            u &= _clause_mask(F, c, t)
        m &= ~u
    return m


def frames(T: Table) -> dict[int, Table]:
    """The token table in both frames, built once."""
    return {1: T, -1: frame(T, -1)}


def words(T: Table, cid: list[str], rid: list[str | None], names: Iterable[str] | None = None,
          table_: dict[str, Word] | None = None, fr: dict[int, Table] | None = None) -> list[Entity]:
    """Every word of the table, and every scan, on the chart and on the chart flipped. Two rows with
    the same head on the same bar and side make one event: the first row's."""
    table_ = WORDS if table_ is None else table_
    names = tuple(table_) if names is None else tuple(names)
    fr = frames(T) if fr is None else fr
    out, seen = [], set()
    for name in names:
        w = table_[name]
        for side, d in zip((1, -1), SIDES):
            F = fr[side]
            for t in np.flatnonzero(word_mask(w, F)):
                t = int(t)
                eid = make_id(w.head, d, t)
                if eid in seen:
                    continue
                seen.add(eid)
                attrs = w.attrs(F, t, side) if w.attrs else {"rule": name}
                parts = tuple(cid[t + k] for k in sorted(w.cells)) + tuple(rid[t + k] for k in sorted(w.rels))
                out.append(Entity(eid, w.head, d, t, t + w.span, attrs_of(attrs), parts=parts))
    if table_ is WORDS:
        for side, d in zip((1, -1), SIDES):
            out += delivery_shifts(fr[side], d, cid)
    return out


# ---------------------------------------------------------------- SCANS: variable runs of tokens

SHIFT_LAG = 3
"""Bars from the delivery run's last token to the shift, at most (zones._cisd: `j - m > 3` fails)."""


def delivery_shifts(F: Table, d: Dir, cid: list[str]) -> list[Entity]:
    """DELIVERY_SHIFT (the desk's CISD) in frame F, up side: a BULL token whose close is above the
    open of the first token of the last BEAR run, which ended at most SHIFT_LAG bars before it."""
    o, c, a, ba = F["open"], F["close"], F["atr"], F["body_atr"]
    bear = F["dir"] == "BEAR"
    bull = F["dir"] == "BULL"
    out = []
    for j in np.flatnonzero(bull):
        j = int(j)
        m = j - 1
        while m >= 0 and not bear[m] and j - m <= SHIFT_LAG:
            m -= 1
        if m < 0 or j - m > SHIFT_LAG or not bear[m]:
            continue
        k = m
        while k - 1 >= 0 and bear[k - 1]:
            k -= 1
        if not c[j] > o[k]:
            continue
        x = ba[k:m + 1]
        x = x[np.isfinite(x)]
        out.append(Entity(make_id("DELIVERY_SHIFT", d, j), "DELIVERY_SHIFT", d, j, j, attrs_of({
            "run_len": m - k + 1, "lag": j - m,
            "run_force_mean": float(x.mean()) if len(x) else None,
            "run_force_max": float(x.max()) if len(x) else None,
            "margin": float((c[j] - o[k]) / a[j]) if a[j] > 0 else None}),
            parts=tuple(cid[k:m + 1]) + (cid[j],)))
    return out


# ---------------------------------------------------------------- RULES: productions over entities

@dataclass(frozen=True)
class Slot:
    name: str
    type: str
    min: int = 1
    max: int | None = 1  # None: as many as match (the + in VOID+)
    where: tuple[Clause, ...] = ()
    dir: str = "same"  # "same" as the rule's direction, or "any" (a CANDLE of either colour)
    absent: bool = False  # a negative slot: the rule fails if anything fills it


@dataclass(frozen=True)
class Rule:
    head: str  # the structure or event it builds
    anchor: str  # the slot it grows from
    horizon: str | None  # structure type, same id stem as the anchor, whose closing decides a candidate
    slots: tuple[Slot, ...]  # in binding order: a slot's clauses may read only earlier slots
    sequence: tuple[str, ...]  # the canonical order of the right-hand side: the parts
    decide: Expr = None  # without a horizon: the last bar of the candidate's window
    report: bool = True  # list refused candidates as failures and undecided ones as pending
    at: str | None = None  # the slot whose bar is the event's bar (default the anchor)
    suffix: tuple[str, Expr] | None = None  # id suffix: (prefix, expression)
    attrs: Callable[[dict[str, list[Entity]], Dir], dict] | None = None

    def bnf(self, d: Dir) -> str:
        names = {s.name: s for s in self.slots}

        def tok(n: str) -> str:
            s = names[n]
            return f"{s.type}_{d.value}{'+' if s.max is None else ''}"
        return f"{self.head}_{d.value} := " + " ".join(tok(n) for n in self.sequence)


def _reject_attrs(b: dict[str, list[Entity]], d: Dir) -> dict:
    return {"zone": b["zone"][0].id, "revisit": b["revisit"][0].id, "count": b["revisit"][0].get("count")}


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

CANDLE_RULES: dict[str, Rule] = {
    "REJECT": Rule(
        head="REJECT", anchor="revisit", horizon=None, report=False,
        decide=("+", "revisit.at", REACTION_BARS - 1), at="candle", suffix=("z", "zone.at"),
        slots=(
            Slot("revisit", "REVISIT"),
            Slot("zone", "ZONE", where=(C("id", "==", "revisit.zone"),)),
            Slot("candle", "CANDLE", dir="any", where=(
                C("at", ">=", "revisit.at"),
                C("at", "<=", ("+", "revisit.at", REACTION_BARS - 1)),
                *q("CANDLE[wick.low≥STRONG]"),  # a strong wick toward the zone (below an up zone)
                C("close", ">", "zone.near"))),  # and the body closed back out of it
            Slot("fail", "FAIL", min=0, absent=True, where=(
                C("zone", "==", "revisit.zone"),
                C("at", "<=", "candle.at"))),
        ),
        sequence=("revisit", "candle"), attrs=_reject_attrs,
    ),
}


def _eval(x: Expr, bound: dict[str, list[Entity]], side: int) -> Any:
    if isinstance(x, tuple):
        op, l, r = x
        lv, rv = _eval(l, bound, side), _eval(r, bound, side)
        return lv + rv if op == "+" else lv * rv
    if isinstance(x, str) and "." in x:
        slot, f = x.split(".", 1)
        return view(bound[slot][0], f, side)
    return x


def _holds(e: Entity, c: Clause, bound: dict[str, list[Entity]], side: int) -> bool:
    v = view(e, c.field, side)
    return v is not None and OPS[c.op](v, _eval(c.rhs, bound, side))


class Index:
    """Entities by (type, dir), and by type for either direction, sorted by bar."""

    def __init__(self, entities: Iterable[Entity]) -> None:
        self.by: dict[tuple[str, Dir], list[Entity]] = {}
        self.any: dict[str, list[Entity]] = {}
        self.ids: dict[str, Entity] = {}
        for e in entities:
            self.by.setdefault((e.type, e.dir), []).append(e)
            self.any.setdefault(e.type, []).append(e)
            self.ids[e.id] = e
        for v in (*self.by.values(), *self.any.values()):
            v.sort(key=lambda e: (e.at, e.id))
        self.ats = {k: [e.at for e in v] for k, v in self.by.items()}
        self.ats_any = {k: [e.at for e in v] for k, v in self.any.items()}

    def _full(self, slot: Slot, d: Dir) -> tuple[list[Entity], list[int]]:
        if slot.dir == "any":
            return self.any.get(slot.type, []), self.ats_any.get(slot.type, [])
        return self.by.get((slot.type, d), []), self.ats.get((slot.type, d), [])

    def narrow(self, slot: Slot, d: Dir, bound: dict[str, list[Entity]], upto: int,
               side: int = 1) -> tuple[list[Entity], str]:
        """Apply the slot's clauses in order to what is known by `upto`; a clause on the bar is a
        binary search. Returns what survives, and the clause that left fewer than the slot's
        minimum (or ""). The grammar sees only what was known when it decides - otherwise even
        the reason for a failure could depend on the future."""
        full, ats_full = self._full(slot, d)
        pool = full[:bisect.bisect_right(ats_full, upto)] if full else full
        pool = [e for e in pool if e.known_at <= upto]
        for c in slot.where:
            if c.field == "at" and c.op in (">=", "<="):
                ats = [e.at for e in pool]
                v = _eval(c.rhs, bound, side)
                pool = pool[bisect.bisect_left(ats, v):] if c.op == ">=" else pool[:bisect.bisect_right(ats, v)]
            else:
                pool = [e for e in pool if _holds(e, c, bound, side)]
            if len(pool) < slot.min:
                return pool, c.text()
        return pool, "" if len(pool) >= slot.min else "exists"

    def narrow_fast(self, slot: Slot, d: Dir, bound: dict[str, list[Entity]], upto: int,
                    side: int) -> list[Entity]:
        """The same pool, cut to the slot's bar window by binary search before anything is
        copied. For rules that do not report which clause failed."""
        full, ats = self._full(slot, d)
        lo, hi = 0, bisect.bisect_right(ats, upto)
        for c in slot.where:
            if c.field == "at" and c.op in (">=", "<=", "=="):
                v = _eval(c.rhs, bound, side)
                if c.op in (">=", "=="):
                    lo = max(lo, bisect.bisect_left(ats, v))
                if c.op in ("<=", "=="):
                    hi = min(hi, bisect.bisect_right(ats, v))
        pool = [e for e in full[lo:hi] if e.known_at <= upto]
        for c in slot.where:
            if not (c.field == "at" and c.op in (">=", "<=", "==")):
                pool = [e for e in pool if _holds(e, c, bound, side)]
        return pool


_FLIP_SENSITIVE = frozenset({"dir", "band", "points", "inner", "rel", "engulf", "beyond", "close_q", "named",
                              "within", *NEG_FIELD, *NAMED_POINTS, *COMPOSITE_POINTS})


def _fields(x: Expr) -> list[str]:
    if isinstance(x, tuple):
        return _fields(x[1]) + _fields(x[2])
    if isinstance(x, str) and "." in x:
        return [x.split(".", 1)[1]]
    return []


def flips(rule: Rule) -> bool:
    """Whether any clause of the rule reads a field whose value or name changes under the flip. If
    none does, the down side reads its entities as they are, which is the same and much faster."""
    for s in rule.slots:
        for c in s.where:
            for f in [c.field] + _fields(c.rhs):
                if f in _FLIP_SENSITIVE or swap_key(f) != f:
                    return True
    return False


def match(rule: Rule, anchor: Entity, idx: Index, upto: int, d: Dir | None = None
          ) -> tuple[dict[str, list[Entity]] | None, Slot | None, str]:
    """Bind every slot for this anchor from what is known by `upto`, or say which slot and clause
    could not be filled."""
    d = anchor.dir if d is None else d
    side = 1 if d is Dir.UP or not flips(rule) else -1
    bound: dict[str, list[Entity]] = {rule.anchor: [anchor]}
    for slot in rule.slots:
        if slot.name == rule.anchor:
            for c in slot.where:
                if not _holds(anchor, c, bound, side):
                    return None, slot, c.text()
            continue
        if rule.report and not slot.absent:
            pool, why = idx.narrow(slot, d, bound, upto, side)
            if why:
                return None, slot, why
        else:
            pool = idx.narrow_fast(slot, d, bound, upto, side)
            if slot.absent:
                if pool:
                    return None, slot, "absent"
                bound[slot.name] = []
                continue
            if len(pool) < slot.min:
                return None, slot, "exists"
        bound[slot.name] = pool if slot.max is None else pool[:slot.max]
    return bound, None, ""


def apply(entities: list[Entity], rules: dict[str, Rule] | None = None,
          n: int | None = None) -> tuple[list[Entity], list[Failure], list[str]]:
    """Every anchor of every rule: the structures accepted, the failures, and the ids still forming.
    `n` (bars in the series) caps a `decide` window at the last bar."""
    rules = RULES if rules is None else rules
    idx = Index(entities)
    built, failed, pending, seen = [], [], [], set()
    for name, rule in rules.items():
        aslot = next(s for s in rule.slots if s.name == rule.anchor)
        for d in SIDES:
            anchors = idx.any.get(aslot.type, []) if aslot.dir == "any" else idx.by.get((aslot.type, d), [])
            for anc in anchors:
                if rule.horizon is not None:
                    stem = anc.id.split(".", 1)[1]  # "U.57": the horizon shares the anchor's stem
                    hz = idx.ids.get(f"{rule.horizon}.{stem}")
                    if hz is None:
                        if rule.report:
                            pending.append(anc.id)
                        continue
                    upto = max(hz.known_at, anc.known_at)
                else:
                    upto = _eval(rule.decide, {rule.anchor: [anc]}, 1) if rule.decide is not None else anc.known_at
                    if n is not None:
                        upto = min(upto, n - 1)
                bound, slot, why = match(rule, anc, idx, upto, d)
                rname = f"{name}_{d.value}"
                if bound is None:
                    if rule.report:
                        failed.append(Failure(anc.id, rname, slot.name, why, upto))
                    continue
                e = _build(rule, anc, bound, d)
                if e.id not in seen:
                    seen.add(e.id)
                    built.append(e)
    return built, failed, pending


def _build(rule: Rule, anc: Entity, bound: dict[str, list[Entity]], d: Dir) -> Entity:
    parts = [e for n in rule.sequence for e in bound[n]]
    known = max(e.known_at for e in parts)
    at = bound[rule.at][0].at if rule.at else anc.at
    if rule.attrs is not None:
        attrs = rule.attrs(bound, d)
    else:
        attrs: dict[str, Any] = {"rule": f"{rule.head}_{d.value}"}
    if rule.head == "ZONE":
        brk = bound["break"][0]
        attrs.update(far=anc.get("far"), near=anc.get("near"), band=anc.get("band"), atr=anc.get("atr"),
                     break_at=brk.at, level=brk.get("level"), n_voids=len(bound["void"]),
                     magnitude=brk.force.magnitude if brk.force else None)
    suffix = ""
    if rule.suffix is not None:
        suffix = f"{rule.suffix[0]}{_eval(rule.suffix[1], bound, 1)}"
    return Entity(make_id(rule.head, d, at, suffix), rule.head, d, at, known,
                  attrs_of(attrs), parts=tuple(e.id for e in parts))
