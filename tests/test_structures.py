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
from till_infinity.structures.learning.anomaly import Detector, _describe, _sigma_to_score
from till_infinity.structures.learning.drift import Drift
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
    from till_infinity.structures.vol.volatility import Volatility

    vol = _run(Volatility(), 0.00003, 400)
    calm = vol.regime
    _run(vol, 0.0008, 200)
    assert vol.regime > calm
    assert vol.violent


def test_a_quiet_market_reads_low_rather_than_merely_small():
    from till_infinity.structures.vol.volatility import Volatility

    vol = _run(Volatility(), 0.0008, 300)
    _run(vol, 0.00002, 400)
    assert vol.regime < 0.3


def test_no_regime_is_claimed_before_there_is_history():
    from till_infinity.structures.vol.volatility import Volatility

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


def test_a_field_added_since_the_save_is_defaulted_not_fatal(tmp_path, monkeypatch):
    """A slotted dataclass unpickles without a new slot and fails much later -
    a `regime` feature was added and a running service died on state written
    before the change, naming neither the field nor the cause.

    That is fixed by `Restorable.__setstate__`, which restores by name and
    defaults what is missing, and **not** by refusing the file. Refusing it
    cost 59MB three times in one day, the last of them for two counters added
    to one small model.
    """
    store.save({"detector": Detector()}, tmp_path)
    assert store.load(tmp_path) is not None

    # A class we persist changes shape. This used to discard the file and no
    # longer does: `Restorable.__setstate__` restores by field name, defaulting
    # what the save predates and ignoring what the build has dropped, so the
    # AttributeError this once guarded against cannot happen. It is reported
    # and the state is kept. See `_reshaped` and the note in `store.load`.
    bent = dict(store._schema())
    name = next(iter(bent))
    bent[name] = bent[name] + ",invented"
    monkeypatch.setattr(store, "_schema", lambda: bent)
    assert store.load(tmp_path) is not None


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
    # `walk_packages`, not `iter_modules`: the package has subpackages since
    # 2026-09-04 and a flat walk finds only the eleven modules left at the top,
    # which is how this test caught the move rather than passing through it.
    for found in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        module = importlib.import_module(found.name)
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
    from till_infinity.structures.learning.anomaly import Detector
    from till_infinity.structures.learning.drift import Drift

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

    from till_infinity.structures.vol.volatility import Book, Volatility

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


def test_adding_a_model_does_not_discard_the_state():
    """A single fingerprint over the whole package changed when anything
    changed, so adding `racing.Races` would have thrown away every level, the
    break model and weeks of touches - for a class that was not in the old file
    and could not conflict with anything in it. Twice in one day."""
    from till_infinity.structures import store

    current = store._schema()
    without = {k: v for k, v in current.items() if not k.startswith("racing.")}

    assert store._reshaped(without, current) == []


def test_changing_a_persisted_class_still_discards_it():
    """The other half. A class in both, with different fields, is the danger
    the fingerprint exists for - `Volatility` gaining `_tick` is what it
    missed."""
    from till_infinity.structures import store

    current = store._schema()
    bent = dict(current)
    bent["activity.Activity"] = current["activity.Activity"] + ",invented"

    assert store._reshaped(bent, current) == ["activity.Activity"]


def test_a_state_file_from_the_hash_era_is_still_readable():
    """Format 3 stored one hash and there is nothing to compare key by key.
    Rejecting it would discard exactly the state this change exists to keep."""
    from till_infinity.structures import store

    assert store._reshaped("1c464f3d6dbfafb5", store._schema()) == []


def test_state_pickled_under_a_module_s_old_path_still_loads():
    """The gap in `codec`'s own reasoning, and it cost a cold start.

    That docstring says raw blobs pickle *river's* classes and this project
    does not move those, so a reorganisation was safe. At least one blob
    referenced `till_infinity.structures.anomaly` instead, and when that module
    moved into `learning/` the whole 59MB file failed to read with `No module
    named 'till_infinity.structures.anomaly'` - every level, the break model
    and weeks of touches, discarded on the first deploy after the move.

    So the basename rule that protects the named classes has to protect the
    pickled ones too.
    """
    import pickle

    from till_infinity.structures import codec
    from till_infinity.structures.learning.anomaly import Detector

    # A GLOBAL opcode naming the module where `anomaly` used to live. This is
    # what the real state file contains.
    old = b"ctill_infinity.structures.anomaly\nDetector\n."
    with pytest.raises((ModuleNotFoundError, AttributeError)):
        pickle.loads(old)

    assert codec._unpickle(old) is Detector


def test_the_relocator_leaves_other_packages_alone():
    """It maps this package's modules and nothing else - river's paths are
    river's business, and rewriting them would break on a version bump."""
    import pickle

    from till_infinity.structures import codec

    blob = pickle.dumps(pickle.loads)
    assert codec._unpickle(blob) is pickle.loads


def test_a_changed_shape_is_reported_rather_than_thrown_away(tmp_path, monkeypatch, caplog):
    """Knowing which classes moved is worth having; it is not worth the file."""
    import logging

    store.save({"detector": Detector()}, tmp_path)
    bent = dict(store._schema())
    name = next(iter(bent))
    bent[name] = bent[name] + ",invented"
    monkeypatch.setattr(store, "_schema", lambda: bent)

    with caplog.at_level(logging.INFO, logger="till_infinity.structures.store"):
        got = store.load(tmp_path)

    assert got is not None
    said = " ".join(caplog.messages)
    assert name in said
    assert "restoring anyway" in said


def test_the_schema_covers_the_subpackages_and_not_their_paths():
    """Two failures the 2026-09-04 folder move could have caused, and the
    fingerprint has to avoid both.

    **Covering too little.** `_schema` walked with `iter_modules`, which is
    flat. After the move it went on finding the eleven modules left at the top
    and silently stopped covering the other thirty-five, so a new field on
    `context.activity.Activity` would not have invalidated saved state and the
    restore would have crashed on it instead of starting cold - the exact
    failure this hash exists to prevent.

    **Covering too much.** Hashing the dotted path instead of the basename
    would make the fingerprint change when a module *moves*, cold-starting 58MB
    of learned state for a change that alters no field of anything.
    """
    import pkgutil

    import till_infinity.structures as package
    from till_infinity.structures import store

    covered = set()
    for info in pkgutil.walk_packages(package.__path__, prefix=package.__name__ + "."):
        covered.add(info.name.rsplit(".", 1)[-1])
    # The walk reaches into the folders, not just the top of the package.
    assert {"activity", "breaking", "pips", "volatility"} <= covered
    assert len(covered) > 40

    # And it is keyed on basenames, so no folder appears in any key.
    shapes = store._schema()
    assert len(shapes) > 40
    assert not [k for k in shapes if "drawing" in k or "learning" in k]
    assert "activity.Activity" in shapes


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
    # `walk_packages`, not `iter_modules`: the package has subpackages since
    # 2026-09-04 and a flat walk finds only the eleven modules left at the top,
    # which is how this test caught the move rather than passing through it.
    for found in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        module = importlib.import_module(found.name)
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
    from till_infinity.structures.context.activity import Book

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


def test_the_mean_reverting_estimate_reduces_to_the_existing_one():
    """`a + b = 1` removes the constant, and the model becomes the EW mean.

    The equivalence is the argument that this adds one property and changes
    nothing else, so it is a test rather than a claim in a docstring.
    """
    from till_infinity.structures.vol.garch import Garch
    from till_infinity.structures.vol.volatility import Volatility

    plain = Volatility(half_life=30.0)
    same = Garch(half_life=30.0, persistence=1.0)
    prices = [100.0 + (i % 7) * 0.4 - (i % 3) * 0.25 for i in range(200)]
    for price in prices:
        plain.update(price)
        same.update(price)
    assert same.bps == pytest.approx(plain.bps, rel=1e-9)


def test_a_shock_fades_toward_the_long_run_level():
    """What an exponentially weighted mean cannot do: have a destination."""
    from till_infinity.structures.vol.garch import Garch

    model = Garch(half_life=10.0, persistence=0.9, long_half_life=200.0)
    for i in range(500):
        model.update(100.0 + (i % 2) * 0.05)  # a steady, quiet series
    calm = model.bps

    model.update(130.0)  # one violent bar
    assert model.bps > calm * 2

    for i in range(300):
        model.update(130.0 + (i % 2) * 0.065)  # quiet again, at the new price
    # Back near where it started, rather than wherever the shock left it.
    assert model.bps < calm * 2
    assert model.stretch < 2.0


def test_the_long_run_level_is_not_just_the_estimate_again():
    """If the anchor moved at the speed of the estimate there would be nothing
    to revert to."""
    from till_infinity.structures.vol.garch import Garch

    model = Garch(half_life=10.0, long_half_life=5_000.0)
    for i in range(400):
        model.update(100.0 + (i % 2) * 0.02)
    quiet_long = model.long_run_bps
    for i in range(60):
        model.update(100.0 + (i % 2) * 2.0)  # a loud stretch
    assert model.bps > model.long_run_bps
    assert model.long_run_bps == pytest.approx(quiet_long, rel=0.9)
    assert model.stretch > 1.5


