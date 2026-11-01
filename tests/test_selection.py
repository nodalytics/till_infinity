"""The selection statistics, checked for the behaviour each exists to produce.

Implemented from papers, so worth exactly as much as these tests: each one
asserts a property the statistic must have rather than a number it happened
to produce.
"""

from __future__ import annotations

import math
import random

import pytest

from till_infinity.node.selection import (
    correlation,
    effective_trials,
    haircut_sharpe,
    lo_adjusted_sharpe,
    probability_of_overfitting,
)


def noise(n: int, seed: int, edge: float = 0.0, sd: float = 1.0) -> list[float]:
    random.seed(seed)
    return [random.gauss(edge, sd) for _ in range(n)]


class TestCorrelation:
    def test_a_series_with_itself_is_one(self):
        assert correlation(noise(100, 1), noise(100, 1)) == pytest.approx(1.0, abs=1e-12)

    def test_a_series_with_its_negation_is_minus_one(self):
        series = noise(100, 2)
        assert correlation(series, [-x for x in series]) == pytest.approx(-1.0, abs=1e-12)

    def test_independent_series_are_near_zero(self):
        """0.05 is arbitrary, but it is set against known arithmetic: the
        standard error of a correlation on 5,000 points is about 0.014, so the
        bound is roughly three and a half of them. These two seeds read
        0.036."""
        assert abs(correlation(noise(5_000, 3), noise(5_000, 4))) < 0.05

    def test_a_constant_series_correlates_with_nothing(self):
        """Zero rather than a division by its own zero standard deviation. A
        flat candidate in a sweep is a real occurrence - a filter that never
        triggered - and it must not take the trial count with it."""
        assert correlation([1.0] * 50, noise(50, 5)) == 0.0


class TestEffectiveTrials:
    def test_independent_trials_count_for_themselves(self):
        trials = [noise(500, seed) for seed in range(10)]
        assert effective_trials(trials) == pytest.approx(10.0, rel=0.3)

    def test_variants_of_one_idea_count_for_far_fewer(self):
        """**The reason this function exists.** A hundred variants of one idea
        are not a hundred tests, and deflating against a hundred discards real
        findings - an error in the conservative direction, but still an error.
        """
        base = noise(500, 11)
        trials = [[x + 0.1 * random.gauss(0, 1) for x in base] for _ in range(20)]
        got = effective_trials(trials)
        # Measured at 1.01 on this seed: twenty variants of one series count as
        # one trial, which is the floor. 5.0 is the arbitrary bound; the floor
        # is what the function actually does here.
        assert got < 5.0
        assert got >= 1.0

    def test_it_never_exceeds_the_number_of_trials(self):
        """Negative mean correlation is clamped: a set cannot be more
        independent than its own size."""
        a = noise(400, 13)
        trials = [a, [-x for x in a]]
        assert effective_trials(trials) <= 2.0

    def test_one_trial_and_no_trials_both_count_as_one(self):
        """An empty sweep is the awkward one. Zero effective trials would make
        the deflation divide by nothing, and a search of none has nothing to
        correct for anyway."""
        assert effective_trials([noise(100, 17)]) == 1.0
        assert effective_trials([]) == 1.0


class TestProbabilityOfOverfitting:
    def test_pure_noise_overfits_badly(self):
        """With no real edge the in-sample winner is chosen by luck, so it
        lands below the out-of-sample median about half the time."""
        trials = [noise(600, seed) for seed in range(12)]
        got = probability_of_overfitting(trials, splits=8)
        assert got.probability > 0.3
        assert got.passes is False

    def test_one_genuinely_better_trial_does_not(self):
        """A real edge wins in-sample *and* out-of-sample, so the rank holds."""
        trials = [noise(600, seed) for seed in range(1, 12)]
        trials.insert(0, noise(600, 99, edge=0.6))
        got = probability_of_overfitting(trials, splits=8)
        assert got.probability < 0.2
        assert got.passes is True

    def test_the_combination_count_is_symmetric(self):
        """Every block serves as in-sample and out-of-sample, which is what
        stops a single arbitrary split deciding the answer."""
        trials = [noise(600, seed) for seed in range(4)]
        got = probability_of_overfitting(trials, splits=8)
        assert got.combinations == math.comb(8, 4)

    def test_one_trial_is_not_a_comparison(self):
        with pytest.raises(ValueError, match="not a comparison"):
            probability_of_overfitting([noise(600, 1)])

    def test_too_few_returns_per_block_is_refused(self):
        with pytest.raises(ValueError, match="too few for a Sharpe"):
            probability_of_overfitting([noise(20, 1), noise(20, 2)], splits=10)


