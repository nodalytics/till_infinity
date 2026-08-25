"""Key levels: PIP extraction, Kalman tracking, and directional inference."""

from __future__ import annotations

import math
import pickle
import random
import time

import pytest

from till_infinity.structures import levels as lv
from till_infinity.structures import pips, pivots, reactions
from till_infinity.structures.engine import STALE_BARS, Engine
from till_infinity.structures.levels import Kalman, Level, Outcome, Side, State
from till_infinity.structures.volatility import Volatility


def _vol(bps: float = 5.0) -> Volatility:
    vol = Volatility()
    price = 4400.0
    for _ in range(60):
        price *= 1 + bps / 10_000
        vol.update(price)
    return vol


# -------------------------------------------------------------------- pips


def test_pips_keep_the_shape_and_drop_the_noise():
    times = list(range(60))
    prices = [100.0] * 60
    prices[20] = 130.0  # one unmistakable peak
    found = pips.points(times, prices, count=5)
    assert 20 in [point.index for point in found]


def test_the_biggest_swing_is_taken_first():
    prices = [100.0] * 40
    prices[10], prices[30] = 105.0, 140.0
    order = pips.extract(prices, 3)
    assert 30 in order  # the larger swing, before the smaller one
    assert 10 not in order


def test_a_swing_is_not_knowable_until_bars_follow_it():
    """The look-ahead trap: a turn is only a turn once the next bars print."""
    times = [i * 60 for i in range(40)]
    prices = [100.0 + (10.0 if i == 20 else 0.0) for i in range(40)]
    found = pips.points(times, prices, count=5, confirm=3)
    peak = next(p for p in found if p.index == 20)
    assert peak.confirmed > peak.time
    assert peak not in pips.as_of(found, peak.time)
    assert peak in pips.as_of(found, peak.confirmed)


def test_highs_and_lows_are_told_apart():
    times = list(range(40))
    prices = [100.0] * 40
    prices[10], prices[25] = 120.0, 80.0
    found = {p.index: p.swing for p in pips.points(times, prices, count=6)}
    assert found[10] is pips.Swing.HIGH
    assert found[25] is pips.Swing.LOW


def test_a_series_too_short_to_have_a_shape_yields_nothing():
    assert pips.points([1, 2], [100.0, 101.0], count=5) == []


def test_mismatched_inputs_are_refused():
    with pytest.raises(ValueError, match="same length"):
        pips.points([1, 2, 3], [1.0, 2.0], count=3)


# ------------------------------------------------------------------ kalman


def test_a_confident_level_barely_moves_for_one_touch():
    """The reason for a filter rather than a chosen smoothing constant."""
    sure = Kalman(mean=100.0, variance=0.0001)
    unsure = Kalman(mean=100.0, variance=1.0)
    sure.update(101.0, noise=0.01, when=1.0)
    unsure.update(101.0, noise=0.01, when=1.0)
    assert abs(sure.mean - 100.0) < abs(unsure.mean - 100.0)


def test_certainty_grows_with_agreeing_touches():
    filt = Kalman(mean=100.0, variance=1.0)
    before = filt.sigma
    for _ in range(10):
        filt.update(100.0, noise=0.01, when=1.0)
    assert filt.sigma < before


def test_uncertainty_grows_while_a_level_goes_untested():
    filt = Kalman(mean=100.0, variance=0.01, updated=0.0)
    before = filt.variance
    filt.predict(when=86_400.0, drift_per_hour=0.05)
    assert filt.variance > before


def test_the_zone_widens_with_volatility():
    level = Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0, variance=0.01))
    calm_low, calm_high = level.zone(_vol(2.0))
    wild_low, wild_high = level.zone(_vol(40.0))
    assert (wild_high - wild_low) > (calm_high - calm_low)


def test_the_zone_is_clamped_at_both_ends():
    vol = _vol()
    tight = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=1e-12))
    loose = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=1e6))
    for level in (tight, loose):
        low, high = level.zone(vol)
        width = (high - low) / 2 / level.price * 10_000 / vol.bps
        assert lv.MIN_ZONE_VOL - 1e-6 <= width <= lv.MAX_ZONE_VOL + 1e-6


# ------------------------------------------------------------------ levels


def _turn(price: float, index: int, when: int) -> pips.Point:
    return pips.Point(
        index=index,
        time=when,
        price=price,
        swing=pips.Swing.LOW,
        prominence_bps=10.0,
        confirmed=when,
    )


def test_swings_at_a_similar_price_become_one_level():
    vol = _vol()
    turns = [_turn(4400.0 + i * 0.05, i, 1_000 + i) for i in range(4)]
    built = lv.form("gold", "5m", turns, vol)
    assert len(built) == 1
    assert built[0].swings == 4


def test_two_swings_are_not_a_level():
    """Any two points define a line, so two swings are evidence of nothing."""
    vol = _vol()
    turns = [_turn(4400.0, 0, 1_000), _turn(4400.05, 1, 1_001)]
    assert lv.form("gold", "5m", turns, vol) == []


def test_distant_swings_stay_separate():
    vol = _vol()
    turns = [_turn(4400.0 + i * 0.02, i, 1_000 + i) for i in range(3)]
    turns += [_turn(4600.0 + i * 0.02, 10 + i, 1_010 + i) for i in range(3)]
    assert len(lv.form("gold", "5m", turns, vol)) == 2


def test_a_rediscovered_level_is_not_a_new_one():
    """Otherwise re-forming throws away the touch history that gives it value."""
    vol = _vol()
    existing = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    existing.stats(Side.ABOVE).record(Outcome.REJECT, 1.0)
    found = [Level(feed="g", interval="5m", filter=Kalman(mean=4400.02, variance=0.5))]

    merged = lv.merge([existing], found, vol)
    assert len(merged) == 1
    assert merged[0].touches == 1


def test_overlapping_levels_are_folded_together_with_their_history():
    vol = _vol()
    first = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    first.stats(Side.ABOVE).record(Outcome.REJECT, 1.0)
    second = Level(feed="g", interval="5m", filter=Kalman(mean=4400.01, variance=0.5))
    second.stats(Side.ABOVE).record(Outcome.BREAK, -1.0)

    folded = lv.dedupe([first, second], vol)
    assert len(folded) == 1
    assert folded[0].touches == 2


def test_a_broken_level_that_holds_again_has_flipped():
    """A flipped level is a repeating structure, which is the point of noticing."""
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    level.record(Side.BELOW, Outcome.BREAK, 2.0)
    assert level.state is State.BROKEN
    level.record(Side.ABOVE, Outcome.REJECT, 1.5)
    assert level.state is State.FLIPPED


def test_which_side_price_is_on():
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    assert level.side_of(4410.0) is Side.ABOVE
    assert level.side_of(4390.0) is Side.BELOW
    assert Side.ABOVE.opposite is Side.BELOW
    assert Side.ABOVE.rejection_is_up


# --------------------------------------------------------------- inference


def _touch(tracker, level, side, exit_bps, when, vol):
    price = level.price
    features = reactions.features_for(level, side, price, vol, approach_vol=1.0, when=when)
    tracker.begin(level, price, features, when)
    for step in range(1, 30):
        moved = level.price * (1 + exit_bps * step / 8 / 10_000)
        done = tracker.update(level, moved, vol, when + step * 60)
        if done:
            return done
    return None


def test_a_level_answers_differently_from_each_side():
    """The asymmetry the whole design exists for."""
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=12)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    for i in range(6):
        _touch(tracker, level, Side.ABOVE, +40.0, 1_000_000 + i * 100_000, vol)

    above = level.stats(Side.ABOVE)
    # Far fewer than 6 effective: these are 5m touches spread over days, and a
    # 5m level's evidence halves in under one. That is the point of scaling the
    # half-life by timeframe rather than holding one constant for all of them.
    assert 0 < above.touches < 6.0
    assert level.stats(Side.BELOW).touches == 0


def test_three_touches_the_same_way_is_not_certainty():
    """Reporting 100% from three observations is how a system talks itself in."""
    stats = lv.SideStats()
    for _ in range(3):
        stats.record(Outcome.REJECT, 1.0)
    assert stats.probability_up(prior_up=0.5) < 0.95


def test_a_fresh_level_borrows_from_similar_ones():
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=12)
    for n in range(6):
        neighbour = Level(feed=f"f{n}", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
        for i in range(4):
            _touch(tracker, neighbour, Side.ABOVE, +40.0, 1_000_000 + n * 10_000 + i * 900, vol)

    fresh = Level(feed="new", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(fresh, Side.ABOVE, 4400.0, vol, approach_vol=1.0)
    found = reactions.infer(fresh, Side.ABOVE, features, tracker.memory, vol)

    assert found.own_touches == 0
    assert found.neighbours > 0
    assert found.probability_up > 0.5


def test_an_edge_is_measured_against_the_base_rate():
    """A conditional that matches the unconditional has said nothing."""
    at_base = reactions.Inference(
        side=Side.ABOVE,
        probability_up=0.62,
        expected_push=2.0,
        push_sigma=0.1,
        base_rate_up=0.62,
        own_touches=50,
        neighbours=12,
    )
    assert at_base.edge == pytest.approx(0.0)
    assert not at_base.actionable


@pytest.mark.parametrize(
    ("touches", "neighbours", "edge_from", "push"),
    [
        (2, 1, 0.90, 3.0),  # a big edge on three observations is noise
        (50, 12, 0.51, 3.0),  # a large sample at the base rate is nothing
        (50, 12, 0.80, 0.1),  # a confident call worth nothing does not pay
    ],
)
def test_all_three_guards_are_needed(touches, neighbours, edge_from, push):
    found = reactions.Inference(
        side=Side.ABOVE,
        probability_up=edge_from,
        expected_push=push,
        push_sigma=0.1,
        base_rate_up=0.5,
        own_touches=touches,
        neighbours=neighbours,
    )
    assert not found.actionable


def _call(edge: float) -> reactions.Inference:
    """A call that clears every guard except, possibly, the edge one."""
    return reactions.Inference(
        side=Side.ABOVE,
        probability_up=0.5 + edge,
        expected_push=1.5,
        push_sigma=0.4,
        base_rate_up=0.5,
        own_touches=10,
        neighbours=12,
        risk_vol=0.5,
    )


def test_the_edge_gate_sits_above_the_measured_step():
    """The step is at 0.0968; anything below it is a coin flip.

    `edge.md` §1 replayed 10,483 calls against the outcome of the touch each
    opened. The three lowest deciles of |edge| run 54.8% to 61.5% direction
    with a mean realised push of *zero*; the fourth, starting at 0.0968, jumps
    to 69.3% and a push of 0.49.

    This guards the number rather than the behaviour, which is unusual and
    deliberate: it was a bare literal for months at 0.08 — inside the flat
    region, publishing a quarter of its calls at a coin flip — precisely
    because nothing pointed at it.
    """
    assert reactions.MIN_EDGE >= 0.0968


def test_a_call_inside_the_flat_region_is_not_published():
    """0.08 was the old gate and admits the band that behaves like noise."""
    assert not _call(0.08).actionable
    assert not _call(0.0967).actionable


def test_a_call_above_the_step_is_published():
    """Clear of the boundary, not on it.

    `_call(0.10)` would land on `MIN_EDGE` exactly and fail: `0.5 + 0.10 - 0.5`
    is `0.09999999999999998`. That is float layout rather than the gate, and a
    boundary test that sits on the boundary measures the wrong thing.
    """
    assert _call(0.11).actionable
    assert _call(0.20).actionable


def test_a_real_call_passes_all_three():
    found = reactions.Inference(
        side=Side.ABOVE,
        probability_up=0.72,
        expected_push=1.5,
        push_sigma=0.4,
        base_rate_up=0.5,
        own_touches=10,
        neighbours=12,
        risk_vol=0.5,
    )
    assert found.actionable
    assert found.direction == "up"


def test_a_touch_resolves_into_a_labelled_example():
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=12)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    done = _touch(tracker, level, Side.ABOVE, +40.0, 1_000_000, vol)

    assert done is not None
    assert done.outcome is Outcome.REJECT
    assert done.push_vol > 0
    assert len(tracker.memory) == 1


def test_an_interaction_that_goes_nowhere_is_kept_as_chop():
    """A model never shown 'nothing happened' will predict a move every time."""
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=0.4)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(level, Side.ABOVE, 4400.0, vol)
    tracker.begin(level, 4400.0, features, 1_000_000)
    done = tracker.update(level, 4400.0, vol, 1_000_200)

    assert done is not None
    assert done.outcome is Outcome.CHOP


