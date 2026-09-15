"""The z-score reaches the journal and the gate, and cannot quietly reach a trade.

Three joins, each of which was broken or absent when this was written:

* **`to_signal` is handed the reading.** It is a method on `Call`, which has no
  engine and therefore no book to ask - the first attempt reached for
  `self.zma.of(feed, interval)` from a scope with none of the three, and did not
  compile. The reading is a parameter now, the way `vol` already is.
* **What it publishes is numeric.** `Signal.features` is `dict[str, float]` and
  `to_dict` rounds every value, so the obvious `"zma_state": "oversold"` raises
  at publication time rather than at the call site.
* **The gate can only remove trades, and only when asked.** The measured record
  is a coin on this desk's instruments and worse than one on Boom and Crash, so
  agreement buys nothing; `TRADING_ZMA_GATE` decides whether even the veto runs.
"""

from __future__ import annotations

import math
import random

import pytest

from till_infinity.structures import zma as zm
from till_infinity.structures.engine import _zma_context
from till_infinity.trading.config import Settings
from till_infinity.trading.strategies.scalper import CycleScalp, zma_gate


def wound(z: zm.Zma, *, agrees: int) -> zm.Zma:
    """A reading holding a stated agreement, without simulating bars to get one.

    The agreement condition is deliberately strict - the percentile thresholds
    mean a series makes a call every forty-odd bars - so driving one out of
    synthetic prices tests the generator rather than the wiring.
    """
    z.seen = 50
    z.strong = 1.0
    z.z_score = -2.0 if agrees > 0 else 2.0
    z.slope = 1.0 if agrees > 0 else -1.0
    assert z.agrees == agrees
    return z


class TestContext:
    def test_cold_publishes_nothing(self):
        """Absent, not zero: a zero here reads downstream as a measurement."""
        assert _zma_context(zm.Zma()) == {}

    def test_absent_reading_publishes_nothing(self):
        assert _zma_context(None) == {}

    def test_every_published_value_is_a_number(self):
        """`Signal.to_dict` rounds the whole features dict."""
        published = _zma_context(wound(zm.Zma(), agrees=1))
        assert published
        for name, value in published.items():
            assert isinstance(value, float), f"{name} is {type(value).__name__}"
            assert round(value, 6) == pytest.approx(value)

    def test_the_state_is_recoverable_from_what_is_published(self):
        """The word was dropped; the two numbers that define it were not."""
        published = _zma_context(wound(zm.Zma(), agrees=-1))
        assert published["zma_z"] > published["zma_strong"]

    def test_a_broken_reading_is_silent(self):
        class Angry:
            seen = 50

            def __getattr__(self, name):
                raise RuntimeError("no reading")

        assert _zma_context(Angry()) == {}

    def test_disabled_publishes_nothing(self, monkeypatch):
        monkeypatch.setattr(zm, "ENABLED", False)
        assert _zma_context(wound(zm.Zma(), agrees=1)) == {}


UP = {"direction": "up", "feed": "v75"}
DOWN = {"direction": "down", "feed": "v75"}


def reading(z: float, *, calls: float = 400.0, hit: float = 0.60) -> dict:
    """A published z-score with a stated record behind it."""
    return {
        "zma_z": z,
        "zma_strong": 1.0,
        "zma_agrees": -1.0 if z > 0 else 1.0,
        "zma_edge_calls": calls,
        "zma_edge_right": calls * hit,
    }


