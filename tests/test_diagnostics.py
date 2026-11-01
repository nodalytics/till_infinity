"""Expectancy and profit factor: reported, never gated on.

The design question behind this file was "can we have PSR and DSR for profit
factor and expectancy too?" The answer is partly:

* **Expectancy, yes and nearly free** - it is a mean, so its standard error is
  `sd/sqrt(n)` whatever the shape of the returns, where a Sharpe's carries skew
  and kurtosis terms because it is a *ratio*. But it is **not independent**:
  `sharpe = expectancy / sd`, so deflating both corrects the same quantity
  twice.
* **Profit factor, only by bootstrap** - a ratio of two sums of positives, with
  no usable closed-form standard error and undefined when there are no losses,
  which is the regime where a strategy looks best.

And the part that decided the shape: the correction applies **once, to the whole
search**. Four correlated statistics with four thresholds gives an effective
trial count nobody can compute. The desk's record is explicit - several
candidates passed DSR, PBO and SPA, and what exposed them was surrogates and an
hourly breakdown. More metrics did not help; a different *kind* of test did.
"""

from __future__ import annotations

import pytest

from till_infinity.node import metrics
from till_infinity.node.statistics import DIAGNOSTICS, GATES

#: A sample with a real edge and real losses: 0.35R mean, PF 1.7.
SAMPLE = [1.8, -1.0, 2.0, -1.0, -1.0, 1.5, -1.0, 2.2, -1.0, 1.0] * 12


# --------------------------------------------------------------- expectancy


def test_expectancy_is_the_mean_in_r():
    assert metrics.expectancy(SAMPLE) == pytest.approx(0.35)
    assert metrics.expectancy([]) == 0.0


def test_a_probability_on_the_expectancy_needs_no_shape_assumption():
    """A mean's standard error is `sd/sqrt(n)` by the central limit theorem,
    where a Sharpe's needs the third and fourth moments."""
    assert metrics.probabilistic_expectancy(SAMPLE) > 0.99
    # And against a threshold it is strictly lower.
    assert metrics.probabilistic_expectancy(
        SAMPLE, benchmark=0.2
    ) < metrics.probabilistic_expectancy(SAMPLE)


def test_a_constant_series_has_an_expectancy_but_has_shown_nothing():
    """`moments` raises here because *a Sharpe* needs a denominator. An
    expectancy does not - so the guard comes first, and the answer is 0.0
    rather than 1.0: no variation has not demonstrated certainty, and rounding
    it to certainty is how one lucky trade becomes a track record.
    """
    assert metrics.expectancy([1.0] * 20) == pytest.approx(1.0)
    assert metrics.probabilistic_expectancy([1.0] * 20) == 0.0
    assert metrics.probabilistic_expectancy([1.0]) == 0.0


def test_the_expectancy_probability_tracks_the_sharpe_probability():
    """**The non-independence, measured - which is why it is not registered.**

    `sharpe = expectancy / sd`, so these two are the same evidence differently
    scaled, and on a real sample they agree to three decimals. The function
    stays in `metrics.py`, documented; the *statistic* does not, because a
    probability looks like a test result and 0.997 printed beside 0.997 reads
    as two confirmations.
    """
    psr = metrics.probabilistic_sharpe(SAMPLE)
    pe = metrics.probabilistic_expectancy(SAMPLE)
    assert abs(psr - pe) < 0.01, f"PSR {psr} vs P_Expectancy {pe}"


def test_the_redundant_probability_is_not_registered_but_the_number_is():
    """Redundant descriptions yes, redundant probabilities no."""
    assert "Expectancy" in DIAGNOSTICS
    assert "P_Expectancy" not in DIAGNOSTICS
    assert "P_Expectancy" not in GATES


# ------------------------------------------------------- the payoff split


#: Same question, opposite structure: 70% at +0.5R against 30% at +3.0R.
TIGHT = ([0.5] * 7 + [-1.0] * 3) * 12
WIDE = ([3.0] * 3 + [-1.0] * 7) * 12


def test_the_payoff_split_is_not_in_the_sharpe():
    """Two series at a similar Sharpe with opposite structure.

    This is what makes the win rate worth reporting: the Sharpe fixes roughly
    one combination of `(win rate, payoff)` and leaves the other direction
    open, and the open direction sets the Kelly fraction, the sizing, and how
    long a losing run lasts before the account is in trouble.
    """
    assert metrics.win_rate(TIGHT) == pytest.approx(0.7)
    assert metrics.win_rate(WIDE) == pytest.approx(0.3)
    assert metrics.payoff(TIGHT) == pytest.approx(0.5)
    assert metrics.payoff(WIDE) == pytest.approx(3.0)
    # Similar Sharpe, and within a factor of two of each other.
    assert 0.5 < metrics.sharpe(TIGHT) / metrics.sharpe(WIDE) < 2.0


