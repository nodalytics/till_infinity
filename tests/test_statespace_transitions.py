"""Transition tracking, and the two controls `docs/todo.md` demanded for it.

The todo named both cautions before any of this was written, and both are
assertions here rather than comments.

**The null is a matrix fitted to a walk through the same inference.** A matrix
estimated on *inferred* states inherits the inference's errors, those errors
are correlated in time, and so the diagonal is inflated by the smoother rather
than by persistence. `against` therefore refuses an empty null set, and the
measured consequence is in the test below: on eurusd 1h with the `Pips`
structure alphabet the diagonal reads 0.2068 against the walk's 0.2163 - a
**negative** inflation of -0.0096 at percentile 0.367 - where against a uniform
0.25 it would have read as a finding.

**"Predict the next transition" is strategy rotation in a new costume**, and
every pause rule this desk tried matched random pausing at the same duty cycle.
So `forecast_skill` is scored against `duty_cycle_matched` and against nothing
else, and the tests pin that the control keeps the marginal and the switch
count - which is what makes it the right control rather than a coin.
"""

from __future__ import annotations

import math
import random

import pytest

from till_infinity.statespace import transitions

#: One bar, in hours. The sequences here are hourly so a dwell reads in hours.
HOUR = 1.0


def steady(*runs: tuple[str, int]) -> list[tuple[str, float]]:
    """A label sequence from `(label, length)` runs, one hour per step."""
    out: list[tuple[str, float]] = []
    for label, length in runs:
        out.extend([(label, HOUR)] * length)
    return out


def cycling(order: tuple[str, ...], dwell: int, cycles: int) -> list[tuple[str, float]]:
    """A fixed cycle: `a` then `b` then `c` then `a`, each held `dwell` steps.

    A **learnable** transition structure, which is what a power test needs. The
    marginal is uniform and the switch count is fixed, so `duty_cycle_matched`
    reproduces both and can only differ in *which* state follows which - and
    that is the single property under test.
    """
    return steady(*[(order[i % len(order)], dwell) for i in range(cycles * len(order))])


def wandering(alphabet: tuple[str, ...], n: int, *, seed: int = 3) -> list[tuple[str, float]]:
    """Labels drawn independently: no transition structure to find."""
    rng = random.Random(seed)
    return [(rng.choice(alphabet), HOUR) for _ in range(n)]


class TestTheMatrix:
    def test_the_alphabet_is_declared_so_two_matrices_can_be_compared(self) -> None:
        """A matrix whose rows are whichever states happened to appear cannot
        be compared with one fitted to a null that visited a different subset,
        and comparing them is the entire purpose of the class."""
        got = transitions.fit(steady(("a", 10), ("b", 10)), ("a", "b", "c"))
        assert set(got.row("a")) == {"a", "b", "c"}
        assert got.row("c")["c"] == pytest.approx(1.0 / 3.0), "an unvisited row is the prior"

    def test_a_single_state_alphabet_is_refused(self) -> None:
        """An alphabet of one has no transitions to model, and a matrix of one
        cell would report a diagonal of 1.0 as a finding."""
        with pytest.raises(ValueError, match="no transitions"):
            transitions.Transitions(alphabet=("only",))

    def test_the_diagonal_ignores_states_the_sample_never_left(self) -> None:
        """A state with no observations has a row that is the prior - `1/k` on
        the diagonal - and averaging that in would pull a real diagonal toward
        chance by however many states went unseen, which is a property of the
        sample rather than of the persistence being measured.

        Including it would read 0.76 here, where excluding it reads 0.98. The
        residual difference between the two alphabets is the add-alpha prior
        spread over one more state, and it cannot affect a comparison, because
        the real matrix and its nulls are fitted over the same alphabet.
        """
        two = transitions.fit(steady(("a", 50), ("b", 50)), ("a", "b"))
        three = transitions.fit(steady(("a", 50), ("b", 50)), ("a", "b", "c"))
        assert three.diagonal() > 0.95, f"an unvisited state dragged it to {three.diagonal():.3f}"
        assert three.diagonal() == pytest.approx(two.diagonal(), abs=0.02)

    def test_the_trailing_run_is_dropped_as_censored_and_says_so(self) -> None:
        """The last run has not ended, so counting its observed length as a
        completed dwell biases every mean duration downward and every hazard
        upward. A dropped observation that is not reported is one a later
        reader cannot put back."""
        got = transitions.fit(steady(("a", 10), ("b", 10), ("a", 10), ("b", 3)), ("a", "b"))
        assert got.censored == ("b", 3.0)
        assert got.dwells["b"] == [10.0], "the censored run was counted as a dwell"
        assert got.expected_time("a") == pytest.approx(10.0)

    def test_a_forecast_breaks_a_tie_toward_staying(self) -> None:
        """The diagonal is the cell the inference inflates, so breaking a tie
        toward it is the conservative direction for a predictor that will be
        scored against a duty-cycle-matched control."""
        got = transitions.Transitions(alphabet=("a", "b"))
        got.observe("a", "a")
        got.observe("a", "b")
        assert got.forecast("a")[0] == "a"


