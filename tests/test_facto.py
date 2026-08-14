"""Factorisation machines over resolved level calls, and the guards on them."""

from __future__ import annotations

import math
import random
import warnings

import pytest

from till_infinity.structures import facto
from till_infinity.structures.facto import Example, Model, encode, evaluate


def _example(when: float, target: float, *, predicted: float | None = None, **features) -> Example:
    base = {"approach_vol": 1.0, "depth_vol": 0.5, "strength": 0.5, "regime": 0.5}
    return Example(features={**base, **features}, target=target, when=when, predicted=predicted)


# ------------------------------------------------------------- encoding


def test_numbers_pass_through_and_names_are_one_hot():
    """An integer code would claim 1h sits between 15m and 4h on some scale."""
    found = encode(
        {"approach_vol": 1.5, "regime": 0.9, "side": "above", "interval": "1h", "junk": "x"}
    )
    assert found["approach_vol"] == pytest.approx(facto.saturate(1.5))
    assert found["regime"] == 0.9  # already bounded, so it passes straight through
    assert found["side_above"] == 1.0
    assert found["interval_1h"] == 1.0
    assert "junk" not in found
    assert "side" not in found


def test_a_missing_feature_is_absent_rather_than_zero():
    """Zero is a value; absent is not knowing, and an FM treats them differently."""
    assert "strength" not in encode({"approach_vol": 1.0})


def test_nonsense_values_are_dropped():
    assert encode({"approach_vol": "wide", "regime": None}) == {}


def test_volatility_unit_features_are_bounded_without_losing_their_order():
    """A touch arriving in a dead pocket divides by a small number and explodes.

    Bounded, because an FM multiplies its features together and an unbounded
    one diverges it. Ordered, because a four-volatility approach and a forty-
    volatility one are different events and a clip would call them the same.
    """
    seen = [encode({"approach_vol": v})["approach_vol"] for v in (0.0, 1.0, 4.0, 40.0, 4_000.0)]
    assert all(0.0 <= value < 1.0 for value in seen)
    assert seen == sorted(seen)
    assert len(set(seen)) == len(seen)


def test_a_violent_touch_does_not_diverge_the_model():
    """The invariant: one low-volatility pocket must not take the factors out.

    Raw, this diverged inside tens of examples and then answered zero forever —
    `Model.predict` catching the NaN, so the service stayed up and the model
    stopped learning without either of them saying so.
    """
    model = Model()
    rows = []
    for n in range(300):
        approach = 5_000.0 if n % 37 == 0 else 1.5
        rows.append((encode({"approach_vol": approach, "run_vol": approach, "regime": 0.5}), 1.0))

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        for features, target in rows:
            model.predict(features)
            model.learn(features, target)

    assert math.isfinite(model.predict(rows[-1][0]))


# ------------------------------------------------------------- the guard


def test_it_refuses_to_answer_on_too_little():
    """An FM over ten rows produces a number, and the number is noise."""
    report = evaluate([_example(float(i), 1.0) for i in range(10)])
    assert not report.enough
    assert "not enough data" in report.verdict
    assert not report.beats_baseline


def test_an_empty_journal_is_not_an_error():
    report = evaluate([])
    assert report.examples == 0
    assert not report.enough


def test_nothing_learnable_does_not_beat_the_average():
    """Random targets with no signal — the honest answer is 'the features are not helping'."""
    rand = random.Random(3)
    rows = [
        _example(float(i), rand.gauss(0, 1), approach_vol=rand.random(), regime=rand.random())
        for i in range(facto.MIN_EXAMPLES + 50)
    ]
    report = evaluate(rows)
    assert report.enough
    assert not report.beats_baseline
    assert "not helping" in report.verdict


def test_edging_the_baseline_is_not_beating_it():
    """A one per cent win over a few hundred noisy rows is the baseline starting cold."""
    close = facto.Report(examples=500, model_mae=0.99, baseline_mae=1.0)
    assert not close.beats_baseline
    clear = facto.Report(examples=500, model_mae=0.80, baseline_mae=1.0)
    assert clear.beats_baseline


