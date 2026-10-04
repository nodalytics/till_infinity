"""The time core, item 2: interval relations (Allen's algebra), usable in productions.

Every stamped entity is an interval (`core.Span`): in bars, the half-open [start, end + 1) - so two
consecutive bars MEET - and in time, [start_ts, end_ts). For x = [a, b) and y = [c, d):

    BEFORE       b < c                  AFTER          (the inverse)
    MEETS        b = c                  MET_BY
    OVERLAPS     a < c < b < d          OVERLAPPED_BY
    STARTS       a = c, b < d           STARTED_BY
    DURING       c < a, b < d           CONTAINS
    FINISHES     c < a, b = d           FINISHED_BY
    EQUALS       a = c, b = d

Exactly one holds for any pair of non-empty intervals. WITHIN is the union a trader means by
"during" - STARTS, DURING, FINISHES or EQUALS (x lies inside y) - and HOLDS its inverse. (CONTAINS
here is Allen's; v0's materialised CONTAIN is parthood - a zone contains its parts.)

`relate(x, y, clock)` computes one on demand, on the bar clock (`"bar"`) or the wall clock
(`"time"`); a calendar WINDOW has a scheduled end in time but none in bars until it closes, so on the
bar clock it relates to nothing (None). On the wall clock a gap is time: a bar before a weekend and
the bar after it are BEFORE, not MEETS.

In productions an interval is the field `interval` (bars) or `interval_ts` (time) and the relation is
the clause's operator: `C("interval_ts", "HOLDS", "revisit.interval_ts")` on a WINDOW slot reads "the
window holds the revisit". The rows below are IN_WINDOW (L3), an event inside a calendar window -
the roadmap's `REVISIT DURING SESSION[LONDON]` is `IN_WINDOW[name=LONDON]` of the first row - with
`of`, `of_type`, `window`, `kind`, `name` and `rel`, the exact Allen relation of the event to the
window (DURING, STARTS, FINISHES or EQUALS). Each is decided at the event's known_at, from the
windows open by then.
"""
from __future__ import annotations

from mcfl import grammar
from mcfl.core import Dir, Entity
from mcfl.grammar import C, Rule, Slot

Interval = tuple[int, int]
WINDOW_MAX_BARS = 1440
"""The default bound on the search: a window's first bar is at most this many bars before an event it
holds (the longest window, nine hours, is 540 one-minute bars). The parse passes the bound its own
bars allow (`max_bars`); it only narrows the search, so any bound at least that large gives the same
productions."""
ALLEN = ("BEFORE", "MEETS", "OVERLAPS", "STARTS", "DURING", "FINISHES", "EQUALS",
         "AFTER", "MET_BY", "OVERLAPPED_BY", "STARTED_BY", "CONTAINS", "FINISHED_BY")
INVERSE = dict(zip(ALLEN, ("AFTER", "MET_BY", "OVERLAPPED_BY", "STARTED_BY", "CONTAINS", "FINISHED_BY", "EQUALS",
                           "BEFORE", "MEETS", "OVERLAPS", "STARTS", "DURING", "FINISHES")))
INSIDE = frozenset({"STARTS", "DURING", "FINISHES", "EQUALS"})


def allen(x: Interval, y: Interval) -> str:
    """The one Allen relation of half-open intervals x and y."""
    a, b = x
    c, d = y
    if b < c:
        return "BEFORE"
    if d < a:
        return "AFTER"
    if b == c:
        return "MEETS" if a < b or c < d else "EQUALS"
    if d == a:
        return "MET_BY"
    if a == c:
        return "EQUALS" if b == d else "STARTS" if b < d else "STARTED_BY"
    if b == d:
        return "FINISHES" if a > c else "FINISHED_BY"
    if c < a and b < d:
        return "DURING"
    if a < c and d < b:
        return "CONTAINS"
    return "OVERLAPS" if a < c else "OVERLAPPED_BY"


def relate(x: Entity, y: Entity, clock: str = "bar") -> str | None:
    key = "interval" if clock == "bar" else "interval_ts"
    p, q = x.field(key), y.field(key)
    if p is None or q is None:
        return None
    return allen(p, q)


def _op(name: str):
    if name == "WITHIN":
        return lambda x, y: x is not None and y is not None and allen(x, y) in INSIDE
    if name == "HOLDS":
        return lambda x, y: x is not None and y is not None and INVERSE[allen(x, y)] in INSIDE
    return lambda x, y: x is not None and y is not None and allen(x, y) == name


for _name in (*ALLEN, "WITHIN", "HOLDS"):
    grammar.OPS[_name] = _op(_name)


def _in_window(event: str):
    def attrs(b: dict[str, list[Entity]], d: Dir) -> dict:
        e, w = b[event][0], b["window"][0]
        return {"of": e.id, "of_type": e.type, "window": w.id, "kind": w.get("kind"), "name": w.get("name"),
                "rel": allen(e.field("interval_ts"), w.field("interval_ts"))}
    return attrs


def in_window(event: str, kind: str, max_bars: int = WINDOW_MAX_BARS) -> Rule:
    """IN_WINDOW_UP := EVENT_UP WINDOW[kind]   where the window HOLDS the event (on the wall clock)."""
    slot = event.lower()
    return Rule(
        head="IN_WINDOW", anchor=slot, horizon=None, report=False,
        suffix=("w", ("+", ("+", "window.name", "_"), f"{slot}.id_suffix")),
        slots=(Slot(slot, event),
               Slot("window", "WINDOW", dir="any", where=(
                   C("at", ">=", ("+", f"{slot}.at", -max_bars)),
                   C("at", "<=", f"{slot}.at"),
                   C("kind", "==", kind),
                   C("interval_ts", "HOLDS", f"{slot}.interval_ts")))),
        sequence=(slot, "window"), attrs=_in_window(slot))


def rules(max_bars: int = WINDOW_MAX_BARS) -> dict[str, Rule]:
    return {
        "REVISIT_IN_SESSION": in_window("REVISIT", "SESSION", max_bars),
        "TAKEN_IN_KILLZONE": in_window("SESSION_EXTREME_TAKEN", "KILLZONE", max_bars),
        "SWEEP_IN_MACRO": in_window("POOL_TAKEN", "MACRO", max_bars),
    }


RULES: dict[str, Rule] = rules()
"""REVISIT DURING SESSION (any session; `IN_WINDOW[name=LONDON]` picks one), a session's high or low
taken inside a killzone (ICT's raid), a liquidity pool taken inside an ICT macro window."""


def max_bars(ts) -> int:
    """How many bars the longest window can hold, from the shortest gap between bar opens."""
    import numpy as np
    from mcfl.anchors import WINDOWS
    d = np.diff(np.asarray(ts, np.int64))
    d = d[d > 0]
    longest = max((e - s) % 1440 or 1440 for _, _, _, s, e in WINDOWS) * 60
    return int(longest // d.min()) + 2 if len(d) else WINDOW_MAX_BARS
