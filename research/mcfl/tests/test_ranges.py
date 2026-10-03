"""v2 item 5: RANGE as a structure - a causal box, tests of its edges, ESCAPE and FAILED_ESCAPE."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import synth
from mcfl.parse import flip, parse
from mcfl.ranges import ESCAPE_HOLD, RANGE_ATR, RANGE_BARS


def B(o, h, l, c):
    return dict(open=o, high=h, low=l, close=c, volume=1.0)


def _evs(ch):
    return [(e.id, e.known_at) for e in ch.entities if e.type in ("RANGE", "RANGE_TEST", "ESCAPE", "FAILED_ESCAPE")]


def test_the_warmup_is_a_range_and_three_closes_above_escape_it():
    """The warm-up bars sit in 99.75 .. 100.75 with ATR 1: a range, known once the ATR exists."""
    ch = parse(F.bars(F.WARMUP + [101.0, 101.5, 102.0]))
    assert _evs(ch) == [("RANGE.N.5", 14), ("ESCAPE.U.20.r5", 22)]
    r = ch.by_id()["RANGE.N.5"]
    assert (r.get("high"), r.get("low"), r.get("height_atr"), r.dir.value) == (100.75, 99.75, 1.0, "NONE")
    assert r.parts == tuple(f"CANDLE.{'U' if t % 2 else 'D'}.{t}" for t in range(5, 15))
    e = ch.by_id()["ESCAPE.U.20.r5"]
    assert e.parts == ("CANDLE.U.20", "CANDLE.U.21", "CANDLE.U.22") and e.get("level") == 100.75


def test_two_closes_above_are_not_an_escape_yet():
    ch = parse(F.bars(F.WARMUP + [101.0, 101.5]))
    assert _evs(ch) == [("RANGE.N.5", 14)]  # pending: a third close decides it


def test_failed_escape_then_escape_down():
    ch = parse(F.bars(F.WARMUP + [101.0, 100.5, 100.0, 99.5, 99.0, 98.5]))
    assert _evs(ch) == [("RANGE.N.5", 14), ("FAILED_ESCAPE.U.20.r5", 21), ("RANGE_TEST.D.22.r5", 22),
                        ("ESCAPE.D.23.r5", 25)]
    e = ch.by_id()["ESCAPE.D.23.r5"]
    assert (e.get("upper_tests"), e.get("lower_tests")) == (1, 1)  # the failed escape tested the top


def test_tests_of_each_edge():
    df = pd.concat([F.bars(F.WARMUP), pd.DataFrame([
        B(100.5, 100.55, 100.1, 100.3), B(100.3, 100.7, 100.2, 100.5),   # within 0.1 ATR of the top
        B(100.5, 100.55, 100.1, 100.3), B(100.3, 100.4, 99.8, 100.0),    # of the bottom
        B(100.0, 100.7, 99.95, 100.6), B(100.6, 100.72, 100.3, 100.5)])],  # the top again, twice running
        ignore_index=True)
    ch = parse(df)
    tests = [(e.id, e.get("count")) for e in ch.of("RANGE_TEST")]
    assert tests == [("RANGE_TEST.U.21.r5", 1), ("RANGE_TEST.D.23.r5", 1), ("RANGE_TEST.U.24.r5", 2)]


def test_flip_twin():
    ch = parse(flip(F.bars(F.WARMUP + [101.0, 100.5, 100.0, 99.5, 99.0, 98.5])))
    assert _evs(ch) == [("RANGE.N.5", 14), ("FAILED_ESCAPE.D.20.r5", 21), ("RANGE_TEST.U.22.r5", 22),
                        ("ESCAPE.U.23.r5", 25)]
    r = ch.by_id()["RANGE.N.5"]
    assert (r.get("high"), r.get("low")) == (-99.75, -100.75)


@pytest.mark.parametrize("seed", [0, 1])
def test_ranges_on_walks(seed):
    df = synth.garch(4000, seed=seed)
    ch = parse(df)
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    ids = ch.by_id()
    rs = ch.of("RANGE")
    assert len(rs) > 5
    for r in rs:
        s, t = r.at, r.known_at
        assert t - s + 1 == RANGE_BARS and h[s:t + 1].max() == r.get("high") and l[s:t + 1].min() == r.get("low")
        assert r.get("height_atr") <= RANGE_ATR
    ends = {}
    for e in ch.of("ESCAPE", "FAILED_ESCAPE"):
        r = ids[e.get("range")]
        up = e.dir.value == "UP"
        beyond = (c[e.at:e.known_at + 1] > r.get("high")) if up else (c[e.at:e.known_at + 1] < r.get("low"))
        if e.type == "ESCAPE":
            assert beyond.all() and e.known_at - e.at + 1 == ESCAPE_HOLD
            ends[r.id] = e.known_at
        else:
            assert beyond[:-1].all() and not beyond[-1] and e.known_at - e.at < ESCAPE_HOLD
    for r in rs:  # ranges do not overlap: the next starts after the last one's escape was confirmed
        later = [x for x in rs if x.at > r.at]
        if later and r.id in ends:
            assert min(x.at for x in later) > ends[r.id]
    assert np.isfinite([e.get("level") for e in ch.of("RANGE_TEST")]).all()
