"""The learners, and the one discipline that makes their numbers mean anything.

Every model here scores itself **predict-then-update**. A model scored on data
it has trained on reports how well it memorised; one that must answer before it
is told reports what it would have said at the time. Every withdrawn number in
this project came from some version of getting that wrong, so the tests below
check the *order* as carefully as they check the arithmetic.
"""

import math
import random

import pytest

from till_infinity.structures import sequences
from till_infinity.structures.attention import Attention, Embedding
from till_infinity.structures.baseline import NAMES, Bench, vector
from till_infinity.structures.online import Linear, Logistic, Scaler
from till_infinity.structures.returns import FEATURES, Returns


class Touch:
    """Enough of `reactions.Features` to be read by `vector`."""

    def __init__(self, **over):
        for name in NAMES:
            setattr(self, name, over.get(name, 0.0))


# ------------------------------------------------------------- the substrate


def test_a_scaler_returns_the_raw_values_until_it_can_scale():
    scaler = Scaler()
    assert scaler.apply([3.0, 4.0]) == [3.0, 4.0]


def test_a_constant_input_scales_to_zero_rather_than_dividing_by_nothing():
    scaler = Scaler()
    for _ in range(10):
        scaler.observe([5.0, 1.0])
    assert scaler.apply([5.0, 1.0]) == [0.0, 0.0]


def test_a_linear_model_learns_a_line():
    model = Linear(rate=0.05)
    random.seed(1)
    for _ in range(4000):
        x = [random.gauss(0, 1), random.gauss(0, 1)]
        model.observe(x, 2.0 * x[0] - x[1])
    assert model.r2 > 0.9


def test_a_linear_model_reports_nothing_on_noise():
    """The efficient-market answer arriving as a measurement rather than as an
    assumption. That is the whole reason for having it."""
    model = Linear()
    random.seed(2)
    for _ in range(4000):
        model.observe([random.gauss(0, 1), random.gauss(0, 1)], random.gauss(0, 1))
    assert model.r2 < 0.05


def test_a_prediction_is_made_before_the_answer_is_given():
    """The discipline, stated as a test. `observe` must return what the model
    said *beforehand*, not what it would say now."""
    model = Linear(rate=0.5)
    said = model.observe([1.0], 100.0)
    assert said == pytest.approx(0.0)
    assert model.predict([1.0]) != pytest.approx(said)


def test_a_logistic_model_separates_what_is_separable():
    model = Logistic(rate=0.1)
    random.seed(3)
    for _ in range(4000):
        x = [random.gauss(0, 1)]
        model.observe(x, x[0] > 0)
    assert model.accuracy > 0.85
    assert model.edge > 0.3


def test_edge_is_accuracy_above_the_base_rate():
    """63% accuracy on a problem whose base rate is 63% is a model that has
    discovered which answer is commoner."""
    model = Logistic()
    random.seed(4)
    for _ in range(3000):
        model.observe([random.gauss(0, 1)], random.random() < 0.75)
    assert model.base_rate == pytest.approx(0.75, abs=0.05)
    assert abs(model.edge) < 0.08


def test_a_confident_model_on_a_surprising_example_does_not_overflow():
    """Clamped before exp, or one row kills the learner."""
    model = Logistic(rate=1.0)
    for _ in range(200):
        model.observe([50.0], True)
    assert 0.0 < model.predict([50.0]) <= 1.0
    assert math.isfinite(model.log_loss)


def test_the_weights_are_readable_which_the_neighbour_vote_cannot_be():
    model = Logistic(rate=0.1)
    random.seed(5)
    for _ in range(3000):
        useful, noise = random.gauss(0, 1), random.gauss(0, 1)
        model.observe([useful, noise], useful > 0)
    ranked = model.importance(("useful", "noise"))
    assert ranked[0][0] == "useful"


# ------------------------------------------------------------- attention


def test_a_learned_distance_starts_as_the_distance_it_replaces():
    """A comparison that starts from noise measures the training, not the idea."""
    model = Attention()
    model.predict([0.0], [[0.0], [1.0]] * 3, [1.0, 0.0] * 3)
    assert all(w == pytest.approx(1.0) for w in model.weights)


def test_attention_says_nothing_with_too_few_neighbours():
    assert Attention().predict([0.0], [[0.0]], [1.0]) is None


def test_attention_leans_toward_the_nearer_neighbour():
    model = Attention()
    got = model.predict([0.0], [[0.0], [5.0], [5.0], [5.0], [5.0]], [1.0, 0.0, 0.0, 0.0, 0.0])
    assert got is not None
    assert got > 1.0 / 5.0


