"""Sweeps: the close-beyond failure, the sweep followed by a shift, inducement, broken structures
retested or reclaimed, and protected highs and lows (the sweeps study, `docs/sweeps.md`).

What MCFL already had, and which this module reuses rather than repeats:

    wick sweep / swing failure (SFP)    BREACH_REVERT       a confirmed swing traded through, closed back
    equal highs / lows swept            POOL_TAKEN[SWEPT]   (pools.py)
    candle-range sweep (CRT)            PURGE               (crt.py; an HTF candle's is mtf.crt)
    session raid                        SESSION_EXTREME_TAKEN with closed_back (timing.py)
    Judas swing                         SESSION_FIRST_MOVE (timed.py)
    the DAX course's protected low      SWEEP_PROTECTED (pools.py)
    inverted FVG                        VOID_INVERTED (voids.py)

What this module adds. Everything is written for the up side (a swing LOW swept, an up ZONE) and run
on the chart and on the chart flipped; directions follow the convention of the entity each one
extends, said per entity below.

CLOSE_REVERT (L2), the close-beyond failure (the "turtle soup"). A swing low (EXTREME↓, price P,
known at k) whose first close below P after k is at bar u, and one of the next TURTLE_N (3) bars
closes back at or above P: at the first such bar v, known there. Once per extreme (its first close
beyond). Direction the breach's, as BREACH_REVERT's: CLOSE_REVERT↓ is a low closed through and
reclaimed. Attributes `extreme`, `level` (P), `through` (u), `bars` (v - u), `depth_atr` (how far the
lows of u..v went under P, ATR at v). Parts the tokens u..v.

SWEEP_SHIFT (L3), a sweep followed by a shift the other way. Rows of the rule table (`RULES`):

    SWEEP_SHIFT_UP := (BREACH_REVERT↓ | CLOSE_REVERT↓) (DISPLACE_C↑ | DELIVERY_SHIFT↑)
                      where shift.at - SHIFT_K <= sweep.at <= shift.at

a low swept (wicked through, or closed through and reclaimed) and, on the same bar or within
SHIFT_K (3) bars after it, a displacement or a delivery shift (CISD) up. Direction the shift's (the
reversal's): SWEEP_SHIFT↑ follows a low swept. At the shift's bar, known there. The rows are tried
in the order BREACH_REVERT before CLOSE_REVERT, DISPLACE_C before DELIVERY_SHIFT; the first that
matches makes the one event of that bar and direction, binding its earliest sweep in the window. Attributes `sweep`, `sweep_type`,
`shift`, `shift_type`, `level` (the swept level), `bars` (shift.at - sweep.at).

INDUCEMENT (L2), a minor swing taken shortly before price reaches a zone. At a ZONE↑'s first REVISIT
(bar r): a swing low s above the zone's near edge, known before it was taken, whose first trade
below (its take) is within INDUCE_N (10) bars before r or on r. The latest-taken such swing is bound
(the lowest on a tie). At r, known at r; direction the zone's. Attributes `zone`, `revisit`,
`extreme`, `level` (s's price), `taken_at`, `bars` (r - taken_at), `gap_atr` ((level - near) / the
zone's ATR). A revisit without one is the comparison.

BREAKER_RETEST and RECLAIM (L2), a broken structure's first return. A ZONE↑ broken by its FAIL (a
close under far - 0.1 ATR) or a VOID↑ by its VOID_INVERTED (a close under its far edge), at bar f.
The edge is the structure's far edge (the zone's `far`, the void's high[k-2]). The first bar t in
f+1 .. f+BREAKER_MAX (100) whose high reaches the edge again is the return:

    BREAKER_RETEST   its close stays at or under the edge: the broken structure is now the other
                     side's level (the breaker, the inverse FVG's retest)
    RECLAIM          its close is back above the edge: the break failed (broken, then reclaimed)

At t, known at t; direction the structure's (lifecycle events keep their structure's direction:
BREAKER_RETEST↑ is a bearish fact about a broken up zone). Attributes `of` (the structure), `kind`
(ZONE or VOID), `level` (the edge), `broke_at` (f), `bars` (t - f), `wick_atr` ((high - edge) / ATR
at t).

PROTECTED (L3), protected highs and lows. For the leg from every swing low p (its ORIGIN and LEG):

    STRONG        the leg BROKE structure (its close above the last swing high known at p: the
                  BREAK, the trader's BOS when it is WITH the structure) without trading under p -
                  the low that caused the break
    SWEEP_STRONG  STRONG, and the low at p swept the previous swing low (SWEEP_PROTECTED) and the
                  leg DISPLACED (2 ATR) at or before the break - the strongest kind
    WEAK          the leg timed out (LEG_MAX bars, no break, never traded under p)

A leg that traded under p (INVALIDATED) makes no PROTECTED: the low did not hold to be graded. STRONG
and SWEEP_STRONG are known with their parts (the BREAK, and the SWEEP_PROTECTED and DISPLACE), WEAK at
the leg's end; one is made only if the low still stands at that bar. Direction UP (it protects an up
move, like the ORIGIN at p); at p. Attributes `grade`, `level` (p's low), `origin`, `break` (or None),
`bos` (the BREAK's vs_structure is WITH). Parts the LEG and, if any, the BREAK, SWEEP_PROTECTED and
DISPLACE.

PROTECTED_TAKEN (L2): the first bar after the PROTECTED is known whose low is under its level.
`protected`, `grade`, `level`, `closed_back` (its close at or above the level: the protected low was
swept rather than broken), `bars` (from the PROTECTED's known_at). Known at its bar. Whether the
level held until the next break of structure is the outcome, measured in `ideas/sweeps.py`, not
part of the definition.
"""
from __future__ import annotations

