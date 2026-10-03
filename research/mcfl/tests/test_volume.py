"""v2 item 3: volume - a fuzzy VOLUME class, EFFORT_RESULT against the size class, and TAKER_SKEW."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import candles, synth
from mcfl.grammar import Clause, q
from mcfl.parse import flip, parse
from mcfl.volume import effort_of


@pytest.mark.parametrize(("vol", "size", "want"), [
    ("LARGE", "SMALL", "ABSORPTION"), ("EXTREMELY_LARGE", "VERY_SMALL", "ABSORPTION"), ("VERY_LARGE", "NONE", "ABSORPTION"),
    ("SMALL", "LARGE", "EASE"), ("VERY_SMALL", "EXTREMELY_LARGE", "EASE"),
    ("LARGE", "LARGE", "AGREE"), ("SMALL", "VERY_SMALL", "AGREE"),
    ("MEDIUM", "LARGE", "NEUTRAL"), ("LARGE", "MEDIUM", "NEUTRAL"), ("MEDIUM", "MEDIUM", "NEUTRAL"),
    ("WARMUP", "LARGE", "WARMUP"), ("LARGE", "WARMUP", "WARMUP")])
def test_effort_against_result(vol, size, want):
    assert effort_of(vol, size) == want


def _bars(vols, closes=None):
    closes = closes or [100.0, 100.5] * (len(vols) // 2) + [100.0] * (len(vols) % 2)
    return F.bars(closes).assign(volume=np.asarray(vols, float))


def test_volume_class_and_absorption_on_bars():
    vols = [100.0] * 15 + [90.0, 110.0] * 5 + [400.0]
    ch = parse(_bars(vols))
    c = ch.of("CANDLE")
    assert c[0].get("volume_class") == "WARMUP" and c[14].get("volume_class") == "MEDIUM"  # a flat window: s = 0
    assert c[-1].get("volume_class") == "EXTREMELY_LARGE"
    # the warm-up's ranges are all 0.75 (s = 0: MEDIUM), so a huge volume is not ABSORPTION here ...
    assert c[-1].get("effort") == "NEUTRAL"
    # ... but on a bar that also shrinks to a sliver it is
    df = _bars(vols)
    df.loc[len(df) - 1, ["open", "high", "low", "close"]] = [100.0, 100.1, 99.95, 100.05]
    assert parse(df).of("CANDLE")[-1].get("effort") == "ABSORPTION"
    from mcfl.serialise import bar_words
    assert "v:XL,ABS" in bar_words(parse(df), v2=True)[-1]


def test_no_volume_is_warmup():
    df = F.bars(F.ZONE_UP).drop(columns="volume")
    c = parse(df).of("CANDLE")
    assert {e.get("volume_class") for e in c} == {"WARMUP"} and {e.get("effort") for e in c} == {"WARMUP"}


def test_taker_skew_and_its_flip():
    df = synth.ticks(synth.garch(800, seed=2), seed=3)
    a, b = parse(df), parse(flip(df))
    ca, cb = a.of("CANDLE"), b.of("CANDLE")
    v, buy = df["volume"].to_numpy(), df["taker_buy_volume"].to_numpy()
    assert ca[100].get("taker_skew") == pytest.approx((2 * buy[100] - v[100]) / v[100])
    for x, y in zip(ca, cb):
        assert y.get("taker_skew") == -x.get("taker_skew") or (x.get("taker_skew") is None and y.get("taker_skew") is None)
        assert y.get("taker") == {"BUY": "SELL", "SELL": "BUY"}.get(x.get("taker"), x.get("taker"))
        assert y.get("volume_class") == x.get("volume_class") and y.get("effort") == x.get("effort")
    assert {"BUY", "SELL", "BALANCED"} <= {e.get("taker") for e in ca}


def test_qualifiers():
    assert q("CANDLE[vol≥LARGE, effort=ABSORPTION, taker=BUY]", 0) == (
        Clause("0.volume_class", "in", frozenset({"LARGE", "VERY_LARGE", "EXTREMELY_LARGE"})),
        Clause("0.effort", "==", "ABSORPTION"), Clause("0.taker", "==", "BUY"))
    T = candles.table(synth.ticks(synth.walk(500, seed=1), seed=2))
    from mcfl import volume
    from mcfl.grammar import Word, word_mask
    volume.columns(T, synth.ticks(synth.walk(500, seed=1), seed=2))
    got = np.flatnonzero(word_mask(Word("X", (0,), q("CANDLE[vol≥LARGE, effort=AGREE]", 0)), T))
    want = np.flatnonzero(np.isin(T["volume_class"], ["LARGE", "VERY_LARGE", "EXTREMELY_LARGE"]) & (T["effort"] == "AGREE"))
    assert len(want) > 20 and list(got) == list(want)
