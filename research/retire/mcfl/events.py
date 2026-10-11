"""MCFL events over closed bars: the productions the alerts are built from.

Ported from `research/mcfl/` - `grammar.py` (DISPLACE_C, EXTREME, VOID,
DELIVERY_SHIFT), `parse.py` (BREACH_REVERT, ORIGIN, LEG, DISPLACE, BREAK),
`structure.py` (swing labels, STRUCTURE_SHIFT), `pools.py` (SWEEP_PROTECTED),
`lifecycle.py` (a zone's REVISIT and FAIL), `voids.py` (VOID_INVERTED) and
`sweeps.py` (CLOSE_REVERT, SWEEP_SHIFT, INDUCEMENT, BREAKER_RETEST, RECLAIM,
PROTECTED, PROTECTED_TAKEN). Each one is the research definition, written the
way the research writes it - for the up side, then run on the flipped chart -
and `tests/test_mcfl_parity.py` holds them to the research parser event for
event.

## Direction

`dir` is +1 or -1 and **follows the research label, which is not always the
trade's side.** DISPLACE_C, DELIVERY_SHIFT, STRUCTURE_SHIFT and SWEEP_SHIFT
are labelled by the move: +1 is bullish. BREACH_REVERT and CLOSE_REVERT are
labelled by the swept swing: -1 is a swing *low* traded through and closed
back, the bullish one. `turn_trade.ups` read that the wrong way round until
2026-10-04 (see `turning-points.md`), so `Event.bullish` exists to say which
side an event is for without anybody re-deriving it.

## Causality

Every event has `known_at`: the last bar any of its inputs needed. A 3/3 swing
is known three bars after it. An alert fires only on events whose `known_at` is
the newest closed bar, so nothing here may read a bar after `known_at` - and
the research parser guarantees the same, which the parity tests check on every
prefix of a fixture.

## CHoCH is deliberately absent

`structure.py` also defines CHARACTER_SHIFT. The desk does not alert on it, at
any timeframe or as an opt-in, so it is not ported: a detector nothing may
publish is a detector somebody will wire up.
"""

from __future__ import annotations

import bisect
import itertools
from dataclasses import dataclass, field

import numpy as np

from .tokens import Bars, Tokens

#: Bars left and right of an EXTREME (a 3/3 pivot), known SWING bars later.
SWING = 3
#: Bars a LEG may run from its origin before it times out.
LEG_MAX = 20
#: ATR the leg must travel from the origin extreme for a DISPLACE.
DISPLACE_MIN = 2.0
#: An ORIGIN band is at least this many ATR tall.
ORIGIN_MIN_HEIGHT = 0.05
#: Bars from the delivery run's last token to the shift, at most (the desk's CISD).
SHIFT_LAG = 3
#: Two swings of a kind are equal within this many ATR at the later one.
SWING_EQ_ATR = 0.1
#: The swept low is the last swing low of this many bars before the sweep (dax_smc).
SWEEP_BACK = 40
#: The close back above the swept low, on the sweep bar or the next.
SWEEP_CLOSE = 2
#: Bars after the first close beyond a swing within which a close back is a CLOSE_REVERT.
TURTLE_N = 3
#: Bars after a sweep within which a shift the other way makes a SWEEP_SHIFT.
SHIFT_K = 3
#: Bars before a zone's first revisit within which a swing taken is an INDUCEMENT.
INDUCE_N = 10
#: Bars after a structure broke within which its first return is a retest or reclaim.
BREAKER_MAX = 100
#: Smallest VOID on a zone's path, in the origin's ATR.
VOID_MIN = 0.1
#: The first bar of the leg a gap may belong to.
VOID_PATH_START = 2
#: ATR price must travel back from `near` after a revisit for a REJECT_PATH.
REJECT_MOVE = 1.0
#: Consecutive closes inside the band after a revisit for an ACCEPT.
ACCEPT_BARS = 3
#: ATR past the far edge a close must reach to FAIL a zone.
FAIL_BUF = 0.1
#: Bars after qualifying before a zone with no terminal event expires.
ZONE_EXPIRE = 500

#: Event kinds whose `dir` is the swept swing's side rather than the move's.
SWEPT_SIDE = frozenset({"BREACH_REVERT", "CLOSE_REVERT"})


