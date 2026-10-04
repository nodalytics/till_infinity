"""v2 items 1 and 11: swing-structure labels, the STRUCTURE state, STRUCTURE_SHIFT, the BREAK's
`vs_structure` and CHARACTER_SHIFT (the trader's CHoCH).

Labels. Each EXTREME after the first of its kind is labelled against the previous EXTREME of its
kind (by bar), with tol = SWING_EQ_ATR x ATR at the later swing:

    highs   HH  price > prev + tol      EH  within tol      LH  price < prev - tol
    lows    LL  price < prev - tol      EL  within tol      HL  price > prev + tol

A label is a SWING event (L2): at and known_at are the EXTREME's (a 3/3 swing, known 3 bars
later), parts the two EXTREMEs. Under the flip a high becomes a low and HH becomes LL, LH HL, EH EL.

The STRUCTURE state (L4) is read from the last high label and the last low label known:

    UP     last high HH and last low HL
    DOWN   last high LH and last low LL
    MIXED  anything else, and before both kinds have a label (EH / EL are not HH / HL: MIXED)

Labels known on the same bar are applied together, then the state is read once (a bar can be a
swing high and a swing low at once; applying them one at a time would make the order, and so the
flip, matter). A STRUCTURE_SHIFT is emitted when the state changes: at the latest labelled bar of
the group, known_at the labels' known_at, `from` and `to` the states, `run` the number of labels
since the previous shift, and direction UP when the state rose in the order DOWN < MIXED < UP,
DOWN when it fell. `state_series` gives the state known at every bar; `structure_at` reads it from a
parsed chart.

vs_structure. Every BREAK reads the state known at its own bar b (labels with known_at <= b): WITH
when the state is the break's direction (UP and a BREAK up: the trader's BOS), AGAINST when it is
the other, NONE when MIXED.

CHARACTER_SHIFT (CHoCH). The state is ESTABLISHED once ESTABLISH_LABELS (2) consecutive labels have
held it - the label that set it counts. A CHARACTER_SHIFT is the first AGAINST BREAK while an
established UP or DOWN state holds, once per run of that state (a run ends at the next
STRUCTURE_SHIFT). Breaks are taken in the order they become known (known_at, then bar, then the
earliest origin), so a prefix sees the same first one; one per bar. Its direction is the break's,
its known_at the break's, its parts the BREAK.
"""
from __future__ import annotations

import numpy as np

from mcfl.core import SIDES, Dir, Entity, attrs_of, make_id

SWING_EQ_ATR = 0.1
"""Two swings of a kind are EQUAL (EH, EL) within this many ATR(14) at the later one."""
ESTABLISH_LABELS = 2
"""Consecutive labels holding a state before it is ESTABLISHED (CHoCH needs an established state)."""
STATES = ("DOWN", "MIXED", "UP")
_RANK = {s: i for i, s in enumerate(STATES)}


def labels(ext: list[Entity], atr: np.ndarray) -> list[Entity]:
    """SWING events: every EXTREME after the first of its kind, labelled against the previous one."""
    out = []
    for d in SIDES:
        xs = sorted((e for e in ext if e.dir is d), key=lambda e: e.at)
        s = 1.0 if d is Dir.UP else -1.0
        for prev, e in zip(xs, xs[1:]):
            a = atr[e.at]
            tol = SWING_EQ_ATR * a if a > 0 else 0.0
            diff = s * (e.get("price") - prev.get("price"))  # > 0: further out (higher high, lower low)
            more, eq, less = ("HH", "EH", "LH") if d is Dir.UP else ("LL", "EL", "HL")
            lab = more if diff > tol else less if diff < -tol else eq
            out.append(Entity(make_id("SWING", d, e.at), "SWING", d, e.at, e.known_at, attrs_of({
                "label": lab, "price": e.get("price"), "prev": prev.id,
                "diff_atr": float(diff / a) if a > 0 else None, "bars": e.at - prev.at}),
                parts=(prev.id, e.id)))
    return out


