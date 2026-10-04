"""Time core item 7: several clocks - bar, wall-clock, trading, volume and event time - the same
sentence read on each, and the parse run unchanged on volume bars and tick bars."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import synth
from mcfl.clocks import CLOCKS, event_clock, in_source, reading, tick_bars, volume_bars
from mcfl.parse import parse
from mcfl.serialise import sentence


@pytest.fixture(scope="module")
def src():
    return F.with_calendar(synth.ticks(synth.garch(3000, seed=91), seed=92), 900, F.WINTER_MONDAY, "fx")


def test_volume_bars(src):
    size = float(src["volume"].median() * 4)
    vb = volume_bars(src, size)
    assert (vb["volume"] >= size).all() and len(vb) > 400
    assert (vb["src_first"].iloc[1:].to_numpy() == vb["src_last"].iloc[:-1].to_numpy() + 1).all()
    for k in range(0, len(vb), 53):
        a, b = vb["src_first"].iloc[k], vb["src_last"].iloc[k]
        seg = src.iloc[a:b + 1]
        assert (vb["open"].iloc[k], vb["high"].iloc[k], vb["low"].iloc[k], vb["close"].iloc[k]) == (
            seg["open"].iloc[0], seg["high"].max(), seg["low"].min(), seg["close"].iloc[-1])
        assert vb["ts"].iloc[k] == seg["ts"].iloc[0] and vb["close_ts"].iloc[k] == seg["ts"].iloc[-1] + 900
        assert vb["volume"].iloc[k] - seg["volume"].iloc[-1] < size  # it closed on the bar that reached the size
    # a prefix of the source gives a prefix of the volume bars: each is known at its last source bar
    for T in (100, 1234, 2999):
        cut = volume_bars(src.iloc[:T + 1], size)
        assert cut.equals(vb[vb["src_last"] <= T].reset_index(drop=True))


def test_the_parse_runs_unchanged_on_volume_bars(src):
    size = float(src["volume"].median() * 4)
    vb = volume_bars(src, size)
    ch = parse(vb)
    assert ch.of("ZONE") and ch.of("HTF_CLOSE") and ch.of("WINDOW")
    c = ch.clock
    assert (c.length == (vb["close_ts"] - vb["ts"]).to_numpy()).all()  # the bars carry their closes
    for e in ch.entities[::401]:
        assert e.time.known_at_ts == vb["close_ts"].iloc[e.known_at]
    # causal in source time: cut the source at T, and what is known is what the full parse knew by T
    full = parse(vb)
    for T in (900, 2100):
        cut_vb = volume_bars(src.iloc[:T + 1], size)
        cut = parse(cut_vb)
        assert set(cut.entities) == {e for e in full.entities if in_source(vb, e) <= T}


def test_tick_bars():
    rng = np.random.default_rng(3)
    t = 1_704_067_200 + np.cumsum(rng.exponential(2.0, 5000))
    ticks = pd.DataFrame({"ts": t, "bid": 100 + np.cumsum(rng.normal(0, 0.01, 5000))})
    ticks["ask"] = ticks["bid"] + 0.02
    tb = tick_bars(ticks, 50)
    assert len(tb) == 100 and (tb["close_ts"] > tb["ts"]).all()
    mid = (ticks["bid"] + ticks["ask"]) / 2
    assert tb["close"].iloc[0] == mid.iloc[49] and tb["high"].iloc[1] == mid.iloc[50:100].max()
    ch = parse(tb)
    assert ch.clock.ts is not None and ch.of("CANDLE")


def test_the_same_sentence_on_every_clock(src):
    ch = parse(src)
    toks = {k: reading(ch, k) for k in CLOCKS}
    words = [w for _, w in toks["bar"]]
    assert all([w for _, w in toks[k]] == words for k in CLOCKS)  # one sentence ...
    for k in CLOCKS:  # ... each clock non-decreasing along it
        xs = [x for x, _ in toks[k]]
        assert all(a <= b for a, b in zip(xs, xs[1:])), k
    ents = sentence(ch)
    assert [x for x, _ in toks["bar"]] == [e.known_at for e in ents]
    assert [x for x, _ in toks["time"]] == [e.time.known_at_ts for e in ents]
    ev = event_clock(ch)
    assert ev[-1] == sum(1 for e in ch.entities if e.layer >= 2 and e.type not in
                         ("WINDOW", "WINDOW_CLOSE", "DAY_OPEN", "WEEK_OPEN", "MONTH_OPEN", "HTF_CLOSE"))
    # over a weekend the wall clock jumps, the trading clock and the bar clock do not
    gap = int(np.flatnonzero(np.diff(src["ts"].to_numpy()) > 900)[0])
    c = ch.clock
    assert c.at("time")[gap + 1] - c.at("time")[gap] == 49 * 3600 + 900
    assert c.at("trade")[gap + 1] - c.at("trade")[gap] == 900
