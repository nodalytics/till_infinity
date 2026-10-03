"""A BREAK knows how old the structure it broke was. LEG_MAX (20) caps how long the breaking move
may take, from origin to break; the level broken can be any age."""
from __future__ import annotations

import fixtures as F
import pytest
from mcfl import synth
from mcfl.parse import LEG_MAX, parse
from mcfl.serialise import tokens

FALL3 = [101.5, 101.0, 100.5]
FLAT = [100.0, 100.5]  # equal highs and lows: no swings while price waits under the old high


def _break(closes):
    (b,) = [e for e in parse(F.bars(closes)).of("BREAK") if e.dir.value == "UP"]
    return b


def test_a_level_ten_bars_old():
    b = _break(F.ZONE_UP)
    assert b.get("ref") == f"EXTREME.U.{F.PEAK_BAR}"
    assert (b.get("ref_age"), b.get("ref_known_age"), b.get("swings_taken"), b.get("max_ref_age"),
            b.get("leg_bars")) == (10, 7, 1, 10, 4)
    assert b.get("leg_bars") == b.force.duration


def test_a_level_two_hundred_bars_old():
    closes = F.WARMUP + F.RISE + FALL3 + FLAT * 95 + [100.0, 99.5, 99.0] + [99.5, 100.5, 102.0, 103.0, 103.5]
    b = _break(closes)
    assert b.get("ref") == f"EXTREME.U.{F.PEAK_BAR}"
    assert (b.get("ref_age"), b.get("ref_known_age"), b.get("swings_taken"), b.get("max_ref_age"),
            b.get("leg_bars")) == (200, 197, 1, 200, 4)
    assert b.get("leg_bars") <= LEG_MAX < b.get("ref_age")  # the cap is on the move, not the level
    assert "BREAK↑[force:strong,age:old,took:1]" in tokens(parse(F.bars(closes)), bins=True)


def test_one_close_takes_a_young_and_an_old_level():
    """A younger, lower swing high forms just before the origin; one bar closes through both. The
    reference is the younger (the last swing known at the origin); the old one is counted too."""
    closes = (F.WARMUP + F.RISE + FALL3 + FLAT * 94 + [100.0] + [101.0] + [100.5, 100.0, 99.5, 99.0]
              + [99.5, 100.5, 103.0, 103.5])
    b = _break(closes)
    bump = len(F.WARMUP + F.RISE + FALL3) + 2 * 94 + 1
    assert b.get("ref") == f"EXTREME.U.{bump}"
    assert (b.get("ref_age"), b.get("swings_taken"), b.get("max_ref_age")) == (b.at - bump, 2, 200)
    assert "took:2" in [t for t in tokens(parse(F.bars(closes)), bins=True) if t.startswith("BREAK↑")][0]


@pytest.mark.parametrize("seed", [0, 3])
def test_break_age_attributes_hold_on_walks(seed):
    ch = parse(synth.walk(3000, seed=seed))
    ids = ch.by_id()
    for b in ch.of("BREAK"):
        ref = ids[b.get("ref")]
        assert b.get("ref_age") == b.at - ref.at and b.get("ref_known_age") == b.at - ref.known_at > 0
        assert b.get("leg_bars") == b.at - ids[b.get("origin")].at <= LEG_MAX
        if b.get("swings_taken"):
            assert b.get("max_ref_age") >= 3 + b.get("swings_taken") - 1
        else:
            assert b.get("max_ref_age") is None
