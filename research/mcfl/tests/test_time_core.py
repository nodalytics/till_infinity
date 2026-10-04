"""Time core item 1: every entity is an interval in bars and in wall-clock time, with its known_at
in time, its duration in bars, seconds and trading seconds; EPISODE makes the lifecycles intervals;
and item 5's age of an event."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pytest
from mcfl import synth
from mcfl.clocks import Clock, age, bar_lengths, first_length
from mcfl.core import Span
from mcfl.grammar import qe
from mcfl.parse import parse


@pytest.fixture(scope="module")
def fx():
    df = F.with_calendar(synth.ticks(synth.garch(1500, seed=41), seed=42), 900, F.WINTER_MONDAY, "fx")
    return df, parse(df)


def test_bar_lengths_are_known_at_the_bar():
    ts = np.array([0, 900, 1800, 7200, 8100], np.int64) + 86400 * 10 + 300  # aligned to 5 minutes, not more
    got = bar_lengths(ts)
    assert got[0] == first_length(int(ts[0])) == 300  # the coarsest standard bar the open is aligned to
    assert list(got[1:]) == [300, 300, 300, 300]  # the running minimum of the gaps, never above the guess
    ts = np.array([86400 * 7, 86400 * 7 + 3600 * 3, 86400 * 7 + 3600 * 4], np.int64)
    assert list(bar_lengths(ts)) == [86400, 3600 * 3, 3600]
    assert list(bar_lengths(ts, seen=True)) == [0, 3600 * 3, 3600]  # bar 0's length is a guess: unseen
    assert list(bar_lengths(ts, sec=3600)) == [3600] * 3
    assert list(bar_lengths(ts, close_ts=ts + 60)) == [60] * 3
    # every prefix reads the same lengths
    big = F.calendar_ts(400, 900, F.WINTER_MONDAY, "index")
    full = bar_lengths(big)
    for T in (1, 2, 50, 399):
        assert (bar_lengths(big[:T]) == full[:T]).all()


def test_every_entity_is_an_interval(fx):
    df, ch = fx
    ts = df["ts"].to_numpy()
    clk = ch.clock
    for e in ch.entities:
        s = e.time
        assert isinstance(s, Span) and s.start <= e.at
        assert s.known_at_ts == ts[e.known_at] + clk.length[e.known_at]
        if e.type == "WINDOW":
            assert s.end is None and s.end_ts == e.get("sched_end") and s.start_ts == e.get("sched_start")
            continue
        assert s.start <= s.end <= e.known_at, e.id
        assert s.start_ts == ts[s.start] and s.end_ts == ts[s.end] + clk.length[s.end]
        assert s.bars == s.end - s.start + 1 and s.trade_sec == clk.seen[s.start:s.end + 1].sum()
        assert s.seconds >= s.trade_sec and s.gap_sec == s.seconds - s.trade_sec


def test_structures_span_what_they_were_built_from(fx):
    _, ch = fx
    ids = ch.by_id()
    for z in ch.of("ZONE"):
        assert (z.time.start, z.time.end) == (z.at, z.get("break_at"))
    for b in ch.of("BREAK"):
        assert (b.time.start, b.time.end) == (int(b.get("origin").split(".")[2]), b.at)
    for g in ch.of("LEG"):
        end = g.get("end") - (g.get("reason") == "INVALIDATED")
        assert (g.time.start, g.time.end) == (g.at, end)
    for x in ch.of("EXTREME"):
        assert x.time.start == x.time.end == x.at  # the swing's bar, not its confirmation window
    for r in ch.of("RANGE"):
        assert (r.time.start, r.time.end) == (r.at, r.known_at)
    for c in ch.of("CANDLE")[:50]:
        assert c.time.bars == 1
    sh = ch.of("STRUCTURE_SHIFT")[0]
    assert sh.time.start == sh.time.end == sh.at
    assert ids  # the chart has its clock
    assert ch.clock is not None


def test_a_weekend_is_calendar_time_not_trading_time(fx):
    df, ch = fx
    ts = df["ts"].to_numpy()
    fri = int(np.flatnonzero(np.diff(ts) > 900)[0])  # the last bar before the first weekend
    spanning = [e for e in ch.entities if e.time.end is not None and e.time.start <= fri < e.time.end]
    assert spanning
    assert ts[fri + 1] - ts[fri] - 900 == 49 * 3600  # Friday 21:00 to Sunday 22:00
    for e in spanning:
        assert e.time.gap_sec >= 49 * 3600
        assert e.time.trade_sec == 900 * e.time.bars


def test_no_timestamps_bars_only():
    ch = parse(synth.garch(400, seed=3))
    z = ch.of("ZONE")[0]
    assert (z.time.start, z.time.end) == (z.at, z.get("break_at"))
    assert z.time.start_ts is None and z.time.known_at_ts is None and z.time.seconds is None
    assert not ch.of("WINDOW") and not ch.of("HTF_CLOSE")  # no calendar without a clock
    assert ch.of("EPISODE") and ch.of("TIMEOUT")  # what needs only bars is there


def test_time_off_is_the_v2_chart():
    df = F.with_calendar(synth.garch(600, seed=5), 900)
    a, b = parse(df, time=False), parse(df)
    assert all(e.time is None for e in a.entities)
    base = {(e.id, e.attrs) for e in a.entities if e.type != "CANDLE"}
    assert base <= {(e.id, e.attrs) for e in b.entities}  # the time core adds, it changes no v2 entity
    old = {e.id: e for e in a.of("CANDLE")}
    for c in b.of("CANDLE"):
        assert set(old[c.id].attrs) <= set(c.attrs)  # only new qualifiers on the CANDLE


def test_episodes(fx):
    _, ch = fx
    ids = ch.by_id()
    eps = ch.of("EPISODE")
    assert {ids[e.get("of")].type for e in eps} == {"ZONE", "VOID", "RANGE"}
    for e in eps:
        s, end = ids[e.parts[0]], ids[e.parts[1]]
        assert e.get("outcome") == end.type and e.known_at == max(end.known_at, s.known_at) and e.dir is s.dir
        assert (e.time.start, e.time.end) == (s.at, end.at)
        life = [x for x in ch.entities if x.get({"ZONE": "zone", "VOID": "void", "RANGE": "range"}[s.type]) == s.id
                and x.type in ("REVISIT", "REJECT_PATH", "ACCEPT", "FAIL", "EXPIRE", "VOID_PARTIAL", "VOID_FILLED",
                               "VOID_INVERTED", "RANGE_TEST", "FAILED_ESCAPE", "ESCAPE")]
        assert min(x.known_at for x in life if x.type == end.type) == end.known_at
    zones_done = {e.get("of") for e in eps if e.get("of").startswith("ZONE")}
    assert zones_done == {z for z, st in ch.states if st in ("ACCEPTED", "FAILED", "EXPIRED")}


def test_age(fx):
    df, ch = fx
    z = ch.of("ZONE")[3]
    t = z.known_at + 200
    a = age(ch, z, t)
    c = ch.clock.close
    assert a["bars"] == 200 and a["seconds"] == c[t] - c[z.known_at]
    assert a["trade_sec"] == 200 * 900 <= a["seconds"]
    assert a["sessions"] == sum(1 for w in ch.of("WINDOW") if w.get("kind") == "SESSION" and z.known_at < w.known_at <= t)
    assert a["sessions"] >= 200 // 24  # a session every 6 hours or so
    with pytest.raises(ValueError):
        age(ch, z, z.known_at - 1)


def test_time_fields_in_clauses(fx):
    _, ch = fx
    b = next(e for e in ch.of("BREAK") if e.time.hour_rate is not None)
    assert b.field("known_at_ts") == b.time.known_at_ts == b.known_at_ts
    assert b.field("dur_bars") == b.time.bars and b.field("interval") == (b.time.start, b.time.end + 1)
    (c,) = qe("BREAK[hour_rate<0.5]")
    assert (c.field, c.op, c.rhs) == ("hour_rate", "<", 0.5)
    assert Clock.of(F.bars([100.0, 101.0])).ts is None
