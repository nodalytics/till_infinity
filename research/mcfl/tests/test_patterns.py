"""The candle productions. Word productions are checked on hand-built token tables, where one
qualifier can be changed alone - so each fixture passes, and fails on strength alone. REJECT is
checked through the rule matcher on hand-built entities and end to end; DELIVERY_SHIFT on bars and
against the desk's own `zones._cisd` on walks."""
from __future__ import annotations

import sys
from pathlib import Path

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import candles, synth
from mcfl.core import Dir, Entity, attrs_of
from mcfl.grammar import CANDLE_RULES, WORDS, Clause, apply, q, run, word_mask
from mcfl.parse import parse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ideas"))
import zones as Z  # noqa: E402

BASE = {"dir": "NONE", "size": "MEDIUM", "body": "MEDIUM", "upper": "MEDIUM", "lower": "MEDIUM",
        "conv_g": "MODERATE", "force_g": "MODERATE", "upper_g": "MODERATE", "lower_g": "MODERATE",
        "upper_share_g": "MODERATE", "lower_share_g": "MODERATE", "close_q": "Q2", "rel": "HH",
        "engulf": "NONE", "beyond": "NONE"}


def table(n: int, **bars: dict) -> candles.Table:
    """n bars of plain tokens; `b2={"dir": "BULL"}` sets bar 2's columns."""
    T = {k: np.array([v] * n, object) for k, v in BASE.items()}
    T["close"] = np.zeros(n)
    T["rel_valid"] = np.arange(n) >= 1
    for key, cols in bars.items():
        t = int(key[1:])
        for k, v in cols.items():
            T[k][t] = v
    return T


def fires(word: str, T: candles.Table, side: int = 1) -> list[int]:
    return [int(t) for t in np.flatnonzero(word_mask(WORDS[word], candles.frame(T, side)))]


# ---------------------------------------------------------------- PIN

PIN = {"lower_g": "STRONG", "force_g": "MODERATE", "close_q": "Q3", "upper_g": "WEAK"}


def test_pin_passes():
    assert fires("PIN", table(4, b2=PIN)) == [2]
    assert fires("PIN", table(4, b2={**PIN, "lower_g": "DOMINANT", "close_q": "Q4", "upper_g": "NONE"})) == [2]


@pytest.mark.parametrize(("col", "val"), [("lower_g", "MODERATE"), ("force_g", "STRONG"), ("close_q", "Q2"),
                                          ("upper_g", "MODERATE")])
def test_pin_fails_on_strength_alone(col, val):
    assert fires("PIN", table(4, b2={**PIN, col: val})) == []


def test_pin_down_is_the_mirror():
    down = {"upper_g": "STRONG", "force_g": "WEAK", "close_q": "Q2", "lower_g": "NONE"}
    assert fires("PIN", table(4, b2=down), side=-1) == [2]
    assert fires("PIN", table(4, b2=down), side=1) == []


# ---------------------------------------------------------------- DISPLACE_C

STRONG_BULL = {"dir": "BULL", "force_g": "STRONG", "close_q": "Q4"}


def test_displace_run_fires_once_where_the_run_reaches_two():
    T = table(6, b1=STRONG_BULL, b2=STRONG_BULL, b3={**STRONG_BULL, "force_g": "DOMINANT"})
    assert fires("DISPLACE_C_RUN", T) == [2]  # bar 3 continues the run, it does not start one


@pytest.mark.parametrize(("col", "val"), [("force_g", "MODERATE"), ("close_q", "Q3"), ("dir", "BEAR")])
def test_displace_run_fails_on_one_qualifier(col, val):
    assert fires("DISPLACE_C_RUN", table(4, b1=STRONG_BULL, b2={**STRONG_BULL, col: val})) == []


def test_displace_single_bar():
    bar = {"dir": "BULL", "size": "EXTREMELY_LARGE", "force_g": "DOMINANT", "close_q": "Q4"}
    assert fires("DISPLACE_C_BAR", table(3, b1=bar)) == [1]
    assert fires("DISPLACE_C_BAR", table(3, b1={**bar, "force_g": "STRONG"})) == []  # strength alone
    assert fires("DISPLACE_C_BAR", table(3, b1={**bar, "size": "VERY_LARGE"})) == []


