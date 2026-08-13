"""Key levels: PIP extraction, Kalman tracking, and directional inference."""

from __future__ import annotations

import random

import pytest

from till_infinity.structures import levels as lv
from till_infinity.structures import pips, pivots, reactions
from till_infinity.structures.engine import Engine
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
    tracker = reactions.Tracker(horizon=3600)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    for i in range(6):
        _touch(tracker, level, Side.ABOVE, +40.0, 1_000_000 + i * 100_000, vol)

    above = level.stats(Side.ABOVE)
    # Not exactly 6: the touches span days, so the early ones have aged.
    assert 5.0 < above.touches <= 6.0
    assert level.stats(Side.BELOW).touches == 0


def test_three_touches_the_same_way_is_not_certainty():
    """Reporting 100% from three observations is how a system talks itself in."""
    stats = lv.SideStats()
    for _ in range(3):
        stats.record(Outcome.REJECT, 1.0)
    assert stats.probability_up(prior_up=0.5) < 0.95


def test_a_fresh_level_borrows_from_similar_ones():
    vol = _vol()
    tracker = reactions.Tracker(horizon=3600)
    for n in range(6):
        neighbour = Level(feed=f"f{n}", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
        for i in range(4):
            _touch(tracker, neighbour, Side.ABOVE, +40.0, 1_000_000 + n * 10_000 + i * 900, vol)

    fresh = Level(feed="new", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(fresh, Side.ABOVE, 4400.0, vol, approach_vol=1.0)
    found = reactions.infer(fresh, Side.ABOVE, features, tracker.memory)

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


def test_a_real_call_passes_all_three():
    found = reactions.Inference(
        side=Side.ABOVE,
        probability_up=0.72,
        expected_push=1.5,
        push_sigma=0.4,
        base_rate_up=0.5,
        own_touches=10,
        neighbours=12,
    )
    assert found.actionable
    assert found.direction == "up"


def test_a_touch_resolves_into_a_labelled_example():
    vol = _vol()
    tracker = reactions.Tracker(horizon=3600)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    done = _touch(tracker, level, Side.ABOVE, +40.0, 1_000_000, vol)

    assert done is not None
    assert done.outcome is Outcome.REJECT
    assert done.push_vol > 0
    assert len(tracker.memory) == 1


def test_an_interaction_that_goes_nowhere_is_kept_as_chop():
    """A model never shown 'nothing happened' will predict a move every time."""
    vol = _vol()
    tracker = reactions.Tracker(horizon=120)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(level, Side.ABOVE, 4400.0, vol)
    tracker.begin(level, 4400.0, features, 1_000_000)
    done = tracker.update(level, 4400.0, vol, 1_000_200)

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


def test_untested_levels_are_pruned_but_touched_ones_are_kept():
    """A swing price never returned to is a swing, not a level."""
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
    tracker = reactions.Tracker(horizon=3600)
    level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    features = reactions.features_for(level, Side.ABOVE, 4400.0, vol)
    tracker.begin(level, 4400.0, features, when=1_000_000)
    done = tracker.update(level, 4500.0, vol, when=1_000_600)
    assert done is not None
    assert done.resolved > done.started
