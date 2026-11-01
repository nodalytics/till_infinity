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

from . import metrics
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


class Expectancy(PortfolioStatistic):
    """Mean return per observation, in R. **A diagnostic, not a gate.**

    `sharpe` is `expectancy / sd`, so this and the Sharpe are the same
    quantity differently scaled. Reported because R per trade is what a person
    reads and a Sharpe is not; **not** gated on, because a gate on both is one
    piece of evidence counted twice.
    """

    @property
    def name(self) -> str:
        return "Expectancy"

    def calculate_from_returns(self, returns) -> float | None:
        return round(metrics.expectancy(_clean(returns)), 6)


class WinRate(PortfolioStatistic):
    """Share of observations that made money. **A diagnostic, not a gate.**

    Zero-return observations count on neither side: a flat trade is neither
    won nor lost.
    """

    @property
    def name(self) -> str:
        return "WinRate"

    def calculate_from_returns(self, returns) -> float | None:
        got = metrics.win_rate(_clean(returns))
        return None if got is None else round(got, 4)


class Payoff(PortfolioStatistic):
    """Average win over average loss. **A diagnostic, not a gate.**"""

    @property
    def name(self) -> str:
        return "Payoff"

    def calculate_from_returns(self, returns) -> float | None:
        got = metrics.payoff(_clean(returns))
        return None if got is None else round(got, 4)


class ProbabilisticWinRate(PortfolioStatistic):
    """P(true win rate > 0.5). **The one probability here that is not the
    Sharpe rescaled.**

    Its standard error is a proportion's, `sqrt(p(1-p)/n)`, not a mean's - so
    it is different machinery and answers a question the Sharpe does not
    contain. Measured on two constructed series: PSR ranks a 70%-at-0.5R
    strategy *below* a 30%-at-3R one (0.779 against 0.894) while this ranks it
    *above* (1.000 against 0.000). Opposite orderings, which a rescaling
    cannot produce.

    **Never read alone.** A 30% win rate at a 3R payoff is a good strategy, so
    a low number here is not a failure - it is half of a description whose
    other half is `Payoff`.
    """

    @property
    def name(self) -> str:
        return "P_WinRate"

    def calculate_from_returns(self, returns) -> float | None:
        return round(metrics.probabilistic_win_rate(_clean(returns)), 6)


class ProfitFactor(PortfolioStatistic):
    """Gross wins over gross losses. **A diagnostic, not a gate.**

    `None` where there are no losses, which is where it is undefined and where
    a strategy looks best - a short sample, a quiet period, a lucky run.
    Returning a number there would put it top of any ranking.
    """

    @property
    def name(self) -> str:
        return "ProfitFactor"

    def calculate_from_returns(self, returns) -> float | None:
        got = metrics.profit_factor(_clean(returns))
        return None if got is None else round(got, 4)


def register(analyzer, trial_sharpes: Sequence[float] = ()) -> None:
    """Attach the gate statistic and the diagnostics to a `PortfolioAnalyzer`.

    Called by the backtest and live nodes so the same figures appear on both
    sides, which is the point of running one engine for measurement and
    execution.

    ## The split, which is the whole design

    **One statistic gates: the deflated Sharpe.** The multiple-testing
    correction applies once to the whole search, and four correlated statistics
    with four thresholds gives an effective trial count nobody can compute -
    requiring all four to pass costs power rather than buying strictness. The
    desk's own record is explicit: several candidates passed DSR, PBO and SPA,
    and what exposed them was running the strategy on **surrogates** and
    breaking the results down **by hour**. More metrics did not help; a
    different *kind* of test did.

    ## Redundant descriptions yes, redundant probabilities no

    `Expectancy` is reported and `P_Expectancy` is **not**, though both exist
    in `metrics.py`. `sharpe = mean / sd`, so a probability on the mean is the
    PSR differently scaled - on a real sample the two agreed to three decimals.
    A bare number in R is a unit conversion a person reads and nobody mistakes
    for a test; **a probability looks like a test result**, and 0.9971 printed
    beside 0.9975 will be read as two confirmations. That reading is the error
    the correction exists to prevent, so the number stays and the probability
    goes.

    What replaced it is `P_WinRate`, which is genuinely different machinery - a
    binomial proportion rather than a rescaled mean - and which disagrees with
    the PSR in ordering on constructed cases, as a rescaling could not.
    """
    analyzer.register_statistic(PerPeriodSharpe())
    analyzer.register_statistic(ProbabilisticSharpe())
    analyzer.register_statistic(MinimumTrackRecord())
    # The diagnostics. `ProbabilisticExpectancy` is deliberately absent - see
    # the docstring above.
    analyzer.register_statistic(Expectancy())
    analyzer.register_statistic(ProfitFactor())
    analyzer.register_statistic(WinRate())
    analyzer.register_statistic(Payoff())
    analyzer.register_statistic(ProbabilisticWinRate())
    if len(tuple(trial_sharpes)) >= 2:
        analyzer.register_statistic(DeflatedSharpe(trial_sharpes))


#: The one statistic a promotion gate may read. Named so a future gate cannot
#: quietly add a second without changing this line, which is the whole
#: argument above made mechanical.
GATES: tuple[str, ...] = ("DSR",)

#: Reported for a person. Correlated with each other and with the gate, which
#: is why they are not gates.
DIAGNOSTICS: tuple[str, ...] = (
    "Expectancy",
    "MinTRL",
    "PSR",
    "Payoff",
    "P_WinRate",
    "ProfitFactor",
    "SR_period",
    "WinRate",
)
