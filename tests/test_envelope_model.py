"""The boosted envelope for FX 15m: regression trees, the model as AgACI's base, the fallbacks."""

from __future__ import annotations

import json
import math
import random
from statistics import NormalDist

import pytest

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


def _ship(tmp_path, horizon: int = 5, family: str = "fx") -> None:
    out = tmp_path / "models"
    out.mkdir(exist_ok=True)
    name = ev.MODELS[(family, horizon)]
    (out / f"{name}.json").write_text(json.dumps(_constant(_gaussian(horizon))))
    frozen.forget_cache()


def test_an_fx_15m_book_reads_the_shipped_model(tmp_path):
    _ship(tmp_path)
    book = ev.Book()
    book.observe("eurusd", "15m", 1.1, 0.001, _features())
    assert book.envelopes["eurusd|15m|5"].base == ev.MODEL_RECIPE
    assert book.reading("eurusd", "15m", 1.1)["env5_model"] == 1.0


@pytest.mark.parametrize(
    ("feed", "interval"),
    [
        # Another family at 15m: it has a boosted envelope in principle, and no
        # model file, so it quotes from the history exactly as it always did.
        ("xauusd", "15m"),
        ("btcusd", "15m"),
        # The wrong interval, which no model is trained for at all.
        ("eurusd", "1h"),
        # A family with no boosted envelope of any kind.
        ("us500", "15m"),
    ],
)
def test_other_series_keep_the_history(tmp_path, feed, interval):
    """Only the series the shipped model was trained for reads it.

    Metals and crypto are families the contest now runs for, so `model_applies`
    is true of them - but an *untrained* family must still quote from the
    history rather than borrowing FX's model, which is the whole reason the
    file is keyed by family.
    """
    _ship(tmp_path)
    book = ev.Book()
    book.observe(feed, interval, 1.1, 0.001, _features())
    assert book.envelopes[f"{feed}|{interval}|5"].base == ""


def test_a_family_reads_its_own_model_and_not_another_s(tmp_path, monkeypatch):
    """The point of keying by family: metals gets a model, FX has none, and FX
    must quote from the history rather than borrowing the metals one.

    The packaged FX models have to be hidden for this, or FX finds its own real
    one and the test proves nothing.
    """
    monkeypatch.setattr(frozen, "PACKAGED", tmp_path / "nothing")
    _ship(tmp_path, family="metals")
    book = ev.Book()
    book.observe("xauusd", "15m", 1.1, 0.001, _features())
    book.observe("eurusd", "15m", 1.1, 0.001, _features())
    assert book.envelopes["xauusd|15m|5"].base == ev.MODEL_RECIPE
    assert book.envelopes["eurusd|15m|5"].base == ""


def test_every_family_with_a_model_has_one_per_horizon():
    for family in ev.MODEL_FAMILIES:
        for horizon in ev.HORIZONS:
            assert (family, horizon) in ev.MODELS
    # The FX names are unchanged, so the models already shipped keep loading.
    assert ev.MODELS[("fx", 5)] == "envelope_fx15m_5"


def test_no_model_no_features_or_a_wrong_recipe_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(frozen, "PACKAGED", tmp_path / "nothing")
    book = ev.Book()
    book.observe("eurusd", "15m", 1.1, 0.001, _features())  # no model shipped
    assert book.envelopes["eurusd|15m|5"].base == ""
    _ship(tmp_path)
    book.observe("eurusd", "15m", 1.1, 0.001, None)  # cold: no features
    assert book.envelopes["eurusd|15m|5"].base == ""
    wrong = {**_constant(_gaussian(5)), "recipe": "something else"}
    (tmp_path / "models" / f"{ev.MODELS[('fx', 5)]}.json").write_text(json.dumps(wrong))
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
    """FX is the only family with models in the tree today. The others are in
    the contest and have not been trained, so they load as None - which is an
    untrained family, not a fault, and the history quotes instead."""
    monkeypatch.delenv("TI_MODELS_DIR")
    frozen.forget_cache()
    shipped = 0
    for (family, horizon), name in ev.MODELS.items():
        spec = frozen.load(name, recipe=ev.MODEL_RECIPES, names=ev.MODEL_NAMES)
        got = ev.model_quantiles(horizon, _features(), family=family)
        if spec is None:
            assert got is None, f"{name} quoted without a model"
            continue
        shipped += 1
        assert spec["levels"] == list(ev.MODEL_LEVELS)
        assert spec["horizon"] == horizon
        assert got == sorted(got)
    assert shipped == len(ev.HORIZONS), "FX's three models must still be found"


