"""Will this level break? The question nothing here had ever asked.

`up_rate` is the strongest feature for *direction* - weight +2.29 in
learning.md, ten times the next - and predicts a break at AUC 0.4892. Nothing.
That is the evidence these are separate questions rather than two views of one,
and it is why this model exists at all.
"""

from __future__ import annotations

import random

import pytest

from till_infinity.structures.learning.breaking import BROKE, HELD, MIN_SEEN, NAMES, Breaks


class Touch:
    def __init__(
        self,
        approach_vol=0.0,
        depth_vol=0.0,
        slowing=0.0,
        slope=0.0,
        prior_slope=0.0,
        interval_log=0.0,
    ):
        self.approach_vol = approach_vol
        self.depth_vol = depth_vol
        self.slowing = slowing
        self.slope = slope
        self.prior_slope = prior_slope
        self.interval_log = interval_log


def teach(model, n=400, seed=3):
    """Fast arrivals break, deep touches hold - the measured directions."""
    rng = random.Random(seed)
    for _ in range(n):
        fast, deep = rng.gauss(0, 1), rng.gauss(0, 1)
        broke = (fast - deep) > 0
        model.observe(Touch(approach_vol=fast, depth_vol=deep), "break" if broke else "reject")
    return model


# ------------------------------------------------------------- what it reads


def test_it_reads_the_features_that_separate():
    """`slowing` earns its place by being nearly orthogonal to `approach_vol` -
    correlation +0.008 - rather than by being strong. A weak separator that
    disagrees adds; a strong one that agrees restates.

    The two slope terms were added on the same argument and a measured lift:
    0.6104 to 0.6408 AUC, out of sample, over 5,452 five-minute touches.
    """
    assert NAMES == (
        "approach_vol",
        "depth_vol",
        "slowing",
        "slope",
        "prior_slope",
        "interval_log",
    )


def test_it_takes_a_plain_dictionary_too():
    """A signal carries its features as a dict, not as a Features object."""
    got = {
        "approach_vol": 1.5,
        "depth_vol": 0.5,
        "slowing": 0.8,
        "slope": 0.2,
        "prior_slope": 0.4,
        "interval_log": 6.8,
    }
    assert Breaks.inputs(got) == [1.5, 0.5, 0.8, 0.2, 0.4, 6.8]
    assert Breaks.inputs(
        Touch(
            approach_vol=1.5,
            depth_vol=0.5,
            slowing=0.8,
            slope=0.2,
            prior_slope=0.4,
            interval_log=6.8,
        )
    ) == [1.5, 0.5, 0.8, 0.2, 0.4, 6.8]


def test_a_missing_feature_reads_as_zero_rather_than_shortening_the_vector():
    assert Breaks.inputs({}) == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_the_slope_is_read_as_a_magnitude():
    """Which way the fit points is a different question from whether the level
    survives, and a signed slope would ask a linear model to learn that steep
    up and steep down both break - the one shape it cannot represent."""
    down = Breaks.inputs({"slope": -0.9, "prior_slope": -1.4, "approach_vol": -2.0})
    up = Breaks.inputs({"slope": 0.9, "prior_slope": 1.4, "approach_vol": -2.0})
    assert down == up
    # And only the slopes are folded; the rest keep their sign.
    assert down[0] == -2.0


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


# --------------------------------------------------- the gate every strategy runs


def _gate(risk=None, ceiling=0.42):
    """Run the shared quality gate with a break estimate on the call."""
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings
    from till_infinity.trading.models import Side

    engine = td.STRATEGIES["level-scalp"](
        Settings(max_break_risk=ceiling, min_probability=0.0, min_edge=0.0, min_base_rate=0.0)
    )
    features = {"probability": 0.9, "edge": 0.5, "base_rate_up": 0.5}
    if risk is not None:
        features["break_probability"] = risk
    return engine.quality("gold", features, Side.BUY, "5m")


def test_a_level_likely_to_give_way_is_refused():
    """The top fifth by this estimate breaks 43.2% of the time against the
    bottom fifth's 16.9%, so the call is right 56.8% there against 83.1%."""
    got = _gate(risk=0.62)
    assert got is not None
    assert got.gate == "break_risk"
    assert "62%" in got.detail


def test_a_level_below_the_ceiling_passes():
    assert _gate(risk=0.20) is None


def test_the_gate_is_off_by_default():
    """A gate that refuses trades is turned on deliberately - and the numbers
    behind this one were wrong once already."""
    from till_infinity.trading.config import Settings

    assert Settings().max_break_risk == 0.0
    assert _gate(risk=0.99, ceiling=0.0) is None