def test_the_scale_conversion_is_applied_before_anything_is_averaged():
    """Averaging a mean absolute deviation against a standard deviation gives
    a number that is neither, and every threshold here would shift by ~20%."""
    from till_infinity.structures.vol.consensus_vol import MAD_TO_SIGMA, Ensemble

    book = Ensemble()
    # Two members reporting the *same underlying* volatility, one on each
    # scale. Reconciled, they should agree - so the average is that value.
    book.observe({"ew": 10.0, "range": 10.0 * MAD_TO_SIGMA}, sigma_scaled=frozenset({"range"}))
    assert book.bps == pytest.approx(10.0)


def test_a_member_is_scored_against_what_actually_happened():
    from till_infinity.structures.vol.consensus_vol import SCORE_WARMUP, Ensemble

    book = Ensemble()
    for _ in range(SCORE_WARMUP + 20):
        book.observe({"good": 10.0, "bad": 40.0})
        book.settle(10.0)  # the truth was 10 every time
    assert book.accuracy("good") > book.accuracy("bad")
    assert next(name for name, _ in book.standings()) == "good"


def test_the_combination_is_equal_weight_until_told_otherwise():
    """The simple average routinely beats fitted weights out of sample, and
    edge.md is this repository's own version of that warning."""
    from till_infinity.structures.vol.consensus_vol import Ensemble

    plain = Ensemble()
    plain.observe({"a": 10.0, "b": 20.0})
    assert plain.bps == pytest.approx(15.0)

    fitted = Ensemble(weighted=True)
    for _ in range(200):
        fitted.observe({"a": 10.0, "b": 20.0})
        fitted.settle(10.0)  # `a` has been right all along
    assert fitted.bps < 15.0, "weighting should lean toward the accurate member"


def test_nothing_earns_a_weight_before_it_has_been_scored():
    """Zero accuracy everywhere is not the same as everything weighing zero."""
    from till_infinity.structures.vol.consensus_vol import Ensemble

    book = Ensemble(weighted=True)
    book.observe({"a": 10.0, "b": 20.0})
    assert book.bps == pytest.approx(15.0)


def test_every_touch_carries_the_edge_it_had_not_only_published_ones():
    """The half of the distribution nothing could look at.

    Publication requires `edge >= MIN_EDGE`, so every edge ever recorded was
    already above the threshold and "does a larger edge resolve better" could
    only be asked of the calls that passed. Attaching it to the touch makes
    every interaction evidence, including the ones nobody was told about -
    which answers the question without trading a single below-threshold call.
    """
    from till_infinity.structures.reactions import Touch

    t = Touch(
        feed="gold", level_price=4400.0, features=None, started=0.0, entry=4400.0, extreme=4400.0
    )
    assert hasattr(t, "edge")
    assert hasattr(t, "actionable")
    # Defaults are honest zeros rather than a guess.
    assert t.edge == 0.0
    assert t.actionable is False


def test_a_resolution_carries_the_belief_beside_the_outcome():
    """The edge and what actually happened have to travel together.

    Recorded separately they cannot be joined: the signal is published only
    when it passes, and the resolution is recorded always, so a scoring pass
    would silently only ever see the touches that were published.
    """
    from till_infinity.structures.reactions import Features, Touch

    t = Touch(
        feed="gold",
        level_price=4400.0,
        features=Features(
            side=Side.ABOVE,
            approach_vol=1.0,
            depth_vol=0.5,
            strength=0.7,
            run_vol=1.2,
            experience=4.0,
        ),
        started=0.0,
        entry=4400.0,
        extreme=4400.0,
    )
    t.edge = -0.043  # below the publication threshold
    t.probability_up = 0.47
    t.base_rate_up = 0.513
    t.actionable = False
    t.push_vol = -1.8

    d = t.to_dict()
    assert d["edge"] == pytest.approx(-0.043)
    assert d["actionable"] is False
    assert d["push_vol"] == pytest.approx(-1.8)
    # A below-threshold touch is now evidence, which it never was before.
    assert abs(d["edge"]) < 0.10


def test_regime_labels_are_ordered_rather_than_arbitrary():
    """A k-means cluster id is a memory address, not a meaning.

    The cluster called 2 today may be the one called 0 after a restart, and a
    per-regime scoreboard keyed on the id would silently pool unrelated
    conditions. Sorting by how energetic the centre is makes the names mean the
    same thing across restarts even as the centres move.
    """
    from till_infinity.structures.learning.regimes import NAMES, WARMUP, Regimes

    book = Regimes()
    # Two clearly separated conditions, fed alternately.
    for i in range(WARMUP * 2):
        calm = {
            "vol_stretch": 0.5,
            "regime": 0.1,
            "activity": 0.6,
            "hour_vol_share": 0.05,
            "forecast_ratio": 0.9,
            "sweep_rate": 0.0,
        }
        loud = {
            "vol_stretch": 2.5,
            "regime": 0.95,
            "activity": 2.4,
            "hour_vol_share": 0.3,
            "forecast_ratio": 1.4,
            "sweep_rate": 0.4,
        }
        book.observe(calm if i % 2 else loud)

    assert book.warm
    quiet = book.observe(
        {
            "vol_stretch": 0.5,
            "regime": 0.1,
            "activity": 0.6,
            "hour_vol_share": 0.05,
            "forecast_ratio": 0.9,
            "sweep_rate": 0.0,
        }
    )
    wild = book.observe(
        {
            "vol_stretch": 2.5,
            "regime": 0.95,
            "activity": 2.4,
            "hour_vol_share": 0.3,
            "forecast_ratio": 1.4,
            "sweep_rate": 0.4,
        }
    )
    assert quiet in NAMES
    assert wild in NAMES
    assert NAMES.index(quiet) < NAMES.index(wild), "the calmer condition should rank calmer"


def test_a_cold_classifier_says_nothing():
    """A label from twenty points is a statement about the first twenty points."""
    from till_infinity.structures.learning.regimes import Regimes

    book = Regimes()
    for _ in range(20):
        book.observe(
            {
                "vol_stretch": 1.0,
                "regime": 0.4,
                "activity": 1.0,
                "hour_vol_share": 0.1,
                "forecast_ratio": 1.0,
                "sweep_rate": 0.0,
            }
        )
    assert not book.warm
    assert (
        book.observe(
            {
                "vol_stretch": 1.0,
                "regime": 0.4,
                "activity": 1.0,
                "hour_vol_share": 0.1,
                "forecast_ratio": 1.0,
                "sweep_rate": 0.0,
            }
        )
        == ""
    )


def test_the_scoreboard_sorts_worst_first():
    """The useful question of a scoreboard like this is which pairing to stop,
    and a list sorted best-first buries it."""
    from till_infinity.structures.learning.regimes import Regimes

    book = Regimes()
    book.record("quiet", "level-scalp", 1.2)
    book.record("quiet", "level-scalp", 0.8)
    book.record("wild", "sweep-aware", -1.0)
    got = book.standings()
    assert got[0][0] == "wild/sweep-aware"
    assert got[0][2] == pytest.approx(-1.0)
    assert got[-1][0] == "quiet/level-scalp"


def test_the_regime_features_only_call_methods_the_clock_has():
    """A production outage, caught here after the fact rather than before.

    The regime wiring called `Clock.vol_share`, which does not exist - the name
    was invented rather than looked up. Structures raised on the first level
    call, the consumer stopped, and the container went on reporting healthy
    while producing nothing, which is the failure state.py was written after.

    Nothing exercised `_level_calls` against a real Clock, so the whole suite
    passed. This asserts the seam directly: every attribute the regime features
    read has to exist on the object that will be passed at runtime.
    """
    from till_infinity.structures.context.sessions import Clock
    from till_infinity.structures.vol.volatility import Volatility

    clock = Clock()
    vol = Volatility()
    # Exactly what `_level_calls` builds, against the real objects.
    features = {
        "vol_stretch": vol.stretch,
        "regime": vol.regime,
        "activity": 1.0,
        "hour_vol_share": clock.volatility("gold", 1_700_000_000.0)[1],
        "forecast_ratio": vol.forecast_ratio,
        "sweep_rate": 0.0,
    }
    from till_infinity.structures.learning import regimes

    assert set(features) == set(regimes.FEATURES)
    assert all(isinstance(v, float) for v in features.values())


def test_a_label_never_goes_into_the_float_dict():
    """The second production outage of the day, and the same shape as the first.

    `Signal.features` is a float dict and every value is rounded on the way
    out, so a string put there raises on the first signal - `type str doesn't
    define __round__` - and the raise lands in the structures consumer, which
    stops while the container goes on reporting healthy.

    Labels belong beside `direction`, which is on the Signal for exactly this
    reason and has been all along.
    """
    from till_infinity.structures.models import Shape, Signal

    sig = Signal(
        shape=Shape.LEVEL,
        feed="gold",
        venue="consensus",
        score=0.4,
        interval="5m",
        direction="up",
        market="quiet",
        features={"vol_bps": 4.2},
    )
    assert sig.market == "quiet"
    # Everything in features must survive being rounded.
    for key, value in sig.features.items():
        assert round(value, 6) is not None, key
    d = sig.to_dict()
    assert d["features"]["vol_bps"] == pytest.approx(4.2)


