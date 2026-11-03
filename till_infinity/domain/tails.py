"""The Student-t quantile, for anything that needs a calibrated tail.

**A second copy, and a deliberate one.** `statespace/tails.py` holds the same
arithmetic and must keep holding it: that package is required to import
nothing outside itself so it stays liftable in one move, which is a constraint
`TestVendoredCusum` enforces. And `risk` may import no layer at all - only
`domain` and `utils`, which `tests/test_service_boundaries.py` pins with
`"risk": frozenset()`. So a function both need cannot live in either, and
putting it in `statespace` and importing it from `risk` is an architecture
violation the boundary tests catch.

**The duplication is therefore required, and so it is checked.** This desk has
the unchecked version on record: `statespace/accruing.py` once held a
field-for-field copy of FOCuS, identical down to the threshold, and the drift
between the two was found by a *persistence collision* rather than by review.
`tests/test_tails_agree.py` asserts this module and `statespace.tails` return
the same numbers, so a change to one that is not made to the other fails
rather than diverges quietly.

**And not scipy**, which is what `risk/quantiles.py` reached for first. Scipy
is not in `pyproject.toml` and resolves today only because `river` pulls it in
transitively, so `test_every_third_party_import_is_declared` turned red the
moment it was imported - exactly the failure that test exists for. Four
modules in this package state the policy outright, `node/metrics.py` among
them: "hand-rolled rather than taking scipy, which would be a dependency for
one".

The dof range is measured rather than chosen: `one-bar-band.md` found a
Student-t at **3 to 5 degrees of freedom** fixing the one-bar band on 64 of 64
out-of-sample readings, where no Gaussian band is calibrated.
"""

from __future__ import annotations

import math

#: Guards for the continued fraction, as `statespace.tails` sets them.
_TINY = 1e-300
_EPS = 3e-16

#: Below this a t fit stops describing the distribution and starts chasing its
#: worst few bars. Mirrors `statespace.tails.LEAST_DOF`.
LEAST_DOF = 3.0


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


def reach(coverage: float, dof: float = LEAST_DOF) -> float:
    """The multiplier on an sd for a central band of `coverage`.

    `value +/- reach(c) * sd` covers `c` of the next observation when the
    standardised residual is a t with `dof` degrees of freedom. Equivalently
    the `(1 + c) / 2` quantile scaled to unit variance - which is also the
    `c` quantile of the **absolute** value, and that is the form a stop wants,
    since an adverse excursion is a distance.

    `dof` is clamped at `LEAST_DOF` rather than refused, matching
    `statespace.tails.reach`. A caller needing the stricter behaviour -
    `risk.quantiles.student_stop` refuses a dof with no finite variance -
    validates before delegating here.
    """
    if not 0.0 < coverage < 1.0:
        raise ValueError("coverage must lie strictly inside (0, 1)")
    dof = max(dof, LEAST_DOF)
    raw = quantile(0.5 * (1.0 + coverage), dof)
    return raw / math.sqrt(dof / (dof - 2.0))
