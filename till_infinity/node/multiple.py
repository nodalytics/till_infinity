"""Best-of-many tests: does the winner beat a benchmark, and which survive.

`selection.py` asks whether *one* candidate's Sharpe survives having been
chosen. These ask the set-level questions:

| test | answers | bar |
| --- | --- | --- |
| Hansen SPA | does the best of N beat the benchmark at all | p < 0.05 |
| Romano-Wolf | which individual candidates survive, controlling FWER | survives |
| BH / BY | what is the false discovery rate across cells | q < 0.05 |
| MinBTL | how long must a backtest be to support N trials | years |

**SPA and Romano-Wolf answer different questions and both are needed.** SPA is
a single verdict on the set - "something here is real" - and tells you nothing
about which. Romano-Wolf names survivors while controlling the family-wise
error rate, so it can reject SPA's winner and keep nobody. A set that passes
SPA and empties under Romano-Wolf has one lucky member.

**The bootstrap is stationary, not i.i.d.** Politis and Romano's geometric
block lengths, because resampling observations independently destroys the
serial dependence that makes the null fair - the same mistake as shuffling,
and this desk has measured what it costs: a level finding at p 0.015 was
anchor overlap, and the no-level control passing was the tell.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from .metrics import phi

#: Expected block length for the stationary bootstrap, in observations.
#: The reciprocal is the geometric parameter, so 20 means blocks averaging 20.
DEFAULT_BLOCK = 20


def stationary_bootstrap(
    length: int, *, block: int = DEFAULT_BLOCK, rng: random.Random | None = None
) -> list[int]:
    """Indices for one stationary-bootstrap draw.

    Geometric block lengths with wraparound, so every observation has the same
    chance of starting a block and the resample is stationary - which an
    ordinary moving-block bootstrap is not.
    """
    r = rng or random.Random()
    p = 1.0 / max(1, block)
    out: list[int] = []
    index = r.randrange(length)
    while len(out) < length:
        out.append(index)
        index = r.randrange(length) if r.random() < p else (index + 1) % length
    return out


@dataclass(frozen=True, slots=True)
class SPA:
    """Hansen's superior predictive ability test."""

    statistic: float
    p_value: float
    draws: int
    candidates: int
    #: Candidates whose mean cleared the recentering threshold and so
    #: contributed to the null. The rest are too poor to matter and including
    #: them would make the test conservative for no gain.
    contributing: int

    @property
    def passes(self) -> bool:
        return self.p_value < 0.05


def hansen_spa(
    differentials: Sequence[Sequence[float]],
    *,
    draws: int = 1_000,
    block: int = DEFAULT_BLOCK,
    seed: int = 0,
) -> SPA:
    """Does the best of N beat the benchmark?

    `differentials[k][t]` is candidate `k`'s performance *minus* the
    benchmark's at time `t`, so a positive mean is an improvement. Returns the
    p-value for the null that no candidate improves on the benchmark.

    **The recentering is what makes this Hansen rather than White.** White's
    reality check lets hopeless candidates inflate the null and so loses
    power; Hansen drops any candidate whose mean sits below
    `-sqrt(var/T) * sqrt(2 log log T)`, which is the version worth having when
    a sweep produces mostly duds - and ours will.
    """
    n = len(differentials)
    if n == 0:
        raise ValueError("no candidates")
    length = min(len(d) for d in differentials)
    if length < 8:
        raise ValueError(f"{length} observations is too few for a bootstrap")

    means = [sum(d[:length]) / length for d in differentials]
    variances = []
    for k in range(n):
        mean = means[k]
        variances.append(
            sum((x - mean) ** 2 for x in differentials[k][:length]) / max(1, length - 1)
        )
    sds = [math.sqrt(v) if v > 0 else 0.0 for v in variances]

    # The observed statistic: the best standardised mean, floored at zero.
    standardised = [
        (math.sqrt(length) * means[k] / sds[k]) if sds[k] > 0 else 0.0 for k in range(n)
    ]
    observed = max([0.0, *standardised])

    # Hansen's threshold: candidates below it cannot plausibly be the best.
    cutoff = math.sqrt(2.0 * math.log(math.log(max(3, length))))
    keep = [k for k in range(n) if sds[k] > 0 and means[k] >= -cutoff * sds[k] / math.sqrt(length)]
    if not keep:
        keep = list(range(n))

    exceeded = 0
    for i in range(draws):
        rng = random.Random(seed * 7_919 + i)
        picks = stationary_bootstrap(length, block=block, rng=rng)
        best = 0.0
        for k in keep:
            series = differentials[k]
            resampled = sum(series[j] for j in picks) / length
            # Centred on the observed mean, which is what makes it a draw from
            # the null rather than from the data.
            centred = resampled - means[k]
            if sds[k] > 0:
                best = max(best, math.sqrt(length) * centred / sds[k])
        if best >= observed:
            exceeded += 1
    return SPA(
        statistic=observed,
        p_value=(exceeded + 1) / (draws + 1),
        draws=draws,
        candidates=n,
        contributing=len(keep),
    )


