"""The multiple-testing layer, the stability tests, and the unattended loop.

Three subjects in one file because they are one decision: what a candidate has
to survive before the ladder gives it money, and what bounds the ladder when
nobody is watching. `CEILING` is 0.60 and no amount of passing can lift it.

**Two of the tests in here used to assert differences that could not exist**,
and both failures had the same shape: a test about dependence run on data with
no dependence in it. `test_the_day_block_interval_is_wider_when_days_are_clustered`
used i.i.d. returns, where resampling by day and resampling by point are the
same operation. `test_a_ruinous_era_fails_even_with_a_majority_positive` used
`[0.1] * 500` for a good era, and a constant series has no Sharpe at all, so
the era it meant to call strong scored zero. Both passed. Neither could have
failed for its own reason, and the surrogate and clock work in
`test_surrogates.py` is the generalisation of the lesson: a null that cannot
move the statistic is not a null.

So the fixtures here carry the structure the assertion is about, and the two
tests that learned it say so in their own docstrings.
"""

from __future__ import annotations

import itertools
import random
import tempfile
from pathlib import Path

import pytest

from till_infinity.node.metrics import sharpe
from till_infinity.node.multiple import (
    benjamini_hochberg,
    benjamini_yekutieli,
    hansen_spa,
    minimum_backtest_length,
    romano_wolf,
    stationary_bootstrap,
    supportable_trials,
)
from till_infinity.node.pipeline import (
    CEILING,
    Ladder,
    pending,
    put_back,
    report,
    step,
    take_off,
)
from till_infinity.node.promotion import Candidate, Gate, Retirement, Rung
from till_infinity.node.stability import day_block_interval, walk_back, walk_forward


def noise(n: int, seed: int, edge: float = 0.0) -> list[float]:
    random.seed(seed)
    return [random.gauss(edge, 1.0) for _ in range(n)]


def passing_gate(seed: int = 1) -> Gate:
    random.seed(seed)
    return Gate(
        name="backtest",
        criterion="DSR >= 0.95",
        control="distance-matched placebo",
        candidates=4,
        episodes=900,
        trial_sharpes=(0.15, 0.02, -0.03, 0.01),
        returns=tuple(random.gauss(0.15, 1.0) for _ in range(900)),
    )


class TestTheBootstrapIsStationary:
    def test_a_resample_is_as_long_as_the_sample_it_came_from(self):
        """A short draw would quietly compute every statistic on fewer
        observations than the one it is being compared against."""
        assert len(stationary_bootstrap(100, rng=random.Random(1))) == 100

    def test_every_index_can_be_used_to_index_the_sample(self):
        """The wraparound is the reason this is worth asserting: blocks run off
        the end on purpose, and an off-by-one there is an `IndexError` in the
        caller rather than here."""
        picks = stationary_bootstrap(50, rng=random.Random(2))
        assert all(0 <= i < 50 for i in picks)

    def test_it_draws_blocks_rather_than_points(self):
        """Resampling observations independently destroys the serial
        dependence that makes the null fair.

        100 of 199 adjacent pairs is an arbitrary threshold - a little over
        half - and it is far from either thing it separates. Measured at this
        seed: `block=20` keeps 187 pairs consecutive and `block=1`, which is
        the i.i.d. draw, keeps none.
        """
        picks = stationary_bootstrap(200, block=20, rng=random.Random(3))
        consecutive = sum(1 for a, b in itertools.pairwise(picks) if b == a + 1)
        assert consecutive > 100


class TestSPAAndRomanoWolfAnswerDifferentQuestions:
    def test_a_real_edge_among_noise_is_found_by_both(self):
        diffs = [noise(600, s) for s in range(1, 20)]
        diffs.insert(0, noise(600, 99, edge=0.18))
        spa = hansen_spa(diffs, draws=200, seed=2)
        rw = romano_wolf(diffs, draws=200, seed=3)
        assert spa.passes is True
        assert 0 in rw.survived

    def test_all_noise_passes_neither(self):
        diffs = [noise(600, s) for s in range(20)]
        assert hansen_spa(diffs, draws=200, seed=4).passes is False
        assert romano_wolf(diffs, draws=200, seed=5).survived == ()

    def test_spa_recenters_so_duds_do_not_inflate_the_null(self):
        """White's reality check lets hopeless candidates carry the null and
        loses power; Hansen drops them. A sweep produces mostly duds."""
        good = noise(600, 7, edge=0.2)
        duds = [[x - 2.0 for x in noise(600, s)] for s in range(8, 28)]
        got = hansen_spa([good, *duds], draws=200, seed=6)
        assert got.contributing < got.candidates

    def test_too_few_observations_is_refused(self):
        with pytest.raises(ValueError, match="too few for a bootstrap"):
            hansen_spa([[1.0, 2.0, 3.0]], draws=10)