@dataclass(frozen=True, slots=True)
class Event:
    """One production, at bar `at`, known at the close of bar `known_at`."""

    kind: str
    dir: int
    at: int
    known_at: int
    attrs: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def bullish(self) -> bool:
        """Whether this event is evidence for the up side."""
        return self.dir < 0 if self.kind in SWEPT_SIDE else self.dir > 0

    def get(self, key: str, default=None):
        return self.attrs.get(key, default)


# ------------------------------------------------------------------ L2 words


def _qualifies(f: Tokens) -> np.ndarray:
    """A bar of DISPLACE_C's run: bullish, strong body, closed in the top quarter."""
    return (f.dir == "BULL") & np.isin(f.force, ("STRONG", "DOMINANT")) & (f.close_q == "Q4")


def displace_c(fr: dict[int, Tokens]) -> list[Event]:
    """DISPLACE_C, both sides: two strong bullish closes in a row (at the second,
    once per run), or one extremely large dominant bar closed at its high."""
    out = []
    for side in (1, -1):
        f = fr[side]
        n = len(f.dir)
        q = _qualifies(f)
        run = np.zeros(n, bool)
        if n >= 2:
            run[1:] = q[1:] & q[:-1]
            run[2:] &= ~q[:-2]
        single = (
            (f.dir == "BULL")
            & (f.size == "EXTREMELY_LARGE")
            & (f.force == "DOMINANT")
            & (f.close_q == "Q4")
        )
        out.extend(
            Event("DISPLACE_C", side, t, t, {"rule": "RUN" if run[t] else "BAR"})
            for t in map(int, np.flatnonzero(run | single))
        )
    return out


def delivery_shifts(fr: dict[int, Tokens]) -> list[Event]:
    """DELIVERY_SHIFT (CISD), both sides: a bullish bar closing above the open of
    the first bar of the last bearish run, which ended at most SHIFT_LAG bars before."""
    out = []
    for side in (1, -1):
        f = fr[side]
        o, c = f.bars.open, f.bars.close
        bear = f.dir == "BEAR"
        for j in map(int, np.flatnonzero(f.dir == "BULL")):
            m = j - 1
            while m >= 0 and not bear[m] and j - m <= SHIFT_LAG:
                m -= 1
            if m < 0 or j - m > SHIFT_LAG or not bear[m]:
                continue
            k = m
            while k - 1 >= 0 and bear[k - 1]:
                k -= 1
            if not c[j] > o[k]:
                continue
            out.append(Event("DELIVERY_SHIFT", side, j, j, {"run_start": k, "run_len": m - k + 1}))
    return out


def extremes(fr: dict[int, Tokens]) -> list[Event]:
    """EXTREME, both sides: a 3/3 swing high (+1) or low (-1), known 3 bars later.
    `price` is in chart terms."""
    out = []
    for side in (1, -1):
        h = fr[side].bars.high
        n = len(h)
        if n < 2 * SWING + 1:
            continue
        mid = h[SWING : n - SWING]
        ok = np.ones(len(mid), bool)
        for k in range(1, SWING + 1):
            ok &= h[SWING - k : n - SWING - k] < mid  # strictly above the bars before
            ok &= h[SWING + k : n - SWING + k] <= mid  # at or above the bars after
        out.extend(
            Event("EXTREME", side, t, t + SWING, {"price": float(side * h[t])})
            for t in map(int, np.flatnonzero(ok) + SWING)
        )
    return out


def voids(fr: dict[int, Tokens]) -> list[Event]:
    """VOID, both sides: a gap between bar t-2's high and bar t's low."""
    out = []
    for side in (1, -1):
        f = fr[side]
        h, low, a = f.bars.high, f.bars.low, f.atr
        for t in range(2, len(h)):
            if low[t] > h[t - 2]:
                size = float(low[t] - h[t - 2])
                out.append(
                    Event(
                        "VOID",
                        side,
                        t,
                        t,
                        {"size": size, "size_atr": size / a[t] if a[t] > 0 else None},
                    )
                )
    return out


def _swings(ext: list[Event], d: int, side: int) -> list[tuple[int, int, float]]:
    """(known_at, at, frame price) of the EXTREMEs of direction `d`, sorted."""
    return sorted((e.known_at, e.at, side * e.get("price")) for e in ext if e.dir == d)


