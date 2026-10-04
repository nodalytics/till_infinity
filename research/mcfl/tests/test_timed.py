"""Time core item 6: time-based events - TIMEOUT (rows of the rule table), STALL, SESSION_FIRST_MOVE
and LATE / EARLY - each against a brute-force reading of its definition."""
from __future__ import annotations

from collections import Counter

import fixtures as F
import numpy as np
import pytest
from mcfl import synth
from mcfl.core import Dir
from mcfl.parse import parse
from mcfl.seasonal import HOUR_MIN, HOUR_WINDOW
from mcfl.timed import (RARE_RATE, RULES, STALL_ATR, STALL_MAX, STALL_MIN, STALL_N, STALL_Q, TIMED, TIMEOUT_BARS,
                        confinement)


@pytest.fixture(scope="module")
def chart():
    df = F.with_calendar(synth.ticks(synth.garch(4000, seed=71), seed=72), 900, F.WINTER_MONDAY, "fx")
    return df, parse(df)


def test_timeout_is_a_row_of_the_rule_table():
    assert {r.head for r in RULES.values()} == {"TIMEOUT"}
    assert RULES["TIMEOUT_ZONE"].timed and RULES["TIMEOUT_RANGE"].sym


@pytest.mark.parametrize(("kind", "key", "life"), [
    ("ZONE", "zone", ("REVISIT",)), ("VOID", "void", ("VOID_PARTIAL",)),
    ("RANGE", "range", ("FAILED_ESCAPE", "ESCAPE"))])
def test_timeout_brute_force(chart, kind, key, life):
    _, ch = chart
    outs = {e.get("of"): e for e in ch.of("TIMEOUT") if e.get("kind") == kind}
    evs = [e for e in ch.entities if e.type in life]
    n_out = 0
    for s in ch.of(kind):
        t = s.known_at + TIMEOUT_BARS
        if t > ch.n - 1:
            assert s.id not in outs
            continue
        quiet = not any(e.get(key) == s.id and e.at <= t and e.known_at <= t for e in evs)
        assert (s.id in outs) == quiet, s.id
        if quiet:
            o = outs[s.id]
            n_out += 1
            assert o.at == o.known_at == t and o.get("bars") == TIMEOUT_BARS
            assert o.dir is (Dir.NONE if kind == "RANGE" else s.dir)
            assert o.time.start == o.time.end == t  # an instant
    assert n_out > 3 or kind == "RANGE"  # on a walk a box is left within 48 bars: see the next test


def test_a_box_that_holds_times_out():
    df = F.bars(F.WARMUP + [100.0, 100.4] * 40)  # a tight oscillation: a RANGE that is never left
    ch = parse(df)
    (r,) = ch.of("RANGE")
    (o,) = [e for e in ch.of("TIMEOUT") if e.get("kind") == "RANGE"]
    assert o.get("of") == r.id and o.at == o.known_at == r.known_at + TIMEOUT_BARS and o.dir is Dir.NONE
    assert not [e for e in parse(df.iloc[:o.at]).of("TIMEOUT") if e.get("kind") == "RANGE"]  # not before


def test_confinement_brute_force(chart):
    df, ch = chart
    from mcfl import candles
    T = candles.table(df)
    c = confinement(T)
    h, l, a = T["high"], T["low"], T["atr"]
    for t in range(30, len(c), 97):
        k = 0
        while k < STALL_MAX and t - k >= 0 and h[t - k:t + 1].max() - l[t - k:t + 1].min() <= STALL_ATR * a[t]:
            k += 1
        assert c[t] == k


def test_stall_brute_force(chart):
    df, ch = chart
    from mcfl import candles
    c = confinement(candles.table(df))
    hr = (df["ts"].to_numpy() // 3600) % 24
    want, above, seen = [], False, {}
    for t in range(len(c)):
        past = seen.setdefault(hr[t], [])[-STALL_N:]
        seen[hr[t]].append(c[t])
        if len(past) < STALL_MIN:
            above = False
            continue
        q = np.quantile(np.array(past, float), STALL_Q)
        now = c[t] > q
        if now and not above:
            want.append(t)
        above = now
    got = [e.at for e in ch.of("STALL")]
    assert got == want and len(got) > 20
    for e in ch.of("STALL"):
        assert e.time.bars == e.get("bars") == c[e.at] and e.dir is Dir.NONE


def test_session_first_move_brute_force(chart):
    df, ch = chart
    ts = df["ts"].to_numpy()
    ext = sorted(ch.of("EXTREME"), key=lambda e: e.at)
    got = Counter((e.get("window"), e.get("extreme")) for e in ch.of("SESSION_FIRST_MOVE"))
    want = Counter()
    for w in ch.of("WINDOW"):
        if w.get("kind") not in ("SESSION", "KILLZONE"):
            continue
        inside = [e for e in ext if e.at >= w.at and w.get("sched_start") <= ts[e.at] < w.get("sched_end")]
        if inside:
            first = inside[0].at
            want.update((w.id, e.id) for e in inside if e.at == first)
    assert got == want and len(got) > 100
    ids = ch.by_id()
    for e in ch.of("SESSION_FIRST_MOVE"):
        x = ids[e.get("extreme")]
        assert (e.at, e.known_at, e.dir) == (x.at, x.known_at, x.dir)
        assert e.get("bars") == e.at - ids[e.get("window")].at


def test_late_and_early_brute_force(chart):
    df, ch = chart
    hr = (df["ts"].to_numpy() // 3600) % 24
    marks = {e.get("of"): e for e in ch.of("LATE", "EARLY")}
    n = 0
    for typ in TIMED:
        es = sorted(ch.of(typ), key=lambda e: (e.known_at, e.at))
        for e in es:
            past = [hr[x.at] for x in es if x.known_at < e.known_at][-HOUR_WINDOW:]
            if len(past) < HOUR_MIN:
                assert e.id not in marks
                continue
            rate = 24 * sum(1 for h in past if h == hr[e.at]) / len(past)
            assert e.time.hour_rate == pytest.approx(rate)
            assert (e.id in marks) == (rate < RARE_RATE)
            if e.id in marks:
                n += 1
                ang = 2 * np.pi * np.array(past) / 24
                usual = (np.arctan2(np.sin(ang).sum(), np.cos(ang).sum()) % (2 * np.pi)) * 24 / (2 * np.pi)
                off = (hr[e.at] + 0.5 - usual + 12) % 24 - 12
                m = marks[e.id]
                assert m.type == ("LATE" if off >= 0 else "EARLY") and m.get("usual_hour") == pytest.approx(usual)
                assert (m.at, m.known_at, m.dir) == (e.at, e.known_at, e.dir)
    assert n > 10
