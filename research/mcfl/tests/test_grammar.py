"""The grammar on hand-built bars: the canonical zone is accepted, and each way of missing it is
reported with the slot and clause that failed, not dropped."""
from __future__ import annotations

import fixtures as F
from mcfl.core import Dir
from mcfl.grammar import RULES, Clause, Rule, Slot, apply
from mcfl.parse import parse


def _fail(chart, cid):
    return [f for f in chart.failures if f.candidate == cid]


def test_canonical_zone_is_accepted():
    ch = parse(F.bars(F.ZONE_UP))
    ids = ch.by_id()
    z = ids[f"ZONE.U.{F.ORIGIN_BAR}"]
    assert [ids[p].type for p in z.parts] == ["ORIGIN", "DISPLACE", "VOID", "VOID", "BREAK"]
    brk = ids[z.parts[-1]]
    assert brk.get("ref") == f"EXTREME.U.{F.PEAK_BAR}"
    assert brk.get("level") == 102.25
    assert z.get("far") == 98.75 and z.get("near") == 99.5  # the origin bar's low and body top
    assert z.known_at == brk.at == F.ORIGIN_BAR + 4  # the chain completes on the break bar
    f = brk.force
    assert f.duration == 4 and f.efficiency == 1.0
    assert abs(f.magnitude - 4.5) < 1e-12  # high 103.25 - origin low 98.75, ATR exactly 1
    assert abs(f.penetration - 0.75) < 1e-12  # close 103 - level 102.25
    assert not _fail(ch, f"ORIGIN.U.{F.ORIGIN_BAR}")


def test_no_gap_fails_on_void():
    ch = parse(F.bars(F.NO_VOID))
    assert not any(z.dir.value == "UP" for z in ch.of("ZONE"))
    (f,) = _fail(ch, f"ORIGIN.U.{F.ORIGIN_BAR}")
    assert f.rule == "ZONE_UP" and f.slot == "void"
    assert f.known_at == ch.by_id()[f"LEG.U.{F.ORIGIN_BAR}"].known_at


def test_shallow_leg_fails_on_displace():
    ch = parse(F.bars(F.SHALLOW))
    (f,) = _fail(ch, f"ORIGIN.U.{F.SHALLOW_ORIGIN}")
    assert f.slot == "displace"
    assert any(e.type == "BREAK" and e.get("origin") == f"ORIGIN.U.{F.SHALLOW_ORIGIN}" for e in ch.entities)


def test_invalidated_leg_fails_on_break():
    ch = parse(F.bars(F.INVALIDATED))
    leg = ch.by_id()[f"LEG.U.{F.ORIGIN_BAR}"]
    assert leg.get("reason") == "INVALIDATED"
    (f,) = _fail(ch, f"ORIGIN.U.{F.ORIGIN_BAR}")
    assert f.slot == "break" and f.known_at == leg.known_at
    # the lower low it made is an origin of its own, and that one qualifies
    assert any(z.at == leg.get("end") for z in ch.of("ZONE"))


def test_every_origin_is_accounted_for():
    """An origin is a zone, a reported failure, or still forming - never silently dropped."""
    from mcfl import synth
    ch = parse(synth.walk(3000, seed=9))
    for o in ch.of("ORIGIN"):
        z = f"ZONE.{o.id.split('.', 1)[1]}"
        n = (z in ch.by_id()) + bool(_fail(ch, o.id)) + (o.id in ch.pending)
        assert n == 1, o.id
    assert ch.of("ZONE") and ch.failures


def test_rules_are_data():
    """A production rule is a table row: a stricter zone (two voids) needs no new code."""
    base = RULES["ZONE"]
    strict = Rule(head="ZONE", anchor="origin", horizon="LEG",
                  slots=tuple(Slot(s.name, s.type, 2 if s.name == "void" else s.min, s.max, s.where)
                              for s in base.slots), sequence=base.sequence)
    ch = parse(F.bars(F.ZONE_UP))
    ents = list(ch.entities)
    raw = [e for e in ents if e.type not in ("ZONE", "REVISIT", "REJECT", "ACCEPT", "FAIL", "EXPIRE")]
    built, _, _ = apply(raw, {"ZONE": strict})
    assert any(z.at == F.ORIGIN_BAR for z in built)  # the fixture has two voids on the path
    three = Rule(head="ZONE", anchor="origin", horizon="LEG",
                 slots=tuple(Slot(s.name, s.type, 3 if s.name == "void" else s.min, s.max, s.where)
                             for s in base.slots), sequence=base.sequence)
    built, failed, _ = apply(raw, {"ZONE": three})
    assert not any(z.at == F.ORIGIN_BAR and z.dir.value == "UP" for z in built)
    assert any(f.candidate == f"ORIGIN.U.{F.ORIGIN_BAR}" and f.slot == "void" for f in failed)
    assert base.bnf(Dir.UP) == \
        "ZONE_UP := ORIGIN_UP DISPLACE_UP VOID_UP+ BREAK_UP"
    assert Clause("at", "<=", ("+", "origin.at", 20)).text() == "at <= (origin.at + 20)"
