"""v2 item 7: retracement depth on every REVISIT (RETRACE) and on the pullbacks of a BREAK's leg
(PULLBACK INSIDE and AFTER), its bins, and the DAX 50% rule as one production (DAX50)."""
from __future__ import annotations

import fixtures as F
import pytest
from mcfl import synth
from mcfl.core import Dir
from mcfl.grammar import Clause, qe
from mcfl.parse import flip, parse
from mcfl.retrace import RULES, depth_bin


def test_bins():
    assert [depth_bin(x) for x in (0.0, 0.3819, 0.382, 0.5, 0.6179, 0.618, 1.0, 1.0001)] == [
        "SHALLOW", "SHALLOW", "HALF", "HALF", "HALF", "DEEP", "DEEP", "BEYOND"]


def test_entity_qualifiers():
    assert qe("PULLBACK[phase=INSIDE, depth≥0.5]") == (Clause("phase", "==", "INSIDE"), Clause("depth", ">=", 0.5))
    assert qe("PULLBACK[depth≥HALF]") == (Clause("depth_bin", "in", frozenset({"HALF", "DEEP", "BEYOND"})),)
    assert qe("RETRACE[depth<DEEP]") == (Clause("depth_bin", "in", frozenset({"SHALLOW", "HALF"})),)


def test_dax50_passes():
    ch = parse(F.bars(F.DAX_DEEP))
    (pb,) = [e for e in ch.of("PULLBACK") if e.get("phase") == "INSIDE"]
    assert (pb.at, pb.known_at, pb.get("break"), pb.get("depth_bin")) == (44, 51, "BREAK.U.51.o34", "DEEP")
    assert pb.get("depth") == pytest.approx(0.8)  # (104.75 - 100.75) / (104.75 - 99.75)
    assert pb.parts == ("BREAK.U.51.o34", "EXTREME.D.44")
    (d,) = ch.of("DAX50")
    assert (d.id, d.known_at, d.parts) == ("DAX50.U.51", 51, ("BREAK.U.51.o34", pb.id))
    assert RULES["DAX50"].bnf(Dir.UP) == "DAX50_UP := BREAK_UP PULLBACK_UP"


def test_dax50_fails_above_half():
    ch = parse(F.bars(F.DAX_SHALLOW))
    (pb,) = [e for e in ch.of("PULLBACK") if e.get("phase") == "INSIDE" and e.get("break") == "BREAK.U.49.o34"]
    assert pb.get("depth") == pytest.approx(0.4) and pb.get("depth_bin") == "HALF"
    assert not ch.of("DAX50")


def test_flip_twin():
    ch = parse(flip(F.bars(F.DAX_DEEP)))
    (d,) = ch.of("DAX50")
    assert d.id == "DAX50.D.51" and d.get("depth") == pytest.approx(0.8)


def test_retrace_on_a_revisit():
    ch = parse(F.bars(F.ZONE_UP + [103.5, 102.5, 101.5, 100.5, 99.5]))
    (r,) = ch.of("RETRACE")
    # the zone's leg: low 98.75 to the highest high before the revisit, 104.75; the revisit's low 99.25
    assert r.id == "RETRACE.U.40.z28" and r.parts == ("REVISIT.U.40.z28",) and r.known_at == 40
    assert (r.get("peak"), r.get("level")) == (104.75, 99.25)
    assert r.get("depth") == pytest.approx(5.5 / 6.0) and r.get("depth_bin") == "DEEP"


@pytest.mark.parametrize("seed", [0, 1])
def test_depths_on_walks(seed):
    df = synth.garch(3000, seed=seed)
    ch = parse(df)
    ids = ch.by_id()
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    assert ch.of("PULLBACK") and ch.of("RETRACE")
    for e in ch.of("PULLBACK"):
        b, x = (ids[p] for p in e.parts)
        assert b.type == "BREAK" and x.type == "EXTREME" and x.dir is e.dir.flip()
        p = int(b.get("origin").split(".")[2])
        if e.dir is Dir.UP:
            end = b.at if e.get("phase") == "INSIDE" else x.at
            peak, low = h[p:end + 1].max(), l[p]
            want = (peak - x.get("price")) / (peak - low)
        else:
            end = b.at if e.get("phase") == "INSIDE" else x.at
            peak, low = l[p:end + 1].min(), h[p]
            want = (x.get("price") - peak) / (low - peak)
        assert e.get("depth") == pytest.approx(want) and e.get("depth_bin") == depth_bin(e.get("depth"))
        assert (p < x.at < b.at) if e.get("phase") == "INSIDE" else (x.at > b.at)
        assert e.known_at == max(b.known_at, x.known_at)
    for d in ch.of("DAX50"):
        assert ids[d.parts[1]].get("depth") >= 0.5
