"""Wasserstein: a second axis for judging a member, beside likelihood.

Two unrelated reviews pointed at the same gap. Düring's programme compares
kinetic wealth models by their **convergence rate to the steady state in a
Wasserstein metric** - exponential for one family, at best algebraic for
another - and TradeFM scores a generative model of order flow by
Kolmogorov-Smirnov and Wasserstein distance to real data. A third, on
regime clustering, uses Wasserstein distance between rolling return
distributions as the clustering metric itself.

This package compares members on **held-out likelihood and nothing else**.

## Why a second axis is not redundant

Likelihood is an average of log densities. It rewards a model that is right
on average and is almost blind to the *shape* of what it gets wrong: a member
whose standardised innovations are far too heavy-tailed, and one whose
innovations are too narrow, can post the same likelihood by trading density
in the middle against density in the tails.

The standardised innovation is the right thing to measure, because under a
correctly specified member it is **standard normal by construction** - every
member in this package already reports `last_standardised`, and making that
mean one thing across members was a day's work earlier in this history. So
the distance between the empirical distribution of those innovations and
`N(0, 1)` is a calibration number that owes nothing to the likelihood.

A member can be best on likelihood and worst here. That is the point of
having it.

## The one-dimensional case is a sort, not an optimisation

Optimal transport in general needs a solver. In one dimension the optimal
coupling is the monotone one, so the Wasserstein-`p` distance between two
samples is the `L_p` distance between their **sorted** values - or between
quantile functions when the sizes differ. That makes this exact, fast and
dependency-free, which is why it is written here rather than imported.

`tests/test_statespace.py` checks it against `scipy.stats.wasserstein_distance`
where scipy happens to be installed, per the module rule that anything
hand-written arrives with its reference.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

#: Points at which the two quantile functions are compared when the samples
#: differ in size. Two hundred is far finer than the tail resolution of any
#: sample this is used on.
GRID = 200


def _quantile(ordered: Sequence[float], share: float) -> float:
    """Linear-interpolated quantile of an already-sorted sample."""
    if not ordered:
        return float("nan")
    if len(ordered) == 1:
        return float(ordered[0])
    position = share * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def wasserstein(left: Sequence[float], right: Sequence[float], power: int = 1) -> float:
    """`W_p` between two samples. Exact in one dimension, by sorting.

    Equal sizes take the direct sorted-pair form; unequal sizes compare
    quantile functions on a shared grid, which is the same quantity evaluated
    by quadrature rather than exactly.
    """
    if not left or not right:
        return float("nan")
    a = sorted(float(v) for v in left)
    b = sorted(float(v) for v in right)
    if len(a) == len(b):
        total = statistics.fmean(abs(x - y) ** power for x, y in zip(a, b, strict=True))
    else:
        total = statistics.fmean(
            abs(_quantile(a, (k + 0.5) / GRID) - _quantile(b, (k + 0.5) / GRID)) ** power
            for k in range(GRID)
        )
    return total ** (1.0 / power)


def _normal_quantile(share: float) -> float:
    """Inverse standard normal CDF, Acklam's rational approximation.

    Accurate to about `1.15e-9` across the range, which is far beyond what a
    sample of a few thousand innovations can resolve. Written out because
    `statistics.NormalDist` exists but a dependency-free closed form keeps
    this module importable anywhere the package is.
    """
    if share <= 0.0:
        return -math.inf
    if share >= 1.0:
        return math.inf
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
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    low, high = 0.02425, 1.0 - 0.02425
    if share < low:
        q = math.sqrt(-2.0 * math.log(share))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if share > high:
        q = math.sqrt(-2.0 * math.log(1.0 - share))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    q = share - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def against_normal(values: Sequence[float], power: int = 1) -> float:
    """`W_p` between a sample and `N(0, 1)`. The member calibration number.

    Zero is a perfectly specified member. **Scale and shape both count**: a
    member whose innovations are twice as wide as it believes scores about
    0.8, and one with the right width but heavy tails scores on the tails
    alone - which is exactly what a likelihood averages away.
    """
    usable = [float(v) for v in values if math.isfinite(v)]
    if len(usable) < 8:
        return float("nan")
    ordered = sorted(usable)
    n = len(ordered)
    total = statistics.fmean(
        abs(ordered[k] - _normal_quantile((k + 0.5) / n)) ** power for k in range(n)
    )
    return total ** (1.0 / power)
