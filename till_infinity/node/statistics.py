"""Our metrics, as Nautilus portfolio statistics.

`PortfolioStatistic` is the engine's plug-in point: implement
`calculate_from_returns` and register it, and the figure appears in every
backtest report and on the live portfolio beside Sharpe and win rate. So the
deflated Sharpe stops being something a report has to remember to compute.

**The deflation needs context a single run does not have.** A backtest knows
its own returns; it cannot know how many candidates were tried to find it. So
`DeflatedSharpe` is constructed with the trial Sharpes by whatever ran the
search, and refuses to report a number when it was not given them - an
undeflated figure labelled "deflated" is worse than no figure.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
from nautilus_trader.analysis.statistic import PortfolioStatistic

from .metrics import (
    deflated_sharpe,
    expected_max_sharpe,
    minimum_track_record,
    probabilistic_sharpe,
    sharpe,
    trial_variance,
)


def _clean(returns: pd.Series) -> list[float]:
    """Nautilus hands a pandas Series, which may be empty or hold NaNs."""
    if returns is None or len(returns) == 0:
        return []
    return [float(x) for x in returns.dropna().to_numpy()]


class ProbabilisticSharpe(PortfolioStatistic):
    """`PSR(0)`: the probability the true Sharpe is above zero.

    Worth having beside the plain Sharpe even without a search to deflate
    against, because the denominator carries the skew and kurtosis. Every
    market this desk trades has kurtosis far above a Gaussian's 3, so a Sharpe
    and its reliability are much less tightly linked here than the usual
    normal-theory reading assumes.
    """

    @property
    def name(self) -> str:
        return "PSR"

    def calculate_from_returns(self, returns: pd.Series) -> float | None:
        series = _clean(returns)
        if len(series) < 4:
            return None
        try:
            return probabilistic_sharpe(series)
        except ValueError:
            # Too non-normal for the approximation to say anything. Reported as
            # absent rather than as a number the formula cannot support.
            return None


class DeflatedSharpe(PortfolioStatistic):
    """`DSR`: PSR against the expected best of the trials that were run.

    Constructed with the Sharpes of everything the search produced, losers
    included. Without at least two it reports nothing.
    """

    def __init__(self, trial_sharpes: Sequence[float] = ()) -> None:
        self._trials = tuple(float(s) for s in trial_sharpes)

    @property
    def name(self) -> str:
        return "DSR"

    @property
    def trials(self) -> int:
        return len(self._trials)

    @property
    def bar(self) -> float | None:
        """`SR*`, the Sharpe the best of these trials would show from nothing."""
        if self.trials < 2:
            return None
        return expected_max_sharpe(trial_variance(self._trials), self.trials)

    def calculate_from_returns(self, returns: pd.Series) -> float | None:
        series = _clean(returns)
        if len(series) < 4 or self.trials < 2:
            return None
        try:
            return deflated_sharpe(series, self._trials)
        except ValueError:
            return None


class MinimumTrackRecord(PortfolioStatistic):
    """How many returns would be needed before PSR could reach 0.95.

    The question that is usually more actionable than significance: a
    candidate asking for more history than exists has not failed, it is
    unmeasurable - a different decision, and a cheaper one to make early.
    """

    @property
    def name(self) -> str:
        return "MinTRL"

    def calculate_from_returns(self, returns: pd.Series) -> float | None:
        series = _clean(returns)
        if len(series) < 4:
            return None
        try:
            got = minimum_track_record(series)
        except ValueError:
            return None
        return None if got == float("inf") else got


class PerPeriodSharpe(PortfolioStatistic):
    """The plain Sharpe, un-annualised, so it is comparable to `SR*`.

    Nautilus ships an annualised Sharpe. Annualising multiplies the estimate
    and its error by the same factor, but `expected_max_sharpe` is computed on
    the per-period scale - so reporting both avoids comparing a number against
    a bar it was never measured against.
    """

    @property
    def name(self) -> str:
        return "SR_period"

    def calculate_from_returns(self, returns: pd.Series) -> float | None:
        series = _clean(returns)
        if len(series) < 4:
            return None
        try:
            return sharpe(series)
        except ValueError:
            return None


def register(analyzer, trial_sharpes: Sequence[float] = ()) -> None:
    """Attach all of them to a `PortfolioAnalyzer`.

    Called by the backtest and live nodes so the same figures appear on both
    sides, which is the point of running one engine for measurement and
    execution.
    """
    analyzer.register_statistic(PerPeriodSharpe())
    analyzer.register_statistic(ProbabilisticSharpe())
    analyzer.register_statistic(MinimumTrackRecord())
    if len(tuple(trial_sharpes)) >= 2:
        analyzer.register_statistic(DeflatedSharpe(trial_sharpes))
