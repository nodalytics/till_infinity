"""OHLC bars to MCFL: the L1 tokens, the L2 events built from them, the ORIGIN and LEG
structures, then the grammar (ZONE), the lifecycle, the candle-level REJECT and the materialised
relations.

Layers. L0, the bars, is only the input. L1 is one CANDLE token per bar (and one BAR_RELATION
from the second bar), each carrying its raw bar as a lexeme (`candles.py`). Every L2 event is a
production over L1 tokens and lists the tokens it consumed in `parts`:

- pattern events (PIN, ENGULF, INSIDE_BREAK, STAR, DISPLACE_C, and REJECT) read the tokens'
  fuzzy classes and strength grades - the WORDS and CANDLE_RULES of `grammar.py` (REJECT also
  needs one price condition, the close back out of the zone); DELIVERY_SHIFT (CISD) is a scan over
  a run of tokens with one price condition, in `grammar.py` too;
- level events cannot be decided from the classes, which discard absolute price. They are
  attributed rules: a match on tokens plus a semantic condition on the tokens' prices. EXTREME and
  VOID are fixed-window words (`grammar.WORDS`); the rest scan a variable run of tokens and are
  the functions below and in `lifecycle.py`, catalogued in LEVEL_RULES.

Every directional rule is written once, for the up side, and run twice: on the token table and on
the flipped one (`candles.frame`). Down events are the up events of the flipped chart with their
prices negated back. Symmetry is then a property of the construction, and `tests/test_symmetry.py`
checks the plumbing that maps it back.

Causality: a bar's close is known at that bar. A 3/3 swing at p is known at p + 3. An entity's
`known_at` is the latest bar any of its inputs needed; nothing reads a later one.
"""
from __future__ import annotations

import bisect

import numpy as np
import pandas as pd

from mcfl import candles
from mcfl.core import Chart, Dir, Entity, Force, Relation, attrs_of, make_id, sort_key
from mcfl.grammar import SWING

ATR_N = candles.ATR_N
"""Wilder ATR length; every threshold below is in units of it (`prims.atr`, the lexeme's `atr`)."""
LEG_MAX = 20
"""Bars a LEG may run from its origin before it times out (zone_events' MAXLEG). It caps how long
the breaking move may take - origin to break - and says nothing about the age of the level broken,
which can be any number of bars old (a BREAK's `ref_age`)."""
DISPLACE_MIN = 2.0
"""ATR the leg must travel from the origin extreme for a DISPLACE (zone_events' DISP_MIN)."""
ORIGIN_MIN_HEIGHT = 0.05
"""An ORIGIN band is at least this many ATR tall (zone_events widens thin bands the same way)."""
SURPRISE_LOOKBACK = 20
"""Bars before the origin whose mean true range is the base of a BREAK's surprise."""
SURPRISE_MIN_BARS = 5
"""Fewer bars than this before the origin and surprise is undefined (None)."""

#: The level productions that scan a variable run of tokens: syntax, and the semantic condition on
#: the tokens' attributes. Written for the up side. (EXTREME and VOID are WORDS in grammar.py.)
LEVEL_RULES = {
    "ORIGIN": ("EXTREME↓ at p", "atr[p] > 0; band = low[p] .. max(open[p], close[p], low[p] + 0.05 atr)"),
    "DISPLACE": ("ORIGIN C[p..t]", "max(high[p..t]) - low[p] >= 2 atr[p], first such t, before the leg ends"),
    "BREAK": ("ORIGIN C[p+1..b], ref = the last EXTREME↑ known at p, priced above low[p]",
              "close[b] > ref.price, first such b <= p + LEG_MAX, no low[k] < low[p] for k <= b"),
    "LEG": ("ORIGIN C[p..end]", "ends at the BREAK, at the first low[k] < low[p] (INVALIDATED), or p + LEG_MAX"),
    "BREACH_REVERT": ("EXTREME↓ then C[t]", "low[t] < price, close[t] >= price, no close < price since it was known"),
    "REVISIT": ("ZONE then C[t]", "low[t] <= near (lifecycle.py)"),
    "REJECT_PATH": ("REVISIT then C[t]", "high[t] >= near + 1 atr, before a FAIL (lifecycle.py)"),
    "ACCEPT": ("REVISIT then C[t-2..t]", "three closes in [far - 0.1 atr, near] (lifecycle.py)"),
    "FAIL": ("ZONE then C[t]", "close[t] < far - 0.1 atr (lifecycle.py)"),
    "EXPIRE": ("ZONE then C[k + 500]", "no terminal event before (lifecycle.py)"),
}


def flip(df: pd.DataFrame) -> pd.DataFrame:
    """The chart upside down: prices negated, highs and lows swapped. flip(flip(df)) == df exactly."""
    return df.assign(open=-df["open"], close=-df["close"], high=-df["low"], low=-df["high"])


def _f(x: float) -> float | None:
    return float(x) if np.isfinite(x) else None


