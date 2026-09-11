"""VIX as a scored member of the volatility ensemble.

`implied.md` is the only positive result in the research folder: over 15 years,
walk-forward, VIX beats a trailing realised estimate by 12-20 points of
R-squared and the naive baseline by +0.26 to +0.43. Its sharpest finding is that
`both` is no better than `vix` alone - VIX **replaces** the historical estimate
rather than adding to it, which is why this is a member of the ensemble rather
than a multiplier bolted on the side.
"""

import math

import pytest

from till_infinity.structures.vol import implied as implied_module
from till_infinity.structures.vol.implied import (
    IMPLIED_FEEDS,
    IMPLIED_INTERVALS,
    Implied,
    bps_for,
)
from till_infinity.structures.vol.volatility import Book


@pytest.fixture
def enabled(monkeypatch):
    """The member ships **off** - `vixseed` measured it last of five on half the
    series - so the tests that exercise it turn it on explicitly."""
    monkeypatch.setattr(implied_module, "ENABLED", True)
    monkeypatch.setattr("till_infinity.structures.vol.volatility.ENABLED", True)


def test_the_conversion_is_what_it_claims_to_be():
    """VIX 20 is 20% annualised sigma. At one day that is 20/sqrt(252) percent,
    which is 1.2599% - 125.99 bps - with no intraday assumption at all.

    Written out rather than recorded from a run: root-time scaling from an
    annualised 30-day number is a modelling assumption even here, and the thing
    most likely to be silently backwards.
    """
    got = bps_for(20.0, "1d")

    by_hand = 20.0 / math.sqrt(252.0) * 100.0  # percent -> bps
    assert by_hand == pytest.approx(125.99, abs=0.01)
    assert got == pytest.approx(by_hand, abs=0.01)

    # A week is five trading days, so the same reading scales by sqrt(5).
    assert bps_for(20.0, "1w") == pytest.approx(by_hand * math.sqrt(5.0), abs=0.1)


def test_a_stale_reading_is_absent_rather_than_carried():
    """If the feed dies the last value keeps voting with full confidence on
    every subsequent bar. Absent from the mapping is what the ensemble already
    handles - members are whatever `observe` was given."""
    held = Implied(max_age=86_400.0)
    held.observe(20.0, when=1000.0)

    assert held.bps("1d", now=1000.0) is not None
    assert held.bps("1d", now=1000.0 + 3_600) is not None
    assert held.bps("1d", now=1000.0 + 200_000) is None, "two days old and still voting"


def test_it_joins_only_the_feeds_and_intervals_it_was_measured_on(enabled):
    """VIX is a 30-day view published daily. Scaling it to a 1m bar assumes a
    flat term structure and no intraday seasonality, and the intraday U-shape is
    large and real - so the scope is a property to assert, not a convention to
    remember."""
    book = Book()
    book.implied.observe(20.0, when=1000.0)

    for interval in ("1m", "5m", "15m", "1h", "4h"):
        assert book.implied_bps("spx500", interval, now=1000.0) is None

    for interval in IMPLIED_INTERVALS:
        assert book.implied_bps("spx500", interval, now=1000.0) is not None

    # And only the four indices it was measured on.
    assert book.implied_bps("eurusd", "1d", now=1000.0) is None
    assert book.implied_bps("volatility_75_index", "1d", now=1000.0) is None
    for feed in IMPLIED_FEEDS:
        assert book.implied_bps(feed, "1d", now=1000.0) is not None


def test_weighting_is_on_only_where_vix_votes(enabled):
    """`Ensemble` is per `(feed, interval)`, so error-weighting can be turned on
    for the instances VIX joins without touching the other 49 instruments. That
    blast radius is the thing most likely to be got wrong, so it is asserted
    across a book holding both."""
    book = Book()
    book.implied.observe(20.0, when=1000.0)

    for feed in ("spx500", "eurusd", "volatility_75_index"):
        for interval in ("1m", "1d", "1w"):
            book.of(feed, interval)

    for feed in ("spx500",):
        for interval in IMPLIED_INTERVALS:
            assert book.of(feed, interval)._ensemble.weighted is True

    assert book.of("spx500", "1m")._ensemble.weighted is False
    assert book.of("eurusd", "1d")._ensemble.weighted is False
    assert book.of("volatility_75_index", "1w")._ensemble.weighted is False


def test_the_member_reaches_the_ensemble_and_is_scored(enabled):
    """The whole point of this shape: it is scored against what the bar actually
    did, so a member that is wrong loses its vote without anyone intervening."""
    book = Book()
    book.implied.observe(20.0, when=1000.0)
    vol = book.of("spx500", "1d")

    for i in range(5):
        book.observe_bar("spx500", "1d", 100.0, 101.0, 99.0, 100.5, when=1000.0 + i)

    assert "vix" in vol._ensemble._members, "it has to reach the members mapping"
    # Scored against what the bar actually did, which is the whole argument for
    # this shape. `standings()` lists only *warm* members and SCORE_WARMUP is
    # 60, so five bars is correctly absent from it - being scored and having
    # earned a vote are different things, and that distinction is why the warm
    # start exists.
    assert vol._ensemble._score("vix").seen > 0
    assert dict(vol._ensemble.standings()) == {}, "five bars has not earned a vote"


def test_a_seeded_score_is_a_prior_and_not_a_floor():
    """`SCORE_WARMUP` is 60, which at daily bars is three months before VIX earns
    any weight - so the scores are seeded from history. A seed the live
    observations contradict has to be able to lose."""
    from till_infinity.structures.vol.consensus_vol import Ensemble

    held = Ensemble(weighted=True)
    held.seed("vix", error=0.05, seen=200.0)
    assert held.accuracy("vix") == pytest.approx(0.95, abs=0.01)

    # Consistently wrong from here: the seeded accuracy has to decay.
    for _ in range(400):
        held.observe({"vix": 100.0})
        held.settle(1.0)
    assert held.accuracy("vix") < 0.5, "a seed that is wrong must be able to lose"


def test_it_ships_off():
    """`vixseed` scored it **last of five** on spx500 and us30 at both intervals,
    with `har` winning everywhere. A member seeded with a weight it has not
    earned is exactly the failure `consensus_vol` exists to prevent - nothing
    may be combined before it can be scored - so the default is off and the
    reason is in `implied.py`."""
    assert implied_module.ENABLED is False

    book = Book()
    book.implied.observe(20.0, when=1000.0)
    assert book.implied_bps("spx500", "1d", now=1000.0) is None
    assert book.of("spx500", "1d")._ensemble.weighted is False
