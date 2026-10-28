"""the compression-to-expansion trainer and its contest, as these passed when the pipeline was retired.

Moved out of `tests/test_expansion.py` on 2026-10-28. The reader half stayed: the shipped
model is still read by the live package, and only the training and promotion of a
replacement is retired. These import `till_infinity.models.*_train`, which lives
beside this file, so they do not run as they stand.
"""

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
