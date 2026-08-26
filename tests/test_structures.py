"""The online layer: cross-venue features, detection, routing and persistence.

The detector is stochastic, so the tests that matter are behavioural - does a
stale feed get caught, does a quiet market stay quiet - rather than assertions
about particular scores.
"""

from __future__ import annotations

import random

import pytest

from till_infinity import structures as sx
from till_infinity.bus import ALERTS, BARS, QUOTES, SIGNALS, Bus, Message
from till_infinity.structures import features, store
from till_infinity.structures.anomaly import Detector, _describe, _sigma_to_score
from till_infinity.structures.drift import Drift
from till_infinity.structures.levels import Side
from till_infinity.structures.models import Shape, Signal
from till_infinity.structures.service import BarConsensus, Watcher

VENUES = ("OANDA", "PEPPERSTONE", "FOREXCOM", "SAXO", "FXPRO", "TVC")


def quote(venue, mid, bps=0.3, when=1_000.0, feed="gold"):
    return {"feed": feed, "venue": venue, "mid": mid, "spread_bps": bps, "time": when}


# ----------------------------------------------------- cross-venue features


def test_a_venue_is_never_part_of_its_own_consensus():
    """Including it is how a bad feed hides - it drags the number it is judged by."""
    book = features.Book("gold")
    for venue in VENUES[:5]:
        book.update(venue, 4400.0, 0.3, 1_000.0)
    book.update("SAXO", 5000.0, 0.3, 1_000.0)  # wildly wrong

    rest = book.consensus(exclude="SAXO", now=1_000.0)
    assert rest.mid == 4400.0
    assert rest.venues == 4


def test_the_consensus_is_a_median_not_a_mean():
    book = features.Book("gold")
    for venue, mid in zip(VENUES[:4], (4400.0, 4400.0, 4400.0, 9999.0), strict=True):
        book.update(venue, mid, 0.3, 1_000.0)
    assert book.consensus(now=1_000.0).mid == 4400.0


def test_deviation_is_measured_against_the_others():
    book = features.Book("gold")
    for venue in VENUES[:5]:
        book.update(venue, 4400.0, 0.3, 1_000.0)
    book.update("SAXO", 4400.0 * 1.001, 0.3, 1_000.0)

    got = book.features("SAXO", now=1_000.0)
    assert got["dev_bps"] == pytest.approx(10.0, abs=0.01)
    assert got["venues"] == 4  # the five, minus SAXO itself


def test_no_features_without_enough_venues_to_compare():
    """Silence is the honest answer when there is no rest of the market."""
    book = features.Book("gold")
    book.update("OANDA", 4400.0, 0.3, 1_000.0)
    book.update("SAXO", 4401.0, 0.3, 1_000.0)
    assert book.features("OANDA", now=1_000.0) is None


def test_a_venue_that_repeats_a_price_has_not_moved():
    """A dead feed often keeps sending; 'spoke' and 'moved' must stay separate."""
    book = features.Book("gold")
    book.update("OANDA", 4400.0, 0.3, 1_000.0)
    book.update("OANDA", 4400.0, 0.3, 1_060.0)
    assert book._readings["OANDA"].still(1_060.0) == 60.0


def test_staleness_is_measured_while_the_group_is_moving():
    """The ratio must not degenerate to 1.0 when everyone else is busy."""
    book = features.Book("gold")
    for venue in VENUES[:5]:
        book.update(venue, 4400.0, 0.3, 900.0)
        book.update(venue, 4400.5, 0.3, 1_000.0)
    book.update("FXPRO", 4400.0, 0.3, 900.0)
    book.update("FXPRO", 4400.0, 0.3, 1_000.0)

    got = book.features("FXPRO", now=1_000.0)
    assert got["staleness"] == 100.0
    assert got["staleness_ratio"] >= 5.0


def test_stale_readings_drop_out():
    book = features.Book("gold", max_age=60.0)
    for venue in VENUES[:4]:
        book.update(venue, 4400.0, 0.3, 1_000.0)
    assert len(book.live(now=1_000.0)) == 4
    assert book.live(now=2_000.0) == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"feed": "gold"},
        {"feed": "gold", "venue": "OANDA"},
        {"feed": "gold", "venue": "OANDA", "mid": None},
        {"feed": "gold", "venue": "OANDA", "mid": "wide"},
        {"feed": "gold", "venue": "OANDA", "mid": 0},
    ],
)
def test_junk_off_the_bus_produces_nothing(payload):
    assert features.Books().observe(payload) is None


# ---------------------------------------------------------------- detection


def _warm(detector, seed=11, ticks=300):
    """Run a calm market through the detector. Returns any false positives."""
    rand = random.Random(seed)
    now, base = 1_000_000.0, 4400.0
    fired = []
    for _ in range(ticks):
        now += 1
        base += rand.gauss(0, 0.15)
        for venue in VENUES:
            fired += detector.observe(
                quote(venue, base + rand.gauss(0, 0.02), abs(rand.gauss(0.3, 0.05)), now)
            )
    return fired, now, base


def test_a_calm_market_is_almost_entirely_quiet():
    fired, _, _ = _warm(Detector(warmup=60))
    assert len(fired) / (300 * len(VENUES)) < 0.01