def test_attention_drops_a_feature_that_separates_nothing():
    """The point of learning the distance: a dimension that is pure noise
    should stop being used to decide who the neighbours are."""
    model = Attention()
    random.seed(6)
    for _ in range(600):
        query = [random.gauss(0, 1), random.gauss(0, 1)]
        keys, values = [], []
        for _ in range(6):
            k = [random.gauss(0, 1), random.gauss(0, 1)]
            keys.append(k)
            values.append(1.0 if k[0] > 0 else 0.0)  # only the first matters
        model.observe(query, keys, values, 1.0 if query[0] > 0 else 0.0)
    ranked = model.importance(("real", "noise"))
    assert ranked[0][0] == "real"


def test_an_attention_weight_never_goes_negative():
    """A negative weight would make a distance a similarity, silently."""
    model = Attention(rate=5.0)
    random.seed(7)
    for _ in range(200):
        keys = [[random.gauss(0, 1)] for _ in range(6)]
        model.observe([0.0], keys, [random.random() for _ in keys], random.random())
    assert all(w >= 0.0 for w in model.weights)


# ------------------------------------------------------------- embeddings


def test_a_level_with_too_little_history_is_not_ranked():
    """A vector made of two nudges is a rumour, and returning it next to one
    made of forty would make them look like the same kind of claim."""
    book = Embedding()
    book.observe("a", [1.0] * 9, True)
    book.observe("b", [1.0] * 9, True)
    assert book.similar("a") == []


def test_levels_that_behaved_alike_end_up_near_each_other():
    book = Embedding()
    for _ in range(5):
        book.observe("holds_one", [1.0, 0.0] * 4 + [0.0], True)
        book.observe("holds_two", [1.0, 0.0] * 4 + [0.0], True)
        book.observe("breaks", [1.0, 0.0] * 4 + [0.0], False)
    near = dict(book.similar("holds_one"))
    assert near["holds_two"] > near["breaks"]


def test_a_vector_is_kept_on_the_unit_sphere():
    """So similarity compares shape rather than how many touches a level had."""
    book = Embedding()
    for _ in range(20):
        book.observe("a", [1.0] * 9, True)
    assert book.of("a").norm() == pytest.approx(1.0)


def test_the_book_can_be_pruned_because_levels_die():
    book = Embedding()
    for i in range(30):
        for _ in range(i + 1):
            book.observe(f"level{i}", [1.0] * 9, True)
    assert book.prune(keep=10) == 20
    assert len(book.vectors) == 10
    # The best-evidenced survive.
    assert "level29" in book.vectors


# ------------------------------------------------------------- sequences


def test_a_leg_becomes_a_symbol_from_its_size_and_direction():
    assert sequences.symbol(0.1) == sequences.FLAT
    assert sequences.symbol(1.0) == "U1"
    assert sequences.symbol(-2.4) == "D2"


def test_a_huge_move_is_just_a_big_move():
    """The difference between six units and nine is not something a few
    thousand observations can say anything about."""
    assert sequences.symbol(99.0) == f"U{sequences.MAX_STEP}"


def test_a_context_is_not_used_until_it_has_been_seen_enough():
    grammar = sequences.Grammar(minimum=5)
    for _ in range(4):
        grammar.learn(["U1"], 1.0)
    assert grammar.predict(["U1"]) is None
    grammar.learn(["U1"], 1.0)
    assert grammar.predict(["U1"]) == pytest.approx(1.0)


def test_a_long_context_backs_off_to_a_shorter_one():
    """Without it the model is silent exactly where it is most confident and
    loud where it has three examples."""
    grammar = sequences.Grammar(minimum=3)
    for _ in range(10):
        grammar.learn(["D1", "U1"], 0.5)
    assert grammar.predict(["U2", "D1", "U1"]) == pytest.approx(0.5)


def test_a_context_reports_how_sure_it_is_rather_than_only_a_mean():
    """A mean of 0.4 over six observations with a sigma of two is noise, and
    the mean alone presents it as a forecast."""
    grammar = sequences.Grammar(minimum=3)
    random.seed(8)
    for _ in range(200):
        grammar.learn(["U1"], random.gauss(0, 2))
    found = grammar.counts["U1"]
    assert abs(found.t) < 3.0
    assert found.sigma > 1.0


def test_a_grammar_scores_itself_walk_forward():
    grammar = sequences.Grammar(minimum=3)
    for _ in range(300):
        grammar.observe(["U1"], 1.0)
        grammar.observe(["D1"], -1.0)
    assert grammar.warm
    assert grammar.r2 > 0.9


def test_a_grammar_can_be_pruned_because_it_runs_forever():
    grammar = sequences.Grammar()
    for i in range(100):
        for _ in range(i + 1):
            grammar.learn([f"U{i % 4 + 1}", str(i)], 1.0)
    assert grammar.prune(keep=20) > 0
    assert len(grammar.counts) == 20