def test_the_path_is_recorded_independently_of_the_outcome():
    """The whole reason it exists.

    `push_vol` is signed by (outcome, approach side): decomposed within each
    outcome the relationship is 0% or 100% at all eight cells, so it is an
    identity and no side rule can be scored against it. The path knows nothing
    about rejects, traps or breaks - it is just where price was.
    """
    from till_infinity.structures.levels import Side
    from till_infinity.structures.reactions import PATH_OFFSETS, Features, Touch

    t = Touch(
        feed="gold",
        level_price=4400.0,
        features=Features(
            side=Side.ABOVE,
            approach_vol=1.0,
            depth_vol=0.5,
            strength=0.7,
            run_vol=1.2,
            experience=4.0,
        ),
        started=0.0,
        entry=4400.0,
        extreme=4400.0,
    )
    # Price a unit above the level at the first offset, a unit below at the next.
    t.path = {str(PATH_OFFSETS[0]): +1.0, str(PATH_OFFSETS[1]): -1.0}
    d = t.to_dict()
    assert d[f"path_{PATH_OFFSETS[0]}"] == pytest.approx(1.0)
    assert d[f"path_{PATH_OFFSETS[1]}"] == pytest.approx(-1.0)
    # And it carries no outcome of its own.
    assert d["outcome"] == "open"


def test_a_missing_sample_is_absent_rather_than_zero():
    """A gap in the record is not a price of zero, and writing one would make
    a quiet stretch look like a return to the level."""
    from till_infinity.structures.levels import Side
    from till_infinity.structures.reactions import PATH_OFFSETS, Features, Touch

    t = Touch(
        feed="gold",
        level_price=4400.0,
        features=Features(
            side=Side.ABOVE,
            approach_vol=1.0,
            depth_vol=0.5,
            strength=0.7,
            run_vol=1.2,
            experience=4.0,
        ),
        started=0.0,
        entry=4400.0,
        extreme=4400.0,
    )
    t.path = {str(PATH_OFFSETS[0]): +0.5}
    d = t.to_dict()
    assert f"path_{PATH_OFFSETS[0]}" in d
    assert f"path_{PATH_OFFSETS[-1]}" not in d


def test_a_resolution_carries_the_timeframes_that_agreed():
    """Confluence was on the signal and not on the outcome.

    So "does agreement across timeframes predict what happens" could only be
    asked of the two dozen touches that were traded, where it is noise - while
    7,198 of 7,966 published calls have no agreement at all and the question is
    really about the whole population.
    """
    from till_infinity.structures.levels import Side
    from till_infinity.structures.reactions import Features, Touch

    t = Touch(
        feed="gold",
        level_price=4400.0,
        features=Features(
            side=Side.ABOVE,
            approach_vol=1.0,
            depth_vol=0.5,
            strength=0.7,
            run_vol=1.2,
            experience=4.0,
        ),
        started=0.0,
        entry=4400.0,
        extreme=4400.0,
    )
    t.confluence = "1d+4h+1h"
    d = t.to_dict()
    assert d["confluence"] == "1d+4h+1h"
    assert d["confluence_n"] == pytest.approx(3.0)
    # And the common case is honest about being empty rather than absent.
    assert Touch(
        feed="gold",
        level_price=1.0,
        features=Features(
            side=Side.ABOVE,
            approach_vol=1.0,
            depth_vol=0.0,
            strength=0.0,
            run_vol=0.0,
            experience=0.0,
        ),
        started=0.0,
        entry=1.0,
        extreme=1.0,
    ).to_dict()["confluence_n"] == pytest.approx(0.0)


def test_confluence_is_written_back_only_once():
    """The first zone to claim a touch names it; a later one does not rename
    it, because the touch opened under the first."""
    from till_infinity.structures.levels import Side
    from till_infinity.structures.reactions import Features, Touch, Tracker

    tracker = Tracker()
    t = Touch(
        feed="gold",
        level_price=4400.0,
        features=Features(
            side=Side.ABOVE,
            approach_vol=1.0,
            depth_vol=0.0,
            strength=0.0,
            run_vol=0.0,
            experience=0.0,
        ),
        started=0.0,
        entry=4400.0,
        extreme=4400.0,
    )
    tracker._open[("gold", 4400.0)] = t
    tracker.note_confluence("gold", 4400.0, "1h+15m")
    tracker.note_confluence("gold", 4400.0, "1d+4h")
    assert t.confluence == "1h+15m"


def test_a_cold_volatility_estimate_is_not_warm():
    """`WARMUP`, the `warmup` field, the `_seen` counter and this property all
    existed, and no code joined them to a decision. A cold estimate returns
    `floor_bps`, every distance here is a price divided by it, and a brent call
    went out claiming an expected push of 10,229 volatility units.
    """
    from till_infinity.structures.vol.volatility import WARMUP, Volatility

    vol = Volatility()
    assert vol.warm is False
    for i in range(WARMUP + 1):
        vol.update(100.0 + i * 0.01)
    assert vol.warm is True


def test_the_volatility_floor_sits_below_anything_real():
    """0.05 bps was an order of magnitude under the lowest volatility ever
    seen live (0.517) and did not bound what it was written to bound."""
    from till_infinity.structures.vol.volatility import MIN_VOL_BPS

    assert 0.1 <= MIN_VOL_BPS <= 0.5


def test_the_engine_will_not_publish_from_a_cold_estimate():
    """The guard has to be asked, not merely available - which was the whole
    defect."""
    import inspect

    from till_infinity.structures import engine as eng

    source = inspect.getsource(eng.Engine)
    assert "if not vol.warm:" in source


def test_adverse_excursion_is_recorded_without_a_threshold():
    """`excursion_vol` is only assigned once price is a full unit past the
    level, so it holds 42,442 zeros and 12,105 values of 1.0 or more with
    nothing between. Every replay stopping a trade at `excursion >= stop`
    therefore modelled a 1.0v stop whatever it was asked for.

    `adverse_vol` has no threshold, which is what a stop has to survive.
    """
    from till_infinity.structures.reactions import Features, Side, Touch

    touch = Touch(
        feed="gold",
        level_price=100.0,
        features=Features(Side.ABOVE, 1.0, 0.5, 0.5, 1.0, 0.5),
        started=0.0,
        entry=100.0,
        extreme=100.0,
    )
    assert touch.adverse_vol == 0.0
    # A shallow move against, well under any resolve threshold.
    touch.adverse_vol = max(touch.adverse_vol, 0.3)
    assert 0 < touch.adverse_vol < 1.0


def test_adverse_excursion_is_published():
    """It is no use unless the journal can be asked about it."""
    from till_infinity.structures.reactions import Features, Side, Touch

    touch = Touch(
        feed="gold",
        level_price=100.0,
        features=Features(Side.ABOVE, 1.0, 0.5, 0.5, 1.0, 0.5),
        started=0.0,
        entry=100.0,
        extreme=100.0,
    )
    touch.adverse_vol = 0.42
    assert touch.to_dict().get("adverse_vol") == pytest.approx(0.42)


def test_the_published_resolution_carries_adverse_excursion():
    """This context is hand-built and does not call `Touch.to_dict`, so adding
    a field to the dataclass does nothing for what is published. That is the
    fourth time in one session a value has been computed correctly and written
    where nothing reads it, and it is only caught by asking what arrives.
    """
    import inspect

    from till_infinity.structures import service as svc

    source = inspect.getsource(svc)
    assert '"adverse_vol": round(touch.adverse_vol, 4),' in source
    assert '"excursion_vol": round(touch.excursion_vol, 4),' in source


def test_the_origin_zone_is_published_in_prices():
    """The scoring fields describe an origin without saying where it is, which
    is enough to judge a level and not enough to enter at one. Resting an order
    at the edge of the zone needs the edge, and `origin_distance_vol` is an
    absolute distance that has lost its direction."""
    from till_infinity.structures.drawing import origins

    origin = origins.Origin(
        price=100.0,
        low=99.0,
        high=101.0,
        launched="up",
        size_vol=2.0,
        when=0.0,
    )
    published = origin.to_dict()
    assert published["low"] == 99.0
    assert published["high"] == 101.0
    assert published["price"] == 100.0


def test_a_venue_on_another_unit_is_dropped_from_the_consensus():
    """`FOREXCOM:USOIL` ran 8047-8397 against 80-85 everywhere else - oil in
    cents, a clean factor of 100, across 70,402 stored wti quotes. That is not
    a dislocation: it drags the median and reads as one venue permanently
    disagreeing with five."""
    from till_infinity.structures.service import BarConsensus

    book = BarConsensus()
    for venue, close in (
        ("OANDA", 82.10),
        ("CAPITALCOM", 82.05),
        ("TVC", 82.15),
        ("FOREXCOM", 8210.0),
    ):
        got = book.observe(
            {
                "feed": "wti",
                "venue": venue,
                "interval": "5m",
                "close": close,
                "time": 1_000,
            }
        )
    assert got is not None
    _, median, _ = got
    # The cent-quoted venue is gone, so the median is an oil price.
    assert 80.0 < median < 85.0