def test_a_touch_spanning_a_closed_market_is_discarded_rather_than_resolved():
    """The weekend case, and it is a data-quality bug rather than an alert one.

    FX shuts on Friday evening and reopens on Sunday. A touch open at the close
    would otherwise resolve on the reopen, and `_close` records `push_vol` as
    the distance at the moment of closing — so the level's own statistics and
    `facto`'s training targets would learn the **opening gap** as this level's
    reaction to being touched. It is not a reaction to anything.
    """
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=12)
    level = Level(feed="eurusd", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(level, Side.ABOVE, 4400.0, vol)
    tracker.begin(level, 4400.0, features, 1_000_000)

    # The market reopens two days later, well past the gap factor, and gaps.
    done = tracker.update(level, 4460.0, vol, 1_000_000 + 2 * 86_400)

    assert done is None, "a gap was recorded as an outcome"
    assert tracker.open_touch(level) is None, "and the touch was left open"
    assert level.touches == 0, "the gap reached the level's own statistics"


def test_a_slow_session_still_resolves_as_chop():
    """The other half: only an absence of observation is thrown away.

    Discarding anything that outlives its horizon would lose chop entirely,
    and chop is the outcome a model most needs to be shown.
    """
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=0.4)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(level, Side.ABOVE, 4400.0, vol)
    tracker.begin(level, 4400.0, features, 1_000_000)

    # Past the horizon but inside the gap factor.
    done = tracker.update(level, 4400.0, vol, 1_000_000 + 200)

    assert done is not None
    assert done.outcome is Outcome.CHOP


def test_neighbours_never_cross_sides():
    """A floor's history must not vote on a ceiling's future."""
    above = reactions.Features(Side.ABOVE, 1.0, 0.5, 0.5, 1.0, 0.5)
    below = reactions.Features(Side.BELOW, 1.0, 0.5, 0.5, 1.0, 0.5)
    assert above.distance(below) == float("inf")
    assert above.distance(above) == 0.0


# ------------------------------------------------------------------ engine


#: The engine takes a median across venues, so a bar needs a quorum to count.
QUORUM = ("OANDA", "SAXO", "TVC")


def _bar(feed, interval, when, price, rand=None, venues=QUORUM):
    """One bar as every venue reports it — the shape the bus delivers."""
    for venue in venues:
        wobble = rand.gauss(0, 0.02) if rand else 0.0
        yield {
            "feed": feed,
            "venue": venue,
            "interval": interval,
            "time": when,
            "high": price + abs(wobble) + 1.0,
            "low": price - abs(wobble) - 1.0,
            "close": price + wobble,
        }


def _range_bound(bars: int = 700, seed: int = 9):
    rand = random.Random(seed)
    price, when = 4425.0, 1_000_000
    for i in range(bars):
        price += rand.gauss(0, 3)
        if price < 4400:
            price = 4400 + (4400 - price) * 0.8
        if price > 4450:
            price = 4450 - (price - 4450) * 0.8
        yield from _bar("gold", "5m", when + i * 300, price, rand)


def test_the_engine_finds_a_handful_of_swing_levels_not_a_forest():
    """At one level every few basis points, every price is at a level."""
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)
    assert 1 <= len(engine.levels("gold", "5m")) <= 12


def test_pivots_are_built_from_completed_sessions():
    """They need no confirmation delay — yesterday fully determines today."""
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)
    daily = engine.levels("gold", "daily")
    assert daily
    assert all(level.origin.startswith("pivot") for level in daily)


def test_a_session_still_running_cannot_make_pivots():
    engine = Engine(intervals=("5m",))
    engine.observe_bar(
        {"feed": "g", "interval": "5m", "time": 1_000_000, "high": 10, "low": 9, "close": 9.5}
    )
    assert engine.levels("g", "daily") == []


def test_the_engine_produces_calls_with_evidence():
    engine = Engine(intervals=("5m",))
    calls = []
    for bar in _range_bound():
        calls += engine.observe_bar(bar)
    assert calls
    assert any(call.inference.actionable for call in calls)
    assert engine.tracker.memory.base_rate_up > 0


def test_an_interval_the_engine_does_not_watch_is_ignored():
    engine = Engine(intervals=("5m",))
    assert engine.observe_bar({"feed": "gold", "interval": "1d", "close": 4400.0}) == []


def test_one_venue_is_not_a_consensus():
    """The series took whichever venue published last, which mixed them."""
    engine = Engine(intervals=("5m",))
    engine.observe_bar(next(iter(_bar("gold", "5m", 1_000, 4400.0, venues=("OANDA",)))))
    assert len(engine.series("gold", "5m").closes) == 0


def test_a_bar_enters_the_series_once_enough_venues_agree():
    engine = Engine(intervals=("5m",))
    for payload in _bar("gold", "5m", 1_000, 4400.0):
        engine.observe_bar(payload)
    series = engine.series("gold", "5m")
    assert len(series.closes) == 1
    assert series.closes[-1] == pytest.approx(4400.0, abs=0.1)


def test_the_consensus_is_a_median_across_venues():
    """One venue printing nonsense must not move the series."""
    engine = Engine(intervals=("5m",))
    for venue, price in zip(QUORUM, (4400.0, 4400.0, 9999.0), strict=True):
        engine.observe_bar(next(iter(_bar("gold", "5m", 1_000, price, venues=(venue,)))))
    assert engine.series("gold", "5m").closes[-1] == pytest.approx(4400.0, abs=0.1)


@pytest.mark.parametrize(
    "payload",
    [{}, {"feed": "gold"}, {"feed": "gold", "interval": "5m"}, {"interval": "5m", "close": 1.0}],
)
def test_junk_bars_produce_nothing(payload):
    assert Engine(intervals=("5m",)).observe_bar(payload) == []


# ------------------------------------------------------------ warming up


def test_an_engine_warms_from_stored_history(tmp_path):
    """The bus carries a notice per sweep; levels need a series."""
    import sqlite3

    path = tmp_path / "prices.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE bars (source TEXT, feed TEXT, venue TEXT, ticker TEXT, interval TEXT,"
        " ts INTEGER, open REAL, high REAL, low REAL, close REAL, volume REAL,"
        " closed INT, updated REAL)"
    )
    rows = [
        (
            "tv",
            payload["feed"],
            payload["venue"],
            "X",
            payload["interval"],
            payload["time"],
            payload["close"],
            payload["high"],
            payload["low"],
            payload["close"],
            0,
            1,
            0.0,
        )
        for payload in _range_bound(300)
    ]
    conn.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    engine = Engine(intervals=("5m",))
    assert engine.seed(path) > 0
    assert engine.levels("gold", "5m")
    assert len(engine.tracker.memory) > 0  # touch history exists from minute one


def test_warming_from_a_missing_store_is_not_an_error(tmp_path):
    assert Engine(intervals=("5m",)).seed(tmp_path / "nothing.db") == 0


def test_an_untouched_level_far_from_price_is_dropped():
    """A swing price never returned to is a swing, not a level."""
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold")
    for _ in range(60):
        vol.update(4400.0 * (1 + 0.0005))

    near = Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    far = Level(feed="gold", interval="5m", filter=Kalman(mean=9000.0, variance=0.5))
    kept = engine.prune([near, far], price=4400.0, vol=vol, when=1_000_000.0)

    assert near in kept
    assert far not in kept


def test_a_touched_level_survives_however_far_price_has_moved():
    """It is worth remembering precisely because price left it."""
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold")
    for _ in range(60):
        vol.update(4400.0 * (1 + 0.0005))

    far = Level(feed="gold", interval="5m", filter=Kalman(mean=9000.0, variance=0.5))
    far.record(Side.ABOVE, Outcome.REJECT, 1.0, 1_000_000.0)

    assert far in engine.prune([far], price=4400.0, vol=vol, when=1_000_100.0)


def test_untouched_levels_are_capped_at_what_a_person_would_mark():
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold")
    for _ in range(60):
        vol.update(4400.0 * (1 + 0.0005))

    crowd = [
        Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0 + i * 0.05, variance=0.5))
        for i in range(120)
    ]
    kept = engine.prune(crowd, price=4400.0, vol=vol, when=1_000_000.0)
    assert len(kept) <= 15


def test_levels_stay_bounded_over_a_long_history():
    engine = Engine(intervals=("5m",))
    for bar in _range_bound(700):
        engine.observe_bar(bar)
    levels = engine.levels("gold", "5m")
    assert len(levels) <= 20
    assert any(level.touches >= 1 for level in levels)


def test_pivots_do_not_accumulate_forever():
    """Ten per session, and sessions keep completing."""
    engine = Engine(intervals=("5m",))
    for bar in _range_bound(2000):
        engine.observe_bar(bar)
    assert len(engine.levels("gold", "daily")) <= 20


def test_a_corrected_bar_replaces_rather_than_appends():
    engine = Engine(intervals=("5m",))
    for price in (4400.0, 4410.0):
        for payload in _bar("g", "5m", 1_000, price):
            engine.observe_bar(payload)
    series = engine.series("g", "5m")
    assert len(series.closes) == 1
    assert series.closes[-1] == pytest.approx(4410.0, abs=0.1)


# ------------------------------------------------------- levels going stale


def test_old_evidence_fades_rather_than_counting_forever():
    """Ten rejections in January must not outvote three breaks last week."""
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    start = 1_000_000.0
    for i in range(10):
        level.record(Side.ABOVE, Outcome.REJECT, 1.0, start + i)
    old = level.stats(Side.ABOVE).touches

    # three months later, the level starts breaking instead
    later = start + 90 * 86_400
    for i in range(3):
        level.record(Side.ABOVE, Outcome.BREAK, -1.0, later + i)

    stats = level.stats(Side.ABOVE)
    assert stats.touches < old  # the ten have decayed below their raw count
    assert stats.probability_up() < 0.5  # recent behaviour now dominates


def test_evidence_survives_a_short_gap():
    """Fading must be gradual — a level should not forget overnight."""
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    start = 1_000_000.0
    for i in range(6):
        level.record(Side.ABOVE, Outcome.REJECT, 1.0, start + i * 3600)
    assert level.stats(Side.ABOVE).touches > 4.0


def test_a_regime_change_discounts_what_a_level_learned():
    """The tide changed: this level learned its behaviour in another market."""
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    for i in range(8):
        level.record(Side.ABOVE, Outcome.REJECT, 1.0, 1_000_000.0 + i)
    before = level.stats(Side.ABOVE).touches

    level.regime_changed()
    assert level.stats(Side.ABOVE).touches < before
    assert level.stats(Side.ABOVE).touches > 0  # discounted, not erased


def test_a_decisive_break_discounts_the_side_it_broke_from():
    """A level that just conspicuously failed should stop predicting a bounce."""
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    for i in range(8):
        level.record(Side.ABOVE, Outcome.REJECT, 1.0, 1_000_000.0 + i)
    before = level.stats(Side.ABOVE).probability_up()

    level.record(Side.ABOVE, Outcome.BREAK, -lv.DECISIVE_BREAK_VOL * 1.5, 1_000_100.0)
    assert level.state is State.BROKEN
    assert level.stats(Side.ABOVE).probability_up() < before


def test_a_shallow_break_does_not_wipe_the_history():
    """Not every break is decisive; a wick through is not a regime change."""
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    for i in range(8):
        level.record(Side.ABOVE, Outcome.REJECT, 1.0, 1_000_000.0 + i)
    level.record(Side.ABOVE, Outcome.BREAK, -0.1, 1_000_100.0)
    assert level.stats(Side.ABOVE).touches > 7.0


