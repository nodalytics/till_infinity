"""The sweeps study's entities (`sweeps.py`): CLOSE_REVERT, SWEEP_SHIFT, INDUCEMENT, BREAKER_RETEST and
RECLAIM, PROTECTED and PROTECTED_TAKEN - on hand-built bars, each against a brute-force restatement of
its definition on walks, under the flip, and at their known_at (present there, absent a bar earlier).
The every-prefix test of `test_v2_causality.py` and the flip test of `test_v2_symmetry.py` cover them
too, since they compare every entity of the parse."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import synth
from mcfl.core import SWEEP_TYPES, Dir
from mcfl.parse import LEG_MAX, flip, parse
from mcfl.sweeps import BREAKER_MAX, INDUCE_N, SHIFT_K, TURTLE_N
from test_symmetry import mirror
from test_v2_causality import series

# a swing low at bar 24 (low 97.75), a rally, a fall that closes under it at bar 36 (97.5) and back
# above it at bar 37 (98.5): the close-beyond failure
SOUP = F.WARMUP + F.zig([100.5, 98, 101]) + F.zig([101, 98.5]) + [97.5, 98.5, 99, 99.5, 100]


def test_close_revert_on_hand_built_bars():
    ch = parse(F.bars(SOUP))
    (e,) = ch.of("CLOSE_REVERT")
    assert (e.id, e.known_at, e.get("through"), e.get("bars"), e.get("level")) == ("CLOSE_REVERT.D.37.x24", 37, 36, 1, 97.75)
    assert e.get("depth_atr") > 0 and e.parts == ("CANDLE.D.36", "CANDLE.U.37")
    assert not ch.of("BREACH_REVERT")  # the first bar under it closed under it: no wick-only breach
    # no close back within TURTLE_N bars: none
    late = SOUP[:37] + [97.0] * TURTLE_N + [98.5, 99]
    assert not parse(F.bars(late)).of("CLOSE_REVERT")


def test_close_revert_flips():
    (e,) = parse(flip(F.bars(SOUP))).of("CLOSE_REVERT")
    assert e.id == "CLOSE_REVERT.U.37.x24" and e.get("level") == -97.75


def _shift_df():
    """SOUP with bar 37 a large bull bar closing at 101.5: a DISPLACE_C and a DELIVERY_SHIFT up."""
    df = F.bars(SOUP).iloc[:37]
    big = pd.DataFrame([dict(open=97.5, high=101.6, low=97.25, close=101.5, volume=1.0)])
    return pd.concat([df, big, F.bars([102.0, 102.5, 103.0], first_open=101.5)], ignore_index=True)


def test_sweep_shift_on_hand_built_bars():
    ch = parse(_shift_df())
    ss = {e.id: e for e in ch.of("SWEEP_SHIFT")}
    e = ss["SWEEP_SHIFT.U.37"]
    assert (e.known_at, e.get("sweep"), e.get("shift"), e.get("bars"), e.get("level")) == (
        37, "CLOSE_REVERT.D.37.x24", "DISPLACE_C.U.37", 0, 97.75)  # DISPLACE_C's row comes first
    assert e.parts == ("CLOSE_REVERT.D.37.x24", "DISPLACE_C.U.37")
    assert all(x.dir is Dir.UP for x in ss.values())
    m = parse(flip(_shift_df())).by_id()["SWEEP_SHIFT.D.37"]
    assert m.get("sweep") == "CLOSE_REVERT.U.37.x24" and m.get("level") == -97.75


def test_sweep_shift_with_a_wick_sweep():
    """A wick under the low that closes back (BREACH_REVERT) and the large bull bar after it."""
    df = F.bars(SOUP).iloc[:36]
    wick = pd.DataFrame([dict(open=98.5, high=98.6, low=97.25, close=98.0, volume=1.0),
                         dict(open=98.0, high=101.6, low=97.9, close=101.5, volume=1.0)])
    ch = parse(pd.concat([df, wick, F.bars([102.0, 102.5, 103.0], first_open=101.5)], ignore_index=True))
    e = ch.by_id()["SWEEP_SHIFT.U.37"]
    assert e.get("sweep") == "BREACH_REVERT.D.36.x24" and e.get("bars") == 1


def _lows(df, ch, side):
    """The frame's swing lows: (price in the frame, known_at, at, id)."""
    d = Dir.DOWN if side > 0 else Dir.UP
    return [(side * e.get("price"), e.known_at, e.at, e.id) for e in ch.of("EXTREME") if e.dir is d]