class TestFalseDiscoveryRates:
    def test_a_smaller_raw_p_never_earns_a_larger_q(self):
        """The step-up runs from the largest p down and takes a running
        minimum, so an inversion here would mean a candidate was rejected
        while a weaker one beside it survived.

        The bound is the second half and it is not decoration: a q above 1 is
        not a probability, and `benjamini_yekutieli` multiplies by a harmonic
        sum greater than 1, so it is the arm where the clamp has to work.
        """
        got = benjamini_hochberg([0.001, 0.008, 0.02, 0.2, 0.7])
        assert got == sorted(got)
        assert all(0.0 <= q <= 1.0 for q in got)

    def test_by_is_more_conservative_than_bh(self):
        """BH assumes independence or positive dependence; a sweep of
        correlated candidates is neither in any dependable way."""
        ps = [0.001, 0.008, 0.02, 0.2, 0.7]
        assert all(
            b >= h for b, h in zip(benjamini_yekutieli(ps), benjamini_hochberg(ps), strict=True)
        )

    def test_no_candidates_is_an_empty_answer_rather_than_an_error(self):
        """A sweep that produced nothing reaches here on a quiet day, and the
        caller zips the q-values back against its candidates."""
        assert benjamini_hochberg([]) == []
        assert benjamini_yekutieli([]) == []


class TestMinimumBacktestLength:
    def test_a_wider_search_needs_a_longer_history_to_support_it(self):
        assert minimum_backtest_length(1_000, 1.0) > minimum_backtest_length(10, 1.0)

    def test_a_stronger_target_sharpe_needs_less_of_it(self):
        assert minimum_backtest_length(100, 2.0) < minimum_backtest_length(100, 1.0)

    def test_the_two_directions_are_inverses_of_each_other(self):
        """They are asked at different moments - how long must I wait, and how
        many ideas may I try with what I have - and an answer that disagreed
        with its own inverse would let a sweep be sized past what the history
        supports."""
        years = minimum_backtest_length(100, 1.5)
        assert supportable_trials(years, 1.5) == pytest.approx(100, rel=0.01)

    def test_short_history_supports_very_few_trials(self):
        """The hard constraint on fast discovery, and it is arithmetic: the
        standard error of an annualised Sharpe depends on calendar span, not
        observation count, so more ticks per month do not help."""
        assert supportable_trials(1 / 12, 1.5) < 2

    def test_a_single_untested_idea_needs_no_history_to_justify_itself(self):
        """Zero rather than a small positive number, because there is no
        selection to correct for: the length this returns pays for the search,
        and a search of one is free."""
        assert minimum_backtest_length(1, 1.0) == 0.0


class TestStability:
    def test_walk_forward_stitches_rather_than_averages(self):
        """A mean of per-fold scores flatters a strategy whose good folds are
        its short ones."""
        rets = noise(1_200, 11, edge=0.08)
        got = walk_forward(rets, lambda tr, te: (sharpe(tr), list(te)), folds=6)
        assert len(got.folds) == 6
        assert got.stitched != pytest.approx(sum(f.test_score for f in got.folds) / 6, abs=1e-9)

    def test_walk_back_refits_nothing(self):
        """The whole difference from walk-forward: a result that passes there
        and fails here was being carried by the refitting."""
        got = walk_back(noise(1_200, 13, edge=0.08), eras=6)
        assert len(got.eras) == 6
        assert got.eras[0].index == 0  # newest first

    def test_a_ruinous_era_fails_even_with_a_majority_positive(self):
        """A setup mildly positive in five eras and ruinous in the sixth is
        not stable; its regime has not arrived yet.

        Varying returns, not constants: a constant series has no Sharpe at
        all, so `[0.1] * 500` scores zero rather than positive - which is
        what the first version of this test asserted against.
        """
        random.seed(19)
        good = [random.gauss(0.4, 1.0) for _ in range(500)]
        ruinous = [random.gauss(-3.0, 1.0) for _ in range(100)]
        got = walk_back([*good, *ruinous], eras=6)
        assert got.positive >= 4
        assert got.passes is False

    def test_the_day_block_interval_is_wider_when_days_are_clustered(self):
        """Intraday returns share the day's volatility, news and session.

        **The data has to have the dependence for the test to mean anything.**
        The first version of this test used i.i.d. returns, where day-blocking
        and point-resampling are the same thing - so it asserted a difference
        that could not exist. Here each day carries a common shock, which is
        what a session actually does.
        """
        random.seed(23)
        rets, days = [], []
        for day in range(50):
            shock = random.gauss(0.0, 1.0)  # the day's own level
            for _ in range(24):
                rets.append(shock + random.gauss(0.08, 0.3))
                days.append(day)
        clustered = day_block_interval(rets, days, draws=300, seed=1)
        per_point = day_block_interval(rets, list(range(len(rets))), draws=300, seed=1)
        assert (clustered.high - clustered.low) > (per_point.high - per_point.low)

    def test_too_few_days_is_refused(self):
        with pytest.raises(ValueError, match="too few to resample"):
            day_block_interval([1.0] * 10, [0, 0, 1, 1, 1, 1, 1, 1, 1, 1], draws=10)