def test_a_model_on_an_older_recipe_still_loads_and_is_fed_its_own_names(monkeypatch):
    """**Adding a feature must not strand the models already in service.**

    `body` and `displaced` joined `MODEL_NAMES` on 2026-10-08, and the three FX
    models in the tree were trained on the six before them. Under an equality
    check every one of them is refused and the engine falls back to its history
    envelope until a retrain lands - for no safety gained, because the only
    unsafe case is a model needing an input the caller cannot supply.

    So the check is a subset, the recipe is a list newest-first, and the vector
    is built from the spec's own `names`. A six-feature model keeps quoting.
    """
    monkeypatch.delenv("TI_MODELS_DIR")
    frozen.forget_cache()
    spec = frozen.load(ev.MODELS[("fx", 20)], recipe=ev.MODEL_RECIPES, names=ev.MODEL_NAMES)
    assert spec is not None, "the shipped model must still load"
    assert spec["recipe"] != ev.MODEL_RECIPE, "this is the older recipe, by construction"
    assert set(spec["names"]) < set(ev.MODEL_NAMES), "fewer names than the recipe now offers"
    # and it quotes, fed the six it declares out of the eight on offer
    got = ev.model_quantiles(20, _features(), family="fx")
    assert got is not None
    assert got == sorted(got)


def test_a_model_needing_a_feature_we_cannot_supply_is_still_refused():
    """The one case a subset check must still catch."""
    assert frozen.load(ev.MODELS[("fx", 20)], recipe=ev.MODEL_RECIPES, names=("lvol", "r1")) is None


# ------------------------------------------------ how much of the path went somewhere


def test_a_straight_move_is_perfectly_efficient():
    """One is a move that went straight there."""
    assert tc._efficiency(list(range(11)), 10) == 1.0


def test_a_path_that_arrives_nowhere_is_zero():
    """Zero is ground covered to no end - the same answer a flat series gives,
    and the right one: no distance travelled is no evidence about direction."""
    assert tc._efficiency([1, 2] * 5 + [1], 10) == 0.0
    assert tc._efficiency([3.0] * 11, 10) == 0.0


def test_it_is_bounded_in_zero_to_one():
    """By the triangle inequality, which is why it needs no scaling and
    compares across instruments as it stands."""
    rng = random.Random(5)
    for _ in range(200):
        walk = [rng.gauss(0, 1) for _ in range(12)]
        assert 0.0 <= tc._efficiency(walk, 10) <= 1.0


def test_direction_does_not_change_it():
    """It is `|net| / path`, so a fall as straight as a rise reads the same.

    Deliberate. Direction is already carried by `r1`, `r5` and `r20`, and the
    one positive result of the z-score line was that **stripping the sign**
    took IC from +0.0024 to +0.0782 (`zscore-magnitude.md`). Efficiency being
    unsigned is that finding applied, not an oversight.
    """
    up = list(range(11))
    assert tc._efficiency(up, 10) == tc._efficiency(up[::-1], 10)


def test_too_short_a_path_is_not_measured():
    """Two points are trivially perfectly efficient and say nothing, which is
    the reason `trend.FEWEST` exists - this uses the same constant rather than
    picking its own."""
    assert tc._efficiency([1.0, 2.0], 10) == 0.0
    assert tc._efficiency([], 10) == 0.0


def test_efficiency_is_in_the_feature_contract():
    """A feature the model cannot see is a feature that cannot be judged."""
    assert "efficiency" in ev.MODEL_NAMES


def test_the_recipe_was_bumped_with_the_feature_set():
    """`frozen.load` checks the recipe, so a shipped model trained without
    `efficiency` must be refused rather than fed an input it never saw - and
    the older recipes stay listed so those models still load on their own."""
    assert "efficiency" in ev.MODEL_RECIPE
    assert ev.MODEL_RECIPES[0] == ev.MODEL_RECIPE
    assert any("efficiency" not in r for r in ev.MODEL_RECIPES[1:])


