"""The zone's width, calibrated rather than assumed.

The band used to be two sigmas, which is 95.4% of a Gaussian and a claim about
touches nobody had checked. These tests are mostly about the cases where that
assumption is wrong, because those are the ones the old width got silently
wrong and this is supposed to get right.
"""

from __future__ import annotations

import random

import pytest

from till_infinity.structures import conformal as cf
from till_infinity.structures.levels import ZONE_SIGMA, Kalman, Level, Side
from till_infinity.structures.vol.volatility import Volatility


def _vol(bps: float = 5.0) -> Volatility:
    vol = Volatility()
    price = 4400.0
    for _ in range(60):
        price *= 1 + bps / 10_000
        vol.update(price)
    return vol


def _feed(pool: cf.Pool, draw, n: int) -> None:
    """Signed scores - the sign is the thing the two tails keep."""
    for _ in range(n):
        pool.observe(draw(), ZONE_SIGMA)


def test_the_run_in_quotes_what_the_band_always_was():
    """Below SETTLE it must behave exactly like the constant it replaces."""
    pool = cf.Pool()
    random.seed(3)
    _feed(pool, lambda: random.gauss(0, 1), cf.SETTLE - 1)
    assert max(pool.reach(ZONE_SIGMA)) == ZONE_SIGMA


def test_a_gaussian_pool_lands_near_two_sigmas():
    """Where the old assumption was right, the calibrated width agrees with
    it - which is the only way to tell the two apart elsewhere."""
    pool = cf.Pool()
    random.seed(5)
    _feed(pool, lambda: random.gauss(0, 1), 400)
    assert max(pool.reach(ZONE_SIGMA)) == pytest.approx(1.96, abs=0.35)


def test_a_heavy_tailed_pool_widens_past_two():
    """The case the Gaussian band gets wrong. Touches with fat tails need a
    wider band to hold 95%, and nothing in a posterior variance knows that."""
    pool = cf.Pool()
    random.seed(5)
    # a normal mixture: mostly tight, occasionally four times as dispersed
    _feed(pool, lambda: random.gauss(0, 4 if random.random() < 0.15 else 0.7), 400)
    assert max(pool.reach(ZONE_SIGMA)) > 2.0


def test_a_tight_pool_narrows_below_two():
    """And the other direction: a band wider than it needs to be is a level
    that reads every passing wick as a touch."""
    pool = cf.Pool()
    random.seed(5)
    _feed(pool, lambda: random.gauss(0, 0.35), 400)
    assert max(pool.reach(ZONE_SIGMA)) < 2.0


def test_the_width_holds_its_target_coverage():
    """The claim the old band made without measuring it."""
    pool = cf.Pool()
    random.seed(11)
    _feed(pool, lambda: random.gauss(0, 4 if random.random() < 0.15 else 0.7), 600)
    assert pool.coverage() == pytest.approx(cf.COVERAGE, abs=0.04)


def test_the_width_is_clamped_at_both_ends():
    """A pool fed something pathological must not quote a band so tight that
    nothing touches a level, nor so wide that everything does."""
    tight, wide = cf.Pool(), cf.Pool()
    random.seed(5)
    _feed(tight, lambda: 0.0, 400)
    _feed(wide, lambda: random.gauss(0, 500), 400)
    assert min(tight.reach(ZONE_SIGMA)) >= cf.MIN_SIGMAS
    assert max(wide.reach(ZONE_SIGMA)) <= cf.MAX_SIGMAS


def test_the_scores_window_is_bounded():
    """A service that runs for months must not grow a list forever."""
    pool = cf.Pool()
    random.seed(5)
    _feed(pool, lambda: random.gauss(0, 1), cf.WINDOW * 3)
    assert len(pool.scores) == cf.WINDOW


def test_the_quantile_uses_the_finite_sample_correction():
    scores = [float(i) for i in range(10)]
    # ceil((n + 1) * level) - 1, not a plain percentile
    assert cf.quantile(scores, 0.9) == scores[9]
    assert cf.quantile([], 0.9) == 0.0


def test_each_side_calibrates_separately():
    """A price met from below and the same price met from above are two
    different objects - there is no reason their dispersion should match."""
    zones = cf.Zones()
    random.seed(5)
    for _ in range(400):
        zones.observe("x", "15m", str(Side.ABOVE), random.gauss(0, 0.35), ZONE_SIGMA)
        zones.observe("x", "15m", str(Side.BELOW), random.gauss(0, 3.0), ZONE_SIGMA)
    below = zones.sigmas("x", "15m", str(Side.ABOVE), ZONE_SIGMA)
    above = zones.sigmas("x", "15m", str(Side.BELOW), ZONE_SIGMA)
    assert below != above


