"""The episode database: every touch's whole path, both ways, in R.

An episode must classify paths correctly, refuse to guess the order inside one bar, survive a
save, and - the property that makes it a fair record - read each way half the time on noise.
"""

from __future__ import annotations

import random

from till_infinity.structures import codec as scodec
from till_infinity.structures import reactions
from till_infinity.structures.levels import Kalman, Level, Side
from till_infinity.structures.vol.volatility import Volatility

BAR = 900.0


def _vol(bps: float = 5.0) -> Volatility:
    vol = Volatility()
    price = 100.0
    for i in range(60):
        price *= 1 + (bps if i % 2 else -bps) / 10_000
        vol.update(price)
    return vol


def _level(price: float = 100.0) -> Level:
    return Level(feed="g", interval="15m", filter=Kalman(mean=price, variance=0.01))


def _open(side: Side = Side.ABOVE):
    tracker = reactions.Tracker()
    episode = tracker.start_episode(_level(), side, 100.0, _vol(), when=0.0)
    assert episode is not None
    return tracker, episode


def _walk(tracker, episode, closes):
    """One close a bar, no wicks, then run the clock out."""
    for k, price in enumerate(closes, start=1):
        tracker.advance_episodes("g", price, when=k * BAR)
    tracker.advance_episodes("g", closes[-1], when=episode.deadline)
    (done,) = tracker.drain_episodes()
    return done


def test_a_run_to_two_r_is_clean():
    tracker, ep = _open()
    r = ep.unit
    done = _walk(tracker, ep, [100 + 0.5 * r, 100 + 1.1 * r, 100 + 2.2 * r, 100 + 3.1 * r])
    found = done.to_dict()
    assert found["kind"] == "clean"
    assert found["first"] == 1
    assert found["held_first"] is True  # a floor that went up
    assert found["bars_up_1r"] == 2.0
    assert found["bars_up_2r"] == 3.0
    assert found["bars_up_3r"] == 4.0
    assert found["bars_down_1r"] is None
    assert found["mfe_up_r"] >= 3.0


def test_one_r_then_the_other_side_is_a_whipsaw():
    tracker, ep = _open()
    r = ep.unit
    done = _walk(tracker, ep, [100 + 1.2 * r, 100, 100 - 1.3 * r])
    found = done.to_dict()
    assert found["kind"] == "whipsaw"
    assert found["bars_opposite"] == 3.0
    assert found["mae_at_down1_r"] >= 1.2  # the short's 1R came after a 1.2R adverse run


def test_nothing_reaching_one_r_is_a_stall():
    tracker, ep = _open()
    r = ep.unit
    done = _walk(tracker, ep, [100 + 0.4 * r, 100 - 0.6 * r, 100 + 0.2 * r])
    assert done.kind == "stall"
    assert done.to_dict()["first"] == 0


def test_one_r_and_no_more_is_partial():
    tracker, ep = _open(Side.BELOW)
    r = ep.unit
    done = _walk(tracker, ep, [100 + 1.2 * r, 100 + 0.8 * r])
    found = done.to_dict()
    assert found["kind"] == "partial"
    assert found["held_first"] is False  # a ceiling that went up


def test_both_sides_inside_one_bar_are_not_guessed():
    tracker, ep = _open()
    r = ep.unit
    tracker.advance_episodes("g", 100.0, when=BAR, low=100 - 1.5 * r, high=100 + 1.5 * r, since=1.0)
    tracker.advance_episodes("g", 100.0, when=ep.deadline)
    (done,) = tracker.drain_episodes()
    assert done.kind == "ambiguous"
    assert done.to_dict()["first"] == 0


def test_the_bar_an_episode_opened_in_counts_only_its_close():
    """The wick happened before the episode existed, as for the races."""
    tracker, ep = _open()
    r = ep.unit
    tracker.advance_episodes("g", 100.0, when=BAR, low=100 - 3 * r, high=100 + 3 * r, since=0.0)
    assert ep.mfe_up == 0.0
    assert ep.mfe_down == 0.0


