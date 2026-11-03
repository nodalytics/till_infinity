"""How wide a band has to be, once the residuals are known not to be Gaussian.

`band(sigmas)` is on every member in this package and on `facade.Readout`, and
it is a **coverage claim wearing a multiplier's clothes**. Two sigmas is 95.4%
of a Gaussian and three is 99.73%, and a caller asking for three sigmas is
asking to be breached 27 times in ten thousand. Nothing had checked whether the
residuals this band is built from are Gaussian.

They are not, and `research/docs/one-bar-band.md` has the measurement. At one
bar the residuals after a well-tracked sigma are **Student-t with about 3 to 5
degrees of freedom**, and a t over the same sigma is both flatter on PIT and
cheaper on CRPS than a Gaussian on **64 of 64 out-of-sample feed-frames** -
eight FX majors and gold, at 15m, 1h, 4h and 1d, under two independent ways of
choosing the tail index. A proper score does not fall for a worse forecast, so
the two winning together is what rules out the alternative explanation that the
calibration was bought with estimation noise.

## Where this changes an answer, and where it does not

The useful part is that the correction is **not uniform in coverage**:

* near **95%** a standardised t with 4 degrees of freedom and a Gaussian agree
  to a fraction of a percent, so every 2-sigma band already in place is about
  right and nothing downstream of it was wrong;
* at **99%** the Gaussian is roughly a fifth too narrow;
* at **99.9%** it is nearly half too narrow.

So the error is concentrated exactly where stops, risk limits and worst-case
sizing live, and it is absent where most casual reads of a band happen. That is
worth stating in both directions, because the finding is easy to overstate into
"every band here was wrong" and that is not what was measured.

Read the other way, `coverage()` says what a sigma multiplier actually buys: a
three-sigma band on t-distributed residuals is breached several times more
often than its Gaussian label promises.

## Why this is not the conformal machinery, or the empirical quantiles

Both already exist here and both are better than this for their own job.
`conformal.py` and `vol/envelope.py` hold a target coverage distribution-free
and keep holding it under shift. `facade.Readout.quantiles` carries the
empirical quantiles of the member's own standardised residuals, at CRPS 0.9899
against a Gaussian's 1.0000.

This is for the one thing neither can do. **An empirical quantile cannot reach
past its own sample.** A 99.9% band wants the 1-in-1000 residual, and a few
thousand residuals contain two or three of those, so the estimate out there is
noise - and a conformal corrector calibrated on the same history has the same
problem for the same reason. A fitted tail index extrapolates, because the
shape is assumed rather than counted. That assumption is the price, and the
measurement above is what was paid for it.

Use the empirical quantiles or a conformal interval in the body, and this in
the far tail. They are answering different questions.

## No library

`scipy` is not a dependency of this project, so the t distribution is here in
full: the regularised incomplete beta by continued fraction, the t CDF from it,
and the quantile by bisection. The tests check it against published t-table
values rather than against another implementation.
"""

from __future__ import annotations

import math

#: The measured tail index by bar interval, from `one-bar-band.md`. These are
#: the CRPS-chosen medians over eight FX majors and gold; maximum likelihood on
#: the standardised residuals - which never sees CRPS or the PIT - gives 3.72,
#: 3.22, 3.23 and 5.13 for the same four, so the two methods agree to about
#: half a degree of freedom everywhere.
#:
#: The rise with the interval is aggregational Gaussianity: sums of returns are
#: closer to Gaussian than their parts, and it was not looked for.
DOF = {
    "15m": 4.0,
    "1h": 3.5,
    "4h": 4.0,
    "1d": 5.0,
}

#: For an interval nobody measured. The fattest measured value rather than the
#: mean, because being too wide in the far tail is the forgiving direction.
DEFAULT_DOF = 3.5

#: Below this the fit stops describing the distribution and starts chasing its
#: worst few bars. On gold, maximum likelihood ran to 2.65 at 4h and scored
#: **worse** on both flatness and CRPS than 3.0 did. A t needs more than two
#: degrees of freedom to have a variance at all, and this says the usable floor
#: is well above that bound.
LEAST_DOF = 3.0

_TINY = 1e-300
_EPS = 3e-16


def dof_for(interval: str) -> float:
    """The measured tail index for a bar interval, floored."""
    return max(DOF.get(interval, DEFAULT_DOF), LEAST_DOF)


def _betacf(a: float, b: float, x: float, iters: int = 300) -> float:
    """Lentz's continued fraction for the incomplete beta."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _TINY:
        d = _TINY
    d = 1.0 / d
    carried = d
    for m in range(1, iters + 1):
        m2 = 2 * m
        step = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + step * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + step / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        carried *= d * c
        step = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + step * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + step / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        moved = d * c
        carried *= moved
        if abs(moved - 1.0) < _EPS:
            break
    return carried


def _betainc(a: float, b: float, x: float) -> float:
    """The regularised incomplete beta `I_x(a, b)`."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    # Swapped below the crossover, where the fraction converges fast.
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def cdf(z: float, dof: float) -> float:
    """`P(T <= z)` for a Student-t with `dof` degrees of freedom."""
    if dof <= 0.0:
        raise ValueError("dof must be positive")
    tail = 0.5 * _betainc(0.5 * dof, 0.5, dof / (dof + z * z))
    return 1.0 - tail if z >= 0.0 else tail


def quantile(probability: float, dof: float) -> float:
    """The inverse of `cdf`, by bisection. Exact to a part in a trillion."""
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must lie strictly inside (0, 1)")
    low, high = -1e6, 1e6
    for _ in range(200):
        mid = 0.5 * (low + high)
        if cdf(mid, dof) < probability:
            low = mid
        else:
            high = mid
        if high - low < 1e-12 * max(1.0, abs(mid)):
            break
    return 0.5 * (low + high)


def _unit(dof: float) -> float:
    """The factor that rescales a t to unit variance."""
    if dof <= 2.0:
        raise ValueError("a t needs more than two degrees of freedom to have a variance")
    return math.sqrt((dof - 2.0) / dof)


def reach(coverage: float, dof: float = DEFAULT_DOF) -> float:
    """The multiplier on the spread's **sd** for a central band of `coverage`.

    `value +/- reach(c) * sd` covers `c` of the next observation, if the
    standardised residual is a t with `dof` degrees of freedom. At `c` near
    0.95 this is within a fraction of a percent of the Gaussian's 1.96, and it
    grows well past it further out - which is the whole point.
    """
    if not 0.0 < coverage < 1.0:
        raise ValueError("coverage must lie strictly inside (0, 1)")
    dof = max(dof, LEAST_DOF)
    return quantile(0.5 * (1.0 + coverage), dof) * _unit(dof)


def coverage(sigmas: float = 2.0, dof: float = DEFAULT_DOF) -> float:
    """What a `sigmas`-wide band actually covers, which is the diagnostic.

    The inverse reading of `reach`, and the one that shows the cost of the
    Gaussian label: a three-sigma band on t-distributed residuals is breached
    several times more often than 0.27%.
    """
    if sigmas < 0.0:
        raise ValueError("sigmas must not be negative")
    dof = max(dof, LEAST_DOF)
    return 2.0 * cdf(sigmas / _unit(dof), dof) - 1.0