def test_the_win_rate_probability_disagrees_with_the_psr_in_ordering():
    """**The proof of independence.** A rescaling cannot disagree with what it
    rescales, and these order the two series opposite ways."""
    assert metrics.probabilistic_sharpe(TIGHT) < metrics.probabilistic_sharpe(WIDE)
    assert metrics.probabilistic_win_rate(TIGHT) > metrics.probabilistic_win_rate(WIDE)


def test_the_win_rate_null_is_a_coin_rather_than_an_absence():
    """A 30% win rate at a 3R payoff is a good strategy, so the benchmark is
    0.5 and a low number is not a failure - it is half a description."""
    assert metrics.probabilistic_win_rate(SAMPLE) == pytest.approx(0.5, abs=0.01)
    assert metrics.probabilistic_win_rate(SAMPLE, benchmark=0.3) > 0.9


def test_a_scratch_counts_on_neither_side():
    """A flat trade is neither won nor lost, and calling it a loss understates
    a strategy that scratches often."""
    assert metrics.win_rate([1.0, -1.0, 0.0, 0.0]) == pytest.approx(0.5)
    assert metrics.win_rate([0.0, 0.0]) is None


def test_payoff_is_none_where_either_side_is_empty():
    assert metrics.payoff([1.0, 2.0]) is None
    assert metrics.payoff([-1.0, -2.0]) is None
    assert metrics.win_rate([]) is None
    assert metrics.probabilistic_win_rate([]) == 0.0


# ------------------------------------------------------------ profit factor


def test_a_profit_factor_with_no_losses_is_none_rather_than_infinite():
    """It is undefined there, and that regime - a short sample, a quiet
    period, a lucky run - is exactly where a strategy looks best. `inf` would
    put it top of any ranking."""
    assert metrics.profit_factor([1.0, 2.0, 3.0]) is None
    assert metrics.log_profit_factor([1.0, 2.0, 3.0]) is None
    assert metrics.profit_factor(SAMPLE) == pytest.approx(1.7, rel=1e-3)


def test_the_interval_is_bootstrapped_because_there_is_no_closed_form():
    """The delta method needs a derivative at the denominator, and the
    denominator is a sum of losses that approaches zero exactly where the
    estimate matters most."""
    got = metrics.profit_factor_interval(SAMPLE, draws=400, seed=1)
    assert got is not None
    low, high = got
    assert low < 1.7 < high, got
    assert low > 0.0, "a profit factor cannot be negative"


def test_the_interval_is_reproducible_for_a_given_seed():
    a = metrics.profit_factor_interval(SAMPLE, draws=200, seed=7)
    b = metrics.profit_factor_interval(SAMPLE, draws=200, seed=7)
    assert a == b


def test_no_interval_where_most_resamples_have_no_losses():
    """A statement about the sample rather than a wide interval."""
    assert metrics.profit_factor_interval([1.0, 2.0, 3.0], draws=100) is None
    assert metrics.profit_factor_interval([1.0], draws=100) is None


def test_the_interval_uses_the_stationary_bootstrap_not_an_iid_one():
    """Trade outcomes cluster, and drawing independently would narrow the
    interval by assuming the clustering away."""
    import inspect

    source = inspect.getsource(metrics.profit_factor_interval)
    assert "stationary_bootstrap" in source


# ------------------------------------------------------------- the gate split


def test_exactly_one_statistic_gates():
    """The correction applies once to the whole search. A second gate makes the
    effective trial count uncomputable."""
    assert GATES == ("DSR",)


def test_no_diagnostic_is_also_a_gate():
    assert not set(GATES) & set(DIAGNOSTICS)


def test_every_registered_statistic_is_declared_as_one_or_the_other():
    """A statistic in neither list is one nobody decided the status of."""
    from nautilus_trader.analysis.analyzer import PortfolioAnalyzer

    from till_infinity.node.statistics import register

    analyzer = PortfolioAnalyzer()
    register(analyzer, trial_sharpes=[0.4, 0.9, -0.2, 1.4, 0.1, 0.7, -0.5, 1.1])
    declared = set(GATES) | set(DIAGNOSTICS)
    assert set(analyzer._statistics) == declared, set(analyzer._statistics) ^ declared


def test_the_deflation_undoes_a_confident_psr():
    """What the gate is for, in one assertion.

    The sample's PSR is above 0.997 - near certainty on its own - and eight
    trials deflate it to effectively zero. A diagnostic that reported 0.997
    beside it would be true and misleading, which is why the gate reads the
    deflated one.
    """
    trials = [0.4, 0.9, -0.2, 1.4, 0.1, 0.7, -0.5, 1.1]
    assert metrics.probabilistic_sharpe(SAMPLE) > 0.997
    assert metrics.deflated_sharpe(SAMPLE, trials) < 0.01