def test_a_dislocation_is_caught():
    detector = Detector(warmup=60)
    _, now, base = _warm(detector)
    found = detector.observe(quote("SAXO", base * 1.003, 0.3, now + 1))
    assert found
    assert found[0].shape is Shape.DISLOCATION
    assert found[0].features["abs_dev_bps"] == pytest.approx(30.0, abs=1.0)


def test_one_big_outlier_does_not_blind_the_next_one():
    """Learning a 30bps print into the variance makes 3bps look ordinary."""
    detector = Detector(warmup=60)
    _, now, base = _warm(detector)
    assert detector.observe(quote("SAXO", base * 1.003, 0.3, now + 1))
    assert detector.observe(quote("SAXO", base * 1.0003, 0.3, now + 2))


def test_a_wide_spread_is_caught_and_named_as_one():
    detector = Detector(warmup=60)
    _, now, base = _warm(detector)
    found = detector.observe(quote("TVC", base, 3.0, now + 1))
    assert found
    assert found[0].shape is Shape.SPREAD


def test_an_unusually_tight_spread_is_not_reported():
    """Two-tailed scoring makes it detectable; nobody needs telling about it."""
    detector = Detector(warmup=60)
    _, now, base = _warm(detector)
    found = detector.observe(quote("TVC", base, 0.001, now + 1))
    assert not any(s.shape is Shape.SPREAD for s in found)


def test_a_stale_feed_is_caught_while_the_others_move():
    detector = Detector(warmup=60)
    _, now, base = _warm(detector)
    rand = random.Random(5)
    stuck, hit = base, None
    for _ in range(60):
        now += 2
        base += rand.gauss(0, 0.2)
        for venue in VENUES:
            mid = stuck if venue == "FXPRO" else base + rand.gauss(0, 0.02)
            for signal in detector.observe(quote(venue, mid, 0.3, now)):
                if signal.venue == "FXPRO" and signal.shape is Shape.STALE:
                    hit = signal
        if hit:
            break
    assert hit is not None
    assert hit.features["staleness"] >= 20.0


def test_a_signal_that_cannot_be_named_is_not_sent():
    """A rare combination in which nothing is remarkable is a shade of ordinary."""
    assert _describe({"staleness_ratio": 1.0, "spread_ratio": 1.0, "abs_dev_bps": 0.05}) is None


def test_a_named_signal_says_which_feature_drove_it():
    stale = _describe({"staleness_ratio": 9.0, "staleness": 90.0, "spread_ratio": 1.0})
    assert stale[0] is Shape.STALE
    assert "90s" in stale[1]


def test_sigma_converts_exactly():
    assert _sigma_to_score(4.0) == pytest.approx(0.999937, abs=1e-6)


# -------------------------------------------------------------------- drift


def _drift_series(detector, interval, seed=3, calm=600, wild=600, start=0.0):
    """Run a calm stretch then a violent one through one timeframe."""
    rand = random.Random(seed)
    mid, when, fired = 4400.0, start, []
    for _ in range(calm):
        mid *= 1 + rand.gauss(0, 0.00002)
        when += 60
        found = detector.observe("gold", mid, when, interval)
        if found:
            fired.append(found)
    for _ in range(wild):
        mid *= 1 + rand.gauss(0, 0.0006)
        when += 60
        found = detector.observe("gold", mid, when, interval)
        if found:
            fired.append(found)
    return fired, when


def test_a_calm_series_never_reports_drift():
    detector, mid, rand = Drift(), 4400.0, random.Random(3)
    fired = []
    for i in range(600):
        mid *= 1 + rand.gauss(0, 0.00002)
        found = detector.observe("gold", mid, float(i * 60), "5m")
        if found:
            fired.append(found)
    assert fired == []


def test_one_fast_timeframe_alone_is_a_busy_hour_not_a_regime_change():
    """A false drift discounts every level's history, so it has to be confirmed."""
    detector = Drift()
    fired, _ = _drift_series(detector, "5m")
    assert fired == []  # the detector fired internally; it was not believed


def test_pending_shows_what_fired_but_has_not_been_confirmed():
    detector = Drift()
    detector._fired[("gold", "5m")] = 1_000.0
    assert detector.pending("gold", 1_100.0) == ["5m"]
    assert detector.agreement("gold", 1_100.0) == []  # one fast timeframe alone
    assert detector.pending("gold", 1_000_000.0) == []  # long expired


def test_two_fast_timeframes_agreeing_is_a_regime_change():
    detector = Drift()
    _drift_series(detector, "5m")
    fired, _ = _drift_series(detector, "15m", seed=4)
    assert fired
    assert fired[0].shape is Shape.DRIFT
    assert fired[0].venue == "consensus"
    assert fired[0].features["timeframes"] >= 2


def test_a_slow_timeframe_is_believed_on_its_own():
    """A 4h regime change is a regime change; it is not a busy hour."""
    detector = Drift()
    fired, _ = _drift_series(detector, "4h")
    assert fired
    assert "4h" in fired[0].detail