def test_the_engine_discounts_every_level_when_the_tide_turns():
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)
    before = sum(level.touches for level in engine.levels("gold"))
    assert engine.regime_changed("gold") > 0
    assert sum(level.touches for level in engine.levels("gold")) < before


def test_a_pivot_and_a_swing_are_told_apart_but_not_walled_off():
    """Pivots behave differently; a pivot with no history still needs a prior."""
    vol = _vol()
    swing = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    pivot = Level(
        feed="g", interval="daily", filter=Kalman(mean=4400.0, variance=0.5), origin="pivot:R1"
    )
    a = reactions.features_for(swing, Side.ABOVE, 4400.0, vol)
    b = reactions.features_for(pivot, Side.ABOVE, 4400.0, vol)
    assert a.pivot == 0.0
    assert b.pivot == 1.0
    assert 0 < a.distance(b) < float("inf")  # further apart, still comparable


# --------------------------------------------------------------- look-ahead


def test_the_engine_never_forms_a_level_from_an_unseen_swing(monkeypatch):
    """The failure that does not show up until the numbers are being trusted.

    A turning point is not knowable until the bars after it print. If the
    engine ever passes an unconfirmed swing to `form`, it is drawing levels
    nobody could have drawn and every measurement against them flatters itself.
    """
    engine = Engine(intervals=("5m",))
    seen: list[tuple[int, int]] = []
    real_form = lv.form

    def spy(feed, interval, turns, vol, **kwargs):
        seen.extend((point.confirmed, engine._now) for point in turns)
        return real_form(feed, interval, turns, vol, **kwargs)

    monkeypatch.setattr(lv, "form", spy)
    monkeypatch.setattr("till_infinity.structures.engine.lv.form", spy)

    for bar in _range_bound(400):
        engine._now = bar["time"]
        engine.observe_bar(bar)

    assert seen, "the spy never ran, so this test proved nothing"
    assert all(confirmed <= now for confirmed, now in seen)


def test_no_level_is_created_before_the_bar_that_created_it():
    engine = Engine(intervals=("5m",))
    for bar in _range_bound(400):
        engine.observe_bar(bar)
        assert all(level.created <= bar["time"] for level in engine.levels("gold", "5m"))


def test_a_pivot_is_never_available_during_its_own_session():
    """Yesterday's range is knowable today. Today's is not."""
    engine = Engine(intervals=("5m",))
    day = 86_400
    start = 1_000_000 - (1_000_000 % day)
    for i in range(12):
        for payload in _bar("g", "5m", start + i * 3600, 100.0):
            engine.observe_bar(payload)
        assert engine.levels("g", "daily") == []

    # a bar from the next day completes the session, and only then do pivots exist
    for payload in _bar("g", "5m", start + day + 60, 100.0):
        engine.observe_bar(payload)
    daily = engine.levels("g", "daily")
    assert daily
    assert all(level.created <= start + day + 60 for level in daily)


def test_a_pivot_uses_only_the_completed_session_range():
    session = pivots.Session(start=0, end=86_400, high=110.0, low=90.0, close=100.0)
    built = pivots.levels_from(session)
    assert built["PP"] == pytest.approx(100.0)
    assert built["PH"] == 110.0
    assert built["R1"] == pytest.approx(110.0)


def test_a_touch_is_only_resolved_by_prices_after_it_began():
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=12)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(level, Side.ABOVE, 4400.0, vol)
    tracker.begin(level, 4400.0, features, when=1_000_000)
    done = tracker.update(level, 4500.0, vol, when=1_000_600)
    assert done is not None
    assert done.resolved > done.started


# ------------------------------------------- evidence ages by timeframe


def test_a_weekly_level_remembers_far_longer_than_a_five_minute_one():
    """One constant cannot serve both: a weekly level is tested a few times a year."""
    fast = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    slow = Level(feed="g", interval="1w", filter=Kalman(mean=4400.0, variance=0.5))
    start = 1_000_000.0
    for level in (fast, slow):
        level.record(Side.ABOVE, Outcome.REJECT, 1.0, start)

    month = start + 30 * 86_400
    for level in (fast, slow):
        level.age(month)

    assert fast.stats(Side.ABOVE).touches < 0.01  # a month is forever on 5m
    assert slow.stats(Side.ABOVE).touches > 0.95  # and nothing at all on 1w


def test_the_half_life_scales_with_the_timeframe():
    steps = [lv.half_life_days(tf) for tf in ("5m", "15m", "1h", "4h", "1d", "1w")]
    assert steps == sorted(steps)
    assert steps[0] < 1.0
    assert steps[-1] > 1000.0


def test_an_unknown_timeframe_falls_back_rather_than_crashing():
    assert lv.half_life_days("fortnightly") == lv.TOUCH_HALF_LIFE_DAYS


# ------------------------------------ certainty the evidence cannot support


def test_neighbours_agreeing_is_evidence_not_proof():
    """Twelve neighbours all going one way must not produce a claim of 0% or 100%."""
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=12)
    when = 1_000_000.0
    for n in range(12):
        level = Level(feed=f"f{n}", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
        when += 50_000
        _touch(tracker, level, Side.ABOVE, +40.0, when, vol)  # every one goes up

    fresh = Level(feed="new", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(fresh, Side.ABOVE, 4400.0, vol)
    found = reactions.infer(fresh, Side.ABOVE, features, tracker.memory, vol)

    assert found.own_touches == 0
    assert found.neighbours >= 8
    assert 0.0 < found.probability_up < 1.0


def test_a_direction_follows_the_expected_move_not_the_win_rate():
    """Four small losses and one large win is a positive expectation."""
    found = reactions.Inference(
        side=Side.ABOVE,
        probability_up=0.2,
        expected_push=1.4,
        push_sigma=2.0,
        base_rate_up=0.5,
        own_touches=20,
        neighbours=12,
    )
    assert found.direction == "up"
    assert found.mixed


def test_a_mixed_signal_is_not_a_call():
    """Whichever half you act on, the other says you are wrong."""
    found = reactions.Inference(
        side=Side.ABOVE,
        probability_up=0.2,
        expected_push=1.4,
        push_sigma=2.0,
        base_rate_up=0.5,
        own_touches=20,
        neighbours=12,
    )
    assert not found.actionable


def test_agreement_between_the_two_is_not_mixed():
    found = reactions.Inference(
        side=Side.ABOVE,
        probability_up=0.75,
        expected_push=1.4,
        push_sigma=0.3,
        base_rate_up=0.5,
        own_touches=20,
        neighbours=12,
        risk_vol=0.5,
    )
    assert not found.mixed
    assert found.direction == "up"
    assert found.actionable


# --------------------------------------------------- false breakouts (traps)


def _walk(tracker, level, side, path, vol, start=1_000_000.0, wick_bps=0.0):
    """Run price along `path` (bps from the level) until the touch resolves.

    `wick_bps` extends each bar beyond its close, which is what separates the
    extreme from the origin — without it they are the same number.
    """
    entry = level.price
    features = reactions.features_for(level, side, entry, vol, approach_vol=1.0, when=start)
    tracker.begin(level, entry, features, start)
    for step, offset in enumerate(path, start=1):
        moved = level.price * (1 + offset / 10_000)
        low = level.price * (1 + (offset - wick_bps) / 10_000)
        high = level.price * (1 + (offset + wick_bps) / 10_000)
        done = tracker.update(level, moved, vol, start + step * 60, low, high)
        if done:
            return done
    return None


def test_a_break_that_comes_straight_back_is_a_trap_not_a_break():
    """The obvious trade lost. Recording it as a clean break teaches the opposite."""
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=24, trap_bars=12)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))

    # up through the level, then all the way back down through it
    done = _walk(tracker, level, Side.BELOW, [10, 20, 30, 20, 5, -10, -20], vol)

    assert done is not None
    assert done.outcome is Outcome.TRAP
    assert done.excursion_vol > 0  # what the breakout entry was offered


def test_a_break_that_holds_is_still_a_break():
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=24, trap_bars=1)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))

    done = _walk(tracker, level, Side.BELOW, [10, 20, 30, 35, 40, 45, 50, 55, 60], vol)

    assert done is not None
    assert done.outcome is Outcome.BREAK


def test_a_break_is_provisional_until_it_survives():
    """It is not a break until it holds, which is how anyone trading one treats it."""
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=24, trap_bars=12)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(level, Side.BELOW, 4400.0, vol)
    tracker.begin(level, 4400.0, features, 1_000_000.0)

    for step, offset in enumerate([10, 20, 30], start=1):
        moved = level.price * (1 + offset / 10_000)
        assert tracker.update(level, moved, vol, 1_000_000.0 + step * 60) is None

    assert tracker.open_touch(level).breaking


def test_a_trap_leaves_the_level_intact():
    """It held — violently, after letting price through. That is not failing."""
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=24, trap_bars=12)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    _walk(tracker, level, Side.BELOW, [10, 20, 30, 20, 5, -10, -20], vol)

    assert level.state is not State.BROKEN
    assert level.stats(Side.BELOW).traps >= 1


def test_the_trap_rate_says_whether_breaks_here_are_worth_trading():
    stats = lv.SideStats()
    for _ in range(3):
        stats.record(Outcome.BREAK, 2.0)
    for _ in range(1):
        stats.record(Outcome.TRAP, -1.0)
    assert stats.trap_rate == pytest.approx(0.25)


def test_a_level_never_broken_has_no_trap_rate():
    stats = lv.SideStats()
    stats.record(Outcome.REJECT, 1.0)
    assert stats.trap_rate == 0.0


def test_a_trap_is_pushed_the_way_it_ended_not_the_way_it_broke():
    """A breakout entry loses; the push has to reflect that, not the excursion."""
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=24, trap_bars=12)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    done = _walk(tracker, level, Side.BELOW, [10, 20, 30, 20, 5, -10, -20], vol)
    assert done.push_vol < 0  # ended below, despite having broken up


def test_traps_and_breaks_are_counted_apart():
    stats = lv.SideStats()
    stats.record(Outcome.BREAK, 2.0)
    stats.record(Outcome.TRAP, -2.0)
    assert stats.breaks == 1
    assert stats.traps == 1
    assert stats.touches == 2


# ------------------------------------------------------------ back checks


def _broken(interval: str = "5m", when: float = 1_000_000.0) -> Level:
    """A level price has broken upward through."""
    level = Level(feed="g", interval=interval, filter=Kalman(mean=4400.0, variance=0.5))
    level.record(Side.BELOW, Outcome.BREAK, 2.0, when)
    return level


def test_a_retest_from_the_new_side_is_a_back_check():
    """Momentum proven by the break, entry on the pullback, stop beyond the level."""
    assert _broken().is_backcheck(Side.ABOVE, 1_000_600.0)


def test_a_return_from_the_old_side_is_not_a_back_check():
    """That is the break failing late, which is a different thing entirely."""
    assert not _broken().is_backcheck(Side.BELOW, 1_000_600.0)


def test_a_visit_long_after_the_break_is_just_a_level():
    level = _broken()
    assert not level.is_backcheck(Side.ABOVE, 1_000_000.0 + 90 * 86_400)


def test_the_back_check_window_scales_with_the_timeframe():
    """Thirty bars is a couple of hours on 5m and most of a year on 1w."""
    fast = _broken("5m").backcheck_window()
    slow = _broken("1w").backcheck_window()
    assert slow > 100 * fast


def test_a_level_never_broken_has_no_back_check():
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    assert not level.is_backcheck(Side.ABOVE, 1_000_000.0)


def test_a_held_retest_is_recorded_as_a_back_check():
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=24, trap_bars=1)
    level = _broken(when=1_000_000.0)

    # price comes back down to it and bounces
    _walk(tracker, level, Side.ABOVE, [-2, -1, 5, 15, 25, 35], vol, start=1_000_600.0)

    stats = level.stats(Side.ABOVE)
    assert stats.backchecks >= 1
    assert stats.rejects >= 1  # it is also a rejection; the level held
    assert level.state is State.FLIPPED


def test_a_first_touch_is_not_counted_as_a_back_check():
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=24)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    _walk(tracker, level, Side.ABOVE, [-2, 5, 15, 25, 35], vol)
    assert level.stats(Side.ABOVE).backchecks == 0


