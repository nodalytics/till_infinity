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


def register(
    analyzer,
    trial_sharpes: Sequence[float] = (),
    benchmark: pd.Series | None = None,
    trial_ratios: Sequence[float] = (),
) -> None:
    """Attach the gate statistic and the diagnostics to a `PortfolioAnalyzer`.

    Called by the backtest and live nodes so the same figures appear on both
    sides, which is the point of running one engine for measurement and
    execution.

    ## The split, which is the whole design

    **One statistic gates: the deflated Sharpe.** The multiple-testing
    correction applies once to the whole search, and four correlated statistics
    with four thresholds gives an effective trial count nobody can compute -
    requiring all four to pass costs power rather than buying strictness. The
    desk holds that several candidates passed DSR, PBO and SPA and were exposed
    only by **surrogates** and a breakdown **by hour** - more metrics did not
    help, a different *kind* of test did. That claim is **unsourced**, and
    `surrogates.py` says where it was looked for; the split above stands on the
    correlation argument without it.

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
    # **Registered only with a benchmark**, on the same terms as `DSR` with
    # its trials: without one an information ratio *is* the Sharpe, so a
    # statistic registered unconditionally would report `None` on every run
    # and put two always-empty columns in every report. A reading that is
    # always absent is noise that a reader learns to skip, and the next real
    # absence is skipped with it.
    if benchmark is not None:
        analyzer.register_statistic(InformationRatio(benchmark))
        if len(tuple(trial_ratios)) >= 2:
            analyzer.register_statistic(DeflatedInformationRatio(benchmark, trial_ratios))


#: The one statistic a promotion gate may read. Named so a future gate cannot
#: quietly add a second without changing this line, which is the whole
#: argument above made mechanical.
class InformationRatio(PortfolioStatistic):
    """Active return over tracking error, against a benchmark you supply.

    **The benchmark is required and there is no default**, because against a
    zero benchmark this is exactly the Sharpe - `metrics.information_ratio`
    says so - and an information ratio reported against nothing is one
    statistic counted twice under two names. A reader seeing both would
    reasonably believe two things had been checked.

    The benchmark that makes it a different question is **the rest of the
    book**: "does this desk beat the others" is what an IR answers and a
    Sharpe cannot. That is also the reading `strategy-rotation-is-not-
    timeable` warns about - every pause rule this desk tried matched random
    pausing at the same duty cycle - so a poor IR against the book is evidence
    for *retiring* a strategy and not for switching it on and off.

    A diagnostic rather than a gate. It is `expectancy / sd` of a differenced
    series, so it is the same shape of quantity as `SR_period` and gating on
    both would count one piece of evidence twice.

    Constructed with the series rather than reading one, because
    `calculate_from_returns` is handed a strategy's returns and nothing else -
    so a statistic that wanted the book would have to reach for it, and what
    it reached into would differ between a backtest and a live node.
    """

    def __init__(self, benchmark: pd.Series | None = None) -> None:
        super().__init__()
        self._benchmark = benchmark

    @property
    def name(self) -> str:
        return "InfoRatio"

    def calculate_from_returns(self, returns: pd.Series) -> float | None:
        if self._benchmark is None:
            # Refused rather than defaulted. The default that suggests itself
            # is zero, and zero makes this the Sharpe.
            return None
        if returns is None or len(returns) == 0:
            return None
        # **Aligned on the index, before either side is cleaned.** Two series
        # from one run differ in length wherever one strategy traded a day
        # another sat out, and lining those up by position would compare
        # Tuesday's return against Wednesday's benchmark - a window mismatch
        # reported as a difference in skill. `_clean` drops to a list and
        # loses the index, so the join has to come first.
        paired = pd.concat(
            [pd.Series(returns), pd.Series(self._benchmark)], axis=1, join="inner"
        ).dropna()
        if len(paired) < 4:
            return None
        try:
            return round(
                metrics.information_ratio(
                    [float(x) for x in paired.iloc[:, 0]],
                    [float(x) for x in paired.iloc[:, 1]],
                ),
                6,
            )
        except ValueError:
            # A constant active return has no ratio - which happens when a
            # strategy tracks its benchmark exactly, and is not a failure.
            return None


class DeflatedInformationRatio(PortfolioStatistic):
    """`DIR`: the information ratio, deflated against the search that found it.

    The same construction as `DSR` and for the same reason - a candidate
    selected as the best of many trials shows a ratio inflated by the
    selection, and at a target Sharpe of 1.5 one month of data supports about
    one trial. What changes is only which series it is computed on.

    **The trial ratios must be information ratios, not Sharpes.**
    `expected_max_sharpe` reads their spread to say what the best of them
    would show from nothing, so a spread measured on undifferenced returns
    deflates against a different search - and the answer would look like a
    number rather than like a mistake. The constructor takes both because
    neither has a defensible default: no benchmark makes this `DSR`, and no
    trials makes it `PSR`.

    A **gate candidate rather than a gate**, and deliberately not in `GATES`.
    `DSR` is the gate; adding a second gate on the same algebra over a
    differenced series would count one piece of evidence twice, which is the
    reason every other reading here is a diagnostic. It earns a place in
    `GATES` the day a benchmark series is routinely available at promotion
    time, and not before.
    """

    def __init__(
        self,
        benchmark: pd.Series | None = None,
        trial_ratios: Sequence[float] = (),
    ) -> None:
        super().__init__()
        self._benchmark = benchmark
        self._trials = tuple(float(ratio) for ratio in trial_ratios)

    @property
    def name(self) -> str:
        return "DIR"

    @property
    def trials(self) -> int:
        return len(self._trials)

    def calculate_from_returns(self, returns: pd.Series) -> float | None:
        if self._benchmark is None or self.trials < 2:
            # Both refused rather than defaulted, for the reasons above: this
            # would otherwise quietly become `DSR` or `PSR` under a third name.
            return None
        if returns is None or len(returns) == 0:
            return None
        paired = pd.concat(
            [pd.Series(returns), pd.Series(self._benchmark)], axis=1, join="inner"
        ).dropna()
        if len(paired) < 4:
            return None
        try:
            return round(
                metrics.deflated_information_ratio(
                    [float(x) for x in paired.iloc[:, 0]],
                    [float(x) for x in paired.iloc[:, 1]],
                    self._trials,
                ),
                6,
            )
        except ValueError:
            return None


GATES: tuple[str, ...] = ("DSR",)

#: Reported for a person. Correlated with each other and with the gate, which
#: is why they are not gates.
DIAGNOSTICS: tuple[str, ...] = (
    "DIR",
    "Expectancy",
    "InfoRatio",
    "MinTRL",
    "PSR",
    "Payoff",
    "P_WinRate",
    "ProfitFactor",
    "SR_period",
    "WinRate",
)
