"""Turning a score that ranks well into a probability that means something."""

import random

import pytest

from till_infinity.structures.learning.calibration import (
    MIN_SEEN,
    Platt,
    Reliability,
)


def overconfident(n: int, factor: float = 3.0, seed: int = 7) -> Platt:
    """A ranker that orders correctly and states the odds too strongly.

    The exact shape the break model turned out to have: AUC intact, numbers
    pushed away from the base rate.
    """
    rng = random.Random(seed)
    model = Platt()
    for _ in range(n):
        true_p = rng.random() * 0.2
        raw = min(0.99, max(0.01, true_p * factor))
        model.observe(raw, rng.random() < true_p)
    return model


def test_it_passes_the_score_through_until_it_has_seen_enough():
    """Two parameters fitted on nothing are noise, and passing the input
    through unchanged is the honest default."""
    model = Platt()

    assert model.apply(0.42) == 0.42
    assert model.warm is False
    assert model.improvement is None
    assert model.reading() == {}


def test_it_pulls_an_overconfident_score_toward_the_base_rate():
    model = overconfident(4000)

    assert model.warm
    # A confident 0.6 from a model that breaks 7% of the time is not a 0.6.
    assert model.apply(0.6) < 0.6
    assert model.improvement > 0


def test_it_scores_both_streams_on_the_same_observations():
    """One number cannot say whether the correction helped, so both are kept
    and `improvement` is their difference."""
    model = overconfident(4000)

    assert model.log_loss > 0
    assert model.raw_log_loss > 0
    assert model.improvement == pytest.approx(model.raw_log_loss - model.log_loss)


def test_a_correction_that_does_not_help_reports_a_negative_improvement():
    """The number that says to remove it. A calibrator nothing can contradict
    is the shape research/inert.md catalogues."""
    rng = random.Random(3)
    model = Platt()
    # Already well calibrated: there is nothing to win and noise to lose.
    for _ in range(4000):
        true_p = rng.random()
        model.observe(true_p, rng.random() < true_p)

    assert model.warm
    assert model.improvement < 0.02  # at best it does nothing


def test_it_is_monotone_so_the_ranking_survives():
    """The whole argument for calibrating rather than retraining: the AUC is a
    ranking claim and must come out the other side untouched."""
    model = overconfident(4000)

    raws = [0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.95]
    fixed = [model.apply(r) for r in raws]

    assert fixed == sorted(fixed)
    assert all(0.0 < f < 1.0 for f in fixed)


def test_it_predicts_before_it_learns():
    """Out of sample by construction rather than by discipline, like every
    other learner here."""
    model = overconfident(int(MIN_SEEN) + 50)
    before = model.apply(0.5)

    said = model.observe(0.5, True)

    assert said == pytest.approx(before)


def test_an_extreme_score_does_not_blow_up():
    """`_logit` of 1.0 is infinite, and a learner that dies on one row takes
    the whole stream with it."""
    model = overconfident(int(MIN_SEEN) + 50)

    for raw in (0.0, 1.0, 1e-12, 1 - 1e-12):
        got = model.observe(raw, True)
        assert 0.0 <= got <= 1.0


def test_reliability_shows_where_the_model_is_wrong():
    """`Platt` says whether the correction helps; this says where the error is,
    which is what tells a reader whether to trust a 90% at all."""
    rel = Reliability()
    rng = random.Random(11)
    for _ in range(3000):
        true_p = rng.random() * 0.2
        rel.observe(min(0.99, true_p * 3), rng.random() < true_p)

    table = rel.table()
    assert table
    for centre, actual, n in table:
        assert n > 0
        # Over-confident by construction: every band claims more than it does.
        if n > 100:
            assert actual < centre


def test_reliability_reports_only_bands_it_has_seen():
    rel = Reliability()
    rel.observe(0.05, False)
    rel.observe(0.05, True)

    table = rel.table()

    assert len(table) == 1
    assert table[0][1] == pytest.approx(0.5)
    assert table[0][2] == 2