def test_the_stop_sits_beyond_the_zone_not_at_the_level():
    """A stop inside the zone is a stop inside the noise — the level working hits it."""
    vol = _vol()
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    low, high = level.zone(vol)

    assert level.stop_for(Side.ABOVE, vol) < low
    assert level.stop_for(Side.BELOW, vol) > high


def test_risk_is_reported_in_the_same_units_as_the_reward():
    vol = _vol()
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    risk = level.risk_vol(Side.ABOVE, 4400.0, vol)
    assert risk > 0

    found = reactions.Inference(
        side=Side.ABOVE,
        probability_up=0.7,
        expected_push=2.0,
        push_sigma=0.5,
        base_rate_up=0.5,
        own_touches=10,
        neighbours=12,
        risk_vol=risk,
    )
    assert found.reward_to_risk == pytest.approx(2.0 / risk)


def test_an_expected_move_with_no_risk_recorded_has_no_ratio():
    found = reactions.Inference(
        side=Side.ABOVE,
        probability_up=0.7,
        expected_push=2.0,
        push_sigma=0.5,
        base_rate_up=0.5,
        own_touches=10,
        neighbours=12,
    )
    assert found.reward_to_risk == 0.0


def test_back_checks_learn_from_other_back_checks():
    """A retest is a different setup from a first touch, so the neighbours differ."""
    first = reactions.Features(Side.ABOVE, 1.0, 0.5, 0.5, 1.0, 0.5, backcheck=0.0)
    retest = reactions.Features(Side.ABOVE, 1.0, 0.5, 0.5, 1.0, 0.5, backcheck=1.0)
    assert first.distance(retest) > 0
    assert first.distance(first) == 0.0


# ------------------------------------ the origin: where the two legs meet


def test_the_origin_is_where_the_move_turned_not_the_wick():
    """The extreme is liquidity taken beyond the level at a price nobody traded."""
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=24)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))

    # closes reach -6bps, but each bar wicks 3bps further than it closes
    done = _walk(tracker, level, Side.ABOVE, [-2, -4, -6, -3, 5, 20, 40], vol, wick_bps=3.0)

    assert done is not None
    assert done.extreme < done.origin  # the wick is deeper than the turn
    assert done.origin == pytest.approx(level.price * (1 - 6 / 10_000), rel=1e-4)
    assert done.extreme == pytest.approx(level.price * (1 - 9 / 10_000), rel=1e-4)


def test_the_level_learns_from_the_origin_rather_than_the_extreme():
    """A level drawn at the wick is drawn where nobody traded."""
    engine = Engine(intervals=("5m",))
    for bar in _range_bound(400):
        engine.observe_bar(bar)
    touched = [lv for lv in engine.levels("gold", "5m") if lv.touches >= 1]
    assert touched  # the path ran; the observation fed in was the origin


def test_a_hard_rejection_leaves_faster_than_it_arrived():
    """Weak in, strong out. The number that says the level did something."""
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=24)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    done = _walk(tracker, level, Side.ABOVE, [-1, -2, 10, 25, 45], vol)

    assert done is not None
    assert done.departure_vol > 0
    assert done.energy > 1.0


def test_energy_needs_both_legs_to_mean_anything():
    """Recording only the approach makes absorption and rejection identical."""
    from till_infinity.structures.reactions import Features, Touch

    quiet = Touch(
        feed="g",
        level_price=4400.0,
        features=Features(
            Side.ABOVE, approach_vol=4.0, depth_vol=0.5, strength=0.5, run_vol=1.0, experience=0.5
        ),
        started=1.0,
        entry=4400.0,
        extreme=4400.0,
        departure_vol=1.0,
    )
    assert quiet.energy < 1.0  # walked in, drifted out — the level was scenery


def test_an_approach_of_zero_has_no_energy_ratio():
    from till_infinity.structures.reactions import Features, Touch

    touch = Touch(
        feed="g",
        level_price=4400.0,
        features=Features(Side.ABOVE, 0.0, 0.5, 0.5, 1.0, 0.5),
        started=1.0,
        entry=4400.0,
        extreme=4400.0,
        departure_vol=2.0,
    )
    assert touch.energy == 0.0


def test_the_zone_stretches_on_the_side_the_wick_ran():
    """A level is a zone from origin to wick, and it is not symmetric."""
    vol = _vol()
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    origin, wick = 4400.0, 4400.0 * (1 - 20 / 10_000)  # came from above, wicked down

    level.observe_wick(Side.ABOVE, origin, wick, vol)
    low, high = level.zone(vol)

    assert level.price - low > high - level.price  # the lower edge stretched


def test_arriving_from_below_stretches_the_other_edge():
    vol = _vol()
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    level.observe_wick(Side.BELOW, 4400.0, 4400.0 * (1 + 20 / 10_000), vol)
    low, high = level.zone(vol)
    assert high - level.price > level.price - low


def test_a_level_with_no_wicks_is_still_a_band():
    vol = _vol()
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    low, high = level.zone(vol)
    assert high > low


def test_wick_depth_is_averaged_rather_than_taken_from_the_last_one():
    """One unusually long wick should not redefine the zone by itself."""
    vol = _vol()
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    for _ in range(6):
        level.observe_wick(Side.ABOVE, 4400.0, 4400.0 * (1 - 5 / 10_000), vol)
    steady = level.stats(Side.ABOVE).wick_vol

    # one wick twelve times as long as the others
    level.observe_wick(Side.ABOVE, 4400.0, 4400.0 * (1 - 60 / 10_000), vol)
    after = level.stats(Side.ABOVE).wick_vol
    raw = 60.0 / vol.bps

    assert after > steady  # it moved
    assert after < steady + (raw - steady) * 0.5  # but took less than half the jump


def test_the_zone_is_still_clamped_however_long_the_wick():
    vol = _vol()
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    for _ in range(20):
        level.observe_wick(Side.ABOVE, 4400.0, 4400.0 * (1 - 5000 / 10_000), vol)
    low, _high = level.zone(vol)
    width = (level.price - low) / level.price * 10_000 / vol.bps
    assert width <= lv.MAX_ZONE_VOL + 1e-6


def test_p_down_is_the_complement_and_nothing_else():
    """One counter, two outcomes. Not a second model."""
    from till_infinity.structures.reactions import Inference

    call = Inference(
        side=Side.ABOVE,
        probability_up=0.23,
        expected_push=-1.4,
        push_sigma=0.8,
        base_rate_up=0.47,
        own_touches=9.0,
        neighbours=12,
    )
    assert call.probability_down == pytest.approx(0.77)
    assert call.probability_up + call.probability_down == pytest.approx(1.0)


def test_a_down_call_reports_the_probability_of_going_down():
    """`down p=23%` reads as 23% confidence in down. It is 77% — say that."""
    from till_infinity.structures.reactions import Inference

    call = Inference(
        side=Side.ABOVE,
        probability_up=0.23,
        expected_push=-1.4,
        push_sigma=0.8,
        base_rate_up=0.47,
        own_touches=9.0,
        neighbours=12,
    )
    assert call.direction == "down"
    assert call.probability == pytest.approx(0.77)
    assert "p=77%" in str(call)
    # The base rate has to move with it, or the pair is not a comparison.
    assert call.base_rate == pytest.approx(0.53)
    assert "base 53%" in str(call)


def test_an_up_call_is_unchanged_by_any_of_this():
    from till_infinity.structures.reactions import Inference

    call = Inference(
        side=Side.BELOW,
        probability_up=0.78,
        expected_push=1.1,
        push_sigma=0.6,
        base_rate_up=0.47,
        own_touches=9.0,
        neighbours=12,
    )
    assert call.probability == pytest.approx(call.probability_up)
    assert call.base_rate == pytest.approx(call.base_rate_up)
    assert "p=78%" in str(call)
    assert "base 47%" in str(call)


def test_the_edge_is_the_same_size_whichever_way_it_points():
    """(1-p) - (1-b) = -(p - b). The gates use abs(edge) for this reason."""
    from till_infinity.structures.reactions import Inference

    kwargs = {
        "push_sigma": 0.5,
        "base_rate_up": 0.5,
        "own_touches": 9.0,
        "neighbours": 12,
        "risk_vol": 0.5,
    }
    up = Inference(side=Side.BELOW, probability_up=0.7, expected_push=1.0, **kwargs)
    down = Inference(side=Side.ABOVE, probability_up=0.3, expected_push=-1.0, **kwargs)
    assert up.edge == pytest.approx(-down.edge)
    assert up.edge_for_direction == pytest.approx(down.edge_for_direction)
    assert up.actionable
    assert down.actionable


def test_a_mixed_call_shows_a_probability_below_half_rather_than_hiding_it():
    """Direction from the push, win rate the other way — visible, and not actionable."""
    from till_infinity.structures.reactions import Inference

    call = Inference(
        side=Side.ABOVE,
        probability_up=0.35,
        expected_push=0.9,  # a few large ups against many small downs
        push_sigma=2.0,
        base_rate_up=0.5,
        own_touches=9.0,
        neighbours=12,
    )
    assert call.mixed
    assert call.direction == "up"
    assert call.probability == pytest.approx(0.35)
    assert "mixed" in str(call)
    assert not call.actionable


def test_both_spellings_reach_the_journal():
    """probability_up keeps its meaning for the models; probability is for people."""
    from till_infinity.structures.reactions import Inference

    call = Inference(
        side=Side.ABOVE,
        probability_up=0.23,
        expected_push=-1.4,
        push_sigma=0.8,
        base_rate_up=0.47,
        own_touches=9.0,
        neighbours=12,
    )
    row = call.to_dict()
    assert row["probability_up"] == pytest.approx(0.23)
    assert row["probability_down"] == pytest.approx(0.77)
    assert row["probability"] == pytest.approx(0.77)
    assert row["base_rate"] == pytest.approx(0.53)


def _seed_level(engine, feed, interval, price):
    """Put one level in the engine, the way a formed level would arrive."""
    level = Level(feed=feed, interval=interval, filter=Kalman(mean=price, variance=0.01))
    engine._levels[(feed, interval)] = [level]
    return level


def test_one_visit_is_one_touch_however_long_price_loiters():
    """The counter must measure turns, not time spent in the zone.

    Before this, a resolved interaction left the level immediately eligible: the
    next quote arrived with price still inside the zone and no open touch, so a
    fresh touch began, resolved, and began again. A BTC level reached 316
    "touches" in a day — on an instrument with 288 five-minute bars in one — and
    that swamped the beta-binomial prior badly enough to report p=100%.
    """
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold", "5m")
    for _ in range(120):
        vol.update(2000.0)
    level = _seed_level(engine, "gold", "5m", 2000.0)
    low, high = level.zone(vol)
    inside = (low + high) / 2
    outside = high + (high - low) * 5

    # Two hundred quotes without price ever leaving: one interaction.
    for n in range(200):
        engine.check("gold", "5m", inside, 1_000.0 + n)
    assert level.touches <= 1.0, f"{level.touches} touches from one visit"

    # Leave, come back: that is a second, and it is allowed.
    engine.check("gold", "5m", outside, 2_000.0)
    engine.check("gold", "5m", inside, 2_100.0)
    assert not level.waiting


def test_leaving_the_zone_re_arms_the_level():
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold", "5m")
    for _ in range(120):
        vol.update(2000.0)
    level = _seed_level(engine, "gold", "5m", 2000.0)
    low, high = level.zone(vol)
    level.waiting = True

    engine.check("gold", "5m", high + (high - low) * 5, 1_000.0)
    assert not level.waiting


def _resolved(feed: str, interval: str, push: float) -> reactions.Touch:
    """A resolved touch, the shape `Memory.add` accepts."""
    features = reactions.Features(
        side=Side.ABOVE, approach_vol=1.0, depth_vol=0.5, strength=0.5, run_vol=1.0, experience=0.5
    )
    return reactions.Touch(
        feed=feed,
        level_price=100.0,
        features=features,
        started=0.0,
        entry=100.0,
        extreme=100.0,
        interval=interval,
        outcome=Outcome.REJECT,
        push_vol=push,
        resolved=1.0,
    )