class TestGate:
    @pytest.fixture
    def strategy(self):
        settings = Settings()
        settings.zma_gate = True
        found = CycleScalp(settings=settings)
        assert found.settings.zma_gate
        return found

    def test_off_by_default(self):
        """The flag, not the reading, is what decides whether this runs at all."""
        assert Settings().zma_gate is False
        plain = CycleScalp(settings=Settings())
        assert zma_gate(plain, UP, reading(2.0)) is None

    def test_refuses_a_call_the_z_score_leans_against(self, strategy):
        refusal = zma_gate(strategy, UP, reading(2.0))
        assert refusal is not None
        assert refusal.gate == "zma_against"
        assert "overbought" in refusal.detail

    def test_agreement_does_not_add_a_trade(self, strategy):
        """It returns None either way - the difference is only ever a refusal."""
        assert zma_gate(strategy, UP, reading(-2.0)) is None
        assert zma_gate(strategy, UP, reading(0.5)) is None

    def test_both_sides(self, strategy):
        assert zma_gate(strategy, DOWN, reading(-2.0)) is not None
        assert zma_gate(strategy, DOWN, reading(2.0)) is None

    def test_inside_its_own_band_is_most_bars_and_is_not_a_lean(self, strategy):
        assert zma_gate(strategy, UP, reading(0.99)) is None

    def test_a_call_with_no_direction_is_not_this_gate_s_refusal(self, strategy):
        """`direction` is refused upstream, and two refusals for one fault is worse."""
        assert zma_gate(strategy, {"feed": "v75"}, reading(2.0)) is None

    def test_a_cold_call_carries_no_reading_and_passes(self, strategy):
        assert zma_gate(strategy, UP, {}) is None


class TestTheRecordDecides:
    """The condition that keeps this gate off Boom and Crash without a family list.

    Those series drift one way and spike the other, so the drift leaves the
    z-score persistently stretched and the spike is what turns it back - a
    reading taken then calls for continuation as the drift resumes.
    `research/adapting.md` measured the flag at a 0.119 and 0.164 hit rate
    there. A veto driven by that would refuse the correct side, most
    confidently on the instruments where one loss is largest.
    """

    @pytest.fixture
    def strategy(self):
        settings = Settings()
        settings.zma_gate = True
        return CycleScalp(settings=settings)

    def test_a_feed_with_no_record_is_not_vetoed(self, strategy):
        assert zma_gate(strategy, UP, reading(2.0, calls=10.0)) is None

    def test_a_feed_whose_z_score_is_a_coin_is_not_vetoed(self, strategy):
        assert zma_gate(strategy, UP, reading(2.0, hit=0.50)) is None

    def test_a_feed_whose_z_score_is_an_anti_signal_is_not_vetoed(self, strategy):
        """0.119 is what Boom measured. The gate must be silent there, not inverted."""
        assert zma_gate(strategy, UP, reading(2.0, hit=0.119)) is None

    def test_a_feed_that_has_earned_it_is_vetoed(self, strategy):
        refusal = zma_gate(strategy, UP, reading(2.0, calls=400.0, hit=0.60))
        assert refusal is not None
        assert "60% of 400 calls" in refusal.detail

    def test_the_margin_over_a_coin_is_what_moves_the_line(self, strategy):
        just_under = reading(2.0, hit=strategy.settings.zma_min_accuracy)
        assert zma_gate(strategy, UP, just_under) is None
        assert zma_gate(strategy, UP, reading(2.0, hit=0.60)) is not None


class TestBook:
    def test_forgetting_a_feed_drops_every_timeframe_of_it(self):
        book = zm.Book()
        for interval in ("1m", "5m", "1h"):
            book.of("v75", interval)
            book.of("v25", interval)
        assert book.forget({"v75"}) == 3
        assert {feed for feed, _ in book._by_key} == {"v75"}

    def test_standings_are_worst_first(self):
        book = zm.Book()
        for name, right in (("good", 180), ("bad", 40)):
            z = book.of(name, "1m")
            z.calls, z.right = 200, right
        assert [name for name, _, _ in book.standings()] == ["bad 1m", "good 1m"]

    def test_a_series_that_has_not_called_enough_is_not_ranked(self):
        book = zm.Book()
        z = book.of("young", "1m")
        z.calls, z.right = zm.WARM - 1, 0
        assert book.standings() == []


