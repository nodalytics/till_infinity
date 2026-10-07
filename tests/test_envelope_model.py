"""The boosted envelope for FX 15m: regression trees, the model as AgACI's base, the fallbacks."""

from __future__ import annotations

import json
import math
import random
from statistics import NormalDist

import pytest

from till_infinity.models import retrain as rt
from till_infinity.shared import frozen
from till_infinity.structures.learning import touches as tc
from till_infinity.structures.vol import envelope as ev


@pytest.fixture(autouse=True)
def _models_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TI_MODELS_DIR", str(tmp_path / "models"))
    frozen.forget_cache()
    yield
    frozen.forget_cache()


def _leaf(value: float) -> list:
    return [[0, 0.0, 0, 0, 1, value, 1]]


def _constant(quantiles: list[float]) -> dict:
    """A spec whose every level predicts a fixed value: one leaf-only tree per level."""
    return {
        "recipe": ev.MODEL_RECIPE,
        "names": list(ev.MODEL_NAMES),
        "link": "identity",
        "levels": list(ev.MODEL_LEVELS),
        "models": [{"baseline": q, "trees": [_leaf(0.0)]} for q in quantiles],
    }


def _gaussian(horizon: int) -> list[float]:
    return [NormalDist().inv_cdf(level) * math.sqrt(horizon) for level in ev.MODEL_LEVELS]


def _features() -> dict[str, float]:
    return dict.fromkeys(ev.MODEL_NAMES, 0.1)


# ------------------------------------------------------------------ the evaluator


def test_the_identity_link_returns_the_raw_sum_and_logit_stays_the_default():
    stump = {
        "baseline": 0.5,
        "trees": [[[0, 1.0, 1, 2, 0, 0.0, 1], [0, 0, 0, 0, 1, -0.2, 0], [0, 0, 0, 0, 1, 0.3, 0]]],
    }
    assert frozen.Trees({**stump, "link": "identity"}).predict([0.0]) == pytest.approx(0.3)
    assert frozen.Trees({**stump, "link": "identity"}).predict([2.0]) == pytest.approx(0.8)
    assert frozen.Trees(stump).predict([2.0]) == pytest.approx(1 / (1 + math.exp(-0.8)))


def test_quantiles_never_cross():
    crossed = _constant([-1.0, -2.0, 0.0, 1.5, 1.0])
    assert frozen.Quantiles(crossed).predict([0.0] * 6) == [-2.0, -1.0, 0.0, 1.0, 1.5]


def test_interpolation_is_linear_between_levels_and_flat_beyond():
    q = [-2.0, -1.0, 0.0, 1.0, 2.0]
    assert ev._interpolate(0.3, q) == pytest.approx(-0.5)
    assert ev._interpolate(0.01, q) == -2.0
    assert ev._interpolate(0.99, q) == 2.0
    assert ev._interpolate(0.9, q) == 1.0


# ------------------------------------------------------------------ the features


def test_the_models_inputs_are_the_touch_features_base():
    s = tc.Series()
    rng = random.Random(1)
    price = 1.1
    t = tc.Touches()
    for i in range(300):
        price *= math.exp(rng.gauss(0, 0.001))
        t.advance(
            "eurusd", "15m", 1_700_000_000 + 900 * i, price * 1.0005, price * 0.9995, price, 0.001
        )
    got = t.base("eurusd", "15m")
    assert set(ev.MODEL_NAMES) <= set(got)
    assert got["hour"] == float(int(got["hour"]))
    s = t.series["eurusd|15m"]
    # the touch features are the same base, plus the bands
    feats = tc.features(s, *s.bar, [-1.0, 0.0, 1.0])
    assert feats[: len(tc.NAMES) - 3] == [got[n] for n in tc.NAMES[:-3]]


def test_no_features_while_the_series_is_cold():
    t = tc.Touches()
    t.advance("eurusd", "15m", 1_700_000_000, 1.1, 1.09, 1.095, 0.001)
    assert t.base("eurusd", "15m") is None


