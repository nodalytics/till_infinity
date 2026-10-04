"""The time core, item 6: time-based events.

TIMEOUT - nothing happened within N. Rows of the rule table (`RULES`), each a structure and an absent
slot, decided TIMEOUT_BARS (48) bars after the structure became known. The event is at that bar and
known there, and exists only once the series has reached it:

    TIMEOUT_UP := ZONE_UP  ¬REVISIT_UP[zone, at ≤ ZONE.known_at + 48]          (kind ZONE)
    TIMEOUT_UP := VOID_UP  ¬VOID_PARTIAL_UP[void, at ≤ VOID.known_at + 48]     (kind VOID)
    TIMEOUT    := RANGE    ¬FAILED_ESCAPE ¬ESCAPE[range, ...]                  (kind RANGE, no direction)

(a range's edges are tested within a few bars almost always; its TIMEOUT is the box holding: no
excursion out of it, failed or not, within N).

On another clock N is that clock's bars: parsed on volume bars, a TIMEOUT is 48 volume bars.

STALL (NONE) - confined longer than usual for this market and hour. A bar's confinement c is the
number of bars, back from it and itself included, whose highs and lows all fit in STALL_ATR (1) ATR
at the bar (capped at STALL_MAX, 192). The usual is the STALL_Q (90th) percentile of the c of the
last STALL_N (120) bars that opened in the same UTC hour, known before the bar (at least STALL_MIN,
30; one baseline for all bars without timestamps). STALL is the bar where c first exceeds the usual,
once per stretch above it: `bars` (c), `usual`, `hour`; its span is the confined bars.

SESSION_FIRST_MOVE - the session's first swing (the "Judas" swing). In each SESSION and KILLZONE
WINDOW instance, the first EXTREME whose bar is inside it: a swing high means the first move was up
(↑), a swing low down (↓); a high and a low on the same first bar give both. At the extreme's bar,
known when the extreme is (three bars later). `kind`, `name`, `window`, `extreme`, `price`, `open`
(the window's first open), `move_atr` (from that open to the extreme, the move's way, in ATR),
`bars` (from the window's first bar). The MCFL fact is the first swing; whether it was a Judas swing
(a false move, reversed) is the outcome, measured in `time_study.py`, not part of the definition.

LATE / EARLY - an event outside its usual hours. For the TIMED types (BREAK, DISPLACE, ZONE,
CHARACTER_SHIFT, SESSION_EXTREME_TAKEN, POOL_TAKEN, SESSION_FIRST_MOVE), an event whose hour rate
(`Span.hour_rate`, item 8) is under RARE_RATE (0.5: half the type's average hour) is LATE when its
hour is after the type's usual hour (the circular mean of its recent hours, within 12 hours), EARLY
when before. Direction, bar and known_at are the event's; `of`, `of_type`, `hour`, `hour_rate`,
`usual_hour`.
"""
from __future__ import annotations

import numpy as np

from mcfl.candles import Table
from mcfl.core import Dir, Entity, attrs_of, make_id
from mcfl.grammar import C, Rule, Slot
from mcfl.seasonal import Rolling

TIMEOUT_BARS = 48
"""N: bars after a structure is known with nothing of its lifecycle before a TIMEOUT (half a day of
15-minute bars, two days of hourly ones)."""
STALL_ATR = 1.0
STALL_MAX = 192
STALL_Q = 0.90
STALL_N = 120
STALL_MIN = 30
TIMED = ("BREAK", "DISPLACE", "ZONE", "CHARACTER_SHIFT", "SESSION_EXTREME_TAKEN", "POOL_TAKEN", "SESSION_FIRST_MOVE")
RARE_RATE = 0.5


def _timeout_attrs(slot: str, kind: str):
    def attrs(b: dict[str, list[Entity]], d: Dir) -> dict:
        return {"of": b[slot][0].id, "kind": kind, "bars": TIMEOUT_BARS}
    return attrs


def _timeout(kind: str, events: tuple[str, ...], sym: bool = False) -> Rule:
    slot = kind.lower()
    key = slot
    return Rule(
        head="TIMEOUT", anchor=slot, horizon=None, report=False, timed=True, sym=sym,
        decide=("+", f"{slot}.known_at", TIMEOUT_BARS), suffix=(slot[0], f"{slot}.at"),
        slots=(Slot(slot, kind, dir="any" if sym else "same"),
               *(Slot(f"no_{e.lower()}", e, min=0, absent=True, dir="any" if sym else "same", where=(
                   C("at", ">=", f"{slot}.at"),
                   C("at", "<=", ("+", f"{slot}.known_at", TIMEOUT_BARS)),
                   C(key, "==", f"{slot}.id"))) for e in events)),
        sequence=(slot,), attrs=_timeout_attrs(slot, kind))