class TestTheUnattendedLoop:
    @staticmethod
    def _ladder(count: int = 15, decide_after: int = 10) -> Ladder:
        ladder = Ladder()
        gate = passing_gate()
        for name in [chr(97 + i) for i in range(count)]:
            ladder.candidates[name] = Candidate(
                name=name,
                rung=Rung.BACKTESTED,
                origin="sweep",
                gates=[gate],
                decide_after=decide_after,
            )
            ladder.enter(name)
            ladder.note_episodes(name, 50)
        return ladder

    def test_it_settles_rather_than_flooding(self):
        """A loop that logs every pass buries the pass that matters, and one
        that logs only promotions cannot say why nothing is happening."""
        ladder = self._ladder()
        first = len(step(ladder))
        second = len(step(ladder))
        assert first > 0
        assert len(step(ladder)) == 0
        assert len(step(ladder)) == 0
        assert second <= first

    def test_forty_passing_candidates_cannot_lift_the_ceiling(self):
        """`CEILING` is 0.60 and the gates are statistical, so they will
        eventually pass something that should not have passed. The bound is
        the thing that is not allowed to move when they do.

        The tolerance is floating-point slack on a sum of allocations, not a
        permitted overshoot.
        """
        ladder = self._ladder(count=40)
        for _ in range(5):
            step(ladder)
        assert ladder.allocated() <= CEILING + 1e-9

    def test_a_held_candidate_says_why_it_is_held(self):
        """An unattended loop that stops promoting and does not say what it is
        waiting for cannot be distinguished from one that has crashed."""
        ladder = self._ladder()
        step(ladder)
        held = [d for d in ladder.log if d.action == "held"]
        assert held
        assert all(d.reason for d in held)

    def test_entering_a_rung_resets_the_sample(self):
        """Carrying the previous rung's episodes over would let a candidate
        promote twice on one sample."""
        ladder = self._ladder(count=1)
        ladder.note_episodes("a", 500)
        ladder.enter("a")
        assert ladder.episodes["a"] == 0

    def test_retiring_frees_the_capital_for_the_next_candidate(self):
        """Otherwise the ceiling is reached once and the ladder never promotes
        again - a loop that looks healthy and has quietly stopped."""
        ladder = self._ladder(count=15)
        step(ladder)
        step(ladder)
        before = ladder.allocated()
        take_off(ladder, "a", Retirement.REFUTED, evidence="null test p=0.41")
        assert ladder.allocated() < before
        assert ladder.candidates["a"].rung is Rung.RETIRED

    def test_a_revived_candidate_arrives_with_no_gates_passed(self):
        """A candidate comes back because the market changed or the idea was
        re-specified. Carrying its old gate results over would promote it on
        evidence gathered about a different thing."""
        ladder = self._ladder(count=3)
        step(ladder)
        take_off(ladder, "a", Retirement.REFUTED, evidence="null test p=0.41")
        put_back(ladder, "a")
        assert ladder.candidates["a"].rung is Rung.BACKTESTED
        assert ladder.candidates["a"].gates == []
        assert any("no gate has been run" in " ".join(r) for _n, r in pending(ladder))

    def test_a_stale_candidate_is_dropped_rather_than_accumulated(self):
        ladder = Ladder()
        ladder.candidates["old"] = Candidate(name="old", rung=Rung.BACKTESTED, origin="sweep")
        ladder.enter("old", now=0.0)
        decided = step(ladder, now=lambda: 100.0 * 86_400)
        assert any(d.action == "dropped" for d in decided)
        assert ladder.candidates["old"].rung is Rung.REJECTED

    def test_the_ladder_survives_a_restart(self):
        ladder = self._ladder(count=4)
        step(ladder)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ladder.json"
            ladder.save(path)
            back = Ladder.load(path)
        assert len(back.candidates) == 4
        assert back.allocated() == pytest.approx(ladder.allocated())

    def test_a_missing_or_corrupt_ladder_is_not_fatal(self):
        """Forgetting candidates is recoverable; a node that will not start
        is not."""
        with tempfile.TemporaryDirectory() as tmp:
            assert Ladder.load(Path(tmp) / "absent.json").candidates == {}
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json")
            assert Ladder.load(bad).candidates == {}

    def test_the_report_names_the_ceiling_it_is_measured_against(self):
        """An allocated figure on its own is unreadable: 40% is most of the way
        to the bound or a third of it depending on a number the reader does not
        have."""
        ladder = self._ladder()
        step(ladder)
        assert any("ceiling" in line for line in report(ladder))