import numpy as np

from mcfl.candles import Table
from mcfl.core import SIDES, Dir, Entity, attrs_of, make_id
from mcfl.grammar import C, Rule, Slot
from mcfl.parse import LEG_MAX

TURTLE_N = 3
"""Bars after the first close beyond a swing within which a close back makes a CLOSE_REVERT."""
SHIFT_K = 3
"""Bars after a sweep within which a DISPLACE_C or DELIVERY_SHIFT the other way makes a SWEEP_SHIFT."""
INDUCE_N = 10
"""Bars before a zone's first revisit within which a swing above the zone taken is an INDUCEMENT."""
BREAKER_MAX = 100
"""Bars after a structure broke within which its first return is a BREAKER_RETEST or a RECLAIM."""
GRADES = ("WEAK", "STRONG", "SWEEP_STRONG")


def _f(x: float) -> float | None:
    return float(x) if np.isfinite(x) else None


def close_reverts(fr: dict[int, Table], ext: list[Entity], cid: list[str]) -> list[Entity]:
    """CLOSE_REVERT, both sides: a swing's first close beyond, closed back within TURTLE_N bars."""
    out = []
    for side, dn in ((1, Dir.DOWN), (-1, Dir.UP)):
        F = fr[side]
        l, c, a = F["low"], F["close"], F["atr"]
        n = len(c)
        for e in ext:
            if e.dir is not dn:
                continue
            P = side * e.get("price")
            s0 = e.known_at + 1
            if s0 >= n:
                continue
            beyond = np.flatnonzero(c[s0:] < P)
            if not len(beyond):
                continue
            u = s0 + int(beyond[0])
            back = np.flatnonzero(c[u + 1:u + 1 + TURTLE_N] >= P)
            if not len(back):
                continue
            v = u + 1 + int(back[0])
            out.append(Entity(make_id("CLOSE_REVERT", dn, v, f"x{e.at}"), "CLOSE_REVERT", dn, v, v, attrs_of({
                "extreme": e.id, "level": float(side * P), "through": u, "bars": v - u,
                "depth_atr": _f((P - l[u:v + 1].min()) / a[v]) if a[v] > 0 else None}),
                parts=tuple(cid[u:v + 1])))
    return out


