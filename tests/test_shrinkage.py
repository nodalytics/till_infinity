"""`PRIOR_WEIGHT`, estimated rather than chosen.

The tests that matter are the two ends: a pool whose levels are really the same
must pool hard, and a pool whose levels really differ must not. In between sits
the reason the arithmetic is not just `variance(rates)` - that spread contains
each level's own sampling noise, so the naive version cannot tell "levels
differ" from "levels were counted few times".
"""

from __future__ import annotations

import random

import pytest

from till_infinity.structures import shrinkage as sh

FALLBACK = 4.0


def _draw(rates, n, seed):
    """One `(touches, ups)` per level, each drawn at its own true rate."""
    rng = random.Random(seed)
    return [(float(n), float(sum(rng.random() < p for _ in range(n)))) for p in rates]


def test_a_thin_pool_keeps_the_constant():
    """K needs enough levels, not enough touches - a handful of levels cannot
    say how much levels differ however often each was touched."""
    samples = _draw([0.5] * 4, n=500, seed=1)
    assert sh.prior_weight(samples, FALLBACK) == FALLBACK


def test_levels_that_are_really_the_same_pool_hard():
    """No spread between them, so a level's own history should count for
    little and the neighbours for much."""
    samples = _draw([0.55] * 60, n=40, seed=2)
    assert sh.prior_weight(samples, FALLBACK) > 20.0


def test_levels_that_really_differ_barely_pool():
    """Real idiosyncrasy, so a level's own record should take over fast."""
    rates = [0.15 + 0.7 * (i % 2) for i in range(60)]
    samples = _draw(rates, n=40, seed=3)
    assert sh.prior_weight(samples, FALLBACK) < 5.0


def test_the_naive_spread_cannot_tell_the_two_apart():
    """Why the noise correction is the method and not a refinement.

    Two hundred identical levels, counted eight times each. The spread of
    their observed rates is almost entirely the binomial noise it is made of,
    but nothing in that spread says so - so the naive route reads it as real
    difference between levels and asks for `K` near 7, which is "a level's own
    eight touches outweigh everything its neighbours know". Subtracting the
    sampling noise gives a `K` at the clamp instead: these levels are the same
    and should pool.

    The naive error is in the direction that costs most. It **under-pools**,
    letting a handful of noisy touches override an estimate built on hundreds.
    """
    samples = _draw([0.5] * 200, n=8, seed=4)
    rates = [ups / n for n, ups in samples]
    mean = sum(rates) / len(rates)
    naive = sum((r - mean) ** 2 for r in rates) / len(rates)
    corrected, _ = sh.tau_squared(samples, mean)

    # the raw spread is near the binomial noise of a rate counted eight times
    assert naive == pytest.approx(0.25 / 8, rel=0.3)
    assert corrected < naive / 4
    # and the two answers disagree about the only thing being asked
    assert mean * (1 - mean) / naive < 10.0
    assert sh.prior_weight(samples, FALLBACK) > 30.0


def test_the_estimate_needs_levels_and_says_so_by_being_noisy():
    """The honest caveat, pinned. `K` is a property of the population, so it
    sharpens with the number of **levels** rather than touches: the same
    identical-level pool leaves a visible residual spread at 60 levels and
    almost none at 600."""
    few, _ = sh.tau_squared(_draw([0.5] * 60, n=8, seed=4), 0.5)
    many, _ = sh.tau_squared(_draw([0.5] * 600, n=8, seed=4), 0.5)
    assert few > many
    assert many < 0.25 / 8 / 20


def test_it_is_clamped_at_both_ends():
    same = _draw([0.5] * 60, n=200, seed=5)
    assert sh.prior_weight(same, FALLBACK) <= sh.MAX_WEIGHT
    split = [(40.0, 0.0)] * 30 + [(40.0, 40.0)] * 30
    assert sh.prior_weight(split, FALLBACK) >= sh.MIN_WEIGHT


def test_a_pool_that_never_disagreed_keeps_the_constant():
    """Every level all-up is no spread to measure, not levels that are alike."""
    assert sh.prior_weight([(10.0, 10.0)] * 40, FALLBACK) == FALLBACK
    assert sh.prior_weight([(10.0, 0.0)] * 40, FALLBACK) == FALLBACK


def test_single_touch_levels_do_not_count():
    """A rate of 0 or 1 with no information about its own precision."""
    assert sh.prior_weight([(1.0, 1.0)] * 40, FALLBACK) == FALLBACK


def test_more_touches_per_level_sharpens_the_same_answer():
    """The estimate is of a property of the population, so counting each level
    more often should agree with itself rather than drift."""
    rates = [0.3 + 0.4 * (i % 3) / 2 for i in range(80)]
    few = sh.prior_weight(_draw(rates, n=20, seed=6), FALLBACK)
    many = sh.prior_weight(_draw(rates, n=200, seed=6), FALLBACK)
    assert few == pytest.approx(many, rel=0.75)
