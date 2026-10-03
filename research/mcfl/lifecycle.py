"""A ZONE's lifecycle as a state machine whose transitions are events.

    FORMING --ZONE--> QUALIFIED --REVISIT--> REVISITED(k) --REJECT_PATH--> REJECTED(k) --REVISIT--> ...
    FORMING --grammar failure--> DISQUALIFIED
    REVISITED(k) --DELIVERY_SHIFT--> CONFIRMED(k) --REJECT_PATH--> REJECTED(k) ...
    REVISITED(k), CONFIRMED(k) --ACCEPT--> ACCEPTED        (terminal)
    any live state --FAIL--> FAILED          (terminal)
    any live state --EXPIRE--> EXPIRED       (terminal, ZONE_EXPIRE bars after qualifying)

For an up zone (down is the flipped chart), with A the origin's ATR, `near` the band's top and
`far` its bottom:

    REVISIT  a bar's low reaches `near` while the zone is QUALIFIED or REJECTED (not on the bar it
             was rejected - a bar cannot say which of its high and low came first)
    REJECT_PATH  after a revisit, a later bar's high reaches near + REJECT_MOVE * A before a FAIL
             (v0's REJECT, renamed in v1: REJECT is now the candle word in grammar.CANDLE_RULES,
             an observation that does not move the state machine)
    ACCEPT   after a revisit, ACCEPT_BARS consecutive closes inside [far - FAIL_BUF * A, near]
    FAIL     a close below far - FAIL_BUF * A (zone_events' death; it implies a revisit that bar)
    CONFIRM  a DELIVERY_SHIFT (CISD) in the zone's direction within the revisit's reaction window
             (the revisit bar and the next REACTION_BARS - 1): REVISITED -> CONFIRMED. The shift is
             an existing L2 event; the transition records it, no new entity is made. CONFIRMED
             behaves as REVISITED for everything else (REJECT_PATH, ACCEPT, FAIL, EXPIRE)
    EXPIRE   none of the terminal events within ZONE_EXPIRE bars of qualifying

Within one bar the order is CONFIRM (of an earlier revisit), REJECT_PATH (a high), REVISIT (a
low), then the close-based FAIL, CONFIRM (of a revisit on this bar) and ACCEPT. CONFIRM comes before
REJECT_PATH because a shift bar usually travels the 1 ATR too; both transitions are then recorded,
REVISITED -> CONFIRMED -> REJECTED, at that bar's close. Every event is known at its own bar's close, and is a production over that bar's CANDLE
token with a condition on its prices; `parts` is that token.
"""
from __future__ import annotations

import numpy as np

from mcfl.candles import Table
from mcfl.core import Dir, Entity, Failure, Transition, attrs_of, make_id

REJECT_MOVE = 1.0
"""ATR price must travel back the zone's way from `near` after a revisit for a REJECT_PATH."""
ACCEPT_BARS = 3
"""Consecutive closes inside the band (FAIL_BUF-padded) after a revisit for an ACCEPT."""
FAIL_BUF = 0.1
"""ATR past the far edge a close must reach to FAIL the zone (zone_events' BUF)."""
ZONE_EXPIRE = 500
"""Bars after qualifying with no terminal event before the zone EXPIREs (zone_events' EXPIRE)."""

REACTION_BARS = 3
"""The revisit bar and the bars after it in which a DELIVERY_SHIFT confirms (grammar.REACTION_BARS)."""

LIVE = ("QUALIFIED", "REVISITED", "CONFIRMED", "REJECTED")
TERMINAL = ("ACCEPTED", "FAILED", "EXPIRED")


def run(T: Table, zones: list[Entity], failures: list[Failure], cid: list[str],
        shifts: list[Entity] = ()) -> tuple[list[Entity], list[Transition], dict[str, str]]:
    """Every zone's lifecycle events, the transitions they cause, and each zone's state at the end."""
    events: list[Entity] = []
    trans: list[Transition] = []
    states: dict[str, str] = {}
    for f in failures:
        trans.append(Transition(f.candidate, "FORMING", "DISQUALIFIED", int(f.candidate.split(".")[2]),
                                f.known_at, f.candidate))
    hi, lo, cl = (T[k] for k in ("high", "low", "close"))  # the tokens' lexemes
    arrays = {Dir.UP: (hi, lo, cl), Dir.DOWN: (-lo, -hi, -cl)}  # a down zone is an up zone flipped
    for z in zones:
        ev, tr, st = _one(z, *arrays[z.dir], cid, {e.at: e.id for e in shifts if e.dir is z.dir})
        events += ev
        trans += tr
        states[z.id] = st
    return events, trans, states


def _one(z: Entity, h: np.ndarray, l: np.ndarray, c: np.ndarray, cid: list[str],
         shift: dict[int, str]) -> tuple[list[Entity], list[Transition], str]:
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
                   attrs_of({"zone": z.id, **attrs}), parts=(cid[t],))
        ev.append(e)
        tr.append(Transition(z.id, state, new, t, t, e.id))
        state = new

    def confirm(t: int) -> None:
        nonlocal state
        tr.append(Transition(z.id, state, "CONFIRMED", t, t, shift[t]))
        state = "CONFIRMED"

    for t in range(k0 + 1, min(n, k0 + ZONE_EXPIRE + 1)):
        if state == "REVISITED" and rev_bar < t < rev_bar + REACTION_BARS and t in shift:
            confirm(t)  # before REJECT_PATH: a shift bar that also travels 1 ATR is recorded as both
        if state in ("REVISITED", "CONFIRMED") and t > rev_bar and h[t] >= near + REJECT_MOVE * A:
            emit("REJECT_PATH", t, "REJECTED", count=count)
            rej_bar = t
        if state in ("QUALIFIED", "REJECTED") and t > rej_bar and l[t] <= near:
            count += 1
            emit("REVISIT", t, "REVISITED", count=count,
                 depth_atr=float((near - l[t]) / A))
            rev_bar, inside = t, 0
        if c[t] < far - FAIL_BUF * A:
            emit("FAIL", t, "FAILED", count=count)
            break
        if state == "REVISITED" and t == rev_bar and t in shift:
            confirm(t)  # a shift on the revisit bar itself
        if state in ("REVISITED", "CONFIRMED"):
            inside = inside + 1 if far - FAIL_BUF * A <= c[t] <= near else 0
            if inside >= ACCEPT_BARS:
                emit("ACCEPT", t, "ACCEPTED", count=count)
                break
    if state in LIVE and k0 + ZONE_EXPIRE <= n - 1:
        emit("EXPIRE", k0 + ZONE_EXPIRE, "EXPIRED", count=count)
    return ev, tr, state
