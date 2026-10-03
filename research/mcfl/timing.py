"""v2 item 8: time and tempo.

Time needs a `ts` column (each bar's open, epoch seconds, UTC); without one there are no session
words. Tempo needs only bars.

SESSION, an L1 qualifier of every CANDLE, by the UTC hour of the bar's open (no daylight saving):

    ASIA     22:00 - 07:00
    LONDON   07:00 - 12:00
    OVERLAP  12:00 - 16:00   (London and New York both open)
    NY       16:00 - 22:00

and DAY_OF_WEEK (`dow`, MON..SUN, of the bar's open). A session INSTANCE is a run of consecutive bars
with one session (a gap of more than 12 hours also starts a new one).

    SESSION_OPEN (NONE)       the first bar of each instance: `session`, `price` (its open). Known there
    SESSION_EXTREME ↑ / ↓     an instance's high (↑) and low (↓), at the bar that made it (the first, on
                              a tie). Known at the first bar of the next instance - when the clock has
                              shown the session is over
    SESSION_EXTREME_TAKEN ↑/↓ the first bar from the next instance on whose high is above the session
                              high (low below the low), before the same session's next instance begins:
                              SESSION_HIGH_TAKEN is SESSION_EXTREME_TAKEN↑, SESSION_LOW_TAKEN ↓.
                              `closed_back`: its close did not stay beyond. Known at its bar

TEMPO: every event of a structure's lifecycle gets `tempo`, the bars since the previous event of the
same structure (a zone's REVISIT, REJECT_PATH, ACCEPT, FAIL, EXPIRE since the zone qualified or its
last event; a VOID's transitions since the void or its last transition; a RANGE's tests and escapes
since the range was known or its last event), and `pace`: FAST when the tempo is at or under the 25th
percentile of the last TEMPO_WINDOW (50) tempos of the same event type known before it, SLOW at or over
the 75th, else NORMAL; WARMUP with fewer than TEMPO_MIN (10) of them. So "a fast return" is
`REVISIT[pace=FAST]`.
"""
from __future__ import annotations

from collections import deque

import numpy as np
import pandas as pd

from mcfl import candles
from mcfl.candles import Table
from mcfl.core import Dir, Entity, attrs_of, make_id, sort_key

SESSIONS = (("ASIA", 22, 7), ("LONDON", 7, 12), ("OVERLAP", 12, 16), ("NY", 16, 22))
"""(name, first UTC hour, end UTC hour), each [start, end); ASIA wraps midnight."""
SESSION_CODE = {"ASIA": "AS", "LONDON": "LN", "OVERLAP": "OV", "NY": "NY"}
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
GAP_HOURS = 12
"""A gap longer than this between bars starts a new session instance even with the same session."""
TEMPO_WINDOW = 50
TEMPO_MIN = 10
PACES = ("FAST", "NORMAL", "SLOW")


def session_of(hour: np.ndarray) -> np.ndarray:
    out = np.empty(len(hour), object)
    for name, a, b in SESSIONS:
        m = (hour >= a) | (hour < b) if a > b else (hour >= a) & (hour < b)
        out[m] = name
    return out


