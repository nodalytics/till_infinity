"""The deflated Sharpe ratio, checked against things with known answers.

A statistic implemented from a paper is worth exactly as much as its tests, so
the normal quantile is checked against published values, the deflation is
checked for the behaviour it exists to produce, and the non-normality term is
checked to move in the direction that makes a fat-tailed Sharpe harder.
"""

from __future__ import annotations

import math
import random

import pytest

from till_infinity.node.metrics import (
    EULER,
    deflated_sharpe,
    expected_max_sharpe,
    minimum_track_record,
    moments,
    phi,
    phi_inverse,
    probabilistic_sharpe,
    sharpe,
    trial_variance,
)


class TestTheNormalFunctions:
    @pytest.mark.parametrize(
        ("p", "want"),
        [(0.5, 0.0), (0.975, 1.959964), (0.95, 1.644854), (0.99, 2.326348), (0.001, -3.090232)],
    )
    def test_the_quantile_matches_published_values(self, p, want):
        assert phi_inverse(p) == pytest.approx(want, abs=1e-5)

    def test_the_cdf_and_quantile_are_inverses(self):
        for p in (0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99):
            assert phi(phi_inverse(p)) == pytest.approx(p, abs=1e-9)

    @pytest.mark.parametrize("p", [0.0, 1.0, -0.1, 1.5])
    def test_a_probability_outside_the_interval_is_refused(self, p):
        with pytest.raises(ValueError, match="0 < p < 1"):
            phi_inverse(p)


class TestMoments:
    def test_a_symmetric_series_has_no_skew(self):
        _mean, _sd, skew, _kurt = moments([-2.0, -1.0, 1.0, 2.0])
        assert skew == pytest.approx(0.0, abs=1e-12)

    def test_kurtosis_is_not_excess(self):
        """Three for a normal, not zero - the DSR formula wants the raw moment."""
        random.seed(7)
        sample = [random.gauss(0.0, 1.0) for _ in range(200_000)]
        _mean, _sd, _skew, kurt = moments(sample)
        assert kurt == pytest.approx(3.0, abs=0.1)

    def test_a_constant_series_is_refused(self):
        with pytest.raises(ValueError, match="no Sharpe"):
            moments([1.0, 1.0, 1.0, 1.0])

    def test_too_short_is_refused(self):
        with pytest.raises(ValueError, match="at least 4"):
            moments([1.0, 2.0, 3.0])


class TestTheDeflationGrowsWithTheSearch:
    """The whole purpose: more trials, higher bar."""

    def test_one_trial_deflates_by_nothing(self):
        assert expected_max_sharpe(0.04, 1) == 0.0

    def test_the_bar_rises_with_the_number_of_trials(self):
        bars = [expected_max_sharpe(0.04, n) for n in (2, 10, 100, 1000)]
        assert bars == sorted(bars)
        assert bars[-1] > bars[0] > 0.0

    def test_the_bar_rises_with_the_spread_of_the_trials(self):
        assert expected_max_sharpe(0.09, 50) > expected_max_sharpe(0.01, 50)

    def test_a_single_trial_cannot_be_deflated_and_says_so(self):
        """Reporting an undeflated Sharpe as deflated is worse than neither."""
        with pytest.raises(ValueError, match="nothing to deflate"):
            trial_variance([0.3])

    def test_euler_is_the_constant_the_paper_uses(self):
        assert pytest.approx(0.5772156649, abs=1e-9) == EULER