# ---------------------------------------------------------------- level productions, one side

def _force(F: candles.Table, i: int, j: int) -> dict:
    """The derived strength of the tokens i..j: the mean and max of their body_atr."""
    x = F["body_atr"][i:j + 1]
    x = x[np.isfinite(x)]
    return {"strength_mean": float(x.mean()) if len(x) else None,
            "strength_max": float(x.max()) if len(x) else None}


def _first_close_above(c: np.ndarray, piv: list[tuple[int, int, float]]) -> dict[int, list[int]]:
    """For each swing high (known, q, price): the first bar after q whose close is above it - the
    bar that takes it. Grouped by that bar. Only closes up to it are read."""
    out: dict[int, list[int]] = {}
    for _, q, price in piv:
        hit = np.flatnonzero(c[q + 1:] > price)
        if len(hit):
            out.setdefault(q + 1 + int(hit[0]), []).append(q)
    return out


def _side(F: candles.Table, ext: list[Entity], side: int, cid: list[str]) -> list[Entity]:
    """The up-side level events of the token table as it is (side = +1), or of the flipped one
    mapped back (side = -1). `up` is the leg's direction; `dn` the direction of the low it starts
    from. `ext` are the EXTREME words of both sides."""
    o, h, l, c, tr, a = (F[k] for k in ("open", "high", "low", "close", "tr", "atr"))
    n = len(c)
    up, dn = Dir.of(side), Dir.of(-side)
    px = lambda v: float(side * v)  # noqa: E731 - a pass-frame price back in the chart's terms
    band = lambda lo, hi: (px(lo), px(hi)) if side > 0 else (px(hi), px(lo))  # noqa: E731
    toks = lambda i, j: tuple(cid[i:j + 1])  # noqa: E731 - the tokens of bars i..j
    pl = sorted((e.known_at, e.at, side * e.get("price")) for e in ext if e.dir is dn)  # frame swing lows
    ph = sorted((e.known_at, e.at, side * e.get("price")) for e in ext if e.dir is up)  # frame swing highs
    ph_known = [x[0] for x in ph]
    taken = _first_close_above(c, ph)
    out: list[Entity] = []

    # BREACH_REVERT: a swing low traded through and closed back above, before any close below it.
    # Once per extreme; an extreme is spent at its first close beyond.
    for known, p, price in pl:
        s0 = known + 1
        if s0 >= n:
            continue
        beyond = np.flatnonzero(c[s0:] < price)
        stop = s0 + int(beyond[0]) if len(beyond) else n
        wick = np.flatnonzero(l[s0:stop] < price)
        if len(wick):
            t = s0 + int(wick[0])
            out.append(Entity(make_id("BREACH_REVERT", dn, t, f"x{p}"), "BREACH_REVERT", dn, t, t,
                              attrs_of({"extreme": make_id("EXTREME", dn, p), "level": px(price),
                                        "depth_atr": _f((price - l[t]) / a[t]) if a[t] > 0 else None}),
                              parts=toks(t, t)))

    # ORIGIN, LEG, DISPLACE, BREAK: the leg away from each swing low
    for known, p, low in pl:
        A = a[p]
        if not A > 0:
            continue
        oid = make_id("ORIGIN", up, p)
        near = max(o[p], c[p], low + ORIGIN_MIN_HEIGHT * A)  # the body top (zone_events' body bound)
        out.append(Entity(oid, "ORIGIN", up, p, known, attrs_of({
            "extreme": make_id("EXTREME", dn, p), "atr": float(A), "far": px(low), "near": px(near),
            "band": band(low, near)}), parts=(make_id("EXTREME", dn, p),)))
        j = bisect.bisect_right(ph_known, p) - 1  # the last swing high known at the origin
        ref = ph[j] if j >= 0 and ph[j][2] > low else None
        ext, end, reason, disp_at = h[p], -1, "", -1
        if h[p] - low >= DISPLACE_MIN * A:
            disp_at = p
        for k in range(p + 1, min(n, p + LEG_MAX + 1)):
            if l[k] < low:  # traded under the origin: the leg is over, this bar is not part of it
                end, reason = k, "INVALIDATED"
                break
            ext = max(ext, h[k])
            if disp_at < 0 and ext - low >= DISPLACE_MIN * A:
                disp_at = k
            if ref is not None and c[k] > ref[2]:
                end, reason = k, "BREAK"
                break
        else:
            if p + LEG_MAX <= n - 1:
                end, reason = p + LEG_MAX, "TIMEOUT"
        if disp_at >= 0:
            out.append(Entity(make_id("DISPLACE", up, disp_at, f"o{p}"), "DISPLACE", up, disp_at,
                              max(disp_at, known), attrs_of({
                                  "origin": oid, "threshold_atr": DISPLACE_MIN,
                                  "bars": disp_at - p}), parts=toks(p, disp_at)))
        if end < 0:
            continue  # the leg is still open at the last bar: nothing about its end is known yet
        if reason == "BREAK":
            b = end
            steps = float(np.abs(np.diff(c[p:b + 1])).sum())
            base = tr[max(0, p - SURPRISE_LOOKBACK):p]
            mag = (ext - low) / A
            force = Force(magnitude=float(mag), speed=float(mag / (b - p)),
                          efficiency=float((c[b] - c[p]) / steps) if steps > 0 else None,
                          penetration=float((c[b] - ref[2]) / A),
                          surprise=_f(tr[p + 1:b + 1].mean() / base.mean())
                          if p >= SURPRISE_MIN_BARS and base.mean() > 0 else None,
                          duration=int(b - p))
            cleared = [q for q in taken.get(b, []) if q + SWING <= b]  # standing highs this close took
            out.append(Entity(make_id("BREAK", up, b, f"o{p}"), "BREAK", up, b, max(b, known),
                              attrs_of({"origin": oid, "ref": make_id("EXTREME", up, ref[1]),
                                        "level": px(ref[2]),
                                        "ref_age": b - ref[1], "ref_known_age": b - ref[0],
                                        "swings_taken": len(cleared),
                                        "max_ref_age": b - min(cleared) if cleared else None,
                                        "leg_bars": b - p, **_force(F, p, b)}),
                              force=force, parts=toks(p, b)))
        last = end - 1 if reason == "INVALIDATED" else end
        out.append(Entity(make_id("LEG", up, p), "LEG", up, p, max(end, known), attrs_of({
            "origin": oid, "end": end, "reason": reason,
            "ref": make_id("EXTREME", up, ref[1]) if ref is not None else None,
            "extreme_px": px(h[p:last + 1].max()),
            "displacement_atr": float((h[p:last + 1].max() - low) / A)})))
    return out