class TestWindow:
    """`period` and `lookback` were decorative, and silently so.

    A `default_factory` is evaluated with no access to the instance, so
    `deque(maxlen=PERIOD)` captured the module constant: `Zma(period=200)`
    built, reported `period == 200`, and kept fifty prices like everything
    else. Production only ever builds the default, so nothing shipped was
    wrong - but `research/harness/zmaonline.py`'s mixture over four periods
    produced four experts with identical predictions, which is not a result a
    mixture can reach by accident.
    """

    @pytest.mark.parametrize("period", [10, 50, 200])
    def test_the_window_is_the_one_asked_for(self, period):
        assert zm.Zma(period=period)._prices.maxlen == period

    @pytest.mark.parametrize("lookback", [20, 200, 1000])
    def test_the_threshold_history_is_the_one_asked_for(self, lookback):
        z = zm.Zma(lookback=lookback)
        assert z._zs.maxlen == lookback
        assert z._slopes.maxlen == lookback

    def test_two_periods_read_the_same_bars_differently(self):
        """The property the mixture needed, stated as behaviour rather than maxlen."""
        prices = [100.0 + i * 0.1 + (3.0 if i % 7 else -3.0) for i in range(400)]
        short, long = zm.Zma(period=10), zm.Zma(period=200)
        for p in prices:
            short.observe(p)
            long.observe(p)
        assert short.z_score != pytest.approx(long.z_score)

    def test_the_window_survives_a_restore(self):
        import pickle

        z = zm.Zma(period=20)
        for i in range(300):
            z.observe(100.0 + i * 0.01)
        back = pickle.loads(pickle.dumps(z))
        assert back._prices.maxlen == 20
        assert back.z_score == pytest.approx(z.z_score)


class TestScoredBothWays:
    """The flag and the number are scored apart, because they are not the same call.

    `research/adapting.md` put the two against each other at an identical bet
    count on three OU controls and the continuous reading won every time - 0.504
    against 0.562, 0.578 against 0.603, 0.646 against 0.724. A veto has to be
    justified by the record of the reading it actually uses, so the book keeps
    both records rather than letting one stand in for the other.
    """

    def stretched(self, z: zm.Zma, *, down: bool) -> zm.Zma:
        z.seen = 50
        z.strong = 1.0
        z.z_score = -2.0 if down else 2.0
        z.slope = -1.0  # falling, so `agrees` is silent on the oversold side
        return z

    def test_the_continuous_call_is_scored_where_the_flag_is_silent(self):
        z = self.stretched(zm.Zma(), down=True)
        assert z.agrees == 0
        assert z.stretched == 1
        z._open_call, z._open_edge, z._open_price = z.agrees, z.stretched, 100.0
        z._settle(101.0)
        assert z.calls == 0, "the flag made no call and must not be scored for one"
        assert (z.edge_calls, z.edge_right) == (1, 1)

    def test_a_flat_bar_settles_nothing(self):
        """A Step index prints flat bars; counting one as a loss scores the tick size."""
        z = self.stretched(zm.Zma(), down=True)
        z._open_call, z._open_edge, z._open_price = 1, 1, 100.0
        z._settle(100.0)
        assert (z.calls, z.edge_calls) == (0, 0)

    def test_both_records_survive_a_real_pass_over_bars(self):
        z = zm.Zma()
        prices = [100.0 + 5.0 * math.sin(i / 9.0) for i in range(1200)]
        for p in prices:
            z.observe(p)
        assert z.edge_calls > z.calls > 0, "the number fires more often than the flag"
        assert 0.0 <= z.edge_accuracy <= 1.0

    def test_accuracy_is_nan_before_there_is_a_record(self):
        z = zm.Zma()
        assert math.isnan(z.accuracy)
        assert math.isnan(z.edge_accuracy)


class TestPublished:
    def test_the_record_rides_along_as_counts(self):
        """Counts, not a rate: a rate is `nan` before the first call, and every
        comparison downstream answers False to a `nan` without saying so."""
        z = wound(zm.Zma(), agrees=1)
        z.edge_calls, z.edge_right = 400, 240
        published = _zma_context(z)
        assert published["zma_edge_calls"] == 400.0
        assert published["zma_edge_right"] == 240.0
        for value in published.values():
            assert isinstance(value, float)