def test_displace_strength_attribute():
    ch = parse(synth.trend(3000, seed=4))
    dc = ch.of("DISPLACE_C")
    assert dc
    ids = ch.by_id()
    for e in dc:
        x = [ids[p].get("body_atr") for p in e.parts]
        assert e.get("strength_mean") == pytest.approx(float(np.mean(x)))
        assert e.get("strength_max") == max(x)
        assert all(ids[p].get("force_g") in ("STRONG", "DOMINANT") for p in e.parts)


# ---------------------------------------------------------------- ENGULF, INSIDE_BREAK, STAR

def test_engulf():
    T = table(4, b1={"dir": "BEAR"}, b2={"dir": "BULL", "engulf": "BULL"})
    assert fires("ENGULF", T) == [2]
    assert fires("ENGULF", table(4, b1={"dir": "BEAR"}, b2={"dir": "BULL"})) == []
    assert fires("ENGULF", table(4, b1={"dir": "BULL"}, b2={"dir": "BEAR", "engulf": "BEAR"}), side=-1) == [2]


def test_inside_break():
    assert fires("INSIDE_BREAK", table(4, b1={"rel": "INSIDE"}, b2={"beyond": "ABOVE"})) == [2]
    assert fires("INSIDE_BREAK", table(4, b1={"rel": "HH"}, b2={"beyond": "ABOVE"})) == []
    assert fires("INSIDE_BREAK", table(4, b1={"rel": "INSIDE"}, b2={"beyond": "BELOW"}), side=-1) == [2]
    assert fires("INSIDE_BREAK", table(4, b0={"rel": "INSIDE"}, b1={"beyond": "ABOVE"})) == []  # bar 0 has no relation


def test_star():
    star = dict(b0={"dir": "BEAR", "body": "LARGE"}, b1={"body": "SMALL"}, b2={"dir": "BULL", "body": "TREND"})
    assert fires("STAR", table(4, **star)) == [2]
    assert fires("STAR", table(4, **{**star, "b1": {"body": "MEDIUM"}})) == []
    evening = dict(b0={"dir": "BULL", "body": "TREND"}, b1={"body": "NONE"}, b2={"dir": "BEAR", "body": "LARGE"})
    assert fires("STAR", table(4, **evening), side=-1) == [2]


def test_words_on_bars_list_their_tokens():
    ch = parse(synth.garch(2000, seed=8))
    ids = ch.by_id()
    for e in ch.of("PIN", "ENGULF", "INSIDE_BREAK", "STAR", "DISPLACE_C", "DELIVERY_SHIFT"):
        assert e.parts and all(ids[p].type in ("CANDLE", "BAR_RELATION") for p in e.parts), e.id
        assert e.known_at == max(ids[p].at for p in e.parts)


# ---------------------------------------------------------------- the qualifier syntax

def test_qualifiers_compile_to_clauses():
    got = q("CANDLE[dir=BULL, body≥STRONG, close=Q4, wick.up≤WEAK]", 0)
    assert got == (Clause("0.dir", "==", "BULL"), Clause("0.force_g", "in", frozenset({"STRONG", "DOMINANT"})),
                   Clause("0.close_q", "==", "Q4"), Clause("0.upper_g", "in", frozenset({"NONE", "WEAK"})))
    assert q("CANDLE[wick.low≥STRONG, wick.low.body>=2]") == (
        Clause("lower_g", "in", frozenset({"STRONG", "DOMINANT"})), Clause("lower_body", ">=", 2.0))
    assert q("CANDLE[body≥LARGE, size>VERY_LARGE, dir!=BEAR]", -1) == (
        Clause("-1.body", "in", frozenset({"LARGE", "TREND"})),
        Clause("-1.size", "in", frozenset({"EXTREMELY_LARGE"})), Clause("-1.dir", "in", frozenset({"BULL", "NONE"})))
    assert q("CANDLE[OPEN_GAP_UP, not CLOSE_AT_HIGH, HIGH_AT_OPEN]") == (
        Clause("OPEN_GAP_UP", "==", True), Clause("CLOSE_AT_HIGH", "==", False), Clause("OPEN_AT_HIGH", "==", True))
    cells, where, unless = run("RUN[k≥3, dir=BULL]")
    assert cells == (-2, -1, 0) and len(where) == 3 and unless == (Clause("-3.dir", "==", "BULL"),)
    with pytest.raises(ValueError):
        q("CANDLE[colour=BULL]")