def breach_reverts(fr: dict[int, Tokens], ext: list[Event]) -> list[Event]:
    """BREACH_REVERT, both sides: a swing traded through and closed back, before
    any close beyond it. Labelled by the swept swing (-1: a low, the bullish one)."""
    out = []
    for side in (1, -1):
        b = fr[side].bars
        low, c = b.low, b.close
        n = len(c)
        for known, p, price in _swings(ext, -side, side):
            s0 = known + 1
            if s0 >= n:
                continue
            beyond = np.flatnonzero(c[s0:] < price)
            stop = s0 + int(beyond[0]) if len(beyond) else n
            wick = np.flatnonzero(low[s0:stop] < price)
            if len(wick):
                t = s0 + int(wick[0])
                out.append(
                    Event("BREACH_REVERT", -side, t, t, {"extreme": p, "level": side * price})
                )
    return out


# ------------------------------------------------------------- legs and breaks


@dataclass(slots=True)
class Legs:
    """The level events of one parse: ORIGIN, DISPLACE, BREAK and LEG."""

    origins: list[Event] = field(default_factory=list)
    displaces: list[Event] = field(default_factory=list)
    breaks: list[Event] = field(default_factory=list)
    legs: list[Event] = field(default_factory=list)


def _leg(
    f: Tokens, p: int, low_p: float, ref: tuple[int, int, float] | None
) -> tuple[int, str, int, float]:
    """Walk one leg from origin p: (end, reason, displace bar, highest high)."""
    h, low, c, a = f.bars.high, f.bars.low, f.bars.close, f.atr
    n = len(c)
    top, end, reason, disp_at = h[p], -1, "", -1
    if h[p] - low_p >= DISPLACE_MIN * a[p]:
        disp_at = p
    for k in range(p + 1, min(n, p + LEG_MAX + 1)):
        if low[k] < low_p:
            return k, "INVALIDATED", disp_at, top
        top = max(top, h[k])
        if disp_at < 0 and top - low_p >= DISPLACE_MIN * a[p]:
            disp_at = k
        if ref is not None and c[k] > ref[2]:
            return k, "BREAK", disp_at, top
    if p + LEG_MAX <= n - 1:
        end, reason = p + LEG_MAX, "TIMEOUT"
    return end, reason, disp_at, top


def legs(fr: dict[int, Tokens], ext: list[Event]) -> Legs:
    """ORIGIN, DISPLACE, BREAK and LEG from every swing low (+1) and high (-1).

    The BREAK is the leg's close above the last swing high known at the origin;
    the leg ends there, at its first trade under the origin, or after LEG_MAX.
    """
    out = Legs()
    for side in (1, -1):
        f = fr[side]
        a = f.atr
        lows = _swings(ext, -side, side)
        highs = _swings(ext, side, side)
        known_highs = [x[0] for x in highs]
        for known, p, low_p in lows:
            if not a[p] > 0:
                continue
            o, c = f.bars.open[p], f.bars.close[p]
            near = max(o, c, low_p + ORIGIN_MIN_HEIGHT * a[p])
            out.origins.append(
                Event(
                    "ORIGIN",
                    side,
                    p,
                    known,
                    {"far": side * low_p, "near": side * near, "atr": float(a[p])},
                )
            )
            j = bisect.bisect_right(known_highs, p) - 1
            ref = highs[j] if j >= 0 and highs[j][2] > low_p else None
            end, reason, disp_at, _ = _leg(f, p, low_p, ref)
            if disp_at >= 0:
                out.displaces.append(
                    Event("DISPLACE", side, disp_at, max(disp_at, known), {"origin": p})
                )
            if end < 0:
                continue
            if reason == "BREAK" and ref is not None:
                out.breaks.append(
                    Event(
                        "BREAK",
                        side,
                        end,
                        max(end, known),
                        {"origin": p, "ref": ref[1], "level": side * ref[2]},
                    )
                )
            out.legs.append(Event("LEG", side, p, max(end, known), {"end": end, "reason": reason}))
    return out


# ------------------------------------------------------------------ structure