def _shift_attrs(b: dict[str, list[Entity]], d: Dir) -> dict:
    s, x = b["sweep"][0], b["shift"][0]
    return {"sweep": s.id, "sweep_type": s.type, "shift": x.id, "shift_type": x.type,
            "level": s.get("level"), "bars": x.at - s.at}


def _shift_rule(sweep: str, shift: str) -> Rule:
    return Rule(
        head="SWEEP_SHIFT", anchor="shift", horizon=None, report=False, attrs=_shift_attrs,
        slots=(
            Slot("shift", shift),
            Slot("sweep", sweep, dir="any", where=(
                C("at", ">=", ("+", "shift.at", -SHIFT_K)), C("at", "<=", "shift.at"),
                C("dir", "==", "DOWN"))),  # the other way: a low swept, for a shift up
        ),
        sequence=("sweep", "shift"),
    )


RULES = {f"SWEEP_SHIFT_{a}_{b}": _shift_rule(s, x)
         for a, s in (("BR", "BREACH_REVERT"), ("CR", "CLOSE_REVERT"))
         for b, x in (("C", "DISPLACE_C"), ("D", "DELIVERY_SHIFT"))}
"""SWEEP_SHIFT_UP := (BREACH_REVERT↓ | CLOSE_REVERT↓) (DISPLACE_C↑ | DELIVERY_SHIFT↑)
    where shift.at - 3 <= sweep.at <= shift.at                 (four rows, one event per bar)"""


def inducements(fr: dict[int, Table], ext: list[Entity], zones: list[Entity], life: list[Entity]) -> list[Entity]:
    """INDUCEMENT, both sides: at a zone's first revisit, the swing above it taken just before."""
    first = {}
    for e in life:
        if e.type == "REVISIT" and e.get("count") == 1:
            first[e.get("zone")] = e
    out = []
    for side, d in zip((1, -1), SIDES):
        F = fr[side]
        l = F["low"]
        n = len(l)
        sl = [e for e in ext if e.dir is d.flip()]  # the frame's swing lows
        px = np.array([side * e.get("price") for e in sl], float)
        tk = np.empty(len(sl), int)  # each one's first take: the first bar after it is known with a low under it
        for i, e in enumerate(sl):
            s0 = e.known_at + 1
            hit = np.flatnonzero(l[s0:] < px[i]) if s0 < n else np.array([], int)
            tk[i] = s0 + int(hit[0]) if len(hit) else n
        for z in zones:
            if z.dir is not d or z.id not in first:
                continue
            rv = first[z.id]
            r = rv.at
            near, A = side * z.get("near"), z.get("atr")
            ok = np.flatnonzero((px > near) & (tk >= r - INDUCE_N) & (tk <= r))
            if not len(ok):
                continue
            i = int(ok[np.lexsort((px[ok], -tk[ok]))[0]])  # the latest taken, the lowest on a tie
            P, t_ = float(px[i]), int(tk[i])
            out.append(Entity(make_id("INDUCEMENT", d, r, f"z{z.at}"), "INDUCEMENT", d, r, r, attrs_of({
                "zone": z.id, "revisit": rv.id, "extreme": sl[i].id, "level": float(side * P), "taken_at": t_,
                "bars": r - t_, "gap_atr": _f((P - near) / A) if A > 0 else None}), parts=(z.id, rv.id, sl[i].id)))
    return out


