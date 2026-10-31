"""The null models, the clock breakdown, and the register of closed questions.

These are the checks this desk trusts most, and that is measured: six
artefacts passed DSR, PBO and SPA, and what exposed them was rerunning on
surrogates and breaking the result down by hour.
"""

from __future__ import annotations

import random

import pytest

from till_infinity.node.breakdown import (
    by_clock,
    concentration_penalty,
    effective_observations,
    stable_across,
)
from till_infinity.node.closed import check, established, null_for, warn
from till_infinity.node.metrics import sharpe
from till_infinity.node.surrogates import (
    against_nulls,
    block_shuffle,
    distance_matched,
    hardest,
    iaaft,
    placebo_anchors,
    sign_flip,
    time_shift,
    vol_path_walk,
)

HOUR = 3600
DAY = 86_400


def noise(n: int, seed: int, edge: float = 0.0) -> list[float]:
    random.seed(seed)
    return [random.gauss(edge, 1.0) for _ in range(n)]


class TestEachSurrogateRemovesOneThing:
    def test_sign_flip_keeps_magnitudes(self):
        series = noise(200, 1)
        flipped = sign_flip(series, rng=random.Random(2))
        assert sorted(abs(x) for x in flipped) == sorted(abs(x) for x in series)

    def test_sign_flip_flips_whole_blocks(self):
        """Per-observation flipping destroys the serial dependence that makes
        the null fair - the same mistake as shuffling."""
        series = [1.0] * 10
        flipped = sign_flip(series, block=5, rng=random.Random(3))
        assert len(set(flipped[:5])) == 1
        assert len(set(flipped[5:])) == 1

    def test_the_vol_path_walk_preserves_the_path_exactly(self):
        series = noise(200, 4)
        walked = vol_path_walk(series, rng=random.Random(5))
        assert [abs(x) for x in walked] == [abs(x) for x in series]

    def test_block_shuffle_preserves_every_value(self):
        series = noise(200, 6)
        assert sorted(block_shuffle(series, rng=random.Random(7))) == sorted(series)

    def test_time_shift_rotates_rather_than_drops(self):
        assert time_shift([1.0, 2.0, 3.0], lag=1) == [2.0, 3.0, 1.0]
        assert sorted(time_shift(noise(50, 8), lag=7)) == sorted(noise(50, 8))

    def test_iaaft_keeps_the_distribution(self):
        series = noise(256, 9)
        got = iaaft(series, iterations=20, rng=random.Random(10))
        assert sorted(got) == pytest.approx(sorted(series), abs=1e-9)


class TestANullThatCannotMoveTheStatisticSaysSo:
    """The mirror of the tautology trap, and easy to walk into."""

    def test_a_shuffle_cannot_change_a_raw_sharpe(self):
        """Reordering leaves the mean and standard deviation untouched, so
        the arm returns the observed value on every draw."""
        arms = against_nulls(noise(400, 11, edge=0.1), sharpe, draws=20, seed=12)
        timing = next(a for a in arms if "block shuffle" in a.name)
        assert timing.uninformative is True
        assert timing.passes is False
        assert "uninformative" in timing.verdict()

    def test_an_uninformative_arm_never_decides(self):
        """It would otherwise always win: a null that does not move the
        statistic leaves the observed value at percentile zero."""
        arms = against_nulls(noise(400, 13, edge=0.1), sharpe, draws=20, seed=14)
        decided = hardest(arms)
        assert decided is not None
        assert decided.uninformative is False

    def test_an_order_dependent_statistic_makes_the_timing_nulls_bite(self):
        def momentum(series):
            return sharpe(
                [series[i] if series[i - 1] > 0 else -series[i] for i in range(1, len(series))]
            )

        arms = against_nulls(noise(400, 15), momentum, draws=30, seed=16)
        timing = next(a for a in arms if "block shuffle" in a.name)
        assert timing.uninformative is False


class TestADirectionalClaimCannotBeJudgedByRemovingDirection:
    def test_the_refusal_is_a_refusal(self):
        """Trading direction *is* trading geometry, so a null that removes
        direction answers a different question and reports a confident
        failure either way."""
        from till_infinity.node.surrogates import NULLS

        only_directional = {k: v for k, v in NULLS.items() if "direction" in k}
        with pytest.raises(ValueError, match="bet on direction"):
            against_nulls(noise(200, 17), sharpe, draws=5, nulls=only_directional, directional=True)

    def test_the_other_arms_survive_the_refusal(self):
        arms = against_nulls(noise(400, 18, edge=0.1), sharpe, draws=10, directional=True)
        assert all("direction" not in a.name for a in arms)
        assert arms