# ------------------------------------------------------------------ activity, and what the
# ------------------------------------------------------------------ contest can actually judge


def _volume_bars(n: int = 400, seed: int = 3) -> list:
    """A 15m series whose bars differ in how busy they are."""
    from till_infinity.prices.models import Bar

    rng = random.Random(seed)
    bars, price = [], 1.1
    for i in range(n):
        price *= math.exp(rng.gauss(0, 0.001))
        bars.append(
            Bar(
                time=1_700_000_000 + 900 * i,
                open=price,
                high=price * 1.001,
                low=price * 0.999,
                close=price,
                volume=100.0 * (1.0 + 4.0 * rng.random()),
            )
        )
    return bars


def test_activity_defaults_to_nothing_unusual_without_a_book():
    """A caller that keeps no activity book must not poison the feature."""
    t = tc.Touches()
    rng = random.Random(1)
    price = 1.1
    for i in range(300):
        price *= math.exp(rng.gauss(0, 0.001))
        t.advance(
            "eurusd", "15m", 1_700_000_000 + 900 * i, price * 1.0005, price * 0.9995, price, 0.001
        )
    assert t.base("eurusd", "15m")["activity"] == 1.0


def test_a_model_trained_before_activity_still_loads(tmp_path):
    """The subset rule: adding a name must not strand the models in service."""
    spec = _constant(_gaussian(5))
    spec["recipe"] = ev.MODEL_RECIPES[-1]
    spec["names"] = ["lvol", "r1", "r5", "r20", "rng", "hour"]
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "envelope_fx15m_5.json").write_text(json.dumps(spec))
    frozen.forget_cache()
    assert ev.model_quantiles(5, _features(), family="fx") is not None


# ---------------------------------------------- a model is fed its own feature order


def test_vector_passes_a_matching_order_through_untouched():
    """The common case costs nothing: same names, same order, same list."""
    from till_infinity.shared import frozen

    names = ("a", "b", "c")
    spec = {"names": list(names)}
    assert frozen.vector(spec, names, [1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]
    # A spec that declares no names at all is an older file; feed it as given.
    assert frozen.vector({}, names, [1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]


def test_vector_reorders_when_the_recipe_has_gained_a_feature():
    """**The bug this exists to stop.** `load` accepts a file whose names are a
    subset, so a module that adds a feature keeps its shipped models - and a
    caller feeding positionally from its own constant then shifts every value.

    `activity` becoming the fifteenth envelope feature on 2026-10-09 is the real
    case: the shipped files have fourteen names.
    """
    from till_infinity.shared import frozen

    code = ("lvol", "r1", "r5", "activity")
    trained_on = ["lvol", "r1", "r5"]
    values = [0.1, 0.2, 0.3, 0.9]

    got = frozen.vector({"names": trained_on}, code, values)
    assert got == [0.1, 0.2, 0.3], "the model must see its own three, not the first three of four"

    # And a reordering, not just a truncation.
    got = frozen.vector({"names": ["r5", "lvol", "r1"]}, code, values)
    assert got == [0.3, 0.1, 0.2]


def test_vector_refuses_a_model_wanting_a_feature_we_cannot_supply():
    """The one genuinely unsafe case, and the only one that returns None."""
    from till_infinity.shared import frozen

    assert frozen.vector({"names": ["a", "zzz"]}, ("a", "b"), [1.0, 2.0]) is None


def test_the_positional_callers_all_route_through_vector():
    """Guards the fix rather than the helper: the three modules that build a
    feature list positionally must hand it to `frozen.vector` before predicting,
    or the hazard above comes straight back."""
    import inspect

    from till_infinity.structures.learning import expansion, shocks, touches

    for mod in (shocks, expansion, touches):
        src = inspect.getsource(mod)
        assert "frozen.vector(" in src, f"{mod.__name__} does not reorder to the spec's names"
        # And it must not still be predicting straight off its own list.
        assert "predict(s.latest)" not in src, f"{mod.__name__} still predicts positionally"