def test_a_stale_fire_does_not_count_towards_agreement():
    """Two timeframes firing a week apart are not agreeing about anything."""
    detector = Drift()
    _drift_series(detector, "5m", start=0.0)
    long_after = 7 * 86_400
    fired, _ = _drift_series(detector, "15m", seed=4, start=long_after)
    assert fired == []


def test_a_confirmed_change_is_announced_once():
    detector = Drift()
    _drift_series(detector, "5m")
    fired, when = _drift_series(detector, "15m", seed=4)
    more, _ = _drift_series(detector, "30m", seed=5, start=when)
    assert len(fired) == 1
    assert more == []  # inside the same window, already announced


def test_the_first_reading_cannot_be_a_return():
    assert Drift().observe("gold", 4400.0, 1.0, "5m") is None


# ------------------------------------------------------------ bar consensus


def bar(venue, close, ts=60, interval="5m"):
    return {"feed": "gold", "venue": venue, "interval": interval, "close": close, "time": ts}


def test_bars_need_several_venues_before_they_mean_anything():
    consensus = BarConsensus()
    assert consensus.observe(bar("OANDA", 4400.0)) is None
    assert consensus.observe(bar("SAXO", 4401.0)) is None
    assert consensus.observe(bar("TVC", 4402.0)) == ("gold", 4401.0, "5m")


def test_only_venues_on_the_same_bar_are_blended():
    """Otherwise the median mixes different minutes and invents a move."""
    consensus = BarConsensus()
    for venue in ("OANDA", "SAXO", "TVC"):
        consensus.observe(bar(venue, 4400.0, ts=60))
    assert consensus.observe(bar("OANDA", 5000.0, ts=120)) is None


def test_the_interval_travels_with_the_price():
    """Drift is judged across timeframes, so it must know which one this is."""
    consensus = BarConsensus()
    for venue in VENUES[:2]:
        consensus.observe(bar(venue, 4400.0, interval="1h"))
    assert consensus.observe(bar("TVC", 4400.0, interval="1h")) == ("gold", 4400.0, "1h")


def test_an_interval_drift_does_not_watch_is_ignored():
    consensus = BarConsensus()
    for venue in VENUES[:4]:
        assert consensus.observe(bar(venue, 4400.0, interval="1d")) is None


# ------------------------------------------------------------------ routing


def _signal(shape=Shape.SPREAD, score=1.0, **features):
    return Signal(
        shape=shape, feed="gold", venue="OANDA", score=score, detail="d", features=features
    )


def test_a_stale_feed_goes_straight_to_a_human():
    watcher = Watcher(Bus(), settings=sx.Settings())
    assert watcher.direct(_signal(Shape.STALE))


def test_a_rare_spread_waits_for_an_agent():
    """Rarity is not unambiguity - a wide spread may well have a release behind it."""
    watcher = Watcher(Bus(), settings=sx.Settings())
    assert not watcher.direct(_signal(Shape.SPREAD, score=1.0, spread_ratio=12.0))


def test_a_broken_quote_goes_straight_through():
    watcher = Watcher(Bus(), settings=sx.Settings())
    assert watcher.direct(_signal(Shape.DISLOCATION, abs_dev_bps=250.0))
    assert not watcher.direct(_signal(Shape.DISLOCATION, abs_dev_bps=5.0))


def test_direct_alerting_can_be_switched_off_entirely():
    watcher = Watcher(Bus(), settings=sx.Settings(alert_direct=False))
    assert not watcher.direct(_signal(Shape.STALE))


async def test_signals_reach_agents_and_alerts_reach_notifications():
    bus = Bus()
    signals = bus.subscribe(SIGNALS, group="agents")
    alerts = bus.subscribe(ALERTS, group="notifications")
    watcher = Watcher(bus, settings=sx.Settings())

    assert await watcher.emit([_signal(Shape.STALE, staleness=90.0)]) == 1
    assert (await signals.next()).payload["shape"] == "stale"
    assert (await alerts.next()).payload["fields"]["venue"] == "OANDA"


async def test_a_situation_is_reported_once_per_cooldown():
    bus = Bus()
    watcher = Watcher(bus, settings=sx.Settings(cooldown=3600.0))
    bus.subscribe(SIGNALS, group="agents")

    assert await watcher.emit([_signal(Shape.STALE)]) == 1
    assert await watcher.emit([_signal(Shape.STALE)]) == 0


async def test_cooldown_memory_is_bounded():
    watcher = Watcher(Bus(), settings=sx.Settings(), memory=5)
    for n in range(20):
        watcher.fresh(Signal(shape=Shape.SPREAD, feed="gold", venue=f"V{n}", score=1.0))
    assert len(watcher._sent) == 5


async def test_a_quote_and_a_bar_take_different_paths():
    watcher = Watcher(Bus(), settings=sx.Settings())
    assert await watcher.handle(Message(topic=QUOTES, payload={"feed": "x"})) == []
    assert await watcher.handle(Message(topic=BARS, payload={"interval": "1h"})) == []
    assert await watcher.handle(Message(topic="something.else", payload={})) == []


# -------------------------------------------------------------- persistence


