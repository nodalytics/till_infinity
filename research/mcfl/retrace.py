"""v2 item 7: retracement depth, on every REVISIT and on the pullbacks of every BREAK's leg.

depth = retracement / leg, for an up structure (down is the flipped chart):

    leg          from the structure's low L (a ZONE's far edge, a BREAK's origin low) to the peak P
    retracement  from P down to the pullback's low x
    depth        (P - x) / (P - L), binned SHALLOW < 0.382 <= HALF < 0.618 <= DEEP <= 1 < BEYOND
                 (BEYOND: past the leg's origin)

RETRACE (L2), on every REVISIT of a zone at bar t: P = the highest high from the origin to the bar
before t, x = low[t]. Known at t; parts the REVISIT.

PULLBACK (L2), two per BREAK at most, from origin p to break b:
    INSIDE  the last swing low (EXTREME, opposite direction) strictly between p and b, above the
            origin's low and confirmed by the time the break is known - the DAX course's "structural
            liquidity". P = the highest high of p..b (the leg to the break), x = its price. Known at
            the break's known_at.
    AFTER   the first swing low after b. P = the highest high of p..that swing, x = its price. Known
            at max(the break's known_at, the swing's).
Attributes: `break`, `phase`, `depth`, `depth_bin`, `peak`, `level` (x); parts the BREAK and the
EXTREME.

The DAX 50% rule (`dax_smc.py` step 3: the structural liquidity is valid at or below the 50% of the
leg) is then one production in the rule table, DAX50 := BREAK PULLBACK[phase=INSIDE, depth≥0.5].
"""
from __future__ import annotations

import bisect

from mcfl.candles import Table
from mcfl.core import Dir, Entity, attrs_of, make_id
from mcfl.grammar import C, ENTITY_ORDERS, Rule, Slot, qe

DEPTH_BINS = ("SHALLOW", "HALF", "DEEP", "BEYOND")
ENTITY_ORDERS["depth"] = ("depth_bin", DEPTH_BINS)
FIB_LO, FIB_HI = 0.382, 0.618
DAX_HALF = 0.5
"""The DAX course's 50%: the structural liquidity at or below half the leg."""


def depth_bin(d: float) -> str:
    if d < FIB_LO:
        return "SHALLOW"
    if d < FIB_HI:
        return "HALF"
    return "DEEP" if d <= 1.0 else "BEYOND"


def _depth(peak: float, low: float, x: float) -> float | None:
    leg = peak - low
    return float((peak - x) / leg) if leg > 0 else None


def retraces(fr: dict[int, Table], zones: list[Entity], life: list[Entity]) -> list[Entity]:
    """RETRACE: the depth of every REVISIT, against its zone's leg."""
    zs = {z.id: z for z in zones}
    out = []
    for r in life:
        if r.type != "REVISIT":
            continue
        z = zs[r.get("zone")]
        side = 1 if z.dir is Dir.UP else -1
        F = fr[side]
        p, t = z.at, r.at
        low, peak, x = F["low"][p], float(F["high"][p:t].max()), F["low"][t]
        d = _depth(peak, low, x)
        if d is None:
            continue
        out.append(Entity(make_id("RETRACE", z.dir, t, f"z{p}"), "RETRACE", z.dir, t, r.known_at, attrs_of({
            "revisit": r.id, "count": r.get("count"), "depth": d, "depth_bin": depth_bin(d),
            "peak": float(side * peak), "level": float(side * x)}), parts=(r.id,)))
    return out


def pullbacks(fr: dict[int, Table], level: list[Entity], ext: list[Entity]) -> list[Entity]:
    """PULLBACK INSIDE and AFTER for every BREAK."""
    out = []
    for side, d in ((1, Dir.UP), (-1, Dir.DOWN)):
        F = fr[side]
        h, l = F["high"], F["low"]
        lows = sorted((e for e in ext if e.dir is d.flip()), key=lambda e: e.at)
        ats = [e.at for e in lows]
        for b in (e for e in level if e.type == "BREAK" and e.dir is d):
            p = int(b.get("origin").split(".")[2])
            low = l[p]
            i0, i1 = bisect.bisect_right(ats, p), bisect.bisect_left(ats, b.at)
            # only swings confirmed by the time the break is known: a swing just before the break is
            # confirmed up to three bars after it, and a later "last swing" would replace, with hindsight,
            # the pullback a reader at the break had already been given (found by the time core's
            # calendar truncation test, 2026-10-04)
            inner = [e for e in lows[i0:i1] if side * e.get("price") > low and e.known_at <= b.known_at]
            cands = []
            if inner:
                cands.append(("INSIDE", inner[-1], float(h[p:b.at + 1].max())))
            j = bisect.bisect_right(ats, b.at)
            if j < len(lows):
                e = lows[j]
                cands.append(("AFTER", e, float(h[p:e.at + 1].max())))
            for phase, e, peak in cands:
                x = side * e.get("price")
                dep = _depth(peak, low, x)
                if dep is None:
                    continue
                out.append(Entity(make_id("PULLBACK", d, e.at, f"{phase[0].lower()}{b.at}o{p}"), "PULLBACK", d, e.at,
                                  max(b.known_at, e.known_at), attrs_of({
                                      "break": b.id, "phase": phase, "depth": dep, "depth_bin": depth_bin(dep),
                                      "peak": float(side * peak), "level": e.get("price")}),
                                  parts=(b.id, e.id)))
    return out


def _dax50_attrs(b: dict[str, list[Entity]], d: Dir) -> dict:
    pb = b["pullback"][0]
    return {"break": b["break"][0].id, "pullback": pb.id, "depth": pb.get("depth")}


#: v2 productions over entities (the rule table's v2 rows), applied by `grammar.apply`.
RULES = {
    "DAX50": Rule(
        head="DAX50", anchor="break", horizon=None, report=False,
        decide=("+", "break.at", 3), attrs=_dax50_attrs,
        slots=(
            Slot("break", "BREAK"),
            Slot("pullback", "PULLBACK", where=(
                C("break", "==", "break.id"),
                *qe(f"PULLBACK[phase=INSIDE, depth≥{DAX_HALF}]"))),
        ),
        sequence=("break", "pullback"),
    ),
}
"""DAX50_UP := BREAK_UP PULLBACK_UP[phase=INSIDE, depth≥0.5] - the DAX course's 50% rule: the
structural liquidity of the leg that broke sits at or below half of it."""