class TestAttention:
    """The softmax had no temperature, so it could not weight anything.

    `exp(|r| - max|r|)` over absolute returns near 1e-4 gives every bar a weight
    of 1.0000: Kish's effective sample size was 49.00 of 50 on real bars, where
    a uniform weighting over this window is exactly 50. The subtraction of the
    maximum - which exists to stop `exp` overflowing and cancels in the
    normalisation - was the entire computation.
    """

    def window(self, quiet: float, loud: float, n: int = 40) -> list[float]:
        """A window of small moves with one large one in the middle."""
        prices = [100.0]
        for i in range(n):
            step = loud if i == n // 2 else quiet
            prices.append(prices[-1] * (1.0 + step))
        return prices

    def effective(self, weights: list[float]) -> float:
        """Kish's effective sample size. Uniform over k weights is exactly k."""
        return 1.0 / sum(w * w for w in weights)

    def test_the_loud_bar_is_weighted_above_the_quiet_ones(self):
        z = zm.Zma()
        weights = z._attention(self.window(0.0001, 0.01))
        assert max(weights) > 5 * min(weights), "a softmax that cannot separate 100x"

    def test_a_lower_temperature_always_sharpens(self):
        """Monotone, which it was not while the cap was applied to the scaled
        return rather than to the gap below the largest bar."""
        prices = self.window(0.0001, 0.005)
        sizes = [
            self.effective(zm.Zma(temperature=t)._attention(prices))
            for t in (16.0, 8.0, 4.0, 2.0, 1.0)
        ]
        assert sizes == sorted(sizes, reverse=True), sizes

    def test_the_shipped_temperature_barely_moves_a_realistic_window(self):
        """Set high on purpose: sharper was measured as worse on every
        instrument where the detector has signal. See `zma.TEMPERATURE`.

        Measured on a **realistic** spread of return magnitudes, not on the
        one-huge-bar window above. That window is 39 identical moves and one
        fifty times larger, so its mean absolute return is mostly the outlier
        and the weighting concentrates however mild the temperature; real
        returns have a spread of sizes and the effective sample size at this
        temperature is 47.99 of 50 on stored BTC bars.
        """
        rng = random.Random(12)
        prices = [100.0]
        for _ in range(60):
            prices.append(prices[-1] * (1.0 + rng.gauss(0.0, 0.0004)))
        got = self.effective(zm.Zma()._attention(prices))
        assert got > 0.9 * len(prices[1:]), got

    def test_a_pathological_window_concentrates_even_when_mild(self):
        """One bar fifty times the rest takes most of the weight at any
        temperature, which is the weighting working rather than failing."""
        got = self.effective(zm.Zma()._attention(self.window(0.0001, 0.005)))
        assert got < 0.5 * 40, got

    def test_the_weighting_is_scale_free(self):
        """Gold at 4,400 and a volatility index at 1.0 weight their moves alike.
        The raw form was not scale-free either: the same shape at a different
        price level produced different weights."""
        small = zm.Zma()._attention(self.window(0.0001, 0.005))
        big = zm.Zma()._attention([p * 4_400.0 for p in self.window(0.0001, 0.005)])
        for a, b in zip(small, big, strict=True):
            assert a == pytest.approx(b, rel=1e-9)

    def test_one_enormous_bar_cannot_own_the_whole_mean(self):
        z = zm.Zma(temperature=0.5)
        weights = z._attention(self.window(0.0001, 10.0))
        assert max(weights) < 0.999, "that is a lookup, not an attention weighting"

    def test_a_window_that_never_moved_weights_every_bar_alike(self):
        weights = zm.Zma()._attention([100.0] * 20)
        assert weights == pytest.approx([1.0 / 19] * 19)

    def test_the_weights_are_a_distribution(self):
        for temperature in (0.5, 1.0, 8.0):
            weights = zm.Zma(temperature=temperature)._attention(self.window(0.0002, 0.004))
            assert sum(weights) == pytest.approx(1.0)
            assert all(w >= 0 for w in weights)


