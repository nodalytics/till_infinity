"""The online layer: cross-venue features, detection, routing and persistence.

The detector is stochastic, so the tests that matter are behavioural — does a
stale feed get caught, does a quiet market stay quiet — rather than assertions
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
from till_infinity.structures.models import Shape, Signal
from till_infinity.structures.service import BarConsensus, Watcher

VENUES = ("OANDA", "PEPPERSTONE", "FOREXCOM", "SAXO", "FXPRO", "TVC")


def quote(venue, mid, bps=0.3, when=1_000.0, feed="gold"):
    return {"feed": feed, "venue": venue, "mid": mid, "spread_bps": bps, "time": when}


# ----------------------------------------------------- cross-venue features


def test_a_venue_is_never_part_of_its_own_consensus():
    """Including it is how a bad feed hides — it drags the number it is judged by."""
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


def test_a_calm_series_never_reports_drift():
    detector, mid, rand = Drift(), 4400.0, random.Random(3)
    fired = []
    for i in range(600):
        mid *= 1 + rand.gauss(0, 0.00002)
        found = detector.observe("gold", mid, float(i))
        if found:
            fired.append(found)
    assert fired == []


def test_a_volatility_regime_change_is_reported():
    detector, mid, rand = Drift(), 4400.0, random.Random(3)
    for i in range(600):
        mid *= 1 + rand.gauss(0, 0.00002)
        detector.observe("gold", mid, float(i))
    found = None
    for i in range(600, 1200):
        mid *= 1 + rand.gauss(0, 0.0006)
        found = detector.observe("gold", mid, float(i))
        if found:
            break
    assert found is not None
    assert found.shape is Shape.DRIFT
    assert found.venue == "consensus"


def test_the_first_reading_cannot_be_a_return():
    assert Drift().observe("gold", 4400.0) is None


# ------------------------------------------------------------ bar consensus


def bar(venue, close, ts=60, interval="5m"):
    return {"feed": "gold", "venue": venue, "interval": interval, "close": close, "time": ts}


def test_bars_need_several_venues_before_they_mean_anything():
    consensus = BarConsensus()
    assert consensus.observe(bar("OANDA", 4400.0)) is None
    assert consensus.observe(bar("SAXO", 4401.0)) is None
    assert consensus.observe(bar("TVC", 4402.0)) == ("gold", 4401.0)


def test_only_venues_on_the_same_bar_are_blended():
    """Otherwise the median mixes different minutes and invents a move."""
    consensus = BarConsensus()
    for venue in ("OANDA", "SAXO", "TVC"):
        consensus.observe(bar(venue, 4400.0, ts=60))
    assert consensus.observe(bar("OANDA", 5000.0, ts=120)) is None


def test_slow_intervals_are_ignored():
    """Above five minutes, disagreement is bar boundaries, not opinions."""
    consensus = BarConsensus()
    for venue in VENUES[:4]:
        assert consensus.observe(bar(venue, 4400.0, interval="1h")) is None


# ------------------------------------------------------------------ routing


def _signal(shape=Shape.SPREAD, score=1.0, **features):
    return Signal(
        shape=shape, feed="gold", venue="OANDA", score=score, detail="d", features=features
    )


def test_a_stale_feed_goes_straight_to_a_human():
    watcher = Watcher(Bus(), settings=sx.Settings())
    assert watcher.direct(_signal(Shape.STALE))


def test_a_rare_spread_waits_for_an_agent():
    """Rarity is not unambiguity — a wide spread may well have a release behind it."""
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