def test_point_qualifiers_select_bars():
    df = synth.walk(400, seed=3)
    T = candles.table(df)
    from mcfl.grammar import Word
    w = Word("X", (0,), q("CANDLE[dir=BULL, CLOSE_ABOVE_PREV_HIGH]", 0))
    got = np.flatnonzero(word_mask(w, T))
    want = np.flatnonzero((T["dir"] == "BULL") & T["CLOSE_ABOVE_PREV_HIGH"])
    assert len(want) > 10 and list(got) == list(want)


# ---------------------------------------------------------------- REJECT

def _ent(kind, d, at, **a):
    return Entity(f"{kind}.{d.letter}.{at}" + (f".z{a.pop('_z')}" if "_z" in a else ""), kind, d, at, at, attrs_of(a))


def _reject(zone_dir, candle_at, fail_at=None, **candle):
    d = zone_dir
    z = _ent("ZONE", d, 10, near=100.0, far=99.0 if d is Dir.UP else 101.0)
    r = _ent("REVISIT", d, 20, zone=z.id, count=1, _z=10)
    c = _ent("CANDLE", Dir.NONE, candle_at, **candle)
    ents = [z, r, c] + ([_ent("FAIL", d, fail_at, zone=z.id, count=1, _z=10)] if fail_at is not None else [])
    built, failed, pending = apply(ents, CANDLE_RULES, n=100)
    assert not failed and not pending  # pattern rules report nothing
    return [e.id for e in built]


def test_reject_passes_and_fails_on_strength_alone():
    assert _reject(Dir.UP, 21, lower_g="STRONG", close=100.5) == ["REJECT.U.21.z10"]
    assert _reject(Dir.UP, 20, lower_g="DOMINANT", close=100.5) == ["REJECT.U.20.z10"]  # on the revisit bar
    assert _reject(Dir.UP, 21, lower_g="MODERATE", close=100.5) == []  # strength alone
    assert _reject(Dir.UP, 21, lower_g="STRONG", close=99.8) == []  # did not close back out
    assert _reject(Dir.UP, 23, lower_g="STRONG", close=100.5) == []  # outside the window (20..22)
    assert _reject(Dir.UP, 22, fail_at=21, lower_g="STRONG", close=100.5) == []  # the zone failed first
    # a down zone: the wick toward it is the upper one, and back out is below its near edge
    assert _reject(Dir.DOWN, 21, upper_g="STRONG", lower_g="NONE", close=99.5) == ["REJECT.D.21.z10"]
    assert _reject(Dir.DOWN, 21, upper_g="WEAK", lower_g="DOMINANT", close=99.5) == []


def test_reject_on_bars():
    """The canonical zone, revisited by a bar with a long lower wick that closes back above."""
    df = F.bars(F.ZONE_UP + [103.5, 102.5, 101.5, 100.5])
    df = pd.concat([df, pd.DataFrame([dict(open=100.5, high=100.8, low=99.0, close=100.6, volume=1.0)])],
                   ignore_index=True)
    ch = parse(df)
    t = len(df) - 1
    (r,) = ch.of("REJECT")
    assert r.id == f"REJECT.U.{t}.z{F.ORIGIN_BAR}" and r.known_at == t
    assert r.parts == (f"REVISIT.U.{t}.z{F.ORIGIN_BAR}", f"CANDLE.U.{t}")
    assert ch.by_id()[f"CANDLE.U.{t}"].get("lower_g") in ("STRONG", "DOMINANT")