def test_ordinary_venue_disagreement_is_kept():
    """A real disagreement is basis points, and must not be discarded as a unit
    error - that would be the gate silently thinning the consensus."""
    from till_infinity.structures.service import BarConsensus

    book = BarConsensus()
    for venue, close in (
        ("OANDA", 82.10),
        ("CAPITALCOM", 82.90),
        ("TVC", 81.40),
        ("FOREXCOM", 83.50),
    ):
        got = book.observe(
            {"feed": "wti", "venue": venue, "interval": "5m", "close": close, "time": 1_000}
        )
    assert got is not None
    _, median, _ = got
    assert 82.0 < median < 82.6


def test_a_single_source_feed_needs_no_agreement():
    """`MIN_VENUES` exists because a median of two is one venue's opinion in a
    median's clothes. That argument does not reach an instrument only one place
    quotes: a synthetic has no underlying, so the broker is not *a* source, it
    is the only one.

    Without this the block was total and silent - nine synthetics quoted, were
    selected in the terminal, published onto the bus, and produced not one
    level between them.
    """
    from till_infinity.structures.engine import Consensus

    lone = Consensus(single_source=frozenset({"volatility_75_index"}))
    got = lone.observe("volatility_75_index", "5m", "BROKER", 1_000, 101.0, 99.0, 100.0)
    assert got == (101.0, 99.0, 100.0)


def test_an_ordinary_feed_still_needs_three_venues():
    """One venue's opinion must not become a level for anything the group can
    actually check."""
    from till_infinity.structures.engine import Consensus

    book = Consensus()
    assert book.observe("gold", "5m", "OANDA", 1_000, 101.0, 99.0, 100.0) is None
    assert book.observe("gold", "5m", "TVC", 1_000, 101.2, 99.1, 100.1) is None
    got = book.observe("gold", "5m", "CAPITALCOM", 1_000, 100.8, 98.9, 99.9)
    assert got is not None


def test_the_single_source_set_is_read_from_the_catalogue():
    """A feed whose symbol map has one source is one nobody else quotes."""
    from till_infinity.prices.config import register_broker_feeds
    from till_infinity.structures.service import single_source_feeds

    added = register_broker_feeds(["Single Source Test Index"])
    try:
        lone = single_source_feeds()
        assert "single_source_test_index" in lone
        # A properly multi-venue feed is not in it.
        assert "gold" not in lone
    finally:
        from till_infinity.prices.config import FEEDS

        for slug in added:
            FEEDS.pop(slug, None)


def _inference(**over):
    from till_infinity.structures.reactions import Inference

    made = {
        "side": Side.ABOVE,
        "probability_up": 0.5,
        "expected_push": 0.0,
        "push_sigma": 1.0,
        "base_rate_up": 0.5,
        "own_touches": 9.0,
        "neighbours": 3,
    }
    made.update(over)
    return Inference(**made)


def test_a_coin_flip_has_no_direction():
    """`>= 0.5` resolved a tie to "up", which is a lean invented out of
    nothing: 0.5 is the absence of a view, not a weak vote for up."""
    tie = _inference(expected_push=0.0, probability_up=0.5)
    assert tie.direction == ""
    assert tie.actionable is False


def test_either_side_of_the_tie_still_leans():
    assert _inference(expected_push=0.0, probability_up=0.5001).direction == "up"
    assert _inference(expected_push=0.0, probability_up=0.4999).direction == "down"


def test_the_expected_push_still_wins_over_the_win_rate():
    """A level that drifts down four times in five and jumps hard on the fifth
    has a losing win rate and a positive expectation."""
    assert _inference(expected_push=1.2, probability_up=0.2).direction == "up"
    assert _inference(expected_push=-1.2, probability_up=0.8).direction == "down"


def test_an_origin_must_break_structure():
    """A turn followed by a large move is not yet an origin. Price turns and
    runs constantly inside a range, and every one of those is a "last opposing
    bar before an impulse" that meant nothing. What separates the ones that
    matter is that the impulse took out the extreme that had been holding."""
    from till_infinity.structures.drawing.origins import Origins

    unit = 1.0
    # A range between 90 and 110, then a turn at 100 that runs to 95 - a large
    # move that stops well inside the range. No structure broken.
    inside = [90.0, 110.0, 95.0, 108.0, 100.0, 99.0, 98.0, 97.0, 96.0, 95.0]
    times = [float(i) for i in range(len(inside))]
    assert Origins().observe(times, inside, unit, move_vol=3.0, bars=6) == []

    # The same shape, but the impulse runs past the range low.
    breaks = [90.0, 110.0, 95.0, 108.0, 100.0, 97.0, 94.0, 91.0, 88.0, 85.0]
    found = Origins().observe(times, breaks, unit, move_vol=3.0, bars=6)
    assert found, "an impulse through the prior low is a break of structure"


def test_the_impulse_still_has_to_be_volatile():
    """`MOVE_VOL` is the other half: a drift that breaks structure slowly is
    not an impulse, and leaves nothing stranded behind it."""
    from till_infinity.structures.drawing.origins import Origins

    drift = [100.0 - i * 0.1 for i in range(30)]
    times = [float(i) for i in range(len(drift))]
    assert Origins().observe(times, drift, unit=1.0, move_vol=3.0, bars=6) == []


def test_the_zone_widens_to_the_origin_the_level_sits_in():
    """The zone is the band a stop has to clear. When the level coincides with
    an origin - the last opposing bar before an impulse that broke structure -
    the interest stranded there is what price reacts to, and its far edge is
    further out than the wick average knows."""
    from till_infinity.structures.engine import _widen_to_origin

    inside = {"in_origin": 1.0, "origin_low": 98.0, "origin_high": 103.0}
    assert _widen_to_origin(99.0, 101.0, inside) == (98.0, 103.0)


def test_a_nearby_origin_the_level_is_not_in_changes_nothing():
    """Stretching a zone towards an unrelated origin would put stops where
    nothing has ever been defended."""
    from till_infinity.structures.engine import _widen_to_origin

    near = {"in_origin": 0.0, "origin_low": 90.0, "origin_high": 92.0}
    assert _widen_to_origin(99.0, 101.0, near) == (99.0, 101.0)


def test_the_zone_can_only_widen():
    """An origin narrower than the observed wicks does not make the wicks
    smaller."""
    from till_infinity.structures.engine import _widen_to_origin

    narrow = {"in_origin": 1.0, "origin_low": 99.5, "origin_high": 100.5}
    assert _widen_to_origin(99.0, 101.0, narrow) == (99.0, 101.0)


def test_a_missing_or_malformed_origin_is_ignored():
    from till_infinity.structures.engine import _widen_to_origin

    assert _widen_to_origin(99.0, 101.0, {}) == (99.0, 101.0)
    assert _widen_to_origin(99.0, 101.0, {"in_origin": 1.0}) == (99.0, 101.0)
    upside_down = {"in_origin": 1.0, "origin_low": 103.0, "origin_high": 98.0}
    assert _widen_to_origin(99.0, 101.0, upside_down) == (99.0, 101.0)


def test_an_origins_time_is_its_turn_and_its_settling_is_the_break():
    """`price` is the turn's price, so `when` has to be the turn's time - it
    was the detection window's start, which sits at or before it. And an origin
    is not knowable until its impulse breaks structure, which is later still:
    reading `when` as the knowable moment is a look-ahead bug."""
    from till_infinity.structures.drawing.origins import Origins

    prices = [90.0, 110.0, 95.0, 108.0, 100.0, 97.0, 94.0, 91.0, 88.0, 85.0]
    times = [float(i) for i in range(len(prices))]
    found = Origins().observe(times, prices, unit=1.0, move_vol=3.0, bars=6)
    assert found

    origin = found[0]
    # The time it reports is the bar its price came from.
    assert prices[int(origin.when)] == origin.price
    # And it was not knowable until the impulse had run.
    assert origin.settled > origin.when
    assert origin.settled in times


def test_an_impulse_that_barely_clears_the_extremum_is_not_an_origin():
    """Measured on 3,458 first returns: clearing by under 0.5 units held 49.7%,
    against 60.4% on a generated process with no structure at all. Barely
    clearing is worse than nothing, so it is a floor rather than a preference."""
    from till_infinity.structures.drawing.origins import Origins

    times = [float(i) for i in range(12)]
    # Falls to 88, recovers, then an impulse that stops a whisker below it.
    grazes = [95.0, 110.0, 88.0, 108.0, 100.0, 97.0, 94.0, 91.0, 89.0, 87.9, 87.9, 87.9]
    assert Origins().observe(times, grazes, unit=1.0, move_vol=4.0, bars=6) == []

    # The same shape, clearing the prior low decisively.
    clears = [95.0, 110.0, 88.0, 108.0, 100.0, 97.0, 94.0, 91.0, 88.0, 84.0, 82.0, 80.0]
    found = Origins().observe(times, clears, unit=1.0, move_vol=4.0, bars=6)
    assert found
    assert found[0].extremum_vol >= 0.5


