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
    """And an empty record is 0.0 rather than an error: a strategy that has
    not traded has an expectancy of nothing, which a report can print."""
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
    """A payoff needs both sides to divide. Zero would read as a strategy with
    no reward rather than one with no losses yet, and the no-losses case is
    where a short sample looks best."""
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
    """A bootstrap whose answer moves between two calls on one sample cannot
    be compared across candidates, which is the only thing the ladder does
    with it."""
    a = metrics.profit_factor_interval(SAMPLE, draws=200, seed=7)
    b = metrics.profit_factor_interval(SAMPLE, draws=200, seed=7)
    assert a == b


def test_no_interval_where_most_resamples_have_no_losses():
    """A statement about the sample rather than a wide interval."""
    assert metrics.profit_factor_interval([1.0, 2.0, 3.0], draws=100) is None
    assert metrics.profit_factor_interval([1.0], draws=100) is None


def test_a_clustered_record_gets_a_wider_interval_than_an_independent_draw():
    """**Trade outcomes cluster, and an i.i.d. draw narrows the interval by
    assuming that away.** Which is the direction that costs money: a confident
    interval around a profit factor is what a search uses to decide a
    candidate is real.

    `block` is the mean run length the resample preserves, so `block=1` *is*
    the i.i.d. bootstrap - `stationary_bootstrap` draws a fresh index with
    probability `1/block`. The series below is the extreme clustered case,
    sixty-four wins then sixty-four losses, where an independent draw always
    sees about half of each and a long block sees mostly one. Widths at seed 7
    over 600 draws: 1.92, 3.20, 7.17, 12.31. The shipped default of
    `block=10` reads 8.88, which is 4.6 times the independent one.

    This replaced `assert "stationary_bootstrap" in inspect.getsource(...)`,
    which asserted that a line existed rather than that it ran.
    """
    clustered = [3.0] * 64 + [-1.0] * 64

    def width(**kwargs) -> float:
        got = metrics.profit_factor_interval(clustered, draws=600, seed=7, **kwargs)
        assert got is not None
        return got[1] - got[0]

    widths = [width(block=block) for block in (1, 2, 8, 32)]
    assert widths == sorted(widths), widths
    assert widths[0] < widths[-1] / 4, widths
    # The default is not a fourth reading of the same thing: it pins that the
    # shipped call is the dependent one, which is the property under test.
    assert width() > 3 * widths[0]


# ------------------------------------------------------------- the gate split


def test_exactly_one_statistic_gates():
    """The correction applies once to the whole search. A second gate makes the
    effective trial count uncomputable."""
    assert GATES == ("DSR",)


def test_no_diagnostic_is_also_a_gate():
    """A statistic in both lists would be reported as a description and
    enforced as a threshold, and only one of those is a decision."""
    assert not set(GATES) & set(DIAGNOSTICS)


def test_every_registered_statistic_is_declared_as_one_or_the_other():
    """A statistic in neither list is one nobody decided the status of."""
    import pandas as pd
    from nautilus_trader.analysis.analyzer import PortfolioAnalyzer

    from till_infinity.node.statistics import register

    analyzer = PortfolioAnalyzer()
    # Everything supplied, because two of these register conditionally - `DSR`
    # on having trials and the two ratios on having a benchmark. Registering
    # them unconditionally would put always-empty columns in every report.
    register(
        analyzer,
        trial_sharpes=[0.4, 0.9, -0.2, 1.4, 0.1, 0.7, -0.5, 1.1],
        benchmark=pd.Series([0.0, 0.0, 0.0, 0.0]),
        trial_ratios=[0.2, -0.1, 0.4, 0.05],
    )
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


# ---------------------------------------- the information ratio, and deflating it


def series(values, start="2026-01-01"):
    import pandas as pd

    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


RETURNS = [0.01, -0.005, 0.02, 0.015, -0.01, 0.03, 0.004, -0.002]
BOOK = [0.005, -0.002, 0.01, 0.012, -0.004, 0.02, 0.003, -0.001]


def test_an_information_ratio_against_zero_is_the_sharpe():
    """**Which is the whole reason the benchmark has no default.** An IR
    reported against nothing is one statistic counted twice under two names,
    and a reader seeing both would reasonably believe two things had been
    checked.

    Asserted as an exact identity rather than approximately, because it is one:
    the IR is the Sharpe of `returns - benchmark`, and subtracting zero is a
    no-op.
    """
    from till_infinity.node.statistics import InformationRatio

    against_zero = InformationRatio(series([0.0] * len(RETURNS)))
    assert against_zero.calculate_from_returns(series(RETURNS)) == round(metrics.sharpe(RETURNS), 6)


def test_no_benchmark_is_refused_rather_than_defaulted():
    """The default that suggests itself is zero, and zero makes it the Sharpe.
    So it answers nothing instead of answering a different question."""
    from till_infinity.node.statistics import InformationRatio

    assert InformationRatio().calculate_from_returns(series(RETURNS)) is None


def test_the_ratio_against_the_book_is_a_different_reading():
    """ "Does this desk beat the others" is what an IR answers and a Sharpe
    cannot. The two differ here, which is the only thing that makes it worth
    reporting."""
    from till_infinity.node.statistics import InformationRatio

    against_book = InformationRatio(series(BOOK)).calculate_from_returns(series(RETURNS))
    assert against_book != pytest.approx(metrics.sharpe(RETURNS))
    assert against_book == pytest.approx(metrics.information_ratio(RETURNS, BOOK), abs=1e-6)


