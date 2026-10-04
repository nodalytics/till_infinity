"""v2 item 2: compression and expansion words - NR4, NR7, WR7 and OVERLAP as L1 qualifiers, and
BALANCE / IMBALANCE runs as L2 events."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import candles, synth
from mcfl.core import Dir
from mcfl.grammar import BALANCE_MIN, IMBALANCE_MAX, WORDS2, Clause, Word, q, word_mask
from mcfl.parse import flip, parse


def B(o, h, l, c):
    return dict(open=o, high=h, low=l, close=c, volume=1.0)


def _table(rows):
    T = candles.table(pd.DataFrame(rows))
    candles.compression(T)
    return T


def test_narrow_and_wide_ranges():
    ranges = [1.0, 0.9, 0.8, 0.7, 0.75, 0.6, 2.0, 0.65, 0.5]
    T = _table([B(100, 100 + r / 2, 100 - r / 2, 100) for r in ranges])
    assert list(np.flatnonzero(T["NR4"])) == [3, 5, 8]  # strictly narrower than the 3 before
    assert list(np.flatnonzero(T["NR7"])) == [8]  # bar 6 is not (bar 6 is 2.0); bar 8 is the narrowest of 2..8
    assert list(np.flatnonzero(T["WR7"])) == [6]
    ties = _table([B(100, 100.5, 99.5, 100)] * 8)
    assert not ties["NR4"].any() and not ties["WR7"].any()  # equal ranges are neither


def test_overlap():
    T = _table([B(100, 101, 99, 100), B(100, 102, 100, 101), B(101, 101.5, 100.5, 101), B(101, 104, 102, 103),
                B(103, 103, 103, 103)])
    assert np.isnan(T["overlap"][0])
    assert T["overlap"][1:4].tolist() == [0.5, 1.0, 0.0] and T["overlap"][4] == 1.0  # a zero-range bar inside


def test_qualifiers():
    assert q("CANDLE[NR7, not WR7, overlap≥0.75]", 0) == (
        Clause("0.NR7", "==", True), Clause("0.WR7", "==", False), Clause("0.overlap", ">=", 0.75))
    T = _table([B(100, 100 + r / 2, 100 - r / 2, 100) for r in [1.0, 0.9, 0.8, 0.7, 0.75, 0.6, 2.0, 0.65, 0.5]])
    assert list(np.flatnonzero(word_mask(Word("X", (0,), q("CANDLE[NR4]", 0)), T))) == [3, 5, 8]


BAL = [B(100, 101, 99, 100), B(100, 101, 99.2, 100.5), B(100.5, 101, 99.3, 100), B(100, 100.9, 99.4, 100.2),
       B(100.2, 100.8, 99.5, 100.1)]
IMB = [B(100, 101, 99, 100.8), B(100.8, 102, 100.8, 101.9), B(101.9, 103, 101.9, 102.9),
       B(102.9, 104, 102.9, 103.9), B(103.9, 105, 103.9, 104.9)]


def _ev(rows, word):
    from mcfl.grammar import frames, words
    T = _table(rows)
    cid, rid = candles.ids(T)
    return [(e.id, e.known_at, e.parts) for e in words(T, cid, rid, table_={word: WORDS2[word]}, fr=frames(T))]


def test_balance_fires_once_per_run_without_direction():
    got = _ev(BAL, "BALANCE")
    assert [(i, k) for i, k, _ in got] == [("BALANCE.N.3", 3)]  # bars 1..3 overlap >= 0.75; bar 4 continues
    assert got[0][2] == ("CANDLE.U.1", "CANDLE.D.2", "CANDLE.U.3", "BAR_RELATION.N.1", "BAR_RELATION.N.2",
                         "BAR_RELATION.N.3")
    loose = [BAL[0], BAL[1], B(100.5, 101.5, 99.6, 101.2), BAL[3], BAL[4]]  # bar 2: overlap 0.74
    assert _ev(loose, "BALANCE") == []


def test_imbalance_and_its_flip():
    assert [(i, k) for i, k, _ in _ev(IMB, "IMBALANCE")] == [("IMBALANCE.U.3", 3)]
    df = pd.DataFrame(IMB)
    ch = parse(flip(df))
    assert [e.id for e in ch.of("IMBALANCE")] == ["IMBALANCE.D.3"]
    over = [IMB[0], IMB[1], B(101.9, 103, 101.5, 102.9), IMB[3], IMB[4]]  # bar 2 overlaps 0.27 of itself
    assert "IMBALANCE.U.3" not in [i for i, _, _ in _ev(over, "IMBALANCE")]


@pytest.mark.parametrize("seed", [0, 1])
def test_on_walks(seed):
    df = synth.garch(3000, seed=seed)
    ch = parse(df)
    rel = {e.at: e for e in ch.of("BAR_RELATION")}
    for e in ch.of("BALANCE"):
        assert e.dir is Dir.NONE and all(rel[t].get("overlap") >= BALANCE_MIN for t in range(e.at - 2, e.at + 1))
    for e in ch.of("IMBALANCE"):
        want = "HH" if e.dir is Dir.UP else "LL"
        assert all(rel[t].get("overlap") <= IMBALANCE_MAX and rel[t].get("rel") == want for t in range(e.at - 2, e.at + 1))
    c = {e.at: e for e in ch.of("CANDLE")}
    rng = (df["high"] - df["low"]).to_numpy()
    for t in range(10, 3000, 37):
        assert c[t].get("NR7") == bool((rng[t] < rng[t - 6:t]).all())


def test_bar_word_text():
    from mcfl.serialise import bar_words
    ch = parse(pd.DataFrame([B(100, 100 + r / 2, 100 - r / 2, 100) for r in [1.0, 0.9, 0.8, 0.7, 0.75, 0.6, 2.0]]))
    ws = bar_words(ch, v2=True)
    assert ws[3].endswith(" #NR4,ov1.00") and ws[6].endswith(" #WR7,ov0.30") and " #" not in bar_words(ch)[3]