class TestHaircutSharpe:
    def test_a_single_trial_does_not_cut_a_strong_sharpe_at_all(self):
        """Not "barely": the cut at one trial is exactly zero, because
        `expected_max_sharpe` returns 0.0 for a single trial by construction.
        A hypothesis stated before the data was seen pays no selection
        penalty, and that is the anchor the whole haircut is measured from.

        **The `0.25` bound below does not separate one trial from many** - the
        500-trial case measures 0.2344 and would satisfy it too - so the
        exact-zero assertion is what makes this test discriminating, and
        `test_many_trials_cut_the_same_sharpe_hard` carries the comparison.
        """
        got = haircut_sharpe(noise(1_000, 21, edge=0.2), trials=1)
        assert got.adjusted > 0.0
        assert got.cut == 0.0
        assert got.cut < 0.25

    def test_many_trials_cut_the_same_sharpe_hard(self):
        """Identical returns; only the number of candidates differs."""
        returns = noise(1_000, 21, edge=0.2)
        few = haircut_sharpe(returns, trials=1)
        many = haircut_sharpe(returns, trials=500)
        assert many.adjusted < few.adjusted
        assert many.cut > few.cut

    def test_enough_trials_remove_it_entirely(self):
        """100,000 is past any sweep this desk would run, and it is there to
        check the floor rather than a realistic search: the adjusted Sharpe
        clamps at zero instead of going negative, which would read as an edge
        in the other direction."""
        got = haircut_sharpe(noise(500, 23, edge=0.05), trials=100_000)
        assert got.adjusted == 0.0
        assert got.passes is False

    def test_the_bar_is_t_above_three_not_two(self):
        """Harvey and Liu's own argument: given how many strategies have been
        tested on the same data, a t of 2 is what noise produces.

        **Seed 29 is load-bearing.** This sample reads t = 2.02, which is the
        band between the two bars, so the comparison below can tell them
        apart: at 3.0 it does not pass and at 2.0 it would. On a sample
        outside that band the test would hold for either bar and assert
        nothing - hence the first assertion, which fails loudly if the fixture
        ever drifts out of the gap rather than passing silently.
        """
        returns = noise(400, 29, edge=0.1)
        got = haircut_sharpe(returns, trials=1)
        assert 2.0 < got.t_statistic < 3.0, (
            f"t of {got.t_statistic} is outside the 2-to-3 band, so this "
            f"test can no longer tell the two bars apart"
        )
        assert got.passes == (got.adjusted > 0 and got.t_statistic > 3.0)

    def test_it_takes_a_fractional_trial_count(self):
        """Because `effective_trials` returns one - adjusting against the
        independent count is the whole reason that function exists."""
        got = haircut_sharpe(noise(800, 31, edge=0.15), trials=11.4)
        assert got.trials == pytest.approx(11.4)

    def test_an_unknown_method_is_refused(self):
        with pytest.raises(ValueError, match="unknown method"):
            haircut_sharpe(noise(100, 37), trials=2, method="guess")


class TestLoAdjustedSharpe:
    def test_independent_returns_are_barely_changed(self):
        returns = noise(3_000, 41, edge=0.1)
        from till_infinity.node.metrics import sharpe

        assert lo_adjusted_sharpe(returns) == pytest.approx(sharpe(returns), rel=0.15)

    def test_positive_autocorrelation_lowers_it(self):
        """A naive Sharpe reads high on autocorrelated returns, and this desk
        measures size autocorrelation of 0.21 on traded markets."""
        from till_infinity.node.metrics import sharpe

        random.seed(43)
        series, previous = [], 0.0
        for _ in range(3_000):
            value = 0.1 + 0.6 * previous + random.gauss(0, 1)
            series.append(value)
            previous = value - 0.1
        assert lo_adjusted_sharpe(series) < sharpe(series)

    def test_negative_autocorrelation_raises_it(self):
        """Correct, and worth knowing: a mean-reverting series is genuinely
        better than its naive Sharpe suggests."""
        from till_infinity.node.metrics import sharpe

        random.seed(47)
        series, previous = [], 0.0
        for _ in range(3_000):
            value = 0.1 - 0.4 * previous + random.gauss(0, 1)
            series.append(value)
            previous = value - 0.1
        assert lo_adjusted_sharpe(series) > sharpe(series)

    def test_no_lags_is_the_iid_answer(self):
        """The degenerate case has to be an identity, or the correction is
        adding something of its own at every horizon."""
        from till_infinity.node.metrics import sharpe

        returns = noise(500, 53, edge=0.1)
        assert lo_adjusted_sharpe(returns, horizon=1) == pytest.approx(sharpe(returns))
