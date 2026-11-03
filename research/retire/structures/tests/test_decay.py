"""When a model stops working, said by the system rather than noticed by a person."""

from __future__ import annotations

import random

from till_infinity.structures.learning.decay import Decay


def _run(watcher, name, wrong_rate, n, seed=1):
    rng = random.Random(seed)
    got = None
    for _ in range(n):
        got = watcher.observe(name, rng.random() < wrong_rate)
    return got


def test_both_detectors_fire_on_a_stream_with_no_change_in_it():
    """**The headline, and the reason this decides nothing.** Run against a
    stationary error stream - where the right number of alarms is zero - EDDM
    fires roughly once every 270 to 940 observations and DDM about once per
    3,000. So "EDDM fired" means nothing on its own, and what is informative is
    the count against the stationary baseline for that model's error rate."""
    watcher = Decay()

    got = _run(watcher, "steady", 0.2, 3000)

    assert got.seen == 3000
    # Asserted as measured rather than as hoped: this is a null result about
    # the detectors, and a test that pretended otherwise would hide it.
    assert got.eddm_alarms > 0, "EDDM is quieter than measured - re-run the null"
    assert got.ddm_alarms <= 2


def test_the_false_alarm_rate_climbs_with_the_error_rate_not_the_drift():
    """Which is why `error_rate` is carried beside the counts. An alarm at 50%
    wrong has to clear a bar several times higher than one at 5%."""
    quiet = _run(Decay(), "low", 0.05, 3000, seed=4)
    noisy = _run(Decay(), "high", 0.50, 3000, seed=4)

    assert noisy.eddm_alarms > quiet.eddm_alarms


def test_a_model_that_breaks_is_caught():
    """DDM models errors as a binomial and is sharp on a step - a model that
    breaks rather than one that slides."""
    watcher = Decay()
    _run(watcher, "broken", 0.15, 1500, seed=2)
    got = _run(watcher, "broken", 0.75, 1500, seed=3)

    assert got.ddm_alarms >= 1
    assert got.error_rate > 0.4


def test_a_model_that_slides_is_caught_by_the_other_one():
    """EDDM watches the distance between errors rather than their rate, which
    is what catches a gradual slide - and gradual is what decay here looks
    like. A model whose edge erodes over a month never has a bad enough day to
    trip DDM."""
    watcher = Decay()
    rng = random.Random(7)
    got = None
    for i in range(4000):
        # error rate walking from 0.12 up to 0.55 with no step anywhere
        rate = 0.12 + 0.43 * (i / 4000)
        got = watcher.observe("sliding", rng.random() < rate)

    assert got.eddm_alarms >= 1


def test_the_reading_carries_the_rate_the_alarm_fired_against():
    """ "It fired" is not actionable on its own: a detector alarming on a model
    that is right nine times in ten is saying something different from one
    alarming at break-even."""
    watcher = Decay()
    got = _run(watcher, "m", 0.3, 800)

    assert 0.0 <= got.error_rate <= 1.0
    assert got.to_dict()["seen"] == 800.0
    assert "error_rate" in got.to_dict()


def test_several_models_are_watched_apart():
    watcher = Decay()
    _run(watcher, "a", 0.1, 500)
    _run(watcher, "b", 0.9, 500)

    assert watcher.reading("a").error_rate < watcher.reading("b").error_rate
    assert "a:" in watcher.report()
    assert "b:" in watcher.report()


def test_a_failing_detector_cannot_stop_the_model_being_watched():
    """A watcher that decides nothing must not be able to break the thing it
    watches."""
    watcher = Decay()
    watcher.observe("m", False)

    class _Broken:
        def update(self, _value):
            raise RuntimeError("no")

    watcher._ddm["m"] = _Broken()

    got = watcher.observe("m", True)  # must not raise
    assert got.seen == 2


def test_nothing_watched_yet_says_so():
    assert "no model error streams" in Decay().report()
