"""A stop at a measured quantile, and whether it delivers the coverage it claims.

A stop distance is a claim about a tail - *price will not run this far against
me, with probability `tau`* - and the only honest test of one is whether that
happens. So almost every test here is a coverage test: draw excursions, set
the stop before seeing them, and count how often it was reached.

Two results from this file are worth stating up front because they decide when
to use which estimator.

**The parametric baseline was wrong by a factor and only coverage found it.**
An adverse excursion is a distance, so it is `|X|`, and the `tau` quantile of
`|X|` is the `(1 + tau) / 2` quantile of `X`. Using the two-sided quantile put
the stop at 1.08 units where it belongs at 1.51, and that stop read a realised
coverage of **0.20 against a 0.100 target** on `|t(4)|` excursions - twice
the intended stop-out rate.

**The t is as good as the empirical estimator where the scale is right, and
only loses where it is not.** On excursions drawn from the distribution it is
built for, the two tie to a thousandth. On a side whose excursions run 1.3x
deeper, the fixed t reads 0.179 against its 0.100 target while the empirical
reads 0.106. That is the whole case for the extra state, and it is narrow.
"""

from __future__ import annotations

import math
import random

import pytest

from till_infinity.risk.quantiles import (
    DOF,
    TAU,
    Coverage,
    Quantile,
    affordable,
    student_stop,
)

#: Unit-variance scaling for a t: its variance is `dof / (dof - 2)`.
SCALE = math.sqrt(DOF / (DOF - 2.0))


def excursions(n: int, seed: int = 4, deeper: float = 1.0) -> list[float]:
    """`n` draws of `|t(DOF)|` at unit variance, optionally scaled deeper.

    The distribution the parametric baseline is built for, so a test of
    calibration against it is a fair one rather than a straw man.
    """
    from scipy import stats

    rng = random.Random(seed)
    return [
        abs(float(stats.t.rvs(DOF, random_state=rng.randrange(10**9)))) / SCALE * deeper
        for _ in range(n)
    ]


def run(draws: list[float], side: int = 1, **kwargs) -> Quantile:
    found = Quantile(**kwargs)
    for value in draws:
        found.observe(side, value)
    return found


# ------------------------------------------------------- the one-sided baseline


def test_the_baseline_is_the_quantile_of_the_absolute_value():
    """**The bug this test exists for.** An excursion is a distance, so the
    90th percentile of `|X|` is the 95th of `X`. The two-sided quantile is
    what a reader expects `ppf(tau)` to be, which is why it was wrong."""
    from scipy import stats

    assert student_stop(0.90, DOF) == pytest.approx(float(stats.t.ppf(0.95, DOF)) / SCALE)
    assert student_stop(0.90, DOF) > float(stats.t.ppf(0.90, DOF)) / SCALE


def test_the_two_sided_stop_would_be_far_too_tight():
    """Pinning the measured consequence rather than only the arithmetic: the
    wrong quantile read a realised coverage of 0.335 against 0.100."""
    from scipy import stats

    wrong = float(stats.t.ppf(0.90, DOF)) / SCALE
    draws = excursions(2_000)
    hit = sum(1 for value in draws if value >= wrong) / len(draws)

    assert hit == pytest.approx(0.20, abs=0.03), f"reached {hit:.3f} of the time"
    assert hit >= 2.0 * (1.0 - TAU), "twice the intended stop-out rate, or worse"


@pytest.mark.parametrize("dof", [3.0, 4.0, 5.0])
def test_the_baseline_moves_with_the_measured_dof_range(dof):
    """`no-gaussian-band-is-calibrated` measured a t at dof 3 to 5 fixing the
    one-bar band on 64 of 64 out-of-sample readings, so a caller may move
    within that range and should see the stop move."""
    assert student_stop(TAU, dof) > 1.0


def test_a_t_without_finite_variance_is_refused():
    """A unit-scale quantile is not defined there, and returning the unscaled
    one would put a stop in different units from every other."""
    with pytest.raises(ValueError, match="no finite variance"):
        student_stop(TAU, 2.0)


def test_a_probability_outside_the_unit_interval_is_refused():
    for bad in (0.0, 1.0, 1.5, -0.1):
        with pytest.raises(ValueError, match="not a quantile"):
            student_stop(bad, DOF)


# ----------------------------------------------------------------- coverage


def test_the_estimator_converges_on_the_coverage_it_targets():
    """The property the whole object is for. A stop at the 90th percentile
    should be reached about one time in ten."""
    found = run(excursions(4_000), gain=0.02)
    reading = found.coverage(1)

    assert reading.enough
    assert reading.rate == pytest.approx(0.10, abs=0.03)
    assert abs(reading.excess) < 0.03


def test_the_excess_is_signed_so_the_correction_is_obvious():
    """ "Miscalibrated by 0.08" does not say whether the desk is being stopped
    out more often than it planned or less, and those want opposite fixes."""
    tight = Coverage(target=0.90, hits=25, n=100)
    loose = Coverage(target=0.90, hits=2, n=100)

    assert tight.excess > 0.0, "positive means too tight"
    assert loose.excess < 0.0