def breakers(fr: dict[int, Table], zones: list[Entity], life: list[Entity], voids: list[Entity],
             void_events: list[Entity], cid: list[str]) -> list[Entity]:
    """BREAKER_RETEST and RECLAIM, both sides: a broken zone's or void's first return to its far edge."""
    broke = {e.get("zone"): e for e in life if e.type == "FAIL"}
    broke.update({e.get("void"): e for e in void_events if e.type == "VOID_INVERTED"})
    out = []
    for s in list(zones) + list(voids):
        if s.id not in broke:
            continue
        side = 1 if s.dir is Dir.UP else -1
        F = fr[side]
        h, c, a = F["high"], F["close"], F["atr"]
        n = len(c)
        edge = side * s.get("far") if s.type == "ZONE" else F["high"][s.at - 2]
        f = broke[s.id].at
        hit = np.flatnonzero(h[f + 1:min(n, f + 1 + BREAKER_MAX)] >= edge)
        if not len(hit):
            continue
        t = f + 1 + int(hit[0])
        kind = "RECLAIM" if c[t] > edge else "BREAKER_RETEST"
        out.append(Entity(make_id(kind, s.dir, t, f"{s.type[0].lower()}{s.at}"), kind, s.dir, t, t, attrs_of({
            "of": s.id, "kind": s.type, "level": float(side * edge), "broke_at": f, "bars": t - f,
            "wick_atr": _f((h[t] - edge) / a[t]) if a[t] > 0 else None}), parts=(s.id, broke[s.id].id, cid[t])))
    return out


def protected(fr: dict[int, Table], level: list[Entity], sweeps: list[Entity]) -> list[Entity]:
    """PROTECTED and PROTECTED_TAKEN, both sides."""
    ids = {e.id: e for e in level}
    sw = {e.id: e for e in sweeps}
    disp = {e.get("origin"): e for e in level if e.type == "DISPLACE"}  # one per origin
    out = []
    for side, up in zip((1, -1), SIDES):
        F = fr[side]
        l, c = F["low"], F["close"]
        for leg in (e for e in level if e.type == "LEG" and e.dir is up):
            p, reason = leg.at, leg.get("reason")
            if reason not in ("BREAK", "TIMEOUT"):
                continue
            low = l[p]
            parts, brk = [leg.id], None
            if reason == "BREAK":
                brk = ids[make_id("BREAK", up, leg.get("end"), f"o{p}")]
                parts.append(brk.id)
                grade, known = "STRONG", brk.known_at
                sp, dsp = sw.get(make_id("SWEEP_PROTECTED", up, p)), disp.get(leg.get("origin"))
                if sp is not None and dsp is not None and dsp.at <= brk.at:
                    grade = "SWEEP_STRONG"
                    parts += [sp.id, dsp.id]
                    known = max(known, sp.known_at, dsp.known_at)
            else:
                grade, known = "WEAK", leg.known_at
            if l[p + 1:known + 1].min(initial=np.inf) < low:
                continue  # already traded under by the bar it could be graded
            pid = make_id("PROTECTED", up, p)
            out.append(Entity(pid, "PROTECTED", up, p, known, attrs_of({
                "grade": grade, "level": float(side * low), "origin": leg.get("origin"),
                "break": brk.id if brk is not None else None,
                "bos": bool(brk is not None and brk.get("vs_structure") == "WITH")}), parts=tuple(parts)))
            hit = np.flatnonzero(l[known + 1:] < low)
            if len(hit):
                t = known + 1 + int(hit[0])
                out.append(Entity(make_id("PROTECTED_TAKEN", up, t, f"p{p}"), "PROTECTED_TAKEN", up, t, t, attrs_of({
                    "protected": pid, "grade": grade, "level": float(side * low),
                    "closed_back": bool(c[t] >= low), "bars": t - known}), parts=(pid,)))
    return out


def run(fr, ext, level, zones, life, voids, void_events, sweeps, words, cid, grammar, n) -> list[Entity]:
    """Every entity of this module, in dependency order."""
    cr = close_reverts(fr, ext, cid)
    pool = [e for e in level if e.type == "BREACH_REVERT"] + cr + [e for e in words if e.type in ("DISPLACE_C",
                                                                                                    "DELIVERY_SHIFT")]
    shifts, _, _ = grammar(pool, RULES, n=n)
    return (cr + shifts + inducements(fr, ext, zones, life) + breakers(fr, zones, life, voids, void_events, cid)
            + protected(fr, level, sweeps))