# ------------------------------------------------------------- the returns


def test_a_returns_model_says_nothing_until_it_is_warm():
    model = Returns()
    assert model.observe("gold", "5m", 4400.0, 4.4, {}) is None


def test_a_returns_model_learns_only_when_the_horizon_completes():
    """Walk-forward by construction: nothing is trained on a future it has
    already been asked about."""
    model = Returns(horizon=3)
    for i in range(2):
        model.observe("gold", "5m", 4400.0 + i, 4.4, {"pressure_vol": 1.0})
    assert model.model("gold", "5m").seen == 0.0
    for i in range(2, 8):
        model.observe("gold", "5m", 4400.0 + i, 4.4, {"pressure_vol": 1.0})
    assert model.model("gold", "5m").seen > 0.0


def test_an_absent_feature_reads_as_zero_rather_than_shortening_the_vector():
    """The vector has to be the same width every time or the weights stop
    meaning anything."""
    assert len(Returns.inputs({})) == len(FEATURES)
    assert len(Returns.inputs({"pressure_vol": 1.0})) == len(FEATURES)


def test_pending_predictions_do_not_accumulate_forever():
    model = Returns(horizon=2)
    for i in range(500):
        model.observe("gold", "5m", 4400.0 + i * 0.01, 4.4, {})
    assert len(model.waiting[("gold", "5m")]) <= model.horizon * 4 + 1


# ------------------------------------------------------------- the bench


def test_every_model_is_scored_on_the_same_touches():
    """Two separate runs would compare two samples rather than two models."""
    bench = Bench()
    random.seed(9)
    for _ in range(200):
        depth = random.gauss(0, 1)
        held = depth > 0
        bench.observe(Touch(depth_vol=depth), held, knn_said=0.9 if held else 0.1)
    assert bench.scores["linear"].seen == bench.scores["knn"].seen


def test_the_incumbent_is_scored_beside_the_challenger():
    bench = Bench()
    random.seed(10)
    for _ in range(400):
        depth = random.gauss(0, 1)
        held = depth > 0
        bench.observe(Touch(depth_vol=depth), held, knn_said=1.0 if held else 0.0)
    assert bench.scores["knn"].edge > bench.scores["linear"].edge - 1.0
    assert "knn" in bench.report()


def test_a_bench_with_nothing_in_it_says_so():
    assert Bench().report() == "nothing scored yet"


def test_the_reading_is_all_floats_for_the_journal():
    bench = Bench()
    random.seed(11)
    for _ in range(200):
        bench.observe(Touch(depth_vol=random.gauss(0, 1)), random.random() > 0.5)
    assert all(isinstance(v, float) for v in bench.reading().values())


def test_a_features_object_becomes_a_vector_in_the_compared_order():
    got = vector(Touch(approach_vol=1.0, up_rate=0.75))
    assert len(got) == len(NAMES)
    assert got[0] == 1.0
    assert got[-1] == 0.75


# ------------------------------------------------- the wiring into the service


@pytest.mark.asyncio
async def test_the_bench_sees_resolved_touches():
    """A model nothing calls is not a model. This repository has shipped that
    four times today alone, so the handover gets its own test."""
    import inspect

    from till_infinity.structures import service

    source = inspect.getsource(service.Watcher.record_outcomes)
    assert "self._benchmark(" in source


def test_the_bench_excludes_the_touch_from_its_own_neighbours():
    """It is added to memory during resolution, so it can appear among its own
    neighbours at distance zero and hand every model the answer."""
    import inspect

    from till_infinity.structures import service

    source = inspect.getsource(service.Watcher._benchmark)
    assert "is not touch" in source


def test_the_bench_compares_on_direction_which_is_what_the_knn_predicts():
    import inspect

    from till_infinity.structures import service

    source = inspect.getsource(service.Watcher._benchmark)
    assert "push_vol" in source


def test_the_floor_is_one_feature_and_no_model():
    """The first bench result put the kNN, a logistic model and a learned
    distance within 0.7 points of each other, while the logistic weights put
    `up_rate` at +0.94 and nothing else above +0.34. If reading that one
    feature scores what they score, eight features and the whole neighbour
    machinery are earning nothing - and that is worth knowing precisely rather
    than suspecting."""
    bench = Bench()
    random.seed(12)
    for _ in range(200):
        rate = random.random()
        bench.observe(Touch(up_rate=rate), random.random() < rate)
    assert "up_rate" in bench.scores
    assert bench.scores["up_rate"].edge > 0.1


# ------------------------------------------- one model set per horizon band