class TestThePlaceboKeepsTheGeometry:
    def test_it_returns_as_many_anchors_as_the_detector_found(self):
        assert len(placebo_anchors(1_000, 7, rng=random.Random(19))) == 7

    def test_distances_are_matched_not_random(self):
        """An unmatched placebo loses for a reason that has nothing to do with
        the shape: a longer horizon reaches a target more often."""
        pairs = distance_matched(1_000, [10, 50, 200], rng=random.Random(20))
        assert [end - start for start, end in pairs] == [10, 50, 200]

    def test_a_distance_longer_than_the_series_is_dropped(self):
        assert distance_matched(100, [500], rng=random.Random(21)) == []


class TestTheClockBreakdown:
    def test_a_spread_result_is_spread(self):
        stamps = [i * HOUR for i in range(240)]
        values = [1.0] * 240
        got = by_clock(stamps, values)
        assert got.positive_cells == 24
        assert got.concentration == pytest.approx(1 / 24, abs=0.01)
        assert got.spread is True

    def test_a_result_in_one_hour_is_about_that_hour(self):
        stamps = [i * HOUR for i in range(240)]
        values = [10.0 if (i % 24) == 14 else 0.0 for i in range(240)]
        got = by_clock(stamps, values)
        assert got.concentration == pytest.approx(1.0)
        assert got.spread is False
        ok, why = stable_across(got)
        assert ok is False
        assert "concentrated" in why

    def test_the_overlap_hours_are_named_when_a_result_sits_there(self):
        """FX volatility at 14 UTC runs about three times its quiet level, so
        a result sitting there may be reading the clock."""
        stamps = [i * HOUR for i in range(240)]
        values = [10.0 if (i % 24) == 14 else 0.1 for i in range(240)]
        text = " ".join(by_clock(stamps, values).lines())
        assert "overlap" in text

    def test_concentration_shrinks_the_effective_sample(self):
        """One hour carrying everything means that hour's count is the real
        sample - the same error as counting one event as many, wearing a
        clock."""
        stamps = [i * HOUR for i in range(240)]
        concentrated = by_clock(stamps, [10.0 if (i % 24) == 14 else 0.0 for i in range(240)])
        spread = by_clock(stamps, [1.0] * 240)
        assert concentration_penalty(concentrated) < concentration_penalty(spread)
        assert effective_observations(concentrated) < effective_observations(spread)

    def test_too_few_cells_cannot_tell_spread_from_concentration(self):
        stamps = [i * DAY for i in range(6)]  # all the same hour
        ok, why = stable_across(by_clock(stamps, [1.0] * 6))
        assert ok is False
        assert "too few" in why

    def test_weekday_is_available_for_the_calendar_control(self):
        """A z of -4.99 survived a placebo and a shuffle, and Wednesday turned
        out to be the second weakest of five weekdays."""
        stamps = [i * DAY for i in range(70)]
        got = by_clock(stamps, [1.0] * 70, field="weekday")
        assert len(got.populated) == 7

    def test_a_mismatched_length_is_refused(self):
        with pytest.raises(ValueError, match="stamps and"):
            by_clock([1.0, 2.0], [1.0])


class TestTheClosedRegister:
    def test_a_closed_shape_claim_is_flagged(self):
        assert warn("an engulfing candle shape predicts continuation")

    def test_shape_transitions_are_their_own_entry(self):
        entry = check("transitions between candle shapes predict the next move")
        assert entry is not None
        assert "transitions" in entry.claim

    def test_an_established_finding_is_not_flagged_as_closed(self):
        """The expensive mistake. The loose matcher flagged this desk's
        strongest result because "range" appears in a closed entry."""
        assert warn("dispersion is forecastable from the bar range") == ""
        assert established("dispersion is forecastable from the bar range") is not None

    def test_an_open_question_passes_through(self):
        assert warn("the spread widens before a release") == ""

    def test_geometric_and_topological_claims_need_different_nulls(self):
        assert "distance-matched" in null_for("geometric")
        assert "same detector" in null_for("topological")
        assert null_for("geometric") != null_for("topological")

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ValueError, match="kind must be"):
            null_for("fractal")
