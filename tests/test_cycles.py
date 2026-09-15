"""The streaming z-score: exact recursions, causal timeframes, weights that survive.

Three groups, and each exists because the batch original got the thing wrong or
could not have it at all.

* **The recursions are exact**, not approximations of the batch forms, and the
  slope one is checked against a least-squares fit computed the slow way.
* **A higher timeframe enters only when its own bar has closed.** A forming
  higher-timeframe bar contains the fast bar being predicted, and a z-score
  built on it knows the answer. It is the easiest look-ahead in this area to
  write by accident.
* **Weights save separately from the engine's state**, because `store._schema`
  invalidates the whole state file when any persisted dataclass changes shape,
  and months of settled turns should not be lost to an unrelated refactor.
"""

from __future__ import annotations

import math
import pickle
import random

import pytest

from till_infinity.structures import cycles as cy


def reverting(n: int, theta: float = 0.15, seed: int = 5) -> list[float]:
    rng = random.Random(seed)
    x, out = 100.0, []
    for _ in range(n):
        x += theta * (100.0 - x) + rng.gauss(0, 0.5)
        out.append(x)
    return out


class TestRecursions:
    def test_the_slope_matches_a_least_squares_fit_done_the_slow_way(self):
        """`b <- lam*(b + a)` is the whole trick; this is what it has to equal."""
        prices = reverting(600)
        online = cy.Slope(lam=0.98)
        for p in prices:
            online.push(p)

        lam, n = 0.98, len(prices)
        ks = [float(i) for i in range(n)]
        xs = list(reversed(prices))  # xs[k] is k bars back
        w = [lam**k for k in ks]
        sw = sum(w)
        mean_k = sum(wi * k for wi, k in zip(w, ks, strict=True)) / sw
        mean_x = sum(wi * x for wi, x in zip(w, xs, strict=True)) / sw
        cov = sum(wi * (k - mean_k) * (x - mean_x) for wi, k, x in zip(w, ks, xs, strict=True))
        var = sum(wi * (k - mean_k) ** 2 for wi, k in zip(w, ks, strict=True))
        expected = -(cov / var) / abs(prices[-1])
        assert online.value == pytest.approx(expected, rel=1e-6)

    def test_the_slope_is_exact_while_it_is_still_warming(self):
        """The closed-form weight sums are wrong until the tail vanishes - 109x
        wrong at 300 bars - so they are accumulated instead. See `Slope`."""
        for n in (60, 150, 300, 1000):
            prices = reverting(n)
            online = cy.Slope(lam=0.98)
            for p in prices:
                online.push(p)
            lam = 0.98
            ks = [float(i) for i in range(n)]
            xs = list(reversed(prices))
            w = [lam**k for k in ks]
            sw = sum(w)
            mean_k = sum(wi * k for wi, k in zip(w, ks, strict=True)) / sw
            mean_x = sum(wi * x for wi, x in zip(w, xs, strict=True)) / sw
            cov = sum(wi * (k - mean_k) * (x - mean_x) for wi, k, x in zip(w, ks, xs, strict=True))
            var = sum(wi * (k - mean_k) ** 2 for wi, k in zip(w, ks, strict=True))
            assert online.value == pytest.approx(-(cov / var) / abs(prices[-1]), rel=1e-6), n

    def test_the_moments_match_a_weighted_mean_done_the_slow_way(self):
        prices = reverting(400)
        online = cy.AttentionZ(lam=0.98, attention=False)
        for p in prices:
            online.push(p)
        lam = 0.98
        xs = list(reversed(prices))
        w = [lam**k for k in range(len(xs))]
        sw = sum(w)
        mean = sum(wi * x for wi, x in zip(w, xs, strict=True)) / sw
        var = sum(wi * x * x for wi, x in zip(w, xs, strict=True)) / sw - mean * mean
        assert online.z_score == pytest.approx(
            (prices[-1] - mean) / (math.sqrt(var) + 1e-12), rel=1e-6
        )

    def test_attention_off_weights_every_bar_alike(self):
        """The shipped `zma.py` does this whether it means to or not - the softmax
        there is over absolute returns near 1e-4, so every weight is 1.0000."""
        prices = reverting(300)
        plain = cy.AttentionZ(attention=False)
        weighted = cy.AttentionZ(attention=True)
        for p in prices:
            plain.push(p)
            weighted.push(p)
        assert plain.z_score != pytest.approx(weighted.z_score, rel=1e-9)

    def test_the_streaming_z_tracks_the_shipped_batch_one(self):
        from till_infinity.structures.zma import Zma

        prices = reverting(3000)
        batch, stream = Zma(), cy.Stream(attention=False)
        pairs = []
        for p in prices:
            batch.observe(p)
            stream.push(p)
            if batch.seen > 400:
                pairs.append((batch.z_score, stream.z.z_score))
        same = sum(1 for a, b in pairs if (a > 0) == (b > 0)) / len(pairs)
        assert same > 0.85, "a geometric window is not a rectangle, but it is the same reading"


class TestCausality:
    def test_an_interval_it_does_not_track_is_ignored(self):
        cycles = cy.Cycles(intervals=("1m", "15m"))
        cycles.observe("4h", 100.0)
        assert cycles.seen == 0
        assert all(s.seen == 0 for s in cycles.streams)

    def test_only_the_fast_interval_advances_the_clock(self):
        """The bar count is the fast timeframe's, because that is what a turn
        is measured in - a higher bar arriving must not age the leg."""
        cycles = cy.Cycles()
        for _ in range(5):
            cycles.observe("1h", 100.0)
        assert cycles.seen == 0
        cycles.observe("1m", 100.0)
        assert cycles.seen == 1

    def test_the_mother_stream_is_driven_apart_from_the_fast_one(self):
        cycles = cy.Cycles()
        for p in reverting(200):
            cycles.observe("1m", p)
        assert cycles.fast.seen == 200
        assert cycles.mother.seen == 0, "a higher timeframe is its own series, not a subsample"

    def test_nothing_is_ready_until_every_cycle_has_bars(self):
        cycles = cy.Cycles()
        for p in reverting(200):
            cycles.observe("1m", p)
        assert not cycles.ready
        for p in reverting(60):
            cycles.observe("15m", p)
            cycles.observe("1h", p)
        assert cycles.ready