# ------------------------------------------------------------------ the envelope


def test_the_model_is_the_base_and_is_published(tmp_path):
    env = ev.Envelope(horizon=5, feed="eurusd", bar_seconds=900.0)
    model = _gaussian(5)
    env.observe(1.1, 0.001, model)
    assert env.base == ev.MODEL_RECIPE
    got = env.prices(1.1)
    assert got["env5_model"] == 1.0
    assert env.quote == pytest.approx([ev._interpolate(t, model) for t in ev.TARGETS])


def test_the_model_carries_agaci_and_coverage_is_honest():
    env = ev.Envelope(horizon=5, feed="eurusd", bar_seconds=900.0)
    rng, price, model = random.Random(3), 1.1, _gaussian(5)
    for _ in range(6_000):
        price *= math.exp(rng.gauss(0.0, 0.001))
        env.observe(price, 0.001, model)
    p10, p50, p90 = env.coverage()
    assert abs(p10 - 0.10) < 0.02
    assert abs(p50 - 0.50) < 0.03
    assert abs(p90 - 0.90) < 0.02
    assert env.learned > ev.WARM


def test_a_change_of_base_relearns_agaci():
    env = ev.Envelope(horizon=5)
    rng, price = random.Random(4), 1.1
    for _ in range(1_500):
        price *= math.exp(rng.gauss(0.0, 0.001))
        env.observe(price, 0.001)
    assert env.learned > 0
    env.observe(price, 0.001, _gaussian(5))
    assert env.learned == 0
    # the quotes made on the old base still settle, but AgACI learns nothing from them
    assert all(len(q) == 3 for q in list(env.pending)[:-1])
    assert len(env.pending[-1]) == 5  # the new base's quote carries its correctors


def _ship(tmp_path, horizon: int = 5) -> None:
    out = tmp_path / "models"
    out.mkdir(exist_ok=True)
    (out / f"{ev.MODELS[horizon]}.json").write_text(json.dumps(_constant(_gaussian(horizon))))
    frozen.forget_cache()


def test_an_fx_15m_book_reads_the_shipped_model(tmp_path):
    _ship(tmp_path)
    book = ev.Book()
    book.observe("eurusd", "15m", 1.1, 0.001, _features())
    assert book.envelopes["eurusd|15m|5"].base == ev.MODEL_RECIPE
    assert book.reading("eurusd", "15m", 1.1)["env5_model"] == 1.0


@pytest.mark.parametrize(
    ("feed", "interval"), [("xauusd", "15m"), ("eurusd", "1h"), ("btcusd", "15m")]
)
def test_other_series_keep_the_history(tmp_path, feed, interval):
    _ship(tmp_path)
    book = ev.Book()
    book.observe(feed, interval, 1.1, 0.001, _features())
    assert book.envelopes[f"{feed}|{interval}|5"].base == ""


def test_no_model_no_features_or_a_wrong_recipe_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(frozen, "PACKAGED", tmp_path / "nothing")
    book = ev.Book()
    book.observe("eurusd", "15m", 1.1, 0.001, _features())  # no model shipped
    assert book.envelopes["eurusd|15m|5"].base == ""
    _ship(tmp_path)
    book.observe("eurusd", "15m", 1.1, 0.001, None)  # cold: no features
    assert book.envelopes["eurusd|15m|5"].base == ""
    wrong = {**_constant(_gaussian(5)), "recipe": "something else"}
    (tmp_path / "models" / f"{ev.MODELS[5]}.json").write_text(json.dumps(wrong))
    frozen.forget_cache()
    book.observe("eurusd", "15m", 1.1, 0.001, _features())
    assert book.envelopes["eurusd|15m|5"].base == ""


def test_a_faulting_model_falls_back(tmp_path, monkeypatch):
    _ship(tmp_path)

    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ev, "model_quantiles", broken)
    book = ev.Book()
    book.observe("eurusd", "15m", 1.1, 0.001, _features())
    assert book.envelopes["eurusd|15m|5"].base == ""


