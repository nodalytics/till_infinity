"""The band-touch forecaster: P(P90 touched) and P(P10 touched) in the next 5 bars, FX 15m only."""

from __future__ import annotations

import json
import math
import random

import pytest

from till_infinity.models import retrain as rt
from till_infinity.models import touches_train as tt
from till_infinity.prices.models import Bar
from till_infinity.shared import frozen
from till_infinity.structures.learning import touches as tc
from till_infinity.structures.vol import envelope as ev


@pytest.fixture(autouse=True)
def _fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TI_MODELS_DIR", str(tmp_path / "models"))
    frozen.forget_cache()
    yield
    frozen.forget_cache()


def _bars(n: int, seed: int = 1, t0: int = 1_700_000_000) -> list[Bar]:
    rng = random.Random(seed)
    price, sigma, out = 1.1, 0.0008, []
    for i in range(n):
        sigma = min(0.004, max(0.0003, sigma * math.exp(rng.gauss(0, 0.1))))
        close = price * math.exp(rng.gauss(0, sigma))
        high = max(price, close) * math.exp(abs(rng.gauss(0, sigma / 2)))
        low = min(price, close) * math.exp(-abs(rng.gauss(0, sigma / 2)))
        out.append(Bar(t0 + 900 * i, price, high, low, close))
        price = close
    return out


def _fed(feed: str = "eurusd", interval: str = "15m", n: int = 600) -> tc.Touches:
    """Bars through the envelope and the forecaster, in the engine's order."""
    from till_infinity.structures.vol.ranges import Ranges

    model, book, ranges = tc.Touches(), ev.Book(), Ranges()
    for bar in _bars(n):
        ranges.observe(bar.open, bar.high, bar.low, bar.close)
        sigma = ranges.ewma_tr_bps / 10_000
        if sigma <= 0:
            continue
        book.observe(feed, interval, bar.close, sigma)
        env = book.envelopes.get(f"{feed}|{interval}|{tc.AHEAD}")
        quote = list(env.quote) if env is not None and env.warm else None
        model.observe(feed, interval, bar.time, bar.high, bar.low, bar.close, sigma, quote)
    return model


# ------------------------------------------------------------------ the shipped models


def _ship_stumps(tmp_path) -> None:
    """A touch model per band under the current recipe: one split on lvol, so the reading has
    something to evaluate whatever ships in the package."""
    out = tmp_path / "models"
    out.mkdir(exist_ok=True)
    for name in tc.MODELS.values():
        spec = {
            "recipe": tc.RECIPE,
            "names": list(tc.NAMES),
            "baseline": -1.3,
            "trees": [
                [[0, 0.0, 1, 2, 0, 0.0, 1], [0, 0, 0, 0, 1, -0.2, 0], [0, 0, 0, 0, 1, 0.2, 0]]
            ],
            "base_rate": 0.21,
        }
        (out / f"{name}.json").write_text(json.dumps(spec))
    frozen.forget_cache()


def test_a_shipped_model_has_earned_its_place(monkeypatch):
    """Whatever ships under the current recipe passed the contest's skill gate. None may ship:
    over the boosted envelope's bands the touch models' skill fell under the gate
    (`touches.RECIPE`), and then the reading is simply absent."""
    monkeypatch.delenv("TI_MODELS_DIR")
    frozen.forget_cache()
    for name in tc.MODELS.values():
        spec = frozen.load(name, recipe=tc.RECIPE, names=tc.NAMES)
        if spec is None:
            continue
        assert spec["names"] == list(tc.NAMES)
        assert 0.1 < spec["base_rate"] < 0.35
        assert spec["test"]["skill"] >= rt.TOUCH_GATES["min_skill"]


def test_a_warm_fx_series_gets_both_probabilities(tmp_path):
    _ship_stumps(tmp_path)
    got = _fed().reading("eurusd", "15m")
    assert set(got) == {"touch90_prob5", "touch10_prob5"}
    assert all(0.0 < v < 1.0 for v in got.values())


@pytest.mark.parametrize(
    ("feed", "interval"), [("xauusd", "15m"), ("eurusd", "1h"), ("volatility_75_index", "15m")]
)
def test_nothing_is_published_off_fx_15m(feed, interval):
    assert not tc.applies(feed, interval)
    assert _fed(feed, interval).reading(feed, interval) == {}


def test_nothing_is_published_while_cold():
    assert _fed(n=100).reading("eurusd", "15m") == {}