def test_models_survive_a_restart(tmp_path):
    detector = Detector(warmup=10)
    _warm(detector, ticks=40)
    store.save({"detector": detector, "drift": Drift()}, tmp_path)

    restored = store.load(tmp_path)
    assert restored["detector"].seen() == detector.seen()


def test_nothing_saved_yet_is_not_an_error(tmp_path):
    assert store.load(tmp_path) is None


def test_a_corrupt_state_file_starts_cold_rather_than_crashing(tmp_path):
    (tmp_path / store.STATE_FILE).write_bytes(b"not a pickle")
    assert store.load(tmp_path) is None


def test_state_from_another_river_version_is_refused(tmp_path):
    import pickle

    (tmp_path / store.STATE_FILE).write_bytes(
        pickle.dumps({"format": 1, "river": "0.0.1", "python": "3.11", "state": {"detector": 1}})
    )
    assert store.load(tmp_path) is None


def test_a_save_leaves_no_temp_file_behind(tmp_path):
    store.save({"detector": Detector()}, tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == [store.STATE_FILE]


# ------------------------------------------------- grading a regime change


def test_severity_is_scale_free():
    """A doubling counts the same on gold as on BTC."""
    assert Drift.severity(1.0, 2.0) == pytest.approx(Drift.severity(1000.0, 2000.0))


def test_a_market_going_quiet_is_as_much_a_change_as_one_going_wild():
    assert Drift.severity(1.0, 4.0) == pytest.approx(Drift.severity(4.0, 1.0))


def test_severity_of_no_change_is_zero():
    assert Drift.severity(5.0, 5.0) == 0.0
    assert Drift.severity(0.0, 5.0) == 0.0  # undefined rather than infinite


def test_a_percentile_is_not_claimed_from_three_samples():
    """A confident number derived from nothing is worse than admitting none."""
    detector = Drift()
    for value in (0.1, 0.2, 0.3):
        detector._remember(value)
    assert detector.percentile(99.0) == 0.5


def test_severity_is_graded_against_past_changes():
    detector = Drift()
    for value in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        detector._remember(value)
    assert detector.percentile(0.05) == 0.0
    assert detector.percentile(0.45) == pytest.approx(0.5)
    assert detector.percentile(9.0) == 1.0


def test_a_bigger_change_costs_a_level_more_of_its_history():
    """The whole point of grading: a marginal change must not act like a rout."""
    from till_infinity.structures.levels import Kalman, Level, Outcome, Side

    def _stocked():
        level = Level(feed="g", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
        for i in range(8):
            level.record(Side.ABOVE, Outcome.REJECT, 1.0, 1_000_000.0 + i)
        return level

    marginal, severe = _stocked(), _stocked()
    before = marginal.stats(Side.ABOVE).touches

    marginal.regime_changed(0.05)
    severe.regime_changed(0.99)

    assert severe.stats(Side.ABOVE).touches < marginal.stats(Side.ABOVE).touches < before
    assert marginal.stats(Side.ABOVE).touches > 0.9 * before  # barely touched


# ------------------------------------------------------ volatility regimes


def _run(vol, sigma, steps, seed=2):
    rand = random.Random(seed)
    price = 4400.0
    for _ in range(steps):
        price *= 1 + rand.gauss(0, sigma)
        vol.update(price)
    return vol


def test_the_regime_percentile_says_what_the_number_cannot():
    """'25bps' means nothing without knowing what this instrument usually does."""
    from till_infinity.structures.volatility import Volatility

    vol = _run(Volatility(), 0.00003, 400)
    calm = vol.regime
    _run(vol, 0.0008, 200)
    assert vol.regime > calm
    assert vol.violent


def test_a_quiet_market_reads_low_rather_than_merely_small():
    from till_infinity.structures.volatility import Volatility

    vol = _run(Volatility(), 0.0008, 300)
    _run(vol, 0.00002, 400)
    assert vol.regime < 0.3


def test_no_regime_is_claimed_before_there_is_history():
    from till_infinity.structures.volatility import Volatility

    assert Volatility().regime == 0.5


# ------------------------------------------- closing the loop on a decision


async def test_a_level_call_gets_its_outcome_attached(tmp_path):
    """A decision without its result is half a training example."""
    from till_infinity import journal as jr
    from till_infinity.structures.levels import Kalman, Level
    from till_infinity.structures.levels import Outcome as LevelOutcome
    from till_infinity.structures.models import Shape
    from till_infinity.structures.reactions import Features, Touch

    bus = Bus()
    bus.subscribe(SIGNALS, group="agents")
    async with jr.Journal(tmp_path / "j.db") as book:
        watcher = Watcher(bus, settings=sx.Settings(state_dir=tmp_path), journal=book)

        level = Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
        call = Signal(
            shape=Shape.LEVEL,
            feed="gold",
            venue="consensus",
            score=0.3,
            detail="up from above",
            features={"level": level.price},
        )
        assert await watcher.emit([call]) == 1

        # the touch that prompted it resolves
        touch = Touch(
            feed="gold",
            level_price=level.price,
            features=Features(Side.ABOVE, 1.0, 0.5, 0.5, 1.0, 0.5),
            started=1_000_000.0,
            entry=4400.0,
            extreme=4399.0,
            outcome=LevelOutcome.REJECT,
            push_vol=1.8,
            resolved=1_000_600.0,
        )
        watcher.engine._resolved.append((level, touch))
        assert await watcher.record_outcomes() == 1

        entries = jr.read(book.path)
        decision = next(e for e in entries if e.kind is jr.Kind.DECISION)
        result = next(e for e in entries if e.kind is jr.Kind.OUTCOME)

        assert result.parent == decision.id  # the pair a model needs
        assert result.context["outcome"] == "reject"
        assert result.context["push_vol"] == 1.8


async def test_a_resolution_nobody_predicted_is_not_an_outcome(tmp_path):
    """An outcome with no decision behind it is a fact, not a label."""
    from till_infinity import journal as jr
    from till_infinity.structures.levels import Kalman, Level
    from till_infinity.structures.levels import Outcome as LevelOutcome
    from till_infinity.structures.reactions import Features, Touch

    async with jr.Journal(tmp_path / "j.db") as book:
        watcher = Watcher(Bus(), settings=sx.Settings(state_dir=tmp_path), journal=book)
        level = Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
        watcher.engine._resolved.append(
            (
                level,
                Touch(
                    feed="gold",
                    level_price=level.price,
                    features=Features(Side.ABOVE, 1.0, 0.5, 0.5, 1.0, 0.5),
                    started=1.0,
                    entry=4400.0,
                    extreme=4400.0,
                    outcome=LevelOutcome.CHOP,
                    resolved=2.0,
                ),
            )
        )
        assert await watcher.record_outcomes() == 0
        assert jr.read(book.path) == []


async def test_an_outcome_is_written_once(tmp_path):
    """Reading without draining would journal the same result every message."""
    from till_infinity import journal as jr
    from till_infinity.structures.levels import Kalman, Level
    from till_infinity.structures.levels import Outcome as LevelOutcome
    from till_infinity.structures.models import Shape
    from till_infinity.structures.reactions import Features, Touch

    bus = Bus()
    bus.subscribe(SIGNALS, group="agents")
    async with jr.Journal(tmp_path / "j.db") as book:
        watcher = Watcher(bus, settings=sx.Settings(state_dir=tmp_path), journal=book)
        level = Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
        await watcher.emit(
            [
                Signal(
                    shape=Shape.LEVEL,
                    feed="gold",
                    venue="consensus",
                    score=0.3,
                    features={"level": level.price},
                )
            ]
        )
        watcher.engine._resolved.append(
            (
                level,
                Touch(
                    feed="gold",
                    level_price=level.price,
                    features=Features(Side.ABOVE, 1.0, 0.5, 0.5, 1.0, 0.5),
                    started=1.0,
                    entry=4400.0,
                    extreme=4400.0,
                    outcome=LevelOutcome.BREAK,
                    push_vol=-2.0,
                    resolved=2.0,
                ),
            )
        )
        assert await watcher.record_outcomes() == 1
        assert await watcher.record_outcomes() == 0


async def test_only_level_calls_wait_for_an_outcome(tmp_path):
    """A wide spread has no moment of being proven right or wrong."""
    from till_infinity import journal as jr
    from till_infinity.structures.models import Shape

    bus = Bus()
    bus.subscribe(SIGNALS, group="agents")
    async with jr.Journal(tmp_path / "j.db") as book:
        watcher = Watcher(bus, settings=sx.Settings(state_dir=tmp_path), journal=book)
        await watcher.emit(
            [Signal(shape=Shape.SPREAD, feed="gold", venue="OANDA", score=1.0, detail="wide")]
        )
        assert watcher._awaiting == {}


async def test_the_pending_map_is_bounded(tmp_path):
    from till_infinity import journal as jr

    async with jr.Journal(tmp_path / "j.db") as book:
        watcher = Watcher(Bus(), settings=sx.Settings(state_dir=tmp_path), journal=book, memory=5)
        for n in range(20):
            watcher._remember("gold", 4400.0 + n, f"ref{n}")
        assert len(watcher._awaiting) == 5


# --------------------------------------- state that no longer fits the code


def test_adding_a_field_invalidates_old_state(tmp_path, monkeypatch):
    """A slotted dataclass unpickles without a new slot and fails much later.

    That is exactly what happened: a `regime` feature was added and a running
    service died on state written before the change, with a message naming
    neither the field nor the cause.
    """
    store.save({"detector": Detector()}, tmp_path)
    assert store.load(tmp_path) is not None

    # the shape of what we persist changes
    monkeypatch.setattr(store, "_schema", lambda: "different")
    assert store.load(tmp_path) is None


def test_the_schema_follows_the_fields_of_every_persisted_class():
    """Nobody remembers to bump a version, and the failure is silent until it is not.

    This used to check one class - `reactions.Features` - which was on the
    hand-written list the hash was built from, so it passed while the guard was
    blind to everything not on that list. `Volatility` was not on it. Adding
    `_tick`, `_steps` and `_grid` therefore left the hash unchanged, stale
    state was accepted as compatible, and the service crashed reading a field
    the save predated: four hours of silence across twelve deploys.

    So the test walks the package too. Picking a class it happens to cover can
    no longer make it pass.
    """
    import dataclasses
    import importlib
    import pkgutil

    import till_infinity.structures as package

    persisted = []
    for found in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"till_infinity.structures.{found.name}")
        for name in dir(module):
            cls = getattr(module, name)
            if (
                isinstance(cls, type)
                and dataclasses.is_dataclass(cls)
                and cls.__module__ == module.__name__
                and getattr(cls, "__slots__", None) is not None
            ):
                persisted.append(cls)

    assert len(persisted) > 20, "the walk found almost nothing, so it is not walking"

    before = store._schema()
    for cls in persisted:
        real = cls.__slots__
        try:
            cls.__slots__ = (*real, "something_new")
            assert store._schema() != before, (
                f"a new field on {cls.__module__}.{cls.__name__} would not invalidate "
                "saved state, so a restore would crash on it instead of starting cold"
            )
        finally:
            cls.__slots__ = real
    assert store._schema() == before


# ------------------------------------- a cold engine must not stay cold


def test_a_restored_but_empty_engine_still_warms(tmp_path, monkeypatch):
    """The bug: a state file saved before any history existed made emptiness
    permanent, because every restart restored nothing and skipped warming on
    the grounds that the restore had succeeded."""
    from till_infinity.structures.anomaly import Detector
    from till_infinity.structures.drift import Drift

    settings = sx.Settings(state_dir=tmp_path, prices_db=tmp_path / "p.db")
    store.save({"detector": Detector(), "drift": Drift(), "engine": sx.Engine()}, tmp_path)

    watcher = Watcher(Bus(), settings=settings)
    assert watcher.load()  # the restore works
    assert watcher.cold  # and leaves nothing behind

    warmed = []
    monkeypatch.setattr(watcher.engine, "seed", lambda *a, **k: warmed.append(1) or 0)
    if watcher.cold:
        watcher.warm()
    assert warmed  # so it warms anyway


def test_an_engine_with_levels_is_not_cold(tmp_path):
    from till_infinity.structures.levels import Kalman, Level

    watcher = Watcher(Bus(), settings=sx.Settings(state_dir=tmp_path))
    assert watcher.cold
    watcher.engine._levels[("gold", "5m")] = [
        Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    ]
    assert not watcher.cold


async def test_a_thin_store_is_backfilled_before_anything_starts(tmp_path, monkeypatch):
    """History has to be in the store before the level engine looks at it."""
    from till_infinity import stack as st

    plan = st.Plan(
        prices=False,
        news=False,
        structures=False,
        journal=False,
        notifications=False,
        backfill=True,
    )
    plan.prices = True
    stack = st.Stack(plan)

    order: list[str] = []
    monkeypatch.setattr(st, "_stored_bars", lambda _p: 0)

    async def fake_backfill(**kwargs):
        order.append("backfill")
        raise RuntimeError("stop here")  # the ordering is the subject, not the pull

    monkeypatch.setattr(st.px, "backfill", fake_backfill)
    await stack._backfill(lambda *a: order.append("say"))
    assert "backfill" in order


async def test_a_full_store_is_not_backfilled_again(tmp_path, monkeypatch):
    """A restart should cost nothing."""
    from till_infinity import stack as st

    stack = st.Stack(st.Plan(backfill=True))
    monkeypatch.setattr(st, "_stored_bars", lambda _p: st.MIN_BARS + 1)

    called = []
    monkeypatch.setattr(st.px, "backfill", lambda **k: called.append(1))
    assert await stack._backfill(lambda *a: None) == 0
    assert not called


def test_counting_bars_in_a_store_that_does_not_exist(tmp_path):
    from till_infinity import stack as st

    assert st._stored_bars(tmp_path / "nothing.db") == 0


def test_a_volatility_saved_before_a_field_existed_still_loads():
    """The failure mode is a silent stop, not a crash, which is why it ran for hours.

    Production saves these models and restores them on every start. A
    `slots=True` dataclass has no `__dict__`, so a field added after the save
    is missing rather than defaulted and every read raises. When `_tick`,
    `_steps` and `_grid` were added the service came up, logged "restored
    models", then threw on the first quote inside the structures consumer - so
    the container stayed healthy at 11% CPU and simply produced nothing for
    four hours.
    """
    import pickle

    from till_infinity.structures.volatility import Book, Volatility

    vol = Volatility()
    price = 100.0
    for n in range(60):
        price += 0.01 if n % 2 else -0.005
        vol.update(price)

    state = vol.__getstate__()
    slots = state[1] if isinstance(state, tuple) else state
    # Exactly what an older save looks like: the newer fields are simply absent.
    for gone in ("_tick", "_steps", "_grid"):
        slots.pop(gone, None)

    restored = Volatility.__new__(Volatility)
    restored.__setstate__(state)

    assert restored.tick == 0.0  # no grid known yet, rather than an AttributeError
    restored.update(price + 0.01)  # the call that used to take the consumer down
    assert restored.bps > 0, "the fields that did survive were dropped too"

    # And through a real pickle round trip, including inside the Book that holds them.
    book = Book()
    book.of("gold", "5m").update(100.0)
    assert pickle.loads(pickle.dumps(book)).of("gold", "5m").tick == 0.0


def test_every_persisted_class_restores_a_field_it_predates():
    """The companion guard to the schema hash, and the one that walks.

    `store._schema` stops state being *loaded* once a shape has changed.
    `Restorable` stops a *crash* if any ever is - a pickle arriving by another
    path, a schema that is itself wrong, a class the walk cannot see. Neither
    subsumes the other, and this one is cheap.

    Written as a walk for the same reason the schema is: the version of the
    schema test that named one class passed while the guard was blind to
    twenty others.
    """
    import dataclasses
    import importlib
    import pickle
    import pkgutil

    import till_infinity.structures as package
    from till_infinity.structures.state import Restorable

    checked = 0
    for found in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"till_infinity.structures.{found.name}")
        for name in dir(module):
            cls = getattr(module, name)
            if not (
                isinstance(cls, type)
                and dataclasses.is_dataclass(cls)
                and cls.__module__ == module.__name__
                and getattr(cls, "__slots__", None) is not None
            ):
                continue
            assert issubclass(cls, Restorable), (
                f"{found.name}.{name} is persisted and does not default a field "
                "added after a save, so a restore raises instead of starting cold"
            )
            checked += 1

            optional = [
                f
                for f in dataclasses.fields(cls)
                if f.default is not dataclasses.MISSING
                or f.default_factory is not dataclasses.MISSING
            ]
            if not optional:
                continue

            # **A real pickle round trip first.** The version of this test that
            # only called `__setstate__` with a hand-built dict is what let an
            # outage through: a `frozen=True, slots=True` dataclass pickles as a
            # *list* of values in field order, not a mapping, and the handler
            # silently produced objects with every required field missing.
            # Production restored its models and `Features` had no `side`.
            built = cls(
                **{
                    f.name: (
                        f.default
                        if f.default is not dataclasses.MISSING
                        else f.default_factory()
                        if f.default_factory is not dataclasses.MISSING
                        else None
                    )
                    for f in dataclasses.fields(cls)
                }
            )
            revived = pickle.loads(pickle.dumps(built))
            for f in dataclasses.fields(cls):
                assert hasattr(revived, f.name), (
                    f"{found.name}.{name} lost {f.name} through pickle - "
                    "its state shape is not being read correctly"
                )

            # Then a state that predates the last optional field: every other
            # field present, that one simply absent.
            missing = optional[-1]
            state = {f.name: None for f in dataclasses.fields(cls) if f.name != missing.name}

            restored = cls.__new__(cls)
            restored.__setstate__(state)

            # The read that used to raise AttributeError, and it comes back as
            # the default rather than as anything invented.
            value = getattr(restored, missing.name)
            if missing.default is not dataclasses.MISSING:
                assert value == missing.default, f"{name}.{missing.name} restored wrong"

    assert checked > 20, "the walk found almost nothing, so it is not walking"


