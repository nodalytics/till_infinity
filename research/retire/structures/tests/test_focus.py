"""FOCuS, checked against the thing it is a fast version of."""

from __future__ import annotations

import random

import pytest

from till_infinity.structures.learning.focus import Focus


def brute(values, up=True):
    """The statistic by definition: every changepoint, no pruning.

    O(n^2) and obviously correct, which is the point - it is the reference the
    pruned version has to equal, not a second implementation of the clever bit.
    """
    out = []
    sums = [0.0]
    for v in values:
        sums.append(sums[-1] + v)
    for n in range(1, len(sums)):
        best = 0.0
        for tau in range(n):
            gap = n - tau
            diff = sums[n] - sums[tau] if up else sums[tau] - sums[n]
            if diff > 0:
                best = max(best, diff * diff / (2.0 * gap))
        out.append(best)
    return out


def test_the_pruned_statistic_equals_the_exact_one_on_every_step():
    """The claim is exactness, not speed. If the hull drops a candidate that
    could still have won, this is where it shows."""
    rng = random.Random(11)
    values = [rng.gauss(0, 1) for _ in range(120)]
    values += [rng.gauss(1.5, 1) for _ in range(80)]

    got = Focus(threshold=1e18)
    mine = []
    for v in values:
        got.update(v)
        mine.append(got.statistic)

    for step, (a, b) in enumerate(zip(mine, brute(values), strict=True)):
        assert a == pytest.approx(b, rel=1e-9, abs=1e-9), f"diverged at step {step}"


def test_it_matches_the_exact_one_looking_the_other_way():
    rng = random.Random(3)
    values = [rng.gauss(0, 1) for _ in range(80)] + [rng.gauss(-2.0, 1) for _ in range(60)]

    got = Focus(threshold=1e18, up=False)
    mine = []
    for v in values:
        got.update(v)
        mine.append(got.statistic)

    assert mine == pytest.approx(brute(values, up=False), rel=1e-9, abs=1e-9)


def test_it_prunes_rather_than_keeping_everything():
    """Without pruning this is the naive O(n) scan it exists to replace."""
    rng = random.Random(5)
    got = Focus(threshold=1e18)
    for _ in range(2000):
        got.update(rng.gauss(0, 1))

    assert got.seen == 2000
    assert len(got.hull) < 200, "the hull is not pruning"


def test_a_stream_with_no_change_stays_under_the_threshold():
    """The null first. A detector that fires on noise costs real evidence -
    the lesson decay.py had to record about EDDM."""
    rng = random.Random(9)
    fired = 0
    for seed in range(5):
        got = Focus()
        rng = random.Random(seed)
        for _ in range(3000):
            if got.update(rng.gauss(0, 1)):
                fired += 1
                got.reset()

    assert fired <= 5, f"fired {fired} times on five stationary streams"


def test_a_real_change_is_found_and_located():
    rng = random.Random(2)
    got = Focus()
    for _ in range(300):
        got.update(rng.gauss(0, 1))
    fired_at = None
    for i in range(300):
        if got.update(rng.gauss(1.2, 1)):
            fired_at = i
            break

    assert fired_at is not None, "a 1.2 sigma shift went unnoticed"
    assert fired_at < 100, "took too long to notice"
    # And it says where, which a threshold-crossing CUSUM cannot.
    assert 250 <= got.at <= 400


def test_the_scale_can_move_with_the_market():
    """A detector calibrated to last week's volatility is measuring the wrong
    thing this week - the argument Cusum.push already makes."""
    got = Focus(threshold=1e18, scale=1.0)
    got.update(10.0)
    loud = got.statistic

    other = Focus(threshold=1e18, scale=1.0)
    other.update(10.0, scale=10.0)

    assert other.statistic < loud


def test_a_reset_forgets_the_candidates_but_not_the_stream():
    got = Focus()
    for _ in range(50):
        got.update(1.0)
    got.reset()

    assert got.statistic == 0.0
    assert len(got.hull) == 1
    assert got.seen == 50


def test_it_refuses_a_scale_of_zero_rather_than_dividing_by_it():
    got = Focus(scale=0.0)

    assert got.update(1.0) is False
    assert got.seen == 0