def test_an_untouched_pool_quotes_the_default():
    assert cf.Zones().sigmas("x", "15m", "above", ZONE_SIGMA) == (ZONE_SIGMA, ZONE_SIGMA)


def test_the_score_is_taken_before_the_filter_moves():
    """The whole validity argument: a score measured after the fold is scored
    against a centre that already moved toward it."""
    zones = cf.Zones()
    vol = _vol()
    when = 1_000_000.0
    level = Level("x", "15m", filter=Kalman(mean=100.0, variance=0.25, updated=when))
    before = level.filter.at(when)
    level.observe_touch(101.0, vol, when, side=Side.ABOVE, calibrator=zones)
    pool = zones.pool("x", "15m", str(Side.ABOVE))
    assert pool.seen == 1
    # scored against where the level was, not where the touch dragged it
    assert level.filter.mean != before
    assert pool.scores[0] == pytest.approx((101.0 - before) / 0.5, rel=1e-6)


def test_a_touch_without_a_calibrator_changes_nothing():
    """Ten callers have no calibrator to hand and must keep working."""
    vol = _vol()
    when = 1_000_000.0
    level = Level("x", "15m", filter=Kalman(mean=100.0, variance=0.25, updated=when))
    level.observe_touch(101.0, vol, when)
    assert level.zone_sigmas_down == ZONE_SIGMA
    assert level.zone_sigmas_up == ZONE_SIGMA


# ------------------------------------------------------- the two tails


def test_a_skewed_pool_reaches_further_on_the_skewed_side():
    """The whole reason the sign is kept.

    Price that overshoots a floor by a long way and undershoots it by a
    little is not described by one number, and the version of this that took
    `abs` was averaging the two into a band wrong on both sides.
    """
    pool = cf.Pool()
    random.seed(13)
    # long tail below the centre, short tail above
    _feed(
        pool,
        lambda: -abs(random.gauss(0, 3.0)) if random.random() < 0.5 else abs(random.gauss(0, 0.5)),
        600,
    )
    down, up = pool.reach(ZONE_SIGMA)
    assert down > up * 2
    assert pool.skew() < 0


def test_a_symmetric_pool_has_no_skew():
    """And where the two tails agree, the `abs` version was losing nothing -
    which is a claim worth being able to check rather than assume."""
    pool = cf.Pool()
    random.seed(14)
    _feed(pool, lambda: random.gauss(0, 1.0), 600)
    down, up = pool.reach(ZONE_SIGMA)
    assert down == pytest.approx(up, abs=0.35)
    assert pool.skew() == pytest.approx(0.0, abs=0.35)


def test_the_band_holds_its_coverage_on_a_skewed_pool():
    """The property a symmetric band cannot have here: one number must either
    over-cover the short side or under-cover the long one."""
    pool = cf.Pool()
    random.seed(15)
    _feed(
        pool,
        lambda: -abs(random.gauss(0, 3.0)) if random.random() < 0.5 else abs(random.gauss(0, 0.5)),
        800,
    )
    assert pool.coverage() == pytest.approx(cf.COVERAGE, abs=0.04)


def test_each_tail_misses_its_own_share():
    """`COVERAGE` is a statement about the band, so each end gets half the
    miss - otherwise two tails at the full rate would leave twice as much
    outside as asked for."""
    pool = cf.Pool()
    random.seed(16)
    _feed(pool, lambda: random.gauss(0, 1.0), 800)
    down, up = pool.reach(ZONE_SIGMA)
    over = sum(1 for s in pool.scores if s > up) / len(pool.scores)
    under = sum(1 for s in pool.scores if s < -down) / len(pool.scores)
    assert over == pytest.approx(cf.TAIL_MISS, abs=0.03)
    assert under == pytest.approx(cf.TAIL_MISS, abs=0.03)


def test_a_pool_entirely_on_one_side_does_not_invert_its_band():
    """A tail whose quantile falls on the wrong side of the centre is asking
    for a negative reach, which is not a band."""
    pool = cf.Pool()
    random.seed(17)
    _feed(pool, lambda: abs(random.gauss(0, 1.0)) + 0.5, 600)
    down, up = pool.reach(ZONE_SIGMA)
    assert down >= cf.MIN_SIGMAS
    assert up >= cf.MIN_SIGMAS


def test_the_run_in_quotes_the_old_constant_on_both_sides():
    pool = cf.Pool()
    random.seed(18)
    _feed(pool, lambda: random.gauss(0, 1.0), cf.SETTLE - 1)
    assert pool.reach(ZONE_SIGMA) == (ZONE_SIGMA, ZONE_SIGMA)