@pytest.mark.parametrize("seed", [0, 1])
def test_close_revert_brute_force(seed):
    df = synth.garch(3000, seed=seed)
    ch = parse(df)
    want = set()
    for side, frame in ((1, df), (-1, flip(df))):
        c = frame["close"].to_numpy()
        for P, known, at, eid in _lows(df, ch, side):
            u = next((t for t in range(known + 1, len(c)) if c[t] < P), None)
            if u is None:
                continue
            v = next((t for t in range(u + 1, min(len(c), u + 1 + TURTLE_N)) if c[t] >= P), None)
            if v is not None:
                want.add((v, eid))
    got = {(e.at, e.get("extreme")) for e in ch.of("CLOSE_REVERT")}
    assert got == want and len(want) > 100


@pytest.mark.parametrize("seed", [0, 1])
def test_sweep_shift_brute_force(seed):
    df = synth.garch(3000, seed=seed)
    ch = parse(df)
    sweeps = [e for e in ch.of("BREACH_REVERT", "CLOSE_REVERT")]
    want = set()
    for x in ch.of("DISPLACE_C", "DELIVERY_SHIFT"):
        if any(s.dir is x.dir.flip() and x.at - SHIFT_K <= s.at <= x.at for s in sweeps):
            want.add((x.at, x.dir))
    got = {(e.at, e.dir) for e in ch.of("SWEEP_SHIFT")}
    assert got == want and len(want) > 50
    shifts = {(x.type, x.at, x.dir) for x in ch.of("DISPLACE_C", "DELIVERY_SHIFT")}
    for e in ch.of("SWEEP_SHIFT"):  # the first row that matches, in table order, and its earliest sweep
        for st in ("BREACH_REVERT", "CLOSE_REVERT"):
            cands = [s for s in sweeps if s.type == st and s.dir is e.dir.flip() and e.at - SHIFT_K <= s.at <= e.at]
            xt = next((x for x in ("DISPLACE_C", "DELIVERY_SHIFT") if (x, e.at, e.dir) in shifts), None)
            if cands:
                assert (e.get("sweep_type"), e.get("shift_type")) == (st, xt)
                assert ch.by_id()[e.get("sweep")].at == min(s.at for s in cands)
                break


@pytest.mark.parametrize("seed", [0, 1])
def test_inducement_brute_force(seed):
    df = synth.garch(4000, seed=seed)
    ch = parse(df)
    ids = ch.by_id()
    got = {e.get("zone"): e for e in ch.of("INDUCEMENT")}
    firsts = [e for e in ch.of("REVISIT") if e.get("count") == 1]
    assert len(got) > 10 and len(firsts) > len(got)
    for rv in firsts:
        z = ids[rv.get("zone")]
        side = 1 if z.dir is Dir.UP else -1
        frame = df if side > 0 else flip(df)
        lo = frame["low"].to_numpy()
        near, r = side * z.get("near"), rv.at
        best = None
        for P, known, at, eid in _lows(df, ch, side):
            tk = next((t for t in range(known + 1, len(lo)) if lo[t] < P), None)
            if tk is not None and P > near and r - INDUCE_N <= tk <= r:
                if best is None or (tk, -P) > (best[0], -best[1]):
                    best = (tk, P, eid)
        if best is None:
            assert z.id not in got
        else:
            e = got[z.id]
            assert (e.at, e.get("taken_at"), e.get("extreme")) == (r, best[0], best[2])


