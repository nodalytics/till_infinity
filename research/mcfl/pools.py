"""v2 item 6: liquidity pools, and the DAX course's protected sweep.

POOL (L3), EQUAL_HIGHS (POOL↑) and EQUAL_LOWS (POOL↓). Written for highs; lows are the flipped
chart. When a swing high e (an EXTREME) becomes known, every earlier swing high q that is

    within tolerance   |price(q) - price(e)| <= POOL_EQ_ATR x ATR(14) at e, and
    still standing     no high strictly between them above the higher of the two

joins e in a pool: a POOL at e's bar, known with e, `count` = 1 + the number of such q, `level` = the
highest member's price, its parts the member EXTREMEs. A third equal high makes a new
POOL (count 3) at its own bar; the earlier one stays as it was.

POOL_TAKEN (L2): the first bar after the pool's last member whose high is above `level` - the pool
traded through. Attributes `pool`, `level`, `closed_back` (its close at or below the level: a sweep of
the pool; else it closed through), `depth_atr`, and `breach_revert`: how many of its members had a
BREACH_REVERT (v0's traded-through-and-closed-back, per swing) on that bar - which happens exactly
when the take closed back and that member had not been closed through before. Its parts are the
POOL and those BREACH_REVERT events (relation LINK). Known at its bar.

SWEEP_PROTECTED (L2), `dax_smc.py` step 1 exactly, for a buy (a sell is the flipped chart): a swing
low s that trades below the last swing low q of the SWEEP_BACK (40) bars before it - q known by s,
and nothing traded below q between them - and closes back above q on s or the bar after. The low at
s is then PROTECTED. Direction UP (it protects an up move, like the ORIGIN at the same bar); at s,
known at s + 3 (the swing); attributes `swept` (q's EXTREME), `swept_level`, `level` (s's low),
`origin` (the ORIGIN at s); parts the two EXTREMEs.

DAX_SETUP (L3), DAX steps 1-3 as one production: SWEEP_PROTECTED, the BREAK from its origin, and the
leg's inside pullback at or below 50% (item 7's DAX50).
"""
from __future__ import annotations

import bisect

import numpy as np

from mcfl.candles import Table
from mcfl.core import SIDES, Dir, Entity, attrs_of, make_id
from mcfl.grammar import C, Rule, Slot, qe

POOL_EQ_ATR = 0.1
"""Two swings are at the same level within this many ATR(14) at the later one (the swing labels'
SWING_EQ_ATR)."""
SWEEP_BACK = 40
"""dax_smc's SWEEP_BACK: the swept low is the last swing low of this many bars before the sweep."""
SWEEP_CLOSE = 2
"""dax_smc: the close back above the swept low on the sweep bar or the next (c[s:s + 2])."""


def pools(fr: dict[int, Table], ext: list[Entity], level_ents: list[Entity]) -> list[Entity]:
    """POOL and POOL_TAKEN, both sides."""
    brev = {e.id for e in level_ents if e.type == "BREACH_REVERT"}
    out = []
    for side, d in zip((1, -1), SIDES):
        F = fr[side]
        h, c, a = F["high"], F["close"], F["atr"]
        highs = sorted((e for e in ext if e.dir is d), key=lambda e: e.at)
        for i, e in enumerate(highs):
            pe = side * e.get("price")
            A = a[e.at]
            tol = POOL_EQ_ATR * A if A > 0 else 0.0
            mem = []
            for q in highs[:i]:
                pq = side * q.get("price")
                if abs(pq - pe) <= tol and (q.at + 1 >= e.at or h[q.at + 1:e.at].max() <= max(pq, pe)):
                    mem.append(q)
            if not mem:
                continue
            mem.append(e)
            lvl = max(side * m.get("price") for m in mem)
            pid = make_id("POOL", d, e.at)
            out.append(Entity(pid, "POOL", d, e.at, e.known_at, attrs_of({
                "kind": "EQUAL_HIGHS" if d is Dir.UP else "EQUAL_LOWS", "count": len(mem),
                "level": float(side * lvl), "first": mem[0].at}), parts=tuple(m.id for m in mem)))
            hit = np.flatnonzero(h[e.at + 1:] > lvl)
            if not len(hit):
                continue
            t = e.at + 1 + int(hit[0])
            back = bool(c[t] <= lvl)
            revs = tuple(sorted(x for x in (make_id("BREACH_REVERT", d, t, f"x{m.at}") for m in mem) if x in brev))
            out.append(Entity(make_id("POOL_TAKEN", d, t, f"p{e.at}"), "POOL_TAKEN", d, t, t, attrs_of({
                "pool": pid, "level": float(side * lvl), "closed_back": back,
                "depth_atr": float((h[t] - lvl) / a[t]) if a[t] > 0 else None, "breach_revert": len(revs)}),
                parts=(pid,) + revs))
    return out


def sweeps(fr: dict[int, Table], ext: list[Entity]) -> list[Entity]:
    """SWEEP_PROTECTED, both sides: dax_smc's protected low, step 1 of its checklist."""
    out = []
    for side, d in zip((1, -1), SIDES):
        F = fr[side]
        l, c, a = F["low"], F["close"], F["atr"]
        pl = sorted(((e.known_at, e.at, side * e.get("price"), e.id) for e in ext if e.dir is d.flip()),
                    key=lambda x: x[1])
        ats = [x[1] for x in pl]
        for known_s, s, low_s, sid in pl:
            if not a[s] > 0:
                continue
            lo = bisect.bisect_left(ats, s - SWEEP_BACK)
            prior = [x for x in pl[lo:bisect.bisect_left(ats, s)] if x[0] <= s]
            if not prior:
                continue
            _, q, q_px, qid = prior[-1]
            if not (low_s < q_px and l[q + 1:s].min(initial=np.inf) >= q_px and c[s:s + SWEEP_CLOSE].max() > q_px):
                continue
            out.append(Entity(make_id("SWEEP_PROTECTED", d, s), "SWEEP_PROTECTED", d, s, max(known_s, s + 1), attrs_of({
                "swept": qid, "swept_level": float(side * q_px), "level": float(side * low_s),
                "origin": make_id("ORIGIN", d, s)}), parts=(qid, sid)))
    return out


def _setup_attrs(b: dict[str, list[Entity]], d: Dir) -> dict:
    return {"sweep": b["sweep"][0].id, "break": b["break"][0].id, "pullback": b["pullback"][0].id,
            "depth": b["pullback"][0].get("depth")}


RULES = {
    "DAX_SETUP": Rule(
        head="DAX_SETUP", anchor="sweep", horizon=None, report=False, attrs=_setup_attrs,
        decide=("+", "sweep.at", 20 + 3),
        slots=(
            Slot("sweep", "SWEEP_PROTECTED"),
            Slot("break", "BREAK", where=(C("origin", "==", "sweep.origin"),)),
            Slot("pullback", "PULLBACK", where=(C("break", "==", "break.id"),
                                                *qe("PULLBACK[phase=INSIDE, depth≥0.5]"))),
        ),
        sequence=("sweep", "break", "pullback"),
    ),
}
"""DAX_SETUP_UP := SWEEP_PROTECTED_UP BREAK_UP PULLBACK_UP[phase=INSIDE, depth≥0.5]
    where BREAK.origin == SWEEP_PROTECTED.origin and PULLBACK.break == BREAK.id
The DAX checklist's steps 1-3: the protected sweep, the break from it (v1's BREAK: within LEG_MAX = 20
bars, where dax_smc allows 60), and the structural liquidity at or below half the leg."""