@dataclass(frozen=True, slots=True)
class Survivors:
    """Romano-Wolf: which candidates survive family-wise control."""

    survived: tuple[int, ...]
    rejected_at: dict[int, float]
    candidates: int
    draws: int

    @property
    def any_survived(self) -> bool:
        return bool(self.survived)


def romano_wolf(
    differentials: Sequence[Sequence[float]],
    *,
    draws: int = 1_000,
    block: int = DEFAULT_BLOCK,
    alpha: float = 0.05,
    seed: int = 0,
) -> Survivors:
    """Step down through the candidates, controlling the family-wise error.

    Sort by t-statistic, bootstrap the *maximum* over the candidates not yet
    rejected, and reject the leader if it clears that critical value. Repeat
    with the leader removed.

    **Stepping down is what buys the power.** A single max over all candidates
    is Holm-conservative; removing each rejection shrinks the null for the
    next test, so a second genuine finding behind a strong one can still be
    seen. That matters here because a sweep's findings are usually correlated
    variants rather than one isolated winner.
    """
    n = len(differentials)
    if n == 0:
        raise ValueError("no candidates")
    length = min(len(d) for d in differentials)
    means = [sum(d[:length]) / length for d in differentials]
    sds = []
    for k in range(n):
        var = sum((x - means[k]) ** 2 for x in differentials[k][:length]) / max(1, length - 1)
        sds.append(math.sqrt(var) if var > 0 else 0.0)
    t_stats = [(math.sqrt(length) * means[k] / sds[k]) if sds[k] > 0 else 0.0 for k in range(n)]

    remaining = sorted(range(n), key=lambda k: -t_stats[k])
    survived: list[int] = []
    rejected: dict[int, float] = {}

    while remaining:
        # Bootstrap the max t over the candidates still in play.
        maxima: list[float] = []
        for i in range(draws):
            rng = random.Random(seed * 104_729 + i)
            picks = stationary_bootstrap(length, block=block, rng=rng)
            best = float("-inf")
            for k in remaining:
                series = differentials[k]
                resampled = sum(series[j] for j in picks) / length
                centred = resampled - means[k]
                if sds[k] > 0:
                    best = max(best, math.sqrt(length) * centred / sds[k])
            maxima.append(best if best > float("-inf") else 0.0)
        maxima.sort()
        index_at = math.ceil((1 - alpha) * len(maxima))
        critical = maxima[min(len(maxima) - 1, index_at)]
        leader = remaining[0]
        if t_stats[leader] > critical:
            rejected[leader] = critical
            survived.append(leader)
            remaining = remaining[1:]
        else:
            break  # nothing left clears it, so nothing below it can either
    return Survivors(
        survived=tuple(survived),
        rejected_at=rejected,
        candidates=n,
        draws=draws,
    )


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """BH adjusted p-values (q-values), controlling the false discovery rate.

    Assumes independence or positive dependence. Use `benjamini_yekutieli`
    when the tests may be arbitrarily dependent, which a correlated sweep is.
    """
    n = len(p_values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: p_values[i])
    adjusted = [0.0] * n
    running = 1.0
    for rank, index in reversed(list(enumerate(order, start=1))):
        running = min(running, n / rank * p_values[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def benjamini_yekutieli(p_values: Sequence[float]) -> list[float]:
    """BY adjusted p-values: BH times the harmonic factor.

    **The right one for a sweep of our shape.** BH assumes the tests are
    independent or positively dependent; a window sweep over correlated
    candidates is neither in any dependable way, and BY holds under arbitrary
    dependence at the cost of a `sum(1/i)` factor - about 5.2 at a hundred
    tests, which is the price of not assuming.
    """
    n = len(p_values)
    if n == 0:
        return []
    factor = sum(1.0 / i for i in range(1, n + 1))
    return [min(1.0, q * factor) for q in benjamini_hochberg(p_values)]


def p_from_sharpe(sharpe_value: float, observations: int) -> float:
    """A one-sided p-value for a Sharpe, for feeding the FDR routines."""
    if observations < 2:
        return 1.0
    return 1.0 - phi(sharpe_value * math.sqrt(observations))


def minimum_backtest_length(trials: int, target_sharpe: float) -> float:
    """MinBTL: years of backtest needed before `trials` can support a claim.

        MinBTL ~ 2 * ln(trials) / target^2

    Bailey and Lopez de Prado's reading: with N trials, the expected maximum
    annualised Sharpe from pure noise over T years is about
    `sqrt(2 ln N / T)`. Invert it and you get the history a search of that
    width needs before its winner means anything.

    **The number is usually uncomfortable, and that is the point.** A thousand
    trials against a target annualised Sharpe of 1.0 wants about fourteen
    years. A twelve-window sweep over twenty candidates at a target of 1.5
    wants about five - which is why `windows.budget` prices a sweep before it
    runs.
    """
    if trials < 2:
        return 0.0
    if target_sharpe <= 0.0:
        return float("inf")
    return 2.0 * math.log(trials) / (target_sharpe**2)


def supportable_trials(years: float, target_sharpe: float) -> float:
    """The other direction: how many trials this much history can support.

    The more actionable form, because the history is usually fixed and the
    width of the search is what we choose.
    """
    if years <= 0.0 or target_sharpe <= 0.0:
        return 1.0
    return math.exp(years * target_sharpe**2 / 2.0)