def test_teaching_with_bar_times_teaches_agaci_on_the_model(tmp_path):
    _ship(tmp_path)
    rng, price, bars = random.Random(5), 1.1, []
    for i in range(3_000):
        close = price * math.exp(rng.gauss(0, 0.001))
        bars.append(
            (
                1_700_000_000.0 + 900 * i,
                price,
                max(price, close) * 1.0003,
                min(price, close) * 0.9997,
                close,
            )
        )
        price = close
    book = ev.Book()
    assert book.teach("eurusd", "15m", bars) >= 1
    env = book.envelopes["eurusd|15m|5"]
    assert env.base == ev.MODEL_RECIPE
    assert env.learned >= ev.WARM
    untimed = ev.Book()
    untimed.teach("eurusd", "15m", [b[1:] for b in bars])
    assert untimed.envelopes["eurusd|15m|5"].base == ""


def test_the_card_tags_a_boosted_band():
    got = {"env_ref": 1.1, "env5_p10": 1.09, "env5_p50": 1.1, "env5_p90": 1.11, "env5_model": 1.0}
    assert "boosted" in ev.card_lines(got, str)[0]


# ------------------------------------------------------------------ the shipped models and gates


def test_the_shipped_models_load_and_match_the_features(monkeypatch):
    monkeypatch.delenv("TI_MODELS_DIR")
    frozen.forget_cache()
    for horizon, name in ev.MODELS.items():
        spec = frozen.load(name, recipe=ev.MODEL_RECIPE, names=ev.MODEL_NAMES)
        assert spec is not None, name
        assert spec["levels"] == list(ev.MODEL_LEVELS)
        assert spec["horizon"] == horizon
        got = ev.model_quantiles(horizon, _features())
        assert got == sorted(got)


GOOD = {
    "vs_empirical_slice": {"relative": -0.04, "low": -0.05, "high": -0.03, "se": 0.005},
    "worst_window": 0.88,
    "empirical_worst_window": 0.885,
    # Pooled coverage, which `envelope_train.summary` reports on every challenger
    # and the absolute gates read. A fixture without them is a challenger that
    # quoted no band at all.
    "p10": 0.10,
    "p50": 0.50,
    "p90": 0.90,
}

#: Quantile boosting as `conformal.md` measured it on metals at 50 bars: the
#: lowest pinball of any method in all 18 cells, and a worst slice of 78.1%
#: against a quoted 90%. Every *relative* gate passes it - it beats the history
#: envelope on pinball and its worst window is close to the history envelope's,
#: because that one is poor on metals too. This is the case the absolute floor
#: exists for, and the test below is the one that would have stopped it
#: shipping.
METALS_50 = {
    "vs_empirical_slice": {"relative": -0.06, "low": -0.07, "high": -0.05, "se": 0.004},
    "worst_window": 0.781,
    "empirical_worst_window": 0.79,
    "p10": 0.10,
    "p50": 0.50,
    "p90": 0.90,
}


def test_the_gates_promote_a_good_model():
    assert rt.envelope_gate(GOOD) == []


@pytest.mark.parametrize(
    ("change", "word"),
    [
        (
            {"vs_empirical_slice": {"relative": -0.01, "low": -0.02, "high": 0.001, "se": 0.005}},
            "noise",
        ),
        ({"worst_window": 0.86}, "worst"),
        ({"vs_champion": {"relative": 0.03, "se": 0.005}}, "champion"),
    ],
)
def test_the_gates_keep_the_champion(change, word):
    assert any(word in r for r in rt.envelope_gate({**GOOD, **change}))


def test_a_small_slip_against_the_champion_is_within_its_slack():
    assert rt.envelope_gate({**GOOD, "vs_champion": {"relative": 0.004, "se": 0.001}}) == []