def swing_labels(ext: list[Event], atr: np.ndarray) -> list[Event]:
    """SWING: every EXTREME after the first of its kind, labelled against the
    previous one (HH / EH / LH for highs, LL / EL / HL for lows)."""
    out = []
    for d in (1, -1):
        xs = sorted((e for e in ext if e.dir == d), key=lambda e: e.at)
        for prev, e in itertools.pairwise(xs):
            a = atr[e.at]
            tol = SWING_EQ_ATR * a if a > 0 else 0.0
            diff = d * (e.get("price") - prev.get("price"))
            more, eq, less = ("HH", "EH", "LH") if d > 0 else ("LL", "EL", "HL")
            label = more if diff > tol else less if diff < -tol else eq
            out.append(
                Event("SWING", d, e.at, e.known_at, {"label": label, "price": e.get("price")})
            )
    return out


_RANK = {"DOWN": 0, "MIXED": 1, "UP": 2}


def _state(hi: str | None, lo: str | None) -> str:
    if hi == "HH" and lo == "HL":
        return "UP"
    if hi == "LH" and lo == "LL":
        return "DOWN"
    return "MIXED"


def structure_shifts(labels: list[Event]) -> list[Event]:
    """STRUCTURE_SHIFT: the swing-structure state (UP: last high HH and last low
    HL; DOWN: LH and LL; else MIXED) changed. +1 when it rose, -1 when it fell.

    Labels known on the same bar are applied together before the state is read,
    so a bar that is a swing high and a swing low at once is order-free.
    """
    groups: dict[int, list[Event]] = {}
    for e in labels:
        groups.setdefault(e.known_at, []).append(e)
    state, hi, lo = "MIXED", None, None
    out = []
    for k in sorted(groups):
        group = sorted(groups[k], key=lambda e: (e.at, "UP" if e.dir > 0 else "DOWN"))
        for e in group:
            if e.dir > 0:
                hi = e.get("label")
            else:
                lo = e.get("label")
        new = _state(hi, lo)
        if new != state:
            at = max(e.at for e in group)
            d = 1 if _RANK[new] > _RANK[state] else -1
            # The level the shift is "about": the swing that set the new state.
            swing = next((e for e in group if e.dir == d), group[-1])
            out.append(
                Event(
                    "STRUCTURE_SHIFT",
                    d,
                    at,
                    k,
                    {"from": state, "to": new, "level": swing.get("price"), "swing": swing.at},
                )
            )
            state = new
    return out


# ------------------------------------------------------------- pools and zones


def sweep_protected(fr: dict[int, Tokens], ext: list[Event]) -> list[Event]:
    """SWEEP_PROTECTED, both sides: a swing low that trades under the last swing
    low of the 40 bars before it and closes back above it on that bar or the next."""
    out = []
    for side in (1, -1):
        b = fr[side].bars
        low, c, a = b.low, b.close, fr[side].atr
        pl = sorted(
            ((e.known_at, e.at, side * e.get("price")) for e in ext if e.dir == -side),
            key=lambda x: x[1],
        )
        ats = [x[1] for x in pl]
        for known_s, s, low_s in pl:
            if not a[s] > 0:
                continue
            lo = bisect.bisect_left(ats, s - SWEEP_BACK)
            prior = [x for x in pl[lo : bisect.bisect_left(ats, s)] if x[0] <= s]
            if not prior:
                continue
            _, q, q_px = prior[-1]
            if not (
                low_s < q_px
                and low[q + 1 : s].min(initial=np.inf) >= q_px
                and c[s : s + SWEEP_CLOSE].max() > q_px
            ):
                continue
            out.append(
                Event(
                    "SWEEP_PROTECTED",
                    side,
                    s,
                    max(known_s, s + 1),
                    {"swept": q, "swept_level": side * q_px, "level": side * low_s},
                )
            )
    return out


def zones(lv: Legs, vds: list[Event]) -> list[Event]:
    """ZONE: an ORIGIN whose leg displaced, left a VOID of 0.1 ATR or more, and
    BROKE structure - the canonical `ZONE := ORIGIN DISPLACE VOID+ BREAK` row."""
    disp = {(e.dir, e.get("origin")): e for e in lv.displaces}
    brk = {(e.dir, e.get("origin")): e for e in lv.breaks}
    by_dir: dict[int, list[Event]] = {1: [], -1: []}
    for v in vds:
        by_dir[v.dir].append(v)
    out = []
    for o in lv.origins:
        b, d = brk.get((o.dir, o.at)), disp.get((o.dir, o.at))
        if b is None or d is None or d.at > b.at:
            continue
        floor = o.get("atr") * VOID_MIN
        path = [
            v
            for v in by_dir[o.dir]
            if o.at + VOID_PATH_START <= v.at <= b.at and v.get("size") >= floor
        ]
        if not path:
            continue
        known = max(o.known_at, b.known_at, d.known_at, *(v.known_at for v in path))
        out.append(Event("ZONE", o.dir, o.at, known, dict(o.attrs, break_at=b.at)))
    return out