def test_intervals_of_comparable_length_share_a_band():
    """1m and 3m can inform each other; 1m and 1w cannot."""
    from till_infinity.structures.reactions import band_of

    assert band_of("3m") == band_of("5m")
    assert band_of("1m") != band_of("1w")
    assert band_of("1d") != band_of("1w")
    assert band_of("nonsense") is None


def test_a_band_is_chosen_from_the_interval_not_the_realised_duration():
    """The band has to be known when the touch *opens*. How long it takes to
    resolve is the future, and choosing neighbours by it would be selecting the
    training set with the answer."""
    import inspect

    from till_infinity.structures import reactions

    source = inspect.getsource(reactions.band_of)
    assert "SECONDS" in source
    assert "resolved" not in source


def test_a_slow_touch_does_not_draw_neighbours_from_fast_ones():
    """The flaw research/similarity.md found, and it is in the training set
    rather than the report: a touch approached from above that resolves inside
    a minute resolves upward 100.0% of the time, so a weekly touch drawing from
    there learns the definition of a rejection."""
    from till_infinity.structures.levels import Side
    from till_infinity.structures.reactions import Features, Memory, Outcome, Touch

    def touch(interval, up):
        return Touch(
            outcome=Outcome.REJECT,
            feed="gold",
            interval=interval,
            level_price=4400.0,
            features=Features(
                side=Side.ABOVE,
                approach_vol=1.0,
                depth_vol=0.0,
                strength=0.0,
                run_vol=0.0,
                experience=0.0,
            ),
            started=0.0,
            resolved=1.0,
            entry=4400.0,
            extreme=4400.0,
            push_vol=1.0 if up else -1.0,
        )

    memory = Memory(k=3)
    for _ in range(50):
        memory.add(touch("1m", up=True))
    for _ in range(10):
        memory.add(touch("1w", up=False))

    want = Features(
        side=Side.ABOVE,
        approach_vol=1.0,
        depth_vol=0.0,
        strength=0.0,
        run_vol=0.0,
        experience=0.0,
    )
    weekly = memory.neighbours(want, "1w")
    assert weekly
    assert all(t.interval == "1w" for _d, t in weekly)


def test_a_thin_band_widens_outward_and_says_so():
    """Bands are thin by construction - 1,762 resolved touches beyond thirty
    minutes against 30,118 under a minute - so a strict band leaves the slow
    end with nothing, which is the cold-start problem pooling solved."""
    from till_infinity.structures.levels import Side
    from till_infinity.structures.reactions import Features, Memory, Outcome, Touch

    memory = Memory(k=12)
    want = Features(
        side=Side.ABOVE,
        approach_vol=1.0,
        depth_vol=0.0,
        strength=0.0,
        run_vol=0.0,
        experience=0.0,
    )
    for _ in range(30):
        memory.add(
            Touch(
                outcome=Outcome.REJECT,
                feed="gold",
                interval="5m",
                level_price=4400.0,
                features=want,
                started=0.0,
                resolved=1.0,
                entry=4400.0,
                extreme=4400.0,
                push_vol=1.0,
            )
        )
    before = memory.widened
    found = memory.neighbours(want, "15m")  # its own band is empty
    assert found
    assert memory.widened > before


def test_the_bench_keeps_one_model_set_per_band():
    """Banding has to reach the *training*, not only the report: a parametric
    model fitted on the pooled stream learns the fast tautology and carries it
    into its predictions about slow touches."""
    bench = Bench()
    random.seed(21)
    for _ in range(120):
        bench.observe(Touch(depth_vol=random.gauss(0, 1)), True, knn_said=0.9, interval="1m")
        bench.observe(Touch(depth_vol=random.gauss(0, 1)), False, knn_said=0.9, interval="1w")
    from till_infinity.structures.reactions import band_of

    fast = bench.band(band_of("1m"))
    slow = bench.band(band_of("1w"))
    assert fast.scores["knn"].accuracy != slow.scores["knn"].accuracy
    assert fast.linear.weights != slow.linear.weights


def test_the_pooled_row_is_kept_and_labelled():
    """It is what every earlier number here was, and the gap between it and the
    bands is the size of the mistake."""
    bench = Bench()
    random.seed(22)
    for _ in range(60):
        bench.observe(Touch(up_rate=0.9), True, knn_said=0.9, interval="1m")
    text = bench.report()
    assert "pooled" in text
    assert "horizon" in text


def test_a_reading_for_one_interval_is_that_band_s():
    """A pooled edge on a signal is the tautology's edge, not this call's."""
    bench = Bench()
    random.seed(23)
    for _ in range(80):
        bench.observe(Touch(up_rate=0.9), True, knn_said=0.9, interval="1m")
    banded = bench.reading("1m")
    pooled = bench.reading()
    assert banded
    assert set(banded) == set(pooled)