def test_the_base_rate_is_per_series_not_one_number_for_everything():
    """BTC 15m and GBPUSD daily do not share an unconditional drift."""
    memory = reactions.Memory()
    for _ in range(60):
        memory.add(_resolved("btc", "15m", -1.0))
    for _ in range(60):
        memory.add(_resolved("gbpusd", "1d", +1.0))

    btc = memory.base_rate_for("btc", "15m")
    cable = memory.base_rate_for("gbpusd", "1d")
    assert btc < 0.25, btc
    assert cable > 0.75, cable
    # The pooled rate sits between them and is what each was reported as before.
    assert 0.4 < memory.base_rate_up < 0.6


def test_a_thin_series_leans_on_the_pool_rather_than_inventing_a_rate():
    """Three touches is not an estimate of anything."""
    memory = reactions.Memory()
    for _ in range(100):
        memory.add(_resolved("btc", "15m", +1.0))
    for _ in range(3):
        memory.add(_resolved("gold", "1h", -1.0))

    gold = memory.base_rate_for("gold", "1h")
    # Pulled down by its own three, but nowhere near the 0.0 they alone imply.
    assert 0.6 < gold < memory.base_rate_up


def test_an_unknown_series_gets_the_pooled_rate():
    memory = reactions.Memory()
    for _ in range(40):
        memory.add(_resolved("btc", "15m", +1.0))
    assert memory.base_rate_for("eurusd", "4h") == memory.base_rate_up


def test_a_touch_with_no_timeframe_never_lands_in_a_bucket():
    """Hand-built touches must not pollute a series they know nothing about."""
    memory = reactions.Memory()
    for _ in range(30):
        memory.add(_resolved("btc", "", +1.0))
    assert not memory._buckets
    assert memory.base_rate_for("btc", "15m") == memory.base_rate_up


def test_buckets_stay_in_step_with_eviction():
    """The tally is maintained, not derived, so eviction must decrement it."""
    memory = reactions.Memory(capacity=50)
    for _ in range(50):
        memory.add(_resolved("btc", "15m", +1.0))
    for _ in range(50):
        memory.add(_resolved("gold", "1h", -1.0))

    assert sum(n for _ups, n in memory._buckets.values()) == len(memory._touches)
    # BTC aged out entirely rather than leaving a stale count behind.
    assert ("btc", "15m") not in memory._buckets


def test_riding_the_zone_edge_is_not_a_touch_each_time():
    """Leaving the zone is not the same as going away from the level.

    A price sitting on the edge crosses it constantly. Re-arming on each
    crossing counts one consolidation as dozens of turns — the residue of the
    same inflation the `waiting` flag was added for, which the flag alone did
    not reach: a BTC zone still read 337 effective touches after a cold start.
    """
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold", "5m")
    # A moving price, because a still one estimates a volatility near zero and
    # then every distance divided by it is enormous: fed 120 identical prices
    # this read 0.05bps, a hundredth of gold's real 5m move, and the edge of
    # the zone came out **three** volatility units from the level — past
    # `resolve_vol`, so the consolidation this test is about resolved as a
    # three-unit rejection on its first step. The fixture has to be realistic
    # for the assertion to mean what it says.
    rand = random.Random(4)
    price = 2000.0
    for _ in range(200):
        price *= 1 + rand.gauss(0, 0.0005)
        vol.update(price)
    level = _seed_level(engine, "gold", "5m", 2000.0)
    low, high = level.zone(vol)
    inside = (low + high) / 2
    just_outside = high * 1.0000001  # over the edge, nowhere near a unit away
    assert abs(level.distance_vol(just_outside, vol)) < lv.REARM_VOL, (
        "the fixture has to put the edge inside the re-arm distance, or the "
        "test is about resolution rather than about riding the edge"
    )

    for n in range(60):
        engine.check("gold", "5m", inside, 1_000.0 + n * 2)
        engine.check("gold", "5m", just_outside, 1_001.0 + n * 2)
    assert level.touches <= 1.0, f"{level.touches} touches from one consolidation"


def test_the_leg_in_survives_a_pause_and_ends_on_a_run():
    """The origin is where two runs meet, not where one observation paused.

    Ending the leg on the first price that fails to extend makes the origin a
    property of the sampling rate: the finer the timeframe, the sooner some tick
    fails to extend, so the same structure gets a different origin on every
    timeframe and the fusion in confluence spends its precision reconciling the
    sampling rather than the market.
    """
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold", "5m")
    for n in range(300):
        vol.update(2000.0 + (n % 11) * 2.0)  # real movement, so a unit means something
    unit = 2000.0 * vol.bps / 10_000.0
    assert unit > 0

    # A deliberately wide zone, so half-unit steps stay inside it and the touch
    # is not resolved out from under the assertions.
    level = Level(feed="gold", interval="5m", filter=Kalman(mean=2000.0, variance=(2 * unit) ** 2))
    engine._levels[("gold", "5m")] = [level]
    features = reactions.features_for(level, Side.ABOVE, 2000.0, vol, approach_vol=1.0, when=0.0)
    touch = engine.tracker.begin(level, 2000.0, features, 0.0)

    # Arriving from above: deeper means lower.
    engine.tracker.update(level, 2000.0 - 0.4 * unit, vol, 1.0)
    assert touch.origin == pytest.approx(2000.0 - 0.4 * unit)

    # A pause — back off the low by well under a run. Not a departure.
    engine.tracker.update(level, 2000.0 - 0.3 * unit, vol, 2.0)
    assert not touch.turned, "one non-extending observation ended the leg"

    # It resumes deeper, and the origin follows it there.
    engine.tracker.update(level, 2000.0 - 0.8 * unit, vol, 3.0)
    assert touch.origin == pytest.approx(2000.0 - 0.8 * unit)
    assert not touch.turned

    # A real departure — a run's worth back off the low — fixes it.
    engine.tracker.update(level, 2000.0 - 0.2 * unit, vol, 4.0)
    assert touch.turned
    settled = touch.origin

    # And it stays fixed even if price returns.
    engine.tracker.update(level, 2000.0 - 0.9 * unit, vol, 5.0)
    assert touch.origin == pytest.approx(settled)


def test_the_leg_out_ends_when_the_run_does():
    """`departure_vol` is how hard price left, not the biggest thing that
    happened while the touch was open."""
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold", "5m")
    for n in range(300):
        vol.update(2000.0 + (n % 11) * 2.0)
    unit = 2000.0 * vol.bps / 10_000.0

    level = Level(feed="gold", interval="5m", filter=Kalman(mean=2000.0, variance=(3 * unit) ** 2))
    engine._levels[("gold", "5m")] = [level]
    features = reactions.features_for(level, Side.ABOVE, 2000.0, vol, approach_vol=1.0, when=0.0)
    touch = engine.tracker.begin(level, 2000.0, features, 0.0)

    engine.tracker.update(level, 2000.0 - 0.5 * unit, vol, 1.0)  # the low: the origin
    engine.tracker.update(level, 2000.0 + 0.3 * unit, vol, 2.0)  # a run out, and it turns
    assert touch.turned
    left = touch.departure_vol
    assert left > 0

    # Price gives back a run's worth: the leg out is over.
    engine.tracker.update(level, 2000.0 - 0.4 * unit, vol, 3.0)
    assert touch.departure_done

    # A later, larger move is not this reaction's departure.
    engine.tracker.update(level, 2000.0 + 2.0 * unit, vol, 4.0)
    assert touch.departure_vol == pytest.approx(left)


def test_an_edge_smaller_than_the_cost_is_not_a_trade():
    """Every push in this system is gross. A +0.5v edge against a 0.3v spread
    is a rounding error with a direction attached."""
    from till_infinity.structures.reactions import Inference

    shared = {
        "side": Side.BELOW,
        "probability_up": 0.72,
        "push_sigma": 0.5,
        "base_rate_up": 0.5,
        "own_touches": 9.0,
        "neighbours": 12,
        # Well inside the move, so the risk gate is not what these assert.
        "risk_vol": 0.4,
    }
    free = Inference(expected_push=0.6, **shared)
    assert free.actionable
    assert free.net_push == pytest.approx(0.6)

    costly = Inference(expected_push=0.6, cost_vol=0.3, **shared)
    assert costly.net_push == pytest.approx(0.3)
    assert not costly.actionable, "an edge inside the spread reached the channel"


def test_a_cost_bigger_than_the_edge_flips_it_through_zero():
    """Not a weak trade — the wrong side of one."""
    from till_infinity.structures.reactions import Inference

    call = Inference(
        side=Side.BELOW,
        probability_up=0.72,
        expected_push=0.4,
        push_sigma=0.5,
        base_rate_up=0.5,
        own_touches=9.0,
        neighbours=12,
        cost_vol=0.9,
    )
    assert call.net_push < 0
    assert not call.actionable


def test_reward_to_risk_is_measured_after_the_cost():
    from till_infinity.structures.reactions import Inference

    call = Inference(
        side=Side.BELOW,
        probability_up=0.72,
        expected_push=1.0,
        push_sigma=0.5,
        base_rate_up=0.5,
        own_touches=9.0,
        neighbours=12,
        risk_vol=0.5,
        cost_vol=0.25,
    )
    assert call.reward_to_risk == pytest.approx(1.5)  # (1.0 - 0.25) / 0.5


def test_the_quoted_spread_reaches_the_call_as_a_cost():
    """The netting was inert until something measured filled cost_vol."""
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold", "5m")
    for n in range(300):
        vol.update(2000.0 + (n % 11) * 2.0)

    assert engine.cost_of("gold", vol) == 0.0  # nothing quoted yet

    for _ in range(60):
        engine.observe_quote(
            {"feed": "gold", "venue": "OANDA", "mid": 2000.0, "spread_bps": 4.0, "time": 1.0}
        )
    cost = engine.cost_of("gold", vol)
    assert cost == pytest.approx(4.0 / vol.bps, rel=0.05)
    assert cost > 0


def test_a_single_wide_print_does_not_disqualify_an_edge():
    """Smoothed on purpose: the cost that matters is what this normally costs."""
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold", "5m")
    for n in range(300):
        vol.update(2000.0 + (n % 11) * 2.0)

    for _ in range(60):
        engine.observe_quote(
            {"feed": "gold", "venue": "OANDA", "mid": 2000.0, "spread_bps": 2.0, "time": 1.0}
        )
    settled = engine.cost_of("gold", vol)
    engine.observe_quote(
        {"feed": "gold", "venue": "OANDA", "mid": 2000.0, "spread_bps": 200.0, "time": 2.0}
    )
    spiked = engine.cost_of("gold", vol)
    # A median over the window: one print out of sixty-one cannot move it at
    # all, which is the property, not a tolerance chosen to pass.
    assert spiked == pytest.approx(settled)


def test_a_call_knows_what_being_wrong_costs():
    """`risk_vol` was 0.0 on every level call ever journalled.

    `vol` was an optional argument to `infer` with a zero fallback, so the risk
    geometry was something a caller could forget — and every caller did, though
    each had `vol` right there in scope. `reward_to_risk` is documented as the
    number that decides whether an edge is worth taking, and it was identically
    zero. Nothing gates on it, which is the only reason it stayed invisible:
    zero looks like a number, not like an omission.
    """
    vol = _vol()
    tracker = reactions.Tracker()
    level = Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(level, Side.ABOVE, 4400.0, vol)

    found = reactions.infer(level, Side.ABOVE, features, tracker.memory, vol, price=4400.0)

    assert found.risk_vol > 0.0
    # The definition, not a tolerance: distance from here to the stop, and the
    # ratio is what the expected move is worth against it.
    assert found.risk_vol == pytest.approx(level.risk_vol(Side.ABOVE, 4400.0, vol))
    assert found.reward_to_risk == pytest.approx(abs(found.net_push) / found.risk_vol)