RULES: dict[str, Rule] = {
    "TIMEOUT_ZONE": _timeout("ZONE", ("REVISIT",)),
    "TIMEOUT_VOID": _timeout("VOID", ("VOID_PARTIAL",)),
    "TIMEOUT_RANGE": _timeout("RANGE", ("FAILED_ESCAPE", "ESCAPE"), sym=True),
}


# ---------------------------------------------------------------- STALL

def confinement(T: Table) -> np.ndarray:
    """Per bar: how many bars back (itself included) fit in STALL_ATR x its ATR, at most STALL_MAX."""
    h, l, a = T["high"], T["low"], T["atr"]
    n = len(h)
    thr = STALL_ATR * a
    hi, lo = h.copy(), l.copy()
    c = np.zeros(n, np.int64)
    alive = np.isfinite(thr) & (hi - lo <= thr)
    c[alive] = 1
    for k in range(2, STALL_MAX + 1):
        if not alive.any():
            break
        sh = np.r_[np.full(k - 1, np.nan), h[:n - k + 1]] if n >= k else np.full(n, np.nan)
        sl = np.r_[np.full(k - 1, np.nan), l[:n - k + 1]] if n >= k else np.full(n, np.nan)
        hi = np.fmax(hi, sh)
        lo = np.fmin(lo, sl)
        with np.errstate(invalid="ignore"):
            alive &= np.isfinite(sh) & (hi - lo <= thr)
        c[alive] = k
    return c


def stalls(T: Table, ts: np.ndarray | None, cid: list[str]) -> list[Entity]:
    c = confinement(T)
    n = len(c)
    hr = (np.asarray(ts, np.int64) // 3600) % 24 if ts is not None else np.zeros(n, np.int64)
    win: dict[int, Rolling] = {}
    out, above = [], False
    for t in range(n):
        d = win.get(int(hr[t]))
        if d is None:
            d = win[int(hr[t])] = Rolling(STALL_N)
        if len(d) >= STALL_MIN:
            q = float(d.quantile(STALL_Q))
            now = c[t] > q
            if now and not above:
                out.append(Entity(make_id("STALL", Dir.NONE, t), "STALL", Dir.NONE, t, t, attrs_of({
                    "bars": int(c[t]), "usual": q, "hour": int(hr[t]) if ts is not None else None}),
                    parts=tuple(cid[t - int(c[t]) + 1:t + 1])))
            above = now
        else:
            above = False
        d.add(int(c[t]))
    return out


# ---------------------------------------------------------------- SESSION_FIRST_MOVE

def first_moves(T: Table, lay: dict, ext: list[Entity], windows: list[Entity]) -> list[Entity]:
    atr = T["atr"]
    out = []
    by_window = {(w.get("name"), w.at): w for w in windows if w.get("kind") in ("SESSION", "KILLZONE")}
    first: dict[tuple[str, int], list[Entity]] = {}
    for e in sorted(ext, key=lambda e: (e.at, e.dir.value)):
        for name, ins in lay.items():
            if ins.kind not in ("SESSION", "KILLZONE") or ins.first[e.at] < 0:
                continue
            k = (name, int(ins.first[e.at]))
            got = first.setdefault(k, [])
            if not got or got[0].at == e.at:
                got.append(e)
    for (name, a), es in first.items():
        w = by_window.get((name, a))
        if w is None:
            continue
        op = w.get("open")
        for e in es:
            s = 1.0 if e.dir is Dir.UP else -1.0
            A = atr[e.at]
            out.append(Entity(make_id("SESSION_FIRST_MOVE", e.dir, e.at, name), "SESSION_FIRST_MOVE", e.dir, e.at,
                              e.known_at, attrs_of({
                                  "kind": w.get("kind"), "name": name, "window": w.id, "extreme": e.id,
                                  "price": e.get("price"), "open": op,
                                  "move_atr": float(s * (e.get("price") - op) / A) if A > 0 else None,
                                  "bars": e.at - a}), parts=(w.id, e.id)))
    return out


# ---------------------------------------------------------------- LATE / EARLY

def off_hours(ents: list[Entity], ts: np.ndarray | None) -> list[Entity]:
    from mcfl.seasonal import hour_profile
    if ts is None:
        return []
    prof = hour_profile([e for e in ents if e.type in TIMED], ts)
    out = []
    for e in ents:
        if e.id not in prof:
            continue
        rate, usual = prof[e.id]
        if rate >= RARE_RATE:
            continue
        h = int((ts[e.at] // 3600) % 24)
        off = (h + 0.5 - usual + 12) % 24 - 12
        kind = "LATE" if off >= 0 else "EARLY"
        rest = e.id.split(".", 3)
        sfx = e.type + ("_" + rest[3].replace(".", "_") if len(rest) > 3 else "")  # the event's id without its direction
        out.append(Entity(make_id(kind, e.dir, e.at, sfx), kind, e.dir, e.at, e.known_at, attrs_of({
            "of": e.id, "of_type": e.type, "hour": h, "hour_rate": rate, "usual_hour": usual}), parts=(e.id,)))
    return out