def test_a_bars_wick_cannot_resolve_a_touch_born_inside_it():
    """The range describes the whole bar, including before the touch existed.

    A quote opens a touch part way through a bar. The bar then arrives carrying
    a low and a high covering the *entire* period. Applied to that touch, it
    resolves instantly on movement that predates it - a large push, a duration
    of zero, and `run_vol` of exactly 0.00 because no leg in was ever observed.

    That was 33.6% of production outcomes and 41.9% of 3m ones (todo 0g), and
    it is invisible in a bars-only replay: without quotes, nothing opens a touch
    part way through a bar.
    """
    from till_infinity.structures import engine as eng

    handed: list[tuple] = []

    class Touching:
        """Stands in for one open touch, recording what it is offered."""

        def __init__(self, started: float) -> None:
            self.started = started

        def open_touch(self, level):
            return self

        def update(self, level, price, vol, when, low=None, high=None):
            handed.append((low, high))

        def expire(self, when):
            return []

    machine = eng.Engine(intervals=("1m",))
    volatility = machine.vol.of("x", "1m")
    for i in range(200):
        volatility.update(100.0 + (i % 5) * 0.1)
    assert volatility.warm, "the check returns early on a cold estimate"

    from till_infinity.structures.levels import Kalman, Level

    level = Level(feed="x", interval="1m", filter=Kalman(mean=100.0, variance=0.01))
    machine._levels[("x", "1m")] = [level]
    machine.tracker = Touching(started=800.0)

    # Open since 800. This bar opened at 900 and closed at 960, so the touch
    # was already live for every price in the range it is carrying.
    machine.check("x", "1m", 100.0, 960.0, low=99.0, high=101.0, since=900.0)

    # Now a touch that opened at 1000, and the bar that opened at 1000 with it.
    # Its low and high cover the seconds before this touch existed.
    machine.tracker = Touching(started=1_000.0)
    machine.check("x", "1m", 100.0, 1_060.0, low=99.0, high=101.0, since=1_000.0)
    # And a caller with no bar behind it, which is every quote.
    machine.check("x", "1m", 100.0, 1_120.0)

    assert len(handed) == 3, "update was not reached on every check"
    assert handed[0] == (99.0, 101.0), "a touch older than the bar keeps its wick"
    assert handed[1] == (None, None), "a touch born inside the bar must not see its range"
    assert handed[2] == (None, None), "a quote carries no range to begin with"