class TestTheDurationHazard:
    """The todo's own conclusion: not "when does it change" but "given it has
    held this long, what is the hazard"."""

    def test_the_empirical_hazard_differs_from_the_flat_one_on_an_ageing_state(self) -> None:
        """A plain Markov chain assumes the hazard is flat in the time already
        spent. A state whose dwells are tightly clustered has a hazard near
        zero early and near one at the cluster, which a flat chain cannot
        represent at all."""
        got = transitions.Durations(state="a", hours=tuple([20.0] * 30))
        assert got.hazard(1.0) == pytest.approx(0.0), "a tight cluster ends early"
        assert got.hazard(20.0, step=1.0) == pytest.approx(1.0)
        assert got.flat_hazard(step=1.0) == pytest.approx(1.0 - math.exp(-1.0 / 20.0))

    def test_an_exponential_dwell_fits_a_shape_of_one_and_earns_no_gain(self) -> None:
        """An exponential is a Weibull at shape 1, so the nested gain has to be
        near zero where the hazard really is flat - otherwise the extra
        parameter would always look like it paid."""
        rng = random.Random(11)
        hours = tuple(rng.expovariate(1.0 / 30.0) for _ in range(400))
        got = transitions.Durations(state="a", hours=hours)
        assert got.shape() == pytest.approx(1.0, abs=0.12)
        assert got.duration_gain() < 1.92, f"a flat hazard earned {got.duration_gain():.2f} nats"

    def test_a_clustered_dwell_earns_the_parameter_it_costs(self) -> None:
        """The power half: a Weibull at shape 3 has a strongly rising hazard
        and twice the gain is a chi-square on one degree of freedom, so above
        1.92 nats is p < 0.05."""
        rng = random.Random(11)
        hours = tuple(30.0 * (-math.log(1.0 - rng.random())) ** (1.0 / 3.0) for _ in range(400))
        got = transitions.Durations(state="a", hours=hours)
        assert got.shape() > 2.0, f"the fitted shape was {got.shape():.3f}"
        assert got.duration_gain() > 1.92

    def test_a_handful_of_dwells_reports_nan_rather_than_no_dependence(self) -> None:
        """`nan` and not zero. A zero reads as "the hazard is flat", which is a
        claim; three dwells support neither claim."""
        got = transitions.Durations(state="a", hours=(10.0, 20.0, 30.0))
        assert math.isnan(got.shape())
        assert math.isnan(got.duration_gain())


class TestTheNullIsTheSameInference:
    def test_a_comparison_cannot_be_built_without_matrices_fitted_the_same_way(self) -> None:
        """`docs/todo.md`: the null has to be a transition matrix fitted to a
        *walk through the same inference*, not a uniform one. A uniform `1/k`
        cannot see the diagonal the smoother inflated, so it passes whatever
        the labeller does - and the refusal is what stops one being passed."""
        fitted = transitions.fit(steady(("a", 20), ("b", 20)), ("a", "b"))
        with pytest.raises(ValueError, match="same inference"):
            transitions.against(fitted, [], removes="nothing")

    def test_a_comparison_needs_the_property_its_nulls_remove(self) -> None:
        """A control is only ever for a named property."""
        fitted = transitions.fit(steady(("a", 20), ("b", 20)), ("a", "b"))
        other = transitions.fit(wandering(("a", "b"), 40), ("a", "b"))
        with pytest.raises(ValueError, match="name the property"):
            transitions.against(fitted, [other], removes="  ")

    def test_a_real_persistence_clears_the_same_inference_null(self) -> None:
        """The power half. Long planted runs have a diagonal far above what
        independently drawn labels produce, so the comparison has to find it -
        otherwise its null on real data says nothing."""
        alphabet = ("a", "b", "c")
        fitted = transitions.fit(cycling(alphabet, 40, 8), alphabet)
        nulls = [
            transitions.fit(wandering(alphabet, 960, seed=seed), alphabet) for seed in range(30)
        ]
        got = transitions.against(fitted, nulls, removes="the run structure")
        assert got.survives, got.line()
        assert got.inflation > 0.5, got.line()

    def test_an_unstructured_sequence_does_not_clear_it(self) -> None:
        """The size half, on the same code path."""
        alphabet = ("a", "b", "c")
        fitted = transitions.fit(wandering(alphabet, 960, seed=99), alphabet)
        nulls = [
            transitions.fit(wandering(alphabet, 960, seed=seed), alphabet) for seed in range(30)
        ]
        got = transitions.against(fitted, nulls, removes="the run structure")
        assert not got.survives, got.line()

    def test_the_duration_gain_gets_the_same_arm_as_the_diagonal(self) -> None:
        """**The hole this closed.** The first run reported the `walk` state's
        duration gain as +7.44 nats on eurusd 1h against a bar of 1.92, with no
        null beside it - and a gaussian walk through the same labeller reads
        **+13.66** at a Weibull shape of 0.319. So the decreasing hazard was
        the labeller and the censoring, and `of=` is what lets the statistic be
        scored rather than quoted."""
        alphabet = ("a", "b", "c")
        fitted = transitions.fit(cycling(alphabet, 40, 8), alphabet)
        nulls = [
            transitions.fit(wandering(alphabet, 960, seed=seed), alphabet) for seed in range(20)
        ]
        got = transitions.against(
            fitted,
            nulls,
            removes="the run structure",
            of=transitions.mean_duration_gain,
            statistic="mean duration gain (nats)",
        )
        assert "mean duration gain" in got.line()
        assert got.statistic != "diagonal"