def _state(hi: str | None, lo: str | None) -> str:
    if hi == "HH" and lo == "HL":
        return "UP"
    if hi == "LH" and lo == "LL":
        return "DOWN"
    return "MIXED"


def shifts(swings: list[Entity], n: int) -> tuple[list[Entity], np.ndarray, np.ndarray, np.ndarray]:
    """STRUCTURE_SHIFT events, and per bar: the state known at that bar, the number of labels the
    current run has had, and the run's id (the bar of the shift that began it; -1 before any)."""
    groups: dict[int, list[Entity]] = {}
    for e in swings:
        groups.setdefault(e.known_at, []).append(e)
    state, hi, lo, run, run_id = "MIXED", None, None, 0, -1
    out = []
    st = np.empty(n, object)
    cnt = np.zeros(n, int)
    rid = np.full(n, -1)
    changes: list[tuple[int, str, int, int]] = []  # (bar known, state, run count, run id)
    for k in sorted(groups):
        g = sorted(groups[k], key=lambda e: (e.at, e.dir.value))
        for e in g:
            if e.dir is Dir.UP:
                hi = e.get("label")
            else:
                lo = e.get("label")
        new = _state(hi, lo)
        if new != state:
            at = max(e.at for e in g)
            d = Dir.UP if _RANK[new] > _RANK[state] else Dir.DOWN
            out.append(Entity(make_id("STRUCTURE_SHIFT", d, k), "STRUCTURE_SHIFT", d, at, k, attrs_of({
                "from": state, "to": new, "run": run}),
                parts=tuple(e.id for e in sorted(g, key=lambda e: (e.at, e.id)))))
            state, run, run_id = new, len(g), k
        else:
            run += len(g)
        changes.append((k, state, run, run_id))
    j, cur = 0, ("MIXED", 0, -1)
    for t in range(n):
        while j < len(changes) and changes[j][0] <= t:
            cur = changes[j][1:]
            j += 1
        st[t], cnt[t], rid[t] = cur
    return out, st, cnt, rid


def vs(brk: Entity, state: str) -> str:
    if state == "MIXED":
        return "NONE"
    return "WITH" if state == brk.dir.value else "AGAINST"


def annotate_breaks(level: list[Entity], st: np.ndarray) -> list[Entity]:
    """Every BREAK with `vs_structure` (and the `structure` state it read) at its bar."""
    out = []
    for e in level:
        if e.type == "BREAK":
            s = st[e.at]
            e = Entity(e.id, e.type, e.dir, e.at, e.known_at,
                       attrs_of({**dict(e.attrs), "structure": s, "vs_structure": vs(e, s)}), e.force, e.parts)
        out.append(e)
    return out


def character_shifts(breaks: list[Entity], st: np.ndarray, cnt: np.ndarray, rid: np.ndarray) -> list[Entity]:
    """The first AGAINST BREAK in each established run of an UP or DOWN state."""
    def origin_at(e: Entity) -> int:
        return int(e.get("origin").split(".")[2])
    fired: set[int] = set()
    bars: set[int] = set()
    out = []
    for e in sorted(breaks, key=lambda e: (e.known_at, e.at, origin_at(e), e.id)):
        b = e.at
        if e.get("vs_structure") != "AGAINST" or cnt[b] < ESTABLISH_LABELS or rid[b] in fired or b in bars:
            continue
        fired.add(int(rid[b]))
        bars.add(b)
        out.append(Entity(make_id("CHARACTER_SHIFT", e.dir, b), "CHARACTER_SHIFT", e.dir, b, e.known_at,
                          attrs_of({"break": e.id, "structure": st[b], "run": int(cnt[b]),
                                    "level": e.get("level")}), parts=(e.id,)))
    return out


def structure_at(chart, t: int) -> str:
    """The STRUCTURE state known at bar t of a parsed chart."""
    s = "MIXED"
    for e in sorted(chart.of("STRUCTURE_SHIFT"), key=lambda e: e.known_at):
        if e.known_at > t:
            break
        s = e.get("to")
    return s