def test_a_rate_off_a_handful_of_events_is_not_a_rate():
    """At one stop-out in ten, thirty trades expect three. Below that the
    coverage is reported and must not be acted on."""
    assert Coverage(target=0.90, hits=1, n=10).enough is False
    assert Coverage(target=0.90, hits=3, n=30).enough is True


def test_coverage_is_none_before_any_trade():
    found = Quantile()
    assert found.coverage(1) is None
    assert found.parametric(1) is None
    assert found.beats_parametric(1) is None


# ------------------------------------- when the extra state earns itself, and when not


def test_the_t_matches_the_empirical_where_the_scale_is_right():
    """**The honest control.** On excursions from the distribution the
    baseline is built for, the fixed t is already well calibrated - which is
    what `no-gaussian-band-is-calibrated` measured - so an adaptive estimator
    has almost nothing to win, and this test says so rather than letting a
    later reading look like a victory."""
    found = run(excursions(4_000), gain=0.02)
    mine, theirs = found.coverage(1), found.parametric(1)

    assert abs(mine.excess) < 0.03
    assert abs(theirs.excess) < 0.03
    assert abs(abs(mine.excess) - abs(theirs.excess)) < 0.02, "a dead heat, not a win"


def test_the_empirical_wins_where_the_scale_differs():
    """Which is the per-side case, and the only case for the extra state.
    `fear-greed.md` measured down moves faster and deeper, stable across 6 of
    6 eras - a property of the return distribution, which a fixed baseline
    cannot track and a stop can use."""
    deep = run(excursions(4_000, deeper=1.3), gain=0.02)
    mine, theirs = deep.coverage(1), deep.parametric(1)

    assert theirs.rate > 0.15, "the fixed t is reached far more often than intended"
    assert abs(mine.excess) < abs(theirs.excess)
    assert deep.beats_parametric(1) is True


def test_the_two_sides_are_calibrated_apart():
    """A single stop for both would be too wide for one and too tight for the
    other, which is the shape of the measured asymmetry."""
    found = Quantile(gain=0.02)
    for value in excursions(3_000, seed=5):
        found.observe(1, value)
    for value in excursions(3_000, seed=6, deeper=1.3):
        found.observe(-1, value)

    assert found.stop(-1) > found.stop(1)
    assert found.stop(-1) / found.stop(1) == pytest.approx(1.3, abs=0.35)


# ----------------------------------------------------------------- the plumbing


def test_the_stop_starts_at_the_baseline_rather_than_at_zero():
    """An empirical estimator started from zero would place its first stops at
    the entry. The baseline is measured and well calibrated, so it is the
    honest starting point."""
    assert Quantile().stop(1) == pytest.approx(student_stop())


def test_the_excursion_is_scored_before_the_estimate_moves():
    """Which is what makes the coverage one-step-ahead: the stop was fixed
    when the trade opened, so it must be judged against where it was."""
    found = Quantile(gain=0.5)
    start = found.stop(1)
    found.observe(1, start + 1.0)

    assert found.coverage(1).hits == 1, "the excursion passed the stop as it stood"
    assert found.stop(1) > start, "and the estimate then moved up"


def test_a_negative_excursion_is_refused_rather_than_clamped():
    """Zero is a real outcome - price never moved against the trade - and a
    negative one means the sign came from the wrong side, which should
    surface rather than be absorbed."""
    found = Quantile()
    found.observe(1, 0.0)
    with pytest.raises(ValueError, match="negative"):
        found.observe(1, -0.5)


def test_an_unusable_gain_is_refused():
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="not a step"):
            Quantile(gain=bad)


def test_the_stop_cannot_go_negative():
    """A long run of small excursions walks the estimate down, and a stop at
    or through the entry is not a stop."""
    found = run([0.0] * 500, gain=0.5)
    assert found.stop(1) >= 0.0


# ------------------------------------------------------------- what it costs


def test_a_stop_too_tight_to_carry_its_spread_is_named():
    """`stop-anchor.md` measured a level-anchored stop at 0.169 to 0.198 of
    risk against this desk's 0.16 limit - outside the envelope on 3 of 6 feeds
    before any edge was tested. A quantile stop can land there too."""
    found = affordable(0.30, 0.06)
    assert "20% of its risk" in found
    assert "limit is 16%" in found


def test_a_stop_with_room_for_its_spread_says_nothing():
    assert affordable(3.00, 0.06) == ""


def test_an_unmeasurable_cost_is_not_a_refusal():
    """A missing spread and a zero stop have their own gates upstream, and a
    trade attributed to the wrong gate is a per-gate count that cannot be
    read."""
    assert affordable(0.0, 0.06) == ""
    assert affordable(0.30, 0.0) == ""
    assert affordable(0.30, 0.06, limit=0.0) == ""
