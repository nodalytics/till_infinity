"""v2 item 4: a VOID's lifecycle, UNTOUCHED -> PARTIAL -> FILLED -> INVERTED, each transition an event."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import synth
from mcfl.parse import flip, parse
from mcfl.voids import void_state

# the canonical zone's leg leaves VOID↑ at 31 (band 99.75 .. 100.25), 32 and 33 (102.25 .. 102.75)
VOID = "VOID.U.31"


def _bars(extra):
    df = F.bars(F.ZONE_UP)
    return pd.concat([df, pd.DataFrame(extra)], ignore_index=True)


def _life(ch, vid):
    return [(t.src, t.dst, t.at) for t in ch.transitions if t.zone == vid]


def test_partial_then_filled_then_inverted():
    n = len(F.ZONE_UP)
    ch = parse(_bars([dict(open=104.5, high=104.6, low=100.1, close=100.3, volume=1.0),   # into the gap
                      dict(open=100.3, high=100.5, low=99.7, close=100.0, volume=1.0),    # through it
                      dict(open=100.0, high=100.1, low=99.2, close=99.5, volume=1.0)]))   # closes below
    assert _life(ch, VOID) == [("UNTOUCHED", "PARTIAL", n), ("PARTIAL", "FILLED", n + 1), ("FILLED", "INVERTED", n + 2)]
    ids = ch.by_id()
    p, f, i = (ids[f"{k}.U.{n + j}.v31"] for j, k in enumerate(("VOID_PARTIAL", "VOID_FILLED", "VOID_INVERTED")))
    assert p.get("share") == pytest.approx(0.3) and f.get("share") == 1.0
    assert i.get("beyond_atr") > 0 and i.parts == (f"CANDLE.D.{n + 2}",) and i.known_at == n + 2
    assert [void_state(ch, VOID, t) for t in (30, 31, n - 1, n, n + 1, n + 2)] == [
        None, "UNTOUCHED", "UNTOUCHED", "PARTIAL", "FILLED", "INVERTED"]


def test_one_bar_can_make_every_transition():
    n = len(F.ZONE_UP)
    ch = parse(_bars([dict(open=104.5, high=104.6, low=99.0, close=99.2, volume=1.0)]))
    assert _life(ch, VOID) == [("UNTOUCHED", "PARTIAL", n), ("PARTIAL", "FILLED", n), ("FILLED", "INVERTED", n)]


def test_untouched_and_touching_the_edge():
    """A low exactly at the top edge has not entered the gap; one tick below has."""
    ch = parse(_bars([dict(open=104.5, high=104.6, low=102.75, close=103.0, volume=1.0)]))
    assert _life(ch, "VOID.U.33") == [] and void_state(ch, "VOID.U.33", ch.n - 1) == "UNTOUCHED"
    ch = parse(_bars([dict(open=104.5, high=104.6, low=102.74, close=103.0, volume=1.0)]))
    assert _life(ch, "VOID.U.33") == [("UNTOUCHED", "PARTIAL", ch.n - 1)]


def test_flip_twin():
    df = _bars([dict(open=104.5, high=104.6, low=99.0, close=99.2, volume=1.0)])
    ch = parse(flip(df))
    assert [(t.src, t.dst) for t in ch.transitions if t.zone == "VOID.D.31"] == [
        ("UNTOUCHED", "PARTIAL"), ("PARTIAL", "FILLED"), ("FILLED", "INVERTED")]
    assert "VOID_INVERTED.D.{}.v31".format(ch.n - 1) in ch.by_id()


@pytest.mark.parametrize("seed", [0, 1])
def test_lifecycle_on_walks(seed):
    df = synth.walk(3000, seed=seed)
    ch = parse(df)
    ids = ch.by_id()
    lo, hi, c = df["low"].to_numpy(), df["high"].to_numpy(), df["close"].to_numpy()
    n_seen = 0
    for v in ch.of("VOID"):
        tr = [t for t in ch.transitions if t.zone == v.id]
        assert [t.dst for t in tr] == ["PARTIAL", "FILLED", "INVERTED"][:len(tr)]
        assert all(t.at > v.at for t in tr) and [t.at for t in tr] == sorted(t.at for t in tr)
        b0, b1 = v.get("band")
        k = v.at
        if v.dir.value == "UP":
            want = np.flatnonzero(lo[k + 1:] < b1)
        else:
            want = np.flatnonzero(hi[k + 1:] > b0)
        assert (tr[0].at if tr else -1) == (k + 1 + int(want[0]) if len(want) else -1)
        for t in tr:
            assert ids[t.event].get("void") == v.id
        n_seen += len(tr)
    assert n_seen > 500