def test_a_benchmark_is_aligned_on_the_index_and_not_by_position():
    """Two series from one run differ in length wherever one strategy traded a
    day another sat out. Lined up by position that compares Tuesday's return
    against Wednesday's benchmark - a window mismatch reported as a difference
    in skill."""
    from till_infinity.node.statistics import InformationRatio

    full = series(RETURNS)
    # The same benchmark, offset by three days: only five days overlap.
    shifted = series(BOOK, start="2026-01-04")
    found = InformationRatio(shifted).calculate_from_returns(full)
    overlap = metrics.information_ratio(RETURNS[3:], BOOK[:5])
    assert found == pytest.approx(overlap, abs=1e-6)


def test_a_length_mismatch_is_refused_in_the_arithmetic():
    """The statistic aligns, so this is the layer below: handed two unaligned
    lists directly, it raises rather than truncating. Padding or trimming one
    would measure a window mismatch."""
    with pytest.raises(ValueError, match="an information ratio needs them aligned"):
        metrics.information_ratio(RETURNS, BOOK[:4])


def test_a_strategy_that_tracks_its_benchmark_exactly_has_no_ratio():
    """A constant active return has no standard deviation to divide by. That
    is not a failure - it is a strategy that *is* its benchmark - so it reports
    nothing rather than raising."""
    from till_infinity.node.statistics import InformationRatio

    same = series(RETURNS)
    assert InformationRatio(same).calculate_from_returns(same) is None


def test_the_tracking_error_is_reported_in_its_own_right():
    """It is the half a person can act on: a high ratio off a tiny tracking
    error is a strategy that barely deviates, which is a different thing to
    own from one that deviates a lot and is right."""
    # 0.005430 is this fixture's own computed value, not a measured fact from
    # any market - it is here so the second assertion's identity has an anchor.
    assert metrics.tracking_error(RETURNS, BOOK) == pytest.approx(0.005430, abs=1e-5)
    assert metrics.tracking_error(RETURNS, [0.0] * len(RETURNS)) == pytest.approx(
        metrics.moments(RETURNS)[1], abs=1e-9
    )


def test_the_deflated_ratio_against_zero_is_the_deflated_sharpe():
    """**The identity that proves the delegation is right.** A deflated IR is
    the deflated Sharpe on a differenced series, so writing the PSR algebra
    out again would have been a second copy of a formula to drift from the
    first."""
    from till_infinity.node.statistics import DeflatedInformationRatio

    trials = [0.1, -0.2, 0.35, 0.05, -0.1, 0.22]
    zero = series([0.0] * len(RETURNS))
    found = DeflatedInformationRatio(zero, trials).calculate_from_returns(series(RETURNS))
    assert found == round(metrics.deflated_sharpe(RETURNS, trials), 6)


def test_the_deflated_ratio_is_a_probability_and_not_a_smaller_ratio():
    """**The two cannot be ordered, which is the trap in the name.**

    This test used to be called `test_the_deflated_ratio_is_below_the_
    undeflated_one`, and it never asserted that - because it is not true. On
    the fixtures here the plain ratio reads 0.437 and the deflated one 0.629,
    so the deflated figure is the *larger* number. Deflating a ratio does not
    return a ratio: `DIR` is the probability that the true information ratio
    beats the benchmark once the search is paid for, and comparing it against
    the ratio itself is comparing a probability with a slope.

    So what is held here is the type and the range, plus the one ordering that
    does exist: eight trials buy less than certainty.
    """
    from till_infinity.node.statistics import DeflatedInformationRatio, InformationRatio

    book = series(BOOK)
    plain = InformationRatio(book).calculate_from_returns(series(RETURNS))
    trials = [0.1, -0.2, 0.35, 0.05, -0.1, 0.22, 0.4, -0.05]
    deflated = DeflatedInformationRatio(book, trials).calculate_from_returns(series(RETURNS))
    assert 0.0 <= deflated <= 1.0
    assert plain > 0.0
    # Measured at 0.629. Strictly below 1.0, which the bound above permits and
    # the sentence above it claimed: a search of eight trials cannot leave a
    # certainty behind.
    assert deflated < 1.0


def test_the_deflated_ratio_refuses_without_a_benchmark_or_without_trials():
    """Neither has a defensible default: no benchmark makes it `DSR`, and no
    trials makes it `PSR`. Defaulting either would give a third name to a
    statistic that is already reported."""
    from till_infinity.node.statistics import DeflatedInformationRatio

    book = series(BOOK)
    assert (
        DeflatedInformationRatio(None, [0.1, 0.2]).calculate_from_returns(series(RETURNS)) is None
    )
    assert DeflatedInformationRatio(book, [0.1]).calculate_from_returns(series(RETURNS)) is None
    assert DeflatedInformationRatio(book, []).calculate_from_returns(series(RETURNS)) is None


def test_both_ratios_are_diagnostics_and_neither_is_a_gate():
    """`DSR` is the gate. A second gate on the same algebra over a differenced
    series would count one piece of evidence twice, which is why every other
    reading here is a diagnostic.

    `DIR` earns a place in `GATES` the day a benchmark series is routinely
    available at promotion time, and this test is where that decision gets
    made rather than drifted into.
    """
    assert "InfoRatio" in DIAGNOSTICS
    assert "DIR" in DIAGNOSTICS
    assert GATES == ("DSR",)