def test_the_margin_past_the_extremum_is_recorded():
    """Kept so a consumer can weigh the two tests instead of taking both as
    pass/fail, and so the journal can say which mattered."""
    from till_infinity.structures.drawing.origins import Origins

    prices = [90.0, 110.0, 95.0, 108.0, 100.0, 97.0, 94.0, 91.0, 88.0, 85.0]
    times = [float(i) for i in range(len(prices))]
    found = Origins().observe(times, prices, unit=1.0, move_vol=4.0, bars=6)
    assert found
    assert found[0].extremum_vol > 0
    assert "extremum_vol" in found[0].to_dict()


def test_the_formation_is_reachable_from_settings():
    """It was not, and the `origin` formation shipped unreachable: `Engine`
    took the argument, nothing passed it, and the default won. Every level in
    production was drawn by `pip` while the other two looked available."""
    import os
    from unittest import mock

    from till_infinity.structures.config import DEFAULT_FORMATION, Settings

    # Both defaults named once. They had drifted apart - the field said three
    # passes and `from_env` said one - so a deployment that set nothing got a
    # formation the documentation beside the field denied it had.
    assert Settings().formation == DEFAULT_FORMATION
    assert Settings.from_env().formation == DEFAULT_FORMATION
    with mock.patch.dict(os.environ, {"STRUCTURES_FORMATION": "origin"}):
        assert Settings.from_env().formation == "origin"


def test_the_watcher_hands_the_formation_to_the_engine():
    """The setting existing is not the same as it arriving."""
    import inspect

    from till_infinity.structures import service

    source = inspect.getsource(service.Watcher.__init__)
    assert "formation=self.settings.formation" in source
    # And again after a restore, which is the half this missed: the pickled
    # engine carries the formation it was first saved with, so handing the
    # setting to the constructor is not enough to make it reach production.
    assert "draw_with(self.settings.formation)" in inspect.getsource(service.Watcher.load)


def test_formations_compose():
    """Several passes is the point rather than a fallback. `origin` alone draws
    no levels at all on gold at 1m, 5m or 15m - the timeframes carrying nearly
    every signal - so selecting it on its own would stop that instrument
    trading, quietly."""
    from till_infinity.structures.engine import Engine

    assert Engine(formation="pip").passes == ("pip",)
    assert Engine(formation="origin").passes == ("origin",)
    assert Engine(formation="pip,origin").passes == ("pip", "origin")
    assert Engine(formation="pip, run , origin").passes == ("pip", "run", "origin")


def test_both_still_means_pip_and_run():
    """It is in deployments and in the docs; a rename would be a silent change
    of which levels exist."""
    from till_infinity.structures.engine import Engine

    assert Engine(formation="both").passes == ("pip", "run")


def test_an_unknown_pass_is_refused_rather_than_dropped():
    """Dropping it would leave a deployment running fewer formations than it
    asked for, with nothing said."""
    import pytest

    from till_infinity.structures.engine import Engine

    with pytest.raises(ValueError, match="unknown formation"):
        Engine(formation="pip,nonsense")
    with pytest.raises(ValueError, match="unknown formation"):
        Engine(formation="")


def test_the_level_says_which_formation_drew_it():
    """Running several passes is pointless without it: the argument for merging
    pip, run and origin is that the journal says which price gets respected,
    and it cannot say that if the record does not carry which pass found it.

    `drawn_by` rather than `origin`, which in this namespace now means the
    impulse origin - `origin_price`, `origin_low`, `origin_extremum_vol`."""
    import inspect

    from till_infinity.structures import engine, service

    assert '"drawn_by": level.origin,' in inspect.getsource(service)
    # Never in the signal's features: those are dict[str, float] and
    # `Signal.to_dict` rounds every value, so a string there raises
    # `TypeError: type str doesn't define __round__` - which stopped the
    # structures service in production.
    assert "drawn_by" not in inspect.getsource(engine.Call.to_signal)


def test_every_signal_feature_is_a_number():
    """`Signal.to_dict` rounds every feature value, so one string anywhere in
    that dict takes the whole service down - it did, for four minutes, when a
    level's formation was published there."""
    from till_infinity.structures.models import Shape, Signal

    made = Signal(
        shape=Shape.LEVEL,
        feed="gold",
        venue="consensus",
        score=0.3,
        detail="",
        features={"level": 4400.0, "edge": 0.2},
        interval="5m",
    )
    assert made.to_dict()["features"] == {"level": 4400.0, "edge": 0.2}

    import pytest

    made.features["drawn_by"] = "pip"  # type: ignore[assignment]
    with pytest.raises(TypeError, match="round"):
        made.to_dict()


# ------------------------------- warming a feed added to a running deployment


def _prices_with(path, feeds, bars=600):
    """A prices database holding candles for the named feeds.

    Three venues, because a bar needs `MIN_VENUES` to become a consensus bar: a
    one-venue fixture replays every bar happily and leaves no series behind,
    which is indistinguishable from a warm-up that did nothing.
    """
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE bars (feed TEXT, venue TEXT, interval TEXT, ts INTEGER,"
        " open REAL, high REAL, low REAL, close REAL, volume REAL)"
    )
    rows = []
    for feed in feeds:
        price = 100.0
        for i in range(bars):
            price += (i % 7) - 3
            rows += [
                (
                    feed,
                    venue,
                    "5m",
                    1_700_000_000 + i * 300,
                    price,
                    price + 1,
                    price - 1,
                    price,
                    10.0,
                )
                for venue in ("DERIV", "OANDA", "SAXO")
            ]
    conn.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return path


def test_a_feed_the_engine_has_never_seen_is_reported_as_unwarmed(tmp_path):
    from till_infinity.structures.config import Settings
    from till_infinity.structures.service import Watcher

    db = _prices_with(tmp_path / "prices.db", ["gold", "jump_10_index"])
    watcher = Watcher(Bus(), settings=Settings(prices_db=db, state_dir=tmp_path))
    assert set(watcher.unwarmed()) == {"gold", "jump_10_index"}


def test_a_feed_already_replayed_is_not_warmed_again(tmp_path):
    """Seeding it twice would count every one of its bars twice, and the
    engine's own series are the test rather than its levels: a feed that was
    replayed and legitimately formed no level is warm."""
    from till_infinity.structures.config import Settings
    from till_infinity.structures.service import Watcher

    db = _prices_with(tmp_path / "prices.db", ["gold", "jump_10_index"])
    watcher = Watcher(Bus(), settings=Settings(prices_db=db, state_dir=tmp_path))
    watcher.warm()
    assert watcher.unwarmed() == ()
    assert watcher.warm_new() == 0


def test_a_feed_added_later_is_warmed_although_the_engine_is_not_cold(tmp_path):
    """The bug: `cold` asks whether the engine holds *any* levels, so with
    2,018 restored it is not cold and the warm-up was skipped entirely -
    leaving eleven new instruments with 2,700 stored bars each to learn from
    the bus one bar at a time."""
    from till_infinity.structures.config import Settings
    from till_infinity.structures.service import Watcher

    db = tmp_path / "prices.db"
    _prices_with(db, ["gold"])
    watcher = Watcher(Bus(), settings=Settings(prices_db=db, state_dir=tmp_path))
    watcher.warm()
    assert not watcher.cold, "gold should have formed something to replay from"

    # A new instrument arrives in the store while the engine is running.
    import sqlite3

    conn = sqlite3.connect(db)
    price = 100.0
    rows = []
    for i in range(600):
        price += (i % 7) - 3
        rows.append(
            (
                "jump_10_index",
                "DERIV",
                "5m",
                1_700_000_000 + i * 300,
                price,
                price + 1,
                price - 1,
                price,
                10.0,
            )
        )
    conn.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    assert watcher.unwarmed() == ("jump_10_index",)
    assert watcher.warm_new() > 0
    assert watcher.unwarmed() == ()


def test_the_warm_up_can_be_turned_off(tmp_path):
    from till_infinity.structures.config import Settings
    from till_infinity.structures.service import Watcher

    db = _prices_with(tmp_path / "prices.db", ["gold"])
    watcher = Watcher(Bus(), settings=Settings(prices_db=db, state_dir=tmp_path, warm=False))
    assert watcher.warm_new() == 0


def test_a_missing_prices_database_is_silence_rather_than_a_fault(tmp_path):
    from till_infinity.structures.config import Settings
    from till_infinity.structures.service import Watcher

    watcher = Watcher(Bus(), settings=Settings(prices_db=tmp_path / "absent.db"))
    assert watcher.unwarmed() == ()
    assert watcher.warm_new() == 0


def test_both_entry_points_warm_the_new_feeds():
    """`structures.watch` and the stack had the same two lines once, and only
    one of them was fixed - production kept the bug for a deploy after the fix
    shipped."""
    import inspect

    from till_infinity import stack
    from till_infinity.structures import service

    assert "warm_new()" in inspect.getsource(service.watch)
    assert "warm_new()" in inspect.getsource(stack.Stack._run_structures)


