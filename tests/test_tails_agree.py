"""The two Student-t implementations must return the same numbers.

`statespace/tails.py` and `domain/tails.py` hold the same arithmetic, and the
duplication is **required** rather than careless. `statespace` must import
nothing outside itself so it stays liftable in one move, which
`TestVendoredCusum` enforces; and `risk` may import no layer at all, which
`test_service_boundaries.py` pins as `"risk": frozenset()`. So a function both
need cannot live in either of them, and importing across is an architecture
violation the boundary tests catch - as they did.

**This desk has the unchecked version of this situation on record.**
`statespace/accruing.py` once held a field-for-field copy of FOCuS, identical
down to the threshold, and the drift between the two copies was found by a
*persistence collision* rather than by review, because the registry keys state
on module basename and class name and two modules called `focus` holding two
classes called `Focus` resolved to one key.

So the duplication here is checked. A change to one that is not made to the
other fails this file rather than diverging quietly.
"""

from __future__ import annotations

import pytest

from till_infinity.domain import tails as mine
from till_infinity.statespace import tails as theirs

#: The measured range plus the ends of what a caller might ask for.
COVERAGES = [0.50, 0.80, 0.90, 0.95, 0.99, 0.999]
DEGREES = [3.0, 3.5, 4.0, 5.0, 8.0, 30.0]


@pytest.mark.parametrize("coverage", COVERAGES)
@pytest.mark.parametrize("dof", DEGREES)
def test_the_band_multiplier_agrees(coverage, dof):
    """To floating point, not to a tolerance somebody chose."""
    assert mine.reach(coverage, dof) == pytest.approx(theirs.reach(coverage, dof), abs=1e-12)


@pytest.mark.parametrize("probability", [0.55, 0.75, 0.90, 0.975, 0.995])
@pytest.mark.parametrize("dof", DEGREES)
def test_the_quantile_agrees(probability, dof):
    assert mine.quantile(probability, dof) == pytest.approx(
        theirs.quantile(probability, dof), abs=1e-12
    )


@pytest.mark.parametrize("z", [-4.0, -1.0, 0.0, 0.5, 2.0, 6.0])
@pytest.mark.parametrize("dof", DEGREES)
def test_the_cdf_agrees(z, dof):
    assert mine.cdf(z, dof) == pytest.approx(theirs.cdf(z, dof), abs=1e-12)


def test_both_clamp_the_degrees_of_freedom_the_same_way():
    """A t below two has no finite variance, so a unit-scale band is not
    defined there. Both clamp rather than raise, and a caller wanting the
    stricter behaviour - `risk.quantiles.student_stop` refuses it - validates
    before delegating."""
    assert mine.LEAST_DOF == theirs.LEAST_DOF
    assert mine.reach(0.90, 1.0) == pytest.approx(theirs.reach(0.90, 1.0), abs=1e-12)


def test_both_refuse_a_coverage_outside_the_unit_interval():
    for bad in (0.0, 1.0, -0.5, 2.0):
        with pytest.raises(ValueError, match="strictly inside"):
            mine.reach(bad)
        with pytest.raises(ValueError, match="strictly inside"):
            theirs.reach(bad)


def test_the_shipped_stop_reads_the_same_through_both_paths():
    """The number a stop is actually placed at, through the production
    function and through `statespace` directly."""
    from till_infinity.risk.quantiles import student_stop

    assert student_stop(0.90, 4.0) == pytest.approx(theirs.reach(0.90, 4.0), abs=1e-12)
    assert student_stop(0.90, 4.0) == pytest.approx(1.5074433191, abs=1e-9)
