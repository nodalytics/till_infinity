"""Deriv's own-law envelope: Boom, Crash, DEX, Range Break and Drift Switch quoted from a shipped
convolved table (`research/docs/deriv-variants.md`), cell by cell, calibrated from bar zero."""

from __future__ import annotations

import json
import math
import random

import pytest
from till_platform import frozen

from till_infinity.prices.models import Bar
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