def test_a_real_interaction_is_found():
    """The thing an additive model cannot express: the sign depends on the pair."""
    rand = random.Random(5)
    rows = []
    for i in range(facto.MIN_EXAMPLES * 3):
        above = i % 2 == 0
        violent = (i // 2) % 2 == 0
        # push is up only when both hold — a pure interaction, zero main effect
        target = (2.0 if (above and violent) else -2.0) + rand.gauss(0, 0.1)
        rows.append(
            Example(
                features={
                    "side_above": 1.0 if above else 0.0,
                    "side_below": 0.0 if above else 1.0,
                    "regime": 1.0 if violent else 0.0,
                    "calm": 0.0 if violent else 1.0,
                },
                target=target,
                when=float(i),
            )
        )
    report = evaluate(rows)
    assert report.enough
    assert report.beats_baseline
    assert report.direction > report.base_rate


# --------------------------------------------------------- walk-forward


def test_every_example_is_predicted_before_it_is_learned():
    """No split to arrange wrongly, and no later row can inform an earlier call."""
    seen: list[str] = []

    class Spy(Model):
        def predict(self, features):
            seen.append("predict")
            return 0.0

        def learn(self, features, target):
            seen.append("learn")

    evaluate([_example(float(i), 1.0) for i in range(5)], model=Spy())
    assert seen == ["predict", "learn"] * 5


def test_examples_are_scored_in_time_order():
    """A shuffled split leaks: two touches minutes apart are one observation."""
    order: list[float] = []

    class Spy(Model):
        def learn(self, features, target):
            order.append(target)

    rows = [_example(float(i), float(i)) for i in (3, 1, 2, 0)]
    evaluate(rows, model=Spy())
    assert order == [0.0, 1.0, 2.0, 3.0]


# ------------------------------------------------------------ baselines


def test_the_levels_model_is_scored_on_the_same_rows():
    """An FM that does not beat what it was meant to improve on is not an improvement."""
    rows = [_example(float(i), 2.0, predicted=2.0) for i in range(facto.MIN_EXAMPLES + 10)]
    report = evaluate(rows)
    assert report.levels_examples == len(rows)
    assert report.levels_mae == pytest.approx(0.0)  # it predicted them exactly
    assert not report.beats_levels  # nothing beats an exact predictor


def test_rows_the_levels_model_never_saw_are_not_counted_against_it():
    rows = [_example(float(i), 1.0) for i in range(facto.MIN_EXAMPLES + 10)]
    report = evaluate(rows)
    assert report.levels_examples == 0


def test_the_baseline_gets_the_same_no_lookahead_treatment():
    """Comparing against the full-sample mean would hand the baseline the future."""
    rows = [_example(float(i), 1.0) for i in range(facto.MIN_EXAMPLES + 10)]
    report = evaluate(rows)
    # first prediction has no history, so a constant target still costs it something
    assert report.baseline_mae > 0


def test_a_report_reads_as_a_sentence():
    rows = [_example(float(i), 1.0) for i in range(facto.MIN_EXAMPLES + 10)]
    assert "examples" in str(evaluate(rows))
    assert "not enough" in str(evaluate(rows[:5]))


def test_a_single_feature_has_no_interaction_to_report():
    """An FM models pairs; one feature has none, and river raises rather than say so."""
    model = Model()
    model.learn({"a": 1.0, "b": 1.0}, 1.0)
    assert model.predict({"a": 1.0}) == 0.0


def test_an_unfitted_model_has_no_opinion():
    assert Model().predict({"a": 1.0, "b": 2.0}) == 0.0


def test_a_non_finite_prediction_is_no_opinion_rather_than_a_nan():
    """A NaN propagates through MAE and reads as 'not better', not as broken."""
    import math

    from till_infinity.structures.facto import Model

    model = Model()
    model.learn({"a": 1.0, "b": 2.0}, 1.0)

    class Diverged:
        def predict_one(self, _features):
            return float("nan")

    model._fm = Diverged()
    assert model.predict({"a": 1.0, "b": 2.0}) == 0.0
    assert not math.isnan(model.predict({"a": 1.0, "b": 2.0}))
