"""The signal registry: orientation, earned weight, and the clock.

Three things here can go wrong silently, and each one would look like a working registry.

**Orientation.** Three of the seven signals are negatively signed and two of those are the
strongest. A sign error would not crash, would not look wrong in the journal, and would produce
an ensemble that is confidently backwards - which is the failure `force.md` published once and
had to retract.

**Earned weight.** The whole design claim is that weights come from the live score rather than
from the backtested claim. A signal that is at chance, or that has not been seen enough, has to
contribute *nothing* - not a little.

**The clock.** It is the one new signal and the only one whose input is free, so its curve is
pinned against the measured row rather than against itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from till_infinity.structures.context.registry import (
    MIN_EDGE,
    MIN_SEEN,
    Registry,
    Score,
    clock_odds,
)


@dataclass
class Fake:
    """Whatever carries features - the registry reads by name and cares about nothing else."""

    experience: float = 0.0
    strength: float = 0.0
    depth_vol: float = 0.0
    slowing: float = 0.0
    approach_vol: float = 0.0
    slope: float = 0.0


def test_the_clock_tracks_the_measured_one_minute_row():
    """14.4% at open, 22.4% at two bars, 54.7% at five, 77.8% at ten - break-trade.md."""
    # Pinned against the measurement, not against round numbers: the curve's job is to
    # reproduce the row, and five bars measured 54.7% rather than 50%.
    for bars, measured in ((0, 0.144), (2, 0.224), (5, 0.547), (10, 0.778)):
        assert abs(clock_odds(bars) - measured) < 0.06, f"{bars} bars drifted from the row"
    # And the rule the row is quoted for: past five of its own bars, the break is the
    # majority outcome and the level's own directional call is the minority one.
    assert clock_odds(5) > 0.5
    assert clock_odds(4) < clock_odds(5) < clock_odds(6)


def test_the_clock_is_monotone_and_stays_a_probability():
    seen = [clock_odds(b) for b in (0, 0.1, 0.5, 1, 2, 5, 10, 50, 500, 10_000)]
    assert seen == sorted(seen)
    assert all(0.0 <= p <= 1.0 for p in seen)


def test_negatively_signed_signals_are_flipped_once_in_the_registry():
    """Larger must always mean likelier break, or the ensemble sums evidence backwards."""
    got = Registry.readings(Fake(experience=2.0, strength=0.9, depth_vol=1.5, slowing=3.0))
    # A deep touch, a strong level and an experienced one all mean the level is likelier to
    # HOLD, so each has to arrive negative.
    assert got["experience"] < 0
    assert got["strength"] < 0
    assert got["depth_vol"] < 0
    # Arrival speed and deceleration run the other way.
    assert got["slowing"] > 0


def test_slope_is_read_as_a_magnitude():
    """Its sign says which way price is going, which is a different question."""
    up = Registry.readings(Fake(slope=+2.0))["slope"]
    down = Registry.readings(Fake(slope=-2.0))["slope"]
    assert up == down > 0


def test_the_clock_is_absent_rather_than_guessed_when_the_age_is_unknown():
    assert "clock" not in Registry.readings(Fake())
    assert "clock" in Registry.readings(Fake(), age_bars=3.0)


def test_a_signal_at_chance_earns_no_weight_however_often_it_is_seen():
    """The point of scoring live: a signal that does not separate does not get a vote."""
    score = Score()
    for i in range(int(MIN_SEEN) * 3):
        # Identical distributions on both classes - the definition of no separation.
        score.observe(math.sin(i), broke=i % 2 == 0)
    assert score.seen > MIN_SEEN
    assert abs(score.live - 0.5) < MIN_EDGE
    assert score.weight == 0.0


def test_a_separating_signal_earns_weight_once_it_has_been_seen_enough():
    score = Score()
    for i in range(int(MIN_SEEN) * 2):
        broke = i % 2 == 0
        # Cleanly separated classes, so the live score must find it.
        score.observe(1.0 + 0.1 * math.sin(i) if broke else -1.0 + 0.1 * math.sin(i), broke)
    assert score.live > 0.9
    assert score.weight > 0.0


def test_weight_is_withheld_until_min_seen_however_strong_the_separation():
    """A large effect on forty observations is what this folder keeps having to retract."""
    score = Score()
    for i in range(40):
        score.observe(5.0 if i % 2 == 0 else -5.0, broke=i % 2 == 0)
    assert score.live > 0.9, "the separation is obvious"
    assert score.weight == 0.0, "and it still gets no vote"


def test_the_ensemble_says_nothing_until_a_signal_has_earned_a_vote():
    """Correct after a fresh deploy, and not a fault - the same shape as armed-after-backfill."""
    book = Registry()
    assert book.ensemble(Fake(approach_vol=3.0)) is None


def test_the_ensemble_follows_a_signal_that_has_earned_its_vote():
    book = Registry()
    for i in range(int(MIN_SEEN) * 2):
        broke = i % 2 == 0
        book.observe(Fake(approach_vol=1.0 if broke else -1.0), broke=broke)
    fast = book.ensemble(Fake(approach_vol=1.0))
    slow = book.ensemble(Fake(approach_vol=-1.0))
    assert fast is not None
    assert slow is not None
    assert fast > slow
    assert 0.0 <= slow <= 1.0
    assert 0.0 <= fast <= 1.0


def test_the_reading_publishes_the_live_score_beside_the_backtested_claim():
    """The gap between them is the whole reason this class exists."""
    book = Registry()
    for i in range(int(MIN_SEEN) * 2):
        broke = i % 2 == 0
        book.observe(Fake(approach_vol=1.0 if broke else -1.0), broke=broke)
    got = book.reading()
    assert got["approach_vol_live"] > 0.5
    # The gap, not the claim: a constant on every row is what test_published.py refuses.
    assert got["approach_vol_drift"] == round(got["approach_vol_live"] - 0.525, 4)
    assert got["registry_seen"] == float(int(MIN_SEEN) * 2)


def test_an_unseen_signal_is_left_out_of_the_reading_rather_than_reported_as_a_coin():
    book = Registry()
    book.observe(Fake(approach_vol=1.0), broke=True)
    reading = book.reading()
    assert "approach_vol_live" not in reading
    assert "approach_vol_drift" not in reading


def test_the_registry_holds_nothing_with_a_length_that_could_come_back_uncapped():
    """A capped deque restored from an older save comes back unbounded - it happened here."""
    book = Registry()
    book.observe(Fake(approach_vol=1.0), broke=True)
    for score in book.scores.values():
        for slot in score.__slots__:
            assert isinstance(getattr(score, slot), float)
