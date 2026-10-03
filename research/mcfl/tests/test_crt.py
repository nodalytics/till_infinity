"""v2 item 12: candle range theory - PURGE from the v1 relation words, DISTRIBUTION within N candles
with the mid's timing, and CRT3 = RANGE_CANDLE PURGE DISTRIBUTION."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pytest
from mcfl import synth
from mcfl.core import Dir
from mcfl.crt import CRT_N
from mcfl.parse import flip, parse

RANGE = (100.5, 101.0, 99.0, 100.5)  # the range candle: 99 .. 101, mid 100
PURGE = (100.5, 101.5, 99.8, 100.2)  # above 101, closing back inside at 100.2
K = len(F.FINE)  # the range candle's bar


def _crt(rows):
    return parse(F.after(F.FINE, [RANGE] + rows))


def test_purge_distribution_crt3():
    ch = _crt([PURGE, (100.2, 100.3, 99.5, 99.6), (99.6, 99.7, 98.9, 99.0)])
    p = ch.by_id()[f"PURGE.U.{K + 1}"]
    assert p.parts == (f"CANDLE.N.{K}", f"CANDLE.D.{K + 1}", f"BAR_RELATION.U.{K + 1}") and p.known_at == K + 1
    assert (p.get("upper_edge"), p.get("lower_edge"), p.get("range_mid")) == (101.0, 99.0, 100.0)
    assert p.get("close_loc") == pytest.approx(0.4) and p.get("depth_atr") > 0
    d = ch.by_id()[f"DISTRIBUTION.D.{K + 3}.p{K + 1}"]
    assert (d.get("bars"), d.get("mid_bars"), d.get("mid_same_bar"), d.known_at) == (2, 1, False, K + 3)
    (c,) = [e for e in ch.of("CRT3") if e.get("purge") == p.id]
    assert c.id == f"CRT3.D.{K}" and c.dir is Dir.DOWN and c.known_at == K + 3
    assert c.parts == (ch.of("CANDLE")[K].id, p.id, d.id)


def test_no_purge_when_the_close_stays_above():
    ch = _crt([(100.5, 101.5, 99.8, 101.2), (101.2, 101.3, 98.5, 98.6)])
    assert f"PURGE.U.{K + 1}" not in ch.by_id()


def test_no_distribution_after_n_candles():
    rows = [PURGE] + [(100.2, 100.4, 99.6, 100.0)] * CRT_N + [(100.0, 100.1, 98.0, 98.2)]
    ch = _crt(rows)
    assert f"PURGE.U.{K + 1}" in ch.by_id()
    assert not [d for d in ch.of("DISTRIBUTION") if d.get("purge") == f"PURGE.U.{K + 1}"]


def test_flip_twin():
    df = F.after(F.FINE, [RANGE, PURGE, (100.2, 100.3, 99.5, 99.6), (99.6, 99.7, 98.9, 99.0)])
    ch = parse(flip(df))
    p = ch.by_id()[f"PURGE.D.{K + 1}"]
    assert (p.get("upper_edge"), p.get("lower_edge")) == (-99.0, -101.0) and p.get("close_loc") == pytest.approx(0.4)
    assert f"CRT3.U.{K}" in ch.by_id()


@pytest.mark.parametrize("seed", [0, 1])
def test_on_walks(seed):
    df = synth.garch(3000, seed=seed)
    ch = parse(df)
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    ids = ch.by_id()
    dist = {d.get("purge"): d for d in ch.of("DISTRIBUTION")}
    for p in ch.of("PURGE"):
        t = p.at
        if p.dir is Dir.UP:
            assert h[t] > h[t - 1] and l[t - 1] - 0.5 < c[t] <= h[t - 1] + 0.5
            seg = l[t + 1:t + CRT_N + 1] <= l[t - 1]
        else:
            seg = h[t + 1:t + CRT_N + 1] >= h[t - 1]
        hit = np.flatnonzero(seg)
        if len(hit):
            assert dist[p.id].at == t + 1 + int(hit[0])
        else:
            assert p.id not in dist
    assert len(ch.of("CRT3")) == len(dist) > 100
    for x in ch.of("CRT3"):
        assert ids[x.parts[2]].dir is x.dir is ids[x.parts[1]].dir.flip()