class TestTheDutyCycleControl:
    """`strategy-rotation-is-not-timeable`: every pause rule matched random
    pausing at the same duty cycle."""

    def test_the_control_keeps_the_marginal_and_the_switch_count(self) -> None:
        """What makes it the right control rather than a coin. If it changed
        the time spent in each state, a predictor would beat it by predicting
        the marginal - which is a restatement of the data, not a forecast."""
        labels = [s for s, _ in cycling(("a", "b", "c"), 7, 20)]
        shuffled = transitions.duty_cycle_matched(labels, random.Random(5))
        assert len(shuffled) == len(labels)
        assert sorted(shuffled) == sorted(labels), "the duty cycle moved"
        switches = sum(1 for i in range(1, len(labels)) if labels[i] != labels[i - 1])
        moved = sum(1 for i in range(1, len(shuffled)) if shuffled[i] != shuffled[i - 1])
        assert moved == switches, f"{moved} switches against {switches}"

    def test_the_control_destroys_which_state_follows_which(self) -> None:
        """The one property it is for. A fixed `a -> b -> c` cycle has three
        certain transitions; the control has to break them while keeping
        everything else."""
        labels = [s for s, _ in cycling(("a", "b", "c"), 7, 30)]
        shuffled = transitions.duty_cycle_matched(labels, random.Random(5))
        assert shuffled != labels
        pairs = {
            (labels[i - 1], labels[i]) for i in range(1, len(labels)) if labels[i] != labels[i - 1]
        }
        null_pairs = {
            (shuffled[i - 1], shuffled[i])
            for i in range(1, len(shuffled))
            if shuffled[i] != shuffled[i - 1]
        }
        assert null_pairs - pairs, "the control reproduced only the real transitions"

    def test_a_learnable_order_beats_the_control_and_a_wander_does_not(self) -> None:
        """Power and size on the forecast, in one test, because the two
        readings are only meaningful beside each other: a hit rate of 0.99 on a
        sequence that is 99% one state is the stay rate and not skill, which is
        why `Skill` reports `stay_rate` alongside.

        A **one-step** cycle, so that changing is the usual thing. See the test
        below for why a persistent cycle cannot show this.
        """
        alphabet = ("a", "b", "c")
        learnable = transitions.forecast_skill(cycling(alphabet, 1, 320), alphabet, draws=40)
        assert learnable.survives, learnable
        assert learnable.excess > 0.2, learnable
        assert learnable.stay_rate == pytest.approx(0.0), "the fixture is persistent after all"

        noise = transitions.forecast_skill(wandering(alphabet, 960, seed=77), alphabet, draws=40)
        assert abs(noise.excess) < 0.05, noise

    def test_an_argmax_predictor_reads_nothing_off_a_persistent_chain(self) -> None:
        """**The limitation worth recording, because it is most of the answer
        to "predict the next transition".**

        A planted three-state cycle with a 20-step dwell has a matrix full of
        real transition information - `a` is followed by `b` and never by `c` -
        and an argmax predictor reaches none of it, because the modal next
        state is always "stay". Measured: hits 0.9520, which is exactly the
        stay rate, against a duty-cycle-matched control of the same, for an
        excess of zero.

        So a transition matrix buys a forecaster nothing unless it is asked a
        conditional question, which is the todo's own conclusion arriving from
        a second direction.
        """
        alphabet = ("a", "b", "c")
        got = transitions.forecast_skill(cycling(alphabet, 20, 16), alphabet, draws=20)
        assert got.hits == pytest.approx(got.stay_rate), (
            "the argmax predictor said something other than stay"
        )
        assert abs(got.excess) < 0.03, got
        model = transitions.fit(cycling(alphabet, 20, 16), alphabet)
        assert transitions.most_likely_next(model, "a") == "a"
        assert transitions.most_likely_change(model, "a") == "b", (
            "the row knows the order even though the argmax cannot reach it"
        )

    def test_a_short_sequence_reports_nan_rather_than_a_hit_rate(self) -> None:
        """Eight labels fit on four and predict on four. A number from that is
        a number a reader will quote."""
        got = transitions.forecast_skill(steady(("a", 3), ("b", 2)), ("a", "b"))
        assert math.isnan(got.hits)
        assert got.attempts == 0
        assert not got.survives
