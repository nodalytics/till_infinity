"""v2 item 4: the VOID lifecycle.

    UNTOUCHED --VOID_PARTIAL--> PARTIAL --VOID_FILLED--> FILLED --VOID_INVERTED--> INVERTED

For an up VOID at bar k (down is the flipped chart): `near` is its top, low[k], the edge price meets
first coming back down; `far` is its bottom, high[k-2]. From bar k + 1:

    VOID_PARTIAL   the first bar whose low is below `near`: price entered the gap
    VOID_FILLED    the first bar whose low is at or below `far`: the gap traded through
    VOID_INVERTED  the first bar whose close is below `far`: a close beyond its far side (the IFVG,
                   inverted fair-value gap)

Each implies the ones before it, so a bar can make several transitions; all are recorded, in order,
at that bar's close. INVERTED is terminal. Each transition is an event (L2) known at its bar, with
`parts` that bar's CANDLE, and a `Transition(void, src, dst, at, known_at, event)` record. A void's
state at any bar is `void_state(chart, void_id, t)`.

Attributes: `void` (the VOID's id); VOID_PARTIAL and VOID_FILLED `share`, the part of the gap traded
into on that bar (low - near) / (far - near), capped at 1 (so 1 on a filled bar); VOID_INVERTED
`beyond_atr`, how far the close went past `far` in ATR at that bar.
"""
from __future__ import annotations

import numpy as np

from mcfl.candles import Table
from mcfl.core import Chart, Dir, Entity, Transition, attrs_of, make_id

STATES = ("UNTOUCHED", "PARTIAL", "FILLED", "INVERTED")
EVENTS = {"PARTIAL": "VOID_PARTIAL", "FILLED": "VOID_FILLED", "INVERTED": "VOID_INVERTED"}


def _first(x: np.ndarray) -> int:
    i = np.flatnonzero(x)
    return int(i[0]) if len(i) else -1


def run(fr: dict[int, Table], voids: list[Entity], cid: list[str]) -> tuple[list[Entity], list[Transition]]:
    events, trans = [], []
    for v in voids:
        side = 1 if v.dir is Dir.UP else -1
        F = fr[side]
        k = v.at
        near, far = F["low"][k], F["high"][k - 2]
        lo, c, a = F["low"][k + 1:], F["close"][k + 1:], F["atr"][k + 1:]
        hits = {"PARTIAL": _first(lo < near), "FILLED": _first(lo <= far), "INVERTED": _first(c < far)}
        state = "UNTOUCHED"
        for st in ("PARTIAL", "FILLED", "INVERTED"):
            j = hits[st]
            if j < 0:
                break
            t = k + 1 + j
            if st == "INVERTED":
                attrs = {"void": v.id, "beyond_atr": float((far - c[j]) / a[j]) if a[j] > 0 else None}
            else:
                attrs = {"void": v.id, "share": float(min(1.0, (near - lo[j]) / (near - far)))}
            kind = EVENTS[st]
            e = Entity(make_id(kind, v.dir, t, f"v{k}"), kind, v.dir, t, t, attrs_of(attrs), parts=(cid[t],))
            events.append(e)
            trans.append(Transition(v.id, state, st, t, t, e.id))
            state = st
    return events, trans


def void_state(chart: Chart, void_id: str, t: int) -> str | None:
    """The state of a VOID at bar t (None before it is known)."""
    ids = chart.by_id()
    if void_id not in ids or ids[void_id].known_at > t:
        return None
    s = "UNTOUCHED"
    for tr in chart.transitions:
        if tr.zone == void_id and tr.known_at <= t:
            s = tr.dst if STATES.index(tr.dst) > STATES.index(s) else s
    return s
