"""Deriv's own-law envelope: Boom, Crash, DEX, Range Break and Drift Switch quoted from a shipped
convolved table (`research/docs/deriv-variants.md`), cell by cell, calibrated from bar zero."""

from __future__ import annotations

import json
import math
import random

import numpy as np
import pytest

from till_infinity.models import deriv_law_train as dl
from till_infinity.prices.models import Bar
from till_infinity.shared import frozen
from till_infinity.structures.vol import envelope as ev

TABLE = [-0.004, -0.003, -0.002, -0.001, 0.0, 0.001, 0.002, 0.003, 0.004]


@pytest.fixture(autouse=True)
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TI_MODELS_DIR", str(tmp_path))
    frozen.forget_cache()
    yield tmp_path
    frozen.forget_cache()


def _ship(path, tables, recipe=None):
    spec = {"recipe": recipe or ev.LAW_RECIPE, "names": list(ev.LAW_NAMES), "tables": tables}
    (path / f"{ev.LAW_MODEL}.json").write_text(json.dumps(spec))
    frozen.forget_cache()


@pytest.mark.parametrize(
    ("feed", "own"),
    [
        ("boom_1000_index", True),
        ("Crash 500 Index", True),
        ("DEX 600 UP Index", True),
        ("range_break_100_index", True),
        ("drift_switch_index_10", True),
        ("volatility_75_index", False),  # published law
        ("jump_50_index", False),
        ("step_index", False),
        ("eurusd", False),
    ],
)
def test_only_mechanics_only_indices_have_an_own_law(feed, own):
    assert ev.own_law_family(feed) is own


def test_a_shipped_table_is_quoted_from_the_first_bar(models_dir):
    _ship(models_dir, {"boom_1000_index|15m|5": TABLE})
    book = ev.Book()
    book.observe("boom_1000_index", "15m", 10_000.0, 0.001)
    got = book.reading("boom_1000_index", "15m", 10_000.0)
    assert got["env5_ownlaw"] == 1.0
    assert got["env5_p90"] == pytest.approx(10_000.0 * math.exp(0.002), rel=1e-9)
    assert got["env5_p10"] == pytest.approx(10_000.0 * math.exp(-0.002), rel=1e-9)
    assert "env5_law" not in got
    # the other horizons have no table, so they keep the empirical envelope (cold here)
    assert "env20_p90" not in got


def test_a_wrong_recipe_or_a_missing_table_falls_back(models_dir):
    _ship(models_dir, {"boom_1000_index|15m|5": TABLE}, recipe="something else")
    book = ev.Book()
    book.observe("boom_1000_index", "15m", 10_000.0, 0.001)
    assert book.reading("boom_1000_index", "15m", 10_000.0) == {}
    _ship(models_dir, {"boom_1000_index|1h|5": TABLE})  # another interval only
    book = ev.Book()
    book.observe("boom_1000_index", "15m", 10_000.0, 0.001)
    assert book.reading("boom_1000_index", "15m", 10_000.0) == {}


def test_a_published_law_is_not_replaced(models_dir):
    _ship(models_dir, {"volatility_75_index|15m|5": TABLE})
    book = ev.Book()
    book.observe("volatility_75_index", "15m", 1000.0, 0.002)
    got = book.reading("volatility_75_index", "15m", 1000.0)
    assert got["env5_law"] == 1.0
    assert "env5_ownlaw" not in got


def test_the_card_names_the_index_s_own_law(models_dir):
    _ship(models_dir, {"boom_1000_index|15m|5": TABLE})
    book = ev.Book()
    book.observe("boom_1000_index", "15m", 10_000.0, 0.001)
    lines = ev.card_lines(book.reading("boom_1000_index", "15m", 10_000.0), str)
    assert "the index's own law" in lines[0]
    assert "published" not in lines[0]


def test_teaching_skips_an_own_law_index(models_dir):
    _ship(models_dir, {"boom_1000_index|15m|5": TABLE})
    bars = [(100.0, 100.1, 99.9, 100.0)] * 3000
    assert ev.Book().teach("boom_1000_index", "15m", bars) == 0


def _walk(n: int, sigma: float = 0.001, seed: int = 3, t0: int = 1_700_000_000) -> list[Bar]:
    rng = random.Random(seed)
    price, out = 1000.0, []
    for i in range(n):
        close = price * math.exp(rng.gauss(0.0, sigma))
        out.append(
            Bar(t0 + 900 * i, price, max(price, close) * 1.0002, min(price, close) * 0.9998, close)
        )
        price = close
    return out


def test_the_fitted_table_is_the_convolved_one_bar_law():
    spec = dl.fit({("Boom_1000_Index", "15m"): _walk(5000), ("EURUSD", "15m"): _walk(5000)})
    assert set(spec["tables"]) == {f"boom_1000_index|15m|{n}" for n in ev.HORIZONS}
    q = spec["tables"]["boom_1000_index|15m|20"]
    assert q == sorted(q)
    # iid Gaussian steps: the 20-bar P90 is about 1.2816 * 0.001 * sqrt(20)
    assert ev.table_quantile(q, 0.9) == pytest.approx(1.2816 * 0.001 * math.sqrt(20), rel=0.08)


def test_a_memoryless_series_passes_its_cell_and_a_regime_switcher_fails():
    good = {("Boom_1000_Index", "15m"): _walk(12_000)}
    cut = good[("Boom_1000_Index", "15m")][7_200].time
    spec = dl.fit({k: [b for b in v if b.time < cut] for k, v in good.items()})
    kept, cells = dl.select(spec, good, cut)
    assert all(c["pass"] for c in cells if c["n"] <= 20)
    assert kept["tables"]

    # a drift that switches sign every 400 bars: the one-bar law understates the N-bar spread
    rng = np.random.default_rng(5)
    price, out, t0 = 1000.0, [], 1_700_000_000
    for i in range(12_000):
        drift = 0.0006 if (i // 400) % 2 else -0.0006
        close = price * math.exp(drift + rng.normal(0, 0.0005))
        out.append(Bar(t0 + 900 * i, price, max(price, close), min(price, close), close))
        price = close
    bad = {("Drift_Switch_Index_10", "15m"): out}
    spec = dl.fit({k: [b for b in v if b.time < cut] for k, v in bad.items()})
    kept, cells = dl.select(spec, bad, cut)
    assert not any(c["pass"] for c in cells if c["n"] == 50)
    assert not any(k.endswith("|50") for k in kept["tables"])


def test_the_retrain_contest_promotes_passing_cells():
    from till_infinity.models import retrain as rt

    bars = _walk(9_000 * 4, seed=9)  # 15m bars, long enough for a 90-day hold-out

    def fetch(symbol, interval):
        return bars if interval == "15m" else []

    spec, report = rt.run_deriv_law(fetch, ["Boom_1000_Index", "EURUSD"])
    assert report["series"] == 1
    assert report["challenger"]["cells"] == len(ev.HORIZONS)
    assert (spec is not None) == report["promoted"]
    if spec is not None:
        assert spec["recipe"] == ev.LAW_RECIPE
        assert all(k.startswith("boom_1000_index|15m|") for k in spec["tables"])
