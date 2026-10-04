"""v2 item 9: FOCuS and CUSUM changepoints as events - reproducing the research detectors exactly,
`at` the change's start and `known_at` the fire, causal, flip-symmetric (CUSUM under the log-price
flip it is defined by), and usable in a production (FOCUS_ZONE)."""
from __future__ import annotations

import sys
from pathlib import Path

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import synth
from mcfl.changepoints import FOCUS_SENSITIVE, ORIGIN_BARS, threshold
from mcfl.core import Dir
from mcfl.parse import flip, parse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ideas"))
import prims as P  # noqa: E402
from survivors import cusum  # noqa: E402

T0 = 1_700_006_400 - 1_700_006_400 % 86400


def _df(kind, seed, n=3000, sec=900):
    df = {"walk": synth.walk, "garch": synth.garch, "trend": synth.trend}[kind](n, seed=seed)
    return F.with_time(df, sec, T0)


def test_threshold_is_zone_events():
    assert threshold(3600) == 12.0 and threshold(900) == pytest.approx(12 + 3 * np.log(4))
    assert threshold(60) == max(12 + 3 * np.log(60), 3.0) and threshold(86400) == 3.0


@pytest.mark.parametrize(("kind", "seed"), [("walk", 1), ("garch", 2), ("trend", 3)])
def test_focus_is_the_research_detector(kind, seed):
    """zone_events' own lines: rr, scale, th; prims.focus_series up and down, at 12 + 3 ln(3600/sec) and 6."""
    df = _df(kind, seed)
    ch = parse(df, changepoints=True)
    c = df["close"].to_numpy()
    rr = np.r_[0.0, np.diff(c)]
    scale = pd.Series(np.abs(rr)).ewm(span=100).mean().shift(1).to_numpy() * np.sqrt(np.pi / 2)
    th = max(12.0 + 3.0 * np.log(3600.0 / 900), 3.0)
    for kind_, t in (("FOCUS", th), ("FOCUS6", FOCUS_SENSITIVE)):
        want = set()
        for d, up in ((Dir.UP, True), (Dir.DOWN, False)):
            fired, at = P.focus_series(rr, scale, t, up)
            want |= {(d, int(at[i]), int(i)) for i in np.flatnonzero(fired)}
        got = {(e.dir, e.at, e.known_at) for e in ch.of(kind_)}
        assert got == want
    assert ch.of("FOCUS6")


@pytest.mark.parametrize(("kind", "seed"), [("walk", 1), ("garch", 2), ("trend", 3)])
def test_cusum_is_survivors_cusum(kind, seed):
    df = _df(kind, seed)
    ch = parse(df, changepoints=True)
    cs = cusum(df, P.atr(df, 14), k=0.5, h=5.0)
    want = {(Dir.of(int(s)), int(i)) for i, s in zip(cs["i"], cs["side"])}
    assert {(e.dir, e.at) for e in ch.of("CUSUM_IGNITION")} == want and want
    assert all(e.known_at == e.at for e in ch.of("CUSUM_IGNITION"))


def test_known_at_is_the_fire_and_at_the_start():
    df = _df("trend", 3)
    ch = parse(df, changepoints=True)
    for e in ch.of("FOCUS", "FOCUS6"):
        assert e.known_at - e.at == e.get("lag") >= 0
        assert e.parts[0] == ch.of("CANDLE")[e.at].id and len(e.parts) == e.get("lag") + 1


def test_changepoints_are_causal():
    df = _df("trend", 3, n=1200)
    full = parse(df, changepoints=True)
    ents = [e for e in full.entities if e.type in ("FOCUS", "FOCUS6", "CUSUM_IGNITION", "FOCUS_ZONE")]
    assert len({e.type for e in ents}) >= 2
    for T in sorted({e.known_at for e in ents} | {e.known_at - 1 for e in ents} | set(range(150, 1200, 97))):
        cut = parse(df.iloc[:T + 1], changepoints=True)
        want = {e for e in full.entities if e.known_at <= T}
        assert set(cut.entities) == want, T


def test_flip():
    df = _df("garch", 4)
    a, b = parse(df, changepoints=True), parse(flip(df), changepoints=True)
    for k in ("FOCUS", "FOCUS6"):
        assert {(e.dir.flip(), e.at, e.known_at) for e in a.of(k)} == {(e.dir, e.at, e.known_at) for e in b.of(k)}
    # CUSUM reads log returns: its mirror is the chart with prices inverted (the log-price flip)
    inv = df.assign(open=1 / df["open"], close=1 / df["close"], high=1 / df["low"], low=1 / df["high"])
    c = parse(inv, changepoints=True)
    assert {(e.dir.flip(), e.at) for e in a.of("CUSUM_IGNITION")} == {(e.dir, e.at) for e in c.of("CUSUM_IGNITION")}
    assert a.of("CUSUM_IGNITION")


def test_focus_zone_production():
    found = 0
    for seed in range(6):
        ch = parse(_df("trend", seed, n=3000), changepoints=True)
        ids = ch.by_id()
        for fz in ch.of("FOCUS_ZONE"):
            z, f = (ids[p] for p in fz.parts)
            assert z.type == "ZONE" and f.type in ("FOCUS", "FOCUS6") and z.dir == f.dir == fz.dir
            assert abs(f.at - z.at) <= ORIGIN_BARS and f.known_at <= z.known_at == fz.known_at
            found += 1
        for z in ch.of("ZONE"):  # and every such pair is found
            for f in ch.of("FOCUS6"):
                if f.dir == z.dir and abs(f.at - z.at) <= ORIGIN_BARS and f.known_at <= z.known_at:
                    assert any(fz.parts == (z.id, f.id) for fz in ch.of("FOCUS_ZONE"))
    assert found > 0
