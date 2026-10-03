"""OHLC bars to MCFL entities: L1 facts, L2 events, the ORIGIN and LEG structures, then the grammar
(ZONE), the lifecycle and the materialised relations.

Every directional rule is written once, for the up side, and run twice: on the chart and on the
chart upside down (`flip`), the way `research/ideas/zones.py` does it. Down events are the up
events of the flipped chart with their prices negated back. Symmetry is then a property of the
construction, and `tests/test_symmetry.py` checks the plumbing that maps it back.

Causality: a bar's close is known at that bar. A 3/3 swing at p is known at p + 3. An entity's
`known_at` is the latest bar any of its inputs needed; nothing reads a later one.
"""
from __future__ import annotations

import bisect
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ideas"))
import prims as P

from mcfl.core import Chart, Dir, Entity, Force, Relation, attrs_of, make_id, sort_key

ATR_N = 14
"""Wilder ATR length; every threshold below is in units of it (`prims.atr`)."""
SWING = 3
"""Bars left and right of an EXTREME (a 3/3 pivot), as in `zone_events.py`. Known SWING bars later."""
LEG_MAX = 20
"""Bars a LEG may run from its origin before it times out (zone_events' MAXLEG)."""
DISPLACE_MIN = 2.0
"""ATR the leg must travel from the origin extreme for a DISPLACE (zone_events' DISP_MIN)."""
ORIGIN_MIN_HEIGHT = 0.05
"""An ORIGIN band is at least this many ATR tall (zone_events widens thin bands the same way)."""
SURPRISE_LOOKBACK = 20
"""Bars before the origin whose mean true range is the base of a BREAK's surprise."""
SURPRISE_MIN_BARS = 5
"""Fewer bars than this before the origin and surprise is undefined (None)."""


# ---------------------------------------------------------------- L1: geometric facts, not entities

def flip(df: pd.DataFrame) -> pd.DataFrame:
    """The chart upside down: prices negated, highs and lows swapped. flip(flip(df)) == df exactly."""
    return df.assign(open=-df["open"], close=-df["close"], high=-df["low"], low=-df["high"])


def true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    pc = np.r_[c[0], c[:-1]]
    return np.maximum(h, pc) - np.minimum(l, pc)


def gap_up(h: np.ndarray, l: np.ndarray, k: int) -> float:
    """The three-bar gap at k: bar k's low above bar k-2's high (positive) or not."""
    return float(l[k] - h[k - 2])


def _f(x: float) -> float | None:
    return float(x) if np.isfinite(x) else None


# ---------------------------------------------------------------- L2 and the L3 it needs, one side

def _side(df: pd.DataFrame, a: np.ndarray, side: int) -> list[Entity]:
    """The up-side entities of `df` as it is given (side = +1), or of the flipped chart mapped
    back (side = -1). `up` is the leg's direction; `dn` the direction of the low it starts from."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    up, dn = Dir.of(side), Dir.of(-side)
    px = lambda v: float(side * v)  # noqa: E731 - a pass-frame price back in the chart's terms
    band = lambda lo, hi: (px(lo), px(hi)) if side > 0 else (px(hi), px(lo))  # noqa: E731
    tr = true_range(h, l, c)
    ph, pl = P.pivots(h, l, SWING, SWING)
    ph_known = [x[0] for x in ph]
    out: list[Entity] = []

    # EXTREME: the pass frame's swing lows (the other pass makes the highs)
    for known, p, price in pl:
        out.append(Entity(make_id("EXTREME", dn, p), "EXTREME", dn, p, known,
                          attrs_of({"price": px(price), "swing": SWING})))

    # VOID: every three-bar gap in the leg's direction; the grammar decides which are big enough
    for k in range(2, n):
        g = gap_up(h, l, k)
        if g > 0:
            out.append(Entity(make_id("VOID", up, k), "VOID", up, k, k, attrs_of({
                "band": band(h[k - 2], l[k]), "size": float(g),
                "size_atr": _f(g / a[k]) if a[k] > 0 else None})))

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
                                        "depth_atr": _f((price - l[t]) / a[t]) if a[t] > 0 else None})))

    # ORIGIN, LEG, DISPLACE, BREAK: the leg away from each swing low
    for known, p, low in pl:
        A = a[p]
        if not A > 0:
            continue
        oid = make_id("ORIGIN", up, p)
        near = max(o[p], c[p], low + ORIGIN_MIN_HEIGHT * A)  # the body top (zone_events' body bound)
        out.append(Entity(oid, "ORIGIN", up, p, known, attrs_of({
            "extreme": make_id("EXTREME", dn, p), "atr": float(A), "far": px(low), "near": px(near),
            "band": band(low, near)})))
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
                                  "bars": disp_at - p})))
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
            out.append(Entity(make_id("BREAK", up, b, f"o{p}"), "BREAK", up, b, max(b, known),
                              attrs_of({"origin": oid, "ref": make_id("EXTREME", up, ref[1]),
                                        "level": px(ref[2])}), force=force))
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
    from mcfl.grammar import apply as grammar
    from mcfl.lifecycle import run as lifecycle

    df = df.reset_index(drop=True)
    a = P.atr(df, ATR_N)
    ents = _side(df, a, 1) + _side(flip(df), a, -1)
    zones, failures, pending = grammar(ents)
    life, transitions, states = lifecycle(df, zones, failures)
    ents = sorted(ents + zones + life, key=sort_key)
    rels = sorted(relations(ents), key=lambda r: (r.known_at, r.kind, r.src, r.dst))
    return Chart(n=len(df), entities=tuple(ents), relations=tuple(rels),
                 failures=tuple(sorted(failures, key=lambda f: (f.known_at, f.candidate))),
                 transitions=tuple(sorted(transitions, key=lambda t: (t.known_at, t.zone, t.at))),
                 states=tuple(sorted(states.items())), pending=tuple(sorted(pending)))