@pytest.mark.parametrize("seed", [0, 1])
def test_breakers_brute_force(seed):
    df = synth.garch(3000, seed=seed)
    ch = parse(df)
    ids = ch.by_id()
    broke = {e.get("zone"): e.at for e in ch.of("FAIL")} | {e.get("void"): e.at for e in ch.of("VOID_INVERTED")}
    want = set()
    for sid, f in broke.items():
        s = ids[sid]
        side = 1 if s.dir is Dir.UP else -1
        frame = df if side > 0 else flip(df)
        h, c = frame["high"].to_numpy(), frame["close"].to_numpy()
        edge = side * s.get("far") if s.type == "ZONE" else h[s.at - 2]
        t = next((t for t in range(f + 1, min(len(h), f + 1 + BREAKER_MAX)) if h[t] >= edge), None)
        if t is not None:
            want.add(("RECLAIM" if c[t] > edge else "BREAKER_RETEST", sid, t))
    got = {(e.type, e.get("of"), e.at) for e in ch.of("BREAKER_RETEST", "RECLAIM")}
    assert got == want
    kinds = {(k, ids[s].type) for k, s, _ in got}
    assert kinds == {(a, b) for a in ("RECLAIM", "BREAKER_RETEST") for b in ("ZONE", "VOID")}


@pytest.mark.parametrize("seed", [0, 1])
def test_protected_brute_force(seed):
    df = synth.garch(3000, seed=seed)
    ch = parse(df)
    ids = ch.by_id()
    prot = {e.at * 2 + (e.dir is Dir.DOWN): e for e in ch.of("PROTECTED")}
    grades = set()
    for leg in ch.of("LEG"):
        side = 1 if leg.dir is Dir.UP else -1
        lo = (df if side > 0 else flip(df))["low"].to_numpy()
        p = leg.at
        e = prot.get(p * 2 + (leg.dir is Dir.DOWN))
        if leg.get("reason") not in ("BREAK", "TIMEOUT"):
            assert e is None
            continue
        if e is None:  # only when the low was traded under before it could be graded
            known = ids[f"BREAK.{leg.dir.letter}.{leg.get('end')}.o{p}"].known_at if leg.get("reason") == "BREAK" \
                else leg.known_at
            assert lo[p + 1:known + 1].min() < lo[p]
            continue
        grades.add(e.get("grade"))
        assert e.get("level") == side * lo[p]
        if leg.get("reason") == "TIMEOUT":
            assert e.get("grade") == "WEAK" and e.known_at == p + LEG_MAX
        else:
            sp = ids.get(f"SWEEP_PROTECTED.{leg.dir.letter}.{p}")
            assert (e.get("grade") == "SWEEP_STRONG") == (sp is not None and any(
                d.get("origin") == leg.get("origin") and d.at <= leg.get("end") for d in ch.of("DISPLACE")))
            assert e.get("break") in e.parts
        tk = [x for x in ch.of("PROTECTED_TAKEN") if x.get("protected") == e.id]
        hit = np.flatnonzero(lo[e.known_at + 1:] < lo[p])
        assert len(tk) == (1 if len(hit) else 0)
        if tk:
            assert tk[0].at == e.known_at + 1 + hit[0]
    assert grades == {"WEAK", "STRONG", "SWEEP_STRONG"}


def test_sweep_entities_at_their_known_at():
    df = series(2500, 23)
    full = parse(df)
    cache = {}

    def at(T):
        if T not in cache:
            cache[T] = parse(df.iloc[:T + 1])
        return cache[T]

    for kind in SWEEP_TYPES:
        ents = [e for e in full.entities if e.type == kind]
        assert ents, kind
        for e in ents[:3]:
            assert e in set(at(e.known_at).entities), e.id
            assert e not in set(at(e.known_at - 1).entities), e.id


def test_sweep_entities_flip():
    df = series(2500, 31)
    a, b = parse(df), parse(flip(df))
    m = mirror(a)
    for kind in SWEEP_TYPES:
        got = {e for e in m.entities if e.type == kind}
        want = {e for e in b.entities if e.type == kind}
        assert got == want and got, kind