def test_the_fade_is_one_r_given_back_from_the_peak():
    tracker, ep = _open()
    r = ep.unit
    done = _walk(tracker, ep, [100 + 1.5 * r, 100 + 2.5 * r, 100 + 1.4 * r])
    found = done.to_dict()
    assert found["bars_peak"] == 2.0
    assert found["bars_fade"] == 3.0


def test_an_episode_finishes_only_at_its_horizon():
    tracker, ep = _open()
    tracker.advance_episodes("g", 100 + 5 * ep.unit, when=BAR)
    assert tracker.drain_episodes() == []
    assert ep.deadline == reactions.EPISODE_BARS * BAR


def test_open_episodes_survive_a_save():
    from till_infinity.structures import engine

    eng = engine.Engine(intervals=("15m",))
    ep = eng.tracker.start_episode(_level(), Side.ABOVE, 100.0, _vol(), when=0.0)
    eng.tracker.advance_episodes("g", 100 + 1.2 * ep.unit, when=BAR)
    back = scodec.unpack(scodec.pack({"engine": eng}))["engine"]
    (got,) = back.tracker._episodes
    assert got.side is Side.ABOVE
    assert got.first == 1
    eng.tracker.advance_episodes("g", 100 + 2.2 * ep.unit, when=2 * BAR)
    back.tracker.advance_episodes("g", 100 + 2.2 * ep.unit, when=2 * BAR)
    assert back.tracker._episodes[0].to_dict() == eng.tracker._episodes[0].to_dict()


def test_on_noise_the_first_one_r_goes_each_way_half_the_time():
    rng = random.Random(3)
    ups = n = 0
    for _ in range(600):
        tracker, ep = _open()
        price, step = 100.0, ep.unit / 4
        for k in range(1, int(reactions.EPISODE_BARS) + 1):
            price += rng.choice((-step, step))
            tracker.advance_episodes("g", price, when=k * BAR)
        (done,) = tracker.drain_episodes() or (ep,)
        if done.first:
            ups += done.first > 0
            n += 1
    assert n > 400
    assert abs(ups / n - 0.5) < 0.07


def test_the_engine_journals_an_episode_for_every_touch():
    """Wired end to end: a touch opens an episode, and the engine hands it over when it ends."""
    from till_infinity.structures import engine

    eng = engine.Engine(intervals=("15m",))
    level = _level()
    eng._levels[("g", "15m")] = [level]
    eng.tracker.start_episode(level, Side.ABOVE, 100.0, _vol(), when=0.0)
    eng._advance_races("g", 101.0, when=reactions.EPISODE_BARS * BAR)
    (done,) = eng.drain_episodes()
    assert done.to_dict()["level_id"] == level.id


def test_the_service_journals_finished_episodes():
    """`record_outcomes` writes each finished episode as an observation with its path."""
    import asyncio
    import tempfile
    from pathlib import Path

    from till_infinity.bus import Bus
    from till_infinity.journal import Journal
    from till_infinity.structures import config as sx
    from till_infinity.structures.service import Watcher

    async def drive():
        with tempfile.TemporaryDirectory() as tmp:
            book = Journal(Path(tmp) / "journal.db")
            await book.open()
            watcher = Watcher(Bus(), settings=sx.Settings(macro=False), journal=book)
            try:
                tracker = watcher.engine.tracker
                ep = tracker.start_episode(_level(), Side.ABOVE, 100.0, _vol(), when=0.0)
                for k, x in enumerate((1.2, 2.3), start=1):
                    tracker.advance_episodes("g", 100 + x * ep.unit, when=k * BAR)
                tracker.advance_episodes("g", 100 + 2.3 * ep.unit, when=ep.deadline)
                await watcher.record_outcomes()
                return await book.entries()
            finally:
                await book.close()

    found = [e for e in asyncio.run(drive()) if e.context.get("shape") == "episode"]
    assert len(found) == 1
    assert str(found[0].kind) == "observation"
    assert found[0].context["kind"] == "clean"
    assert found[0].context["bars_up_2r"] == 2.0