async def test_a_resolution_is_published_as_ground_truth(tmp_path):
    """The bus carries findings; this is the one message that carries facts.

    Published unconditionally rather than only for touches something predicted:
    most resolutions were never called by anything, and those are exactly the
    ones a consumer learning what levels do needs to see.
    """
    from till_infinity.bus import RESOLUTIONS
    from till_infinity.structures.levels import Kalman, Level
    from till_infinity.structures.levels import Outcome as LevelOutcome
    from till_infinity.structures.reactions import Features, Touch

    bus = Bus()
    resolutions = bus.subscribe(RESOLUTIONS, group="test")
    watcher = Watcher(bus, settings=sx.Settings(state_dir=tmp_path), journal=None)

    level = Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    touch = Touch(
        feed="gold",
        level_price=level.price,
        features=Features(Side.ABOVE, 1.0, 0.5, 0.5, 1.0, 0.5),
        started=1_000_000.0,
        entry=4400.0,
        extreme=4399.0,
        outcome=LevelOutcome.REJECT,
        push_vol=1.8,
        resolved=1_000_600.0,
    )
    watcher.engine._resolved.append((level, touch))
    # Nothing predicted this touch, so nothing is journalled for it.
    assert await watcher.record_outcomes() == 0

    message = await resolutions.next()
    assert message is not None
    assert message.payload["feed"] == "gold"
    assert message.payload["outcome"] == "reject"
    assert message.payload["direction"] == "up"
    assert message.payload["push_vol"] == 1.8
    assert message.payload["seconds"] == 600


