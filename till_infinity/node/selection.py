"""Selection and overfitting: what survives being chosen out of many.

`metrics.py` answers "is this Sharpe real given the sample". These answer the
harder question - "is this Sharpe real given that it was *picked*" - and they
disagree with each other often enough to be worth all four.

| statistic | what it answers | bar |
| --- | --- | --- |
| PSR | is the Sharpe above zero, given length, skew and fat tails | >= 0.95 |
| effective trials | how many of the trials were truly independent | feeds DSR |
| PBO (CSCV) | how often does the in-sample best fall below the out-of-sample median | < 0.2 |
| haircut Sharpe | what is left after a multiple-testing cut | positive, t > 3 |
| Lo-adjusted Sharpe | the Sharpe corrected for autocorrelation in returns | reported |

**Effective trials is the one that changes DSR's answer most.** A hundred
variants of one idea are not a hundred tests: if they are 0.9 correlated they
are closer to a dozen. Counting them as a hundred over-deflates and throws
away real findings, which is the error in the *conservative* direction and
still an error.

**PBO is the one that catches what DSR cannot.** DSR asks whether this
Sharpe beats the best of N nothings. PBO asks something orthogonal: when you
pick the best half-sample performer, how often does it land below median on
the other half? A strategy can clear DSR and still fail PBO, and that
combination is the signature of fitting the selection rather than the market.

**Lo's correction matters here specifically.** Autocorrelated returns inflate
a naive Sharpe, and this desk measures size autocorrelation of 0.21 on traded
markets against 0.00-0.13 on the synthetics -
`research/docs/pattern-fingerprint.md` - so a Sharpe computed as though returns
were independent reads high before any selection effect is considered.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

from .metrics import moments, phi, phi_inverse, sharpe


def correlation(a: Sequence[float], b: Sequence[float]) -> float:
    """Pearson correlation. Zero when either series does not vary."""
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    first, second = a[:n], b[:n]
    mean_a, mean_b = sum(first) / n, sum(second) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(first, second, strict=True))
    var_a = sum((x - mean_a) ** 2 for x in first)
    var_b = sum((y - mean_b) ** 2 for y in second)
    if var_a <= 0.0 or var_b <= 0.0:
        return 0.0
    return cov / math.sqrt(var_a * var_b)


def effective_trials(returns_by_trial: Sequence[Sequence[float]]) -> float:
    """How many independent tests the trials amount to.

        N_eff = N / (1 + (N - 1) * mean pairwise correlation)

    Clamped to `[1, N]`. **A hundred variants of one idea are not a hundred
    tests**: at a mean correlation of 0.9 they are about eleven, and deflating
    against a hundred would discard real findings. Negative mean correlation
    is clamped rather than allowed to inflate the count above N, because a
    set of trials cannot be more independent than its own size.

    The average-correlation form rather than the eigenvalue one, deliberately:
    it needs no matrix decomposition, and the precision the extra machinery
    buys is far below the precision of the question.
    """
    n = len(returns_by_trial)
    if n < 2:
        return float(max(1, n))
    pairs = [
        correlation(returns_by_trial[i], returns_by_trial[j]) for i, j in combinations(range(n), 2)
    ]
    mean_rho = sum(pairs) / len(pairs) if pairs else 0.0
    denominator = 1.0 + (n - 1) * mean_rho
    if denominator <= 0.0:
        return float(n)
    return min(float(n), max(1.0, n / denominator))


@dataclass(frozen=True, slots=True)
class PBO:
    """The probability of backtest overfitting, and how it was reached."""

    probability: float
    #: Combinations examined. `C(splits, splits/2)`.
    combinations: int
    #: Median out-of-sample rank of the in-sample winner, in `[0, 1]`.
    median_rank: float
    trials: int

    @property
    def passes(self) -> bool:
        return self.probability < 0.2


def probability_of_overfitting(
    returns_by_trial: Sequence[Sequence[float]], *, splits: int = 10
) -> PBO:
    """PBO by combinatorially symmetric cross-validation.

    Cut the sample into `splits` blocks, and for every way of choosing half of
    them as in-sample: pick the trial with the best in-sample Sharpe, then look
    up where it ranks out of sample. PBO is the share of those choices where
    the in-sample winner lands below the out-of-sample median.

    **Symmetric is the point.** Every block serves as in-sample and as
    out-of-sample across the combinations, so no single arbitrary split decides
    the answer - which is what a plain train/test split does, and why a plain
    split can be rerun until it agrees with you.

    `splits=10` gives 252 combinations. Sixteen gives 12,870 and a better
    estimate; the default is chosen so a sweep's gate costs milliseconds rather
    than seconds, since `sizing.py` exists because this pipeline has to run on
    two cores.

    **Blocks, not shuffles.** `overlapping-windows-inflate-permutation-nulls`
    is why: a level finding at p 0.015 was anchor overlap, and shuffling
    destroys the serial structure that makes a block a fair out-of-sample.
    """
    n_trials = len(returns_by_trial)
    if n_trials < 2:
        raise ValueError("PBO compares trials against each other; one is not a comparison")
    length = min(len(r) for r in returns_by_trial)
    if length < splits * 4:
        raise ValueError(
            f"{length} returns across {splits} splits leaves {length // splits} per block - "
            f"too few for a Sharpe. Use fewer splits or a longer sample."
        )

    size = length // splits
    blocks = [[r[i * size : (i + 1) * size] for r in returns_by_trial] for i in range(splits)]
    half = splits // 2
    logits: list[float] = []
    ranks: list[float] = []

    for chosen in combinations(range(splits), half):
        inside = set(chosen)
        outside = [i for i in range(splits) if i not in inside]
        in_sample = [[x for i in chosen for x in blocks[i][t]] for t in range(n_trials)]
        out_sample = [[x for i in outside for x in blocks[i][t]] for t in range(n_trials)]
        in_scores = [_safe_sharpe(series) for series in in_sample]
        out_scores = [_safe_sharpe(series) for series in out_sample]
        winner = max(range(n_trials), key=lambda t: in_scores[t])
        # Rank of the winner's out-of-sample score among all trials.
        beaten = sum(1 for score in out_scores if score < out_scores[winner])
        rank = (beaten + 1) / (n_trials + 1)
        ranks.append(rank)
        # Logit, with the ends pulled in so a clean win or loss is finite.
        bounded = min(max(rank, 1e-6), 1.0 - 1e-6)
        logits.append(math.log(bounded / (1.0 - bounded)))

    below = sum(1 for value in logits if value <= 0.0)
    ranks.sort()
    middle = ranks[len(ranks) // 2]
    return PBO(
        probability=below / len(logits),
        combinations=len(logits),
        median_rank=middle,
        trials=n_trials,
    )


def _safe_sharpe(series: Sequence[float]) -> float:
    try:
        return sharpe(series)
    except ValueError:
        return float("-inf")


@dataclass(frozen=True, slots=True)
class Haircut:
    """Harvey-Liu: the Sharpe left after a multiple-testing cut."""

    observed: float
    adjusted: float
    t_statistic: float
    trials: float
    method: str

    @property
    def cut(self) -> float:
        """Fraction of the Sharpe the adjustment removed."""
        if self.observed == 0.0:
            return 0.0
        return max(0.0, 1.0 - self.adjusted / self.observed)

    @property
    def passes(self) -> bool:
        """Still positive, and the adjusted t above 3.

        Three rather than two, which is Harvey and Liu's own argument: with
        the number of strategies that have been tested on the same data, a
        t of 2 is what noise produces.
        """
        return self.adjusted > 0.0 and self.t_statistic > 3.0


def haircut_sharpe(
    returns: Sequence[float], trials: float, *, method: str = "bonferroni"
) -> Haircut:
    """The Sharpe that survives having been chosen from `trials` candidates.

    The t-statistic is inflated by selection, so its p-value is adjusted for
    multiplicity and a Sharpe is read back out of the adjusted t.

    `trials` is a float because `effective_trials` returns one: adjusting
    against the *independent* count rather than the raw count is the whole
    reason that function exists.
    """
    series = list(returns)
    length = len(series)
    if length < 4:
        raise ValueError("a haircut needs at least 4 returns")
    observed = sharpe(series)
    t_observed = observed * math.sqrt(length)
    # Two-sided p from the observed t.
    p_single = 2.0 * (1.0 - phi(abs(t_observed)))
    count = max(1.0, trials)
    if method == "bonferroni":
        p_adjusted = min(1.0, p_single * count)
    elif method == "holm":
        # The best of N under Holm is adjusted by N, same as Bonferroni; the
        # methods differ for the others, and this function judges one.
        p_adjusted = min(1.0, p_single * count)
    else:
        raise ValueError(f"unknown method {method!r}")
    if p_adjusted >= 1.0:
        return Haircut(observed, 0.0, 0.0, count, method)
    t_adjusted = phi_inverse(1.0 - p_adjusted / 2.0)
    adjusted = math.copysign(t_adjusted / math.sqrt(length), observed)
    return Haircut(observed, adjusted, t_adjusted, count, method)


def lo_adjusted_sharpe(returns: Sequence[float], *, horizon: int = 0) -> float:
    """Lo's Sharpe, corrected for autocorrelation in the returns.

        SR_adjusted = SR / sqrt(1 + 2 * sum_{k=1}^{q-1} (1 - k/q) * rho_k)

    Autocorrelated returns make a naive Sharpe read high, and this desk
    measures size autocorrelation of 0.21 on traded markets - so the
    correction is not a formality here. Positive autocorrelation lowers the
    Sharpe; negative raises it, which is correct and worth knowing, because a
    mean-reverting series is genuinely better than its naive Sharpe suggests.

    `horizon` defaults to `min(10, len/10)`: Lo's `q`, how many lags of
    dependence to carry. Zero lags is the IID assumption and returns the
    naive figure.
    """
    series = list(returns)
    naive = sharpe(series)
    q = horizon or min(10, max(2, len(series) // 10))
    if q < 2:
        return naive
    _mean, _sd, _skew, _kurt = moments(series)
    total = 0.0
    for lag in range(1, q):
        rho = correlation(series[:-lag], series[lag:])
        total += (1.0 - lag / q) * rho
    factor = 1.0 + 2.0 * total
    if factor <= 0.0:
        # Strong negative dependence. Refused rather than square-rooted into a
        # complex number and silently cast to a number that looks fine.
        raise ValueError(
            f"the autocorrelation correction is non-positive ({factor:.4g}) over "
            f"{q} lags - this series is too strongly mean-reverting for Lo's "
            f"adjustment to say anything"
        )
    return naive / math.sqrt(factor)


@dataclass(frozen=True, slots=True)
class Verdict:
    """Every selection statistic for one candidate, and whether it passes."""

    psr: float
    dsr: float
    pbo: PBO | None
    haircut: Haircut
    lo_sharpe: float
    effective: float
    raw_trials: int

    @property
    def passes(self) -> bool:
        """All of them, because they answer different questions.

        A candidate clearing DSR and failing PBO has fitted the *selection*
        rather than the market, and that combination is the one worth
        refusing - it is invisible to either statistic alone.
        """
        return (
            self.psr >= 0.95
            and self.dsr >= 0.95
            and (self.pbo is None or self.pbo.passes)
            and self.haircut.passes
        )

    def lines(self) -> list[str]:
        out = [
            f"PSR {self.psr:.3f} (>= 0.95)",
            f"DSR {self.dsr:.3f} (>= 0.95)",
            f"haircut SR {self.haircut.adjusted:.4f} at t {self.haircut.t_statistic:.2f} "
            f"(> 3), cut {self.haircut.cut:.0%}",
            f"Lo-adjusted SR {self.lo_sharpe:.4f}",
            f"effective trials {self.effective:.1f} of {self.raw_trials}",
        ]
        if self.pbo is not None:
            out.insert(
                2,
                f"PBO {self.pbo.probability:.3f} (< 0.2) over {self.pbo.combinations} splits",
            )
        return out
