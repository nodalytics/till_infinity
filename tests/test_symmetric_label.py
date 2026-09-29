"""The symmetric label: fixed barriers either side of a touch's start, no trap, its own clock.

It exists because the production outcomes read as holding 55-65% of the time on a random walk
(research/docs/holdlabel.md, research/docs/skill.md). The one property it must have is the one that
makes it worth adding: on noise it settles each way half the time.
"""

from __future__ import annotations

import random

from till_infinity.structures import codec as scodec
from till_infinity.structures import reactions
from till_infinity.structures.levels import Kalman, Level, Side, SideStats
from till_infinity.structures.vol.volatility import Volatility


def _vol(bps: float = 5.0) -> Volatility:
    vol = Volatility()
    price = 100.0
    for i in range(60):
        price *= 1 + (bps if i % 2 else -bps) / 10_000
        vol.update(price)
    return vol


def _engine():
    """Looked up at call time: other tests reload `engine`, and a class imported at the top of this
    file would then be a stale copy the codec refuses to pack."""
    from till_infinity.structures import engine

    return engine.Engine(intervals=("15m",))


def _level(price: float = 100.0) -> Level:
    return Level(feed="g", interval="15m", filter=Kalman(mean=price, variance=0.01))


def test_a_race_settles_on_the_barrier_reached_first():
    tracker, vol = reactions.Tracker(), _vol()
    race = tracker.start_race(_level(), Side.ABOVE, 100.0, vol, when=0.0)
    assert race is not None
    assert race.down < 100.0 < race.up
    tracker.advance_races("g", race.up + 1e-9, when=60.0)
    (done,) = tracker.drain_races()
    assert done.outcome == 1
    assert done.held  # arrived from above and went back up: the floor held


def test_a_ceiling_holds_when_price_goes_back_down():
    tracker, vol = reactions.Tracker(), _vol()
    race = tracker.start_race(_level(), Side.BELOW, 100.0, vol, when=0.0)
    tracker.advance_races("g", race.down - 1e-9, when=60.0)
    (done,) = tracker.drain_races()
    assert done.outcome == -1
    assert done.held


def test_a_bar_that_reaches_both_barriers_is_not_scored():
    tracker, vol = reactions.Tracker(), _vol()
    race = tracker.start_race(_level(), Side.ABOVE, 100.0, vol, when=0.0)
    # A bar that opened after the race began, so its whole range counts.
    tracker.advance_races("g", 100.0, when=1500.0, low=race.down - 1, high=race.up + 1, since=600.0)
    assert tracker.drain_races() == []
    assert tracker._races == []  # dropped, not left running


def test_a_race_opened_inside_a_bar_sees_only_that_bars_close():
    tracker, vol = reactions.Tracker(), _vol()
    race = tracker.start_race(_level(), Side.ABOVE, 100.0, vol, when=900.0)
    # The bar opened at 0 and its wick went through the lower barrier before the race existed.
    tracker.advance_races("g", 100.0, when=900.0, low=race.down - 1, high=100.0, since=0.0)
    assert tracker.drain_races() == []
    assert tracker._races == [race]


def test_a_race_that_reaches_neither_barrier_in_time_is_dropped():
    tracker, vol = reactions.Tracker(), _vol()
    race = tracker.start_race(_level(), Side.ABOVE, 100.0, vol, when=0.0)
    tracker.advance_races("g", 100.0, when=race.deadline)
    assert tracker.drain_races() == []
    assert tracker._races == []


def test_other_feeds_are_left_alone():
    tracker, vol = reactions.Tracker(), _vol()
    tracker.start_race(_level(), Side.ABOVE, 100.0, vol, when=0.0)
    tracker.advance_races("other", 1_000.0, when=60.0)
    assert len(tracker._races) == 1
    assert tracker.drain_races() == []


def test_on_a_random_walk_the_symmetric_label_reads_half():
    rng = random.Random(7)
    tracker, vol = reactions.Tracker(), _vol()
    step = vol.price_units(100.0, 1.0) * 0.4
    held = settled = 0
    for i in range(3000):
        side = Side.ABOVE if i % 2 else Side.BELOW
        race = tracker.start_race(_level(), side, 100.0, vol, when=0.0)
        price, t = 100.0, 0.0
        while race in tracker._races:
            t += 60.0
            price += rng.gauss(0.0, step)
            tracker.advance_races("g", price, when=t)
        for done in tracker.drain_races():
            settled += 1
            held += done.held
    assert settled > 2800
    assert abs(held / settled - 0.5) < 0.03


def test_side_stats_count_and_fade_the_symmetric_label():
    stats = SideStats()
    for held in (True, True, True, False):
        stats.record_symmetric(held)
    assert stats.sym_hold_rate == 0.75
    stats.decay(0.5)
    assert (stats.sym_held, stats.sym_failed) == (1.5, 0.5)
    assert stats.to_dict()["sym_hold_rate"] == 0.75
    assert SideStats().sym_hold_rate == 0.0


def test_the_engine_credits_a_settled_race_to_its_level():
    engine, vol = _engine(), _vol()
    level = _level()
    engine._levels[("g", "15m")] = [level]
    race = engine.tracker.start_race(level, Side.ABOVE, 100.0, vol, when=0.0)
    engine._advance_races("g", race.up + 1e-9, when=60.0)
    assert level.stats(Side.ABOVE).sym_held == 1.0
    assert level.stats(Side.ABOVE).sym_failed == 0.0


def test_open_races_survive_a_save():
    """Through the codec the state file is written with, not pickle."""
    engine, vol = _engine(), _vol()
    engine.tracker.start_race(_level(), Side.ABOVE, 100.0, vol, when=0.0)
    back = scodec.unpack(scodec.pack({"engine": engine}))["engine"]
    assert len(back.tracker._races) == 1
    assert back.tracker._races[0].side is Side.ABOVE
    assert back.tracker._races[0].up == engine.tracker._races[0].up
