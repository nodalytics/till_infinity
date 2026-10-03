"""The zone state machine on hand-built bars. The zone is fixtures.ZONE_UP: band 98.75-99.5,
origin ATR exactly 1, qualified at bar 32."""
from __future__ import annotations

import fixtures as F
from mcfl.lifecycle import ACCEPT_BARS, ZONE_EXPIRE
from mcfl.parse import parse

Z = f"ZONE.U.{F.ORIGIN_BAR}"
LIFE = ("REVISIT", "REJECT_PATH", "ACCEPT", "FAIL", "EXPIRE")  # v1: the candle REJECT is not a state event
DOWN_TO_ZONE = [103.5, 102.5, 101.5, 100.5, 99.5]  # the last bar's low, 99.25, reaches the band


def _life(closes):
    ch = parse(F.bars(F.ZONE_UP + closes))
    ev = [e for e in ch.entities if e.get("zone") == Z and e.type in LIFE]
    tr = [t for t in ch.transitions if t.zone == Z]
    return ch, ev, tr, dict(ch.states)[Z]


def test_revisit_reject_revisit_fail():
    start = len(F.ZONE_UP)
    ch, ev, tr, state = _life(DOWN_TO_ZONE + [100.5, 99.5, 98.5])
    assert [(e.type, e.at) for e in ev] == [
        ("REVISIT", start + 4),  # low 99.25 <= near 99.5
        ("REJECT_PATH", start + 5),  # high 100.75 >= near + 1 ATR
        ("REVISIT", start + 6),
        ("FAIL", start + 7),  # close 98.5 < far 98.75 - 0.1
    ]
    assert [e.get("count") for e in ev if e.type == "REVISIT"] == [1, 2]
    assert [(t.src, t.dst) for t in tr] == [
        ("FORMING", "QUALIFIED"), ("QUALIFIED", "REVISITED"), ("REVISITED", "REJECTED"),
        ("REJECTED", "REVISITED"), ("REVISITED", "FAILED")]
    assert state == "FAILED"
    assert all(e.known_at == e.at for e in ev)
    assert all(t.known_at >= t.at for t in tr)
    rels = {(r.kind, r.src) for r in ch.relations if r.dst == Z}
    assert ("INVALIDATE", f"FAIL.U.{start + 7}.z{F.ORIGIN_BAR}") in rels
    assert ("TOUCH", f"REVISIT.U.{start + 4}.z{F.ORIGIN_BAR}") in rels


def test_accept_after_closes_inside():
    start = len(F.ZONE_UP)
    _, ev, _, state = _life(DOWN_TO_ZONE + [99.2, 99.0, 99.3])
    assert [e.type for e in ev] == ["REVISIT", "ACCEPT"]
    assert ev[-1].at == start + 4 + ACCEPT_BARS - 1  # the revisit bar's close counts
    assert state == "ACCEPTED"


def test_still_revisited_when_nothing_resolves():
    _, ev, _, state = _life(DOWN_TO_ZONE + [100.0])  # one close inside, then above the band
    assert [e.type for e in ev] == ["REVISIT"]
    assert state == "REVISITED"


def test_expires():
    _, ev, tr, state = _life([104.0, 104.5] * 270)
    assert [e.type for e in ev] == ["EXPIRE"]
    assert ev[0].at == F.ORIGIN_BAR + 4 + ZONE_EXPIRE
    assert tr[-1].dst == "EXPIRED" and state == "EXPIRED"


def test_qualified_when_untouched():
    _, ev, _, state = _life([104.0, 104.5] * 5)
    assert ev == [] and state == "QUALIFIED"