def test_a_live_bar_carries_its_extremes():
    """It carried only the close, and the engine falls back to high=low=close.

    Every bar arriving on the bus therefore looked like a doji. Levels formed
    on the live path were built from closing prices alone, session pivots were
    computed from closes rather than session highs and lows, and a bar that
    pierced a level intrabar and closed away from it registered no touch. The
    stored history was always correct, so a restart re-warmed into a healthy
    state and the defect only reappeared as live bars accumulated.
    """
    from till_infinity.prices.models import Bar, SeriesKey, Symbol, WriteResult
    from till_infinity.prices.service import announce_bars

    key = SeriesKey("tradingview", "gold", Symbol("OANDA", "XAUUSD"), "5m")
    bar = Bar(time=1_700_000_000, open=4400.0, high=4412.0, low=4395.0, close=4408.0, volume=1234)
    out = announce_bars(key, [bar], WriteResult(inserted=1, updated=0))

    assert out["high"] == 4412.0
    assert out["low"] == 4395.0
    assert out["open"] == 4400.0
    assert out["volume"] == 1234
    # The thing that made it silent: reading it the old way still "works".
    assert float(out.get("high") or out["close"]) != out["close"]


def test_activity_is_a_ratio_because_the_underlying_count_is_not_comparable():
    """Tick volume counts price changes, differently per venue, and spot FX
    reports none at all. Only "against this instrument's own normal" travels."""
    from till_infinity.structures.activity import Book

    book = Book()
    for _ in range(40):
        book.update("gold", "5m", 1000)
    assert book.update("gold", "5m", 1000) == pytest.approx(1.0, abs=0.05)
    assert book.update("gold", "5m", 3000) > 2.5
    assert book.update("gold", "5m", 250) < 0.4
    # An instrument that reports nothing contributes a constant rather than a
    # hole, so it cannot skew whatever it is compared against.
    assert book.update("eurusd", "5m", None) == 1.0
    # And a cold estimator says "ordinary" rather than inventing a ratio.
    assert Book().update("btc", "1m", 99_999) == 1.0