def test_a_missing_model_publishes_nothing(monkeypatch):
    monkeypatch.setattr(tc, "MODELS", {"touch90": "absent", "touch10": "absent"})
    assert _fed().reading("eurusd", "15m") == {}


def test_features_are_the_documented_ones_in_order():
    s = _fed().series["eurusd|15m"]
    assert len(s.latest) == len(tc.NAMES)
    by = dict(zip(tc.NAMES, s.latest, strict=True))
    assert 0.0 <= by["tr_pct"] <= 1.0
    assert min(by["d90"], by["d10"], by["asym"]) > 0
    assert 0.0 <= by["to_weekend"] < 168


def test_the_series_state_stays_bounded():
    s = _fed(n=1500).series["eurusd|15m"]
    assert len(s.sigmas) == tc.NORM
    assert len(s.closes) == 21


# ------------------------------------------------------------------ the card


def test_the_card_line_says_both_bands_and_nothing_while_absent():
    assert tc.card_line({}) == []
    line = tc.card_line({"touch90_prob5": 0.38, "touch10_prob5": 0.22})
    assert line == ["👆 next 5 bars · P90 touched 38% · P10 touched 22%"]


def test_the_envelope_card_carries_the_touch_line():
    got = {
        "env_ref": 1.1,
        "env5_p10": 1.09,
        "env5_p50": 1.1,
        "env5_p90": 1.11,
        "touch90_prob5": 0.4,
        "touch10_prob5": 0.2,
    }
    assert any("P90 touched 40%" in line for line in ev.card_lines(got, str))


# ------------------------------------------------------------------ training and the gates


def test_the_dataset_labels_touches_and_keeps_only_fx_15m():
    rows = tt.dataset(
        {
            ("EURUSD", "15m"): _bars(1500),
            ("XAUUSD", "15m"): _bars(1500, seed=2),
            ("EURUSD", "1h"): _bars(800, seed=3),
        }
    )
    when, x, y90, y10 = rows.arrays()
    assert set(rows.key) == {"eurusd"}
    assert x.shape[1] == len(tc.NAMES)
    assert list(when) == sorted(when)
    assert 0.05 < y90.mean() < 0.5
    assert 0.05 < y10.mean() < 0.5


def test_a_decile_fails_only_beyond_both_the_error_and_the_noise():
    good = {"predicted": 0.10, "realised": 0.13, "n": 500, "error": 0.30, "se": 0.02}  # noise
    bad = {"predicted": 0.10, "realised": 0.16, "n": 500, "error": 0.60, "se": 0.02}
    close = {"predicted": 0.30, "realised": 0.33, "n": 500, "error": 0.10, "se": 0.001}
    assert tt.miscalibrated([good, close]) == []
    assert tt.miscalibrated([good, bad, close]) == [bad]


def test_the_touch_gate():
    """Skill over the flat base rate the card would otherwise print - not over geometry, which the
    boosted bands now carry - with calibration and the champion as before."""
    ok = {"skill_rate": 0.08, "skill_rate_se": 0.01, "skill": 0.01, "calibration_fails": 1}
    assert rt.touch_gate(ok, {}) == []  # little over geometry is no longer a reason
    assert rt.touch_gate({**ok, "skill_rate": 0.02}, {})
    assert rt.touch_gate({**ok, "calibration_fails": 2}, {})
    assert rt.touch_gate({k: v for k, v in ok.items() if k != "calibration_fails"}, {})
    assert rt.touch_gate({**ok, "skill_rate": 0.06}, {"skill_rate": 0.09})  # beyond the slack
    assert rt.touch_gate({**ok, "skill_rate": 0.08}, {"skill_rate": 0.085}) == []


def test_the_touch_contest_runs_and_its_export_is_exact(monkeypatch):
    pytest.importorskip("sklearn")
    monkeypatch.setattr(tt, "CAL_DAYS", 10)
    series = {"EURUSD": _bars(4000, seed=4), "XAUUSD": _bars(4000, seed=5)}
    spec, report = rt.run_touch90(
        lambda symbol, interval: series[symbol] if interval == "15m" else [], list(series)
    )
    assert report["series"] == 1
    assert report["evaluator_max_diff"] <= rt.GATES["exact"]
    assert {"skill", "skill_rate", "calibration_fails"} <= set(report["challenger"])
    assert isinstance(report["champion"], dict)  # empty while no model has earned the recipe
    assert (spec is not None) == report["promoted"]
    json.dumps(report)  # the report file must be able to hold it