class TestNonNormalityMakesTheBarHarder:
    """Where it bites here: traded markets run kurtosis 20 to 74, not 3."""

    @staticmethod
    def _series(kurt_driver: float, n: int = 500) -> list[float]:
        random.seed(11)
        out = []
        for i in range(n):
            x = random.gauss(0.05, 1.0)
            if i % 50 == 0:  # occasional outlier, which is what fat tails are
                x *= kurt_driver
            out.append(x)
        return out

    def test_fat_tails_lower_the_probabilistic_sharpe(self):
        mild, wild = self._series(1.0), self._series(12.0)
        assert moments(wild)[3] > moments(mild)[3]
        assert probabilistic_sharpe(wild) < probabilistic_sharpe(mild)

    def test_a_longer_record_raises_it(self):
        random.seed(3)
        short = [random.gauss(0.04, 1.0) for _ in range(100)]
        long = short + [random.gauss(0.04, 1.0) for _ in range(900)]
        assert probabilistic_sharpe(long) > probabilistic_sharpe(short)

    def test_a_zero_edge_centres_on_a_half_across_seeds(self):
        """Across seeds, not within one - and the difference is the statistic.

        PSR answers "given this record, how likely is the true Sharpe to beat
        the benchmark", so on 5,000 samples it is *confident* about whichever
        side the sample mean happened to land: `sqrt(n - 1)` is about 70, and
        a sample Sharpe of 0.014 from pure noise comes out near 0.84. That is
        the right answer to the question asked, and asserting one draw sits
        near a half asks a different one.
        """
        readings = []
        for seed in range(40):
            random.seed(seed)
            readings.append(probabilistic_sharpe([random.gauss(0.0, 1.0) for _ in range(2_000)]))
        assert sum(readings) / len(readings) == pytest.approx(0.5, abs=0.1)
        # And it does spread, which is the point of the note above.
        assert max(readings) > 0.7
        assert min(readings) < 0.3


class TestDeflatedSharpeEndToEnd:
    @staticmethod
    def _returns(edge: float, n: int = 1_000, seed: int = 17) -> list[float]:
        random.seed(seed)
        return [random.gauss(edge, 1.0) for _ in range(n)]

    def test_a_real_edge_found_in_few_trials_survives(self):
        got = deflated_sharpe(self._returns(0.15), [0.15, 0.02, -0.03, 0.01])
        assert got > 0.9

    def test_the_same_edge_found_in_a_thousand_trials_does_not(self):
        """**This is the finding the whole pipeline exists to avoid.**

        Identical returns. The only difference is how many candidates were
        tried to find them, and that is enough to turn a convincing Sharpe
        into an unconvincing one - which is what happened when a block of
        eight found structure in 27 of 36 placebo pools.
        """
        random.seed(23)
        many = [random.gauss(0.0, 0.2) for _ in range(1_000)] + [0.15]
        few = deflated_sharpe(self._returns(0.15), [0.15, 0.02, -0.03, 0.01])
        lots = deflated_sharpe(self._returns(0.15), many)
        assert lots < few
        assert lots < 0.95

    def test_no_edge_does_not_survive_either_way(self):
        assert deflated_sharpe(self._returns(0.0), [0.0, 0.01, -0.01, 0.02]) < 0.9


class TestMinimumTrackRecord:
    def test_a_stronger_edge_needs_less_history(self):
        random.seed(29)
        weak = [random.gauss(0.02, 1.0) for _ in range(600)]
        strong = [random.gauss(0.20, 1.0) for _ in range(600)]
        assert minimum_track_record(strong) < minimum_track_record(weak)

    def test_no_edge_is_unmeasurable_rather_than_failing(self):
        """A different decision from failing, and usually a cheaper one."""
        random.seed(31)
        assert minimum_track_record([random.gauss(-0.1, 1.0) for _ in range(500)]) == math.inf

    def test_it_agrees_with_the_probabilistic_sharpe_it_inverts(self):
        random.seed(37)
        returns = [random.gauss(0.08, 1.0) for _ in range(4_000)]
        needed = minimum_track_record(returns, target=0.95)
        assert sharpe(returns) > 0
        # At the length it asks for, PSR should be at the target.
        assert probabilistic_sharpe(returns[: int(needed) + 1]) == pytest.approx(0.95, abs=0.15)