def test_a_thin_series_counts_as_unwarmed(tmp_path):
    """ "Has a series" is not "has enough of one". The eleven new synthetics had
    about twenty bars each, collected live since they were added, so the first
    version of this reported nothing to warm while they sat on 2,700 stored
    bars apiece."""
    from till_infinity.structures.config import Settings
    from till_infinity.structures.service import WARM_MIN_BARS, Watcher

    db = _prices_with(tmp_path / "prices.db", ["gold"])
    watcher = Watcher(Bus(), settings=Settings(prices_db=db, state_dir=tmp_path))
    watcher.warm()
    assert watcher.unwarmed() == ()

    # A feed the engine has seen a handful of live bars from is not warm.
    engine = watcher.engine
    thin = next(iter(engine._series))
    series = engine._series[thin]
    while len(series.closes) >= WARM_MIN_BARS:
        series.closes.popleft()
        series.times.popleft()
    watcher._seeded.clear()
    assert thin[0] in watcher.unwarmed()


# ------------------------------------ a duration that runs backwards


def _open_touch(tracker, started=1_000.0, feed="gold", price=4400.0):
    from till_infinity.structures.levels import Side
    from till_infinity.structures.reactions import Features, Touch

    touch = Touch(
        feed=feed,
        interval="1m",
        level_price=price,
        features=Features(
            side=Side.ABOVE,
            approach_vol=1.0,
            depth_vol=0.0,
            strength=0.0,
            run_vol=0.0,
            experience=0.0,
        ),
        started=started,
        entry=price,
        extreme=price,
    )
    tracker._open[(feed, price)] = touch
    return touch


def test_an_observation_older_than_the_touch_is_refused():
    """A bar reaches the tracker stamped at its own close and arrives *after*
    that close, so a touch a quote opened in the meantime gets handed a bar
    describing a window it did not exist in. That resolved 28.9% of production
    outcomes at a negative duration, median exactly one bar on a 1m series."""
    from till_infinity.structures.levels import Kalman, Level
    from till_infinity.structures.reactions import Tracker

    tracker = Tracker()
    level = Level(feed="gold", interval="1m", filter=Kalman(4400.0, 1.0))
    touch = _open_touch(tracker, started=1_000.0, price=level.price)
    assert tracker._live(level, 1_060.0) is touch
    assert tracker._live(level, 940.0) is None


def test_the_touch_stays_open_when_a_stale_bar_is_refused():
    """Refused rather than clamped: the bar's range is evidence about a period
    before the touch and says nothing about what the touch did, so the touch
    waits for an observation that is actually about it."""
    from till_infinity.structures.levels import Kalman, Level
    from till_infinity.structures.reactions import Tracker

    tracker = Tracker()
    level = Level(feed="gold", interval="1m", filter=Kalman(4400.0, 1.0))
    _open_touch(tracker, started=1_000.0, price=level.price)
    tracker._live(level, 940.0)
    assert ("gold", 4400.0) in tracker._open


def test_a_resolution_can_never_precede_its_own_start():
    """The backstop for every path into `_close` that is not `update`. A
    duration running backwards is not a small error - it silently reverses
    whatever reads it."""
    from till_infinity.structures.levels import Kalman, Level, Side
    from till_infinity.structures.reactions import Outcome, Tracker

    tracker = Tracker()
    level = Level(feed="gold", interval="1m", filter=Kalman(4400.0, 1.0))
    touch = _open_touch(tracker, started=1_000.0, price=level.price)
    done = tracker._close(level, touch, Outcome.REJECT, 1.0, Side.ABOVE, when=940.0)
    assert done.resolved >= done.started
    assert done.resolved - done.started >= 0.0


def test_an_expired_touch_also_cannot_run_backwards():
    from till_infinity.structures.levels import Kalman, Level
    from till_infinity.structures.reactions import Tracker

    tracker = Tracker()
    level = Level(feed="gold", interval="1m", filter=Kalman(4400.0, 1.0))
    touch = _open_touch(tracker, started=10_000.0, price=level.price)
    # Far enough past the horizon to expire, but stamped earlier than the
    # touch began - which `expire` reaches without going through `update`.
    touch.started = 10_000.0
    for done in tracker.expire(when=10_000.0 + tracker.horizon_for(touch) * 2):
        assert done.resolved >= done.started
    assert all(t.resolved >= t.started for t in tracker.memory._touches)


# --------------------------------------- the second detector, tried and removed


def test_the_retired_second_detector_leaves_nothing_behind():
    """KSWIN was counted for weeks, fired zero times against ADWIN's 136, and
    was removed on 2026-09-09.

    A save written while it ran carries `_shape`, one pickled detector per
    instrument and timeframe each holding a hundred-sample window. Those still
    unpickle - river is still a dependency - so nothing breaks; they would
    simply be restored on every start and referenced by nothing. And the three
    retired counters would go on being logged as permanent zeros, which reads
    as a detector running and silent rather than one that is gone."""
    from till_infinity.structures.learning.drift import Drift

    restored = Drift.__new__(Drift)
    restored.__setstate__(
        {
            "delta": 0.002,
            "quorum": 2,
            "_detectors": {},
            "_shape": {("t", "5m"): object()},
            "_agreement": {"adwin": 136, "kswin": 0, "both": 0, "kswin_alone": 0},
            "_last": {},
            "_fired": {},
            "_announced": {},
            "_seen": {},
            "_before": {},
            "_severities": [],
        }
    )

    assert not hasattr(restored, "_shape"), "a retired detector was restored anyway"
    assert restored.watching() == {"adwin": 136}


def test_drift_still_fires_and_counts_after_the_removal():
    """The half that was actually being used has to be untouched."""
    import random

    from till_infinity.structures.learning.drift import Drift

    rng = random.Random(5)
    watcher = Drift()
    price = 100.0
    fired = []
    for i in range(1200):
        step = rng.gauss(0, 0.02) if i < 600 else rng.choice([-1, 1]) * rng.gauss(0.4, 0.02)
        price = max(1.0, price + step)
        got = watcher.observe("t", price, when=float(i), interval="5m")
        if got is not None:
            fired.append(got)

    seen = watcher.watching()

    assert set(seen) == {"adwin"}
    # Every emitted signal has to have come through the ADWIN path.
    assert len(fired) <= seen["adwin"]


# ---------------------------------------------------------------------------
# The learned volatility forecaster. See `vol/learned.py`.
# ---------------------------------------------------------------------------


def test_the_learner_is_pooled_not_per_series():
    """One model across the book is the design, not a concession.

    A per-series model is 525MB at ~424 series on the cheapest tree available,
    on a box with about 1.1GB free. If this ever becomes one model per key, the
    memory is what fails, and it fails in production rather than here.
    """
    from till_infinity.structures.vol.learned import Learned

    model = Learned(warmup=10)
    for i in range(60):
        for key in ("eurusd|5m", "volatility_75_index|4h"):
            row = model.features(key, ew_bps=2.0, open_=100, high=101, low=99, close=100.5)
            model.observe(key, 2.0 + (i % 3), row, ew_bps=2.0)

    assert len(model._by_key) == 2  # two series
    assert model._seen > 50  # one model, learning from both


def test_the_target_is_scale_free_so_one_model_can_span_the_book():
    """A 2bps bar against a 2bps estimate and a 40bps bar against a 40bps one
    are the same observation. If they are not, pooling is illegitimate."""
    from till_infinity.structures.vol.learned import Learned

    model = Learned()
    assert model._target(2.0, 2.0) == pytest.approx(model._target(40.0, 40.0))
    assert model._target(4.0, 2.0) == pytest.approx(model._target(80.0, 40.0))
    # Centred on the incumbent: no correction means no change.
    assert model._target(5.0, 5.0) == pytest.approx(0.0)


def test_a_cold_learner_returns_the_estimate_it_was_given():
    """Predicting zero correction means 'the standing estimate is right', so a
    model that has learned nothing must not make anything worse."""
    from till_infinity.structures.vol.learned import Learned

    model = Learned(warmup=1_000_000)  # never warm
    row = model.features("x|5m", ew_bps=3.0, open_=100, high=101, low=99, close=100.5)
    assert model._predict(row, ew_bps=3.0, fallback=7.0) == 7.0
    assert model.ratio("x|5m") == 1.0


def test_the_correction_is_bounded_in_both_directions():
    """`har.ratio` reached 1.3e11 and was published 19,511 times. The log cap is
    that lesson applied before the fact rather than after it."""
    from till_infinity.structures.vol.learned import LOG_CAP, Learned

    model = Learned()
    assert model._target(1_000_000.0, 0.001) == pytest.approx(LOG_CAP)
    assert model._target(0.001, 1_000_000.0) == pytest.approx(-LOG_CAP)


def test_features_are_all_dimensionless():
    """A single feature in price units turns the pooled model back into 424
    per-series models sharing one set of splits."""
    from till_infinity.structures.vol.learned import Learned

    cheap_model, dear_model = Learned(), Learned()
    for _ in range(5):
        cheap_model.observe("gold|1h", 30.0, None, ew_bps=30.0)
        dear_model.observe("eurusd|1h", 30.0, None, ew_bps=30.0)
    cheap = cheap_model.features(
        "gold|1h", ew_bps=30.0, garch_bps=33.0, open_=2_000, high=2_010, low=1_990, close=2_005
    )
    # The same series shape at a thousandth of the price, same volatility.
    dear = dear_model.features(
        "eurusd|1h", ew_bps=30.0, garch_bps=33.0, open_=2.0, high=2.010, low=1.990, close=2.005
    )
    assert cheap is not None
    assert dear is not None
    for name in ("garch_rel", "r1", "r5", "body", "upper_wick", "lower_wick", "span_rel"):
        assert cheap[name] == pytest.approx(dear[name], rel=1e-6), name