def test_a_call_with_no_estimate_is_not_refused():
    """Silence is the honest state until the model has 200 resolutions behind
    it. A level call with no break reading is not one with a low reading."""
    assert _gate(risk=None) is None


def test_every_strategy_runs_it_rather_than_one():
    """`quality` exists because `FadeToValue` overrode `consider` entirely and
    therefore ran none of the gates - the exemption was invisible from the
    configuration and the exempt strategy was taking most of the trades."""
    import inspect

    from till_infinity.trading.strategies import scalper

    assert "max_break_risk" in inspect.getsource(scalper.LevelStrategy.quality)


def test_the_outcome_records_which_timeframes_agreed():
    """It was on the signal and on the touch and not on the outcome, so all
    12,504 resolutions recorded zero timeframes and "does agreement across
    timeframes predict anything" could not be asked of the only record that
    can answer it."""
    import inspect

    from till_infinity.structures import service

    source = inspect.getsource(service.Watcher.record_outcomes)
    assert '"confluence": touch.confluence' in source
    assert '"confluence_n"' in source


def test_deceleration_needs_no_new_state():
    """It was parked for a day on a guess about the plumbing. The series window
    already holds five hundred closes, so this reads six where `_speed` reads
    two."""
    from till_infinity.structures.engine import Engine

    engine = Engine()
    assert engine._slowing("nothing", "5m") == 0.0


# ------------------------------------------------- the slope, end to end


class _Vol:
    bps = 10.0
    warm = True
    tick = 0.01


def test_the_slope_is_zero_without_enough_series():
    """Forty closes, because the pair needs two windows. Zero reads as "no
    reading" everywhere downstream."""
    from till_infinity.structures.engine import Engine

    engine = Engine()
    assert engine._slope("nothing", "5m", _Vol()) == (0.0, 0.0)


def _drive(engine, feed, interval, prices):
    for price in prices:
        engine._bar(feed, interval, price)


def test_the_engine_publishes_the_slope_onto_the_touch():
    """The check this repository keeps failing: computed correctly, recorded
    where nothing reads it. `Breaks.inputs` names them, so the features object
    has to carry them or every touch scores zero forever."""
    import dataclasses
    import inspect

    from till_infinity.structures import reactions
    from till_infinity.structures.learning.breaking import NAMES

    carried = {f.name for f in dataclasses.fields(reactions.Features)}
    for name in NAMES:
        assert name in carried, f"{name} is in NAMES and not on the features"

    # And published, not merely held: `Breaks` reads a signal's dictionary.
    published = inspect.getsource(reactions.Features.to_dict)
    for name in NAMES:
        assert f'"{name}"' in published, f"{name} never reaches the signal"

    # And threaded through the builder the engine calls.
    builder = inspect.signature(reactions.features_for).parameters
    assert "slope" in builder
    assert "prior_slope" in builder


def test_the_engine_actually_calls_the_slope():
    """A feature the engine computes and does not pass on is the defect that
    left STRUCTURES_FORMATION inert for its whole life."""
    import inspect

    from till_infinity.structures import engine as eng

    source = inspect.getsource(eng.Engine)
    assert "self._slope(feed, interval, vol)" in source
    assert '"slope", "prior_slope"' in source


def test_slowing_is_bounded():
    """It is a ratio and its denominator can be almost zero. The break model's
    own standardiser had a running mean of 141,380,329 for this feature against
    1.36 for `approach_vol` - one input eight orders of magnitude wider than
    its neighbours, which makes every other weight rescale whenever a new
    extreme lands."""
    from till_infinity.structures.engine import SLOWING_CAP, Engine

    assert SLOWING_CAP == 10.0
    src = __import__("inspect").getsource(Engine._slowing)
    assert "min(after / before, SLOWING_CAP)" in src


def test_a_changed_recipe_drops_the_saved_model():
    """A fix to an input is not a fix if the statistics describing it survive.

    `slowing` was capped at 10.0 while its running mean in the standardiser was
    141,380,329. `Scaler` is plain Welford with no decay, so at n=5,256 a
    clamped observation moves the mean by (10 - 141M)/5256 and recovery would
    take on the order of 1e11 samples. The cap read as done and changed
    nothing.
    """
    from till_infinity.structures.learning.breaking import RECIPE, Breaks

    trained = teach(Breaks(), n=int(MIN_SEEN) + 50)
    assert trained.warm
    before = trained.model.seen

    # Same recipe: nothing is thrown away.
    trained.observe(Touch(approach_vol=1.0), "reject")
    assert trained.model.seen >= before
    assert trained.warm

    # A different one: it starts again rather than trusting stale statistics.
    stale = teach(Breaks(), n=int(MIN_SEEN) + 50)
    stale.recipe = "trained when slowing was unbounded"
    stale.observe(Touch(approach_vol=1.0), "reject")
    assert stale.recipe == RECIPE
    assert stale.model.seen <= 1.0
    assert not stale.warm


