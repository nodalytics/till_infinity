"""v2 item 8: sessions, days, session anchors (SESSION_OPEN, SESSION_EXTREME, SESSION_EXTREME_TAKEN)
and the tempo of every lifecycle event, with FAST / SLOW qualifiers."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import synth
from mcfl.core import Dir, Entity, attrs_of
from mcfl.grammar import Clause, qe
from mcfl.parse import flip, parse
from mcfl.timing import DAYS, TEMPO_MIN, session_of, tempo

MONDAY = 4 * 86400  # 1970-01-05 00:00 UTC, a Monday


def test_session_hours():
    got = session_of(np.arange(24))
    assert list(got[:7]) == ["ASIA"] * 7 and list(got[7:12]) == ["LONDON"] * 5
    assert list(got[12:16]) == ["OVERLAP"] * 4 and list(got[16:22]) == ["NY"] * 6 and list(got[22:]) == ["ASIA"] * 2


def _day(closes, start=MONDAY):
    return F.with_time(F.bars(closes), 3600, start)


def test_words_and_anchors_on_an_hourly_day():
    # 30 hourly bars from Monday 00:00: ASIA 0-6, LONDON 7-11, OVERLAP 12-15, NY 16-21, ASIA 22-29
    closes = [100.0] * 7 + [101.0, 102.0, 103.0, 102.5, 102.0] + [101.5] * 4 + [101.0] * 6 + [104.0] * 8
    ch = parse(_day(closes))
    c = {e.at: e for e in ch.of("CANDLE")}
    assert (c[0].get("session"), c[0].get("dow"), c[7].get("session"), c[25].get("dow")) == ("ASIA", "MON", "LONDON", "TUE")
    opens = [(e.at, e.get("session")) for e in ch.of("SESSION_OPEN")]
    assert opens == [(0, "ASIA"), (7, "LONDON"), (12, "OVERLAP"), (16, "NY"), (22, "ASIA")]
    ext = {(e.get("session"), e.dir): e for e in ch.of("SESSION_EXTREME")}
    lon = ext["LONDON", Dir.UP]
    assert (lon.at, lon.known_at, lon.get("price")) == (9, 12, 103.25)  # known when OVERLAP opens
    taken = [(e.get("session"), e.dir, e.at) for e in ch.of("SESSION_EXTREME_TAKEN")]
    # the NY bars stay under every earlier high; ASIA's 104 bar (22) takes the highs of LONDON, OVERLAP, NY
    assert ("LONDON", Dir.UP, 22) in taken and ("NY", Dir.UP, 22) in taken
    assert ("LONDON", Dir.DOWN, 16) not in taken  # NY's lows (100.75) stay above LONDON's low (99.75 from bar 7's open)
    assert ("ASIA", Dir.UP, 22) not in taken  # the second ASIA instance starts at 22: the first's watch has ended
    from mcfl.serialise import bar_words
    assert bar_words(ch, v2=True)[7].endswith("@LN.MON")


def test_extremes_and_takes_on_a_walk():
    df = F.with_time(synth.garch(2000, seed=3), 900, MONDAY)
    ch = parse(df)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    for e in ch.of("SESSION_EXTREME"):
        a, b = e.get("start"), e.get("end")
        x = h if e.dir is Dir.UP else -l
        assert e.at == a + int(np.argmax(x[a:b + 1])) and e.known_at == b + 1
    ids = ch.by_id()
    for t in ch.of("SESSION_EXTREME_TAKEN"):
        x = ids[t.get("extreme")]
        lvl = x.get("price")
        seg = h[x.known_at:t.at + 1] > lvl if t.dir is Dir.UP else l[x.known_at:t.at + 1] < lvl
        assert seg[-1] and not seg[:-1].any()
    assert len(ch.of("SESSION_EXTREME_TAKEN")) > 50


def test_flip_keeps_sessions_and_swaps_extremes():
    df = _day([100.0] * 7 + [101.0, 102.0, 103.0, 102.5, 102.0] + [101.5] * 4 + [101.0] * 6 + [104.0] * 8)
    ch = parse(flip(df))
    ext = {(e.get("session"), e.dir): e for e in ch.of("SESSION_EXTREME")}
    assert ext["LONDON", Dir.DOWN].at == 9 and ext["LONDON", Dir.DOWN].get("price") == -103.25
    assert [e.at for e in ch.of("SESSION_OPEN")] == [0, 7, 12, 16, 22]


def test_no_time_no_sessions():
    ch = parse(F.bars(F.ZONE_UP))
    assert not ch.of("SESSION_OPEN") and ch.of("CANDLE")[0].get("session") is None


def _ev(kind, at, group, known=None):
    return Entity(f"{kind}.U.{at}.v{group}", kind, Dir.UP, at, at if known is None else known, attrs_of({"void": f"VOID.U.{group}"}))


def test_tempo_and_pace():
    voids = [Entity(f"VOID.U.{g}", "VOID", Dir.UP, g, g) for g in range(0, 200, 10)]
    evs = [_ev("VOID_PARTIAL", g + 1 + (g // 10) % 5, g) for g in range(0, 200, 10)]  # tempos 1,2,3,4,5,1,...
    evs.append(_ev("VOID_FILLED", 197, 190))
    got = {e.id: e for e in tempo(voids + evs)}
    partial = sorted((e for e in got.values() if e.type == "VOID_PARTIAL"), key=lambda e: e.at)
    assert [e.get("tempo") for e in partial[:6]] == [1, 2, 3, 4, 5, 1]
    assert all(e.get("pace") == "WARMUP" for e in partial[:TEMPO_MIN])
    assert [e.get("pace") for e in partial[TEMPO_MIN:TEMPO_MIN + 5]] == ["FAST", "NORMAL", "NORMAL", "SLOW", "SLOW"]
    f = got["VOID_FILLED.U.197.v190"]
    assert f.get("tempo") == 197 - partial[-1].at and f.get("pace") == "WARMUP"  # since its void's last event


def test_a_fast_return_is_grammatical():
    assert qe("REVISIT[pace=FAST]") == (Clause("pace", "==", "FAST"),)
    ch = parse(F.with_time(synth.garch(3000, seed=4), 900, MONDAY))
    rev = ch.of("REVISIT")
    z = {e.id: e for e in ch.of("ZONE")}
    for r in rev:
        prev = [e.at for e in ch.entities if e.get("zone") == r.get("zone") and e.type in
                ("REVISIT", "REJECT_PATH") and e.at < r.at]
        assert r.get("tempo") == r.at - (max(prev) if prev else z[r.get("zone")].known_at)
    assert {r.get("pace") for r in rev} == {"FAST", "NORMAL", "SLOW", "WARMUP"}