def test_the_contest_runs_on_a_toy_fetch():
    pytest.importorskip("sklearn")
    from till_infinity.prices.models import Bar

    def walk(seed: int) -> list[Bar]:
        rng, price, out = random.Random(seed), 1.1, []
        for i in range(10_500):
            sigma = 0.0015 if (i // 1500) % 2 else 0.0006
            close = price * math.exp(rng.gauss(0, sigma))
            out.append(
                Bar(
                    1_700_000_000 + 900 * i,
                    price,
                    max(price, close) * (1 + sigma / 3),
                    min(price, close) * (1 - sigma / 3),
                    close,
                )
            )
            price = close
        return out

    data = {"EURUSD": walk(1), "GBPUSD": walk(2)}
    spec, report = rt.run_envelope5(lambda s, i: data[s] if i == "15m" else [], list(data))
    assert report["evaluator_max_diff"] <= rt.GATES["exact"]
    for key in ("vs_empirical", "vs_empirical_slice", "worst_window", "empirical_worst_window"):
        assert key in report["challenger"]
    assert (spec is not None) == report["promoted"]


# ------------------------------------------- the absolute gates (added 2026-10-07)


def test_the_metals_model_conformal_measured_would_not_ship():
    """`conformal.md`'s closing recommendation, as a test.

    Quantile boosting had the lowest pinball of every method in all 18 family x
    horizon cells and a worst slice in metals of 78.1% at 50 bars. Every
    *relative* gate passes it, because the history envelope is poor on metals
    too - which is exactly how a model that quotes 90 and covers 78 reaches
    production.
    """
    reasons = rt.envelope_gate(METALS_50)
    assert reasons, "78.1% worst-window coverage must not promote"
    assert any("floor" in r for r in reasons)
    # And it is the absolute floor that catches it, not the relative one: its
    # worst window is within `slice_points` of the history envelope's.
    assert not any("against the history envelope's" in r for r in reasons)


def test_the_relative_gates_alone_would_have_passed_it():
    """The reason the floor had to be added rather than the others tightened."""
    from till_infinity.models.envelope_train import ENVELOPE_GATES

    mine = METALS_50["worst_window"]
    theirs = METALS_50["empirical_worst_window"]
    assert mine >= theirs - ENVELOPE_GATES["slice_points"]
    assert METALS_50["vs_empirical_slice"]["high"] < ENVELOPE_GATES["beats_empirical"]


@pytest.mark.parametrize("cover", [0.84, 0.70, 0.0])
def test_any_worst_window_under_the_floor_is_refused(cover):
    got = rt.envelope_gate({**GOOD, "worst_window": cover, "empirical_worst_window": cover})
    assert any("floor" in r for r in got)


def test_a_worst_window_just_over_the_floor_is_allowed():
    """The history envelope moves with it, so only the absolute gate is in play:
    0.851 against its 0.885 would fail the *relative* one on its own."""
    just = {**GOOD, "worst_window": 0.851, "empirical_worst_window": 0.855}
    assert rt.envelope_gate(just) == []


@pytest.mark.parametrize(
    ("level", "value"),
    [("p10", 0.14), ("p10", 0.06), ("p50", 0.55), ("p90", 0.86), ("p90", 0.94)],
)
def test_a_band_wrong_at_any_level_is_refused(level, value):
    """A model can buy pinball with a band that is wrong in a useful direction,
    so each level is checked against its own nominal rather than the width."""
    got = rt.envelope_gate({**GOOD, level: value})
    assert any(level in r for r in got), got


def test_a_missing_coverage_figure_is_refused_rather_than_assumed():
    """Absent is not passing. A challenger that reported no coverage at all used
    to clear every gate here, because all of them were comparisons."""
    for level in ("p10", "p50", "p90"):
        missing = {k: v for k, v in GOOD.items() if k != level}
        assert any(level in r for r in rt.envelope_gate(missing))
    nan = rt.envelope_gate({**GOOD, "worst_window": float("nan")})
    assert any("floor" in r for r in nan)