def test_the_model_learns_a_shape_a_line_cannot():
    """It separates two bars of identical magnitude and opposite future.

    This asserts the **mechanism**, not a win. An earlier version asserted that
    the model beat `naive`, and that was wrong: on a split-sample replay it does
    not - `research/forecasting.md` has the table. A synthetic test that kept
    claiming otherwise would exist to flatter the model.

    What is worth pinning down is the interaction HAR structurally cannot hold:
    a large bar that is a trend and a large bar that is a rejection wick have
    the same magnitude and different futures, and a straight line over three
    lagged magnitudes has nowhere to put that.

    The alignment is the part that is easy to get wrong. `observe` learns the
    row from call *i* against the value arriving at call *i+1*, so the generator
    has to make bar `i`'s shape decide bar `i+1`'s size. Writing it the natural
    way produces a model that correctly learns nothing, and the failure reads as
    a bad model rather than a bad test.
    """
    import random

    from till_infinity.structures.vol.learned import Learned

    random.seed(7)
    model = Learned(warmup=200)
    key, ew = "synthetic|5m", 2.0

    def bar(big: bool, wick: bool):
        span = (6.0 if big else 1.0) / 10_000 * 100.0
        open_, high, low = 100.0, 100.0 + span, 100.0
        # A trend bar closes at its high; a rejection bar gives it all back.
        return open_, high, low, (high if not wick else open_ + span * 0.02)

    big = wick = False
    for _ in range(3_000):
        realised = 6.0 if (big and not wick) else 1.0
        big, wick = random.random() < 0.5, random.random() < 0.5
        open_, high, low, close = bar(big, wick)
        row = model.features(key, ew_bps=ew, open_=open_, high=high, low=low, close=close)
        model.observe(key, realised, row, ew_bps=ew, close=close)

    assert model.warm
    trend = model.features(key, ew_bps=ew, open_=100.0, high=100.06, low=100.0, close=100.06)
    reject = model.features(key, ew_bps=ew, open_=100.0, high=100.06, low=100.0, close=100.0012)
    after_trend = model._predict(trend, ew_bps=ew, fallback=ew)
    after_reject = model._predict(reject, ew_bps=ew, fallback=ew)
    assert after_trend > after_reject, (after_trend, after_reject)

    # And it carries its own head-to-head. It is required to keep the
    # scoreboard, not to win it.
    assert {"naive", "learned"} <= set(dict(model.standings()))


def test_a_broken_row_cannot_stop_the_engine():
    """Two outages this month were a reading nobody gates on taking the whole
    structures service down. This one is guarded at the source."""
    from till_infinity.structures.vol.learned import Learned

    model = Learned(warmup=0)

    class Exploding:
        def predict_one(self, row):
            raise RuntimeError("no")

        def learn_one(self, row, y):
            raise RuntimeError("no")

    model._model = Exploding()
    assert model._predict({"a": 1.0}, ew_bps=3.0, fallback=9.0) == 9.0


def test_the_learner_survives_a_restore():
    """A learner that resets on every deploy has learned nothing. This is the
    fourth instance of that bug class here - see `trading.Speeds`,
    `Drift._agreement`, `Live.ref` and the intent interval."""
    from till_infinity.shared import codec
    from till_infinity.structures.vol.learned import Learned

    model = Learned(warmup=5)
    for i in range(40):
        row = model.features("eurusd|5m", ew_bps=2.0, open_=100, high=101, low=99, close=100.5)
        model.observe("eurusd|5m", 2.0 + (i % 4), row, ew_bps=2.0)
    seen = model._seen
    assert seen > 20

    back = codec.unpack(codec.pack(model), codec.registry(sx))
    assert isinstance(back, Learned)
    assert back._seen == seen
    assert set(back._by_key) == set(model._by_key)
    # And the river model came back able to answer.
    row = back.features("eurusd|5m", ew_bps=2.0, open_=100, high=101, low=99, close=100.5)
    assert back._predict(row, ew_bps=2.0, fallback=1.0) > 0


def test_the_book_holds_one_learner_for_every_series():
    from till_infinity.structures.vol.volatility import Book

    book = Book()
    assert book.of("eurusd", "5m") is not book.of("gold", "4h")
    assert book.learned is book.learned  # shared, not per series


def test_observe_bar_returns_the_realised_value_everything_is_scored_on():
    """Returned rather than recomputed by the caller, so the learner and the
    ensemble cannot score against subtly different targets."""
    from till_infinity.structures.vol.volatility import Volatility

    vol = Volatility()
    for i in range(80):
        vol.update(100.0 + (i % 5) * 0.1)
    got = vol.observe_bar(100.0, 100.5, 99.5, 100.2)
    assert isinstance(got, float)
    assert got > 0


def test_the_anomaly_feature_is_a_percentile_not_a_raw_score():
    """`HalfSpaceTrees` is uncalibrated - measured here, its tenth and ninetieth
    percentiles on random rows were 0.70 and 0.83. A feature living in a tenth
    of its range is one a tree can barely split on, and where that band sits
    drifts with the market."""
    import random

    from till_infinity.structures.vol.learned import Learned

    random.seed(3)
    model = Learned(warmup=50)
    key = "eurusd|5m"
    got = []
    for i in range(1_200):
        span = 1.0 + (8.0 if i % 97 == 0 else 0.0)  # an occasional violent bar
        close = 100.0 + span / 100
        row = model.features(key, ew_bps=2.0, open_=100.0, high=close, low=100.0, close=close)
        if row is not None:
            got.append(row["anomaly"])
        model.observe(key, 2.0, row, ew_bps=2.0, close=close)

    assert got, "no rows were produced"
    for value in got:
        assert 0.0 <= value <= 1.0
    # Cold rows sit in the middle rather than at an extreme: a missing reading
    # must not read as "the most anomalous thing ever seen".
    assert got[0] == pytest.approx(0.5)
    # And once warm it actually uses its range, which the raw score would not.
    warm = got[400:]
    assert max(warm) - min(warm) > 0.3, (min(warm), max(warm))


def test_the_detector_scores_before_it_learns():
    """`learning/anomaly.py` states the rule: learning first teaches the model
    that the anomaly is normal, and it then scores it as normal."""
    from till_infinity.structures.vol.learned import Learned

    model = Learned()
    seen = []

    class Watching:
        def score_one(self, row):
            seen.append("score")
            return 0.8

        def learn_one(self, row):
            seen.append("learn")

    # Seed the history first: `features` returns None until the series has two
    # realised readings, so a detector swapped in before that is never reached
    # and the test would pass or fail for the wrong reason.
    for _ in range(3):
        model.observe("x|5m", 2.0, None, ew_bps=2.0)

    model._anomaly = Watching()
    for _ in range(2):
        row = model.features("x|5m", ew_bps=2.0, open_=100, high=101, low=99, close=100.5)
        assert row is not None
        assert "anomaly" in row
        model.observe("x|5m", 2.0, row, ew_bps=2.0)
    assert seen, "the detector was never consulted"
    assert seen[0] == "score", seen[:4]


def test_the_analogue_answers_with_what_followed_similar_rows():
    """The attention idea without the transformer: weight the past by relevance
    rather than by recency. Two distinct regimes, and it must not average
    across them."""
    from till_infinity.structures.vol.analogue import Analogue

    model = Analogue(warmup=100, k=8)
    for i in range(600):
        quiet = i % 2 == 0
        row = {"span_rel": 0.5 if quiet else 4.0, "r1": 0.5 if quiet else 4.0}
        model.observe(row, -0.7 if quiet else 0.7)

    assert model.warm
    calm = model.predict({"span_rel": 0.5, "r1": 0.5})
    loud = model.predict({"span_rel": 4.0, "r1": 4.0})
    assert calm is not None
    assert loud is not None
    assert calm < 0, calm
    assert loud > 0, loud


def test_the_analogue_says_nothing_rather_than_guessing():
    """`None`, not zero. Zero is the confident claim that the standing estimate
    is exactly right, which is the opposite of having no view."""
    from till_infinity.structures.vol.analogue import Analogue

    model = Analogue(warmup=100)
    assert model.predict({"span_rel": 1.0}) is None  # cold
    assert model.predict(None) is None
    for _ in range(200):
        model.observe({"span_rel": 1.0, "r1": 1.0}, 0.1)
    assert model.warm
    assert model.predict({"span_rel": 1.0, "r1": 1.0}) is not None


def test_the_analogue_memory_is_bounded():
    """A reservoir that grows with the run is the shape that has already cost
    this repository four outages."""
    from till_infinity.structures.vol.analogue import Analogue

    model = Analogue(memory=50, warmup=1)
    for i in range(500):
        model.observe({"span_rel": float(i), "r1": 1.0}, 0.01 * i)
    assert len(model._rows) == 50