class TestTheAlertCard:
    """Published into `features` is not the same as shown to a person.

    `zma_*` and `cycle_*` were in the features dict from the moment they were
    wired, so the journal had them all along - and the card renders a
    hand-picked list of fields they were never added to. The reading was
    recorded, scored, gated on, and **invisible to the reader the alert exists
    for**: publishing a number and showing it are two jobs.

    And shown in **words**, not in z-scores. The underlying number is a z, and
    printing it that way makes the block unreadable to anybody who has not read
    the source. An alert is for a person deciding in seconds.
    """

    def lines(self, got: dict) -> list[str]:
        from till_infinity.structures.service import _cycle_lines

        return _cycle_lines(got)

    def test_a_cold_feed_adds_nothing(self):
        """Absent rather than a placeholder. A line reading "cycle neutral" on
        every alert of a feed that never warms trains the reader to skip it."""
        assert self.lines({}) == []
        assert self.lines({"zma_z": -2.0}) == [], "no threshold is no reading"

    def test_no_jargon_reaches_the_card(self):
        """The whole point of the rewrite: a reader should not need the source."""
        got = " ".join(
            self.lines(
                {
                    "zma_z": -2.14,
                    "zma_strong": 1.62,
                    "zma_agrees": 1.0,
                    "zma_edge_calls": 412.0,
                    "zma_edge_right": 240.0,
                    "cycle_alignment": 0.41,
                    "turn_price": 2751.36,
                }
            )
        ).lower()
        for word in ("z-score", "zma", "sigma", "z ", "stretch_", "percentile"):
            assert word not in got, f"{word!r} leaked onto the card"

    def test_it_says_which_way_and_whether_it_is_turning(self):
        low = " ".join(self.lines({"zma_z": -2.0, "zma_strong": 1.5, "zma_agrees": 1.0}))
        high = " ".join(self.lines({"zma_z": 2.0, "zma_strong": 1.5, "zma_agrees": 0.0}))
        assert "stretched low" in low
        assert "turning back" in low
        assert "stretched high" in high
        assert "not turning yet" in high

    def test_the_stretch_is_a_multiple_of_this_feed_s_own_usual(self):
        """Not a count of standard deviations - the threshold is already a
        percentile of this instrument's own history."""
        got = " ".join(self.lines({"zma_z": -3.0, "zma_strong": 1.5}))
        assert "2.0x its usual" in got

    def test_the_record_is_shown_with_its_denominator(self):
        """A hit rate without a count is not a claim."""
        got = " ".join(
            self.lines(
                {
                    "zma_z": -2.0,
                    "zma_strong": 1.5,
                    "zma_edge_calls": 412.0,
                    "zma_edge_right": 240.0,
                }
            )
        )
        assert "58%" in got
        assert "412" in got

    def test_a_thin_record_is_not_shown_at_all(self):
        got = " ".join(
            self.lines(
                {
                    "zma_z": -2.0,
                    "zma_strong": 1.5,
                    "zma_edge_calls": 12.0,
                    "zma_edge_right": 7.0,
                }
            )
        )
        assert "times on this feed" not in got

    def test_mid_range_cycles_above_say_nothing(self):
        """Neutral is not agreement and not opposition, and printing either
        would be a coin dressed as a reading."""
        got = " ".join(self.lines({"zma_z": -2.0, "zma_strong": 1.5, "cycle_alignment": 0.05}))
        assert "bigger cycles" not in got

    def test_the_turn_is_shown_when_the_model_has_one(self):
        got = " ".join(self.lines({"zma_z": -2.0, "zma_strong": 1.5, "turn_price": 2751.36}))
        assert "2751" in got
        assert "next turn expected" in got

    def test_a_silent_turn_model_adds_no_turn_line(self):
        got = " ".join(self.lines({"zma_z": -2.0, "zma_strong": 1.5}))
        assert "next turn" not in got


