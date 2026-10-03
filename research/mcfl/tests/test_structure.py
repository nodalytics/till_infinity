"""v2 items 1 and 11: swing labels, the STRUCTURE state, STRUCTURE_SHIFT, a BREAK's vs_structure
(WITH is the trader's BOS) and CHARACTER_SHIFT (CHoCH)."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pytest
from mcfl import synth
from mcfl.core import Dir, Entity, attrs_of
from mcfl.parse import flip, parse
from mcfl.structure import SWING_EQ_ATR, labels, shifts, structure_at


def _seq(ch, *types):
    return [(e.type, e.dir.value, e.at, e.get("label") or e.get("to") or e.get("vs_structure"))
            for e in ch.entities if e.type in types]


def test_trend_then_choch_then_bos():
    ch = parse(F.bars(F.TREND_CHOCH_BOS))
    assert [e.get("label") for e in ch.of("SWING")] == ["HH", "HL", "HH", "HL", "HH", "LL", "LH", "LL", "LH"]
    assert [(e.get("from"), e.get("to"), e.known_at) for e in ch.of("STRUCTURE_SHIFT")] == [
        ("MIXED", "UP", 41), ("UP", "MIXED", 77), ("MIXED", "DOWN", 83)]
    brk = [(e.dir.value, e.at, e.get("vs_structure")) for e in ch.of("BREAK")]
    assert brk == [("UP", 31, "NONE"), ("UP", 43, "WITH"), ("UP", 55, "WITH"), ("DOWN", 67, "AGAINST"),
                   ("DOWN", 87, "WITH"), ("DOWN", 103, "WITH")]  # WITH = the trader's BOS
    (c,) = ch.of("CHARACTER_SHIFT")
    assert (c.id, c.known_at, c.get("structure")) == (f"CHARACTER_SHIFT.D.{F.CHOCH_BAR}", F.CHOCH_BAR, "UP")
    assert c.parts == (f"BREAK.D.{F.CHOCH_BAR}.o58",) and c.get("break") == c.parts[0]
    assert structure_at(ch, 76) == "UP" and structure_at(ch, 77) == "MIXED" and structure_at(ch, 90) == "DOWN"


def test_choch_flips():
    ch = parse(flip(F.bars(F.TREND_CHOCH_BOS)))
    assert [e.get("label") for e in ch.of("SWING")] == ["LL", "LH", "LL", "LH", "LL", "HH", "HL", "HH", "HL"]
    (c,) = ch.of("CHARACTER_SHIFT")
    assert c.id == f"CHARACTER_SHIFT.U.{F.CHOCH_BAR}" and c.get("structure") == "DOWN"
    assert [e.get("vs_structure") for e in ch.of("BREAK")] == ["NONE", "WITH", "WITH", "AGAINST", "WITH", "WITH"]


def test_no_choch_before_the_state_is_established():
    """HH then HL set UP with a run of one label; a one-bar collapse breaks the higher low before the
    next label is known: AGAINST, but the state was not established, so no CHoCH."""
    closes = F.WARMUP + F.zig([100.5, 103, 101.5, 104, 102.5, 106]) + [100, 99.5, 99, 98.5, 98]
    ch = parse(F.bars(closes))
    assert [(s.get("to"), s.get("run")) for s in ch.of("STRUCTURE_SHIFT")] == [("UP", 1)]  # run: labels the previous state held
    (b,) = [b for b in ch.of("BREAK") if b.dir is Dir.DOWN]
    assert (b.at, b.get("vs_structure"), b.get("structure")) == (43, "AGAINST", "UP")
    assert not ch.of("CHARACTER_SHIFT")


def _ext(d, at, price):
    return Entity(f"EXTREME.{d.letter}.{at}", "EXTREME", d, at, at + 3, attrs_of({"price": price, "swing": 3}))


def test_equal_tolerance():
    atr = np.ones(100)
    tol = SWING_EQ_ATR
    sw = labels([_ext(Dir.UP, 10, 100.0), _ext(Dir.UP, 20, 100.0 + tol), _ext(Dir.UP, 30, 100.0 + 2.5 * tol),
                 _ext(Dir.UP, 40, 100.0)], atr)
    assert [e.get("label") for e in sw] == ["EH", "HH", "LH"]
    sw = labels([_ext(Dir.DOWN, 10, 100.0), _ext(Dir.DOWN, 20, 100.0 - tol), _ext(Dir.DOWN, 30, 99.0)], atr)
    assert [e.get("label") for e in sw] == ["EL", "LL"]
    assert sw[0].parts == ("EXTREME.D.10", "EXTREME.D.20") and sw[0].known_at == 23


def test_same_bar_labels_apply_together():
    """A bar that is both a swing high and a swing low: both labels are applied, then the state is
    read once - so the order of the two cannot matter, and no transient shift is emitted."""
    atr = np.ones(100)
    ext = [_ext(Dir.UP, 10, 100.0), _ext(Dir.DOWN, 12, 95.0), _ext(Dir.UP, 30, 102.0), _ext(Dir.DOWN, 30, 96.0)]
    sh, st, cnt, _ = shifts(labels(ext, atr), 100)
    assert [(s.get("from"), s.get("to"), s.known_at, s.at) for s in sh] == [("MIXED", "UP", 33, 30)]
    assert st[32] == "MIXED" and st[33] == "UP" and cnt[33] == 2


@pytest.mark.parametrize("seed", [0, 1])
def test_labels_and_states_on_walks(seed):
    ch = parse(synth.walk(3000, seed=seed))
    ids = ch.by_id()
    for s in ch.of("SWING"):
        prev, cur = (ids[p] for p in s.parts)
        assert prev.type == cur.type == "EXTREME" and prev.dir == cur.dir == s.dir and prev.at < cur.at
        assert s.known_at == cur.known_at and s.at == cur.at
    sh = ch.of("STRUCTURE_SHIFT")
    assert all(a.get("to") == b.get("from") for a, b in zip(sh, sh[1:]))
    for b in ch.of("BREAK"):
        assert b.get("vs_structure") in ("WITH", "AGAINST", "NONE")
        assert b.get("structure") == structure_at(ch, b.at)
    for c in ch.of("CHARACTER_SHIFT"):
        brk = ids[c.parts[0]]
        assert brk.get("vs_structure") == "AGAINST" and c.known_at == brk.known_at


def test_text_forms():
    from mcfl.serialise import tokens
    ch = parse(F.bars(F.TREND_CHOCH_BOS))
    toks = tokens(ch, types=("SWING", "STRUCTURE_SHIFT", "BREAK", "CHARACTER_SHIFT"), v2=True)
    assert toks[:4] == ["BREAK↑[NONE]", "SWING↑[HH]", "SWING↓[HL]", "STRUCTURE_SHIFT↑[MIXED>UP]"]
    assert "BREAK↓[AGAINST]" in toks and toks[toks.index("BREAK↓[AGAINST]") + 1] == "CHARACTER_SHIFT↓"
    assert toks[-1] == "BREAK↓[WITH]"
