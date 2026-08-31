"""Will this level break? The question nothing here had ever asked.

`up_rate` is the strongest feature for *direction* - weight +2.29 in
learning.md, ten times the next - and predicts a break at AUC 0.4892. Nothing.
That is the evidence these are separate questions rather than two views of one,
and it is why this model exists at all.
"""

from __future__ import annotations

import random

import pytest

from till_infinity.structures.breaking import BROKE, HELD, MIN_SEEN, NAMES, Breaks


class Touch:
    def __init__(self, approach_vol=0.0, depth_vol=0.0):
        self.approach_vol = approach_vol
        self.depth_vol = depth_vol


def teach(model, n=400, seed=3):
    """Fast arrivals break, deep touches hold - the measured directions."""
    rng = random.Random(seed)
    for _ in range(n):
        fast, deep = rng.gauss(0, 1), rng.gauss(0, 1)
        broke = (fast - deep) > 0
        model.observe(Touch(approach_vol=fast, depth_vol=deep), "break" if broke else "reject")
    return model


# ------------------------------------------------------------- what it reads


def test_it_reads_the_two_that_separate():
    assert NAMES == ("approach_vol", "depth_vol")


def test_it_takes_a_plain_dictionary_too():
    """A signal carries its features as a dict, not as a Features object."""
    assert Breaks.inputs({"approach_vol": 1.5, "depth_vol": 0.5}) == [1.5, 0.5]
    assert Breaks.inputs(Touch(approach_vol=1.5, depth_vol=0.5)) == [1.5, 0.5]


def test_a_missing_feature_reads_as_zero_rather_than_shortening_the_vector():
    assert Breaks.inputs({}) == [0.0, 0.0]


# --------------------------------------------------------- what it will say


def test_it_says_nothing_until_it_has_seen_enough():
    """None rather than 0.5: "no opinion" and "an even chance" are different
    claims, and a consumer that cannot tell them apart will act on the second
    when it was handed the first."""
    model = Breaks()
    assert model.predict(Touch(approach_vol=3.0)) is None
    assert model.reading(Touch(approach_vol=3.0)) == {}
    assert not model.warm


def test_it_speaks_once_it_is_warm():
    model = teach(Breaks(), n=int(MIN_SEEN) + 50)
    assert model.warm
    said = model.predict(Touch(approach_vol=1.0, depth_vol=0.0))
    assert said is not None
    assert 0.0 < said < 1.0


def test_a_fast_shallow_arrival_is_likelier_to_break_than_a_slow_deep_one():
    """The whole claim, end to end: arrive hard at a level barely entered and
    it goes; arrive gently having pushed deep into it and it holds."""
    model = teach(Breaks(), n=1200)
    hard = model.predict(Touch(approach_vol=2.0, depth_vol=-1.0))
    gentle = model.predict(Touch(approach_vol=-1.0, depth_vol=2.0))
    assert hard > gentle


def test_the_weights_point_the_way_the_measurement_did():
    """approach_vol positive, depth_vol negative - fitted, not asserted."""
    model = teach(Breaks(), n=1200)
    weights = dict(model.importance())
    assert weights["approach_vol"] > 0
    assert weights["depth_vol"] < 0


# ------------------------------------------------------------ what it learns


def test_chop_is_not_evidence_that_the_level_held():
    """A touch that went nowhere is not a hold, and counting it as one is the
    discipline the rest of the package already applies to chop."""
    model = Breaks()
    before = model.model.seen
    assert model.observe(Touch(), "chop") is None
    assert model.model.seen == before


def test_an_unrecognised_outcome_is_ignored():
    model = Breaks()
    assert model.observe(Touch(), "something new") is None
    assert model.model.seen == 0.0


def test_both_break_outcomes_count_as_breaks():
    for outcome in BROKE:
        model = Breaks()
        model.observe(Touch(approach_vol=1.0), outcome)
        assert model.model.seen == 1.0


def test_both_hold_outcomes_count_as_holds():
    for outcome in HELD:
        model = Breaks()
        model.observe(Touch(approach_vol=1.0), outcome)
        assert model.model.seen == 1.0


def test_it_predicts_before_it_learns():
    """The discipline every model here keeps: `observe` returns what it said
    beforehand, not what it would say now.

    Not bit-identical to a prior `predict`, and the reason is worth knowing.
    `Logistic.observe` updates the **standardiser** with the input before it
    predicts - deliberately, because knowing the distribution of the inputs is
    not knowing the outcome, and refusing that would mean standardising from
    nothing on the first example. The *weights* are untouched until after, which
    is the part that makes the score walk-forward.
    """
    model = teach(Breaks(), n=400)
    touch = Touch(approach_vol=0.4, depth_vol=0.1)
    before = model.predict(touch)
    said = model.observe(touch, "break")
    assert said == pytest.approx(before, abs=1e-3)
    # And the weights did move, which is the other half.
    assert model.predict(touch) > said


# ------------------------------------------------------------- the handover


def test_the_reading_is_floats_for_the_journal():
    model = teach(Breaks(), n=1200)
    got = model.reading(Touch(approach_vol=1.0))
    assert set(got) == {"break_probability", "break_seen"}
    assert all(isinstance(v, float) for v in got.values())


def test_the_service_learns_from_every_resolution_and_publishes_it():
    """A model nothing calls is not a model - this repository shipped that five
    times in two days."""
    import inspect

    from till_infinity.structures import service

    assert "self.breaks.observe(" in inspect.getsource(service.Watcher.record_outcomes)
    assert "self.breaks.reading(" in inspect.getsource(service.Watcher._level_calls)


def test_it_survives_a_restart():
    import inspect

    from till_infinity.structures import service

    assert '"breaks": self.breaks' in inspect.getsource(service.Watcher.save)
    assert 'state.get("breaks"' in inspect.getsource(service.Watcher.load)


def test_the_alert_shows_the_break_risk_when_there_is_one():
    """A number nobody sees is a number nobody can sanity-check, and this one is
    new enough to want checking against what the chart actually did."""
    from till_infinity.structures.models import Shape, Signal
    from till_infinity.structures.service import alert_payload

    signal = Signal(
        shape=Shape.LEVEL,
        feed="gold",
        venue="consensus",
        score=0.3,
        direction="up",
        features={"level": 4400.0, "probability_up": 0.7, "break_probability": 0.62},
    )
    assert "break risk 62%" in alert_payload(signal)["body"]


def test_the_alert_says_nothing_when_the_model_is_cold():
    """Silence rather than 50%, for the same reason `predict` returns None."""
    from till_infinity.structures.models import Shape, Signal
    from till_infinity.structures.service import alert_payload

    signal = Signal(
        shape=Shape.LEVEL,
        feed="gold",
        venue="consensus",
        score=0.3,
        direction="up",
        features={"level": 4400.0, "probability_up": 0.7},
    )
    assert "break risk" not in alert_payload(signal)["body"]


def test_it_reaches_trading_as_a_feature():
    """`trading` copies the signal's features onto the intent, so the estimate
    is journalled beside every decision that was taken while it existed - which
    is what will make it possible to ask later whether it was worth gating on."""
    from till_infinity.trading.models import Intent, Side

    intent = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4395.0,
        target=4410.0,
        features={"break_probability": 0.62},
    )
    assert intent.to_context()["break_probability"] == pytest.approx(0.62)