def test_reward_to_risk_no_longer_decides_anything():
    """It was a gate until 2026-08-17, and it was losing money.

    Gating at `reward_to_risk >= 1.0` turned a mean realised push of +0.496
    into **-0.268** across 11,113 calls, because the ratio is substantially a
    measure of how *tight* the stop is: it correlates -0.359 with `risk_vol`,
    and top-decile calls were stopped out 44.8% of the time against 29.1%.

    The number is still computed and still reported — a human reading an alert
    should see what the move is worth against what it risks. It just does not
    decide any more.
    """
    shared = {
        "side": Side.BELOW,
        "probability_up": 0.72,
        "push_sigma": 0.5,
        "base_rate_up": 0.5,
        "own_touches": 9.0,
        "neighbours": 12,
        "expected_push": 1.0,
    }
    worth_it = reactions.Inference(risk_vol=0.5, **shared)
    not_worth_it = reactions.Inference(risk_vol=2.0, **shared)

    # Still computed, still different.
    assert worth_it.reward_to_risk == pytest.approx(2.0)
    assert not_worth_it.reward_to_risk == pytest.approx(0.5)
    # Everything else about the two calls is identical, so if the ratio still
    # gated, these would differ. They must not.
    assert worth_it.edge == not_worth_it.edge
    assert worth_it.net_push == not_worth_it.net_push
    assert worth_it.actionable == not_worth_it.actionable
    assert worth_it.actionable

    # And a ratio far below the old threshold cannot block a call on its own.
    hopeless = reactions.Inference(risk_vol=50.0, **shared)
    assert hopeless.reward_to_risk < 0.05
    assert hopeless.actionable


def test_the_risk_gate_is_a_ratio_so_it_travels_across_timeframes():
    """`risk_vol` is in each timeframe's own units and must not be compared.

    0.90 volatility units is $0.77 on 15m gold and $24.76 on the daily. The
    ratio divides those units out, which is why the gate is on the ratio and
    not on the risk.
    """
    shared = {
        "side": Side.BELOW,
        "probability_up": 0.72,
        "push_sigma": 0.5,
        "base_rate_up": 0.5,
        "own_touches": 9.0,
        "neighbours": 12,
    }
    # A small move against a small stop, and a large move against a large one.
    fine = reactions.Inference(expected_push=0.8, risk_vol=0.4, **shared)
    coarse = reactions.Inference(expected_push=8.0, risk_vol=4.0, **shared)

    assert fine.reward_to_risk == pytest.approx(coarse.reward_to_risk)
    assert fine.actionable
    assert coarse.actionable


def test_the_risk_geometry_cannot_be_forgotten():
    """Requiring `vol` is the fix; a default would let the omission return."""
    vol = _vol()
    tracker = reactions.Tracker()
    level = Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(level, Side.ABOVE, 4400.0, vol)

    with pytest.raises(TypeError):
        reactions.infer(level, Side.ABOVE, features, tracker.memory)


def test_warming_reports_progress_rather_than_going_quiet(tmp_path):
    """A cold start replays six-figure bar counts and used to say nothing.

    Minutes of a service whose only honest reading was "possibly hung", which
    is the same failure as a gate that declines silently: the work being
    correct and the work being dead look identical from outside.
    """
    import sqlite3

    db = tmp_path / "prices.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE bars (feed TEXT, venue TEXT, interval TEXT, ts REAL,"
        " high REAL, low REAL, close REAL)"
    )
    rows = [
        ("gold", venue, "5m", float(n * 300), 2001.0, 1999.0, 2000.0 + (n % 7))
        for n in range(120)
        for venue in ("OANDA", "SAXO", "FOREXCOM")
    ]
    conn.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    seen: list[tuple[int, int]] = []
    replayed = Engine().seed(db, on_progress=lambda done, total: seen.append((done, total)))

    assert replayed == len(rows)
    assert seen, "warming reported nothing at all"
    # Monotonic, and it finishes at the total rather than stopping short.
    assert [d for d, _t in seen] == sorted(d for d, _t in seen)
    assert seen[-1] == (replayed, replayed)


def test_state_from_an_older_build_restores_without_losing_new_fields():
    """Unpickling never calls __init__, so new attributes are simply absent.

    This took structures down in production: the deploy restored its models,
    hit `AttributeError: 'Engine' object has no attribute '_touch_eras'` on the
    first bar five seconds later, and stopped. Nothing then consumed the bus,
    so it presented as dropped quotes and a silent journal — never as the
    attribute error that caused it.

    The property is that a state file missing *any* field still restores a
    working engine, not that these two particular names are handled.
    """
    saved = Engine().__dict__.copy()
    for added_since in ("_touch_eras", "charge_spread"):
        saved.pop(added_since, None)

    restored = Engine.__new__(Engine)
    restored.__setstate__(saved)

    # The two calls that ran on every bar and every quote respectively.
    assert restored.touch_interval("gold", 1.0)
    assert restored.cost_of("gold", None) == 0.0
    assert restored.charge_spread is True


def test_a_pickle_round_trip_keeps_what_was_learned():
    """Restoring must not quietly reset the engine to a default one."""
    engine = Engine(intervals=("5m",))
    engine.series("gold", "5m")
    engine.calls = 17

    back = pickle.loads(pickle.dumps(engine))
    assert back.calls == 17
    assert ("gold", "5m") in back._series
    assert back.intervals == ("5m",)


def test_the_touch_source_gets_finer_as_history_allows():
    """Venues keep years of 1w and days of 1m, so "finest" changes with time."""
    rows = [
        {"interval": "1d", "time": 0.0},
        {"interval": "1w", "time": -500.0},
        {"interval": "1d", "time": 900.0},
        {"interval": "1m", "time": 800.0},
    ]
    assert Engine._eras(rows) == [(-500.0, "1w"), (0.0, "1d"), (800.0, "1m")]


def test_early_history_is_touched_by_the_finest_thing_that_existed_then():
    """The regression that pinning to the globally finest series caused.

    A replay of a few hundred bars per interval covers hours at 1m and years
    at 1w. Pinning the check to 1m left every earlier era untouched — 1w and 4h
    opened zero touches across 20,159 gold bars, so their levels were pruned
    for never having been visited and twenty-one levels became four.

    The property is that no era goes untouched: every point in the replay has
    some interval carrying the check, and before the fine series begins that
    has to be a coarse one.
    """
    engine = Engine()
    engine._touch_eras = [(0.0, "1w"), (1_000.0, "1m")]

    # Before the 1m series starts, 1w carries it — this is what was broken.
    assert engine.touch_interval("gold", 10.0) == "1w"
    assert engine.touch_interval("gold", 999.0) == "1w"
    # Once it starts, it takes over and the coarse bars stop touching.
    assert engine.touch_interval("gold", 1_000.0) == "1m"
    assert engine.touch_interval("gold", 50_000.0) == "1m"


def test_live_the_touch_source_is_the_finest_series_seen():
    """No eras outside a replay: live, every interval is streaming at once."""
    engine = Engine(intervals=("5m", "1h"))
    engine.series("gold", "1h")
    assert engine.touch_interval("gold") == "1h"
    engine.series("gold", "5m")
    assert engine.touch_interval("gold") == "5m"


def _quoted_engine(*, charge_spread: bool) -> tuple[Engine, object]:
    engine = Engine(intervals=("5m",), charge_spread=charge_spread)
    vol = engine.vol.of("gold", "5m")
    for n in range(300):
        vol.update(2000.0 + (n % 11) * 2.0)
    for _ in range(60):
        engine.observe_quote(
            {"feed": "gold", "venue": "OANDA", "mid": 2000.0, "spread_bps": 4.0, "time": 1.0}
        )
    return engine, vol


def test_the_spread_charge_can_be_turned_off():
    """Off is for asking what the model would have said gross, and nothing else.

    Charged and uncharged runs differ in this one term, which is what makes the
    comparison worth anything — so the test pins that the *same* quotes and the
    *same* volatility produce a real cost with it on and exactly zero with it
    off.
    """
    on, vol_on = _quoted_engine(charge_spread=True)
    off, vol_off = _quoted_engine(charge_spread=False)

    assert on.cost_of("gold", vol_on) == pytest.approx(4.0 / vol_on.bps, rel=0.05)
    assert off.cost_of("gold", vol_off) == 0.0
    # The spreads were still observed either way — the switch decides whether
    # they are charged, not whether they are measured, so turning it back on
    # must not need a fresh window.
    off.charge_spread = True
    assert off.cost_of("gold", vol_off) == pytest.approx(on.cost_of("gold", vol_on))


def test_disabling_the_charge_says_so_rather_than_going_quiet(caplog):
    """A configured zero must not read like a broken one.

    Both present as `cost_vol: 0.0` in the journal, and the whole reason the
    cost was found to be inert in production is that nothing distinguished
    them.
    """
    with caplog.at_level("WARNING"):
        Engine(intervals=("5m",), charge_spread=False)
    assert any("spread costs disabled" in record.message for record in caplog.records)

    caplog.clear()
    with caplog.at_level("WARNING"):
        Engine(intervals=("5m",))
    assert not any("spread costs disabled" in record.message for record in caplog.records)


# ------------------------------------------------------------ the price grid


def test_the_tick_is_measured_from_the_series():
    """`structures` has no other route to it — `prices` sees quotes and stops."""
    vol = Volatility()
    price = 0.18
    for step in [3, -2, 1, -1, 5, -3, 2, -1, 1, 4] * 6:
        price = round(price + step * 0.0001, 6)
        vol.update(price)
    assert vol.tick == pytest.approx(0.0001)


def test_a_series_that_only_jumps_teaches_nothing_about_the_grid():
    """The degenerate case, and the reason the obvious test is wrong.

    If every change is the same size, "the tick is that size" and "the tick is
    tiny and price is jumping" fit equally. Taking the first would widen every
    zone on the instrument by that jump.
    """
    vol = Volatility()
    price = 4400.0
    for _ in range(200):
        price *= 1 + 5 / 10_000  # every change identical
        vol.update(price)
    assert vol.tick == 0.0


def test_a_coarse_grid_is_still_believed():
    """The case the tempting guard threw away.

    On ADA the tick genuinely *is* most of a typical move — that is the whole
    problem — so "the tick must be small against a typical move" rejects the
    instrument this exists for. Distinct multiples separate them instead.
    """
    vol = Volatility()
    price = 0.18
    for step in [1, -1, 2, -1, 3, -2, 1, 1, -1, 2] * 6:
        price = round(price + step * 0.0001, 6)
        vol.update(price)
    assert vol.tick == pytest.approx(0.0001)
    # And it is a large fraction of a typical move, which is the point.
    assert vol.tick / (vol.bps / 10_000 * price) > 0.3


def test_a_coarse_grid_widens_the_zone_beyond_the_volatility_floor():
    """A band tighter than the price grid is a rounding boundary, not a zone.

    The widening is bounded by `MAX_ZONE_VOL` rather than granted outright,
    because the tick is an *observed* minimum and errs large. What the test
    pins is that the grid raises the floor at all — without it the zone would
    sit at the volatility floor, narrower than the prices that can be quoted.
    """
    vol = Volatility()
    price = 75.0
    for step in [1, -1, 2, -1, 3, -2, 1, 1, -1, 2] * 6:
        price = round(price + step * 0.01, 6)
        vol.update(price)

    level = Level(feed="sol", interval="3m", filter=Kalman(mean=price, variance=1e-18))
    low, high = level.zone(vol)

    assert vol.tick == pytest.approx(0.01)
    # The grid floor is the binding one here, so the zone is wider than
    # volatility alone would have made it.
    assert vol.tick * lv.MIN_ZONE_TICKS > vol.price_units(price, lv.MIN_ZONE_VOL)
    assert (high - low) > 2 * vol.price_units(price, lv.MIN_ZONE_VOL)