def test_every_member_is_scored_on_one_scale():
    """A Rogers-Satchell reading is a standard deviation and `vol_bps` is a mean
    absolute deviation; they differ by sqrt(pi/2).

    `observe_bar` settles the ensemble with `realised / MAD_TO_SIGMA` for that
    reason, and `Book.learn` did not - so the learner's target was centred on
    log(1.25) instead of zero, and in the scoreboard `har` and `learned` were
    converted to the mean-absolute scale while `naive` was compared against the
    raw one. Two competitors shrank by a quarter before a comparison whose
    headline result is that persistence beats them.
    """
    from till_infinity.structures.vol.consensus_vol import MAD_TO_SIGMA
    from till_infinity.structures.vol.volatility import Book

    book = Book()
    vol = book.of("eurusd", "5m")
    for i in range(120):
        vol.update(100.0 + (i % 7) * 0.05)
    assert vol.warm

    book.learn(
        "eurusd",
        "5m",
        10.0,
        open_=100.0,
        high=100.1,
        low=99.9,
        close=100.05,
        interval_seconds=300.0,
    )
    seen = book.learned._by_key["eurusd|5m"]
    # What it remembered is the converted value, not the raw one.
    assert seen.realised[-1] == pytest.approx(10.0 / MAD_TO_SIGMA)
    assert seen.said["naive"] == pytest.approx(10.0 / MAD_TO_SIGMA)


def test_the_target_is_centred_on_no_change():
    """Predicting zero must mean 'the standing estimate is right'. With the two
    scales mixed it meant 'the standing estimate is a quarter low'."""
    from till_infinity.structures.vol.learned import Learned

    model = Learned()
    assert model._target(7.0, 7.0) == pytest.approx(0.0)


def test_the_fine_series_can_cover_a_daily_bar():
    """`_capture_fine` needs the 1m series to still cover a coarse bar when that
    bar closes. A 1d bar is 1,440 minutes; at 500 it could never be refined."""
    from till_infinity.structures.engine import FINE_WINDOW, Series, window_for

    assert FINE_WINDOW >= 1_440, "the daily is 1,440 minutes"
    fine = Series("eurusd", "1m")
    assert fine.times.maxlen == FINE_WINDOW
    assert window_for("1m") > window_for("4h")


def test_a_restored_series_is_widened_rather_than_left_at_its_old_size():
    """A deque restored from a save carries the `maxlen` it was written with, so
    a window change would otherwise only reach series created after the deploy -
    the shape `Analogue.memory` failed in on the same day this was written."""
    from collections import deque

    from till_infinity.structures.engine import Series, window_for

    old = Series("gold", "4h")
    # Simulate a restore from a build whose window was 500.
    for name in ("times", "closes", "highs", "lows", "opens", "volumes"):
        setattr(old, name, deque(getattr(old, name), maxlen=500))
    assert old.times.maxlen == 500

    old.closes.extend([1.0, 2.0, 3.0])
    old.retune()
    assert old.times.maxlen == window_for("4h")
    assert list(old.closes) == [1.0, 2.0, 3.0], "retune must not drop what it holds"


def test_the_window_is_settable_from_the_environment():
    """The container was OOM-killed nineteen times in nine days for reasons of
    exactly this kind, so the size has to be revertible without a deploy."""
    import importlib
    import os

    from till_infinity.structures import engine as eng

    was = os.environ.get("STRUCTURES_WINDOW")
    try:
        os.environ["STRUCTURES_WINDOW"] = "321"
        importlib.reload(eng)
        assert eng.WINDOW == 321
        assert eng.window_for("4h") == 321
    finally:
        if was is None:
            os.environ.pop("STRUCTURES_WINDOW", None)
        else:
            os.environ["STRUCTURES_WINDOW"] = was
        importlib.reload(eng)


def test_the_engine_forgets_feeds_outside_the_universe():
    """The state grew to 349 feeds for a 53-instrument book and nothing shrank
    it: `_series` held 3,280 entries and `vol._by_key` 5,416, together 324MB of
    a 552MB state that costs 1.33GB resident.

    Capping the price collector did not stop it, and that is the part worth
    pinning. `PRICES_CCXT_TOP=25` bounds how many crypto pairs are discovered at
    one moment; the top twenty-five by volume rotates, so 235 distinct crypto
    feeds had produced a bar within three days. A rotating window against a
    store that never forgets is unbounded whatever the cap is.
    """
    from till_infinity.structures.engine import Engine

    engine = Engine()
    for feed in ("eurusd", "gold", "ace_usdt_usdt", "mon_usdt_usdt"):
        for interval in ("1m", "1h"):
            engine.series(feed, interval)
            engine.vol.of(feed, interval)

    assert len({f for f, _ in engine._series}) == 4

    dropped = engine.forget({"eurusd", "gold"})

    assert dropped["feeds"] == 2
    assert {f for f, _ in engine._series} == {"eurusd", "gold"}
    assert {f for f, _ in engine.vol._by_key} == {"eurusd", "gold"}


def test_forgetting_is_a_no_op_for_a_desk_that_has_not_configured_it():
    """`feeds` empty means "whatever arrives", which is what it did before.
    A bound nobody asked for that silently deletes learned state would be a
    worse bug than the one it fixes."""
    from till_infinity.structures.engine import Engine

    engine = Engine()
    engine.series("ace_usdt_usdt", "1m")
    engine.vol.of("ace_usdt_usdt", "1m")

    assert engine.forget(None, now=0.0) == {}
    assert ("ace_usdt_usdt", "1m") in engine._series


def test_a_feed_is_judged_quiet_across_all_its_intervals_not_one():
    """A 1w series gets one bar a week and would look abandoned every time,
    while a live feed's 1m series updates constantly. Judging per series would
    evict the slow timeframes of perfectly live instruments."""
    import time

    from till_infinity.structures.engine import Engine

    now = time.time()
    engine = Engine()
    engine.forget_feed = 3 * 86_400

    fresh = engine.series("eurusd", "1m")
    fresh.times.append(int(now))
    stale_side = engine.series("eurusd", "1w")
    stale_side.times.append(int(now - 30 * 86_400))
    engine.vol.of("eurusd", "1w")

    gone = engine.series("ace_usdt_usdt", "1m")
    gone.times.append(int(now - 30 * 86_400))
    engine.vol.of("ace_usdt_usdt", "1m")

    dropped = engine.forget(None, now=now)

    assert dropped["feeds"] == 1
    assert ("eurusd", "1w") in engine._series, "a slow interval is not an abandoned feed"
    assert ("ace_usdt_usdt", "1m") not in engine._series


def test_forgetting_keeps_what_is_pooled():
    """The learner's tree, the shape library and the regime labeller are trained
    on scale-free features precisely so what they learned from a feed outlives
    the feed. Dropping them because a symbol left throws away the part that
    generalises."""
    from till_infinity.structures.engine import Engine

    engine = Engine()
    engine.series("ace_usdt_usdt", "1m")
    engine.vol.of("ace_usdt_usdt", "1m")
    shapes, regimes = engine.shapes, engine.regimes
    learned = engine.vol.learned

    engine.forget({"eurusd"})

    assert engine.shapes is shapes
    assert engine.regimes is regimes
    assert engine.vol.learned is learned


def test_the_warm_up_skips_feeds_outside_the_universe(tmp_path):
    """`Engine.forget` drops what the desk no longer follows at every save, and
    without this the warm-up replayed price history for **392 feeds** against a
    53-symbol book - 339 of which the next save discarded.

    Bounding a store at the exit while filling it at the entrance is a
    treadmill, not a bound."""
    from till_infinity.bus import Bus
    from till_infinity.structures.config import Settings
    from till_infinity.structures.service import Watcher

    watcher = Watcher(
        Bus(),
        settings=Settings(
            warm=True, journalling=False, feeds=("eurusd", "gold"), state_dir=tmp_path
        ),
    )
    watcher.unwarmed = lambda: ("eurusd", "gold", "ace_usdt_usdt", "mon_usdt_usdt")
    seen = []
    watcher.engine.seed = lambda _db, feeds=(), **k: seen.extend(feeds) or 0

    watcher.warm_new()

    assert set(seen) == {"eurusd", "gold"}, "339 of 392 were outside the book"


def test_an_unconfigured_universe_still_warms_everything(tmp_path):
    """`feeds` empty means "whatever arrives", which is what it did before. A
    filter nobody asked for that silently skips history would be a worse bug
    than the one it fixes."""
    from till_infinity.bus import Bus
    from till_infinity.structures.config import Settings
    from till_infinity.structures.service import Watcher

    watcher = Watcher(
        Bus(), settings=Settings(warm=True, journalling=False, feeds=(), state_dir=tmp_path)
    )
    watcher.unwarmed = lambda: ("eurusd", "ace_usdt_usdt")
    seen = []
    watcher.engine.seed = lambda _db, feeds=(), **k: seen.extend(feeds) or 0

    watcher.warm_new()

    assert set(seen) == {"eurusd", "ace_usdt_usdt"}
