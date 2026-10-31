"""Deflated Sharpe ratio, and the pieces it needs.

**A Sharpe ratio read off the best of many backtests is not a Sharpe ratio.**
Bailey and Lopez de Prado's deflated Sharpe states the probability that an
observed Sharpe exceeds what the *best of N trials* would produce under a null
of no skill, correcting for three things at once: how many candidates were
tried, how long the track record is, and how non-normal the returns are.

All three bite on this desk, and the third hardest. Traded markets here run
kurtosis between 20 and 74 against a Gaussian's 3, so the variance of a Sharpe
estimate is far larger than the normal-theory formula implies - a Sharpe that
looks comfortable on 500 fat-tailed returns is not.

    PSR(SR*) = Phi( (SR - SR*) * sqrt(T - 1)
                    / sqrt(1 - g3*SR + (g4 - 1)/4 * SR^2) )

with `g3` the skew and `g4` the kurtosis of the returns, and

    SR* = sqrt(Var(SR_trials)) * [ (1 - y) * Phi^-1(1 - 1/N)
                                 + y * Phi^-1(1 - 1/(N*e)) ]

`y` being Euler-Mascheroni. DSR is PSR evaluated at that SR*: the expected
maximum Sharpe from N trials of nothing.

**`Var(SR_trials)` is the input that is usually faked.** It is the spread of
Sharpes across everything that was tried, so it only exists if the search kept
its losers. A discovery node that reports its best candidate and discards the
rest cannot compute this, and a guessed variance makes the whole number
decorative. `trial_variance` therefore takes the readings, not a number.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: Euler-Mascheroni, as it appears in the expected-maximum term.
EULER = 0.577_215_664_901_532_9


def phi(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def phi_inverse(p: float) -> float:
    """Standard normal quantile, by Acklam's rational approximation.

    Hand-rolled rather than taking scipy, which would be a dependency for one
    function on a path that already avoids numpy. Accurate to about 1.15e-9
    in relative terms across the open interval, which is far beyond what a
    Sharpe threshold needs. `diagnostics._chi2_sf` is the precedent.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"phi_inverse needs 0 < p < 1, got {p}")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00)
    low, high = 0.02425, 1.0 - 0.02425
    if p < low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p > high:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def moments(returns: Sequence[float]) -> tuple[float, float, float, float]:
    """`(mean, sd, skew, kurtosis)` of a return series, kurtosis not excess.

    Population moments, matching the DSR formulation. A series of fewer than
    four points has no kurtosis worth the name and is refused.
    """
    n = len(returns)
    if n < 4:
        raise ValueError(f"need at least 4 returns for a skew and kurtosis, got {n}")
    mean = sum(returns) / n
    centred = [r - mean for r in returns]
    m2 = sum(c * c for c in centred) / n
    if m2 <= 0.0:
        raise ValueError("a constant return series has no Sharpe")
    sd = math.sqrt(m2)
    m3 = sum(c**3 for c in centred) / n
    m4 = sum(c**4 for c in centred) / n
    return mean, sd, m3 / sd**3, m4 / sd**4


def sharpe(returns: Sequence[float]) -> float:
    """Per-period Sharpe. Not annualised.

    **Deliberately not annualised**, because annualising multiplies the
    estimate and its error by the same factor while the *threshold* below is
    computed on the per-period scale. Mixing the two is how a Sharpe gets
    compared against a bar it was never measured against.
    """
    mean, sd, _skew, _kurt = moments(returns)
    return mean / sd


def trial_variance(trial_sharpes: Sequence[float]) -> float:
    """Variance of the Sharpes across everything that was tried.

    Takes the readings rather than a number, because this is the term a search
    cannot supply unless it kept its losers - and a guessed value makes the
    deflation decorative. Two trials is the minimum that has a variance at all.
    """
    n = len(trial_sharpes)
    if n < 2:
        raise ValueError(
            "the deflation needs the spread of Sharpes across trials; with fewer "
            "than two there is nothing to deflate against, and reporting an "
            "undeflated Sharpe as deflated is worse than reporting neither"
        )
    mean = sum(trial_sharpes) / n
    return sum((s - mean) ** 2 for s in trial_sharpes) / (n - 1)


def expected_max_sharpe(variance: float, trials: int) -> float:
    """`SR*`: the Sharpe the best of `trials` nothings would show."""
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if variance < 0.0:
        raise ValueError("variance cannot be negative")
    if trials == 1:
        return 0.0
    spread = math.sqrt(variance)
    return spread * (
        (1.0 - EULER) * phi_inverse(1.0 - 1.0 / trials)
        + EULER * phi_inverse(1.0 - 1.0 / (trials * math.e))
    )


def probabilistic_sharpe(returns: Sequence[float], benchmark: float = 0.0) -> float:
    """`PSR(benchmark)`: the probability the true Sharpe exceeds it.

    The denominator is where non-normality enters, and on this desk it is not
    a small correction: positive excess kurtosis inflates it, so a given
    Sharpe clears a lower bar on well-behaved returns than on the fat-tailed
    ones every market here produces.
    """
    _mean, _sd, skew, kurt = moments(returns)
    sr = sharpe(returns)
    n = len(returns)
    spread = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if spread <= 0.0:
        # Possible with strong skew at a high Sharpe. Refused rather than
        # square-rooted into a complex number and silently cast.
        raise ValueError(
            f"the Sharpe's variance estimate is non-positive ({spread:.4g}) at "
            f"skew {skew:.3f} and kurtosis {kurt:.1f} - this series is too "
            f"non-normal for the PSR approximation to say anything"
        )
    return phi((sr - benchmark) * math.sqrt(n - 1) / math.sqrt(spread))


def deflated_sharpe(returns: Sequence[float], trial_sharpes: Sequence[float]) -> float:
    """DSR: PSR against the expected maximum of the trials that were run.

    Returns a probability. Read it as: given that this candidate was the best
    of what was tried, how likely is its true Sharpe to be above zero.
    """
    variance = trial_variance(trial_sharpes)
    threshold = expected_max_sharpe(variance, len(trial_sharpes))
    return probabilistic_sharpe(returns, benchmark=threshold)


def minimum_track_record(returns: Sequence[float], target: float = 0.95) -> float:
    """How many returns are needed before PSR could reach `target`.

    The useful direction of the same algebra: not "is this significant" but
    "how long until it could be". A candidate whose answer exceeds the history
    available has not failed - it is unmeasurable, which is a different
    decision and usually a cheaper one to make early.
    """
    _mean, _sd, skew, kurt = moments(returns)
    sr = sharpe(returns)
    if sr <= 0.0:
        return float("inf")
    spread = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    return 1.0 + spread * (phi_inverse(target) / sr) ** 2