def _arrays(bars: Bars, d: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """High, low and close in the up frame of a structure of direction d."""
    if d > 0:
        return bars.high, bars.low, bars.close
    return -bars.low, -bars.high, -bars.close


def lifecycle(bars: Bars, zs: list[Event]) -> list[Event]:
    """Each zone's REVISIT (with its count) and FAIL, from the zone state machine.

    REJECT_PATH and ACCEPT are walked as well, because they move the state a
    REVISIT needs and ACCEPT ends a zone before it can FAIL; they are not
    returned, since nothing here alerts on them.
    """
    out = []
    n = len(bars)
    for z in zs:
        h, low, c = _arrays(bars, z.dir)
        a, far, near = z.get("atr"), z.dir * z.get("far"), z.dir * z.get("near")
        state, count, rev_bar, rej_bar, inside = "QUALIFIED", 0, -1, -1, 0
        for t in range(z.known_at + 1, min(n, z.known_at + ZONE_EXPIRE + 1)):
            if state == "REVISITED" and t > rev_bar and h[t] >= near + REJECT_MOVE * a:
                state, rej_bar = "REJECTED", t
            if state in ("QUALIFIED", "REJECTED") and t > rej_bar and low[t] <= near:
                count += 1
                state, rev_bar, inside = "REVISITED", t, 0
                out.append(Event("REVISIT", z.dir, t, t, {"zone": z.at, "count": count}))
            if c[t] < far - FAIL_BUF * a:
                out.append(Event("FAIL", z.dir, t, t, {"zone": z.at, "count": count}))
                break
            if state == "REVISITED":
                inside = inside + 1 if far - FAIL_BUF * a <= c[t] <= near else 0
                if inside >= ACCEPT_BARS:
                    break
    return out


def void_inversions(fr: dict[int, Tokens], vds: list[Event]) -> list[Event]:
    """VOID_INVERTED: the first close beyond a void's far side (the IFVG)."""
    out = []
    for v in vds:
        b = fr[v.dir].bars
        k = v.at
        hit = np.flatnonzero(b.close[k + 1 :] < b.high[k - 2])
        if len(hit):
            t = k + 1 + int(hit[0])
            out.append(Event("VOID_INVERTED", v.dir, t, t, {"void": k}))
    return out


# ------------------------------------------------------------------- sweeps


def close_reverts(fr: dict[int, Tokens], ext: list[Event]) -> list[Event]:
    """CLOSE_REVERT, both sides: a swing's first close beyond, closed back within
    TURTLE_N bars (the turtle soup). Labelled by the swept swing, as BREACH_REVERT."""
    out = []
    for side in (1, -1):
        b = fr[side].bars
        c = b.close
        n = len(c)
        for e in ext:
            if e.dir != -side:
                continue
            level = side * e.get("price")
            s0 = e.known_at + 1
            if s0 >= n:
                continue
            beyond = np.flatnonzero(c[s0:] < level)
            if not len(beyond):
                continue
            u = s0 + int(beyond[0])
            back = np.flatnonzero(c[u + 1 : u + 1 + TURTLE_N] >= level)
            if not len(back):
                continue
            v = u + 1 + int(back[0])
            out.append(
                Event(
                    "CLOSE_REVERT",
                    -side,
                    v,
                    v,
                    {"extreme": e.at, "level": side * level, "through": u},
                )
            )
    return out


def _rid(e: Event) -> str:
    """The research id of a swept-swing event: `BREACH_REVERT.D.57.x50`."""
    return f"{e.kind}.{'U' if e.dir > 0 else 'D'}.{e.at}.x{e.get('extreme')}"


def sweep_shifts(sweeps: list[Event], shifts: list[Event], n: int) -> list[Event]:
    """SWEEP_SHIFT: a sweep (BREACH_REVERT, else CLOSE_REVERT) and, on the same
    bar or within SHIFT_K bars after it, a DISPLACE_C (else a DELIVERY_SHIFT) the
    other way. One per bar and direction; the earliest sweep in the window."""
    found: dict[tuple[int, int], Event] = {}
    for sweep_kind in ("BREACH_REVERT", "CLOSE_REVERT"):
        # Ordered as the research index orders them - by bar, then by id - so
        # two sweeps on one bar bind the same one there and here.
        pool = sorted((e for e in sweeps if e.kind == sweep_kind), key=lambda e: (e.at, _rid(e)))
        for shift_kind in ("DISPLACE_C", "DELIVERY_SHIFT"):
            for x in sorted((e for e in shifts if e.kind == shift_kind), key=lambda e: e.at):
                key = (x.dir, x.at)
                if key in found:
                    continue
                upto = min(x.known_at, n - 1)
                hit = [
                    e
                    for e in pool
                    if x.at - SHIFT_K <= e.at <= x.at and e.known_at <= upto and e.dir == -x.dir
                ]
                if not hit:
                    continue
                s = hit[0]
                found[key] = Event(
                    "SWEEP_SHIFT",
                    x.dir,
                    x.at,
                    max(s.known_at, x.known_at),
                    {
                        "sweep_type": s.kind,
                        "shift_type": x.kind,
                        "level": s.get("level"),
                        "sweep_at": s.at,
                    },
                )
    return sorted(found.values(), key=lambda e: (e.at, e.dir))


def inducements(
    fr: dict[int, Tokens], ext: list[Event], zs: list[Event], life: list[Event]
) -> list[Event]:
    """INDUCEMENT: at a zone's first revisit, the swing beyond its near edge that
    was taken within INDUCE_N bars before (the latest taken, lowest on a tie)."""
    first = {(e.dir, e.get("zone")): e for e in life if e.kind == "REVISIT" and e.get("count") == 1}
    out = []
    for side in (1, -1):
        low = fr[side].bars.low
        n = len(low)
        sl = [e for e in ext if e.dir == -side]
        px = np.array([side * e.get("price") for e in sl], float)
        taken = np.empty(len(sl), int)
        for i, e in enumerate(sl):
            s0 = e.known_at + 1
            hit = np.flatnonzero(low[s0:] < px[i]) if s0 < n else np.array([], int)
            taken[i] = s0 + int(hit[0]) if len(hit) else n
        for z in zs:
            rv = first.get((z.dir, z.at))
            if z.dir != side or rv is None:
                continue
            r = rv.at
            near = side * z.get("near")
            ok = np.flatnonzero((px > near) & (taken >= r - INDUCE_N) & (taken <= r))
            if not len(ok):
                continue
            i = int(ok[np.lexsort((px[ok], -taken[ok]))[0]])
            out.append(
                Event(
                    "INDUCEMENT",
                    side,
                    r,
                    r,
                    {"zone": z.at, "level": side * float(px[i]), "taken_at": int(taken[i])},
                )
            )
    return out


def breakers(
    fr: dict[int, Tokens],
    zs: list[Event],
    life: list[Event],
    vds: list[Event],
    inverted: list[Event],
) -> list[Event]:
    """BREAKER_RETEST and RECLAIM: a broken zone's or void's first return to its
    far edge - closed back under it (a retest) or above it (the break failed)."""
    broke = {("ZONE", e.dir, e.get("zone")): e.at for e in life if e.kind == "FAIL"}
    broke.update({("VOID", e.dir, e.get("void")): e.at for e in inverted})
    out = []
    for s in list(zs) + list(vds):
        f_at = broke.get((s.kind, s.dir, s.at))
        if f_at is None:
            continue
        b = fr[s.dir].bars
        h, c = b.high, b.close
        n = len(c)
        edge = s.dir * s.get("far") if s.kind == "ZONE" else b.high[s.at - 2]
        hit = np.flatnonzero(h[f_at + 1 : min(n, f_at + 1 + BREAKER_MAX)] >= edge)
        if not len(hit):
            continue
        t = f_at + 1 + int(hit[0])
        kind = "RECLAIM" if c[t] > edge else "BREAKER_RETEST"
        out.append(
            Event(
                kind,
                s.dir,
                t,
                t,
                {"of": s.kind, "of_at": s.at, "level": s.dir * float(edge), "broke_at": f_at},
            )
        )
    return out


def protected(fr: dict[int, Tokens], lv: Legs, sweeps_p: list[Event]) -> list[Event]:
    """PROTECTED (WEAK / STRONG / SWEEP_STRONG) and PROTECTED_TAKEN, both sides.

    STRONG: the leg from a swing low broke structure without trading under it;
    SWEEP_STRONG also swept the previous low and displaced by the break; WEAK:
    the leg timed out with the low standing. Taken: the first trade under it.
    """
    brk = {(e.dir, e.get("origin")): e for e in lv.breaks}
    disp = {(e.dir, e.get("origin")): e for e in lv.displaces}
    sp = {(e.dir, e.at): e for e in sweeps_p}
    out = []
    for leg in lv.legs:
        side, p, reason = leg.dir, leg.at, leg.get("reason")
        if reason not in ("BREAK", "TIMEOUT"):
            continue
        b = fr[side].bars
        low, c = b.low, b.close
        low_p = low[p]
        if reason == "BREAK":
            brk_e = brk[(side, p)]
            grade, known = "STRONG", brk_e.known_at
            s, d = sp.get((side, p)), disp.get((side, p))
            if s is not None and d is not None and d.at <= brk_e.at:
                grade, known = "SWEEP_STRONG", max(known, s.known_at, d.known_at)
        else:
            grade, known = "WEAK", leg.known_at
        if low[p + 1 : known + 1].min(initial=np.inf) < low_p:
            continue
        level = float(side * low_p)
        out.append(Event("PROTECTED", side, p, known, {"grade": grade, "level": level}))
        hit = np.flatnonzero(low[known + 1 :] < low_p)
        if len(hit):
            t = known + 1 + int(hit[0])
            out.append(
                Event(
                    "PROTECTED_TAKEN",
                    side,
                    t,
                    t,
                    {"grade": grade, "level": level, "closed_back": bool(c[t] >= low_p), "of": p},
                )
            )
    return out


# ------------------------------------------------------------- the major BOS

#: Bars either side of a major swing (`turning-points.md`'s major turn).
MAJOR_PIVOT = 10
#: ATR price must travel away from a major swing before its break counts.
MAJOR_MOVE_ATR = 3.0


def major_bos(
    fr: dict[int, Tokens], pivot: int = MAJOR_PIVOT, move_atr: float = MAJOR_MOVE_ATR
) -> list[Event]:
    """MAJOR_BOS: a close through a major swing, in the break's direction.

    The "major turn" of `turning-points.md` made causal. A swing high is the
    highest high of `pivot` bars either side (ties allowed, as `ideas/turns.py`
    has it), so it is known `pivot` bars later. Price must then travel at least
    `move_atr` ATR (the swing bar's) away from it - measured from the swing to
    the furthest point *before* the break bar, so all of it is known at the
    break's close. The break is the first close beyond the swing. Down is the
    flipped chart. Where one close takes several such swings, the one with the
    longest leg is kept: one event per bar and direction.
    """
    out = []
    for side in (1, -1):
        f = fr[side]
        h, low, c, a = f.bars.high, f.bars.low, f.bars.close, f.atr
        n = len(c)
        best: dict[int, Event] = {}
        for p in range(pivot, n - pivot):
            if not a[p] > 0 or h[p] < h[p - pivot : p + pivot + 1].max():
                continue
            above = np.flatnonzero(c[p + 1 :] > h[p])
            if not len(above):
                continue
            b = p + 1 + int(above[0])
            if b - 1 < p + 1:
                continue
            k = p + 1 + int(np.argmin(low[p + 1 : b]))
            leg = float((h[p] - low[k]) / a[p])
            if leg < move_atr:
                continue
            e = Event(
                "MAJOR_BOS",
                side,
                b,
                b,
                {
                    "level": float(side * h[p]),
                    "pivot": p,
                    "leg_atr": leg,
                    "leg_end": k,
                    "leg_px": float(side * low[k]),
                },
            )
            if b not in best or leg > best[b].get("leg_atr"):
                best[b] = e
        out += [best[b] for b in sorted(best)]
    return out