# ---------------------------------------------------------------- DELIVERY_SHIFT

def test_delivery_shift_on_bars():
    base = F.WARMUP + [101.0, 102.0, 101.5, 101.0, 100.5]  # bars 22-24: a run of three BEAR bars from 102
    ch = parse(F.bars(base + [102.5]))
    e = ch.by_id()["DELIVERY_SHIFT.U.25"]
    assert (e.get("run_len"), e.get("lag"), e.known_at) == (3, 1, 25)
    assert e.parts == ("CANDLE.D.22", "CANDLE.D.23", "CANDLE.D.24", "CANDLE.U.25")
    assert e.get("margin") == pytest.approx(0.5 / ch.by_id()["CANDLE.U.25"].get("atr"))
    assert e.get("run_force_max") >= e.get("run_force_mean") > 0
    # not above the run's first open: no shift
    assert "DELIVERY_SHIFT.U.25" not in parse(F.bars(base + [101.9])).by_id()
    # two small BULL bars, then the shift 3 bars after the run: yes; 4 bars after: no
    late = parse(F.bars(base + [100.7, 100.9, 102.2]))
    assert "DELIVERY_SHIFT.U.27" in late.by_id() and late.by_id()["DELIVERY_SHIFT.U.27"].get("lag") == 3
    later = parse(F.bars(base + [100.6, 100.7, 100.9, 102.2]))
    assert "DELIVERY_SHIFT.U.28" not in later.by_id()


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_delivery_shift_is_the_desks_cisd(seed):
    """Every bar of a walk, both directions: a DELIVERY_SHIFT exactly where zones._cisd says so."""
    for gen in (synth.walk, synth.garch):
        df = gen(3000, seed=seed)
        ch = parse(df)
        ours = {(e.at, e.dir) for e in ch.of("DELIVERY_SHIFT")}
        n = 0
        for d, frame in ((Dir.UP, df), (Dir.DOWN, Z.flip(df))):
            o, c = frame["open"].to_numpy(), frame["close"].to_numpy()
            for j in range(len(df)):
                want = bool(c[j] > o[j] and Z._cisd(o, c, j))
                assert ((j, d) in ours) == want, (gen.__name__, d, j)
                n += want
        assert n == len(ours) > 100


def test_delivery_shift_flips():
    df = synth.garch(1500, seed=6)
    from mcfl.parse import flip
    a = {(e.at, e.dir.flip(), e.get("run_len"), e.get("lag"), e.get("margin")) for e in parse(df).of("DELIVERY_SHIFT")}
    b = {(e.at, e.dir, e.get("run_len"), e.get("lag"), e.get("margin")) for e in parse(flip(df)).of("DELIVERY_SHIFT")}
    assert a == b and a


def test_delivery_shift_confirms_a_revisit():
    """A revisit, then a BULL bar that closes above the open of the BEAR run that came down into
    the zone: REVISITED -> CONFIRMED, caused by the shift."""
    df = F.bars(F.ZONE_UP + [103.5, 102.5, 101.5, 100.5, 99.5])
    df = pd.concat([df, pd.DataFrame([dict(open=99.5, high=105.0, low=99.4, close=104.8, volume=1.0)])],
                   ignore_index=True)
    ch = parse(df)
    t = len(df) - 1
    z = f"ZONE.U.{F.ORIGIN_BAR}"
    tr = [(x.src, x.dst, x.event.split(".")[0], x.known_at) for x in ch.transitions if x.zone == z]
    assert tr[-3:] == [("QUALIFIED", "REVISITED", "REVISIT", t - 1), ("REVISITED", "CONFIRMED", "DELIVERY_SHIFT", t),
                       ("CONFIRMED", "REJECTED", "REJECT_PATH", t)]  # the shift bar also travelled 1 ATR
    assert ch.by_id()[f"DELIVERY_SHIFT.U.{t}"].get("run_len") == 5
