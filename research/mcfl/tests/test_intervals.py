"""Time core item 2: Allen's interval relations, on the bar clock and the wall clock, and as clause
operators in productions (IN_WINDOW: `REVISIT DURING SESSION[LONDON]`)."""
from __future__ import annotations

import itertools

import fixtures as F
import pytest
from mcfl import synth
from mcfl.grammar import OPS
from mcfl.intervals import ALLEN, INSIDE, INVERSE, allen, relate
from mcfl.parse import parse


def test_exactly_one_relation_and_its_inverse():
    pts = range(6)
    seen = set()
    for a, b, c, d in itertools.product(pts, pts, pts, pts):
        if not (a < b and c < d):
            continue
        r = allen((a, b), (c, d))
        assert sum(OPS[k]((a, b), (c, d)) for k in ALLEN) == 1, (a, b, c, d)
        assert allen((c, d), (a, b)) == INVERSE[r]
        seen.add(r)
    assert seen == set(ALLEN)


@pytest.mark.parametrize(("x", "y", "rel"), [
    ((0, 2), (3, 5), "BEFORE"), ((0, 3), (3, 5), "MEETS"), ((0, 4), (3, 6), "OVERLAPS"),
    ((3, 4), (3, 6), "STARTS"), ((4, 5), (3, 6), "DURING"), ((4, 6), (3, 6), "FINISHES"), ((3, 6), (3, 6), "EQUALS"),
    ((3, 6), (4, 5), "CONTAINS"), ((5, 9), (0, 5), "MET_BY")])
def test_named_cases(x, y, rel):
    assert allen(x, y) == rel
    assert OPS["WITHIN"](x, y) == (rel in INSIDE)
    assert OPS["HOLDS"](y, x) == (rel in INSIDE)


@pytest.fixture(scope="module")
def chart():
    df = F.with_calendar(synth.ticks(synth.garch(2500, seed=51), seed=52), 900, F.WINTER_MONDAY, "fx")
    return df, parse(df)


def test_bar_clock_and_wall_clock_differ_across_a_weekend(chart):
    df, ch = chart
    ts = df["ts"].to_numpy()
    fri = next(i for i in range(len(ts) - 1) if ts[i + 1] - ts[i] > 900)
    c = {e.at: e for e in ch.of("CANDLE")}
    assert relate(c[fri], c[fri + 1], "bar") == "MEETS"  # consecutive bars
    assert relate(c[fri], c[fri + 1], "time") == "BEFORE"  # two days apart
    assert relate(c[fri + 1], c[fri + 2], "time") == "MEETS"
    w = ch.of("WINDOW")[5]
    assert relate(c[w.at], w, "bar") is None  # an open window has no last bar
    assert relate(c[w.at], w, "time") in INSIDE


def test_in_window_is_the_session_of_the_revisit(chart):
    _, ch = chart
    ids = ch.by_id()
    cand = {e.at: e for e in ch.of("CANDLE")}
    got = {e.get("of"): e for e in ch.of("IN_WINDOW") if e.get("kind") == "SESSION"}
    revs = ch.of("REVISIT")
    assert len(revs) > 50
    for r in revs:
        e = got.get(r.id)
        assert e is not None, r.id  # every bar is in a session: every revisit is in one
        w = ids[e.get("window")]
        assert w.get("name") == cand[r.at].get("session") == e.get("name")
        assert e.get("rel") in INSIDE and e.get("rel") == relate(r, w, "time")
        assert e.dir is r.dir and e.at == r.at and e.known_at == r.known_at
    london = [e for e in got.values() if e.get("name") == "LONDON"]  # `REVISIT DURING SESSION[LONDON]`
    assert london and all(cand[e.at].get("session") == "LONDON" for e in london)


def test_killzone_and_macro_rows(chart):
    _, ch = chart
    ids = ch.by_id()
    rows = {}
    for e in ch.of("IN_WINDOW"):
        rows.setdefault(e.get("kind"), []).append(e)
        w = ids[e.get("window")]
        lo, hi = w.time.start_ts, w.time.end_ts
        ev = ids[e.get("of")]
        assert lo <= ev.time.start_ts and ev.time.end_ts <= hi
        assert e.get("of_type") == {"SESSION": "REVISIT", "KILLZONE": "SESSION_EXTREME_TAKEN",
                                    "MACRO": "POOL_TAKEN"}[e.get("kind")]
    assert set(rows) == {"SESSION", "KILLZONE", "MACRO"}
    # these events are their own bar: one whose bar lies in a killzone (15-minute bars inside whole
    # hours) has its row, and one whose bar does not, none
    kz = {e.get("of") for e in rows["KILLZONE"]}
    mac = {e.get("of") for e in rows["MACRO"]}
    cand = {e.at: e for e in ch.of("CANDLE")}
    for x in ch.of("SESSION_EXTREME_TAKEN"):
        assert x.time.start == x.time.end == x.at
        assert (x.id in kz) == (cand[x.at].get("killzone") != "NONE")
    for x in ch.of("POOL_TAKEN"):
        assert x.time.start == x.time.end == x.at
        if x.id in mac:
            assert cand[x.at].get("macro") != "NONE"