def relations(entities: list[Entity]) -> list[Relation]:
    """The materialised relations. BEFORE and AFTER are computed on demand (`core.before`)."""
    ids = {e.id: e for e in entities}
    voids = {d: sorted((e.at, e.id) for e in entities if e.type == "VOID" and e.dir is d) for d in Dir}
    out = []

    def rel(kind: str, s: Entity, d: str) -> None:
        if d in ids:
            out.append(Relation(kind, s.id, d, max(s.known_at, ids[d].known_at)))

    for e in entities:
        if e.type == "BREAK":
            rel("CROSS", e, e.get("ref"))  # its close crossed the reference extreme
        elif e.type == "BREACH_REVERT":
            rel("TOUCH", e, e.get("extreme"))  # traded through it, closed back
        elif e.type == "REVISIT":
            rel("TOUCH", e, e.get("zone"))
        elif e.type == "FAIL":
            rel("INVALIDATE", e, e.get("zone"))
        elif e.type == "ZONE":
            for part in e.parts:
                rel("CONTAIN", e, part)
        elif e.type == "LEG":
            vs = voids[e.dir]
            lo = bisect.bisect_left(vs, (e.at + 2, ""))
            for at, vid in vs[lo:]:
                if at > e.get("end"):
                    break
                if e.get("reason") == "INVALIDATED" and at >= e.get("end"):
                    break
                rel("CONTAIN", e, vid)
    return out


def parse(df: pd.DataFrame) -> Chart:
    """Bars (open, high, low, close[, volume]) to a Chart. The index is ignored: bars are 0..n-1."""
    from mcfl.grammar import CANDLE_RULES, RULES, frames, words
    from mcfl.grammar import apply as grammar
    from mcfl.lifecycle import run as lifecycle

    df = df.reset_index(drop=True)
    T = candles.table(df)
    cid, rid = candles.ids(T)
    toks = candles.entities(T)
    fr = frames(T)
    wds = words(T, cid, rid, fr=fr)
    ext = [e for e in wds if e.type == "EXTREME"]
    level = [e for side in (1, -1) for e in _side(fr[side], ext, side, cid)]
    zones, failures, pending = grammar([e for e in wds if e.type in ("EXTREME", "VOID")] + level, RULES)
    life, transitions, states = lifecycle(T, zones, failures, cid, [e for e in wds if e.type == "DELIVERY_SHIFT"])
    rejects, _, _ = grammar([e for e in toks if e.type == "CANDLE"] + zones + life, CANDLE_RULES, n=len(df))
    ents = sorted(toks + wds + level + zones + life + rejects, key=sort_key)
    rels = sorted(relations(ents), key=lambda r: (r.known_at, r.kind, r.src, r.dst))
    return Chart(n=len(df), entities=tuple(ents), relations=tuple(rels),
                 failures=tuple(sorted(failures, key=lambda f: (f.known_at, f.candidate))),
                 transitions=tuple(sorted(transitions, key=lambda t: (t.known_at, t.zone, t.at))),
                 states=tuple(sorted(states.items())), pending=tuple(sorted(pending)))