def test_adding_an_input_is_already_handled():
    """`Logistic` and `Scaler` rebuild on a length change, so the recipe is for
    re-*meaning* an input rather than adding one."""
    import inspect

    from till_infinity.structures.learning import online

    assert "len(x) != len(self.mean)" in inspect.getsource(online.Scaler.observe)


def test_every_unbounded_ratio_in_the_record_is_bounded():
    """Measured on 2026-09-03 over the published record. Four fields had a max
    more than a hundred times their own 99th percentile:

    | field | median | p99 | max |
    | --- | --- | --- | --- |
    | forecast_ratio | 1.12 | 629 | 132,923,621,621 |
    | slowing | 1.00 | 67.6 | 934,584,883,610 |
    | reward_to_risk | 0.364 | 13.2 | 15,846 |
    | push_sigma_vol | 0.51 | 3.43 | 22,415 |

    A guard against a zero denominator is not a guard against a small one, and
    one such field disabled the break model for weeks without breaking it - see
    research/standardising.md.
    """
    import inspect

    from till_infinity.structures import engine, levels, reactions
    from till_infinity.structures.vol import har

    assert har.RATIO_CAP == 10.0
    assert reactions.RR_CAP == 20.0
    assert levels.SIGMA_CAP == 20.0
    assert engine.SLOWING_CAP == 10.0

    # Applied, not merely defined. A constant nothing multiplies is decoration.
    # `fget` because these are properties, and `getsource` wants the function.
    assert "RATIO_CAP)" in inspect.getsource(har.Har.ratio.fget)
    assert "SIGMA_CAP)" in inspect.getsource(levels.SideStats.push_sigma.fget)
    assert "RR_CAP)" in inspect.getsource(reactions.Inference.reward_to_risk.fget)
    assert "SLOWING_CAP)" in inspect.getsource(engine.Engine._slowing)


def test_the_caps_sit_above_the_measured_ninety_ninth_percentile():
    """Except `slowing`, deliberately: its p99 is 67.6, which is already the
    denominator talking rather than a real acceleration."""
    from till_infinity.structures import levels, reactions
    from till_infinity.structures.vol import har

    assert har.RATIO_CAP > 1.12 * 5
    assert reactions.RR_CAP > 13.2
    assert levels.SIGMA_CAP > 3.43


def test_the_timeframe_reaches_the_model():
    """The largest single separator on this book: break rate by the interval a
    level was drawn on runs 57.9% at 1m to 1.4% at 1h over 126,296
    resolutions. It was invisible because every other feature is scale-free by
    construction, which is exactly why it is orthogonal to them."""
    from till_infinity.structures.engine import _interval_log
    from till_infinity.structures.learning.breaking import NAMES
    from till_infinity.structures.reactions import Features

    assert "interval_log" in NAMES
    assert "interval_log" in {f.name for f in __import__("dataclasses").fields(Features)}
    assert _interval_log("1m") < _interval_log("15m") < _interval_log("4h")
    # An interval the table does not know reads as no reading, not as a fast one.
    assert _interval_log("nonsense") == 0.0
    assert _interval_log("") == 0.0


def test_lengthening_the_vector_bumps_the_recipe():
    """`Scaler` silently returns raw values when the vector length changes, so
    a longer feature set without a reset standardises new inputs against
    statistics gathered for a shorter one. That is the trap in
    research/inert.md, and the recipe is what avoids walking into it."""
    from till_infinity.structures.learning.breaking import NAMES, RECIPE

    assert len(NAMES) == 6
    assert "interval_log" in RECIPE


def test_the_learning_rate_favours_a_stable_gate():
    """Swept over the whole record: 0.05 scored 0.7304 AUC at 2.751 drift per
    100 observations, 0.02 scored 0.7206 at 1.110. Accuracy saturates long
    before stability does, and `max_break_risk` acts on this model's output -
    at the old rate the live weights moved 1.652, 1.174, 1.840 and 1.441 in
    four consecutive half-hours."""
    from till_infinity.structures.learning.breaking import RATE, Breaks

    assert RATE == 0.02
    assert Breaks().model.rate == RATE
    # And a restart uses the same one rather than a second copy of the number.
    model = Breaks()
    model.recipe = "something older"
    model.observe(Touch(approach_vol=1.0), "reject")
    assert model.model.rate == RATE