class TestTheRecordSurvivesADeploy:
    """The record lived only inside the engine state, and that made the gate
    structurally unable to earn its keep.

    `structures/store.py` hashes the shape of every persisted dataclass and
    invalidates the whole file when any of them changes - so the book was lost
    on any deploy touching any persisted class, not merely a zma one. Both
    `TRADING_ZMA_GATE` and `cycle-turn` need **200 settled calls a feed**
    before they may act. On 2026-09-15 the desk deployed eleven times and the
    book was back at zero series every time, so the evidence they were waiting
    for could never accumulate however long they ran.

    `cycles.Book` already had its own file for exactly this reason. This is the
    same fix applied to the book that needed it more.
    """

    def stocked(self) -> zm.Book:
        book = zm.Book()
        for feed, calls, right, edge_calls, edge_right in (
            ("v75", 400, 230, 512, 300),
            ("boom_1000_index", 350, 40, 401, 48),
        ):
            z = book.of(feed, "1m")
            z.calls, z.right = calls, right
            z.edge_calls, z.edge_right = edge_calls, edge_right
        return book

    def test_the_record_round_trips(self, tmp_path):
        path = tmp_path / "zma.pkl"
        assert self.stocked().save(path) == 2
        fresh = zm.Book()
        assert fresh.load(path) == 2
        good = fresh.of("v75", "1m")
        bad = fresh.of("boom_1000_index", "1m")
        assert good.edge_accuracy == pytest.approx(300 / 512)
        assert bad.edge_accuracy == pytest.approx(48 / 401)

    def test_an_anti_signal_feed_stays_an_anti_signal_across_a_restart(self, tmp_path):
        """The whole point: a feed that has proven itself wrong must not get a
        clean slate every deploy and start being trusted again."""
        path = tmp_path / "zma.pkl"
        self.stocked().save(path)
        fresh = zm.Book()
        fresh.load(path)
        assert fresh.of("boom_1000_index", "1m").edge_accuracy < 0.2

    def test_only_the_record_is_saved_not_the_window(self, tmp_path):
        """Prices and thresholds rebuild from a few hundred bars. A restored
        window pasted beside counts earned on a different stretch of history is
        a mismatch nobody would notice."""
        path = tmp_path / "zma.pkl"
        book = self.stocked()
        live = book.of("v75", "1m")
        for i in range(120):
            live.observe(100.0 + i * 0.01)
        # Read *after* the bars, because observing settles calls and moves the
        # record - comparing against the pre-observation number would be
        # asserting that the book does not work.
        expected = live.edge_calls
        assert live.seen == 120
        book.save(path)

        fresh = zm.Book()
        fresh.load(path)
        back = fresh.of("v75", "1m")
        assert back.seen == 0, "the stream is not restored"
        assert back.edge_calls == expected, "the record is"

    def test_a_missing_file_is_a_cold_start_not_an_error(self, tmp_path):
        assert zm.Book().load(tmp_path / "nothing.pkl") == 0

    def test_a_file_from_another_build_is_refused(self, tmp_path):
        import pickle

        path = tmp_path / "zma.pkl"
        path.write_bytes(pickle.dumps({"version": 99, "record": {}}))
        assert zm.Book().load(path) == 0

    def test_a_corrupt_file_does_not_take_the_desk_down(self, tmp_path):
        path = tmp_path / "zma.pkl"
        path.write_bytes(b"not a pickle at all")
        assert zm.Book().load(path) == 0

    def test_a_book_with_no_record_writes_nothing(self, tmp_path):
        """A series that has never settled a call has nothing worth keeping,
        and an empty file would only be something to load later and believe."""
        path = tmp_path / "zma.pkl"
        book = zm.Book()
        book.of("cold", "1m")
        assert book.save(path) == 0
        assert not path.exists()

    def test_a_feed_with_a_separator_in_its_name_still_round_trips(self, tmp_path):
        """Keys are joined with a NUL, which no feed slug can contain - a
        separator that appears in a name would silently merge two series'
        records."""
        path = tmp_path / "zma.pkl"
        book = zm.Book()
        z = book.of("btc_binance_coinbase", "15m")
        z.edge_calls, z.edge_right = 300, 200
        book.save(path)
        fresh = zm.Book()
        fresh.load(path)
        assert fresh.of("btc_binance_coinbase", "15m").edge_calls == 300
