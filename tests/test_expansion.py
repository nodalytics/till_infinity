"""The compression-to-expansion alert: its state, its reading, its card line, its contest."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from till_infinity.models import expansion_train as et
from till_infinity.models import retrain as rt
from till_infinity.shared import frozen
from till_infinity.structures import codec as scodec
from till_infinity.structures.learning import expansion as ex


def _bars(n: int, seed: int = 1, quiet_from: int | None = None):
    """15m bars of a walk; from `quiet_from` on the range shrinks tenfold, so it compresses."""
    rng = np.random.default_rng(seed)
    price, t, out = 100.0, 1_700_000_000, []
    for k in range(n):
        scale = 0.0001 if quiet_from is not None and k >= quiet_from else 0.001
        move = rng.standard_normal() * scale
        close = price * math.exp(move)
        high = max(price, close) * math.exp(abs(rng.standard_normal()) * scale / 2)
        low = min(price, close) * math.exp(-abs(rng.standard_normal()) * scale / 2)
        out.append((t + 900, high, low, close))
        price, t = close, t + 900
    return out


def _fed(n: int, quiet_from: int | None = None, feed: str = "g") -> ex.Expansion:
    model = ex.Expansion()
    for when, h, lo, c in _bars(n, quiet_from=quiet_from):
        model.observe(feed, "15m", 900, when, h, lo, c)
    return model


def test_the_percentile_is_the_research_definition():
    bars = _bars(2_500)
    model = ex.Expansion()
    for when, h, lo, c in bars:
        model.observe("g", "15m", 900, when, h, lo, c)
    hi, low, cl = (np.log([b[i] for b in bars]) for i in (1, 2, 3))
    prev = np.r_[np.nan, cl[:-1]]
    tr = np.maximum(hi - low, np.maximum(abs(hi - prev), abs(low - prev)))[1:]
    pct = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().rolling(1500).rank(pct=True)
    assert model.series["g|15m"].pct == pytest.approx(pct.iloc[-1])


def test_it_reads_only_while_compressed():
    loud = _fed(800)
    assert not loud.series["g|15m"].compressed
    assert loud.reading("g", "15m") == {}
    quiet = _fed(800, quiet_from=700)
    s = quiet.series["g|15m"]
    assert s.compressed
    assert s.run > 0
    assert s.depth <= ex.COMPRESSED
    got = quiet.reading("g", "15m")
    assert 0.0 < got["expansion_probability"] < 1.0
    assert got["expansion_lift"] > 0


def test_the_shipped_model_matches_this_recipe():
    spec = frozen.load(ex.MODEL, recipe=ex.RECIPE, names=ex.NAMES)
    assert spec is not None
    assert spec["ahead"] == ex.AHEAD
    assert spec["test"]["real"] >= rt.EXPANSION_GATES["min_real_auc"]


def test_the_card_speaks_only_well_above_normal_and_never_names_a_side():
    assert ex.card_line({}) == []
    assert ex.card_line({"expansion_probability": 0.2, "expansion_lift": 2.0}) == []
    line = ex.card_line({"expansion_probability": 0.31, "expansion_lift": 3.0})
    assert line == ["🌀 coiled · expansion next 16 bars 31% · 3.0x normal · no side"]


def test_the_higher_timeframe_informs_the_lower():
    model = ex.Expansion()
    for when, h, lo, c in _bars(2_000):
        model.observe("g", "15m", 900, when, h, lo, c)
        if (when // 900) % 4 == 0:
            model.observe("g", "1h", 3600, when, h, lo, c)
    up = ex.NAMES.index("up_pct")
    assert not math.isnan(model.series["g|15m"].latest[up])


def test_bad_bars_and_other_intervals_are_ignored():
    model = ex.Expansion()
    model.observe("g", "15m", 900, 0.0, 1.0, 2.0, 1.5)  # high below low
    model.observe("g", "1m", 60, 0.0, 2.0, 1.0, 1.5)
    assert model.series == {}


def test_the_state_survives_the_state_file():
    model = _fed(800, quiet_from=700)
    back = scodec.unpack(scodec.pack({"expansion": model}))["expansion"]
    s = back.series["g|15m"]
    assert s.history.maxlen == ex.WINDOW
    assert s.ranked == sorted(s.history)
    assert back.reading("g", "15m") == model.reading("g", "15m")
    # and it keeps working after the restore
    for when, h, lo, c in _bars(20, seed=4):
        back.observe("g", "15m", 900, when + 10**7, h, lo, c)
    assert len(back.series["g|15m"].ranked) == len(back.series["g|15m"].history)


def test_forget_drops_only_feeds_not_kept():
    model = ex.Expansion()
    for when, h, lo, c in _bars(10):
        model.observe("a", "15m", 900, when, h, lo, c)
        model.observe("b", "1h", 3600, when, h, lo, c)
    assert model.forget({"a"}) == 1
    assert list(model.series) == ["a|15m"]


def test_the_engine_publishes_it_while_compressed():
    from till_infinity.structures import engine

    eng = engine.Engine(intervals=("15m",))
    assert eng._expansion_at("g", "15m") == {}
    for when, h, lo, c in _bars(800, quiet_from=700):
        eng._expansion().observe("g", "15m", 900, when, h, lo, c)
    assert 0.0 < eng._expansion_at("g", "15m")["expansion_probability"] < 1.0


def test_rows_are_compressed_bars_labelled_by_the_next_sixteen():
    rows = et.dataset(et.walks(1, 4_000))
    _, kinds, x, y = rows.arrays()
    assert len(y) > 0
    assert set(kinds) == {"control"}
    assert (x[:, ex.NAMES.index("pct")] <= ex.COMPRESSED).all()
    assert 0 < y.mean() < 1


def test_the_expansion_contest_runs_and_its_export_is_exact(monkeypatch):
    pytest.importorskip("sklearn")
    walks = et.walks
    monkeypatch.setattr(et, "walks", lambda: walks(1, 3_000))
    series = walks(2, 6_000, seed=5)
    names = sorted({s for s, _ in series})
    spec, report = rt.run_expansion(lambda s, iv: series.get((s, iv), []), names)
    usable = [v for v in series.values() if len(v) > ex.WARM + ex.AHEAD + 50]
    assert report["series"] == len(usable)  # a 6,000-bar 15m walk is too short for daily
    assert report["evaluator_max_diff"] <= rt.GATES["exact"]
    assert (spec is not None) == report["promoted"]


def test_the_calendar_sees_a_busier_session_coming():
    """A series whose range quadruples every day from 12:00 to 16:00 UTC: at 09:00 the next 16
    quarter-hours reach into the busy session, so the calendar reads positive; at 16:00 it turns."""
    rng = np.random.default_rng(0)
    model, price = ex.Expansion(), 100.0
    t = 1_700_000_000 - 1_700_000_000 % 86_400
    readings = {}
    for _ in range(6_000):
        hour = (t % 86_400) // 3_600
        scale = 0.002 if 12 <= hour < 16 else 0.0005
        close = price * math.exp(rng.standard_normal() * scale)
        high = max(price, close) * math.exp(abs(rng.standard_normal()) * scale / 2)
        low = min(price, close) * math.exp(-abs(rng.standard_normal()) * scale / 2)
        model.observe("g", "15m", 900, t + 900, high, low, close)
        price, t = close, t + 900
        if t % 3_600 == 0:
            readings[(t % 86_400) // 3_600] = ex.clock_ahead(model.series["g|15m"], t)
    assert readings[9] > 0.3
    assert readings[16] < -0.3


def test_deriv_is_recognised_however_its_name_is_spelled():
    from till_infinity.models.shocks_train import kind

    for name in (
        "Range Break 100 Index",
        "Range_Break_100_Index",
        "Drift_Switch_Index_10",
        "Volatility_75_Index",
        "Boom 1000 Index",
    ):
        assert kind(name) == "deriv", name
    assert kind("EURUSD") == "real"
    assert kind("AAPL.OQ") == "real"