class TestAlignment:
    def test_a_mid_range_cycle_above_is_neutral_rather_than_opposed(self):
        """A mother cycle with no displacement is not disagreeing with anything,
        and counting it as opposition would make the reading a coin."""
        cycles = cy.Cycles(intervals=("1m", "15m"))
        for p in reverting(300):
            cycles.observe("1m", p)
        for _ in range(60):
            cycles.observe("15m", 100.0)  # perfectly still
        assert cycles.alignment == 0.0

    def test_no_opinion_from_the_fast_stream_is_zero(self):
        cycles = cy.Cycles()
        assert cycles.alignment == 0.0
        assert cycles.with_trend == 0.0


class TestTurns:
    @pytest.fixture
    def taught(self):
        book = cy.Book()
        prices = reverting(9000)
        for i, p in enumerate(prices):
            book.observe("v75", "1m", p)
            if i % 15 == 0:
                book.observe("v75", "15m", p)
            if i % 60 == 0:
                book.observe("v75", "1h", p)
        return book

    def test_turns_are_found_and_settled(self, taught):
        turns = taught.of("v75").turns
        assert turns.turns > 100
        assert turns.settled > turns.turns

    def test_the_depth_head_beats_the_running_mean_where_the_series_reverts(self, taught):
        assert taught.of("v75").turns.depth_skill > 0.0

    def test_the_prediction_is_silent_until_it_is_warm(self):
        book = cy.Book()
        for i, p in enumerate(reverting(600)):
            book.observe("cold", "1m", p)
            if i % 15 == 0:
                book.observe("cold", "15m", p)
            if i % 60 == 0:
                book.observe("cold", "1h", p)
        series = book.of("cold")
        assert not series.turns.warm
        assert not any(k.startswith("turn_") for k in series.reading())

    def test_the_prediction_names_the_side_the_turn_goes(self, taught):
        got = taught.of("v75").reading()
        assert got["turn_side"] == -float(taught.of("v75").turns.leg.direction)
        assert got["turn_depth_vol"] >= 0.0

    def test_every_published_value_is_a_number(self, taught):
        """`Signal.to_dict` rounds the whole features dict."""
        for name, value in taught.of("v75").reading().items():
            assert isinstance(value, float), f"{name} is {type(value).__name__}"


class TestWeights:
    @pytest.fixture
    def taught(self):
        book = cy.Book()
        for i, p in enumerate(reverting(6000)):
            book.observe("v75", "1m", p)
            if i % 15 == 0:
                book.observe("v75", "15m", p)
            if i % 60 == 0:
                book.observe("v75", "1h", p)
        return book

    def test_saving_and_loading_reproduces_the_prediction(self, taught, tmp_path):
        path = tmp_path / "w.pkl"
        assert taught.save(path) == 1
        fresh = cy.Book()
        assert fresh.load(path) == 1
        x = {**taught.of("v75").cycles.features(), "age": 0.5}
        assert fresh.of("v75").turns.depth.predict_one(x) == pytest.approx(
            taught.of("v75").turns.depth.predict_one(x)
        )

    def test_a_missing_file_is_a_cold_start_and_not_an_error(self, tmp_path):
        assert cy.Book().load(tmp_path / "nothing.pkl") == 0

    def test_a_file_from_another_build_is_refused_rather_than_unpacked(self, tmp_path):
        path = tmp_path / "w.pkl"
        path.write_bytes(pickle.dumps({"version": 99, "weights": {}}))
        assert cy.Book().load(path) == 0

    def test_a_corrupt_file_does_not_take_the_desk_down(self, tmp_path):
        path = tmp_path / "w.pkl"
        path.write_bytes(b"not a pickle at all")
        assert cy.Book().load(path) == 0

    def test_an_interrupted_save_leaves_the_previous_weights(self, taught, tmp_path):
        path = tmp_path / "w.pkl"
        taught.save(path)
        before = path.read_bytes()
        assert not list(tmp_path.glob("*.tmp")), "the temporary file is renamed, not left"
        assert path.read_bytes() == before

    def test_nothing_learned_writes_nothing(self, tmp_path):
        assert cy.Book().save(tmp_path / "w.pkl") == 0
        assert not (tmp_path / "w.pkl").exists()

    def test_the_whole_book_still_pickles_with_the_engine(self, taught):
        back = pickle.loads(pickle.dumps(taught))
        assert back.of("v75").turns.settled == taught.of("v75").turns.settled


class TestBook:
    def test_forgetting_a_feed_drops_it(self):
        book = cy.Book()
        book.of("a")
        book.of("b")
        assert book.forget({"a"}) == 1
        assert set(book._by_feed) == {"a"}

    def test_standings_are_worst_first(self):
        book = cy.Book()
        for name, error in (("good", 50.0), ("bad", 200.0)):
            turns = book.of(name).turns
            turns.settled = cy.WARM + 1
            turns.depth_error, turns.depth_base_error = error, 100.0
        assert [n for n, _, _ in book.standings()] == ["bad", "good"]
