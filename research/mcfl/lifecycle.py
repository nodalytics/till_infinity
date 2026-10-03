"""A ZONE's lifecycle as a state machine whose transitions are events.

    FORMING --ZONE--> QUALIFIED --REVISIT--> REVISITED(k) --REJECT--> REJECTED(k) --REVISIT--> ...
    FORMING --grammar failure--> DISQUALIFIED
    REVISITED(k) --ACCEPT--> ACCEPTED        (terminal)
    any live state --FAIL--> FAILED          (terminal)
    any live state --EXPIRE--> EXPIRED       (terminal, ZONE_EXPIRE bars after qualifying)

For an up zone (down is the flipped chart), with A the origin's ATR, `near` the band's top and
`far` its bottom:

    REVISIT  a bar's low reaches `near` while the zone is QUALIFIED or REJECTED (not on the bar it
             was rejected - a bar cannot say which of its high and low came first)
    REJECT   after a revisit, a later bar's high reaches near + REJECT_MOVE * A before a FAIL
    ACCEPT   after a revisit, ACCEPT_BARS consecutive closes inside [far - FAIL_BUF * A, near]
    FAIL     a close below far - FAIL_BUF * A (zone_events' death; it implies a revisit that bar)
    EXPIRE   none of the terminal events within ZONE_EXPIRE bars of qualifying

Within one bar the order is REJECT (a high), then REVISIT (a low), then the close-based FAIL and
ACCEPT. Every event is known at its own bar's close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mcfl.core import Dir, Entity, Failure, Transition, attrs_of, make_id

REJECT_MOVE = 1.0
"""ATR price must travel back the zone's way from `near` after a revisit for a REJECT."""
ACCEPT_BARS = 3
"""Consecutive closes inside the band (FAIL_BUF-padded) after a revisit for an ACCEPT."""
FAIL_BUF = 0.1
"""ATR past the far edge a close must reach to FAIL the zone (zone_events' BUF)."""
ZONE_EXPIRE = 500
"""Bars after qualifying with no terminal event before the zone EXPIREs (zone_events' EXPIRE)."""

LIVE = ("QUALIFIED", "REVISITED", "REJECTED")
TERMINAL = ("ACCEPTED", "FAILED", "EXPIRED")


def run(df: pd.DataFrame, zones: list[Entity],
        failures: list[Failure]) -> tuple[list[Entity], list[Transition], dict[str, str]]:
    """Every zone's lifecycle events, the transitions they cause, and each zone's state at the end."""
    events: list[Entity] = []
    trans: list[Transition] = []
    states: dict[str, str] = {}
    for f in failures:
        trans.append(Transition(f.candidate, "FORMING", "DISQUALIFIED", int(f.candidate.split(".")[2]),
                                f.known_at, f.candidate))
    hi, lo, cl = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    arrays = {Dir.UP: (hi, lo, cl), Dir.DOWN: (-lo, -hi, -cl)}  # a down zone is an up zone flipped
    for z in zones:
        ev, tr, st = _one(z, *arrays[z.dir])
        events += ev
        trans += tr
        states[z.id] = st
    return events, trans, states


def _one(z: Entity, h: np.ndarray, l: np.ndarray, c: np.ndarray) -> tuple[list[Entity], list[Transition], str]:
    """One zone, in the up-zone frame (`h`, `l`, `c` already flipped for a down zone)."""
    s = 1.0 if z.dir is Dir.UP else -1.0
    A, far, near = z.get("atr"), s * z.get("far"), s * z.get("near")
    n, k0 = len(c), z.known_at
    ev: list[Entity] = []
    tr = [Transition(z.id, "FORMING", "QUALIFIED", z.at, k0, z.id)]
    state, count, rev_bar, rej_bar, inside = "QUALIFIED", 0, -1, -1, 0

    def emit(kind: str, t: int, new: str, **attrs) -> None:
        nonlocal state
        e = Entity(make_id(kind, z.dir, t, f"z{z.at}"), kind, z.dir, t, t,
                   attrs_of({"zone": z.id, **attrs}))
        ev.append(e)
        tr.append(Transition(z.id, state, new, t, t, e.id))
        state = new

    for t in range(k0 + 1, min(n, k0 + ZONE_EXPIRE + 1)):
        if state == "REVISITED" and t > rev_bar and h[t] >= near + REJECT_MOVE * A:
            emit("REJECT", t, "REJECTED", count=count)
            rej_bar = t
        if state in ("QUALIFIED", "REJECTED") and t > rej_bar and l[t] <= near:
            count += 1
            emit("REVISIT", t, "REVISITED", count=count,
                 depth_atr=float((near - l[t]) / A))
            rev_bar, inside = t, 0
        if c[t] < far - FAIL_BUF * A:
            emit("FAIL", t, "FAILED", count=count)
            break
        if state == "REVISITED":
            inside = inside + 1 if far - FAIL_BUF * A <= c[t] <= near else 0
            if inside >= ACCEPT_BARS:
                emit("ACCEPT", t, "ACCEPTED", count=count)
                break
    if state in LIVE and k0 + ZONE_EXPIRE <= n - 1:
        emit("EXPIRE", k0 + ZONE_EXPIRE, "EXPIRED", count=count)
    return ev, tr, state