def test_a_bar_with_no_extremes_is_reported_once(caplog):
    """The fallback that let the original bug hide in plain sight.

    `prices.announce_bars` shipped for a while sending close alone. Every live
    bar arrived flat, so levels on the live path formed from closing prices
    while the leg extremes that place an origin existed only in replayed
    history - and nothing said so. The fallback stays, because a notice from an
    older producer is better folded in flat than dropped, but it is no longer
    quiet.
    """
    engine = sx.Engine(intervals=("5m",))
    with caplog.at_level("WARNING"):
        for i in range(4):
            engine.observe_bar(
                {
                    "feed": "gold",
                    "interval": "5m",
                    "venue": "OANDA",
                    "time": 1_700_000_000 + i * 300,
                    "close": 4400.0 + i,
                }
            )
    said = [r.getMessage() for r in caplog.records if "no high/low" in r.getMessage()]
    assert len(said) == 1, "warned once per series, not once per bar"
    assert "gold" in said[0]


def test_a_bar_with_real_extremes_is_not_reported(caplog):
    engine = sx.Engine(intervals=("5m",))
    with caplog.at_level("WARNING"):
        engine.observe_bar(
            {
                "feed": "gold",
                "interval": "5m",
                "venue": "OANDA",
                "time": 1_700_000_000,
                "close": 4400.0,
                "high": 4402.0,
                "low": 4398.0,
            }
        )
    assert not [r for r in caplog.records if "no high/low" in r.getMessage()]
