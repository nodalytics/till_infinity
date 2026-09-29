"""The shock forecaster (a frozen boosted model) and the frozen-model loader it reads through."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import random

import pytest

from till_infinity.shared import frozen
from till_infinity.structures import codec as scodec
from till_infinity.structures.learning import shocks as sh


@pytest.fixture(autouse=True)
def _fresh_cache(tmp_path, monkeypatch):
    """Every test reads models from its own empty directory unless it writes one, and never from a
    cache left by another test."""
    monkeypatch.setenv("TI_MODELS_DIR", str(tmp_path / "models"))
    frozen.forget_cache()
    yield
    frozen.forget_cache()


def _bars(n: int, seed: int = 1, calm: float = 0.001, wild: float = 0.004, spell: int = 200):
    """A walk that alternates calm and volatile spells."""
    rng = random.Random(seed)
    price, t = 100.0, 1_700_000_000.0
    for i in range(n):
        sigma = wild if (i // spell) % 2 else calm
        move = rng.gauss(0.0, sigma)
        high = price * math.exp(max(move, 0) + abs(rng.gauss(0, sigma / 2)))
        low = price * math.exp(min(move, 0) - abs(rng.gauss(0, sigma / 2)))
        price *= math.exp(move)
        t += 900
        yield t, max(high, price), min(low, price), price


def _fed(n: int = 800) -> sh.Shocks:
    model = sh.Shocks()
    for t, h, lo, c in _bars(n):
        model.observe("g", "15m", 900, t, h, lo, c)
    return model


# ------------------------------------------------------------------ the shipped model


def test_the_shipped_model_is_found_and_matches_the_features():
    spec = frozen.load(sh.MODEL, recipe=sh.RECIPE, names=sh.NAMES)
    assert spec is not None
    assert spec["names"] == list(sh.NAMES)
    assert 0.0 < spec["base_rate"] < 0.5


def test_a_warm_series_gets_a_probability_and_a_lift():
    got = _fed().reading("g", "15m")
    assert set(got) == {"shock_probability", "shock_lift"}
    assert 0.0 < got["shock_probability"] < 1.0
    base = frozen.load(sh.MODEL, recipe=sh.RECIPE, names=sh.NAMES)["base_rate"]
    assert got["shock_lift"] == pytest.approx(got["shock_probability"] / base, rel=1e-2)


def test_a_cold_series_gets_nothing():
    model = sh.Shocks()
    for t, h, lo, c in _bars(100):
        model.observe("g", "15m", 900, t, h, lo, c)
    assert model.reading("g", "15m") == {}


def test_volatility_well_above_its_norm_reads_as_more_risk():
    s = _fed().series["g|15m"]
    spec = frozen.load(sh.MODEL, recipe=sh.RECIPE, names=sh.NAMES)
    trees = frozen.Trees(spec)
    calm, wild = list(s.latest), list(s.latest)
    calm[0], calm[1], calm[2], calm[3] = -0.6, 0.36, 0.05, 0.0025
    wild[0], wild[1], wild[2], wild[3] = 0.8, 0.64, 0.97, 0.9409
    wild[5], wild[6] = 0.1, 0.05  # and shocks have been happening
    assert trees.predict(wild) > 2 * trees.predict(calm)


# ------------------------------------------------------------------ the loader


def _write(name: str, spec: dict) -> None:
    path = frozen.models_dir() / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec))


def _stump(value: float, recipe: str = "r", names=("x",)) -> dict:
    """One tree: x <= 0 goes to a leaf worth -value, x > 0 to +value."""
    return {
        "recipe": recipe,
        "names": list(names),
        "baseline": 0.0,
        "base_rate": 0.1,
        "trees": [
            [[0, 0.0, 1, 2, 0, 0.0, 1], [0, 0.0, 0, 0, 1, -value, 0], [0, 0.0, 0, 0, 1, value, 0]]
        ],
    }


def test_a_model_trained_on_other_features_is_refused():
    _write("m", _stump(1.0, recipe="other"))
    assert frozen.load("m", recipe="r", names=("x",)) is None
    _write("m", _stump(1.0, names=("y",)))
    frozen.forget_cache()
    assert frozen.load("m", recipe="r", names=("x",)) is None


def test_a_missing_model_publishes_nothing():
    assert frozen.load("absent", recipe="r", names=("x",)) is None


def test_the_models_dir_wins_over_the_shipped_copy_and_changes_are_picked_up():
    _write("m", _stump(1.0))
    first = frozen.load("m", recipe="r", names=("x",), now=1000.0)
    assert frozen.Trees(first).predict([1.0]) == pytest.approx(1 / (1 + math.exp(-1.0)))
    path = frozen.models_dir() / "m.json"
    _write("m", _stump(2.0))
    os.utime(path, (5_000, 5_000))
    # not re-checked inside the window...
    assert frozen.load("m", recipe="r", names=("x",), now=1000.0 + frozen.RECHECK / 2) is first
    # ...and picked up after it
    later = frozen.load("m", recipe="r", names=("x",), now=1000.0 + frozen.RECHECK + 1)
    assert frozen.Trees(later).predict([1.0]) == pytest.approx(1 / (1 + math.exp(-2.0)))


def test_trees_follow_thresholds_and_missing_values():
    trees = frozen.Trees(_stump(1.5))
    low, high = 1 / (1 + math.exp(1.5)), 1 / (1 + math.exp(-1.5))
    assert trees.predict([-1.0]) == pytest.approx(low)
    assert trees.predict([0.0]) == pytest.approx(low)  # x <= threshold goes left
    assert trees.predict([0.1]) == pytest.approx(high)
    assert trees.predict([float("nan")]) == pytest.approx(low)  # missing goes left


# ------------------------------------------------------------------ the rest


def test_the_card_speaks_only_when_the_risk_is_well_above_normal():
    assert sh.card_line({}) == []
    assert sh.card_line({"shock_probability": 0.12, "shock_lift": 2.2}) == []
    line = sh.card_line({"shock_probability": 0.2, "shock_lift": 3.6})
    assert line == ["⚠️ shock risk next 4 bars 20% · 3.6x normal · no side"]


def test_bad_bars_are_ignored():
    model = sh.Shocks()
    model.observe("g", "15m", 900, 0.0, 1.0, 2.0, 1.5)  # high below low
    model.observe("g", "15m", 900, 0.0, 1.0, 1.0, 0.0)
    assert model.series == {}


def test_the_series_history_survives_the_state_file():
    model = _fed(400)
    back = scodec.unpack(scodec.pack({"shocks": model}))["shocks"]
    s = back.series["g|15m"]
    assert s.abs_returns.maxlen == sh.NORM
    assert back.reading("g", "15m") == model.reading("g", "15m")


def test_hours_to_the_weekly_close():
    s = sh.Series(seconds=900)
    s.true_ranges.extend([1e-3] * 10)
    s.ewma_tr = 1e-3
    s.log_tr.extend([-7.0] * 5)

    def to_close(when: str) -> float:
        t = dt.datetime.fromisoformat(when).replace(tzinfo=dt.UTC).timestamp()
        return math.expm1(sh._features(s, t)[9])

    assert round(to_close("2026-09-25 20:00")) == 1  # Friday, an hour before the close
    assert round(to_close("2026-09-28 00:00")) == 117  # Monday midnight


def test_forget_drops_only_feeds_not_kept():
    model = sh.Shocks()
    for t, h, lo, c in _bars(10):
        model.observe("a", "15m", 900, t, h, lo, c)
        model.observe("b", "1h", 3600, t, h, lo, c)
    assert model.forget({"a"}) == 1
    assert list(model.series) == ["a|15m"]


def test_the_engine_publishes_it_once_warm():
    from till_infinity.structures import engine

    eng = engine.Engine(intervals=("15m",))
    assert eng._shock_at("g", "15m") == {}
    for t, h, lo, c in _bars(800):
        eng._shocks().observe("g", "15m", 900, t, h, lo, c)
    assert 0.0 < eng._shock_at("g", "15m")["shock_probability"] < 1.0