def columns(T: Table, df: pd.DataFrame) -> bool:
    """Add `session` and `dow` to the token table, in place. False when the bars have no `ts`."""
    if "ts" not in df:
        return False
    ts = df["ts"].to_numpy(np.int64)
    hour = (ts // 3600) % 24
    T["session"] = session_of(hour)
    T["dow"] = np.array([DAYS[int(d)] for d in ((ts // 86400) + 3) % 7], object)  # 1970-01-01 was a Thursday
    T["ts"] = ts
    candles.V2_CANDLE.update(session=False, dow=False)
    return True


def _instances(T: Table) -> list[tuple[int, int, str]]:
    s, ts = T["session"], T["ts"]
    out, start = [], 0
    for t in range(1, len(s) + 1):
        if t == len(s) or s[t] != s[t - 1] or ts[t] - ts[t - 1] > GAP_HOURS * 3600:
            out.append((start, t - 1, s[start]))
            start = t
    return out


def sessions(T: Table, cid: list[str]) -> list[Entity]:
    if "session" not in T:
        return []
    h, l, c, o = T["high"], T["low"], T["close"], T["open"]
    n = len(c)
    inst = _instances(T)
    out = []
    for i, (a, b, name) in enumerate(inst):
        out.append(Entity(make_id("SESSION_OPEN", Dir.NONE, a), "SESSION_OPEN", Dir.NONE, a, a,
                          attrs_of({"session": name, "price": float(o[a])}), parts=(cid[a],)))
        if b + 1 >= n:
            continue  # the session has not been seen to end
        known = b + 1
        nxt = next((x[0] for x in inst[i + 1:] if x[2] == name), n)  # the same session's next instance
        for d, x, sgn in ((Dir.UP, h, 1.0), (Dir.DOWN, l, -1.0)):
            seg = sgn * x[a:b + 1]
            at = a + int(np.argmax(seg))
            lvl = float(x[at])
            eid = make_id("SESSION_EXTREME", d, at, f"s{a}")
            out.append(Entity(eid, "SESSION_EXTREME", d, at, known, attrs_of({
                "session": name, "price": lvl, "start": a, "end": b}), parts=tuple(cid[a:b + 1])))
            w = sgn * x[known:nxt] > sgn * lvl
            hit = np.flatnonzero(w)
            if len(hit):
                t = known + int(hit[0])
                out.append(Entity(make_id("SESSION_EXTREME_TAKEN", d, t, f"s{a}"), "SESSION_EXTREME_TAKEN", d, t, t,
                                  attrs_of({"extreme": eid, "session": name, "level": lvl,
                                            "closed_back": bool(sgn * c[t] <= sgn * lvl)}),
                                  parts=(eid, cid[t])))
    return out


# ---------------------------------------------------------------- tempo

def _group(e: Entity) -> str | None:
    for k in ("zone", "void", "range"):
        v = e.get(k)
        if v is not None and e.type not in ("REJECT", "RETRACE"):
            return v
    return None


TEMPO_TYPES = frozenset({"REVISIT", "REJECT_PATH", "ACCEPT", "FAIL", "EXPIRE", "VOID_PARTIAL", "VOID_FILLED",
                         "VOID_INVERTED", "RANGE_TEST", "ESCAPE", "FAILED_ESCAPE"})


def tempo(ents: list[Entity]) -> list[Entity]:
    """The same entities, with `tempo` and `pace` on every lifecycle event of a structure."""
    ids = {e.id: e for e in ents}
    life = sorted((e for e in ents if e.type in TEMPO_TYPES), key=sort_key)  # in-bar order: the lifecycle's
    last: dict[str, int] = {}
    tempos: dict[str, int] = {}
    for e in life:
        g = _group(e)
        s = ids[g]
        base = s.known_at if s.type in ("ZONE", "RANGE") else s.at
        tempos[e.id] = e.at - last.get(g, base)
        last[g] = e.at
    pace: dict[str, str] = {}
    by_type: dict[str, list[Entity]] = {}
    for e in life:
        by_type.setdefault(e.type, []).append(e)
    for typ, es in by_type.items():
        # the window's order must not depend on direction (the flip): ties on (known_at, bar) are broken
        # by the tempo itself, so whichever of them falls in the window, the window holds the same values
        es = sorted(es, key=lambda e: (e.known_at, e.at, tempos[e.id]))
        hist: deque = deque(maxlen=TEMPO_WINDOW)
        i = 0
        for e in es:  # in known_at order
            while i < len(es) and es[i].known_at < e.known_at:
                hist.append(tempos[es[i].id])
                i += 1
            if len(hist) < TEMPO_MIN:
                pace[e.id] = "WARMUP"
                continue
            q25, q75 = np.quantile(np.fromiter(hist, float), [0.25, 0.75])
            x = tempos[e.id]
            pace[e.id] = "FAST" if x <= q25 else "SLOW" if x >= q75 else "NORMAL"
    out = []
    for e in ents:
        if e.id in tempos:
            e = Entity(e.id, e.type, e.dir, e.at, e.known_at,
                       attrs_of({**dict(e.attrs), "tempo": tempos[e.id], "pace": pace[e.id]}), e.force, e.parts)
        out.append(e)
    return out