def test_an_instrument_quoted_finely_is_left_alone():
    """btc's tick is 1% of a minimum zone, so the volatility floor still binds.

    The moves have to be realistic for the price or the test proves nothing:
    steps of one tick on a 63,000 instrument put volatility on its own floor,
    at which point the grid binds for a reason that has nothing to do with the
    grid. Real btc measures 4.94bps, which is a few hundred ticks.
    """
    vol = Volatility()
    price = 63_000.0
    # Large moves with the occasional single-tick print, which is what a real
    # series looks like — and what lets the tick be resolved at all.
    for step in [250, -200, 1, 300, -150, -1, 400, -260, 1, 180, 220, -190] * 5:
        price = round(price + step * 0.12, 6)
        vol.update(price)

    level = Level(feed="btc", interval="3m", filter=Kalman(mean=price, variance=1e-18))
    low, high = level.zone(vol)

    assert vol.tick == pytest.approx(0.12)
    # A tick this fine cannot reach the volatility floor, so nothing changes.
    assert vol.tick * lv.MIN_ZONE_TICKS < vol.price_units(price, lv.MIN_ZONE_VOL)
    assert (high - low) == pytest.approx(2 * vol.price_units(price, lv.MIN_ZONE_VOL))


def test_a_bar_is_observed_at_its_close_not_its_open():
    """Bars are stamped with the open; quotes carry wall clock. One tracker.

    A touch opened by a quote and resolved by the bar that closed *after* it
    recorded a negative duration — 10% of resolved touches in the journal,
    every one 5m, every one about 300 seconds, which is exactly one bar. The
    duration itself is cosmetic. What is not is that `horizon`, `trap_window`
    and the `GAP_FACTOR` weekend guard all test `when - touch.started`, and a
    negative elapsed satisfies none of them: a touch that should have chopped
    out, converted to a break, or been discarded as a gap instead stays open.
    """
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)

    seen: list[float] = []
    original = engine.check
    engine.check = lambda *a, **k: (seen.append(a[3]), original(*a, **k))[1]

    opened = 2_000_000
    for bar in _bar("gold", "5m", opened, 4425.0):
        engine.observe_bar(bar)

    assert seen, "the bar never reached a touch check"
    assert all(when == opened + 300 for when in seen), (
        "a 5m bar was observed at its open time, which is 300 seconds before "
        "anyone could have known it"
    )


def test_a_quote_and_the_bar_that_follows_it_agree_on_which_came_first():
    """The invariant the two clocks broke: elapsed time is never negative."""
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)

    level = engine.levels("gold", "5m")[0]
    vol = engine.vol.of("gold", "5m")
    features = reactions.features_for(level, Side.ABOVE, level.price, vol)

    # A quote opens the touch partway through the bar, at wall clock.
    started = 2_000_000 + 250
    engine.tracker.begin(level, level.price, features, started)
    # The bar covering that quote opens at 2_000_000 and closes at +300.
    for bar in _bar("gold", "5m", 2_000_000, level.price * 1.02):
        engine.observe_bar(bar)

    touch = engine.tracker.open_touch(level)
    resolved = [t for _, t in engine._resolved if t.started == started]
    for done in resolved:
        assert done.resolved >= done.started, "a touch resolved before it began"
    assert touch is None or touch.started == started


@pytest.mark.parametrize("venues", [3, 4, 5, 6])
def test_volatility_does_not_depend_on_how_many_venues_report(venues):
    """The estimate is per bar. It was per venue row, and that divided it.

    `Consensus.observe` answers again on every venue that reports a bar, on
    purpose, so the median improves within a sweep instead of waiting for a
    venue that may never arrive. `Series.add` handles the repeat by
    overwriting. The volatility estimate had no such handling: it folded the
    same close in once per venue and read a run of zero returns.

    Measured on the live feeds, that divided the estimate by the venue count
    past quorum — four on EURUSD and GBPUSD, three on XAUUSD, two on BTCUSD —
    and since every threshold here is expressed in volatility units, and a
    distance in those units *divides* by this number, every distance read two
    to four times larger than it was. A level 0.4 volatility units away
    presented as 1.6, which is past `resolve_vol`: an arrival recorded as a
    rejection having observed nothing.
    """
    names = ("a", "b", "c", "d", "e", "f")[:venues]
    engine = Engine(intervals=("5m",))
    rand = random.Random(11)
    price, when = 4425.0, 1_000_000
    for i in range(700):
        price *= 1 + rand.gauss(0, 0.0012)
        for venue in names:
            engine.observe_bar(
                {
                    "feed": "gold",
                    "venue": venue,
                    "interval": "5m",
                    "time": when + i * 300,
                    "high": price * 1.001,
                    "low": price * 0.999,
                    "close": price,
                }
            )

    assert engine.vol.of("gold", "5m").bps == pytest.approx(9.31, abs=0.05)


def test_a_corrected_bar_does_not_count_as_a_second_observation():
    """The narrow version of the same invariant, without the venue machinery."""
    series = Engine(intervals=("5m",)).series("gold", "5m")
    assert series.add(1_000_000, 10.0, 9.0, 9.5) is True
    assert series.add(1_000_000, 11.0, 9.0, 10.5) is False, "a correction read as a new bar"
    assert series.add(1_000_300, 11.0, 9.0, 10.5) is True
    assert list(series.closes) == [10.5, 10.5]  # the correction replaced, not appended


def test_a_touch_arriving_at_the_far_edge_is_not_born_resolved():
    """The zone reaches MAX_ZONE_VOL; a rejection needs only resolve_vol.

    Those two are independent numbers, and the first is twice the second, so
    price clipping the far edge of a wide zone used to open a touch that was
    *already* past the rejection threshold. The next observation closed it as
    a REJECT having watched nothing happen — 17% of touches in a replay of the
    stored bars, spread evenly across all six instruments, and on the
    production journal 46% of outcomes resolved at or before the instant they
    opened.

    Measuring the leg out from the origin — where the leg in ended, which
    `Level.zone` already calls the price the level is drawn at — makes the two
    independent. A touch must now *move*, whatever width it arrived through.
    """
    vol = _vol()
    tracker = reactions.Tracker(horizon_bars=12)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    edge = 4400.0 * (1 + 2.5 * vol.bps / 10_000)  # inside the zone, past resolve_vol
    assert abs(level.distance_vol(edge, vol)) > tracker.resolve_vol, "fixture is not the case"

    features = reactions.features_for(level, Side.ABOVE, edge, vol)
    tracker.begin(level, edge, features, when=1_000_000)
    # Price holds where it arrived. Nothing has happened, so nothing resolves.
    assert tracker.update(level, edge, vol, when=1_000_060) is None
    assert tracker.open_touch(level) is not None, "an arrival was recorded as a reaction"

    # It resolves once it has actually travelled, measured from where it came in.
    away = 4400.0 * (1 + (2.5 + tracker.resolve_vol + 0.1) * vol.bps / 10_000)
    done = tracker.update(level, away, vol, when=1_000_120)
    assert done is not None
    assert done.outcome is Outcome.REJECT


def test_a_touch_that_expires_reaches_the_level_and_the_journal():
    """A touch ends two ways, and only one of them was being delivered.

    `Tracker.expire` closes a touch on the clock, gives it an outcome and folds
    it into the kNN memory — and `Engine.check` discarded what it returned, so
    that memory was the only place it ever reached. No `level.record`, no
    Kalman update, nothing appended to `_resolved`, so nothing in the journal
    and nothing in `facto`.

    It matters far past the count, because expiry is where a break that got
    through and then went quiet resolves. On a replay of the stored bars,
    delivering these took breaks from 11 to 61 and back checks from 3 to 29 —
    the second because `level.broke_at` is what makes a retest detectable, and
    it was only ever set on the path that already worked.
    """
    engine = Engine(intervals=("5m",))
    vol = engine.vol.of("gold", "5m")
    rand = random.Random(7)
    price = 2000.0
    for _ in range(200):
        price *= 1 + rand.gauss(0, 0.0005)
        vol.update(price)
    level = _seed_level(engine, "gold", "5m", 2000.0)
    features = reactions.features_for(level, Side.ABOVE, 2000.0, vol)
    engine.tracker.begin(level, 2000.0, features, when=1_000_000)

    before = len(engine._resolved)
    # Well past horizon * 2, and short of the gap factor that would discard it.
    engine.check("gold", "5m", 2000.0, 1_000_000 + engine.tracker.horizon * 3)

    assert engine.tracker.open_touch(level) is None, "the touch never closed"
    assert len(engine._resolved) == before + 1, "an expired touch reached nothing downstream"
    resolved_level, touch = engine._resolved[-1]
    assert resolved_level is level
    assert touch.outcome is Outcome.CHOP  # it went nowhere, which is what chop is
    assert level.touches > 0, "the level's own statistics never saw it"


def test_a_change_of_quoting_venue_is_not_a_price_move():
    """Bars got a cross-venue median; quotes did not, and needed it more.

    `check` was called with whichever venue published last, and venues do not
    agree on the price. Measured over a five second window: 6.12bps between
    venues on US500 and 5.74 on BTCUSD, which in each instrument's own
    volatility units is 3.46 and 1.09 against a `resolve_vol` of 1.5. So two
    consecutive quotes from different venues looked like a three-and-a-half
    unit move, opening and closing a touch between them.

    It is why spx500 and btc led the instant-resolution table at 41% and 39%
    while gold and the FX majors, whose venues agree to within a twentieth of a
    unit, sat near zero — and why the rate stayed at 43% on production after
    the bar path was fixed.
    """
    from till_infinity.structures.engine import QUOTE_STALE, Quotes

    book = Quotes()
    # Three venues on the same instrument, one of them a long way out.
    assert book.observe("spx500", "a", 1_000.0, 7739.0) == 7739.0  # alone, so itself
    assert book.observe("spx500", "b", 1_000.1, 7741.0) == pytest.approx(7740.0)
    agreed = book.observe("spx500", "c", 1_000.2, 7739.5)
    assert agreed == 7739.5, "the median should ignore the outlier, not average it in"

    # The outlier quoting again does not move the agreed price.
    assert book.observe("spx500", "b", 1_000.3, 7741.0) == 7739.5

    # A venue that stops quoting drops out rather than anchoring the median for
    # ever, which would make the consensus lag every live venue on a fast move.
    later = 1_000.0 + QUOTE_STALE + 1
    assert book.observe("spx500", "a", later, 7800.0) == 7800.0

    # And instruments do not bleed into each other.
    assert book.observe("btc", "a", 1_000.0, 63_000.0) == 63_000.0


def test_a_bar_still_forming_is_not_observed_in_the_future():
    """The other half of the clock fix, and the half that made things worse.

    Stamping a bar at its close is right for a bar that has closed. The bar
    being delivered is usually the one still forming, and stamping *that* one
    at its close puts it up to a whole interval ahead of now — so a quote
    arriving in the meantime resolves a touch before it began, which is the
    negative duration the close-time stamp was introduced to remove.

    Production took negatives from 1.7% of outcomes to 5.7% on that change,
    and at -98, -98, -98, -7 and -1 seconds across 3m, 5m and 15m: partial
    intervals, which is a partly-formed bar rather than the clean one-bar skew
    that came before.
    """
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)

    seen: list[float] = []
    original = engine.check
    engine.check = lambda *a, **k: (seen.append(a[3]), original(*a, **k))[1]

    now = time.time()
    # A 5m bar that opened one minute ago: four minutes of it have not happened.
    opened = int(now) - 60
    for bar in _bar("gold", "5m", opened, 4425.0):
        engine.observe_bar(bar)

    assert seen, "the bar never reached a touch check"
    assert all(when <= now + 1 for when in seen), (
        "a forming bar was observed at its close, which has not happened yet"
    )
    # And it is still the close that is used once the bar really has closed.
    seen.clear()
    old = int(now) - 86_400
    for bar in _bar("gold", "5m", old, 4425.0):
        engine.observe_bar(bar)
    assert all(when == old + 300 for when in seen), "a closed bar lost its close time"


def test_a_market_that_has_shut_opens_no_new_touches():
    """Quotes keep arriving after a market closes; price stops.

    On a Saturday morning the FX venues were still answering every poll —
    quotes sixteen minutes old — while the last 3m bar was nine hours old.
    Those quotes carry Friday's closing price, and a frozen price cannot
    arrive anywhere. Without this the engine opened touches against it and
    published directional calls: USDCNH and AUDUSD both alerted on a Saturday,
    one of them `down 97%` on a market where nothing could move.
    """
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)
    level = engine.levels("gold", "5m")[0]
    last = engine.series("gold", "5m").times[-1]

    # A quote arriving one bar after the last one is an ordinary live market.
    assert engine.trading("gold", last + 300)
    assert engine.check("gold", "5m", level.price, last + 300) or True
    assert engine.tracker.open_touch(level) is not None, "a live market opened nothing"

    # A weekend: bars stopped hours ago, quotes did not.
    engine.tracker._open.clear()
    level.waiting = False
    shut = last + lv.SECONDS["5m"] * (STALE_BARS + 10)
    assert not engine.trading("gold", shut)
    calls = engine.check("gold", "5m", level.price, shut)
    assert not calls, "a shut market produced a directional call"
    assert engine.tracker.open_touch(level) is None, "a shut market opened a touch"


def test_an_expired_touch_holds_the_level_back():
    """Otherwise the same visit is counted again on the next observation.

    A touch expires because price sat at the level and went nowhere — so price
    is still there. Leaving the level re-armed opened another touch against
    that same visit immediately, producing another call and another alert. On a
    closed market, where the price is frozen and nothing can ever resolve, that
    is a loop rather than a duplicate.
    """
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)
    level = engine.levels("gold", "5m")[0]
    vol = engine.vol.of("gold", "5m")
    features = reactions.features_for(level, Side.ABOVE, level.price, vol)
    engine.tracker.begin(level, level.price, features, when=1_000_000)

    engine._drain_expired(1_000_000 + engine.tracker.horizon * 3)

    assert engine.tracker.open_touch(level) is None
    assert level.waiting, "the level re-armed on the visit that had just expired"


def test_a_levels_own_record_reaches_the_features():
    """The one measured addition, and the one thing that was never handed over.

    research/features.md found that none of the other eight features predicts
    direction once `side` is known, while the level's own same-side record —
    which was not among them — is worth +0.024 AUC on levels with three or
    more prior touches. It was hiding inside `strength`, diluted with terms
    that separate nothing, and behind `experience`, which counts touches
    without saying what they did.
    """
    vol = _vol()
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))

    # No history reads as 0.5 — not knowing rather than an even split. The pair
    # with `experience` is what tells them apart.
    fresh = reactions.features_for(level, Side.ABOVE, 4400.0, vol)
    assert fresh.up_rate == 0.5
    assert fresh.experience == 0.0

    # Three touches from above that all pushed up.
    for _ in range(3):
        level.record(Side.ABOVE, Outcome.REJECT, 1.2, 1_000_000)
    assert reactions.features_for(level, Side.ABOVE, 4400.0, vol).up_rate == 1.0

    # The other side is untouched and says so, which is the whole point of
    # keeping the record per side.
    assert reactions.features_for(level, Side.BELOW, 4400.0, vol).up_rate == 0.5

    # One down among four.
    level.record(Side.ABOVE, Outcome.BREAK, -1.5, 1_000_000)
    assert reactions.features_for(level, Side.ABOVE, 4400.0, vol).up_rate == pytest.approx(0.75)


def test_the_record_is_read_before_this_touch_is_added_to_it():
    """Otherwise the feature contains its own answer.

    `features_for` runs before `Tracker.begin`, and `record` is only called by
    `_close`, so a touch is never in its own denominator. This pins that
    ordering, because it is the sort of thing a refactor breaks silently and
    the symptom would be a model that looks excellent and predicts nothing.
    """
    vol = _vol()
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)
    level = engine.levels("gold", "5m")[0]

    for _ in range(4):
        level.record(Side.ABOVE, Outcome.REJECT, 1.0, 1_000_000)
    before = reactions.features_for(level, Side.ABOVE, level.price, vol).up_rate

    features = reactions.features_for(level, Side.ABOVE, level.price, vol)
    touch = engine.tracker.begin(level, level.price, features, when=1_000_000)

    assert touch.features.up_rate == before, "the touch saw a record it had already changed"


def test_similar_records_are_nearer_than_opposite_ones():
    """`up_rate` earns its place in the distance as well as in the model.

    Measured over a replay of the stored bars, adding it takes the neighbour
    vote's AUC from 0.797 to 0.813. Unweighted, like every other dimension.
    """
    base = {
        "approach_vol": 1.0,
        "depth_vol": 0.2,
        "strength": 0.5,
        "run_vol": 1.0,
        "experience": 0.5,
        "pivot": 0.0,
        "backcheck": 0.0,
        "regime": 0.5,
    }
    holds = reactions.Features(side=Side.ABOVE, up_rate=0.9, **base)
    also_holds = reactions.Features(side=Side.ABOVE, up_rate=0.85, **base)
    breaks = reactions.Features(side=Side.ABOVE, up_rate=0.1, **base)

    assert holds.distance(also_holds) < holds.distance(breaks)
    # And side is still a hard constraint rather than another dimension.
    assert holds.distance(reactions.Features(side=Side.BELOW, up_rate=0.9, **base)) == math.inf


def test_a_coarse_grid_cannot_make_a_zone_wider_than_a_resolution():
    """The floor that stopped price crossing a zone in a few ticks overshot.

    `MIN_ZONE_TICKS` is six, which is sensible while a tick is a small part of
    a typical move. On sol a tick is 0.378 volatility units, so six of them is
    2.27 — wider than `resolve_vol`, the distance a touch must travel to count
    as a rejection. The zone then catches everything: sol 3m produced 582
    outcomes per thousand bars against btc 3m's 62.8, a resolution every 1.7
    bars, and sol alone was half of every outcome in the journal.

    That is the concentration gating `fit`, and it is geometry rather than a
    sampling problem, so it is fixed here rather than worked around there.
    """

    class Coarse(Volatility):
        """sol's grid: a tick worth a third of a typical move."""

        @property
        def tick(self) -> float:
            return self.price_units(75.0, 0.378)

    coarse = Coarse()
    for _ in range(200):
        coarse.update(75.0 * (1 + _vol().bps / 10_000))

    level = Level(feed="sol", interval="3m", filter=Kalman(mean=75.0, variance=1e-9))
    _low, high = level.zone(coarse)
    half_vol = abs(level.distance_vol(high, coarse))

    assert half_vol <= lv.GRID_ZONE_VOL + 0.01, (
        f"the grid alone opened a {half_vol:.2f}v zone; six ticks is "
        f"{6 * 0.378:.2f}v and nothing bounded it"
    )
    # And it stays under the distance that resolves a touch, which is the point.
    assert half_vol < reactions.Tracker().resolve_vol

    # A finely quoted instrument is untouched: its grid never reaches the bound.
    fine = _vol()
    btc = Level(feed="btc", interval="3m", filter=Kalman(mean=63000.0, variance=1e-6))
    assert abs(btc.distance_vol(btc.zone(fine)[1], fine)) == pytest.approx(
        lv.MIN_ZONE_VOL, abs=0.05
    ), "the floor moved for an instrument whose grid was never the problem"


def test_a_grid_too_coarse_for_a_zone_forms_no_levels():
    """Some instrument and timeframe pairs cannot carry a level at all.

    A level is a band price is meant to enter, react inside and leave. When the
    venue's tick is a large fraction of a typical move, price cannot be inside
    it — it jumps across, and every crossing is a touch. On the instance
    `sol 3m` fits 2.5 ticks in a zone and `audusd 1m` fits 2.7, against
    `btc 5m`'s 170, and sol alone was half of every outcome in the journal.

    Both ends of this are bad and `GRID_ZONE_VOL` only fixes one: it stops a
    coarse grid opening an absurdly wide zone. What is left is a zone two or
    three ticks across, which is the failure `MIN_ZONE_TICKS` was added for.
    No width works, so the pair is declined.
    """
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)
    assert engine.levels("gold", "5m"), "the fixture instrument should be fine"
    assert engine.supports("gold", "5m")

    vol = engine.vol.of("gold", "5m")

    class Coarse(Volatility):
        """A tick worth a third of a typical move, which is sol's grid."""

        @property
        def tick(self) -> float:
            return self.price_units(4425.0, 0.38)

    coarse = Coarse()
    for _ in range(200):
        coarse.update(4425.0 * (1 + vol.bps / 10_000))
    engine.vol._by_key[("gold", "5m")] = coarse

    assert not engine.supports("gold", "5m"), "a two-tick zone should be declined"

    # Reforming drops what was formed on the bad geometry rather than leaving
    # it to age out, because it was never a level.
    series = engine.series("gold", "5m")
    assert engine.reform(series, when=series.times[-1]) == []
    assert engine.levels("gold", "5m") == []
    assert ("gold", "5m") in engine._declined


def test_an_instrument_with_no_evidence_yet_is_not_declined():
    """Missing evidence is not evidence of a problem.

    `tick` is measured rather than configured and only shrinks as data arrives,
    so an instrument that has not yet printed a single-step move reads coarser
    than it is. Declining on that would refuse every instrument for its first
    hour and then never revisit, since a declined pair forms nothing to learn
    from.
    """
    engine = Engine(intervals=("5m",))
    assert engine.supports("gold", "5m"), "no series at all"

    for bar in _range_bound(bars=40):
        engine.observe_bar(bar)
    assert engine.supports("gold", "5m"), "a cold volatility estimate"


def test_an_unsupported_pair_is_declined_at_startup_not_at_the_next_reform():
    """`reform` applies the rule; it just does not apply it soon enough.

    A series comes due every `REFORM_EVERY` bars, which is twenty — so a 15m
    series restored from disk carries levels it should not have for five hours,
    opening touches and publishing calls from them the whole time. A restart is
    exactly when that matters, because state on disk was formed under whatever
    geometry was current when it was saved.
    """
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)
    assert engine.levels("gold", "5m"), "the fixture should have formed levels"

    vol = engine.vol.of("gold", "5m")

    class Coarse(Volatility):
        @property
        def tick(self) -> float:
            return self.price_units(4425.0, 0.38)

    coarse = Coarse()
    for _ in range(200):
        coarse.update(4425.0 * (1 + vol.bps / 10_000))
    engine.vol._by_key[("gold", "5m")] = coarse

    # Not due for a reform, so the existing rule would leave these standing.
    engine.series("gold", "5m").since_reform = 0
    assert engine.levels("gold", "5m"), "still holding levels before the sweep"

    assert engine.drop_unsupported() == 1
    assert engine.levels("gold", "5m") == []
    assert ("gold", "5m") in engine._declined

    # And it is idempotent — a second sweep has nothing left to say.
    assert engine.drop_unsupported() == 0


def test_the_startup_sweep_leaves_healthy_pairs_alone():
    engine = Engine(intervals=("5m",))
    for bar in _range_bound():
        engine.observe_bar(bar)
    before = len(engine.levels("gold", "5m"))
    assert before

    assert engine.drop_unsupported() == 0
    assert len(engine.levels("gold", "5m")) == before
    assert not engine._declined


# ------------------------------------------------- the level's own record


def test_the_hold_rate_counts_a_back_check_as_the_level_holding():
    """A retest that holds is the level holding, violently or not."""
    from till_infinity.structures.levels import Outcome, SideStats

    stats = SideStats()
    stats.record(Outcome.REJECT, 1.0)
    stats.record(Outcome.BACKCHECK, 1.0)
    assert stats.decisive == 2
    assert stats.hold_rate == 1.0


def test_chop_is_excluded_from_the_hold_rate_rather_than_taking_a_side():
    """Folding it into either column moves the rate for no reason."""
    from till_infinity.structures.levels import Outcome, SideStats

    stats = SideStats()
    stats.record(Outcome.REJECT, 1.0)
    stats.record(Outcome.BREAK, -1.0)
    stats.record(Outcome.CHOP, 0.0)
    assert stats.decisive == 2
    assert stats.hold_rate == 0.5


def test_a_trap_counts_as_price_having_got_through():
    from till_infinity.structures.levels import Outcome, SideStats

    stats = SideStats()
    stats.record(Outcome.TRAP, -1.0)
    assert stats.hold_rate == 0.0
    assert stats.decisive == 1


def test_a_rate_with_nothing_behind_it_is_not_a_low_rate():
    """Which is why the count travels with it."""
    from till_infinity.structures.levels import SideStats

    stats = SideStats()
    assert stats.hold_rate == 0.0
    assert stats.decisive == 0
